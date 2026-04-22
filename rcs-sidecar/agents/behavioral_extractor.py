from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from google.genai import types
from rules_engine import CANONICAL_KEYS

AGENT_NAME = "behavioral_extractor"

class BehavioralAttributeDraft(BaseModel):
    key: str
    value: str | float | bool | list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    segment_id: str | None = None
    citations: list[dict] = []

class BehavioralExtractionOutput(BaseModel):
    behavioral_attributes: list[BehavioralAttributeDraft]

SYSTEM_PROMPT = f"""Extract behavioral attributes using ONLY these canonical keys:
{", ".join(sorted(CANONICAL_KEYS))}.
Do NOT use keys outside this set.
For each attribute provide: key, value, confidence (0-1), segment_id if applicable,
and citations with artifact_id, locator, and excerpt."""


async def behavioral_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Extracting behavioral attributes from {len(filtered)} artifacts...", {"model": MODEL_FLASH})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    try:
        result = await generate_structured(MODEL_FLASH, contents, BehavioralExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={
                "segments[].behavioral_attributes": [a.model_dump() for a in result.behavioral_attributes],
            },
            citations=[], validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
