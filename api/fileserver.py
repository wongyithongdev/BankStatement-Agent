"""
File Server client — uploads Excel output to the object storage server.
"""

import os
from pathlib import Path

import httpx

FILESERVER_URL     = os.getenv("FILESERVER_URL", "https://files.my365biz.com")
FILESERVER_API_KEY = os.getenv("FILESERVER_API_KEY", "")


async def upload_xlsx(xlsx_path: str, book_id: str, task_name: str = "") -> dict:
    """
    Upload an Excel file to the file server.
    Returns {"code": str, "link": str} on success.
    Raises httpx.HTTPError on failure.
    """
    path = Path(xlsx_path)
    filename = f"{task_name}.xlsx" if task_name else path.name

    async with httpx.AsyncClient(timeout=60) as client:
        with open(xlsx_path, "rb") as f:
            resp = await client.post(
                f"{FILESERVER_URL}/upload",
                headers={"X-API-Key": FILESERVER_API_KEY},
                data={"bookid": book_id},
                files={
                    "file": (
                        filename,
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        resp.raise_for_status()
        return resp.json()   # {"code": "...", "link": "..."}
