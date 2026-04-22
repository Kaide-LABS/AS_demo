# ULTIMATE_PRD.md — Radiant Calibration Sidecar for Artificial Societies

> FDE sidecar spec. Stateless. Gemini-only. DMZ-upstream of Tom's engine. 48–72hr build.

---

## The FDE thesis

**Artificial Societies just killed their consumer product and bet the company on Radiant.** As of Q1 2026, James He publicly announced: *"we've made the decision to focus on providing bespoke services to enterprises, and discontinue public access to the Artificial Societies platform."* Every dollar of future revenue now flows through one narrow choke-point — the **bespoke simulation** workflow where an F100 strategic comms, investor relations, or policy affairs lead shows up with *their* research artifacts and asks Radiant to simulate *their* audience. That workflow has exactly one unsolved bottleneck: **translating messy, heterogeneous enterprise research artifacts (Kantar/Ipsos exports, SPSS files, Dovetail transcripts, Qualtrics .qsf, CRM segment CSVs, ethnography PDFs) into the persona-calibration JSON Radiant needs to run.** Today this is done by the AS team as hand-rolled consulting work, which is why Radiant takes 24 hours to turn around and why AS can only serve a handful of F100 logos with six humans.

We build the **Radiant Calibration Sidecar (RCS)**: a stateless Gemini-powered ingestion pipeline that sits strictly upstream of Tom's core engine, consumes the customer's research warehouse, and emits a schema-validated `RadiantPersonaCalibration` JSON document the core engine's audience builder can consume as-is. No touch to the 2.5M-persona database, the network simulation engine, the 95%-accuracy moat, the Pulsar data pipe, the UI, or anything Tom has shipped. Pure DMZ. Pure sidecar. Pure bottleneck assassination.

This lands lethally on all three founders simultaneously:

**James (CEO).** *"We had no customers, no revenue, no clue how we'll provide value to real people… we were the kind of startups they warned investors about: a hammer-on-paper, looking for a nail."* RCS is the nail — the specific, unglamorous, expensive-to-solve piece of F100 research plumbing that converts every inbound enterprise conversation from "can your 2.5M personas represent our audience?" to "upload your segmentation deck and Kantar export, we'll calibrate in 4 minutes." It is the literal operationalization of James's *"bias to build"* and *"ship the bare minimum improvement that runs."*

**Patrick (CPO).** *"Traditional market research is slow, expensive, and often fails to capture the social nature of human behavior."* Patrick spent his Swiss Re years running 200+ Fortune 500 experiments — he knows personally that the 6–12 week custom-segment stand-up is where project timelines die. RCS executes his **"Promise Market Fit"** thesis with machinery: it removes the *months-long survey project friction* Radiant markets against but doesn't yet fully deliver on, because it compresses Phase 1 (audience definition/recruitment) from weeks to minutes. Patrick is the internal champion.

**Tom (CTO).** *"No tests, no staging environment — test in prod. Best practice is not universal gospel, it's contextual."* RCS respects Tom's philosophy: stateless, single-purpose, sub-200-LOC-per-module, shipped as one Cloud Run service with a `/healthz` and a `/calibrate` endpoint. No test pyramid, no CI matrix — just a lightweight contract test harness that verifies the Pydantic schema contract with the core engine. Critically, **it threatens nothing he has built.** The network visualization UI, the persona DB, the 90-second deploy loop, the Pulsar pipe, Mirror World — untouched. Tom's relief is the architecture's signature.

### Strategic hook

The single irresistible hook: **James's own post describing the NYC/DC F500 tour** — *"we weren't there to sell… every time we walkthrough a simulation with them, we note down what are they finding valuable, and what needs improvement. We almost work alongside them against our own product."* The specific feedback every F100 comms lead gives during those walkthroughs is a variant of *"this is impressive but how do I know it represents **our** board / **our** shareholders / **our** institutional investors?"* RCS is the exact answer James wishes he could pull out of his pocket in the next NYC meeting. The fact that Radiant's only named F100 logo publicly (Teneo, a CEO advisory firm) is *itself a shop that lives on client research artifacts* makes the sidecar a natural land-and-expand into the rest of the Teneo book.

