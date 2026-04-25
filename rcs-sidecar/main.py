import os
import orjson
from pathlib import Path
import uvicorn
from auth import verify_token
from fastapi import Depends, FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import Response

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # type: ignore
from sse_starlette import EventSourceResponse
from schemas import RadiantPersonaCalibration, PartialCalibrationResponse
from typing import Literal, Union
from schemas import InterviewResponse, SectionStatus
from copilot.interview_engine import InterviewEngine

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
SAMPLE_ARTIFACTS_DIR = Path(__file__).resolve().parent / "demo" / "sample_artifacts"
SAMPLE_ARTIFACT_DESCRIPTIONS = {
    "executive_report.md": "Segmentation study — 4 segments, n=1,247",
    "survey_responses.csv": "Raw survey data — 120 respondents, 16 fields",
    "screener.qsf": "Qualtrics screener — 13 questions",
    "interview_transcripts.md": "In-depth interviews — 3 transcripts",
    "persona_brief.txt": "Strategist's audience brief — narrative prose",
}
SAMPLE_ARTIFACT_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".qsf": "application/json",
    ".txt": "text/plain",
}

@app.get("/healthz")
async def healthz():
    checks = {"status": "ok", "version": "1.1.0"}
    if os.getenv("REDIS_URL"):
        if aioredis is None:
            checks["redis"] = "client_missing"
            checks["status"] = "degraded"
        else:
            try:
                r = aioredis.from_url(os.getenv("REDIS_URL"))
                await r.ping()
                checks["redis"] = "connected"
                await r.aclose()
            except Exception:
                checks["redis"] = "unreachable"
                checks["status"] = "degraded"
    return checks


@app.get("/v1/sample_artifacts")
async def list_sample_artifacts():
    artifacts = []
    for filename, description in SAMPLE_ARTIFACT_DESCRIPTIONS.items():
        path = SAMPLE_ARTIFACTS_DIR / filename
        if not path.is_file():
            raise HTTPException(500, f"Sample artifact '{filename}' is missing")

        artifacts.append({
            "filename": filename,
            "description": description,
            "size_bytes": path.stat().st_size,
            "content_type": SAMPLE_ARTIFACT_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        })

    return artifacts


@app.get("/v1/sample_artifacts/{filename}")
async def get_sample_artifact(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    path = SAMPLE_ARTIFACTS_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Sample artifact not found")

    content_type = SAMPLE_ARTIFACT_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return Response(content=path.read_bytes(), media_type=content_type)


@app.post("/v1/calibrate", response_model=Union[RadiantPersonaCalibration, PartialCalibrationResponse])
async def calibrate(
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = File(...),
    job_id: str = Form(None),
    claims: dict = Depends(verify_token),
) -> Union[RadiantPersonaCalibration, PartialCalibrationResponse]:
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

    # Auto-register broadcaster: clients open SSE before POST /calibrate fires.
    if job_id not in _broadcasters:
        _broadcasters[job_id] = TheaterBroadcaster(job_id)
    return EventSourceResponse(_broadcasters[job_id].stream())

@app.get("/v1/admin/costs")
async def get_costs(job_id: str, claims: dict = Depends(verify_token)):
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    if not os.getenv("REDIS_URL") or aioredis is None:
        return {"error": "Cost tracking requires REDIS_URL and redis client"}
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

@app.post("/v1/copilot/start", response_model=InterviewResponse)
async def copilot_start(
    project_id: str = Form(...),
    brief: str = Form(..., max_length=2000),
    claims: dict = Depends(verify_token),
) -> InterviewResponse:
    engine = InterviewEngine()
    return await engine.start(project_id, brief)

@app.post("/v1/copilot/{job_id}/respond", response_model=InterviewResponse)
async def copilot_respond(
    job_id: str,
    answer: str = Form(...),
    files: list[UploadFile] = File(None),
    claims: dict = Depends(verify_token),
) -> InterviewResponse:
    engine = InterviewEngine()
    return await engine.respond(job_id, answer, files)

@app.get("/v1/copilot/{job_id}/state")
async def copilot_state(job_id: str, claims: dict = Depends(verify_token)):
    engine = InterviewEngine()
    return await engine.get_state(job_id)

@app.get("/v1/calibrate/{job_id}/sections", response_model=list[SectionStatus])
async def get_sections(job_id: str, claims: dict = Depends(verify_token)) -> list[SectionStatus]:
    # Mock returning sections
    return [
        SectionStatus(section_id="seg1", section_name="Segments", status="pending", field_count=5, approved_count=0),
        SectionStatus(section_id="dem1", section_name="Demographics", status="approved", field_count=3, approved_count=3)
    ]

@app.post("/v1/calibrate/{job_id}/sections/{section_id}/approve", response_model=SectionStatus)
async def approve_section(
    job_id: str, section_id: str, claims: dict = Depends(verify_token)
) -> SectionStatus:
    return SectionStatus(section_id=section_id, section_name="Section", status="approved", field_count=5, approved_count=5)

@app.post("/v1/calibrate/{job_id}/sections/{section_id}/reject", response_model=SectionStatus)
async def reject_section(
    job_id: str, section_id: str, reason: str = Form(...),
    claims: dict = Depends(verify_token),
) -> SectionStatus:
    return SectionStatus(section_id=section_id, section_name="Section", status="rejected", field_count=5, approved_count=0, rejection_reason=reason)

@app.get("/v1/connectors/s3/files")
async def s3_files(
    bucket: str,
    path: str = "",
    claims: dict = Depends(verify_token),
):
    from connectors.s3 import S3Connector
    conn = S3Connector(bucket=bucket)
    return await conn.list_files(path=path)

@app.post("/v1/connectors/s3/fetch")
async def s3_fetch(
    bucket: str = Form(...),
    file_ids: list[str] = Form(...),
    claims: dict = Depends(verify_token),
):
    from connectors.s3 import S3Connector
    conn = S3Connector(bucket=bucket)
    fetched = []
    for fid in file_ids:
        try:
            data, name = await conn.fetch_file(fid)
            fetched.append({"filename": name, "size": len(data)})
        except Exception as e:
            fetched.append({"file_id": fid, "error": str(e)})
    return {"fetched": fetched}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
