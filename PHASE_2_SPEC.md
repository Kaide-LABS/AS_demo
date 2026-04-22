# PHASE_2_SPEC.md — Real Parser Implementations, LLM-Wired Agents, and Theater Frontend

> For the execution agent. Covers Phase 2 (Hours 40-60 of the 72hr sprint).
> Phase 1 delivered the skeleton: schemas, rules engine, field-state engine, evidence merger,
> pipeline orchestrator, and contract tests — all passing. Parsers and extraction agents are
> stubbed. This phase replaces every stub with production logic.
> All SDK syntax verified against live documentation on 2026-04-22.

---

## 1. Scope

Phase 2 delivers three work streams:

| Stream | What | Hours |
|--------|------|-------|
| **A. Real parsers** | Replace all 8 mocked parsers with actual file processing | 40-46 |
| **B. LLM-wired agents** | Replace all 6 extraction agent stubs + triage with real Gemini calls | 46-54 |
| **C. Theater frontend** | Next.js drag-drop UI + SSE tail matching societies.io design | 54-60 |

**NOT in scope (Phase 3):** Enterprise connectors, conversational copilot, JWT auth, Redis SSE, prompt caching, cost monitoring.

---

## 2. Stream A: Real parser implementations

### 2.1 File: `parsers/pdf_parser.py`

```python
import io
from agents.client import generate_text, MODEL_PRO
from google.genai import types

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    Strategy:
    1. Attempt text extraction with pdfplumber:
       - pip already has it implicitly via pandas; if not, add pdfplumber==0.11.6
         to requirements.txt.
       - Actually, pdfplumber is NOT in requirements.txt. ADD it.
       - Extract text page-by-page. Concatenate.
       - Extract tables via pdfplumber.pages[i].extract_tables().
       - Convert each table to list[dict] using first row as headers.
    2. If total extracted text < 100 characters (scanned PDF):
       - Fallback: send raw file_bytes to Gemini 3.1 Pro multimodal vision.
       - Use generate_text(MODEL_PRO, contents=[...], thinking_level=MINIMAL)
       - Contents must be a list containing a Part with inline_data (mime_type="application/pdf", data=base64_encoded_bytes).
       - System instruction: "Extract all text, tables, and data from this PDF. Preserve table structure as markdown."
    3. Return (raw_text, tables, metadata).
       metadata = {"page_count": int, "extraction_method": "text" | "vision"}
    """
```

**New dependency:** Add `pdfplumber==0.11.6` to `requirements.txt`.

---

### 2.2 File: `parsers/image_parser.py`

```python
import base64
from agents.client import generate_text, MODEL_PRO
from google.genai import types

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. Detect MIME subtype from filename extension (.png, .jpg, .jpeg, .webp, .gif).
    2. Base64-encode file_bytes.
    3. Call generate_text(MODEL_PRO, contents=[...], thinking_level=MINIMAL):
       - Contents: a list with one dict containing:
         {"inline_data": {"mime_type": f"image/{ext}", "data": b64_string}}
       - System instruction: "Extract all text, tables, charts, and data from this image.
         Preserve any table structure as markdown tables."
    4. Parse the response text.
       - If response contains markdown tables, extract them into list[dict].
       - Otherwise tables = [].
    5. Return (raw_text, tables, {"extraction_method": "vision"}).
    """
```

---

### 2.3 File: `parsers/csv_parser.py`

```python
import io
import pandas as pd

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. Detect delimiter: try pd.read_csv with sep=None, engine='python' (auto-detect).
       Fallback to comma if detection fails.
    2. df = pd.read_csv(io.BytesIO(file_bytes), sep=detected_sep)
    3. raw_text = df.to_string(index=False, max_rows=500)
       (cap at 500 rows for token budget; note in metadata if truncated)
    4. tables = df.head(500).to_dict(orient='records')
    5. metadata = {
           "row_count": len(df),
           "column_names": list(df.columns),
           "truncated": len(df) > 500,
       }
    6. Return (raw_text, tables, metadata).
    """
```

---

### 2.4 File: `parsers/xlsx_parser.py`

