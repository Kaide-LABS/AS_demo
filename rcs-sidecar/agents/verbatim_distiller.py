import json
import os
import structlog
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact, SourceCitation
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types
from validators import nia_corpus

AGENT_NAME = "verbatim_distiller"
logger = structlog.get_logger()

NIA_QUERY = (
    "direct quotes, customer testimonials, interview excerpts, focus group statements, "
    "first-person responses, what respondents said, verbatim quotes, in-their-own-words, "
    "participant statements, recorded responses"
)
NIA_TOP_K = 30


class VerbatimDraft(BaseModel):
    text: str = Field(min_length=20, max_length=1200)
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    segment_id: str | None = None
    citation: dict


class VerbatimExtractionOutput(BaseModel):
    verbatims: list[VerbatimDraft]


SYSTEM_PROMPT = """Extract representative direct quotes from transcripts and ethnographic research.
Each quote must be 20-1200 characters. Tag with sentiment (positive/neutral/negative/mixed)
and the audience segment it most likely represents (or null if unclear).
Include citation with artifact_id, locator (timestamp/page/paragraph), and excerpt.
Aim for at least 5 quotes per identified segment.
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
            "RCS_CHUNK_DIAGNOSTIC_PATH_VERBATIM",
            os.getenv("RCS_CHUNK_DIAGNOSTIC_PATH", str(Path.home() / "rcs_chunks_verbatim.json")),
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


async def verbatim_distiller(
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
                    f"Nia retrieved chunks for verbatims from {len(filtered)} artifacts...",
                    {"model": MODEL_FLASH, "path": "nia"},
                )
        except Exception as e:
            logger.warning("nia_retrieval_failed_falling_back", agent=AGENT_NAME, error=str(e))
            contents = None

    if contents is None:
        contents = _build_truncated_contents(filtered)
        await broadcaster.emit(
            "extract",
            f"Distilling verbatims from {len(filtered)} artifacts...",
            {"model": MODEL_FLASH, "path": "truncation"},
        )

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={"segments[].verbatims": []}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(
            MODEL_FLASH, contents, VerbatimExtractionOutput,
            thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT,
        )
        if not result.verbatims:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments[].verbatims": [v.model_dump() for v in result.verbatims]},
            citations=coerce_citations([v.citation for v in result.verbatims if v.citation], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(
            agent_name=AGENT_NAME, extracted_fields={}, citations=[],
            validation_passed=False, validation_errors=[str(e)],
        )
