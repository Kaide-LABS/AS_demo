# PHASE_3_SPEC.md — End-to-End Integration, Demo Hardening, and Production Deploy

> For the execution agent. Covers Phase 3 (Hours 60-72 of the 72hr sprint).
> Phase 1 delivered the skeleton. Phase 2 delivered real parsers, LLM-wired agents,
> and the Theater frontend. This phase wires everything end-to-end, hardens for the
> demo video, tunes latency, and deploys to Cloud Run.

---

## 1. Scope

| Stream | What | Hours |
|--------|------|-------|
| **A. End-to-end wiring** | Connect frontend → backend, fix CORS, verify SSE streaming works across the full pipeline | 60-63 |
| **B. Fixture bundle & smoke tests** | Build realistic test artifacts, run full pipeline, verify output schema | 63-66 |
| **C. Prompt hardening** | Tune all agent system prompts for quality, add few-shot examples where needed | 66-68 |
| **D. Latency tuning** | Profile pipeline, optimize token budgets, add timing metadata to Theater events | 68-70 |
| **E. Production deploy** | Cloud Run deploy, smoke test against live revision, environment configuration | 70-72 |

**NOT in scope:** Enterprise connectors, conversational copilot, JWT auth, Redis SSE, cost monitoring, demo video production (handled externally).

---

## 2. Stream A: End-to-end wiring

### 2.1 File: `main.py` — Add CORS middleware

The frontend runs on `localhost:3000`, the backend on `localhost:8080`. Without CORS, the browser blocks the SSE connection and the form POST.

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Placement:** Immediately after `app = FastAPI(...)`, before route definitions.

**Production note:** For Cloud Run, also add the deployed frontend URL (e.g., `https://rcs-frontend.societies.io`) to `allow_origins`. Use an env var:
```python
import os
extra_origins = os.getenv("CORS_ORIGINS", "").split(",")
```

### 2.2 File: `main.py` — Return `job_id` in calibrate response header

The frontend needs the `job_id` before the POST completes (to open the SSE stream). Two options:

**Option A (current approach, already implemented):** Frontend generates `job_id` client-side (`crypto.randomUUID()`) and passes it as a form field. Backend uses it. This is already wired in `page.tsx` and `main.py`. **Verify this works end-to-end.**

**Option B (if Option A breaks):** Backend returns `job_id` in the response JSON. The frontend opens the SSE stream only after receiving the response. This delays Theater streaming. Not preferred.

**Verification test:** Start backend (`uvicorn main:app --port 8080`), start frontend (`cd frontend && npm run dev`), upload a `.txt` file, confirm SSE events appear in the TheaterPanel.

### 2.3 File: `frontend/app/page.tsx` — API base URL configuration

Currently hardcoded to `http://127.0.0.1:8080`. Make configurable:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8080'
```

Replace all instances of `http://127.0.0.1:8080` with `API_BASE`.

Add to `frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=http://127.0.0.1:8080
```

### 2.4 File: `frontend/app/page.tsx` — Error handling for SSE

Add `onerror` handler to EventSource:
```typescript
eventSource.onerror = () => {
  eventSource.close()
  setIsProcessing(false)
}
```

### 2.5 File: `frontend/components/TheaterPanel.tsx` — Expandable meta rows

Phase 2 spec required expandable rows showing model/tokens/latency. Implement:

```typescript
const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

// On click, toggle expanded state
// When expanded, show: model, input_tokens, output_tokens, latency_ms from event.meta
```

Render meta as a gray sub-row:
```tsx
{expandedIdx === i && Object.keys(e.meta).length > 0 && (
  <div className="ml-20 text-xs text-gray-600 mb-2">
    {Object.entries(e.meta).map(([k, v]) => (
      <span key={k} className="mr-4">{k}: {String(v)}</span>
    ))}
  </div>
)}
```

---

## 3. Stream B: Fixture bundle & smoke tests

### 3.1 Directory: `tests/fixtures/`

Create 4 realistic test files:

#### `tests/fixtures/kantar_brand_tracker.csv`
```csv
segment,brand_awareness_pct,purchase_intent_pct,age_range,gender,n_respondents
Institutional Investors,78.2,42.1,35-54,M,312
Retail Shareholders,61.5,33.8,25-44,Mixed,489
ESG-Focused Analysts,85.1,55.2,30-50,Mixed,198
Passive Index Holders,45.3,18.7,40-65,Mixed,248
```

