"""
Background worker — runs the Bank Statement Agent for a task,
pushes SSE events, updates Postgres + Redis cache.
"""

import asyncio
import json
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine

from api.sse import publish
from api.tasks.state import update_task_status
from agent.main import BankStatementAgent


# Keywords that signal state transitions
_STATE_SIGNALS = {
    "extracting": ["parse", "extract", "transaction", "parsing", "extracting"],
    "verifying":  ["level 1", "level 2", "verification", "verify", "l1", "l2"],
    "exporting":  ["export", "openpyxl", "workbook", "saving", "write excel", "xlsx"],
}


def _detect_state(text: str) -> str | None:
    lower = text.lower()
    for state, keywords in _STATE_SIGNALS.items():
        if any(kw in lower for kw in keywords):
            return state
    return None


async def run_task(
    task_id: str,
    pdf_path: str,
    xlsx_path: str,
    db: AsyncEngine,
    redis: aioredis.Redis,
) -> None:
    current_state = "investigating"
    messages: list[dict] = []

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
        # Run in thread context — schedule coroutine on the event loop
        loop = asyncio.get_event_loop()

        if event_type == "token":
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                publish(redis, task_id, "token", {"task_id": task_id, **data})
            )
            # Detect state from accumulated agent text
            text = data.get("text", "")
            detected = _detect_state(text)
            if detected and detected != current_state:
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    _update(detected)
                )

        elif event_type == "tool":
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                publish(redis, task_id, "tool", {"task_id": task_id, **data})
            )

        elif event_type == "message":
            messages.append(data)

    try:
        await _update("investigating")

        agent = BankStatementAgent()

        # Run agent in executor (blocking)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: agent.extract(
                pdf_path,
                output_path=xlsx_path,
                status_callback=_callback,
            )
        )

        if result.get("status") == "completed":
            await _update(
                "completed",
                xlsx_path=result.get("xlsx_path", xlsx_path),
                current_turn=result.get("turns_used", 0),
                chat_history=messages,
            )
            await publish(redis, task_id, "done", {
                "task_id": task_id,
                "status": "completed",
                "xlsx_path": result.get("xlsx_path", xlsx_path),
                "xlsx_rows": result.get("xlsx_rows", 0),
            })
        else:
            error_msg = result.get("raw_response", "")[-500:] if result.get("raw_response") else "Unknown error"
            await _update("failed", error=error_msg, chat_history=messages)
            await publish(redis, task_id, "done", {
                "task_id": task_id,
                "status": "failed",
                "error": error_msg,
            })

    except Exception as exc:
        error_msg = str(exc)
        await update_task_status(db, redis, task_id, "failed", error=error_msg)
        await publish(redis, task_id, "done", {
            "task_id": task_id,
            "status": "failed",
            "error": error_msg,
        })