---

## System architecture & agent routing

### Data flow map

```
┌─────────────────────────────────────────────────────────────────────────┐
│   ENTERPRISE CLIENT: drag-drop research artifacts into RCS web UI        │
│   (PDF decks, .sav, .qsf, .csv, .docx transcripts, .txt, .xlsx, images)  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  multipart/form-data
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   STATELESS FastAPI SIDECAR (Cloud Run, us-central1, min=1 max=50)       │
│                                                                          │
│   ┌─── [1] INGESTION LAYER ────────────────────────────────────────────┐│
│   │  Format detection (python-magic) → route to parser                  ││
│   │  • PDF / image  → Gemini 3.1 Pro multimodal vision extraction       ││
│   │  • .sav / .sps  → pyreadstat → structured DF → string serialization ││
│   │  • .csv / .xlsx → pandas → typed columns → string serialization     ││
│   │  • .qsf         → JSON parser → question inventory                  ││
│   │  • .docx / .txt → docx2txt / raw                                    ││
│   │  Output: List[SourceArtifact] with raw_text + artifact_type metadata││
│   └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│   ┌─── [2] TRIAGE AGENT (gemini-3.1-flash-lite-preview, minimal think) ─┐│
│   │  Classifies each artifact: BRAND_TRACKER / FOCUS_GROUP_TRANSCRIPT / ││
│   │  SEGMENTATION_STUDY / CRM_EXPORT / SURVEY_INSTRUMENT / ETHNOGRAPHY  ││
│   │  / COMPETITIVE_INTEL / OTHER. Produces routing manifest.            ││
│   │  ~$0.001/artifact. Latency <2s.                                     ││
│   └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│   ┌─── [3] PARALLEL EXTRACTION AGENTS (asyncio.gather) ─────────────────┐│
│   │                                                                     ││
│   │   3a. SEGMENT_EXTRACTOR  (gemini-3-flash-preview, think=low)        ││
│   │       Extracts named segments + attributes from decks/studies       ││
│   │                                                                     ││
│   │   3b. VERBATIM_DISTILLER (gemini-3-flash-preview, think=low)        ││
│   │       Pulls representative quotes from transcripts/ethnography,     ││
│   │       tags by segment, emits (segment_id, verbatim, sentiment)      ││
│   │                                                                     ││
│   │   3c. DEMOGRAPHIC_NORMALIZER (gemini-3.1-flash-lite, think=minimal) ││
│   │       Maps SPSS/CSV rows to Pulsar-compatible demographic schema    ││
│   │                                                                     ││
│   │   3d. BEHAVIORAL_ATTRIBUTE_EXTRACTOR (gemini-3-flash-preview, low)  ││
│   │       Extracts stated behaviors, psychographics, info-sources       ││
│   │                                                                     ││
│   │   All use response_schema=Pydantic. Structured JSON only.           ││
│   └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│   ┌─── [4] SYNTHESIS AGENT (gemini-3.1-pro-preview, think=high) ────────┐│
│   │  Long-context consolidator: ingests full normalized artifact bundle ││
│   │  + all parallel extractions (typically 200k–800k tokens).           ││
│   │  Emits draft RadiantPersonaCalibration with:                        ││
│   │    • 3–8 named segment profiles (with size weights)                 ││
│   │    • behavioral attribute matrix per segment                        ││
│   │    • verbatim corpus indexed by segment                             ││
│   │    • calibration confidence score per attribute                     ││
│   │    • source-provenance citations for every field                    ││
│   └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│   ┌─── [5] DETERMINISTIC VALIDATION LAYER (pure Python, no LLM) ────────┐│
│   │  • Pydantic v2 schema validation (hard reject on failure)           ││
│   │  • Segment weights sum to 1.0 ± 0.01                                ││
│   │  • Every attribute has ≥1 source citation                           ││
│   │  • Verbatim corpus ≥5 quotes per segment                            ││
│   │  • Behavioral attributes in canonical vocabulary (jsonschema enum)  ││
│   │  • Confidence scores monotonic w/ source count                      ││
│   │  • If ANY rule fails → targeted retry on that field w/ 3.1 Pro      ││
│   │    (max 2 retries, then flag field as `requires_human_review=true`) ││
│   │  • NEVER allow LLM to self-certify — rules engine is the gate       ││
│   └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│   ┌─── [6] OUTPUT LAYER ────────────────────────────────────────────────┐│
│   │  Returns RadiantPersonaCalibration JSON + provenance manifest       ││
│   │  Streams SSE "Theater" events during processing for frontend UI     ││
│   └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
                                │  HTTP 200 + JSON
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   ARTIFICIAL SOCIETIES CORE ENGINE (Tom's — we never touch this)         │
│   Consumes RadiantPersonaCalibration as the audience-build input,        │
│   runs the 1000+ agent simulation, renders in the existing network UI.   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Model routing rationale (April 2026 frontier)

| Step | Model | Rationale |
|------|-------|-----------|
| Triage (step 2) | **`gemini-3.1-flash-lite-preview`** `thinking_level=minimal` | $0.25 input / $1.50 output per 1M (flat, no 200K cliff); fastest in family; classifying 8-class routing is trivial reasoning; sub-second latency keeps Theater UI snappy. |
| Parallel extractors (step 3) | **`gemini-3-flash-preview`** `thinking_level=low` | $0.50 / $3.00 flat (no 200K cliff); supports all four thinking levels (`minimal`/`low`/`medium`/`high`); Pro-level reasoning at ~3× Pro speed; ideal for structured extraction with Pydantic `response_schema`. |
| Demographic normalizer (3c) | **`gemini-3.1-flash-lite-preview`** `thinking_level=minimal` | Pure mechanical schema-mapping — burn the cheapest tokens. |
| Synthesis consolidator (step 4) | **`gemini-3.1-pro-preview`** `thinking_level=high`, `location=global` | 1M context; deep reasoning; explicit Google positioning for *"PDFs, and entire code repositories"*; the only model that can hold a full research-warehouse bundle and reconcile contradictions across sources. Long-context pricing ($4 input / $18 output per 1M >200K) is the single biggest cost line — budgeted deliberately. Prompt caching available at $0.40/$0.20 per 1M (≤200K/≥200K cached input). |
| Targeted retry (step 5) | **`gemini-3.1-pro-preview`** `thinking_level=medium` | If rules engine rejects a field, re-ask with the specific rule as a constraint. Medium think = faster than high, sufficient for narrow rewrites. |

**Why not Deep Think / Gemini 3 Ultra?** Neither exists on Vertex AI as of April 21, 2026. Deep Think is Gemini-app-only; Ultra is unannounced. `gemini-3.1-pro-preview` with `thinking_level=high` is the frontier reasoning endpoint on Vertex.

### Container boundary — stateless API contract

```
POST /v1/calibrate
  Content-Type: multipart/form-data
  Headers: Authorization: Bearer <signed JWT from AS>
  Body:
    - project_id: str
    - target_audience_brief: str  (1–3 sentence brief from the comms lead)
    - artifacts[]: File (up to 20 files, 50MB each)
  
  Response: 200 application/json
    RadiantPersonaCalibration  (full schema below)

