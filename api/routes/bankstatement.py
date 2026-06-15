"""
Bank Statement API routes.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth import get_current_user, require_book_access
from api.sse import sse_response
from api.tasks.state import (
    create_task,
    get_task,
    get_task_chat,
    list_tasks,
)
from api.tasks.worker import run_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/bankstatement", tags=["bankstatement"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/bankstatement/uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/bankstatement/outputs"))


# ── Pydantic response models ───────────────────────────────────────────────

class TaskCreatedResponse(BaseModel):
    task_id: str
    task_name: str
    status: str


class TaskSummary(BaseModel):
    task_id: str
    task_name: Optional[str]
    user_id: str
    status: str
    created_at: datetime
    file_link: Optional[str]
    action: str   # "download" | "pending" | "failed"


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]
    limit: int
    offset: int


def _action_for(task: dict) -> str:
    if task["status"] == "completed" and task.get("file_link"):
        return "download"
    if task["status"] == "failed":
        return "failed"
    return "pending"


# ── POST /tasks ────────────────────────────────────────────────────────────

@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED, response_model=TaskCreatedResponse)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    book_id: str = Form(...),
    user: dict = Depends(get_current_user),
):
    await require_book_access(book_id, "book.read", user["token"])

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # task_name = filename without extension
    task_name = Path(file.filename).stem

    task_id   = str(uuid.uuid4())
    pdf_path  = str(UPLOAD_DIR / f"{task_id}.pdf")
    xlsx_path = str(OUTPUT_DIR / f"{task_id}.xlsx")

    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)

    db    = request.app.state.db
    redis = request.app.state.redis
    rpm   = request.app.state.rpm_limiter

    db_task_id = await create_task(db, book_id, user["user_id"], pdf_path, task_name=task_name)

    # Fire and forget — pass task_id returned by DB (same uuid we generated)
    active_tasks: set = request.app.state.active_tasks
    bg = asyncio.create_task(
        run_task(db_task_id, pdf_path, xlsx_path, book_id, task_name, db, redis, rpm)
    )
    active_tasks.add(bg)
    bg.add_done_callback(active_tasks.discard)

    logger.info("task=%s created book=%s user=%s", db_task_id, book_id, user["user_id"])
    return TaskCreatedResponse(task_id=db_task_id, task_name=task_name, status="queued")


# ── GET /tasks ─────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=TaskListResponse)
async def list_book_tasks(
    request: Request,
    book_id: str,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    await require_book_access(book_id, "book.read", user["token"])
    db = request.app.state.db
    rows = await list_tasks(db, book_id, limit=limit, offset=offset)
    tasks = [
        TaskSummary(
            task_id=r["task_id"],
            task_name=r.get("task_name"),
            user_id=r["user_id"],
            status=r["status"],
            created_at=r["created_at"],
            file_link=r.get("file_link"),
            action=_action_for(r),
        )
        for r in rows
    ]
    return TaskListResponse(tasks=tasks, limit=limit, offset=offset)


# ── GET /tasks/{task_id} ───────────────────────────────────────────────────

@router.get("/tasks/{task_id}")
async def get_task_detail(
    task_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db   = request.app.state.db
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await require_book_access(task["book_id"], "book.read", user["token"])
    task.pop("chat_history", None)
    return task


# ── GET /tasks/{task_id}/stream ────────────────────────────────────────────

@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db   = request.app.state.db
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await require_book_access(task["book_id"], "book.read", user["token"])

    redis = request.app.state.redis
    return sse_response(redis, task_id)


# ── GET /tasks/{task_id}/chat ──────────────────────────────────────────────

@router.get("/tasks/{task_id}/chat")
async def get_chat_history(
    task_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db   = request.app.state.db
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await require_book_access(task["book_id"], "book.read", user["token"])

    messages = await get_task_chat(db, task_id)
    return {"task_id": task_id, "messages": messages, "count": len(messages)}


# ── GET /tasks/{task_id}/download ─────────────────────────────────────────

@router.get("/tasks/{task_id}/download")
async def download_xlsx(
    task_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db   = request.app.state.db
    task = await get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await require_book_access(task["book_id"], "book.read", user["token"])

    if task["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Task is not completed yet (current status: {task['status']})",
        )

    file_link = task.get("file_link")
    if not file_link:
        raise HTTPException(status_code=404, detail="Output file not available")

    return RedirectResponse(url=file_link, status_code=302)
