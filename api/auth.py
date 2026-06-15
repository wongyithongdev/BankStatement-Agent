"""
Auth middleware — validates Keycloak JWT and checks book permissions via AuthServer.
Uses the shared httpx.AsyncClient from app.state to reuse connections.
"""

import os

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

AUTH_SERVER_BASE = os.getenv("AUTH_SERVER_BASE", "http://localhost:8080")

bearer_scheme = HTTPBearer()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    token = credentials.credentials
    client: httpx.AsyncClient = request.app.state.http_client
    resp = await client.get(
        f"{AUTH_SERVER_BASE}/auth/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return {"token": token, **resp.json()}


async def require_book_access(
    book_id: str,
    action: str,
    token: str,
    http_client: httpx.AsyncClient,
) -> None:
    resp = await http_client.post(
        f"{AUTH_SERVER_BASE}/auth/api/v1/permissions/check",
        headers={"Authorization": f"Bearer {token}"},
        json={"book_id": book_id, "action": action},
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission check failed")

    data = resp.json()
    if not data.get("allowed"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Action '{action}' denied for book '{book_id}'",
        )