GET /v1/calibrate/{job_id}/stream
  → text/event-stream  (SSE — Theater events for frontend)

GET /healthz → 200 "ok"
```

No database. No session state. Each call is fully self-contained; if the core engine wants to persist the calibration, it does so in its own Postgres. RCS holds nothing between requests beyond Cloud Run's per-instance warm filesystem (scratch space for the duration of a single request, wiped on response).

---

## The "Native Environment" UI spec

RCS lives as a **single new tab inside the existing Radiant project-creation flow** at `app.societies.io/radiant/new → Step 2: Calibrate Audience`. Today that step is a blank textarea where AS solution engineers paste client notes. Tomorrow it is a drag-drop zone that says **"Drop your research. We'll build the audience."**

### First 15 seconds (demo cold open)

The demo video opens with an F100 investor-relations lead's desktop. Their cursor drags four files — `Kantar_Brand_Tracker_Q4_2025.sav`, `Ipsos_Shareholder_Segments_v3.pdf`, `Earnings_Call_Transcripts.docx`, `CRM_Top200_Institutional_Holders.csv` — onto the Radiant calibration drop zone. The zone glows. The "Theater" panel on the right lights up. Before the user has released the mouse, the first triage event streams in: *"Detected: Kantar brand tracker • 4 segments • 1,247 respondents."* Tom's existing network visualization — untouched — waits in the background, ready to receive the calibrated audience.

### The Magic Moment (sub-60s)

A live-streaming **Theater** panel, rendered right of the drop zone, shows the pipeline executing as it happens. Every SSE event is a line. Timing is non-negotiable:

```
T+0.4s   📄 Kantar_Brand_Tracker_Q4_2025.sav   → BRAND_TRACKER
T+0.6s   📄 Ipsos_Shareholder_Segments_v3.pdf  → SEGMENTATION_STUDY  
T+1.1s   📄 Earnings_Call_Transcripts.docx     → VERBATIM_CORPUS
T+1.2s   📄 CRM_Top200_Institutional_Holders.csv → CRM_EXPORT
T+3.8s   🎯 Extracting segments from Ipsos deck… 4 segments found
T+4.1s   💬 Distilling 412 verbatims from transcripts…
T+6.9s   🧬 Normalizing demographic fields to Pulsar schema
T+14.2s  🧠 Synthesizing calibration (1M context, deep reasoning)…
T+38.5s  ✅ Validation: 6/6 rules passed
T+42.0s  📦 RadiantPersonaCalibration ready
         ├ 4 segments • 87 behavioral attributes • 412 verbatims
         └ [ Load into Simulation → ]
