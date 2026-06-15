"""
FastAPI application entry point.
"""

import os

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from api.routes.bankstatement import router as bankstatement_router

POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://root:root@10.0.10.63:5432/root"
)
REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://ubuntu:root@192.168.11.177:6379/0"
)

app = FastAPI(
    title="Bank Statement Agent API",
    version="1.0.0",
    description="Upload PDF bank statements and extract transactions via AI agent",
)

app.include_router(bankstatement_router)


@app.on_event("startup")
async def startup():
    app.state.db = create_async_engine(
        POSTGRES_URL,
        pool_size=5,
        max_overflow=10,
    )
    app.state.redis = await aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        encoding="utf-8",
    )
    # Ensure table exists
    from sqlalchemy import text
    async with app.state.db.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bankstatement (
                task_id      VARCHAR(36)  PRIMARY KEY,
                book_id      VARCHAR(128) NOT NULL,
                user_id      VARCHAR(128) NOT NULL,
                status       VARCHAR(32)  NOT NULL DEFAULT 'queued',
                pdf_path     TEXT,
                xlsx_path    TEXT,
                current_turn INT          DEFAULT 0,
                error        TEXT,
                chat_history JSONB,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_bankstatement_book_id ON bankstatement(book_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_bankstatement_user_id ON bankstatement(user_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_bankstatement_status  ON bankstatement(status)
        """))


@app.on_event("shutdown")
async def shutdown():
    await app.state.db.dispose()
    await app.state.redis.aclose()


@app.get("/health")
async def health():
    return {"status": "ok"}
