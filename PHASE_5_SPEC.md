# PHASE_5_SPEC.md — Conversational Copilot, Schema Approval UI, and Demo Video Pipeline

> Post-hardening phase. Phases 1-4 delivered the complete pipeline: schemas, parsers,
> LLM-wired agents, Theater frontend, JWT auth, Redis SSE, connectors, cost tracking.
> This phase adds the two remaining Lateral PRD features and prepares for the demo shoot.

---

## 1. Scope

| Stream | What | Source | Priority |
|--------|------|--------|----------|
| **A. Conversational Calibration Copilot** | Brief-first interview flow with field-state gap model | Lateral v3 | P1 |
| **B. Schema Section Approval UI** | Per-section user approval with provenance visibility | Lateral v4 | P1 |
| **C. Demo video pipeline** | Fixture-driven demo script, screen recording automation | ULTIMATE_PRD | P0 |
| **D. S3 connector wiring** | Wire S3 connector routes in main.py (Google Drive done) | PHASE_4_SPEC | P2 |

---

## 2. Stream A: Conversational Calibration Copilot (Lateral v3)

### 2.1 Architecture

An alternative intake mode alongside the existing drag-drop. The user starts with a short business brief. The copilot runs a structured interview that requests only the missing artifacts and clarifications needed to fill the `RadiantPersonaCalibration` schema.

**Statefulness requirement:** Unlike the existing stateless pipeline, the copilot requires multi-turn state. Use Redis (already available) to store interview state per `job_id`.

### 2.2 New files

```
rcs-sidecar/
├── copilot/
│   ├── __init__.py
│   ├── interview_engine.py     # Interview state machine
│   ├── question_generator.py   # Gemini-driven next-question selection
│   └── answer_normalizer.py    # Flash-based answer→typed value conversion
└── frontend/
    └── components/
        └── CopilotPanel.tsx    # Chat-style interview UI
```

### 2.3 File: `copilot/interview_engine.py`

```python
class InterviewEngine:
    """
    Multi-turn interview state machine backed by the Field-State Engine.
    
    State stored in Redis as JSON:
      key: "interview:{job_id}"
      value: {
        "project_id": str,
        "brief": str,
        "field_states": dict[str, FieldState],
        "conversation": list[{"role": "system"|"user"|"assistant", "content": str}],
        "uploaded_artifact_ids": list[str],
        "turn_count": int,
      }
    
    Methods:
    
    async def start(self, project_id: str, brief: str) -> InterviewResponse:
        '''
        1. Initialize FieldStateEngine with all fields UNKNOWN.
        2. Pass brief to Gemini Pro to map it to required calibration fields.
        3. Create a missing-information plan.
        4. Generate the first question.
        5. Store state in Redis.
        6. Return InterviewResponse with the first question + field state summary.
        '''
    
    async def respond(self, job_id: str, user_answer: str,
                      uploaded_files: list[UploadFile] | None = None) -> InterviewResponse:
        '''
        1. Load state from Redis.
        2. If uploaded_files: parse them, run targeted extraction for currently-missing fields.
        3. Pass user_answer to AnswerNormalizer (Flash) to convert to typed candidate values.
        4. Update FieldStateEngine with new evidence.
        5. Check if enough fields are CANDIDATE/VALIDATED to attempt synthesis.
        6. If yes: run synthesis_agent, return calibration.
        7. If no: generate next question via QuestionGenerator (Pro).
        8. Save state to Redis.
        9. Return InterviewResponse.
        '''
    
    async def get_state(self, job_id: str) -> dict:
        '''Load and return current interview state from Redis.'''
    '''
```

### 2.4 File: `copilot/question_generator.py`

```python
async def generate_next_question(
    field_states: dict[str, FieldState],
    conversation: list[dict],
    broadcaster: TheaterBroadcaster,
) -> str:
    """
    Model: MODEL_PRO, thinking_level=MEDIUM
    
    System prompt:
    "You are an interview planner for enterprise audience calibration.
    Given the current field state (which fields are filled vs missing)
    and the conversation so far, generate the single most valuable
    next question to ask the user.
    
    Rules:
    - Every question must map to one or more missing schema fields.
    - Never ask broad or redundant questions.
    - If a file upload would be more efficient than a text answer, suggest it.
    - Keep questions tightly tied to missing JSON fields."
    
    Input: field_states + last 10 conversation turns
    Output: plain text question string
    """
```

### 2.5 File: `copilot/answer_normalizer.py`

```python
class NormalizedAnswer(BaseModel):
    field_path: str
    value: str | float | bool | list[str]
    confidence: float
    needs_file_evidence: bool

class AnswerNormalizationOutput(BaseModel):
    normalized: list[NormalizedAnswer]

async def normalize_answer(
    answer: str,
    target_fields: list[str],
    broadcaster: TheaterBroadcaster,
) -> AnswerNormalizationOutput:
    """
    Model: MODEL_FLASH, thinking_level=LOW
    
    Converts free-text user answer into typed candidate values
    for specific schema fields. Flags when a file upload would
    provide stronger evidence than the text answer alone.
    """
```

