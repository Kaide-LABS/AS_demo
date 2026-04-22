import os
import sys
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

@pytest.mark.asyncio
async def test_full_pipeline_offline():
    from fastapi import UploadFile
    from io import BytesIO
    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    fixture_files = [
        ("kantar_brand_tracker.csv", "text/csv"),
        ("ipsos_segments.txt", "text/plain"),
        ("earnings_transcripts.txt", "text/plain"),
        ("crm_holders.csv", "text/csv"),
    ]

    uploads = []
    for fname, content_type in fixture_files:
        path = os.path.join(FIXTURES_DIR, fname)
        with open(path, "rb") as f:
            data = f.read()
        upload = UploadFile(filename=fname, file=BytesIO(data))
        uploads.append(upload)

    broadcaster = TheaterBroadcaster("test-smoke-job")
    result = await run_calibration("smoke-project", "Test investor audience", uploads, broadcaster)

    assert result.schema_version == "1.1.0"
    assert result.project_id == "smoke-project"
    assert len(result.segments) >= 1
    assert len(result.field_state_summary) > 0
