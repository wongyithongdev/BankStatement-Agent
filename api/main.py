"""
FastAPI application entry point.
"""

import asyncio
import logging
import os

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.ratelimit import GlobalRPMLimiter
from api.routes.bankstatement import router as bankstatement_router

# ── Structured JSON logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://root:root@10.0.10.63:5432/root"
)
REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://ubuntu:root@192.168.11.177:6379/0"
)
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]

app = FastAPI(
    title="Bank Statement Agent API",
    version="1.0.0",
    description="Upload PDF bank statements and extract transactions via AI agent",
)

# ── CORS ──────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(bankstatement_router)


# ── Lifecycle ──────────────────────────────────────────────────────────────

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
    app.state.rpm_limiter = GlobalRPMLimiter(app.state.redis)
    app.state.active_tasks: set = set()

    # Ensure table + new columns exist
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
        # New columns (idempotent)
        for ddl in [
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS task_name VARCHAR(255)",
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS file_code VARCHAR(64)",
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS file_link TEXT",
        ]:
            await conn.execute(text(ddl))
        # Indexes
        for idx in [
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_book_id ON bankstatement(book_id)",
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_user_id ON bankstatement(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_status  ON bankstatement(status)",
        ]:
            await conn.execute(text(idx))

    logger.info("startup complete — db=%s redis=%s", POSTGRES_URL.split("@")[-1], REDIS_URL.split("@")[-1])


@app.on_event("shutdown")
async def shutdown():
    active = app.state.active_tasks
    if active:
        logger.info("shutdown: waiting for %d active tasks (30s timeout)", len(active))
        try:
            await asyncio.wait_for(
                asyncio.gather(*active, return_exceptions=True),
                timeout=30,
            )
        except asyncio.TimeoutError:
            logger.warning("shutdown: timed out waiting for tasks, forcing exit")

    await app.state.db.dispose()
    await app.state.redis.aclose()
    logger.info("shutdown complete")


# ── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    db_ok    = False
    redis_ok = False
    try:
        async with app.state.db.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception:
        pass

    ok = db_ok and redis_ok
    return {"ok": ok, "database": db_ok, "redis": redis_ok}
