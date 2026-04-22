# PHASE_1_SPEC.md — Exhaustive File-by-File Technical Blueprint

> For the execution agent. Covers ONLY Phase 1 (Hours 0-40 of the 48-72hr sprint).
> Do NOT implement Phase 2 features (connectors, conversational copilot, per-section approval UI).
> All SDK syntax verified against live documentation on 2026-04-22.

---

## 1. Project structure

```
rcs-sidecar/
├── main.py                     # FastAPI app, routes, lifespan
├── schemas.py                  # All Pydantic v2 models
├── pipeline.py                 # Top-level orchestrator
├── field_state.py              # Field-State Engine (pure Python)
├── evidence_merger.py          # Evidence Merger (pure Python)
├── rules_engine.py             # Deterministic validation rules (pure Python)
├── agents/
│   ├── __init__.py
│   ├── client.py               # Shared google-genai client + helper
│   ├── triage.py               # Triage Agent
│   ├── segment_extractor.py    # 3a
│   ├── verbatim_distiller.py   # 3b
│   ├── demographic_normalizer.py # 3c
│   ├── behavioral_extractor.py # 3d
│   ├── brand_tone_extractor.py # 3e
│   └── campaign_benchmark_extractor.py # 3f
├── parsers/
│   ├── __init__.py
│   ├── detect.py               # MIME detection + router
│   ├── pdf_parser.py
│   ├── image_parser.py
│   ├── spss_parser.py          # .sav / .sps via pyreadstat
│   ├── csv_parser.py           # .csv via pandas 3.0
│   ├── xlsx_parser.py          # .xlsx via openpyxl + pandas
│   ├── qsf_parser.py           # Qualtrics .qsf JSON
│   ├── docx_parser.py          # .docx via python-docx
│   └── txt_parser.py           # raw text
├── theater.py                  # SSE event broadcaster
├── requirements.txt
├── Dockerfile
├── .env.example
├── tests/
│   ├── __init__.py
│   ├── test_contract.py
│   ├── test_field_state.py
│   ├── test_evidence_merger.py
│   ├── test_rules_engine.py
│   └── fixtures/
│       ├── kantar_brand_tracker.sav
│       ├── ipsos_segments.pdf
│       ├── earnings_transcripts.docx
│       └── crm_holders.csv
└── deploy.sh                   # gcloud run deploy wrapper
```

---

## 2. File: `requirements.txt`

```
google-genai==1.73.1
fastapi==0.136.0
pydantic==2.13.3
pydantic-core==2.46.3
uvicorn[standard]==0.45.0
python-multipart==0.0.26
sse-starlette==3.3.4
pandas==3.0.2
pyreadstat==1.3.4
openpyxl==3.1.5
python-docx==1.2.0
python-magic==0.4.27
httpx==0.28.1
tenacity==9.1.4
orjson==3.11.8
```

Runtime: **Python 3.12** (Cloud Run base image `python:3.12-slim`).

---

## 3. File: `schemas.py` — Complete Pydantic v2 models

Every model below must use `model_config = ConfigDict(extra="forbid")` unless explicitly stated otherwise.

### 3.1 Enums

```python
class ArtifactType(str, Enum):
    """9 values. Used by triage agent and source citations."""
    BRAND_TRACKER = "brand_tracker"
    FOCUS_GROUP_TRANSCRIPT = "focus_group_transcript"
    SEGMENTATION_STUDY = "segmentation_study"
    CRM_EXPORT = "crm_export"
    SURVEY_INSTRUMENT = "survey_instrument"
    ETHNOGRAPHY = "ethnography"
    COMPETITIVE_INTEL = "competitive_intel"
    VERBATIM_CORPUS = "verbatim_corpus"
    OTHER = "other"

class FieldState(str, Enum):
    """4 lifecycle states for the Field-State Engine."""
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    BLOCKED = "blocked"
```

### 3.2 Internal pipeline models (not in API response)

```python
class SourceArtifact(BaseModel):
    """Output of parsers/detect.py. Internal only."""
    artifact_id: str          # UUID4 string, generated at parse time
    filename: str
    artifact_type: ArtifactType | None = None  # populated by triage agent
    raw_text: str             # full extracted text
    tables: list[dict] = []   # tabular data as list of row-dicts
    metadata: dict = {}       # parser-specific: page_count, row_count, etc.
    size_bytes: int

class TriageManifest(BaseModel):
    """Output of triage agent."""
    classifications: list[ArtifactClassification]

class ArtifactClassification(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_strategy: str = Field(description="Which extractor agents should process this artifact")

class FieldExtractionPlan(BaseModel):
    """Output of FieldStateEngine.plan_extractions(). Maps agents to target fields."""
    assignments: list[AgentAssignment]

class AgentAssignment(BaseModel):
    agent_name: str           # e.g. "segment_extractor"
    target_fields: list[str]  # schema field paths this agent should populate
    artifact_ids: list[str]   # which artifacts to process
    priority: int = Field(ge=1, le=10)

class ExtractionResult(BaseModel):
    """Standardized output from every extraction agent."""
    agent_name: str
    extracted_fields: dict    # keyed by target schema field path
    citations: list[SourceCitation]
    validation_passed: bool
    validation_errors: list[str] = []

class MergedEvidence(BaseModel):
    """Output of EvidenceMerger. Input to synthesis agent."""
    evidence_by_field: dict[str, list[EvidenceNode]]
    contradictions: list[Contradiction]
    deduplication_stats: dict  # {"total_nodes": int, "unique_after_merge": int}

class EvidenceNode(BaseModel):
    field_path: str
    value: str | float | bool | list[str] | dict
    confidence: float = Field(ge=0.0, le=1.0)
    source_authority: Literal["primary_research", "secondary", "inferred"]
    citation: SourceCitation

class Contradiction(BaseModel):
    field_path: str
    competing_values: list[EvidenceNode]
    resolution_needed: bool = True
```

