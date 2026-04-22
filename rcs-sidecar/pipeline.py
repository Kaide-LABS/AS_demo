import asyncio
import json
from fastapi import UploadFile
from google.genai import types
from schemas import (
    RadiantPersonaCalibration, MergedEvidence, RuleViolation,
    PersonaSegment, BehavioralAttribute, Verbatim, SourceCitation,
    ArtifactType, FieldState,
)
from theater import TheaterBroadcaster
from parsers.detect import detect_and_parse
from agents.triage import triage_agent
from field_state import FieldStateEngine
from evidence_merger import EvidenceMerger
from rules_engine import validate
from agents.segment_extractor import segment_extractor
from agents.verbatim_distiller import verbatim_distiller
from agents.demographic_normalizer import demographic_normalizer
from agents.behavioral_extractor import behavioral_extractor
from agents.brand_tone_extractor import brand_tone_extractor
from agents.campaign_benchmark_extractor import campaign_benchmark_extractor
from agents.client import generate_structured, generate_text, MODEL_PRO, client

SYNTHESIS_SYSTEM_PROMPT = """You are an enterprise audience calibration synthesizer.
You will receive a merged evidence graph from multiple extraction agents.
Produce a single RadiantPersonaCalibration JSON object.
Rules:
- Create 3-8 named segments. Segment weights MUST sum to 1.0.
- Every attribute must cite at least one source artifact.
- Each segment must have at least 5 verbatims.
- Resolve any contradictions flagged in the evidence.
- For fields marked as UNKNOWN in the field state, note them in coverage_gaps.
- Do NOT invent data. If evidence is insufficient, set requires_human_review=true."""


def _build_mock_calibration(project_id: str, brief: str, field_state: dict) -> RadiantPersonaCalibration:
    """Deterministic mock for offline/demo use when no Gemini client is available."""
    mock_citation = SourceCitation(
        artifact_id="mock-artifact-001",
        artifact_type=ArtifactType.SEGMENTATION_STUDY,
        locator="page 1",
        excerpt="Mock excerpt for demo purposes.",
    )
    mock_attr = BehavioralAttribute(
        key="media_consumption", value="moderate", confidence=0.4,
        citations=[mock_citation],
    )
    mock_verbatim = lambda i: Verbatim(
        text=f"This is a representative mock verbatim quote number {i} for demo purposes.",
        sentiment="neutral", citation=mock_citation,
    )
    seg = PersonaSegment(
        segment_id="demo_segment",
        label="Demo Segment",
        description="A placeholder segment generated for offline demo.",
        weight=1.0,
        demographic_attributes=[mock_attr],
        psychographic_attributes=[mock_attr],
        behavioral_attributes=[mock_attr],
        information_sources=["mock_source"],
        verbatims=[mock_verbatim(i) for i in range(5)],
        overall_confidence=0.4,
        requires_human_review=True,
    )
    return RadiantPersonaCalibration(
        project_id=project_id,
        target_audience_brief=brief,
        segments=[seg],
        global_provenance=[mock_citation],
        coverage_gaps=["All fields require human review — mock calibration."],
        field_state_summary=field_state,
    )


async def synthesis_agent(
    project_id: str, brief: str, evidence: MergedEvidence,
    field_state: dict, broadcaster: TheaterBroadcaster,
) -> RadiantPersonaCalibration:
    await broadcaster.emit("synthesize", "Synthesizing calibration (deep reasoning)...")
    if not client:
        return _build_mock_calibration(project_id, brief, field_state)

    evidence_json = json.dumps({
        "evidence_by_field": {k: [n.model_dump() for n in v] for k, v in evidence.evidence_by_field.items()},
        "contradictions": [c.model_dump() for c in evidence.contradictions],
    }, default=str)

    contents = (
        f"Target audience brief: {brief}\n\n"
        f"Field state: {json.dumps(field_state, default=str)}\n\n"
        f"Evidence graph:\n{evidence_json}\n"
    )

    result, usage = await generate_structured(
        model=MODEL_PRO,
        contents=contents,
        response_schema=RadiantPersonaCalibration,
        thinking_level=types.ThinkingLevel.HIGH,
        system_instruction=SYNTHESIS_SYSTEM_PROMPT,
    )
    await broadcaster.emit('synthesize', 'Synthesis completed', meta=usage)
    result.project_id = project_id
    return result

