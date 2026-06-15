"""
Global RPM rate limiter — Redis sliding window.
All concurrent agent tasks share this single bucket (75 req/min).
"""

import asyncio
import time

import redis.asyncio as aioredis

GLOBAL_RPM_KEY   = "bankstatement:global:rpm"
GLOBAL_RPM_LIMIT = int(__import__("os").getenv("GLOBAL_RPM_LIMIT", "75"))
WINDOW_SECONDS   = 60


class GlobalRPMLimiter:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Block the caller until a slot is available within the 75 RPM window.
        Uses Redis sorted set as the sliding window; score = timestamp.
        """
        while True:
            async with self._lock:
                now   = time.time()
                start = now - WINDOW_SECONDS

                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(GLOBAL_RPM_KEY, 0, start)
                    pipe.zcard(GLOBAL_RPM_KEY)
                    _, count = await pipe.execute()

                if count < GLOBAL_RPM_LIMIT:
                    await self.redis.zadd(GLOBAL_RPM_KEY, {f"{now:.6f}": now})
                    await self.redis.expire(GLOBAL_RPM_KEY, WINDOW_SECONDS + 5)
                    return

            # Slot not available — wait briefly then retry
            await asyncio.sleep(0.5)

    async def current_usage(self) -> int:
        now   = time.time()
        start = now - WINDOW_SECONDS
        async with self.redis.pipeline() as pipe:
            pipe.zremrangebyscore(GLOBAL_RPM_KEY, 0, start)
            pipe.zcard(GLOBAL_RPM_KEY)
            _, count = await pipe.execute()
        return count
