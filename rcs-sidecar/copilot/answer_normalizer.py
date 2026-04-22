from pydantic import BaseModel
from typing import Union, List
from agents.client import generate_structured, MODEL_FLASH
from google.genai import types
from theater import TheaterBroadcaster

class NormalizedAnswer(BaseModel):
    field_path: str
    value: Union[str, float, bool, List[str]]
    confidence: float
    needs_file_evidence: bool

class AnswerNormalizationOutput(BaseModel):
    normalized: List[NormalizedAnswer]

async def normalize_answer(
    answer: str,
    target_fields: List[str],
    broadcaster: TheaterBroadcaster,
) -> AnswerNormalizationOutput:
    system_prompt = """Converts free-text user answer into typed candidate values
for specific schema fields. Flags when a file upload would
provide stronger evidence than the text answer alone.

CRITICAL: Your response must be valid JSON matching the provided schema.
Do not include markdown code fences, explanatory text, or any content
outside the JSON object."""

    contents = f"User Answer: {answer}\nTarget Fields: {target_fields}"
    
    result, usage = await generate_structured(
        model=MODEL_FLASH,
        contents=contents,
        response_schema=AnswerNormalizationOutput,
        thinking_level=types.ThinkingLevel.LOW,
        system_instruction=system_prompt
    )
    await broadcaster.emit("copilot", "Answer normalized", meta=usage)
    return result
