# PHASE_4_SPEC.md — Post-Sprint Hardening: JWT Auth, Redis SSE, Connector MVP, and Production Polish

> For the execution agent. Covers post-sprint work after the 72hr demo sprint.
> Phases 1-3 delivered: schemas, rules engine, field-state engine, evidence merger,
> real parsers, LLM-wired agents, Theater frontend, CORS, fixtures, tests, and
> deployment config. This phase adds production-grade infrastructure.

---

## 1. Scope

| Stream | What | Priority |
|--------|------|----------|
| **A. JWT authentication** | Replace API key auth with signed JWT verification from AS core engine | P0 |
| **B. Redis Pub/Sub SSE** | Replace in-memory broadcaster with Redis for multi-instance Cloud Run | P0 |
| **C. Connector MVP** | Google Drive + S3 connector intake path (Lateral v2 feature) | P1 |
| **D. Prompt caching** | Enable Gemini prompt caching for synthesis agent's repeated context | P1 |
| **E. Cost monitoring** | Track per-request Gemini API spend, expose in admin endpoint | P2 |
| **F. Production polish** | Error recovery, graceful shutdown, request tracing, structured logging | P0 |

---

## 2. Stream A: JWT authentication

### 2.1 Architecture

Replace the `X-API-Key` header check with JWT verification. The AS core engine signs JWTs using a shared secret or RSA keypair. RCS verifies the signature and extracts the `project_id` from claims.

### 2.2 File: `auth.py` (new)

```python
import os
import jwt  # PyJWT
from fastapi import HTTPException, Header

JWT_SECRET = os.getenv("RCS_JWT_SECRET")
JWT_ALGORITHM = os.getenv("RCS_JWT_ALGORITHM", "HS256")


def verify_token(authorization: str = Header(...)) -> dict:
    """
    1. Extract Bearer token from Authorization header.
    2. Decode with PyJWT using JWT_SECRET and JWT_ALGORITHM.
    3. Verify claims: 'exp' (expiration), 'sub' (project_id or user_id).
    4. Return decoded payload.
    5. On failure: raise HTTPException(401).

    If JWT_SECRET is not set (dev/demo mode), skip verification
    and return a mock payload with project_id="demo".
    """
```

### 2.3 File: `main.py` — Wire auth

```python
from auth import verify_token
from fastapi import Depends

@app.post("/v1/calibrate", response_model=RadiantPersonaCalibration)
async def calibrate(
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = File(...),
    job_id: str = Form(None),
    claims: dict = Depends(verify_token),  # replaces x_api_key
) -> RadiantPersonaCalibration:
    project_id = claims.get("sub", claims.get("project_id", "unknown"))
    ...
```

Remove the `x_api_key` parameter and the `RCS_API_KEY` env var check.

### 2.4 New dependency

```
PyJWT==2.9.0
```

### 2.5 Tests

```python
def test_jwt_verification_valid():
    """Sign a token with test secret, verify it decodes correctly."""

def test_jwt_verification_expired():
    """Sign a token with exp in the past, assert 401."""

def test_jwt_skipped_in_dev():
    """Unset JWT_SECRET, assert mock payload returned."""
```

---

## 3. Stream B: Redis Pub/Sub SSE

### 3.1 Problem

Cloud Run scales to 50 instances. The `POST /v1/calibrate` request may land on instance A, but `GET /v1/calibrate/{job_id}/stream` may land on instance B. In-memory `_broadcasters` dict is per-instance. SSE stream returns 404.

### 3.2 Solution

Use Redis Pub/Sub. Each Theater event is published to a Redis channel keyed by `job_id`. The SSE endpoint subscribes to that channel.

### 3.3 File: `theater.py` — Dual-mode broadcaster

```python
import os
import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL")

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
        else:
            while True:
                event = await self._queue.get()
                yield {
                    "event": "theater",
                    "data": orjson.dumps(event.model_dump()).decode("utf-8"),
                }
                if event.stage in ("done", "error"):
                    break
```

### 3.4 File: `main.py` — Remove in-memory store dependency

With Redis, the SSE endpoint creates its own `TheaterBroadcaster` for the given `job_id` and subscribes to the Redis channel. No need for `_broadcasters` dict (though keep it as fallback for memory mode).