```python
import io
import pandas as pd

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, engine='openpyxl')
       This returns dict[str, DataFrame].
    2. Concatenate all sheets:
       - For each sheet_name, df: prepend a header row "--- Sheet: {sheet_name} ---"
       - Concatenate raw text from all sheets.
    3. tables = combined_df.head(500).to_dict(orient='records')
    4. metadata = {
           "sheet_names": list(sheets.keys()),
           "total_rows": sum(len(df) for df in sheets.values()),
           "truncated": total_rows > 500,
       }
    5. Return (raw_text, tables, metadata).
    """
```

---

### 2.5 File: `parsers/spss_parser.py`

```python
import io
import pyreadstat

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. Write file_bytes to a temporary file (pyreadstat requires file path).
       Use tempfile.NamedTemporaryFile(suffix='.sav', delete=False).
    2. df, meta = pyreadstat.read_sav(temp_path)
    3. raw_text = df.to_csv(index=False)
       (cap at 500 rows for token budget)
    4. tables = df.head(500).to_dict(orient='records')
    5. metadata = {
           "row_count": len(df),
           "column_names": list(df.columns),
           "variable_labels": meta.column_names_to_labels,
           "value_labels": {k: dict(v) for k, v in meta.variable_value_labels.items()},
           "truncated": len(df) > 500,
       }
    6. Clean up temp file.
    7. Return (raw_text, tables, metadata).
    """
```

---

### 2.6 File: `parsers/docx_parser.py`

```python
import io
from docx import Document

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. doc = Document(io.BytesIO(file_bytes))
    2. Extract paragraphs with heading hierarchy:
       - For each paragraph, prefix with heading level if style.name starts with 'Heading'.
       - Concatenate all paragraph text with newlines.
    3. Extract tables:
       - For each table in doc.tables:
         - First row = headers.
         - Remaining rows = data.
         - Convert to list[dict].
    4. metadata = {
           "paragraph_count": len(doc.paragraphs),
           "table_count": len(doc.tables),
       }
    5. Return (raw_text, tables, metadata).
    """
```

---

### 2.7 File: `parsers/qsf_parser.py`

```python
import json

async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. Parse file_bytes as JSON.
    2. Navigate the Qualtrics .qsf structure:
       - root["SurveyElements"] contains all survey elements.
       - Filter for elements where "Element" == "SQ" (Survey Question).
       - For each question element:
         - Extract: QuestionID, QuestionText, QuestionType, Choices (if present),
           SubSelector, Selector.
    3. Build raw_text as a formatted question inventory:
       "Q1 (MC): What is your primary source of information?\n  1. Television\n  2. Social media\n  ..."
    4. tables = list of dicts with keys:
       question_id, question_text, question_type, choices (list[str])
    5. metadata = {"question_count": int, "survey_name": root.get("SurveyEntry", {}).get("SurveyName", "")}
    6. Return (raw_text, tables, metadata).

    Note: .qsf format varies across Qualtrics versions. Handle missing keys gracefully
    with .get() defaults. Do not crash on malformed exports.
    """
```

---

### 2.8 File: `parsers/txt_parser.py`

```python
async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """
    1. Try decode as UTF-8. If UnicodeDecodeError, fallback to latin-1.
    2. raw_text = decoded string.
    3. tables = [] (no structured data in plain text).
    4. metadata = {"encoding": detected_encoding, "char_count": len(raw_text)}
    5. Return (raw_text, tables, metadata).
    """
```

---

### 2.9 Requirements update

Add to `requirements.txt`:
```
pdfplumber==0.11.6
```

---

## 3. Stream B: LLM-wired extraction agents

### 3.1 Common pattern for all 6 agents

Every extraction agent must:

1. **Filter artifacts** by checking `plan.assignments` for an entry where `agent_name` matches this agent. Use only the `artifact_ids` listed in that assignment. If no assignment exists for this agent, return an empty `ExtractionResult` with `validation_passed=True`.

2. **Build the prompt** using the filtered artifacts' `raw_text` (concatenated, truncated to 100K chars if needed to stay under token limits).

3. **Define a Pydantic sub-schema** for this agent's output (see per-agent specs below).

4. **Call `generate_structured()`** with the sub-schema as `response_schema`.

5. **Continuous validation:** Wrap the call in a try/except. If Pydantic validation fails on the response, set `validation_passed=False` and populate `validation_errors`.

6. **Map the sub-schema output** into the standardized `ExtractionResult` format: populate `extracted_fields` dict keyed by target field paths from `plan.assignments[].target_fields`.

7. **Emit SSE event** via broadcaster.

