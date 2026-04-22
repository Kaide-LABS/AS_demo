import os
from auth import verify_token
from fastapi import Depends, FastAPI, UploadFile, File, Form, HTTPException, Header

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # type: ignore
from sse_starlette import EventSourceResponse
from schemas import RadiantPersonaCalibration
from pipeline import run_calibration
from theater import TheaterBroadcaster
import uuid

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Radiant Calibration Sidecar", version="1.1.0", redoc_url=None)

extra_origins = os.getenv("CORS_ORIGINS", "").split(",")
origins = ["http://localhost:3000", "http://127.0.0.1:3000"] + [o for o in extra_origins if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_broadcasters: dict[str, TheaterBroadcaster] = {}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@app.get("/healthz")
async def healthz():
    checks = {"status": "ok", "version": "1.1.0"}
    if os.getenv("REDIS_URL"):
        try:
            r = aioredis.from_url(os.getenv("REDIS_URL"))
            await r.ping()
            checks["redis"] = "connected"
            await r.aclose()
        except Exception:
            checks["redis"] = "unreachable"
            checks["status"] = "degraded"
    return checks


@app.post("/v1/calibrate", response_model=RadiantPersonaCalibration)
async def calibrate(
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = File(...),
    job_id: str = Form(None),
    claims: dict = Depends(verify_token),
) -> RadiantPersonaCalibration:
    project_id = claims.get("sub", claims.get("project_id", "unknown"))

    if len(artifacts) < 1 or len(artifacts) > 25:
        raise HTTPException(400, "Artifacts count must be between 1 and 25")

    for f in artifacts:
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, f"File '{f.filename}' exceeds 50MB limit")
        await f.seek(0)
        
    job_id = job_id or str(uuid.uuid4())
    broadcaster = TheaterBroadcaster(job_id)
    _broadcasters[job_id] = broadcaster
    
    try:
        res = await run_calibration(project_id, target_audience_brief, artifacts, broadcaster)
        return res
    except Exception as e:
        await broadcaster.emit("error", str(e))
        raise HTTPException(500, detail={"job_id": job_id, "error": str(e)})
    finally:
        if job_id in _broadcasters:
            del _broadcasters[job_id]

@app.get("/v1/calibrate/{job_id}/stream")
async def stream_theater(job_id: str) -> EventSourceResponse:
    if os.getenv("REDIS_URL"):
        broadcaster = TheaterBroadcaster(job_id)
        return EventSourceResponse(broadcaster.stream())

    if job_id not in _broadcasters:
        raise HTTPException(404, "Job not found")
    return EventSourceResponse(_broadcasters[job_id].stream())

@app.get("/v1/admin/costs")
async def get_costs(job_id: str, claims: dict = Depends(verify_token)):
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    if not os.getenv("REDIS_URL"):
        return {"error": "Cost tracking requires REDIS_URL"}
    r = aioredis.from_url(os.getenv("REDIS_URL"))
    events_raw = await r.lrange(f"costs:{job_id}", 0, -1)
    await r.aclose()
    
    events = [orjson.loads(e) for e in events_raw]
    return {"job_id": job_id, "events": events}

@app.get("/v1/connectors/gdrive/auth")
async def gdrive_auth():
    # Mock OAuth flow
    return {"auth_url": "https://accounts.google.com/o/oauth2/v2/auth?... Mocked"}

@app.get("/v1/connectors/gdrive/callback")
async def gdrive_callback(code: str, project_id: str):
    # Mock token exchange
    if os.getenv("REDIS_URL"):
        r = aioredis.from_url(os.getenv("REDIS_URL"))
        await r.set(f"gdrive_creds:{project_id}", '{"mock": "creds"}')
        await r.aclose()
    return {"status": "success", "project_id": project_id}

@app.get("/v1/connectors/gdrive/files")
async def gdrive_files(project_id: str, path: str = "root"):
    from connectors.google_drive import GoogleDriveConnector
    conn = GoogleDriveConnector(project_id)
    try:
        files = await conn.list_files(path=path)
        return files
    except Exception as e:
        return {"error": str(e)}

@app.post("/v1/connectors/gdrive/fetch")
async def gdrive_fetch(project_id: str, file_ids: list[str]):
    from connectors.google_drive import GoogleDriveConnector
    conn = GoogleDriveConnector(project_id)
    fetched = []
    for fid in file_ids:
        try:
            b, n = await conn.fetch_file(fid)
            fetched.append({"filename": n, "size": len(b)})
        except Exception as e:
            fetched.append({"file_id": fid, "error": str(e)})
    return {"fetched": fetched}
