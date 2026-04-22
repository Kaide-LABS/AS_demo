from typing import Literal
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact, SourceCitation
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from google.genai import types

AGENT_NAME = "segment_extractor"

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
Every claim must include a citation with artifact_id, page/row locator, and a short excerpt."""


async def segment_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Extracting segments from {len(filtered)} artifacts...", {"model": MODEL_FLASH})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={"segments": []}, citations=[], validation_passed=True)

    try:
        result = await generate_structured(MODEL_FLASH, contents, SegmentExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments": [s.model_dump() for s in result.segments]},
            citations=[SourceCitation(**c) for s in result.segments for c in s.citations if len(c) >= 3],
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