### 3.2 File: `agents/triage.py` — Upgrade to real LLM

Replace the filename-heuristic fallback with an actual Gemini call:

```python
async def triage_agent(artifacts: list[SourceArtifact], broadcaster: TheaterBroadcaster) -> TriageManifest:
    """
    1. Build contents string with each artifact's filename + first 2000 chars of raw_text.
    2. If client is available:
       - Call generate_structured(MODEL_FLASH_LITE, contents, TriageManifest,
           thinking_level=types.ThinkingLevel.MINIMAL,
           system_instruction="Classify each document into exactly one category: ...")
       - Parse and return.
    3. If client is None (offline/demo):
       - Fall back to the existing filename-heuristic logic (keep current code as fallback).
    4. Emit one SSE event per artifact classified.
    """
```

### 3.3 File: `agents/segment_extractor.py`

**Model:** `MODEL_FLASH`, `thinking_level=LOW`

**Sub-schema:**
```python
class SegmentExtractionOutput(BaseModel):
    segments: list[ExtractedSegmentDraft]

class ExtractedSegmentDraft(BaseModel):
    segment_id: str
    label: str = Field(max_length=80)
    description: str = Field(max_length=600)
    weight: float = Field(gt=0.0, le=1.0)
    demographic_attributes: list[dict]   # free-form for extraction, validated later
    psychographic_attributes: list[dict]
    citations: list[dict]                # {artifact_id, locator, excerpt}
```

**System prompt:**
```
Extract named audience segments from this market research.
For each segment provide: a slug ID, human label, description, relative size weight
(weights across all segments should sum to approximately 1.0),
demographic attributes, and psychographic attributes.
Every claim must include a citation with the artifact_id, page/row locator, and a short excerpt.
```

**Mapping:** `extracted_fields = {"segments": [s.model_dump() for s in result.segments]}`

---

### 3.4 File: `agents/verbatim_distiller.py`

**Model:** `MODEL_FLASH`, `thinking_level=LOW`

**Sub-schema:**
```python
class VerbatimExtractionOutput(BaseModel):
    verbatims: list[VerbatimDraft]

class VerbatimDraft(BaseModel):
    text: str = Field(min_length=20, max_length=1200)
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    segment_id: str | None = None
    citation: dict
```

**System prompt:**
```
Extract representative direct quotes from transcripts and ethnographic research.
Each quote must be 20-1200 characters. Tag with sentiment (positive/neutral/negative/mixed)
and the audience segment it most likely represents (or null if unclear).
Include citation with artifact_id, locator (timestamp/page/paragraph), and excerpt.
Minimum 5 quotes per identified segment.
```

**Mapping:** `extracted_fields = {"segments[].verbatims": [v.model_dump() for v in result.verbatims]}`

---

### 3.5 File: `agents/demographic_normalizer.py`

**Model:** `MODEL_FLASH_LITE`, `thinking_level=MINIMAL`

**Sub-schema:**
```python
class DemographicExtractionOutput(BaseModel):
    demographic_fields: list[NormalizedDemographic]

class NormalizedDemographic(BaseModel):
    field_name: str    # Pulsar-compatible: age_range, gender_distribution, etc.
    segment_id: str | None = None
    value: str | float | list[str]
    citation: dict
```

**System prompt:**
```
Map demographic data to these standardized fields:
age_range, gender_distribution, income_bracket, education_level,
geographic_region, occupation_category.
Output only fields present in the source data. Do not invent demographics.
```

**Mapping:** `extracted_fields = {"segments[].demographic_attributes": [d.model_dump() for d in result.demographic_fields]}`

---

### 3.6 File: `agents/behavioral_extractor.py`

**Model:** `MODEL_FLASH`, `thinking_level=LOW`

**Sub-schema:**
```python
class BehavioralExtractionOutput(BaseModel):
    behavioral_attributes: list[BehavioralAttributeDraft]

class BehavioralAttributeDraft(BaseModel):
    key: str           # from CANONICAL_KEYS
    value: str | float | bool | list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    segment_id: str | None = None
    citations: list[dict]
```

**System prompt must include the full CANONICAL_KEYS set** from `rules_engine.py`:
```
Extract behavioral attributes using ONLY these canonical keys:
media_consumption, information_sources, content_consumption_format,
social_media_usage, digital_savviness, purchase_frequency, price_sensitivity,
brand_affinity, channel_preference, risk_tolerance, trust_in_institutions,
environmental_concern, health_consciousness, political_engagement,
work_life_priority, community_involvement, education_aspiration,
decision_making_style, technology_adoption, financial_literacy.
Do NOT use keys outside this set.
```