async def targeted_retry(calibration: RadiantPersonaCalibration, violations: list[RuleViolation]) -> RadiantPersonaCalibration:
    if not client:
        return calibration
    violation_text = "\n".join(f"- {v.rule_name}: {v.description} (field: {v.field_path})" for v in violations)
    contents = (
        f"The following validation rules failed on this calibration JSON. "
        f"Fix ONLY the failing fields. Do not alter passing fields.\n\n"
        f"Violations:\n{violation_text}\n\n"
        f"Current calibration:\n{calibration.model_dump_json()}"
    )
    result, usage = await generate_structured(
        model=MODEL_PRO,
        contents=contents,
        response_schema=RadiantPersonaCalibration,
        thinking_level=types.ThinkingLevel.MEDIUM,
        system_instruction="You are a calibration repair agent. Fix only the specific violations listed.",
    )
    await broadcaster.emit('validate', 'Targeted retry completed', meta=usage)
    result.project_id = calibration.project_id
    return result

async def run_calibration(project_id: str, brief: str, uploads: list[UploadFile], broadcaster: TheaterBroadcaster) -> RadiantPersonaCalibration:
    await broadcaster.emit("ingest", f"Parsing {len(uploads)} files...")
    artifacts = await asyncio.gather(*[detect_and_parse(f) for f in uploads])
    await broadcaster.emit("ingest", f"Parsed {len(artifacts)} artifacts")

    await broadcaster.emit("triage", "Classifying artifacts...")
    manifest = await triage_agent(artifacts, broadcaster)
    for a in artifacts:
        for c in manifest.classifications:
            if c.artifact_id == a.artifact_id:
                a.artifact_type = c.artifact_type

    field_state = FieldStateEngine()
    plan = field_state.plan_extractions(manifest)
    await broadcaster.emit("field_state", f"{field_state.count_unknown()} fields required, 0 populated")

    await broadcaster.emit("extract", "Running 6 extraction agents in parallel...")
    import time
    t0 = time.time()
    extractions = await asyncio.gather(
        segment_extractor(artifacts, plan, broadcaster),
        verbatim_distiller(artifacts, plan, broadcaster),
        demographic_normalizer(artifacts, plan, broadcaster),
        behavioral_extractor(artifacts, plan, broadcaster),
        brand_tone_extractor(artifacts, plan, broadcaster),
        campaign_benchmark_extractor(artifacts, plan, broadcaster)
    )
    extraction_latency = time.time() - t0
    await broadcaster.emit('extract', f'Extraction complete in {extraction_latency:.1f}s')
    passed = sum(1 for e in extractions if e.validation_passed)
    await broadcaster.emit("extract", f"Continuous validation: {passed}/{len(extractions)} extractors passed")

    await broadcaster.emit("merge", "Merging extraction results...")
    merged = EvidenceMerger().merge(extractions)
    field_state.update(merged)
    await broadcaster.emit("merge", f"Evidence Merger: {merged.deduplication_stats} ... Field-State: {field_state.summary()}")

    draft = await synthesis_agent(project_id, brief, merged, field_state.export(), broadcaster)

    calibration, violations = validate(draft)
    field_state.update_from_validation(calibration, violations)
    retry_budget = 2
    while violations and retry_budget > 0:
        await broadcaster.emit("validate", f"Validation failed: {len(violations)} violations. Retrying...")
        calibration = await targeted_retry(calibration, violations)
        calibration, violations = validate(calibration)
        field_state.update_from_validation(calibration, violations)
        retry_budget -= 1

    if violations:
        for v in violations:
            calibration.coverage_gaps.append(v.description)
        for seg in calibration.segments:
            if any(v.segment_id == seg.segment_id for v in violations):
                seg.requires_human_review = True

    calibration.field_state_summary = field_state.export()
    await broadcaster.emit("validate", f"Final validation: {len(violations)} rules failed")
    
    await broadcaster.emit("done", f"RadiantPersonaCalibration ready")
    return calibration