```python
@app.get("/v1/calibrate/{job_id}/stream")
async def stream_theater(job_id: str) -> EventSourceResponse:
    if os.getenv("REDIS_URL"):
        broadcaster = TheaterBroadcaster(job_id)
        return EventSourceResponse(broadcaster.stream())

    if job_id not in _broadcasters:
        raise HTTPException(404, "Job not found")
    return EventSourceResponse(_broadcasters[job_id].stream())
```

### 3.5 New dependency

```
redis[hiredis]==5.2.1
```

### 3.6 Deploy changes

Add `REDIS_URL` to Cloud Run env vars. Use Memorystore for Redis or Cloud Redis.

```bash
--set-env-vars="...,REDIS_URL=redis://10.0.0.3:6379"
```

---

## 4. Stream C: Connector MVP (from Lateral v2)

### 4.1 Scope

Two connectors only for MVP:
1. **Google Drive** — OAuth2 flow, browse/select files
2. **S3** — IAM role or access key, bucket + prefix browse

### 4.2 New files

```
rcs-sidecar/
└── connectors/
    ├── __init__.py
    ├── base.py              # Abstract connector interface
    ├── google_drive.py      # Google Drive OAuth + file fetch
    └── s3.py                # AWS S3 file fetch
```

### 4.3 File: `connectors/base.py`

```python
from abc import ABC, abstractmethod

class Connector(ABC):
    @abstractmethod
    async def list_files(self, path: str = "/", query: str = "") -> list[FileEntry]:
        """List available files at path. Returns metadata only, not content."""

    @abstractmethod
    async def fetch_file(self, file_id: str) -> tuple[bytes, str]:
        """Download file content. Returns (bytes, filename)."""

class FileEntry(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    modified_at: str
    path: str
```

### 4.4 File: `connectors/google_drive.py`

```python
"""
OAuth2 flow:
1. GET /v1/connectors/gdrive/auth → redirect to Google OAuth consent
2. GET /v1/connectors/gdrive/callback → exchange code for token, store in session
3. GET /v1/connectors/gdrive/files?path={folder_id} → list files using Drive API v3
4. POST /v1/connectors/gdrive/fetch → download selected files, pipe to parsers

Uses google-auth and google-api-python-client.
Scopes: drive.readonly
Token stored in-memory per session (Phase 4 only).
"""
```

### 4.5 New API routes in `main.py`

```python
@app.get("/v1/connectors/gdrive/auth")
@app.get("/v1/connectors/gdrive/callback")
@app.get("/v1/connectors/gdrive/files")
@app.post("/v1/connectors/gdrive/fetch")

@app.get("/v1/connectors/s3/files")
@app.post("/v1/connectors/s3/fetch")
```

### 4.6 New dependencies

```
google-auth==2.38.0
google-api-python-client==2.165.0
boto3==1.36.0
```

### 4.7 Frontend: `ConnectorPanel.tsx`

New component replacing or augmenting the DropZone:
- Connector cards (Google Drive, S3)
- File browser modal after auth
- Select files → fetch → pipe to existing calibrate flow

---

## 5. Stream D: Prompt caching

### 5.1 Rationale

The synthesis agent sends the same `SYNTHESIS_SYSTEM_PROMPT` and often similar evidence structures across requests for the same project. Gemini's prompt caching can reduce input costs by ~90% for cached tokens.

### 5.2 Implementation

In `agents/client.py`, add cached content support:

```python
async def generate_structured_cached(
    model: str,
    cached_content_name: str,  # from a prior caching call
    contents: str | list,
    response_schema: type[BaseModel],
    ...
) -> tuple[BaseModel, dict]:
    config = {
        "cached_content": cached_content_name,
        "response_mime_type": "application/json",
        "response_json_schema": response_schema.model_json_schema(),
    }
    ...
```

### 5.3 Cache lifecycle

```python
# Create cache for a project's system prompt + base evidence structure
cache = client.caches.create(
    model=MODEL_PRO,
    contents=[SYNTHESIS_SYSTEM_PROMPT],
    config=types.CreateCachedContentConfig(
        display_name=f"rcs-{project_id}",
        ttl="3600s",  # 1 hour
    ),
)
# Use cache.name in subsequent calls
```

### 5.4 When to use