```

At T+42s the "Load into Simulation →" button illuminates. Click it, and Tom's existing network viz boots with a pre-calibrated audience. **That button is the architectural handshake** — it is the only surface RCS ever shows the core engine, and it passes exactly one thing: a validated JSON blob.

### Theater proof-of-work

The right panel never fakes work. Every line is a real SSE event tied to a real Gemini call or Python validation. Expand any line to see: (a) which model ran, (b) input token count, (c) output token count, (d) latency, (e) the exact schema that validated. This is the Renlo/Mundostra "no hand-waving" standard — the demo viewer can literally see the pipeline work.

---

## Phase 1 execution spec

### Pydantic v2 schemas

```python
# schemas.py — pydantic 2.13.3 + pydantic-core 2.46.3
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

class ArtifactType(str, Enum):
    BRAND_TRACKER = "brand_tracker"
    FOCUS_GROUP_TRANSCRIPT = "focus_group_transcript"
    SEGMENTATION_STUDY = "segmentation_study"
    CRM_EXPORT = "crm_export"
    SURVEY_INSTRUMENT = "survey_instrument"
    ETHNOGRAPHY = "ethnography"
    COMPETITIVE_INTEL = "competitive_intel"
    VERBATIM_CORPUS = "verbatim_corpus"
    OTHER = "other"

class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    artifact_type: ArtifactType
    locator: str = Field(description="page/row/timestamp/question_id")
    excerpt: str = Field(max_length=500)

class Verbatim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=1200)
    sentiment: Literal["positive","neutral","negative","mixed"]
    citation: SourceCitation

class BehavioralAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str   # canonical vocabulary enforced by rules engine
    value: str | float | bool | list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[SourceCitation] = Field(min_length=1)

class PersonaSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    label: str = Field(max_length=80)
    description: str = Field(max_length=600)
    weight: float = Field(gt=0.0, le=1.0, description="share of audience")
    demographic_attributes: list[BehavioralAttribute]
    psychographic_attributes: list[BehavioralAttribute]
    behavioral_attributes: list[BehavioralAttribute]
    information_sources: list[str]
    verbatims: list[Verbatim] = Field(min_length=5)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = False

class RadiantPersonaCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0.0"] = "1.0.0"
    project_id: str
    target_audience_brief: str
    segments: list[PersonaSegment] = Field(min_length=1, max_length=8)
    global_provenance: list[SourceCitation]
    coverage_gaps: list[str] = Field(
        description="Attributes the rules engine flagged for human review"
    )

    @field_validator("segments")
    @classmethod
    def weights_sum_to_one(cls, v: list[PersonaSegment]) -> list[PersonaSegment]:
        total = sum(s.weight for s in v)
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"segment weights sum to {total}, must equal 1.0 ± 0.01")
        return v