---

### 3.7 File: `agents/brand_tone_extractor.py`

**Model:** `MODEL_FLASH`, `thinking_level=LOW`

**Sub-schema:**
```python
class BrandToneExtractionOutput(BaseModel):
    constraints: list[BrandConstraintDraft]

class BrandConstraintDraft(BaseModel):
    constraint_type: Literal["tone", "forbidden_language", "messaging_guardrail", "voice_parameter"]
    description: str = Field(max_length=300)
    examples: list[str] = Field(max_length=5)
    citations: list[dict]
```

**System prompt:**
```
Extract brand voice and tone constraints from these documents.
Categories: tone (e.g., "authoritative but approachable"),
forbidden_language (words/phrases never to use),
messaging_guardrail (boundaries for messaging),
voice_parameter (specific voice attributes).
Include 1-5 concrete examples per constraint.
```

---

### 3.8 File: `agents/campaign_benchmark_extractor.py`

**Model:** `MODEL_FLASH`, `thinking_level=LOW`

**Sub-schema:**
```python
class CampaignBenchmarkExtractionOutput(BaseModel):
    benchmarks: list[CampaignBenchmarkDraft]

class CampaignBenchmarkDraft(BaseModel):
    metric_name: str
    baseline_value: float
    time_period: str
    channel: str | None = None
    citations: list[dict]
```

**System prompt:**
```
Extract campaign performance benchmarks and KPI baselines.
Include: metric name (e.g., email_open_rate, brand_awareness_pct),
numeric baseline value, time period (e.g., "Q4 2025"), and channel if applicable.
```

---

### 3.9 Agent sub-schema placement

All sub-schemas (`SegmentExtractionOutput`, `VerbatimExtractionOutput`, etc.) should be defined **inside their respective agent files**, NOT in `schemas.py`. These are internal extraction types, not API contract types. They do not need `ConfigDict(extra="forbid")`.

---

## 4. Stream C: Theater frontend

### 4.1 Directory structure

```
rcs-sidecar/
└── frontend/
    ├── package.json
    ├── next.config.js
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── public/
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx           # drag-drop upload + Theater panel
    │   └── globals.css
    └── components/
        ├── DropZone.tsx       # drag-drop file upload surface
        ├── TheaterPanel.tsx   # SSE event stream display
        ├── FileChip.tsx       # per-file classification badge
        ├── FieldStateBar.tsx  # progress bar from field-state updates
        └── LoadButton.tsx     # "Load into Simulation →" CTA
```

### 4.2 File: `app/page.tsx`

**Layout:** Two-column. Left: drop zone + file list. Right: Theater panel.

**State management:**
```typescript
const [files, setFiles] = useState<File[]>([])
const [jobId, setJobId] = useState<string | null>(null)
const [events, setEvents] = useState<TheaterEvent[]>([])
const [calibration, setCalibration] = useState<any>(null)
const [isProcessing, setIsProcessing] = useState(false)
```

**Upload flow:**
1. User drops files onto `DropZone`.
2. On submit, `POST /v1/calibrate` via `fetch` with `FormData`.
3. Simultaneously, open `EventSource` to `GET /v1/calibrate/{job_id}/stream`.
4. Append each SSE event to the `events` array.
5. When response returns, set `calibration` and show `LoadButton`.

**Critical UX constraint:** The upload `POST` and SSE stream must connect to the **same Cloud Run instance** (Phase 1 uses in-memory broadcaster). In Phase 2, this is acceptable for demo. Phase 3 introduces Redis Pub/Sub for multi-instance.

### 4.3 Component: `DropZone.tsx`

```
- Large drop surface (min 300px height)
- Accepts: .pdf, .sav, .csv, .xlsx, .qsf, .docx, .txt, .png, .jpg, .jpeg
- Max 25 files
- Per-file size check (50MB) client-side
- Drag-over glow animation
- File list with remove buttons
- "Calibrate" primary button (disabled until ≥1 file)
```

### 4.4 Component: `TheaterPanel.tsx`

