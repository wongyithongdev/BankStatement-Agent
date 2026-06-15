"""
FastAPI application entry point.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.ratelimit import GlobalRPMLimiter
from api.routes.bankstatement import router as bankstatement_router

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv("DATABASE_URL", "")
REDIS_URL    = os.getenv("REDIS_URL", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    if not POSTGRES_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL environment variable is required")
    if not CORS_ORIGINS:
        logger.warning("CORS_ORIGINS is not set — all origins are blocked; set it to allow frontend access")

    app.state.db = create_async_engine(POSTGRES_URL, pool_size=5, max_overflow=10)
    app.state.redis = await aioredis.from_url(
        REDIS_URL, decode_responses=True, encoding="utf-8"
    )
    app.state.rpm_limiter  = GlobalRPMLimiter(app.state.redis)
    app.state.active_tasks = set()
    app.state.http_client  = httpx.AsyncClient(
        timeout=10,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )

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
        for ddl in [
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS task_name VARCHAR(255)",
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS file_code VARCHAR(64)",
            "ALTER TABLE bankstatement ADD COLUMN IF NOT EXISTS file_link TEXT",
        ]:
            await conn.execute(text(ddl))
        for idx in [
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_book_id ON bankstatement(book_id)",
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_user_id ON bankstatement(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_bankstatement_status  ON bankstatement(status)",
        ]:
            await conn.execute(text(idx))

    logger.info("startup complete")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
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

    await app.state.http_client.aclose()
    await app.state.db.dispose()
    await app.state.redis.aclose()
    logger.info("shutdown complete")


app = FastAPI(
    title="Bank Statement Agent API",
    version="1.0.0",
    description="Upload PDF bank statements and extract transactions via AI agent",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,   # empty = block all cross-origin requests (fail closed)
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(bankstatement_router)


@app.get("/health")
async def health():
    db_ok = redis_ok = False
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
    return {"ok": db_ok and redis_ok, "database": db_ok, "redis": redis_ok}