class TheaterEvent(BaseModel):
    ts_ms: int
    stage: Literal["ingest","triage","extract","synthesize","validate","done","error"]
    message: str
    meta: dict = {}
```

### FastAPI route signatures

```python
# main.py — fastapi 0.136.0
from fastapi import FastAPI, UploadFile, Form, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from schemas import RadiantPersonaCalibration, TheaterEvent

app = FastAPI(title="Radiant Calibration Sidecar", version="1.0.0")

@app.get("/healthz")
async def healthz() -> dict: ...

@app.post("/v1/calibrate", response_model=RadiantPersonaCalibration)
async def calibrate(
    project_id: str = Form(...),
    target_audience_brief: str = Form(..., max_length=2000),
    artifacts: list[UploadFile] = ...,
) -> RadiantPersonaCalibration: ...

@app.get("/v1/calibrate/{job_id}/stream")
async def stream_theater(job_id: str) -> StreamingResponse: ...
```

### pip dependencies (exact pins)

```
# requirements.txt — April 2026 frontier (verified against PyPI 2026-04-22)
google-genai==1.73.1           # unified Gemini SDK (GA); accepts Pydantic as response_schema
fastapi==0.136.0               # requires pydantic>=2.9.0; dropped Python 3.8
pydantic==2.13.3               # fixes pydantic-core version-mismatch startup errors
pydantic-core==2.46.3          # must match pydantic 2.13.3 (was 2.41.5 — stale)
uvicorn[standard]==0.45.0      # was 0.35.0 — 10 patch releases of perf/bugfix
python-multipart==0.0.26       # was 0.0.19 — required by FastAPI for Form/UploadFile
sse-starlette==3.3.4           # BREAKING: major version bump from 2.x → 3.x (new API surface)
pandas==3.0.2                  # BREAKING: Copy-on-Write default, requires Python >=3.11
pyreadstat==1.3.4              # SPSS .sav / .sps (was 1.3.2)
openpyxl==3.1.5                # .xlsx
python-docx==1.2.0             # .docx
python-magic==0.4.27           # format detection
httpx==0.28.1                  # stable; 1.0 is dev-only pre-release — do not use
tenacity==9.1.4                # retry logic (was 9.0.0)
orjson==3.11.8                 # faster JSON (was 3.11.0)
# Runtime: Python 3.12 on Cloud Run (satisfies pandas >=3.11 requirement)
```

### Backend logic flow

```python
# pipeline.py
async def run_calibration(req: CalibrateRequest) -> RadiantPersonaCalibration:
    # 1. INGEST — parse each file to SourceArtifact
    artifacts = await asyncio.gather(*[parse(f) for f in req.artifacts])
    
    # 2. TRIAGE — single Flash-Lite call classifying all artifacts
    manifest = await triage_agent(artifacts)  # gemini-3.1-flash-lite-preview
    
    # 3. PARALLEL EXTRACTION
    extractions = await asyncio.gather(
        segment_extractor(artifacts, manifest),        # 3-flash, think=low
        verbatim_distiller(artifacts, manifest),        # 3-flash, think=low
        demographic_normalizer(artifacts, manifest),    # 3.1-flash-lite, think=min
        behavioral_attribute_extractor(artifacts, manifest),  # 3-flash, think=low
    )
    
    # 4. SYNTHESIS — long-context consolidator
    draft = await synthesis_agent(
        brief=req.target_audience_brief,
        artifacts=artifacts,
        extractions=extractions,
    )  # gemini-3.1-pro-preview, think=high, location=global
    
    # 5. VALIDATE — deterministic rules engine
    calibration, violations = rules_engine.validate(draft)
    
    retry_budget = 2
    while violations and retry_budget > 0:
        calibration = await targeted_retry(calibration, violations)
        # gemini-3.1-pro-preview, think=medium
        calibration, violations = rules_engine.validate(calibration)
        retry_budget -= 1
    
    if violations:
        for v in violations:
            calibration.coverage_gaps.append(v.description)
        for seg in calibration.segments:
            if any(v.segment_id == seg.segment_id for v in violations):
                seg.requires_human_review = True
    
    return calibration