### 3.3 API response models (in final JSON output)

```python
class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    artifact_type: ArtifactType
    locator: str              # "page 4", "row 127", "timestamp 14:32", "question Q7a"
    excerpt: str = Field(max_length=500)

class Verbatim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=1200)
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    citation: SourceCitation

class BehavioralAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str                  # must be in CANONICAL_KEYS (enforced by rules engine)
    value: str | float | bool | list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[SourceCitation] = Field(min_length=1)

class BrandConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint_type: Literal["tone", "forbidden_language", "messaging_guardrail", "voice_parameter"]
    description: str = Field(max_length=300)
    examples: list[str] = Field(max_length=5)
    citations: list[SourceCitation] = Field(min_length=1)

class CampaignBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_name: str          # e.g. "email_open_rate", "brand_awareness_pct"
    baseline_value: float
    time_period: str          # e.g. "Q4 2025", "FY2025"
    channel: str | None = None
    citations: list[SourceCitation] = Field(min_length=1)

class PersonaSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str           # lowercase slug, e.g. "institutional_investors"
    label: str = Field(max_length=80)
    description: str = Field(max_length=600)
    weight: float = Field(gt=0.0, le=1.0)
    demographic_attributes: list[BehavioralAttribute]
    psychographic_attributes: list[BehavioralAttribute]
    behavioral_attributes: list[BehavioralAttribute]
    information_sources: list[str]
    verbatims: list[Verbatim] = Field(min_length=5)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = False

class RadiantPersonaCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.1.0"] = "1.1.0"
    project_id: str
    target_audience_brief: str
    segments: list[PersonaSegment] = Field(min_length=1, max_length=8)
    brand_constraints: list[BrandConstraint] = Field(default_factory=list)
    campaign_benchmarks: list[CampaignBenchmark] = Field(default_factory=list)
    global_provenance: list[SourceCitation]
    coverage_gaps: list[str]
    field_state_summary: dict[str, FieldState]

    @field_validator("segments")
    @classmethod
    def weights_sum_to_one(cls, v: list[PersonaSegment]) -> list[PersonaSegment]:
        total = sum(s.weight for s in v)
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"segment weights sum to {total}, must equal 1.0 ± 0.01")
        return v

class TheaterEvent(BaseModel):
    ts_ms: int                # milliseconds since job start
    stage: Literal[
        "ingest", "triage", "field_state", "extract",
        "merge", "synthesize", "validate", "done", "error"
    ]
    message: str
    meta: dict = {}           # optional: model, input_tokens, output_tokens, latency_ms
```

### 3.4 Request/internal models

```python
class CalibrateRequest(BaseModel):
    """Internal representation after FastAPI form parsing."""
    project_id: str
    target_audience_brief: str = Field(max_length=2000)
    artifacts: list[SourceArtifact]

class RuleViolation(BaseModel):
    rule_name: str
    field_path: str
    segment_id: str | None = None
    description: str
```

---

## 4. File: `main.py` — FastAPI application

### 4.1 Imports

```python
from fastapi import FastAPI, UploadFile, Form, HTTPException
from sse_starlette import EventSourceResponse
from schemas import RadiantPersonaCalibration, TheaterEvent
from pipeline import run_calibration
from theater import TheaterBroadcaster
import uuid, asyncio
```

### 4.2 App initialization

```python
app = FastAPI(
    title="Radiant Calibration Sidecar",
    version="1.1.0",
    docs_url="/docs",       # Swagger UI for demo
    redoc_url=None,
)
```

### 4.3 Route: `GET /healthz`

- Returns `{"status": "ok", "version": "1.1.0"}`
- No auth required
- Used by Cloud Run health checks

### 4.4 Route: `POST /v1/calibrate`

**Signature:**
```python
@app.post("/v1/calibrate", response_model=RadiantPersonaCalibration)
async def calibrate(
    project_id: str = Form(...),
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = ...,
) -> RadiantPersonaCalibration:
```

**Logic flow:**
1. Validate `len(artifacts) >= 1` and `len(artifacts) <= 25`. Raise `HTTPException(400)` otherwise.
2. Validate each file size `<= 50 * 1024 * 1024` bytes. Raise `HTTPException(413)` for oversized files.
3. Generate a `job_id` (UUID4 string).
4. Create a `TheaterBroadcaster` instance for this `job_id`.
5. Start `run_calibration()` as the main pipeline, passing the broadcaster for SSE events.
6. Return the `RadiantPersonaCalibration` JSON on success.
7. On pipeline failure, return `HTTPException(500)` with a structured error body containing the `job_id` and failure stage.

