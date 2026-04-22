import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from copilot.interview_engine import InterviewEngine, _memory_store
from schemas import FieldState


@pytest.mark.asyncio
async def test_copilot_start_generates_first_question():
    engine = InterviewEngine()
    resp = await engine.start("test-project", "Test audience brief for investors")
    assert resp.job_id
    assert resp.question is not None
    assert len(resp.question) > 0
    assert resp.fields_total > 0
    assert resp.fields_remaining > 0
    assert resp.calibration is None


@pytest.mark.asyncio
async def test_copilot_state_persists_in_memory():
    engine = InterviewEngine()
    resp = await engine.start("test-project", "Investor audience")
    state = await engine.get_state(resp.job_id)
    assert state != {}
    assert state["project_id"] == "test-project"
    assert state["turn_count"] == 1
    assert len(state["conversation"]) >= 2  # system + first question


@pytest.mark.asyncio
async def test_copilot_respond_updates_field_state():
    engine = InterviewEngine()
    resp1 = await engine.start("test-project", "Investor audience")
    resp2 = await engine.respond(resp1.job_id, "The primary audience is institutional investors aged 35-54")
    assert resp2.job_id == resp1.job_id
    # Either a follow-up question or calibration-ready
    assert resp2.question is not None or resp2.calibration is not None


@pytest.mark.asyncio
async def test_copilot_respond_nonexistent_raises():
    engine = InterviewEngine()
    with pytest.raises(Exception, match="not found"):
        await engine.respond("nonexistent-job-id", "some answer")