```

### Rules engine (deterministic, no LLM)

```python
# rules_engine.py
RULES = [
    weights_sum_to_one,                    # ± 0.01
    every_attribute_has_citation,          # len(citations) >= 1
    verbatims_per_segment_minimum,         # >= 5 per segment
    canonical_attribute_vocabulary,        # key in CANONICAL_KEYS set
    confidence_monotonic_with_sources,     # conf bounded by sqrt(n_citations/10)
    no_pii_in_verbatims,                   # regex scrub for emails/phones
    provenance_completeness,               # every segment traces to >=1 artifact
]
```

The rules engine is **the LLM safety net**. It is pure Python, deterministic, and is the only authority that can certify a `RadiantPersonaCalibration` as valid. Gemini generates; Python verifies. Zero exceptions.

### Test harness (Tom's philosophy — lightweight)

No test pyramid. Three contract tests only, run via `pytest` on push to main. No CI matrix, no coverage gate.

```python
# tests/test_contract.py
def test_schema_roundtrip_fixture():
    """A known-good calibration fixture roundtrips through Pydantic."""

def test_rules_engine_rejects_bad_weights():
    """Segments summing to 0.85 must fail validation."""

def test_live_smoke():
    """Upload the 4-file fixture bundle, assert 200 + schema validity.
    Skipped locally; runs once post-deploy in Cloud Run revision smoke."""
```

That's it. Tom's *"test in prod"* — the smoke test runs against the deployed revision before traffic is shifted.

### Cloud Run deployment spec

```bash
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
  --set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global \
  --no-allow-unauthenticated
