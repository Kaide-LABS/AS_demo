import asyncio
import time
from typing import AsyncGenerator
import orjson
from schemas import TheaterEvent

class TheaterBroadcaster:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._queue: asyncio.Queue[TheaterEvent] = asyncio.Queue()
        self._start_time_ms = int(time.time() * 1000)

    async def emit(self, stage: str, message: str, meta: dict = {}) -> None:
        event = TheaterEvent(
            ts_ms=int(time.time() * 1000) - self._start_time_ms,
            stage=stage,
            message=message,
            meta=meta,
            trace_id=self.job_id
        )
        await self._queue.put(event)

    async def stream(self) -> AsyncGenerator[dict, None]:
        while True:
            event = await self._queue.get()
            yield {
                "event": "theater",
                "data": orjson.dumps(event.model_dump()).decode('utf-8')
            }
            if event.stage in ["done", "error"]:
                break