**Auth:** In Phase 1, use a simple `X-API-Key` header check against an environment variable `RCS_API_KEY`. JWT validation is Phase 2.

### 4.5 Route: `GET /v1/calibrate/{job_id}/stream`

**Signature:**
```python
@app.get("/v1/calibrate/{job_id}/stream")
async def stream_theater(job_id: str) -> EventSourceResponse:
```

**Logic flow:**
1. Look up the `TheaterBroadcaster` for this `job_id`. Return `HTTPException(404)` if not found.
2. Return an `EventSourceResponse` wrapping the broadcaster's async generator.
3. Each SSE event is a JSON-serialized `TheaterEvent`.
4. The stream closes when the broadcaster emits a `stage="done"` or `stage="error"` event.

**SSE format per event:**
```
event: theater
data: {"ts_ms": 1420, "stage": "extract", "message": "Extracting segments...", "meta": {"model": "gemini-3-flash-preview", "input_tokens": 12400}}
```

### 4.6 In-memory job store

```python
# Simple dict for Phase 1. NOT production-grade — Cloud Run stateless means
# the SSE stream must connect to the same instance as the calibrate call.
# This is acceptable for demo/single-instance. Phase 2: use Redis or Pub/Sub.
_broadcasters: dict[str, TheaterBroadcaster] = {}
```

---

## 5. File: `theater.py` — SSE event broadcaster

### 5.1 Class: `TheaterBroadcaster`

```python
class TheaterBroadcaster:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._queue: asyncio.Queue[TheaterEvent] = asyncio.Queue()
        self._start_time_ms: int  # set on first emit

    async def emit(self, stage: str, message: str, meta: dict = {}) -> None:
        """Push a TheaterEvent to the SSE queue. Called by pipeline stages."""
        ...

    async def stream(self) -> AsyncGenerator[dict, None]:
        """Async generator yielding SSE-formatted dicts. Consumed by EventSourceResponse."""
        ...
        # Yields {"event": "theater", "data": event.model_dump_json()} for each event
        # Stops when stage == "done" or "error"
```

**Requirements:**
- `emit()` must be non-blocking (just puts on the queue).
- `stream()` must be an async generator that `await`s `_queue.get()`.
- `ts_ms` is computed as `current_time_ms - self._start_time_ms`.
- Use `orjson` for JSON serialization inside `model_dump_json()` if performance matters, otherwise Pydantic's built-in is fine.

---

## 6. File: `parsers/detect.py` — Format detection + routing

### 6.1 Function: `detect_and_parse`

```python
async def detect_and_parse(upload: UploadFile) -> SourceArtifact:
    """
    1. Read file bytes into memory.
    2. Use python-magic to detect MIME type.
    3. Route to the correct parser based on MIME + file extension:
       - application/pdf → pdf_parser.parse()
       - image/* → image_parser.parse()
       - application/x-spss-sav → spss_parser.parse()
       - text/csv → csv_parser.parse()
       - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet → xlsx_parser.parse()
       - application/json AND .qsf extension → qsf_parser.parse()
       - application/vnd.openxmlformats-officedocument.wordprocessingml.document → docx_parser.parse()
       - text/plain → txt_parser.parse()
       - fallback: txt_parser.parse() with a warning in metadata
    4. Generate artifact_id as uuid4().
    5. Return SourceArtifact with raw_text, tables, metadata, size_bytes.
    """
```

### 6.2 Individual parsers

Each parser module exposes a single function:

```python
async def parse(file_bytes: bytes, filename: str) -> tuple[str, list[dict], dict]:
    """Returns (raw_text, tables, metadata)."""
```

**Parser-specific requirements:**

| Parser | Module | Key logic |
|--------|--------|-----------|
| `pdf_parser` | `parsers/pdf_parser.py` | Use `gemini-3.1-pro-preview` multimodal vision for scanned PDFs (images). For text-based PDFs, use `PyPDF2` or `pdfplumber` for fast text extraction. Fallback to Gemini vision only if text extraction yields < 100 chars. |
| `image_parser` | `parsers/image_parser.py` | Send image bytes directly to `gemini-3.1-pro-preview` with a prompt: "Extract all text, tables, and data from this image. Preserve table structure as markdown." |
| `spss_parser` | `parsers/spss_parser.py` | Use `pyreadstat.read_sav()`. Return variable labels as metadata. Convert DataFrame to string via `.to_csv(index=False)`. Return column metadata (variable labels, value labels) in `metadata`. |
| `csv_parser` | `parsers/csv_parser.py` | Use `pandas.read_csv()`. Auto-detect delimiter. Return `df.to_string()` as raw_text. Return `df.to_dict(orient='records')` as tables. Report `row_count`, `column_names` in metadata. |
| `xlsx_parser` | `parsers/xlsx_parser.py` | Use `pandas.read_excel(engine='openpyxl')`. Handle multi-sheet workbooks: concatenate all sheets. Return same structure as csv_parser. |
| `qsf_parser` | `parsers/qsf_parser.py` | Parse the Qualtrics `.qsf` JSON structure. Extract question inventory: question ID, question text, answer choices, question type. Return as structured text. |
| `docx_parser` | `parsers/docx_parser.py` | Use `python-docx`. Extract all paragraphs + tables. Preserve heading hierarchy. Return tables as list of row-dicts. |
| `txt_parser` | `parsers/txt_parser.py` | Decode bytes as UTF-8 (fallback latin-1). Return raw text. No tables. Metadata: `{"encoding": detected_encoding}`. |

