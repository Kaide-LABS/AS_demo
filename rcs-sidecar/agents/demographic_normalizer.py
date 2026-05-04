import json
import os
import structlog
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH_LITE, client
from agents._citations import coerce_citations
from google.genai import types
from retrieval import chroma_corpus as nia_corpus

AGENT_NAME = "demographic_normalizer"
logger = structlog.get_logger()

NIA_QUERY = (
    "demographic breakdown, age range, gender distribution, income bracket, "
    "education level, geographic region, occupation category, household composition, "
    "ethnicity, employment status, segment demographics"
)
NIA_TOP_K = 20


class NormalizedDemographic(BaseModel):
    field_name: str
    segment_id: str | None = None
    value: str | float | list[str]
    citation: dict


class DemographicExtractionOutput(BaseModel):
    demographic_fields: list[NormalizedDemographic]


SYSTEM_PROMPT = """Map demographic data to these standardized fields:
age_range, gender_distribution, income_bracket, education_level,
geographic_region, occupation_category.
Output only fields present in the source data. Do not invent demographics.
If this artifact contains ANY content relevant to the fields above, you MUST populate the corresponding arrays with at least one evidence node. Return an empty array ONLY if the artifact contains absolutely no relevant content whatsoever."""


def _build_truncated_contents(filtered: list[SourceArtifact]) -> str:
    return "\n\n".join(
        f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}"
        for a in filtered
    )


async def _build_nia_contents(
    engagement_source_id: str,
    assigned_artifact_ids: set[str],
    filtered: list[SourceArtifact],
) -> Optional[str]:
    chunks = await nia_corpus.query_engagement_corpus(
        engagement_source_id, NIA_QUERY, top_k=NIA_TOP_K
    )

    if os.getenv("RCS_CHUNK_DIAGNOSTIC") == "true":
        diag_path = Path(os.getenv(
            "RCS_CHUNK_DIAGNOSTIC_PATH_DEMOGRAPHIC",
            os.getenv("RCS_CHUNK_DIAGNOSTIC_PATH", str(Path.home() / "rcs_chunks_demographic.json")),
        ))
        diag = {
            "agent": AGENT_NAME,
            "query": NIA_QUERY,
            "engagement_source_id": engagement_source_id,
            "assigned_artifact_ids": sorted(assigned_artifact_ids),
            "all_chunks": [
                {
                    "artifact_id": c["artifact_id"],
                    "score": c["score"],
                    "locator": c.get("locator", ""),
                    "content_preview": c["content"][:500],
                    "content_length": len(c["content"]),
                }
                for c in chunks
            ],
        }
        try:
            diag_path.parent.mkdir(parents=True, exist_ok=True)
            diag_path.write_text(json.dumps(diag, indent=2), encoding="utf-8")
        except Exception:
            pass

    if not chunks:
        return None
    chunks = [c for c in chunks if c["artifact_id"] in assigned_artifact_ids]
    if not chunks:
        return None
    by_id = {a.artifact_id: a for a in filtered}
    parts = []
    for c in chunks:
        art = by_id.get(c["artifact_id"])
        filename = art.filename if art else c["artifact_id"]
        parts.append(
            f"[{filename} | artifact_id={c['artifact_id']} | {c['locator']} | "
            f"score={c['score']:.2f}]\n{c['content']}"
        )
    return "\n\n".join(parts)


async def demographic_normalizer(
    artifacts: list[SourceArtifact],
    plan: FieldExtractionPlan,
    broadcaster: TheaterBroadcaster,
    engagement_source_id: Optional[str] = None,
) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    assigned_ids = set(assigned.artifact_ids)

    contents: Optional[str] = None
    if nia_corpus.EXTRACTION_ENABLED and engagement_source_id:
        try:
            contents = await _build_nia_contents(engagement_source_id, assigned_ids, filtered)
            if contents:
                await broadcaster.emit(
                    "extract",
                    f"Nia retrieved chunks for demographics from {len(filtered)} artifacts...",
                    {"model": MODEL_FLASH_LITE, "path": "nia"},
                )
        except Exception as e:
            logger.warning("nia_retrieval_failed_falling_back", agent=AGENT_NAME, error=str(e))
            contents = None

    if contents is None:
        contents = _build_truncated_contents(filtered)
        await broadcaster.emit(
            "extract",
            f"Normalizing demographics from {len(filtered)} artifacts...",
            {"model": MODEL_FLASH_LITE, "path": "truncation"},
        )

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(
            MODEL_FLASH_LITE, contents, DemographicExtractionOutput,
            thinking_level=types.ThinkingLevel.MINIMAL, system_instruction=SYSTEM_PROMPT,
        )
        if not result.demographic_fields:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments[].demographic_attributes": [d.model_dump() for d in result.demographic_fields]},
            citations=coerce_citations([d.citation for d in result.demographic_fields if d.citation], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(
            agent_name=AGENT_NAME, extracted_fields={}, citations=[],
            validation_passed=False, validation_errors=[str(e)],
        )