```

Service account `rcs-sa` granted `roles/aiplatform.user`. Invocation restricted to the AS core engine's service identity via IAM. IAP optional for demo URL.

### Build timeline (48–72hr FDE sprint)

| Hours | Milestone |
|-------|-----------|
| 0–4 | Repo scaffold, Pydantic schemas, FastAPI skeleton, Cloud Run hello-world deploy |
| 4–12 | Ingestion layer (all 7 parsers), format detection, fixture file set assembled |
| 12–20 | Triage agent + 4 parallel extraction agents, structured-output harnesses |
| 20–32 | Synthesis agent w/ long-context prompt, SSE streaming wiring |
| 32–40 | Rules engine + targeted retry loop + provenance tracking |
| 40–52 | Theater frontend (Next.js drag-drop + SSE tail, Tailwind match to societies.io) |
| 52–60 | End-to-end smoke against fixture bundle, latency tuning, prompt hardening |
| 60–68 | Demo video shoot (15s cold open + 60s Magic Moment), README, one-pager |
| 68–72 | Buffer, final deploy, Loom walkthrough for James/Patrick |

---

## Killed proposals

### ❌ Proposal 2: Post-Core Executive Synthesis Engine — KILLED

**Ego Check failure.** F100 strategic comms leads are *the people whose job is to write the narrative*. James and Patrick have personally spent the Q1 2026 NYC/DC tour *"almost work[ing] alongside them against our own product"* — the feedback was never "we need the deck auto-generated," it was "we need to trust the audience." An auto-deck generator competes with the buyer's own headcount and with Beautiful.AI / Gamma / Enlyta / A1 Slides, a crowded category. Patrick's *"Promise Market Fit"* thesis is about removing *months* of pre-field friction, not *hours* of deck friction. The synthesis pain is real but secondary, politically awkward, and downstream of the deal-blocking bottleneck. **Killed.**

### ❌ Proposal 3: Compliance Router — KILLED

**Ego Check failure and Bottleneck Assassin failure.** Three strikes: (1) **Commodity.** Vanta, Drata, Secureframe, Loopio, Conveyor, Responsive, Arphie all occupy this space with $150M–$200M+ war chests; building a me-too is Ego-Check-negative against the *$10k/month* pricing anchor. (2) **Wrong bottleneck owner.** SOC 2 pain is felt by *AS's own infosec function*, not by the F100 customer's comms lead; solving it is internal ops, not sidecar demo value. AS has **zero public compliance posture** today — that means they haven't even decided on their own strategy, and a sidecar prescribing it would leapfrog a foundational business decision that belongs to James + legal counsel (Taylor Wessing). (3) **Patrick's frustration is explicitly about research velocity, not procurement** — *"traditional market research is slow, expensive"* is not *"SOC 2 audits are slow, expensive."* The compliance stack is a business-ops project, not an FDE demo. **Killed.**

---

## Ego Check audit — surviving proposal (Proposal 1)

| Risk vector | Status | Evidence |
|---|---|---|
| Replicates Tom's network-viz UI? | ✅ Clean | RCS has no graph rendering; it stops at JSON. Tom's viz is the downstream consumer. |
| Touches the 1000+ agent simulation engine? | ✅ Clean | Strict upstream DMZ. Zero calls into the core. |
| Competes with Reach / AS / Radiant? | ✅ Clean | Feeds Radiant; does not replace it. Reach / consumer AS are sunset. |
| Competes with shipped features? | ✅ Clean | Intel refresh confirmed: no existing upload/ingest/connector/BYO-segment feature. |
| Competes with Mirror World? | ✅ Clean | Mirror World takes a LinkedIn URL → persona chat. RCS takes a research warehouse → JSON. Disjoint. |
| Touches Pulsar pipe? | ✅ Clean | Pulsar stays the dynamic social-listening feed. RCS is the static enterprise-artifact feed. Complementary. |
| Undermines "2.5M persona" moat? | ✅ Clean | RCS *calibrates against* the persona DB, it doesn't build a new one. The moat is fed, not competed with. |

### 5-Pillar audit — Proposal 1

1. **Bottleneck Assassin.** Confirmed: F100 custom-segment stand-up is 6–12 weeks industry-standard; Radiant's own 24hr turnaround claim is bottlenecked by the pre-field phase. Quirk's Media: *"up to a third of research data goes unused… 30–40% of reports add little or no value."* Patrick's Swiss Re background is the in-house voice confirming it.
2. **Anti-Replication.** Zero overlap with anything AS ships. Structural weakness documented by competitor review (askditto.io): *"Building personas from public social media profiles inherently overrepresents digitally active populations."* RCS is the bridge to traditional research that closes that gap — which AS cannot build with 6 humans and 2 non-engineering open roles.
3. **Native Environment.** Lives inside `app.societies.io/radiant/new → Step 2`. Same Tailwind tokens, same nav, same auth.
4. **Magic Moment.** T+42s from drag-drop to "Load into Simulation →" — visible on screen, SSE-backed, provable.
5. **System Resilience.** Deterministic Python rules engine is the certification gate. LLM generates; rules verify; targeted retry; `requires_human_review` flag on unfixable fields. No silent LLM hallucination path to the core engine.

All five pillars pass.

---

## Modernization notes

The original proposal drafts referenced a generic "Gemini stack" without specifying models. Based on verified Vertex AI frontier as of April 21, 2026:

| Pipeline step | Original draft | Upgraded to | Why |
|---|---|---|---|
| Triage / routing | (unspecified Gemini Flash) | **`gemini-3.1-flash-lite-preview`** `thinking_level=minimal` | Released March 3, 2026; cheapest and fastest 3.x variant ($0.25/$1.50 per 1M); purpose-built for "high-volume, cost-sensitive LLM traffic." |
| Parallel extractors | Gemini 2.5 Flash | **`gemini-3-flash-preview`** `thinking_level=low` | Released Dec 17, 2025; Pro-level reasoning at ~3× speed; flat pricing ($0.50/$3.00) avoids the 200K cliff; Gemini 3 family introduced `thinking_level` (minimal/low/medium/high) replacing the older `thinking_budget` API. |
| Long-context synthesizer | Gemini 2.5 Pro | **`gemini-3.1-pro-preview`** `thinking_level=high`, `location=global` | Released Feb 19, 2026; replaced retired `gemini-3-pro-preview` (shut down March 26, 2026 — *do not use*); explicit Vertex positioning for "vast datasets… PDFs, and entire code repositories with its 1M token context window." |
| SDK | `google-generativeai` or `vertexai.generative_models` | **`google-genai==1.73.1`** | Both legacy SDKs deprecated; `vertexai.generative_models` removed June 24, 2026 (~2 months away). `google-genai` is the single unified SDK and accepts Pydantic classes directly as `response_schema`. |
| Framework | FastAPI (unspecified) | **`fastapi==0.136.0` + `pydantic==2.13.3`** | Latest stable as of April 16/20, 2026. Pydantic v2.13 fixes pydantic-core version-mismatch startup errors that silently broke prior builds. |
| Endpoint region | regional Vertex endpoint | **`GOOGLE_CLOUD_LOCATION=global`** | Both Gemini 3.1 Pro Preview and Gemini 3 Flash Preview are **global-endpoint-only** on Vertex AI — regional endpoints return "model not found." Hard requirement. |
| Reasoning control | `thinking_budget` token budget | **`thinking_level`** enum | Gemini 3.x introduced level-based thinking; `thinking_budget` still works for back-compat but levels are the canonical Gemini 3 API. Don't mix both in one call. |

**Deep Think / Gemini 3 Ultra explicitly NOT used.** Deep Think is not on Vertex AI as of April 21, 2026 (Gemini-app-only, rolling out to AI Ultra subscribers). Gemini 3 Ultra is unannounced. `gemini-3.1-pro-preview` with `thinking_level=high` is the Vertex frontier reasoning endpoint.

**Preview-stage risk acknowledged.** All Gemini 3.x models on Vertex are preview-tier under "Pre-GA Offerings Terms"; prior retirement (Gemini 3 Pro → 3.1 Pro in ~4 months) shows ~17-day shutdown notice. Production SLA fallback path: swap routing to `gemini-2.5-pro` (GA) / `gemini-2.5-flash` (GA) / `gemini-2.5-flash-lite` (GA) — all GA, all 1M context for Pro, all supported by `google-genai`. Env-var driven swap, no code change. Gemini 2.5 GA retirement extended to **October 16, 2026** — ample runway.

**SDK syntax note — `ThinkingConfig`.** The `google-genai` SDK wraps thinking control in `types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH)`. **Do NOT mix `thinking_level` and `thinking_budget` in the same request** — Gemini 3.x returns an error. `thinking_level` is the canonical Gemini 3 enum; `thinking_budget` is the Gemini 2.5 back-compat path.

**Dependency modernization audit (2026-04-22).** Eight pinned versions updated against live PyPI. Two breaking upgrades flagged: (1) **pandas 3.0** — Copy-on-Write is now default; all `.copy()` calls on DataFrame slices can be removed, but in-place mutation of views will silently no-op. Since RCS uses pandas only for tabular serialization (no in-place mutation), this is safe. (2) **sse-starlette 3.x** — the `EventSourceResponse` constructor signature changed; verify import path is `sse_starlette.sse.EventSourceResponse` and that the `data` kwarg is used (not positional). See `requirements.txt` inline comments for full diff.

---

## Conclusion — why this wins

The FDE move is always to find the one unglamorous bottleneck the target company cannot afford to build themselves but cannot survive without. James shut down the consumer product in Q1 2026 and bet everything on Radiant. Radiant's 24-hour bespoke promise is bottlenecked by the pre-field phase — the 6–12 week custom-segment stand-up that competitors like Evidenza are now compressing to 30 days. With six humans, two non-engineering open roles, and a publicly-documented social-media persona bias, AS will not build the research-artifact ingestion layer in H1 2026. Someone needs to hand them one that works, fits inside the Radiant flow, threatens no shipped IP, and can be demoed in 60 seconds at the next F500 walkthrough.

That is the Radiant Calibration Sidecar. Gemini 3.1 Pro consolidates. Gemini 3 Flash extracts. Gemini 3.1 Flash-Lite triages. Python verifies. Cloud Run hosts. $10k/month. Forty-eight hours to a working demo. Zero touch to Tom's engine. A drag-drop UI that makes Patrick's *"Promise Market Fit"* mission real. The nail for James's hammer.

**Ship it.**