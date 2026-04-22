import base64
import os
from agents.client import generate_text, MODEL_PRO, client
from google.genai import types

MIME_MAP = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}


async def parse(file_bytes: bytes, filename: str):
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_MAP.get(ext, "image/png")

    if not client:
        return "image content (no Gemini client available)", [], {"extraction_method": "unavailable"}

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    raw_text, _ = await generate_text(
        model=MODEL_PRO,
        contents=[{"inline_data": {"mime_type": mime, "data": b64}}],
        thinking_level=types.ThinkingLevel.LOW,
        system_instruction="Extract all text, tables, charts, and data from this image. Preserve any table structure as markdown tables.",
    )
    return raw_text, [], {"extraction_method": "vision"}