### 2.6 API routes

```python
@app.post("/v1/copilot/start")
async def copilot_start(
    project_id: str = Form(...),
    brief: str = Form(..., max_length=2000),
    claims: dict = Depends(verify_token),
) -> InterviewResponse:
    """Start a new copilot interview session."""

@app.post("/v1/copilot/{job_id}/respond")
async def copilot_respond(
    job_id: str,
    answer: str = Form(...),
    files: list[UploadFile] | None = File(None),
    claims: dict = Depends(verify_token),
) -> InterviewResponse:
    """Send a user response (text and/or files) to the copilot."""

@app.get("/v1/copilot/{job_id}/state")
async def copilot_state(job_id: str, claims: dict = Depends(verify_token)):
    """Get current interview state including field progress."""
```

### 2.7 Pydantic models

```python
class InterviewResponse(BaseModel):
    job_id: str
    question: str | None = None        # null when calibration is ready
    field_state_summary: dict[str, FieldState]
    fields_remaining: int
    fields_total: int
    calibration: RadiantPersonaCalibration | None = None  # set when ready
    suggested_upload: str | None = None  # e.g. "Upload your brand guidelines PDF"
```

### 2.8 Frontend: `CopilotPanel.tsx`

```
- Chat-style interface
- Left: conversation thread (user messages + copilot questions)
- Right: field-state progress rail (reuse FieldStateBar)
- File upload button inline with the chat input
- "Synthesize Now" button appears when ≥80% of required fields are CANDIDATE+
- Final state: shows LoadButton when calibration is ready
```

---

## 3. Stream B: Schema Section Approval UI (Lateral v4)

### 3.1 Architecture

After calibration completes (either via batch upload or copilot), show a section-by-section review interface where the user can approve, reject, or flag individual schema sections.

### 3.2 Frontend: `components/SchemaApproval.tsx`

```
Layout:
- Left sidebar: schema section list with status badges
  - Sections: Segments, Demographics, Psychographics, Behavioral,
    Verbatims, Brand Constraints, Campaign Benchmarks
  - Status: approved (green), pending (yellow), rejected (red)
- Center: selected section detail view
  - Per-field display with value + citation chips
  - Each field shows: source (Flash/Pro/user), confidence badge, provenance
  - Approve / Reject / Flag buttons per field
- Right: source panel showing relevant artifact excerpts

Behavior:
- "Load into Simulation" button only enabled when all required sections
  are approved
- Rejected sections trigger a targeted re-extraction with additional
  user context ("This segment weight seems too high because...")
- Per-field provenance: click citation chip → scrolls to source artifact
  excerpt
```

### 3.3 API routes

```python
@app.get("/v1/calibrate/{job_id}/sections")
async def get_sections(job_id: str) -> list[SectionStatus]:
    """Return per-section approval status."""

@app.post("/v1/calibrate/{job_id}/sections/{section_id}/approve")
async def approve_section(job_id: str, section_id: str) -> SectionStatus:
    """Mark a section as approved."""

@app.post("/v1/calibrate/{job_id}/sections/{section_id}/reject")
async def reject_section(
    job_id: str, section_id: str, reason: str = Form(...)
) -> SectionStatus:
    """Reject a section with reason. Triggers targeted re-extraction."""
```

### 3.4 Pydantic models

```python
class SectionStatus(BaseModel):
    section_id: str
    section_name: str
    status: Literal["pending", "approved", "rejected"]
    field_count: int
    approved_count: int
    rejection_reason: str | None = None

class FieldDetail(BaseModel):
    field_path: str
    value: str | float | bool | list[str] | dict
    confidence: float
    source_agent: str      # which agent populated this
    citations: list[SourceCitation]
    user_approved: bool = False
```

---

## 4. Stream C: Demo video pipeline

### 4.1 Demo script (15s cold open + 60s Magic Moment)

Based on the ULTIMATE_PRD's Theater spec:

```
SCENE 1 (0-15s): Cold Open
- Screen: F100 investor relations lead's desktop
- Action: Drag 4 files onto the Radiant calibration drop zone
- Files: kantar_brand_tracker.csv, ipsos_segments.txt,
         earnings_transcripts.txt, crm_holders.csv
- Drop zone glows indigo
- First triage event appears in Theater panel

SCENE 2 (15-42s): The Pipeline
- Theater panel streams real SSE events
- FieldStateBar fills progressively (purple → yellow → green)
- Events match the ULTIMATE_PRD Magic Moment timing:
  T+0.4s through T+42.0s
- Camera zooms into Theater panel to show proof-of-work

SCENE 3 (42-55s): The Result
- "Load into Simulation →" button illuminates
- Click it
- Cut to Tom's existing network visualization (screenshot/mockup)
- Text overlay: "4 segments • 87 attributes • 412 verbatims"

SCENE 4 (55-60s): CTA
- Text: "Radiant Calibration Sidecar"
- Subtext: "From research warehouse to simulation in 42 seconds"
```

