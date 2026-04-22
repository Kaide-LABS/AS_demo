from fastapi import FastAPI, UploadFile, Form, HTTPException
from sse_starlette import EventSourceResponse
from schemas import RadiantPersonaCalibration
from pipeline import run_calibration
from theater import TheaterBroadcaster
import uuid

app = FastAPI(title="Radiant Calibration Sidecar", version="1.1.0", redoc_url=None)

_broadcasters: dict[str, TheaterBroadcaster] = {}

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": "1.1.0"}

@app.post("/v1/calibrate", response_model=RadiantPersonaCalibration)
async def calibrate(
    project_id: str = Form(...),
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = Form(...)
) -> RadiantPersonaCalibration:
    if len(artifacts) < 1 or len(artifacts) > 25:
        raise HTTPException(400, "Artifacts count must be between 1 and 25")
        
    job_id = str(uuid.uuid4())
    broadcaster = TheaterBroadcaster(job_id)
    _broadcasters[job_id] = broadcaster
    
    try:
        res = await run_calibration(project_id, target_audience_brief, artifacts, broadcaster)
        return res
    except Exception as e:
        await broadcaster.emit("error", str(e))
        raise HTTPException(500, detail={"job_id": job_id, "error": str(e)})

@app.get("/v1/calibrate/{job_id}/stream")
async def stream_theater(job_id: str) -> EventSourceResponse:
    if job_id not in _broadcasters:
        raise HTTPException(404, "Job not found")
    
    return EventSourceResponse(_broadcasters[job_id].stream())
