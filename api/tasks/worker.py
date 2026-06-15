"""
Background worker — runs the Bank Statement Agent for a task,
pushes SSE events, updates Postgres + Redis cache.
"""

import asyncio
import logging
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine

from api.fileserver import upload_xlsx
from api.ratelimit import GlobalRPMLimiter
from api.sse import publish
from api.tasks.state import update_task_status
from agent.main import BankStatementAgent

logger = logging.getLogger(__name__)

# State is driven by tool call descriptions, not raw token text, to avoid
# false positives from ordinary English words in the model's reasoning.
_TOOL_STATE_SIGNALS = {
    "extracting": ["extract", "parse", "transaction", "parsing"],
    "verifying":  ["verif", "level 1", "level 2", "l1", "l2", "balance"],
    "exporting":  ["export", "openpyxl", "workbook", "xlsx", "write excel"],
}


def _detect_state_from_tool(desc: str) -> str | None:
    lower = desc.lower()
    for state, keywords in _TOOL_STATE_SIGNALS.items():
        if any(kw in lower for kw in keywords):
            return state
    return None


async def run_task(
    task_id: str,
    pdf_path: str,
    xlsx_path: str,
    book_id: str,
    task_name: str,
    db: AsyncEngine,
    redis: aioredis.Redis,
    rpm_limiter: GlobalRPMLimiter,
) -> None:
    current_state = "investigating"
    messages: list[dict] = []
    loop = asyncio.get_running_loop()

    async def _update(status: str, **kwargs):
        nonlocal current_state
        if status != current_state:
            current_state = status
            await update_task_status(db, redis, task_id, status, **kwargs)
            await publish(redis, task_id, "status", {
                "task_id": task_id,
                "status": status,
                **{k: v for k, v in kwargs.items() if k == "current_turn"},
            })

    def _callback(event_type: str, data: dict) -> None:
        if event_type == "turn_start":
            future = asyncio.run_coroutine_threadsafe(rpm_limiter.acquire(), loop)
            future.result()
            return

        if event_type == "message":
            messages.append(data)
            return

        if event_type == "token":
            loop.call_soon_threadsafe(
                loop.create_task,
                publish(redis, task_id, "token", {"task_id": task_id, **data})
            )
            # State detection only from tool descriptions — not raw token text —
            # to avoid false transitions triggered by normal English words.

        elif event_type == "tool":
            loop.call_soon_threadsafe(
                loop.create_task,
                publish(redis, task_id, "tool", {"task_id": task_id, **data})
            )
            detected = _detect_state_from_tool(data.get("desc", ""))
            if detected and detected != current_state:
                loop.call_soon_threadsafe(
                    loop.create_task,
                    _update(detected)
                )

    try:
        await _update("investigating")

        agent = BankStatementAgent()

        result = await loop.run_in_executor(
            None,
            lambda: agent.extract(
                pdf_path,
                output_path=xlsx_path,
                status_callback=_callback,
            )
        )

        agent_status = result.get("status")

        if agent_status == "completed":
            actual_xlsx = result.get("xlsx_path", xlsx_path)
            turns_used  = len(result.get("trace", []))

            file_code = file_link = None
            try:
                upload_resp = await upload_xlsx(actual_xlsx, book_id, task_name)
                file_code = upload_resp.get("code")
                file_link = upload_resp.get("link")
                logger.info("task=%s uploaded to file server: %s", task_id, file_link)
            except Exception as exc:
                logger.warning("task=%s file server upload failed: %s", task_id, exc)

            await update_task_status(
                db, redis, task_id, "completed",
                xlsx_path=actual_xlsx,
                current_turn=turns_used,
                chat_history=messages,
                file_code=file_code,
                file_link=file_link,
            )
            current_state = "completed"
            await publish(redis, task_id, "done", {
                "task_id": task_id,
                "status": "completed",
                "file_link": file_link,
                "xlsx_rows": result.get("xlsx_rows", 0),
            })

        elif agent_status == "completed_no_output":
            error_msg = "Agent completed all turns but produced no Excel output"
            logger.warning("task=%s completed_no_output", task_id)
            await _update("failed", error=error_msg, chat_history=messages)
            await publish(redis, task_id, "done", {
                "task_id": task_id,
                "status": "failed",
                "error": error_msg,
            })

        else:
            raw = result.get("raw_response")
            error_msg = (str(raw)[-500:] if raw else "") or "Unknown error"
            await _update("failed", error=error_msg, chat_history=messages)
            await publish(redis, task_id, "done", {
                "task_id": task_id,
                "status": "failed",
                "error": error_msg,
            })

    except Exception as exc:
        logger.exception("task=%s unhandled error", task_id)
        error_msg = str(exc)
        await update_task_status(db, redis, task_id, "failed", error=error_msg)
        await publish(redis, task_id, "done", {
            "task_id": task_id,
            "status": "failed",
            "error": error_msg,
        })

    finally:
        # Clean up the uploaded PDF — it is no longer needed after the agent finishes
        Path(pdf_path).unlink(missing_ok=True)
