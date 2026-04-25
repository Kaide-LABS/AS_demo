import structlog
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types
from rules_engine import CANONICAL_KEYS

AGENT_NAME = "behavioral_extractor"
logger = structlog.get_logger()

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
and citations with artifact_id, locator, and excerpt.
If this artifact contains ANY content relevant to the fields above, you MUST populate the corresponding arrays with at least one evidence node. Return an empty array ONLY if the artifact contains absolutely no relevant content whatsoever."""


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
        result, usage, raw_text = await generate_structured(MODEL_FLASH, contents, BehavioralExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        if not result.behavioral_attributes:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={
                "segments[].behavioral_attributes": [a.model_dump() for a in result.behavioral_attributes],
            },
            citations=coerce_citations([c for a in result.behavioral_attributes for c in a.citations], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