- Cache the system prompt + any static project context for the synthesis agent.
- Do NOT cache the dynamic evidence graph (it changes per request).
- TTL: 1 hour (covers a typical demo/workshop session).

---

## 6. Stream E: Cost monitoring

### 6.1 File: `cost_tracker.py` (new)

```python
PRICING = {
    "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},  # per 1M
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-pro-preview": {"input_low": 2.00, "input_high": 4.00,
                                "output_low": 12.00, "output_high": 18.00},
}

class CostTracker:
    def __init__(self):
        self.events: list[CostEvent] = []

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD, append to events, return cost."""

    def total(self) -> float:
        """Return total cost across all recorded events."""

    def summary(self) -> dict:
        """Return per-model breakdown."""
```

### 6.2 API route

```python
@app.get("/v1/admin/costs")
async def get_costs():
    """Return per-request cost breakdown. Protected by admin API key."""
```

### 6.3 Integration

Thread `CostTracker` through `run_calibration`. After each `generate_structured` call, record the usage metadata. Include total cost in the final SSE `done` event.

---

## 7. Stream F: Production polish

### 7.1 Structured logging

Replace `print` statements with `structlog`:
```python
import structlog
logger = structlog.get_logger()

logger.info("pipeline_stage", stage="extract", agent="segment_extractor",
            artifacts=len(filtered), model=MODEL_FLASH)
```

New dependency: `structlog==24.4.0`

### 7.2 Request tracing

Generate a `trace_id` per request (already in `TheaterEvent.trace_id`). Pass it through all pipeline stages. Include in all log entries for cross-correlation.

### 7.3 Graceful error recovery

In `pipeline.py`, wrap each extraction agent in individual try/except:
```python
async def _safe_extract(coro, agent_name, broadcaster):
    try:
        return await coro
    except Exception as e:
        await broadcaster.emit("error", f"{agent_name} failed: {e}")
        return ExtractionResult(agent_name=agent_name, extracted_fields={},
                                citations=[], validation_passed=False,
                                validation_errors=[str(e)])
```

This prevents one agent failure from crashing the entire pipeline.

### 7.4 Broadcaster cleanup

In `main.py`, clean up `_broadcasters` after the response is sent (memory mode):
```python
finally:
    if job_id in _broadcasters:
        del _broadcasters[job_id]
```

### 7.5 Health check enhancement

```python
@app.get("/healthz")
async def healthz():
    checks = {"status": "ok", "version": "1.1.0"}
    if os.getenv("REDIS_URL"):
        try:
            r = redis.from_url(os.getenv("REDIS_URL"))
            await r.ping()
            checks["redis"] = "connected"
        except Exception:
            checks["redis"] = "unreachable"
            checks["status"] = "degraded"
    checks["gemini_client"] = "available" if client else "unavailable"
    return checks
```

---

## 8. New dependencies summary

```
PyJWT==2.9.0
redis[hiredis]==5.2.1
google-auth==2.38.0
google-api-python-client==2.165.0
boto3==1.36.0
structlog==24.4.0
```

---

## 9. Execution order

| Order | Task | Stream | Est. LOC |
|-------|------|--------|----------|
| 1 | `auth.py` + JWT wiring in `main.py` | A | ~60 |
| 2 | `theater.py` Redis Pub/Sub dual-mode | B | ~80 |
| 3 | `main.py` SSE Redis fallback | B | ~10 |
| 4 | Production polish: safe_extract, cleanup, logging | F | ~60 |
| 5 | `cost_tracker.py` + admin endpoint | E | ~50 |
| 6 | `connectors/base.py` + interface | C | ~30 |
| 7 | `connectors/google_drive.py` | C | ~120 |
| 8 | `connectors/s3.py` | C | ~80 |
| 9 | Connector API routes + frontend | C | ~100 |
| 10 | Prompt caching in `client.py` | D | ~40 |
| 11 | Tests for auth, Redis, connectors | All | ~150 |
| 12 | `requirements.txt` update | All | ~6 |

**Total estimated LOC:** ~786

---

## 10. What is NOT in this spec

- Conversational interview copilot (Lateral v3 — requires session store + stateful UX)
- Per-section user approval UI (Lateral v4 — requires significant frontend work)
- Demo video production
- SOC 2 / compliance infrastructure
- Multi-region deployment
- Rate limiting / quotas