#### `tests/fixtures/ipsos_segments.txt`
```
# Ipsos Shareholder Segmentation Study v3

## Segment 1: Institutional Investors (25.1%)
Active fund managers and institutional allocators who prioritize quarterly earnings guidance
and management credibility. Primary information sources: Bloomberg Terminal, sell-side research,
direct IR contact. Behaviorally characterized by high engagement with earnings calls and
proxy materials.

## Segment 2: Retail Shareholders (39.3%)
Individual investors holding direct equity positions. Information sources: financial news
websites, Reddit/social forums, brokerage app notifications. Lower engagement with formal
IR communications. Price-sensitive with shorter holding periods.

## Segment 3: ESG-Focused Analysts (15.9%)
Analysts and portfolio managers applying ESG scoring frameworks. Information sources:
MSCI ESG ratings, sustainability reports, CDP disclosures. High engagement with
non-financial reporting. Decision-making driven by governance and environmental metrics.

## Segment 4: Passive Index Holders (19.7%)
Investors holding through index funds and ETFs. Minimal direct engagement with individual
company communications. Information sources: fund provider reports, financial media headlines.
Low brand affinity at the individual company level.
```

#### `tests/fixtures/earnings_transcripts.txt`
```
EARNINGS CALL TRANSCRIPT - Q4 2025

CEO: "We've seen significant traction with institutional investors this quarter.
Our new sustainability reporting framework has been very well received by the
ESG community. I'd say that's been the single biggest driver of new interest."

ANALYST Q: "Can you speak to retail shareholder engagement? We've noticed
declining participation in the annual proxy vote."

CFO: "Yes, retail engagement remains a challenge. We're exploring digital-first
communication strategies. The traditional letter-to-shareholders approach
simply doesn't reach the younger demographic anymore."

IR VP: "We've actually piloted a short-form video summary of our quarterly
results on social media. Early data shows 3x the engagement versus our
PDF earnings release. The institutional side doesn't care about format —
they want the data in Bloomberg. But retail wants accessibility."

CEO: "Our brand awareness among passive index holders is frankly low.
That's by design — they're holding us through Vanguard and BlackRock, not
because they chose us specifically. But we need to be visible enough that
if they ever make active allocation decisions, we're on their radar."
```

#### `tests/fixtures/crm_holders.csv`
```csv
holder_name,holder_type,shares_held,pct_outstanding,last_engagement,engagement_channel
BlackRock Fund Advisors,Passive Index,4250000,8.5,2025-11-15,Proxy Vote
Vanguard Group,Passive Index,3800000,7.6,2025-09-20,Annual Meeting
Capital Research,Active Institutional,2100000,4.2,2026-01-10,1-on-1 IR Meeting
Fidelity Management,Active Institutional,1850000,3.7,2025-12-05,Earnings Call
State Street,Passive Index,1500000,3.0,2025-11-15,Proxy Vote
Individual - Smith J,Retail,50000,0.1,2025-10-01,Email Newsletter
Individual - Chen W,Retail,25000,0.05,Never,None
ESG Capital Partners,ESG Fund,750000,1.5,2026-02-15,ESG Briefing
```

### 3.2 File: `tests/test_parsers.py`

```python
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES_DIR, name), "rb") as f:
        return f.read()


@pytest.mark.asyncio
async def test_csv_parser_reads_real_csv():
    from parsers.csv_parser import parse
    raw, tables, meta = await parse(_read_fixture("kantar_brand_tracker.csv"), "kantar.csv")
    assert meta["row_count"] == 4
    assert "Institutional Investors" in raw
    assert len(meta["column_names"]) == 6


@pytest.mark.asyncio
async def test_txt_parser_handles_utf8():
    from parsers.txt_parser import parse
    raw, tables, meta = await parse("Hello résumé café".encode("utf-8"), "test.txt")
    assert "résumé" in raw
    assert meta["encoding"] == "utf-8"


@pytest.mark.asyncio
async def test_txt_parser_falls_back_to_latin1():
    from parsers.txt_parser import parse
    raw, tables, meta = await parse("Hello résumé".encode("latin-1"), "test.txt")
    assert "résumé" in raw
    assert meta["encoding"] == "latin-1"


@pytest.mark.asyncio
async def test_csv_parser_truncates_large_files():
    from parsers.csv_parser import parse
    # Create CSV with 600 rows
    lines = ["col_a,col_b"] + [f"val_{i},data_{i}" for i in range(600)]
    raw, tables, meta = await parse("\n".join(lines).encode(), "big.csv")
    assert meta["row_count"] == 600
    assert meta["truncated"] is True
    assert len(tables) == 500
```

**Dependency:** Add `pytest-asyncio` to dev dependencies or install via `pip3 install pytest-asyncio`.

### 3.3 File: `tests/test_smoke.py`

