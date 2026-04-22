import os
import json
import redis.asyncio as redis
from pydantic import BaseModel

PRICING = {
    "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00}, # simplified for demo
}

REDIS_URL = os.getenv("REDIS_URL")

class CostEvent(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

class CostTracker:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.events = []
        self._redis = redis.from_url(REDIS_URL) if REDIS_URL else None

    async def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rates = PRICING.get(model, {"input": 0, "output": 0})
        cost = (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]
        event = CostEvent(model=model, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)
        self.events.append(event)
        
        if self._redis:
            await self._redis.lpush(f"costs:{self.job_id}", event.model_dump_json())
        return cost

    async def total(self) -> float:
        return sum(e.cost_usd for e in self.events)

    async def summary(self) -> dict:
        summary = {}
        for e in self.events:
            if e.model not in summary:
                summary[e.model] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            summary[e.model]["input_tokens"] += e.input_tokens
            summary[e.model]["output_tokens"] += e.output_tokens
            summary[e.model]["cost_usd"] += e.cost_usd
        return summary
