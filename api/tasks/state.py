"""
Task state management — Postgres (source of truth) + Redis (cache).
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REDIS_CACHE_TTL = 300  # seconds


# ── Postgres CRUD ──────────────────────────────────────────────────────────

async def create_task(
    db: AsyncEngine,
    book_id: str,
    user_id: str,
    pdf_path: str,
    task_name: str = "",
    task_id: Optional[str] = None,
) -> str:
    if task_id is None:
        task_id = str(uuid.uuid4())
    async with db.begin() as conn:
        await conn.execute(text("""
            INSERT INTO bankstatement
                (task_id, book_id, user_id, status, pdf_path, task_name, created_at, updated_at)
            VALUES
                (:task_id, :book_id, :user_id, 'queued', :pdf_path, :task_name, NOW(), NOW())
        """), {
            "task_id": task_id,
            "book_id": book_id,
            "user_id": user_id,
            "pdf_path": pdf_path,
            "task_name": task_name,
        })
    return task_id


async def get_task(db: AsyncEngine, task_id: str) -> Optional[dict]:
    async with db.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM bankstatement WHERE task_id = :task_id"),
            {"task_id": task_id}
        )
        row = result.mappings().fetchone()
    if row is None:
        return None
    return dict(row)


async def list_tasks(
    db: AsyncEngine,
    book_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    async with db.connect() as conn:
        result = await conn.execute(text("""
            SELECT task_id, task_name, user_id, status,
                   created_at, updated_at, file_link
            FROM bankstatement
            WHERE book_id = :book_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"book_id": book_id, "limit": limit, "offset": offset})
        return [dict(r) for r in result.mappings()]


async def update_task_status(
    db: AsyncEngine,
    redis: aioredis.Redis,
    task_id: str,
    status: str,
    *,
    current_turn: Optional[int] = None,
    xlsx_path: Optional[str] = None,
    error: Optional[str] = None,
    chat_history: Optional[list] = None,
    file_code: Optional[str] = None,
    file_link: Optional[str] = None,
) -> None:
    fields: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
    if current_turn is not None:
        fields["current_turn"] = current_turn
    if xlsx_path is not None:
        fields["xlsx_path"] = xlsx_path
    if error is not None:
        fields["error"] = error
    if chat_history is not None:
        fields["chat_history"] = json.dumps(chat_history)
    if file_code is not None:
        fields["file_code"] = file_code
    if file_link is not None:
        fields["file_link"] = file_link

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["task_id"] = task_id

    async with db.begin() as conn:
        await conn.execute(
            text(f"UPDATE bankstatement SET {set_clause} WHERE task_id = :task_id"),
            fields
        )

    cache_key = f"bankstatement:task:{task_id}:status"
    await redis.set(cache_key, status, ex=REDIS_CACHE_TTL)


async def get_task_status_cached(redis: aioredis.Redis, task_id: str) -> Optional[str]:
    return await redis.get(f"bankstatement:task:{task_id}:status")


async def get_task_chat(db: AsyncEngine, task_id: str) -> list:
    async with db.connect() as conn:
        result = await conn.execute(
            text("SELECT chat_history FROM bankstatement WHERE task_id = :task_id"),
            {"task_id": task_id}
        )
        row = result.fetchone()
    if row is None or row[0] is None:
        return []
    return row[0] if isinstance(row[0], list) else json.loads(row[0])
