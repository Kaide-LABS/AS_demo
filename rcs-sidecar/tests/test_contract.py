import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import (
    RadiantPersonaCalibration, PersonaSegment, BehavioralAttribute,
    Verbatim, SourceCitation, ArtifactType, FieldState,
    ExtractionResult, EvidenceNode, TriageManifest, ArtifactClassification,
)
from rules_engine import validate
from validators.semantic_validator import get_canonical_keys
CANONICAL_KEYS = get_canonical_keys("behavioral")
from evidence_merger import EvidenceMerger
from field_state import FieldStateEngine


def _make_citation(artifact_id="a1", locator="page 1"):
    return SourceCitation(
        artifact_id=artifact_id, artifact_type=ArtifactType.SEGMENTATION_STUDY,
        locator=locator, excerpt="test excerpt",
    )


def _make_attr(key="media_consumption", confidence=0.4):
    return BehavioralAttribute(
        key=key, value="test", confidence=confidence,
        citations=[_make_citation()],
    )


def _make_verbatim(i=0, text=None):
    return Verbatim(
        text=text or f"This is a representative verbatim quote number {i} for testing purposes.",
        sentiment="neutral", citation=_make_citation(),
    )


def _make_segment(segment_id="seg1", weight=1.0):
    return PersonaSegment(
        segment_id=segment_id, label="Test Segment", description="A test segment.",
        weight=weight,
        demographic_attributes=[_make_attr()],
        psychographic_attributes=[_make_attr()],
        behavioral_attributes=[_make_attr()],
        information_sources=["source1"],
        verbatims=[_make_verbatim(i) for i in range(5)],
        overall_confidence=0.5,
    )


def _make_calibration(**overrides):
    defaults = dict(
        project_id="test-project",
        target_audience_brief="Test brief",
        segments=[_make_segment()],
        global_provenance=[_make_citation()],
        coverage_gaps=[],
        field_state_summary={},
    )
    defaults.update(overrides)
    return RadiantPersonaCalibration(**defaults)


def test_schema_roundtrip_fixture():
    cal = _make_calibration()
    json_str = cal.model_dump_json()
    roundtripped = RadiantPersonaCalibration.model_validate_json(json_str)
    assert roundtripped.project_id == cal.project_id
    assert len(roundtripped.segments) == len(cal.segments)
    assert roundtripped.schema_version == "1.1.0"


@pytest.mark.asyncio
async def test_rules_engine_rejects_bad_weights():
    # Use model_construct to bypass Pydantic's @field_validator
    s1 = _make_segment("s1", weight=0.5)
    s2 = _make_segment("s2", weight=0.35)
    cal = RadiantPersonaCalibration.model_construct(
        schema_version="1.1.0", project_id="test", target_audience_brief="brief",
        segments=[s1, s2], global_provenance=[_make_citation()],
        coverage_gaps=[], field_state_summary={}, brand_constraints=[], campaign_benchmarks=[],
    )
    _, violations = await validate(cal)
    assert any(v.rule_name == "weights_sum_to_one" for v in violations)


@pytest.mark.asyncio
async def test_rules_engine_rejects_missing_citations():
    # Use model_construct to bypass Pydantic's min_length=1
    bad_attr = BehavioralAttribute.model_construct(
        key="media_consumption", value="x", confidence=0.1, citations=[],
    )
    seg = _make_segment()
    seg.behavioral_attributes = [bad_attr]
    cal = _make_calibration(segments=[seg])
    _, violations = await validate(cal)
    assert any(v.rule_name == "every_attribute_has_citation" for v in violations)


@pytest.mark.asyncio
async def test_rules_engine_catches_pii():
    seg = _make_segment()
    seg.verbatims[0] = Verbatim(
        text="Contact john@example.com for more details about this research segment.",
        sentiment="neutral", citation=_make_citation(),
    )
    cal = _make_calibration(segments=[seg])
    _, violations = await validate(cal)
    assert any(v.rule_name == "no_pii_in_verbatims" for v in violations)


def test_field_state_lifecycle():
    engine = FieldStateEngine()
    assert engine.count_unknown() == 11  # 11 registered fields

    manifest = TriageManifest(classifications=[
        ArtifactClassification(
            artifact_id="a1", artifact_type=ArtifactType.SEGMENTATION_STUDY,
            confidence=0.9, extraction_strategy="default",
        )
    ])
    plan = engine.plan_extractions(manifest)
    assert len(plan.assignments) > 0

    from schemas import MergedEvidence
    merged = MergedEvidence(
        evidence_by_field={"segments": [EvidenceNode(
            field_path="segments", value="test", confidence=0.8,
            source_authority="primary_research", citation=_make_citation(),
        )]},
        contradictions=[],
        deduplication_stats={"total_nodes": 1, "unique_after_merge": 1},
    )
    engine.update(merged)
    assert engine.fields["segments"] == FieldState.CANDIDATE

    engine.update_from_validation(_make_calibration(), [])
    assert engine.fields["segments"] == FieldState.VALIDATED


def test_evidence_merger_deduplication():
    cit = _make_citation("a1", "page 1")
    ext1 = ExtractionResult(
        agent_name="agent1",
        extracted_fields={"segments": "val1"},
        citations=[cit],
        validation_passed=True,
    )
    ext2 = ExtractionResult(
        agent_name="agent2",
        extracted_fields={"segments": "val1"},
        citations=[cit],  # same citation
        validation_passed=True,
    )
    merged = EvidenceMerger().merge([ext1, ext2])
    stats = merged.deduplication_stats
    assert stats["unique_after_merge"] <= stats["total_nodes"]
