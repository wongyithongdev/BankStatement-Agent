"""
SSE helpers — publish events to Redis, consume as Server-Sent Events.
"""

import asyncio
import json
import os
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi.responses import StreamingResponse

# Maximum time to hold an SSE connection open (default 30 minutes)
_SSE_MAX_SECONDS = int(os.getenv("SSE_MAX_SECONDS", "1800"))

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _channel(task_id: str) -> str:
    return f"bankstatement:stream:{task_id}"


async def publish(redis: aioredis.Redis, task_id: str, event: str, data: dict) -> None:
    message = json.dumps({"event": event, "data": data})
    await redis.publish(_channel(task_id), message)


async def _event_stream(redis: aioredis.Redis, task_id: str) -> AsyncIterator[str]:
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(task_id))
    try:
        async with asyncio.timeout(_SSE_MAX_SECONDS):
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
                if message is None:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1)
                    continue

                raw = message.get("data", "")
                if not isinstance(raw, (str, bytes)):
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode()

                try:
                    payload = json.loads(raw)
                except Exception:
                    continue

                event = payload.get("event", "message")
                data  = json.dumps(payload.get("data", {}))
                yield f"event: {event}\ndata: {data}\n\n"

                if event == "done":
                    break
    except asyncio.TimeoutError:
        # Send a timeout done event so the client knows the stream ended
        timeout_data = json.dumps({"task_id": task_id, "status": "timeout"})
        yield f"event: done\ndata: {timeout_data}\n\n"
    finally:
        await pubsub.unsubscribe(_channel(task_id))
        await pubsub.aclose()


def sse_response(redis: aioredis.Redis, task_id: str) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(redis, task_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def sse_done_response(task_id: str, status: str, file_link: str | None = None) -> StreamingResponse:
    """Immediate SSE response for tasks that already completed before the client connected."""
    payload = json.dumps({"task_id": task_id, "status": status, "file_link": file_link})

    async def _stream() -> AsyncIterator[str]:
        yield f"event: done\ndata: {payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
