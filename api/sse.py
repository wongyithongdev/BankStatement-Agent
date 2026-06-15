"""
SSE helpers — publish events to Redis, consume as Server-Sent Events.
"""

import asyncio
import json
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi.responses import StreamingResponse


def _channel(task_id: str) -> str:
    return f"bankstatement:stream:{task_id}"


async def publish(redis: aioredis.Redis, task_id: str, event: str, data: dict) -> None:
    message = json.dumps({"event": event, "data": data})
    await redis.publish(_channel(task_id), message)


async def _event_stream(redis: aioredis.Redis, task_id: str) -> AsyncIterator[str]:
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(task_id))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            if message is None:
                # Send keepalive comment
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
    finally:
        await pubsub.unsubscribe(_channel(task_id))
        await pubsub.aclose()


def sse_response(redis: aioredis.Redis, task_id: str) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(redis, task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
