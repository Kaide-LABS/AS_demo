import os
import json
import asyncio
import structlog
from google import genai
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

MODEL_FLASH_LITE = "gemini-3.1-flash-lite-preview"
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"

try:
    client = genai.Client()
except Exception:
    client = None


def _extract_json_object(text: str) -> str:
    """Pull the first complete top-level JSON object/array from text.
    Gemini sometimes wraps output in markdown fences or appends stray braces —
    this walks the bracket stack and returns the balanced substring.
    """
    if not text:
        return text
    s = text.strip()
    # strip markdown code fences
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    # find first { or [
    start = None
    for i, ch in enumerate(s):
        if ch in "{[":
            start = i
            break
    if start is None:
        return s
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return s[start:i+1]
    return s[start:]


def _extract_response_text(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None)
    if callable(text):
        try:
            return text()
        except Exception:
            return None
    return text


def _should_retry_exception(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        if status_code is not None and 400 <= status_code < 500 and status_code != 429:
            logger.error("gemini_client_error_non_retryable", error=str(exc), status_code=status_code)
            response_text = _extract_response_text(exc)
            if response_text:
                logger.error("gemini_client_error_response", response_text=response_text)
            return False
    return True


def _log_retry_failure(retry_state) -> None:
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        if exc is not None:
            logger.error("gemini_request_retry", attempt=retry_state.attempt_number, error=str(exc))


def _call_generate_content_sync(model: str, contents: str | list, config: types.GenerateContentConfig | None):
    try:
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as exc:
        logger.error("gemini_generate_content_failed", error=str(exc))
        response_text = _extract_response_text(exc)
        if response_text:
            logger.error("gemini_generate_content_response", response_text=response_text)
        raise


async def _call_generate_content(model: str, contents: str | list, config: types.GenerateContentConfig | None):
    """Run the sync Gemini call in a thread so it doesn't block the event loop."""
    return await asyncio.to_thread(_call_generate_content_sync, model, contents, config)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_should_retry_exception),
    after=_log_retry_failure,
    before_sleep=_log_retry_failure,
    reraise=True,
)
async def generate_structured(
    model: str,
    contents: str | list,
    response_schema: type[BaseModel],
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> tuple[BaseModel, dict, str]:
    if not client:
        try:
            return response_schema(), {}, ""
        except Exception:
            return response_schema.model_construct(), {}, ""
    # Gemini's Structured Output rejects schemas with additionalProperties/$defs/anyOf
    # (common in pydantic-emitted schemas). We rely on mime_type + prompt + pydantic
    # validation at parse time instead.
    schema_hint = json.dumps(response_schema.model_json_schema(), indent=2)
    combined_instruction = (
        (system_instruction + "\n\n") if system_instruction else ""
    ) + f"Return ONLY valid JSON matching this schema:\n{schema_hint}"
    config = {
        "response_mime_type": "application/json",
        "system_instruction": combined_instruction,
    }
    if thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
        config["temperature"] = 1.0

    response = await _call_generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config),
    )
    try:
        usage = {'input_tokens': response.usage_metadata.prompt_token_count if response.usage_metadata else 0, 'output_tokens': response.usage_metadata.candidates_token_count if response.usage_metadata else 0}
        cleaned = _extract_json_object(response.text)
        return response_schema.model_validate_json(cleaned), usage, response.text
    except Exception as e:
        raise ValueError(f"Failed to parse generation for model {model}: {e}\nRaw output: {response.text[:2000]}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_should_retry_exception),
    after=_log_retry_failure,
    before_sleep=_log_retry_failure,
    reraise=True,
)
async def generate_text(
    model: str,
    contents: str | list,
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> tuple[str, dict]:
    if not client: return "mock", {}
    config = {}
    if thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
        config["temperature"] = 1.0
    if system_instruction:
        config["system_instruction"] = system_instruction
        
    response = await _call_generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config) if config else None,
    )
    usage = {'input_tokens': response.usage_metadata.prompt_token_count if response.usage_metadata else 0, 'output_tokens': response.usage_metadata.candidates_token_count if response.usage_metadata else 0}
    return response.text, usage

async def generate_structured_cached(
    model: str,
    cached_content_name: str,
    contents: str | list,
    response_schema: type[BaseModel],
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> tuple[BaseModel, dict]:
    if not client: return response_schema(), {}
    schema_hint = json.dumps(response_schema.model_json_schema(), indent=2)
    combined_instruction = (
        (system_instruction + "\n\n") if system_instruction else ""
    ) + f"Return ONLY valid JSON matching this schema:\n{schema_hint}"
    config = {
        "cached_content": cached_content_name,
        "response_mime_type": "application/json",
        "system_instruction": combined_instruction,
    }
    if thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
        config["temperature"] = 1.0
        
    response = await _call_generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config),
    )
    usage = {
        'input_tokens': response.usage_metadata.prompt_token_count if response.usage_metadata else 0, 
        'output_tokens': response.usage_metadata.candidates_token_count if response.usage_metadata else 0
    }
    try:
        return response_schema.model_validate_json(_extract_json_object(response.text)), usage
    except Exception as e:
        raise ValueError(f"Failed to parse cached generation for model {model}: {e}\nRaw output: {response.text[:2000]}")
