import structlog
from typing import Literal, Optional
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact, SourceCitation
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types
from validators import nia_corpus

AGENT_NAME = "segment_extractor"
logger = structlog.get_logger()

NIA_QUERY = (
    "audience segments, customer types, persona groups, demographic clusters, "
    "behavioral cohorts, named segments, market subgroups, target personas, "
    "segment definitions, segment weights, segment descriptions"
)


class ExtractedSegmentDraft(BaseModel):
    segment_id: str
    label: str = Field(max_length=80)
    description: str = Field(max_length=600)
    weight: float = Field(gt=0.0, le=1.0)
    demographic_attributes: list[dict] = []
    psychographic_attributes: list[dict] = []
    citations: list[dict] = []


class SegmentExtractionOutput(BaseModel):
    segments: list[ExtractedSegmentDraft]


SYSTEM_PROMPT = """Extract named audience segments from this market research.
For each segment provide: a slug ID, human label, description, relative size weight
(weights across all segments should sum to approximately 1.0),
demographic attributes, and psychographic attributes.
Every claim must include a citation with artifact_id, page/row locator, and a short excerpt.
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
    """Query the engagement corpus, keep only chunks from this agent's
    assigned artifacts, format for Gemini. Returns None on failure or if no
    relevant chunks come back (caller falls back to truncation)."""
    chunks = await nia_corpus.query_engagement_corpus(
        engagement_source_id, NIA_QUERY, top_k=20
    )
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


async def segment_extractor(
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
            contents = await _build_nia_contents(
                engagement_source_id, assigned_ids, filtered
            )
            if contents:
                await broadcaster.emit(
                    "extract",
                    f"Nia retrieved chunks for segments from {len(filtered)} artifacts...",
                    {"model": MODEL_FLASH, "path": "nia"},
                )
        except Exception as e:
            logger.warning("nia_retrieval_failed_falling_back", agent=AGENT_NAME, error=str(e))
            contents = None

    if contents is None:
        contents = _build_truncated_contents(filtered)
        await broadcaster.emit(
            "extract",
            f"Extracting segments from {len(filtered)} artifacts...",
            {"model": MODEL_FLASH, "path": "truncation"},
        )

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={"segments": []}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(
            MODEL_FLASH, contents, SegmentExtractionOutput,
            thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT,
        )
        if not result.segments:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments": [s.model_dump() for s in result.segments]},
            citations=coerce_citations([c for s in result.segments for c in s.citations], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(
            agent_name=AGENT_NAME, extracted_fields={}, citations=[],
            validation_passed=False, validation_errors=[str(e)],
        )
