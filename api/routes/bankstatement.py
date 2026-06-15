"""
Bank Statement API routes.
"""

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from api.auth import get_current_user, require_book_access
from api.sse import sse_response
from api.tasks.state import (
    create_task,
    get_task,
    get_task_chat,
    list_tasks,
)
from api.tasks.worker import run_task

router = APIRouter(prefix="/api/v1/bankstatement", tags=["bankstatement"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/bankstatement/uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/bankstatement/outputs"))


# ── POST /tasks ────────────────────────────────────────────────────────────

@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
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

    task_id   = str(uuid.uuid4())
    pdf_path  = str(UPLOAD_DIR / f"{task_id}.pdf")
    xlsx_path = str(OUTPUT_DIR / f"{task_id}.xlsx")

    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)

    db    = request.app.state.db
    redis = request.app.state.redis

    # Create record in Postgres
    await create_task(db, book_id, user["user_id"], pdf_path)

    # Fire and forget
    asyncio.create_task(run_task(task_id, pdf_path, xlsx_path, db, redis))

    return {"task_id": task_id, "status": "queued"}


# ── GET /tasks ─────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_user_tasks(
    request: Request,
    book_id: str,
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    await require_book_access(book_id, "book.read", user["token"])
    db = request.app.state.db
    tasks = await list_tasks(db, book_id, user["user_id"], limit=limit, offset=offset)
    return {"tasks": tasks, "limit": limit, "offset": offset}


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
    task.pop("chat_history", None)  # exclude from this endpoint
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

    xlsx_path = task.get("xlsx_path")
    if not xlsx_path or not Path(xlsx_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"bankstatement_{task_id}.xlsx",
    )
