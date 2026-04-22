from pydantic import BaseModel
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH_LITE, client
from google.genai import types

AGENT_NAME = "demographic_normalizer"

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
Output only fields present in the source data. Do not invent demographics."""


async def demographic_normalizer(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Normalizing demographics from {len(filtered)} artifacts...", {"model": MODEL_FLASH_LITE})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    try:
        result, usage = await generate_structured(MODEL_FLASH_LITE, contents, DemographicExtractionOutput,
                                           thinking_level=types.ThinkingLevel.MINIMAL, system_instruction=SYSTEM_PROMPT)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"segments[].demographic_attributes": [d.model_dump() for d in result.demographic_fields]},
            citations=[], validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
