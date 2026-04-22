import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import (
    FieldExtractionPlan, AgentAssignment, SourceArtifact, ArtifactType,
    TriageManifest, ArtifactClassification,
)


@pytest.mark.asyncio
async def test_triage_filename_fallback():
    from agents.triage import triage_agent
    from theater import TheaterBroadcaster

    artifacts = [
        SourceArtifact(artifact_id="a1", filename="Brand_Tracker_Q4.csv",
                       raw_text="brand data", size_bytes=100),
        SourceArtifact(artifact_id="a2", filename="CRM_Export.csv",
                       raw_text="crm data", size_bytes=100),
    ]
    broadcaster = TheaterBroadcaster("test")
    manifest = await triage_agent(artifacts, broadcaster)
    types_found = {c.artifact_type for c in manifest.classifications}
    assert ArtifactType.BRAND_TRACKER in types_found
    assert ArtifactType.CRM_EXPORT in types_found


@pytest.mark.asyncio
async def test_extraction_agent_skips_unassigned():
    from agents.segment_extractor import segment_extractor
    from theater import TheaterBroadcaster

    plan = FieldExtractionPlan(assignments=[
        AgentAssignment(agent_name="verbatim_distiller", target_fields=["v"],
                        artifact_ids=["a1"], priority=1),
    ])
    artifacts = [SourceArtifact(artifact_id="a1", filename="test.txt",
                                raw_text="data", size_bytes=10)]
    broadcaster = TheaterBroadcaster("test")
    result = await segment_extractor(artifacts, plan, broadcaster)
    assert result.validation_passed is True
    assert result.extracted_fields == {}