```python
import os
import sys
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.mark.asyncio
async def test_full_pipeline_offline():
    """
    Run the full pipeline with real fixture files in offline mode (no Gemini client).
    Verify:
    1. Pipeline completes without error.
    2. Output is a valid RadiantPersonaCalibration.
    3. schema_version == "1.1.0"
    4. field_state_summary is populated.
    5. At least 1 segment exists (from mock synthesis).
    """
    from fastapi import UploadFile
    from io import BytesIO
    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    fixture_files = [
        ("kantar_brand_tracker.csv", "text/csv"),
        ("ipsos_segments.txt", "text/plain"),
        ("earnings_transcripts.txt", "text/plain"),
        ("crm_holders.csv", "text/csv"),
    ]

    uploads = []
    for fname, content_type in fixture_files:
        path = os.path.join(FIXTURES_DIR, fname)
        with open(path, "rb") as f:
            data = f.read()
        upload = UploadFile(filename=fname, file=BytesIO(data))
        uploads.append(upload)

    broadcaster = TheaterBroadcaster("test-smoke-job")
    result = await run_calibration("smoke-project", "Test investor audience", uploads, broadcaster)

    assert result.schema_version == "1.1.0"
    assert result.project_id == "smoke-project"
    assert len(result.segments) >= 1
    assert len(result.field_state_summary) > 0
```

### 3.4 File: `tests/test_agents.py`

```python
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import (
    FieldExtractionPlan, AgentAssignment, SourceArtifact, ArtifactType,
    TriageManifest, ArtifactClassification,
)


@pytest.mark.asyncio
async def test_triage_filename_fallback():
    from agents.triage import triage_agent
    from theater import TheaterBroadcaster

    artifacts = [
        SourceArtifact(artifact_id="a1", filename="Brand_Tracker_Q4.csv",
                       raw_text="brand data", size_bytes=100),
        SourceArtifact(artifact_id="a2", filename="CRM_Export.csv",
                       raw_text="crm data", size_bytes=100),
    ]
    broadcaster = TheaterBroadcaster("test")
    manifest = await triage_agent(artifacts, broadcaster)
    types_found = {c.artifact_type for c in manifest.classifications}
    assert ArtifactType.BRAND_TRACKER in types_found
    assert ArtifactType.CRM_EXPORT in types_found


@pytest.mark.asyncio
async def test_extraction_agent_skips_unassigned():
    from agents.segment_extractor import segment_extractor
    from theater import TheaterBroadcaster

    plan = FieldExtractionPlan(assignments=[
        AgentAssignment(agent_name="verbatim_distiller", target_fields=["v"],
                        artifact_ids=["a1"], priority=1),
    ])
    artifacts = [SourceArtifact(artifact_id="a1", filename="test.txt",
                                raw_text="data", size_bytes=10)]
    broadcaster = TheaterBroadcaster("test")
    result = await segment_extractor(artifacts, plan, broadcaster)
    assert result.validation_passed is True
    assert result.extracted_fields == {}
```

---

## 4. Stream C: Prompt hardening

### 4.1 All agent system prompts — Add output format enforcement

Every agent's system prompt must end with:
```
CRITICAL: Your response must be valid JSON matching the provided schema.
Do not include markdown code fences, explanatory text, or any content
outside the JSON object.
```

### 4.2 File: `agents/triage.py` — Add few-shot example

Add to the system prompt:
```
Example classification:
Input: filename="Kantar_Brand_Health_2025.sav", preview="Variable: brand_awareness..."
Output: {"artifact_type": "brand_tracker", "confidence": 0.95, "extraction_strategy": "default"}
```

### 4.3 File: `agents/segment_extractor.py` — Constrain weight generation

Add to system prompt:
```
IMPORTANT: Segment weights MUST sum to exactly 1.0.
Calculate weights as proportions of the total audience.
Double-check your arithmetic before outputting.
```

### 4.4 File: `pipeline.py` — Add token count metadata to SSE events

After each Gemini call, include token counts in the SSE `meta` field:
```python
meta = {
    "model": MODEL_FLASH,
    "input_tokens": response.usage_metadata.prompt_token_count,
    "output_tokens": response.usage_metadata.candidates_token_count,
    "latency_ms": int((end_time - start_time) * 1000),
}
```

This requires the `generate_structured` and `generate_text` functions in `agents/client.py` to return the full response object (or at least the usage metadata) in addition to the parsed result.

**Suggested approach:** Modify `generate_structured` to return a tuple `(parsed_result, usage_meta)`:
```python
async def generate_structured(...) -> tuple[BaseModel, dict]:
    ...
    usage = {
        "input_tokens": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
        "output_tokens": response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
    }
    return result, usage
```

**Then update all callers** to unpack the tuple. For offline mode, return `(mock_result, {})`.

---

## 5. Stream D: Latency tuning

### 5.1 Artifact text truncation budget