**Critical constraint for pdf_parser and image_parser:** These are the ONLY parsers that call a Gemini model. All other parsers are pure Python. This keeps cost bounded for non-vision artifacts.

---

## 7. File: `agents/client.py` — Shared Gemini client

### 7.1 Client initialization

```python
from google import genai
from google.genai import types

# Client auto-detects Vertex AI from environment variables:
#   GOOGLE_GENAI_USE_VERTEXAI=True
#   GOOGLE_CLOUD_PROJECT=<project>
#   GOOGLE_CLOUD_LOCATION=global
client = genai.Client()
```

### 7.2 Helper: `generate_structured`

```python
async def generate_structured(
    model: str,
    contents: str | list,
    response_schema: type[BaseModel],
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> BaseModel:
    """
    Wrapper for structured output generation.

    1. Build config:
       config = {
           "response_mime_type": "application/json",
           "response_json_schema": response_schema.model_json_schema(),
       }
    2. If thinking_level is set, add:
       config["thinking_config"] = types.ThinkingConfig(
           thinking_level=thinking_level
       )
    3. If system_instruction is set, add it to config.
    4. Call: response = client.models.generate_content(
           model=model,
           contents=contents,
           config=types.GenerateContentConfig(**config),
       )
    5. Parse: result = response_schema.model_validate_json(response.text)
    6. Return result.

    On parse failure: raise a structured error with model name, raw response text
    (truncated to 2000 chars), and the validation error.
    """
```

### 7.3 Helper: `generate_text`

```python
async def generate_text(
    model: str,
    contents: str | list,
    thinking_level: types.ThinkingLevel | None = None,
    system_instruction: str | None = None,
) -> str:
    """Simple text generation without structured output. Used by pdf/image parsers."""
```

### 7.4 Model constants

```python
MODEL_FLASH_LITE = "gemini-3.1-flash-lite-preview"
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"
```

### 7.5 Retry logic

Wrap all `generate_content` calls with `tenacity`:
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((Exception,)),  # narrow this to API errors
)
```

---

## 8. File: `agents/triage.py` — Triage Agent

### 8.1 Function: `triage_agent`

```python
async def triage_agent(
    artifacts: list[SourceArtifact],
    broadcaster: TheaterBroadcaster,
) -> TriageManifest:
```

**Model:** `MODEL_FLASH_LITE` with `thinking_level=types.ThinkingLevel.MINIMAL`

**Prompt structure:**
```
System: You are a document classifier for enterprise market research artifacts.
Classify each document into exactly one category.
Categories: brand_tracker, focus_group_transcript, segmentation_study,
crm_export, survey_instrument, ethnography, competitive_intel,
verbatim_corpus, other.
Also specify which extraction agents should process each artifact.

User: [For each artifact, include: filename, first 2000 chars of raw_text, metadata summary]
```

**Response schema:** `TriageManifest` (passed as `response_json_schema`)

**SSE events emitted:**
- One event per artifact classified: `stage="triage"`, message includes filename and assigned type.

**Latency target:** < 2 seconds for up to 25 artifacts.

---

## 9. File: `field_state.py` — Field-State Engine

### 9.1 Class: `FieldStateEngine`

**Constructor:**
```python
def __init__(self, schema: type[BaseModel] = RadiantPersonaCalibration):
    """
    Walk the schema recursively and register every leaf field path.
    Example field paths:
      "segments[].weight"
      "segments[].demographic_attributes[].key"
      "segments[].verbatims[].text"
      "brand_constraints[].description"
      "campaign_benchmarks[].metric_name"
    All fields start as FieldState.UNKNOWN.
    """
```

**Method: `plan_extractions`**
```python
def plan_extractions(self, manifest: TriageManifest) -> FieldExtractionPlan:
    """
    Mapping rules (deterministic, no LLM):
      - SEGMENTATION_STUDY → segment_extractor (target: segments[].*)
      - BRAND_TRACKER → segment_extractor + campaign_benchmark_extractor
      - FOCUS_GROUP_TRANSCRIPT → verbatim_distiller
      - VERBATIM_CORPUS → verbatim_distiller
      - CRM_EXPORT → demographic_normalizer
      - ETHNOGRAPHY → behavioral_extractor + verbatim_distiller
      - COMPETITIVE_INTEL → behavioral_extractor
      - SURVEY_INSTRUMENT → segment_extractor + behavioral_extractor
      - OTHER → behavioral_extractor (low priority)

    Brand tone extractor runs on ALL artifacts (extracts brand voice from any source).
    Campaign benchmark extractor runs on BRAND_TRACKER and COMPETITIVE_INTEL.

    Priority: required fields first (segments, weights), optional fields second
    (brand_constraints, campaign_benchmarks).
    """
```

**Method: `update`**
```python
def update(self, merged_evidence: MergedEvidence) -> None:
    """For each field in merged_evidence.evidence_by_field:
       if field has >= 1 evidence node → transition UNKNOWN → CANDIDATE"""
