import os
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

MODEL_FLASH_LITE = "gemini-3.1-flash-lite-preview"
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"

try:
    client = genai.Client()
except Exception:
    client = None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((Exception,)),
)
async def generate_structured(
    model: str,
    contents: str | list,
    response_schema: type[BaseModel],
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> BaseModel:
    if not client: return response_schema() # mock for tests/demo if no client
    config = {
        "response_mime_type": "application/json",
        "response_json_schema": response_schema.model_json_schema(),
    }
    if thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    if system_instruction:
        config["system_instruction"] = system_instruction
        
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config),
    )
    try:
        return response_schema.model_validate_json(response.text)
    except Exception as e:
        raise ValueError(f"Failed to parse generation for model {model}: {e}\nRaw output: {response.text[:2000]}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((Exception,)),
)
async def generate_text(
    model: str,
    contents: str | list,
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> str:
    if not client: return "mock"
    config = {}
    if thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    if system_instruction:
        config["system_instruction"] = system_instruction
        
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config) if config else None,
    )
    return response.text
