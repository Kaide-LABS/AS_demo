import asyncio
from fastapi import UploadFile
from schemas import RadiantPersonaCalibration, MergedEvidence, RuleViolation
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
from agents.client import generate_structured, MODEL_PRO

async def synthesis_agent(brief: str, evidence: MergedEvidence, field_state: dict, broadcaster: TheaterBroadcaster) -> RadiantPersonaCalibration:
    await broadcaster.emit("synthesize", "Synthesizing calibration (deep reasoning)...")
    # For Phase 1 mocked without real LLM call unless connected:
    return RadiantPersonaCalibration(
        project_id="p1",
        target_audience_brief=brief,
        segments=[],
        global_provenance=[],
        coverage_gaps=[],
        field_state_summary=field_state
    )

async def targeted_retry(calibration: RadiantPersonaCalibration, violations: list[RuleViolation]) -> RadiantPersonaCalibration:
    # Full regeneration via PRO
    return calibration

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
    extractions = await asyncio.gather(
        segment_extractor(artifacts, plan, broadcaster),
        verbatim_distiller(artifacts, plan, broadcaster),
        demographic_normalizer(artifacts, plan, broadcaster),
        behavioral_extractor(artifacts, plan, broadcaster),
        brand_tone_extractor(artifacts, plan, broadcaster),
        campaign_benchmark_extractor(artifacts, plan, broadcaster)
    )
    passed = sum(1 for e in extractions if e.validation_passed)
    await broadcaster.emit("extract", f"Continuous validation: {passed}/{len(extractions)} extractors passed")

    await broadcaster.emit("merge", "Merging extraction results...")
    merged = EvidenceMerger().merge(extractions)
    field_state.update(merged)
    await broadcaster.emit("merge", f"Evidence Merger: {merged.deduplication_stats} ... Field-State: {field_state.summary()}")

    draft = await synthesis_agent(brief, merged, field_state.export(), broadcaster)

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