```

**Method: `update_from_validation`**
```python
def update_from_validation(self, calibration, violations: list[RuleViolation]) -> None:
    """
    For each field in the calibration:
      if no violation touches this field → CANDIDATE → VALIDATED
      if a violation touches this field and retry_budget exhausted → CANDIDATE → BLOCKED
    """
```

**Method: `export`**
```python
def export(self) -> dict[str, FieldState]:
    """Return the full field-state map for inclusion in the API response."""
```

**SSE events:** The pipeline calls `broadcaster.emit(stage="field_state", ...)` after each state transition batch, reporting counts: `"28/34 validated, 4 candidate, 2 unknown"`.

---

## 10. Files: `agents/*.py` — Six parallel extraction agents

### 10.1 Common pattern (all 6 agents follow this)

```python
async def <agent_name>(
    artifacts: list[SourceArtifact],
    plan: FieldExtractionPlan,
    broadcaster: TheaterBroadcaster,
) -> ExtractionResult:
    """
    1. Filter artifacts to only those assigned by the plan for this agent.
    2. Filter target_fields to only those assigned by the plan.
    3. Build a prompt that includes:
       - System instruction specific to this agent's domain
       - The target field names and their Pydantic types
       - The artifact text (concatenated, truncated if needed)
    4. Call generate_structured() with the agent's Pydantic sub-schema.
    5. CONTINUOUS VALIDATION: Pydantic-validate the response immediately.
       If validation fails, set validation_passed=False and log errors.
    6. Emit SSE event with stage="extract", agent name, token counts.
    7. Return ExtractionResult.
    """
```

### 10.2 Agent-specific details

#### `agents/segment_extractor.py` (3a)

**Model:** `MODEL_FLASH` with `thinking_level=types.ThinkingLevel.LOW`

**Response sub-schema:**
```python
class SegmentExtractionOutput(BaseModel):
    segments: list[ExtractedSegmentDraft]

class ExtractedSegmentDraft(BaseModel):
    segment_id: str
    label: str
    description: str
    weight: float
    demographic_attributes: list[dict]
    psychographic_attributes: list[dict]
    citations: list[SourceCitation]
```

**System prompt key phrases:** "Extract named audience segments from this market research. Include segment labels, descriptions, relative size weights, and demographic/psychographic attributes. Every claim must include a citation with page/row reference."

---

#### `agents/verbatim_distiller.py` (3b)

**Model:** `MODEL_FLASH` with `thinking_level=types.ThinkingLevel.LOW`

**Response sub-schema:**
```python
class VerbatimExtractionOutput(BaseModel):
    verbatims: list[VerbatimDraft]

class VerbatimDraft(BaseModel):
    text: str
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    segment_id: str | None  # best-guess segment association
    citation: SourceCitation
```

**System prompt key phrases:** "Extract representative direct quotes from transcripts and ethnographic research. Tag each quote with sentiment and the audience segment it most likely represents. Minimum 20 characters per quote."

---

#### `agents/demographic_normalizer.py` (3c)

**Model:** `MODEL_FLASH_LITE` with `thinking_level=types.ThinkingLevel.MINIMAL`

**Response sub-schema:**
```python
class DemographicExtractionOutput(BaseModel):
    demographic_fields: list[NormalizedDemographic]

class NormalizedDemographic(BaseModel):
    field_name: str           # Pulsar-compatible field name
    segment_id: str | None
    value: str | float | list[str]
    citation: SourceCitation
```

**System prompt key phrases:** "Map the demographic data in this dataset to the following standardized field names: age_range, gender_distribution, income_bracket, education_level, geographic_region, occupation_category. Output only fields present in the data."

---

#### `agents/behavioral_extractor.py` (3d)

**Model:** `MODEL_FLASH` with `thinking_level=types.ThinkingLevel.LOW`

**Response sub-schema:**
```python
class BehavioralExtractionOutput(BaseModel):
    behavioral_attributes: list[BehavioralAttributeDraft]

class BehavioralAttributeDraft(BaseModel):
    key: str                  # should match CANONICAL_KEYS
    value: str | float | bool | list[str]
    confidence: float
    segment_id: str | None
    citations: list[SourceCitation]
```

**System prompt key phrases:** "Extract behavioral attributes: media consumption habits, purchase behaviors, information sources, brand affinities, decision-making patterns. Use only canonical attribute keys from this list: [CANONICAL_KEYS]. Every attribute must have at least one citation."

---

#### `agents/brand_tone_extractor.py` (3e)

**Model:** `MODEL_FLASH` with `thinking_level=types.ThinkingLevel.LOW`

**Response sub-schema:**
```python
class BrandToneExtractionOutput(BaseModel):
    constraints: list[BrandConstraintDraft]

class BrandConstraintDraft(BaseModel):
    constraint_type: Literal["tone", "forbidden_language", "messaging_guardrail", "voice_parameter"]
    description: str
    examples: list[str]
    citations: list[SourceCitation]
```

**System prompt key phrases:** "Extract brand voice and tone constraints: approved tone descriptors, forbidden language, messaging guardrails, voice parameters. Include specific examples from the source documents."

---

#### `agents/campaign_benchmark_extractor.py` (3f)

**Model:** `MODEL_FLASH` with `thinking_level=types.ThinkingLevel.LOW`

**Response sub-schema:**
```python
class CampaignBenchmarkExtractionOutput(BaseModel):
    benchmarks: list[CampaignBenchmarkDraft]

class CampaignBenchmarkDraft(BaseModel):
    metric_name: str
    baseline_value: float
    time_period: str
    channel: str | None
    citations: list[SourceCitation]
```

**System prompt key phrases:** "Extract campaign performance benchmarks: KPI baselines, conversion rates, engagement metrics, awareness scores. Include the time period and channel for each metric."

---

## 11. File: `evidence_merger.py` — Deterministic Evidence Merger

### 11.1 Class: `EvidenceMerger`

**Method: `merge`**
```python
def merge(self, extractions: list[ExtractionResult]) -> MergedEvidence:
    """
    Pure Python. No LLM calls.

    Algorithm:
    1. COLLECT: Iterate all ExtractionResult objects. For each extracted_fields dict,
       key every value by its target schema field path.

    2. DEDUPLICATE: For each field path, compare evidence nodes by
       (artifact_id, locator) tuple. If two nodes have the same source,
       keep the one with higher confidence. Log deduplication count.

    3. DETECT CONTRADICTIONS: For each field path, if multiple evidence nodes
       provide different values for the same field:
       - If values are numeric and within 10% of each other → average them,
         mark as "reconciled"
       - If values are categorical and disagree → create a Contradiction object
         with resolution_needed=True

    4. RANK: Sort evidence nodes per field by source_authority:
       primary_research (weight 3) > secondary (weight 2) > inferred (weight 1)
       Then by confidence descending.

    5. EMIT: Return MergedEvidence with evidence_by_field, contradictions list,
       and deduplication_stats.
    """
```

**SSE events:** `stage="merge"`, message reports: `"Evidence Merger: {total_nodes} evidence nodes → {unique} unique, {contradictions} contradictions flagged"`.

---

## 12. File: `agents/synthesis.py` — Synthesis Agent (not in agents/ to emphasize it's the consolidator)

Actually, place this in `pipeline.py` as an inline function or in `agents/synthesis.py`.

### 12.1 Function: `synthesis_agent`

```python
async def synthesis_agent(
    brief: str,
    evidence: MergedEvidence,
    field_state: dict[str, FieldState],
    broadcaster: TheaterBroadcaster,
) -> RadiantPersonaCalibration:
```

**Model:** `MODEL_PRO` with `thinking_level=types.ThinkingLevel.HIGH`, `location=global`

**Input construction:**
```
System: You are an enterprise audience calibration synthesizer.
You will receive a merged evidence graph from multiple extraction agents.
Your job is to produce a single RadiantPersonaCalibration JSON object.

Rules:
- Create 3-8 named segments. Segment weights MUST sum to 1.0.
- Every attribute must cite at least one source artifact.
- Each segment must have at least 5 verbatims.
- Resolve any contradictions flagged in the evidence.
- For fields marked as UNKNOWN in the field state, note them in coverage_gaps.
- Do NOT invent data. If evidence is insufficient, set requires_human_review=true.

User:
Target audience brief: {brief}

Field state: {json.dumps(field_state)}

Evidence graph:
{serialized MergedEvidence — use orjson for speed}

Contradictions requiring resolution:
{serialized contradictions list}
```

**Response schema:** `RadiantPersonaCalibration` (passed as `response_json_schema`)

**Token budget awareness:** The Evidence Merger has already reduced the raw artifact text to an evidence graph. Typical input: 150K-500K tokens (down from 200K-800K raw). This keeps most calls in the cheaper ≤200K pricing tier ($2/$12 instead of $4/$18).

**SSE events:** `stage="synthesize"`, message: `"Synthesizing calibration ({token_count} tokens, deep reasoning)..."`. Emit a second event when complete with latency.

---

## 13. File: `rules_engine.py` — Deterministic validation

### 13.1 Rule functions

Each rule is a pure function with signature:
```python
def rule_name(calibration: RadiantPersonaCalibration) -> list[RuleViolation]:
    """Returns empty list if passes, list of violations if fails."""
```

**Rule 1: `weights_sum_to_one`**
- `sum(seg.weight for seg in calibration.segments)` must be in `[0.99, 1.01]`.
- On violation: `RuleViolation(rule_name="weights_sum_to_one", field_path="segments[].weight", description=f"weights sum to {total}")`.

**Rule 2: `every_attribute_has_citation`**
- For every `BehavioralAttribute` in every segment (demographic, psychographic, behavioral): `len(attr.citations) >= 1`.
- Return one violation per attribute with zero citations.

**Rule 3: `verbatims_per_segment_minimum`**
- For every segment: `len(seg.verbatims) >= 5`.
- Violation includes `segment_id`.

**Rule 4: `canonical_attribute_vocabulary`**
- Define `CANONICAL_KEYS: set[str]` with the allowed attribute key vocabulary.
- For every `BehavioralAttribute.key`: must be in `CANONICAL_KEYS`.
- Suggested initial set (expand as needed):
  ```python
  CANONICAL_KEYS = {
      "media_consumption", "purchase_frequency", "brand_affinity",
      "channel_preference", "risk_tolerance", "price_sensitivity",
      "technology_adoption", "social_media_usage", "information_sources",
      "decision_making_style", "trust_in_institutions", "environmental_concern",
      "health_consciousness", "political_engagement", "financial_literacy",
      "community_involvement", "digital_savviness", "content_consumption_format",
      "work_life_priority", "education_aspiration",
  }
  ```

**Rule 5: `confidence_monotonic_with_sources`**
- For every attribute: `confidence <= sqrt(len(citations) / 10) + 0.1`.
- This bounds confidence to evidence density. An attribute with 1 citation cannot claim 0.95 confidence.

**Rule 6: `no_pii_in_verbatims`**
- Regex scan all `Verbatim.text` for:
  - Email patterns: `r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'`
  - Phone patterns: `r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'`
  - SSN patterns: `r'\b\d{3}-\d{2}-\d{4}\b'`
- Return violation with the offending text (truncated).

**Rule 7: `provenance_completeness`**
- Every segment must have at least one citation that traces to a real artifact in `global_provenance`.
- Cross-reference `artifact_id` values.

**Rule 8: `brand_constraints_have_examples`**
- Every `BrandConstraint` must have `len(examples) >= 1`.

### 13.2 Orchestrator: `validate`

```python
def validate(calibration: RadiantPersonaCalibration) -> tuple[RadiantPersonaCalibration, list[RuleViolation]]:
    """
    Run all RULES in sequence.
    Return the calibration object and the full list of violations.
    If no violations, the calibration is certified valid.
    """
    violations = []
    for rule in RULES:
        violations.extend(rule(calibration))
    return calibration, violations
```

---

## 14. File: `pipeline.py` — Top-level orchestrator

### 14.1 Function: `run_calibration`

```python
async def run_calibration(
    project_id: str,
    target_audience_brief: str,
    uploads: list[UploadFile],
    broadcaster: TheaterBroadcaster,
) -> RadiantPersonaCalibration:
```

**Step-by-step logic:**

```
Step 1: INGEST
  - broadcaster.emit("ingest", "Parsing {len(uploads)} files...")
  - artifacts = await asyncio.gather(*[detect_and_parse(f) for f in uploads])
  - broadcaster.emit("ingest", f"Parsed {len(artifacts)} artifacts")

Step 2: TRIAGE
  - broadcaster.emit("triage", "Classifying artifacts...")
  - manifest = await triage_agent(artifacts, broadcaster)
  - Update each artifact's artifact_type from the manifest

Step 2b: FIELD-STATE ENGINE
  - field_state = FieldStateEngine()
  - extraction_plan = field_state.plan_extractions(manifest)
  - broadcaster.emit("field_state", f"{field_state.count_unknown()} fields required, 0 populated")

Step 3: PARALLEL EXTRACTION
  - broadcaster.emit("extract", "Running 6 extraction agents in parallel...")
  - extractions = await asyncio.gather(
        segment_extractor(artifacts, extraction_plan, broadcaster),
        verbatim_distiller(artifacts, extraction_plan, broadcaster),
        demographic_normalizer(artifacts, extraction_plan, broadcaster),
        behavioral_extractor(artifacts, extraction_plan, broadcaster),
        brand_tone_extractor(artifacts, extraction_plan, broadcaster),
        campaign_benchmark_extractor(artifacts, extraction_plan, broadcaster),
    )
  - Count how many passed continuous validation
  - broadcaster.emit("extract", f"Continuous validation: {passed}/{total} extractors passed")

Step 4: EVIDENCE MERGER
  - broadcaster.emit("merge", "Merging extraction results...")
  - merged = EvidenceMerger().merge(extractions)
  - field_state.update(merged)
  - broadcaster.emit("merge", f"Evidence Merger: {stats}... Field-State: {field_state.summary()}")

Step 5: SYNTHESIS
  - broadcaster.emit("synthesize", f"Synthesizing calibration ({token_estimate} tokens)...")
  - draft = await synthesis_agent(
        brief=target_audience_brief,
        evidence=merged,
        field_state=field_state.export(),
        broadcaster=broadcaster,
    )

Step 6: VALIDATE + RETRY
  - calibration, violations = rules_engine.validate(draft)
  - field_state.update_from_validation(calibration, violations)
  - retry_budget = 2
  - while violations and retry_budget > 0:
      broadcaster.emit("validate", f"Validation failed: {len(violations)} violations. Retrying...")
      calibration = await targeted_retry(calibration, violations)
      calibration, violations = rules_engine.validate(calibration)
      field_state.update_from_validation(calibration, violations)
      retry_budget -= 1

  - if violations:
      for v in violations:
          calibration.coverage_gaps.append(v.description)
      for seg in calibration.segments:
          if any(v.segment_id == seg.segment_id for v in violations):
              seg.requires_human_review = True

  - calibration.field_state_summary = field_state.export()
  - broadcaster.emit("validate", f"Final validation: {8 - len(violations)}/8 rules passed")

Step 7: DONE
  - broadcaster.emit("done", f"RadiantPersonaCalibration ready: {len(calibration.segments)} segments")
  - return calibration
```

### 14.2 Function: `targeted_retry`

```python
async def targeted_retry(
    calibration: RadiantPersonaCalibration,
    violations: list[RuleViolation],
) -> RadiantPersonaCalibration:
    """
    Model: MODEL_PRO with thinking_level=MEDIUM
    Prompt: includes the specific violations and asks the model to fix ONLY those fields.
    Response schema: RadiantPersonaCalibration
    """
```

---

## 15. File: `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install libmagic for python-magic
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 16. File: `deploy.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"

gcloud run deploy rcs-sidecar \
  --source=. \
  --region=us-central1 \
  --service-account=rcs-sa@${PROJECT}.iam.gserviceaccount.com \
  --cpu=2 --memory=2Gi \
  --min-instances=1 \
  --max-instances=50 \
  --concurrency=40 \
  --cpu-boost \
  --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global" \
  --no-allow-unauthenticated
```

---

## 17. File: `.env.example`

```
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
RCS_API_KEY=your-demo-api-key
```

---

## 18. File: `tests/test_contract.py`

### 18.1 `test_schema_roundtrip_fixture`

- Load a known-good `RadiantPersonaCalibration` JSON fixture from `tests/fixtures/`.
- Parse it with `RadiantPersonaCalibration.model_validate_json()`.
- Serialize it back with `.model_dump_json()`.
- Parse again. Assert equality.

### 18.2 `test_rules_engine_rejects_bad_weights`

- Create a `RadiantPersonaCalibration` with segments summing to 0.85.
- Run `rules_engine.validate()`.
- Assert `weights_sum_to_one` violation is present.

### 18.3 `test_rules_engine_rejects_missing_citations`

- Create a segment with a `BehavioralAttribute` with `citations=[]`.
- Run `rules_engine.validate()`.
- Assert `every_attribute_has_citation` violation is present.

### 18.4 `test_rules_engine_catches_pii`

- Create a verbatim containing `"Contact john@example.com for details"`.
- Run `rules_engine.validate()`.
- Assert `no_pii_in_verbatims` violation is present.

### 18.5 `test_field_state_lifecycle`

- Initialize `FieldStateEngine`.
- Assert all fields start as `UNKNOWN`.
- Call `update()` with mock evidence.
- Assert populated fields are `CANDIDATE`.
- Call `update_from_validation()` with no violations.
- Assert fields are `VALIDATED`.

### 18.6 `test_evidence_merger_deduplication`

- Create two `ExtractionResult` objects with overlapping citations (same artifact_id + locator).
- Run `EvidenceMerger.merge()`.
- Assert deduplication_stats shows reduction.

### 18.7 `test_live_smoke` (skipped locally)

- Upload the 4-file fixture bundle to `/v1/calibrate`.
- Assert HTTP 200.
- Parse response as `RadiantPersonaCalibration`.
- Assert `schema_version == "1.1.0"`.
- Assert `len(segments) >= 1`.
- Assert `field_state_summary` is present.
- Mark: `@pytest.mark.skipif(not os.getenv("RCS_SMOKE"), reason="Cloud Run smoke only")`

---

## 19. Canonical keys vocabulary

The execution agent must define this set in `rules_engine.py` and also reference it in the behavioral_extractor prompt:

```python
CANONICAL_KEYS = {
    # Media & information
    "media_consumption", "information_sources", "content_consumption_format",
    "social_media_usage", "digital_savviness",
    # Purchase & economic
    "purchase_frequency", "price_sensitivity", "brand_affinity",
    "channel_preference",
    # Values & attitudes
    "risk_tolerance", "trust_in_institutions", "environmental_concern",
    "health_consciousness", "political_engagement",
    # Lifestyle
    "work_life_priority", "community_involvement", "education_aspiration",
    # Decision-making
    "decision_making_style", "technology_adoption", "financial_literacy",
}
```

---

## 20. Execution order for the build agent

This is the recommended file creation sequence to minimize blocking dependencies:

| Order | File(s) | Depends on | Estimated LOC |
|-------|---------|------------|---------------|
| 1 | `schemas.py` | nothing | ~200 |
| 2 | `rules_engine.py` | schemas.py | ~120 |
| 3 | `field_state.py` | schemas.py | ~100 |
| 4 | `evidence_merger.py` | schemas.py | ~80 |
| 5 | `agents/client.py` | schemas.py | ~60 |
| 6 | `parsers/*.py` (all 9 files) | schemas.py, agents/client.py | ~200 total |
| 7 | `agents/triage.py` | schemas.py, agents/client.py | ~40 |
| 8 | `agents/segment_extractor.py` through `agents/campaign_benchmark_extractor.py` (6 files) | schemas.py, agents/client.py | ~240 total |
| 9 | `theater.py` | schemas.py | ~40 |
| 10 | `pipeline.py` | everything above | ~100 |
| 11 | `main.py` | pipeline.py, theater.py | ~60 |
| 12 | `tests/*.py` | everything above | ~150 |
| 13 | `Dockerfile`, `deploy.sh`, `.env.example`, `requirements.txt` | nothing | ~30 |

**Total estimated LOC:** ~1,420

---

## 21. What is NOT in this spec (Phase 2+)

- Enterprise connectors (Google Drive, SharePoint, S3)
- Conversational interview copilot
- Per-section user approval UI
- JWT authentication (Phase 1 uses API key)
- Redis/Pub/Sub for cross-instance SSE
- Frontend React/Next.js application (Phase 1 is API-only + Swagger UI)
- Prompt caching optimization
- Cost monitoring dashboard
