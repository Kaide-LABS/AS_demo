import structlog
from typing import Literal
from pydantic import BaseModel, Field
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types

AGENT_NAME = "brand_tone_extractor"
logger = structlog.get_logger()

class BrandConstraintDraft(BaseModel):
    constraint_type: Literal["tone", "forbidden_language", "messaging_guardrail", "voice_parameter"]
    description: str = Field(max_length=300)
    examples: list[str] = Field(max_length=5)
    citations: list[dict] = []

class BrandToneExtractionOutput(BaseModel):
    constraints: list[BrandConstraintDraft]

SYSTEM_PROMPT = """Extract brand voice and tone constraints from these documents.
Categories: tone (e.g., "authoritative but approachable"),
forbidden_language (words/phrases never to use),
messaging_guardrail (boundaries for messaging),
voice_parameter (specific voice attributes).
Include 1-5 concrete examples per constraint with citations.
If this artifact contains ANY content relevant to the fields above, you MUST populate the corresponding arrays with at least one evidence node. Return an empty array ONLY if the artifact contains absolutely no relevant content whatsoever."""


async def brand_tone_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Extracting brand tone from {len(filtered)} artifacts...", {"model": MODEL_FLASH})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(MODEL_FLASH, contents, BrandToneExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        if not result.constraints:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"brand_constraints": [c.model_dump() for c in result.constraints]},
            citations=coerce_citations([cc for c in result.constraints for cc in c.citations], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
