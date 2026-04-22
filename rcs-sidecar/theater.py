import os
import time
import asyncio
from typing import AsyncGenerator
import orjson
from schemas import TheaterEvent

REDIS_URL = os.getenv("REDIS_URL")

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # type: ignore
    if REDIS_URL:
        raise ImportError("redis package required when REDIS_URL is set. pip install redis[hiredis]")

class TheaterBroadcaster:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._start_time_ms = int(time.time() * 1000)

        if REDIS_URL:
            self._redis = redis.from_url(REDIS_URL)
            self._channel = f"theater:{job_id}"
            self._mode = "redis"
        else:
            self._queue = asyncio.Queue()
            self._mode = "memory"

    async def emit(self, stage: str, message: str, meta: dict = {}) -> None:
        event = TheaterEvent(
            ts_ms=int(time.time() * 1000) - self._start_time_ms,
            stage=stage, message=message, meta=meta, trace_id=self.job_id,
        )
        payload = orjson.dumps(event.model_dump()).decode("utf-8")

        if self._mode == "redis":
            await self._redis.publish(self._channel, payload)
        else:
            await self._queue.put(event)

    async def stream(self) -> AsyncGenerator[dict, None]:
        if self._mode == "redis":
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(self._channel)
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"].decode("utf-8") if isinstance(message["data"], bytes) else message["data"]
                        yield {"event": "theater", "data": data}
                        parsed = orjson.loads(data)
                        if parsed.get("stage") in ("done", "error"):
                            break
            finally:
                await pubsub.unsubscribe(self._channel)
                await self._redis.aclose()
        else:
            while True:
                event = await self._queue.get()
                yield {
                    "event": "theater",
                    "data": orjson.dumps(event.model_dump()).decode("utf-8"),
                }
                if event.stage in ("done", "error"):
                    break