### 4.2 File: `demo/run_demo.sh`

```bash
#!/usr/bin/env bash
# Start backend with fixture-friendly env
export GOOGLE_GENAI_USE_VERTEXAI=True
export GOOGLE_CLOUD_PROJECT=${PROJECT}
export GOOGLE_CLOUD_LOCATION=global

cd rcs-sidecar
uvicorn main:app --port 8080 &
BACKEND_PID=$!

cd frontend
npm run dev &
FRONTEND_PID=$!

echo "Backend: http://localhost:8080"
echo "Frontend: http://localhost:3000"
echo "Press Ctrl+C to stop"

wait
```

### 4.3 File: `demo/README.md`

Instructions for recording the demo video:
1. Start `run_demo.sh`
2. Open `http://localhost:3000` in browser
3. Use OBS or Loom to record
4. Drag the 4 fixture files from `tests/fixtures/`
5. Click "Calibrate Audience"
6. Wait for pipeline to complete
7. Click "Load into Simulation"

---

## 5. Stream D: S3 connector routes

### 5.1 API routes to add in `main.py`

```python
@app.get("/v1/connectors/s3/files")
async def s3_files(
    bucket: str,
    path: str = "",
    claims: dict = Depends(verify_token),
):
    from connectors.s3 import S3Connector
    conn = S3Connector(bucket=bucket)
    return await conn.list_files(path=path)

@app.post("/v1/connectors/s3/fetch")
async def s3_fetch(
    bucket: str = Form(...),
    file_ids: list[str] = Form(...),
    claims: dict = Depends(verify_token),
):
    from connectors.s3 import S3Connector
    conn = S3Connector(bucket=bucket)
    fetched = []
    for fid in file_ids:
        try:
            data, name = await conn.fetch_file(fid)
            fetched.append({"filename": name, "size": len(data)})
        except Exception as e:
            fetched.append({"file_id": fid, "error": str(e)})
    return {"fetched": fetched}
```

---

## 6. Tests to add

### 6.1 `tests/test_copilot.py`

```python
@pytest.mark.asyncio
async def test_copilot_start_generates_first_question():
    """Start a copilot session with a brief, verify a question is returned."""

@pytest.mark.asyncio
async def test_copilot_respond_updates_field_state():
    """Send a text answer, verify field state transitions."""

@pytest.mark.asyncio
async def test_copilot_file_upload_triggers_extraction():
    """Upload a file mid-interview, verify targeted extraction runs."""
```

### 6.2 `tests/test_schema_approval.py`

```python
def test_section_approve_sets_status():
    """Approve a section, verify status is 'approved'."""

def test_section_reject_includes_reason():
    """Reject with reason, verify reason is stored."""

def test_load_blocked_until_all_approved():
    """Verify calibration cannot be loaded with pending sections."""
```

---

## 7. Execution order

| Order | Task | Stream | Est. LOC |
|-------|------|--------|----------|
| 1 | `copilot/interview_engine.py` | A | ~120 |
| 2 | `copilot/question_generator.py` | A | ~40 |
| 3 | `copilot/answer_normalizer.py` | A | ~40 |
| 4 | Copilot API routes in `main.py` | A | ~30 |
| 5 | `InterviewResponse` model in `schemas.py` | A | ~15 |
| 6 | `CopilotPanel.tsx` | A | ~150 |
| 7 | `SchemaApproval.tsx` + section routes | B | ~200 |
| 8 | `SectionStatus` / `FieldDetail` models | B | ~20 |
| 9 | S3 connector routes | D | ~25 |
| 10 | `demo/run_demo.sh` + README | C | ~40 |
| 11 | Tests (copilot + approval) | All | ~100 |

**Total estimated LOC:** ~780

---

## 8. What this completes

After Phase 5, all features from the ULTIMATE_PRD and all four Lateral PRD variants are implemented:

| Feature | Source | Phase |
|---------|--------|-------|
| Gemini 3.x routing stack | Master PRD | 1 |
| Deterministic rules engine | Master PRD | 1 |
| Field-State Engine | Lateral v3 | 1 |
| Evidence Merger | Lateral v1 | 1 |
| Continuous validation | Lateral v4 | 1 |
| Theater SSE streaming | Master PRD | 1 |
| Real parsers (8 formats) | Phase 2 spec | 2 |
| LLM-wired agents (7) | Phase 2 spec | 2 |
| Theater frontend | Phase 2 spec | 2 |
| End-to-end wiring + CORS | Phase 3 spec | 3 |
| Fixture bundle + tests | Phase 3 spec | 3 |
| JWT authentication | Phase 4 spec | 4 |
| Redis Pub/Sub SSE | Phase 4 spec | 4 |
| Google Drive connector | Phase 4 spec (Lateral v2) | 4 |
| Cost tracking | Phase 4 spec | 4 |
| S3 connector | Phase 4 spec (Lateral v2) | 5 |
| Conversational copilot | Lateral v3 | 5 |
| Schema approval UI | Lateral v4 | 5 |
| Demo video pipeline | Master PRD | 5 |
