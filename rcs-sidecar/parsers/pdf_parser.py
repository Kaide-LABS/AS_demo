import io
import pdfplumber
from agents.client import generate_text, MODEL_PRO, client
from google.genai import types
import base64


async def parse(file_bytes: bytes, filename: str):
    text_parts = []
    tables = []
    page_count = 0

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for tbl in (page.extract_tables() or []):
                if tbl and len(tbl) > 1:
                    headers = [str(h or "") for h in tbl[0]]
                    for row in tbl[1:]:
                        tables.append(dict(zip(headers, [str(c or "") for c in row])))

    raw_text = "\n\n".join(text_parts)

    if len(raw_text.strip()) < 100 and client:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        raw_text = await generate_text(
            model=MODEL_PRO,
            contents=[{"inline_data": {"mime_type": "application/pdf", "data": b64}}],
            thinking_level=types.ThinkingLevel.LOW,
            system_instruction="Extract all text, tables, and data from this PDF. Preserve table structure as markdown.",
        )
        method = "vision"
    else:
        method = "text"

    metadata = {"page_count": page_count, "extraction_method": method}
    return raw_text, tables, metadata
