from agents.client import generate_text, MODEL_PRO
from google.genai import types
from schemas import FieldState
from theater import TheaterBroadcaster
import json

async def generate_next_question(
    field_states: dict[str, FieldState],
    conversation: list[dict],
    broadcaster: TheaterBroadcaster,
) -> str:
    system_prompt = """You are an interview planner for enterprise audience calibration.
Given the current field state (which fields are filled vs missing)
and the conversation so far, generate the single most valuable
next question to ask the user.

Rules:
- Every question must map to one or more missing schema fields.
- Never ask broad or redundant questions.
- If a file upload would be more efficient than a text answer, suggest it.
- Keep questions tightly tied to missing JSON fields."""

    missing_fields = {k: v.value for k, v in field_states.items() if v != FieldState.VALIDATED}
    contents = f"Missing Fields:\n{json.dumps(missing_fields, indent=2)}\n\nConversation:\n{json.dumps(conversation, indent=2)}"
    
    question, usage = await generate_text(
        model=MODEL_PRO,
        contents=contents,
        thinking_level=types.ThinkingLevel.MEDIUM,
        system_instruction=system_prompt
    )
    await broadcaster.emit("copilot", "Question generated", meta=usage)
    return question
