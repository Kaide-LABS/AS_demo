import structlog
from typing import Literal
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact, SourceCitation
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types

AGENT_NAME = "verbatim_distiller"
logger = structlog.get_logger()

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


async def verbatim_distiller(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Distilling verbatims from {len(filtered)} artifacts...", {"model": MODEL_FLASH})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={"segments[].verbatims": []}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(MODEL_FLASH, contents, VerbatimExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        if not result.verbatims:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments[].verbatims": [v.model_dump() for v in result.verbatims]},
            citations=coerce_citations([v.citation for v in result.verbatims if v.citation], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