Currently agents receive `raw_text[:50000]` per artifact. Profile and adjust:
- If total input across all artifacts exceeds 100K chars, truncate proportionally.
- For synthesis agent: the Evidence Merger already reduces input. Verify it stays under 500K tokens.

### 5.2 Parallel extraction timing

Add `time.time()` around `asyncio.gather()` in `pipeline.py`:
```python
import time
t0 = time.time()
extractions = await asyncio.gather(...)
extraction_latency = time.time() - t0
await broadcaster.emit("extract", f"Extraction complete in {extraction_latency:.1f}s")
```

### 5.3 Synthesis agent token budget

If the evidence graph exceeds 200K tokens (the cheaper pricing tier), consider:
1. Truncating evidence nodes to top-5 per field (by confidence).
2. Summarizing contradictions to just the field path and competing values (not full nodes).

---

## 6. Stream E: Production deploy

### 6.1 Pre-deploy checklist

- [ ] All tests pass locally
- [ ] `requirements.txt` includes `pdfplumber`
- [ ] `Dockerfile` builds successfully (`docker build -t rcs-sidecar .`)
- [ ] `.env.example` is up to date
- [ ] No `__pycache__` in git (`.gitignore` covers this)
- [ ] CORS origins include the deployed frontend URL

### 6.2 File: `deploy.sh` — Verify unchanged

```bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
gcloud run deploy rcs-sidecar \
  --source=. \
  --region=us-central1 \
  --service-account=rcs-sa@${PROJECT}.iam.gserviceaccount.com \
  --cpu=2 --memory=2Gi \
  --min-instances=1 --max-instances=50 \
  --concurrency=40 --cpu-boost --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global" \
  --no-allow-unauthenticated
```

### 6.3 Post-deploy smoke test

After `deploy.sh` succeeds:
1. Get the Cloud Run service URL: `gcloud run services describe rcs-sidecar --region=us-central1 --format='value(status.url)'`
2. Hit `GET /healthz` — assert `{"status": "ok", "version": "1.1.0"}`
3. Upload the 4-file fixture bundle via `POST /v1/calibrate` — assert HTTP 200 + valid schema
4. Verify SSE stream delivers events in real-time

### 6.4 Frontend deployment

The frontend can be deployed as:
- **Static export:** `next build && next export` → serve from Cloud Storage + CDN
- **Cloud Run:** Separate service running `next start`
- **For demo:** `npm run dev` locally pointing at the Cloud Run backend URL

Set `NEXT_PUBLIC_API_URL` to the Cloud Run service URL in the frontend's `.env.production`.

---

## 7. New tests to add

| Test file | Test name | What it verifies |
|-----------|-----------|------------------|
| `test_parsers.py` | `test_csv_parser_reads_real_csv` | CSV parsing with real fixture |
| `test_parsers.py` | `test_txt_parser_handles_utf8` | UTF-8 encoding |
| `test_parsers.py` | `test_txt_parser_falls_back_to_latin1` | Latin-1 fallback |
| `test_parsers.py` | `test_csv_parser_truncates_large_files` | 500-row truncation |
| `test_smoke.py` | `test_full_pipeline_offline` | End-to-end pipeline with fixtures |
| `test_agents.py` | `test_triage_filename_fallback` | Heuristic classifier |
| `test_agents.py` | `test_extraction_agent_skips_unassigned` | Plan filtering |

---

## 8. Execution order

| Order | Task | Est. LOC |
|-------|------|----------|
| 1 | Create `tests/fixtures/` with 4 test files | ~60 |
| 2 | Add CORS middleware to `main.py` | ~10 |
| 3 | Make frontend API URL configurable | ~5 |
| 4 | Add EventSource error handler in `page.tsx` | ~5 |
| 5 | Add expandable meta rows to `TheaterPanel.tsx` | ~20 |
| 6 | Write `tests/test_parsers.py` | ~50 |
| 7 | Write `tests/test_agents.py` | ~40 |
| 8 | Write `tests/test_smoke.py` | ~40 |
| 9 | Harden all agent system prompts | ~30 |
| 10 | Add timing metadata to SSE events in pipeline.py | ~20 |
| 11 | Modify `generate_structured` to return usage metadata | ~15 |
| 12 | Verify Docker build | manual |
| 13 | Run `deploy.sh` | manual |
| 14 | Post-deploy smoke test | manual |

**Total estimated LOC:** ~295

---

## 9. What is NOT in this spec (post-sprint)

- Enterprise connectors (Google Drive, SharePoint, S3)
- Conversational interview copilot
- Per-section user approval UI
- JWT authentication
- Redis/Pub/Sub for multi-instance SSE
- Prompt caching optimization
- Cost monitoring dashboard
- Demo video production (handled by the team externally)