```
- Right panel, fixed height, scrollable
- Each event rendered as a single line with:
  - Timestamp badge (T+{ts_ms/1000}s)
  - Stage icon (emoji per stage from the PRD Magic Moment spec)
  - Message text
- Auto-scroll to bottom on new events
- Expandable rows: click to see meta (model, input_tokens, output_tokens, latency_ms)
- Stage-specific colors:
  - ingest: gray
  - triage: blue
  - field_state: purple
  - extract: green
  - merge: orange
  - synthesize: indigo
  - validate: yellow
  - done: green bold
  - error: red
```

### 4.5 Component: `FieldStateBar.tsx`

```
- Horizontal stacked progress bar
- Segments: validated (green), candidate (yellow), unknown (gray), blocked (red)
- Label: "28/34 validated, 4 candidate, 2 unknown"
- Updates on every field_state SSE event
- Parse the message string for counts (regex: /(\d+) validated, (\d+) candidate, (\d+) unknown/)
```

### 4.6 Component: `LoadButton.tsx`

```
- Disabled until calibration is received
- Text: "Load into Simulation →"
- On click: logs calibration JSON to console (in Phase 2, no downstream integration)
- Styled to match societies.io primary CTA (indigo/purple)
```

### 4.7 Tailwind config

```
- Match societies.io brand: dark background (#0a0a0a or #111827), white text
- Primary accent: indigo-500 (#6366f1)
- Font: Inter or system sans-serif
- Monospace for Theater events: JetBrains Mono or system monospace
```

### 4.8 Frontend dependencies

```json
{
  "dependencies": {
    "next": "^15.3.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "tailwindcss": "^4.1.0"
  },
  "devDependencies": {
    "typescript": "^5.8.0",
    "@types/react": "^19.1.0",
    "@types/node": "^22.0.0"
  }
}
```

---

## 5. Integration tests to add

### 5.1 File: `tests/test_parsers.py`

```python
def test_csv_parser_reads_real_csv():
    """Create a small CSV in memory, parse it, assert row_count and column_names in metadata."""

def test_txt_parser_handles_utf8():
    """Encode a string with unicode, parse, assert decoded correctly."""

def test_txt_parser_falls_back_to_latin1():
    """Encode a string with latin-1 chars, parse, assert no crash."""

def test_docx_parser_extracts_paragraphs():
    """Create a minimal .docx with python-docx, parse, assert paragraphs in raw_text."""
```

### 5.2 File: `tests/test_agents.py`

```python
def test_triage_filename_fallback():
    """Test the offline filename-heuristic classifier with known filenames."""

def test_extraction_agent_skips_unassigned():
    """Pass a plan with no assignment for this agent, assert empty ExtractionResult."""
```

---

## 6. Execution order

| Order | File(s) | Depends on | Est. LOC |
|-------|---------|------------|----------|
| 1 | `requirements.txt` — add pdfplumber | nothing | 1 line |
| 2 | `parsers/txt_parser.py` | nothing | ~15 |
| 3 | `parsers/csv_parser.py` | pandas | ~25 |
| 4 | `parsers/xlsx_parser.py` | pandas, openpyxl | ~30 |
| 5 | `parsers/docx_parser.py` | python-docx | ~30 |
| 6 | `parsers/qsf_parser.py` | json (stdlib) | ~40 |
| 7 | `parsers/spss_parser.py` | pyreadstat | ~30 |
| 8 | `parsers/pdf_parser.py` | pdfplumber, agents/client | ~40 |
| 9 | `parsers/image_parser.py` | agents/client | ~25 |
| 10 | `agents/triage.py` — upgrade | agents/client | ~40 |
| 11 | All 6 extraction agents | agents/client, schemas | ~300 total |
| 12 | `tests/test_parsers.py` | parsers | ~60 |
| 13 | `tests/test_agents.py` | agents | ~40 |
| 14 | `frontend/*` — full Next.js app | nothing (standalone) | ~400 |

**Total estimated LOC:** ~1,075

---

## 7. What is NOT in this spec (Phase 3)

- Enterprise connectors (Google Drive, SharePoint, S3)
- Conversational interview copilot
- Per-section user approval UI
- JWT authentication (keeping API key from Phase 1)
- Redis/Pub/Sub for multi-instance SSE
- Prompt caching optimization for Gemini Pro calls
- Cost monitoring dashboard
- Demo video production
- Production Cloud Run deployment tuning
