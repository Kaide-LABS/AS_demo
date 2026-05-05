# RCS Productization v2 — Architecture Roadmap

## Engagement-Indexed Extraction (flag-gated, segment_extractor only)

**Status:** Infrastructure shipped in `cb355d0`. Flag: `RCS_NIA_EXTRACTION_ENABLED`.
Default off. Validated end-to-end on `segment_extractor`; not yet templated
across the other 5 extractors.

### Findings from chunk diagnostic (2026-04-25)

Diagnostic run via `RCS_CHUNK_DIAGNOSTIC=true` against fixture set #1
(Kantar brand tracker, Ipsos segmentation study, earnings transcripts,
CRM holders).

```
Total chunks returned by Nia (top_k=20): 7
After filter to segment_extractor's assigned artifacts: 5
Score range: 0.50 – 0.64  (mean 0.55)
Per-artifact chunk counts:
  461d616a (Ipsos segmentation):    4 chunks
  c60420f3 (Kantar brand tracker):  1 chunk
  97ca86fe (CRM holders):           1 chunk  [filtered out]
  62a6fede (earnings transcript):   1 chunk  [filtered out]

Top 5 chunks (after filter) cover:
  [0.64] Kantar brand_awareness/purchase_intent header row
  [0.57] Ipsos Segment 1: Institutional Investors
  [0.54] Ipsos Segment 2: Retail Shareholders
  [0.50] Ipsos Segment 3: ESG-Focused Analysts
  [0.52] Ipsos Segment 4: Passive Index Holders
```

**Read:** Nia retrieved from every artifact, the filter kept the 5 most
relevant chunks for segment_extractor, and those 5 chunks cover **every
named segment** in the source material plus the brand metrics scaffold.

**This is the same content the truncation path was already feeding the
LLM** — for this fixture, the first 50KB of the Ipsos study and the
first 50KB of the Kantar tracker contain everything that mattered. The
extra ~95KB the truncation path loads beyond Nia's chunks is filler at
this fixture scale.

That's why segment count (4 vs 4) and latency (65 vs 66s) are identical
between the two paths.

### Open work for v1.1

This is "story (1)" from the diagnostic playbook: truncation already had
the signal. The capability is real but doesn't unlock new behavior at
fixture scale. The work needed before templating:

- **Per-agent NIA_QUERY tuning.** The single query string used in
  segment_extractor is too generic for `verbatim_distiller` (needs
  exact-quote retrieval, not thematic) and `demographic_normalizer`
  (needs structured field retrieval). Templating without tuning each
  query risks regression on the chunk-sensitive agents.

- **Top_k tuning per agent.** Segment retrieval works at k=20 because
  segments are typically named in 4-8 places. Verbatim retrieval may
  need k=50+ to surface page-31 buried quotes that segment_extractor
  doesn't need but the verbatim distiller does.

- **Per-agent retrieval mode.** Some agents (`brand_tone_extractor`)
  may benefit from including LLM synthesis (`skip_llm=false`) to
  compensate for narrow chunking; others (`campaign_benchmark_extractor`)
  are pure structured-data retrieval and should keep `skip_llm=true`.

- **Threshold calibration per agent.** Reranker scores cluster
  differently per agent. The 0.50 threshold used in the canonical-key
  validator is unrelated to the engagement corpus retrieval — chunk
  scores there ranged 0.50–0.64 in the diagnostic, suggesting any
  threshold filter would need its own tuning.

### Trigger condition for re-engagement

Pull this work back in when **any** of:

1. A prospect uploads a corpus exceeding 50KB per artifact (truncation
   starts losing signal).
2. We add agents that need more focused retrieval than segment_extractor
   does — an attribute-level discovery agent, a contradiction surfacer,
   a citation expander.
3. AS pilot feedback indicates Gemini is hallucinating because it
   doesn't know which chunk to ground on (ranking failure mode that
   Nia retrieval would mitigate via explicit chunk selection).

### What's already in place (don't rebuild)

- `validators/nia_corpus.py` — `index_engagement_corpus`,
  `query_engagement_corpus`, `teardown_engagement_corpus`. All
  best-effort; never crash the pipeline.
- `agents/segment_extractor.py` — accepts `engagement_source_id` and
  falls back to truncation cleanly. Pattern is templatable to the
  other 5 extractors when the per-agent tuning above is done.
- `pipeline.py` — indexes the engagement at start, tears down at end,
  passes source id only to segment_extractor for now.
- `tests/test_pipeline_e2e.py` — opt-in gate that toggles the flag
  and asserts segment-count parity + sub-5min latency.
- `RCS_CHUNK_DIAGNOSTIC=true` — dumps chunk-level retrieval to a JSON
  file for offline analysis. Re-run this for each new agent before
  flipping its flag.

### Demo posture

Default `RCS_NIA_EXTRACTION_ENABLED=false`. The demo runs the
truncation path. The Nia capability is the v1.1 narrative for the
post-pilot conversation.

## Templated Extractors (2026-04-25 evening)

In addition to `segment_extractor` (cb355d0), the Nia retrieval pattern
is now templated onto:

### `verbatim_distiller` (commit 32e8b1e) — Story 1

`top_k=30` to handle quote scatter. NIA_QUERY tuned for first-person /
testimonial / participant-statement language.

Diagnostic on fixture set #1:
```
7 chunks returned (top_k=30); after filter to assigned artifacts: 1 chunk
Score range: 0.49 - 0.57  (mean 0.53)
Top match: earnings transcript chunk_5
  "EARNINGS CALL TRANSCRIPT - Q4 2025
   CEO: 'We've seen significant traction with institutional inv..."
```

E2E result: `4 segs / 20 verbs / 5 demos` in both modes. **Story 1** —
identical output between Nia and truncation paths. The single chunk
that survived the `assigned_artifact_ids` filter was the earnings
transcript, which is the only artifact assigned to this agent in the
field-state plan. The truncation path was already feeding the same
content. No regression, no upside on this fixture.

### `demographic_normalizer` (commit 6ceab00) — Story 2

`top_k=20`. NIA_QUERY tuned for tabular demographic content.

Diagnostic on fixture set #1:
```
7 chunks returned (top_k=20); after filter to assigned artifacts: 1 chunk
Score range: 0.46 - 0.61  (mean 0.52)
Top match (post-filter): CRM holders chunk_6
  "holder_name,holder_type,shares_held,pct_outstanding,
   last_engagement,engagement_channel
   BlackRock..."
```

E2E result:
```
baseline (truncation): 4 segs / 20 verbs / 6 demos in 60.9s
nia path:              4 segs / 20 verbs / 8 demos in 254.1s
```

**Story 2 signal.** Nia surfaced **two additional demographic fields**
that the truncation path missed — chunk_6 of the CRM file is past the
50KB truncation boundary, and Gemini extracted demographic richness
from those rows that the baseline never saw.

This is the first templating that actually beat truncation on output
quality. It's also the first one that materially impacted latency:
60s → 254s (4×). Likely cause: three concurrent Nia `/v2/search`
calls per pipeline run (segment + verbatim + demographic) plus the
indexing call, hitting Nia's queue.

### Remaining 3 extractors (deferred)

- `behavioral_extractor` — content overlaps heavily with segments;
  expected Story 1.
- `brand_tone_extractor` — content patterns are diffuse and repeated
  throughout docs; expected Story 1.
- `campaign_benchmark_extractor` — usually concentrated in summary
  sections that fit truncation; expected Story 1.

**Sunday-morning checkpoint decision:** the demographic_normalizer
Story-2 win argues *for* templating the remaining 3 since the
infrastructure works and adds value when content is genuinely past
the 50KB cliff. The 4× latency hit argues *against* — adding 3 more
concurrent Nia calls could push p95 past the 5-minute SLA.

If templating Sunday morning, batch all 3 calls behind a single
indexing wait, and consider serializing the Nia queries to control
concurrency (asyncio.gather → asyncio.gather with semaphore).

Trigger condition for re-engagement (unchanged): prospect uploads a
corpus exceeding 50KB per artifact; AS pilot feedback indicates
truncation-induced hallucinations; new agents are added that need
focused retrieval.

## F100 Stress Test — Unilever (2026-04-26)

Sunday-afternoon validation against real-corpus scale: Unilever's most
recent 20-F (13,935,009 chars), plus two recent 6-Ks (251,962 and
13,997 chars). Total raw text: ~14 million characters across 3 files.

### Smoke test (demo fixtures) — Stage 1, PASS
4 segs / 20 verbs / 5 demos baseline → 4 / 20 / **6 demos** Nia.
Story-2 demographic win from Saturday preserved at small-corpus scale.
137s total. Zero `nia_corpus_index_error` warnings. Confirms Saturday
night's smoke failure was transient.

### F100 stress test — Stage 3, MIXED RESULT

| Metric                | Truncation | Nia  | Delta |
|-----------------------|-----------:|-----:|------:|
| Segments              |          2 |    2 |    0  |
| Verbatims             |         10 |   10 |    0  |
| Demographic attrs     |          0 |    2 |   +2  |
| Behavioral attrs      |          3 |    3 |    0  |
| Psychographic attrs   |          0 |    2 |   +2  |
| Latency               |      30.4s | 71.2s| +135% |

The Nia run hit `nia_corpus_index_error` during engagement indexing.
Most likely cause: the 13.9MB 20-F file exceeds Nia `/v2/sources`
inline-payload limits — `validators/nia_corpus.py` builds the request
body in memory and POSTs the entire file content as a `files[].content`
JSON string. Nia's endpoint rejects or times out on bodies of this size.

When indexing fails, `engagement_source_id` is `None`, and all three
templated extractors fall back to truncation (designed safety
behavior — pipeline never crashes). So both Nia and truncation runs
effectively ran in truncation mode for the 20-F.

The +2 demographic and +2 psychographic deltas above therefore cannot
be cleanly attributed to Nia retrieval. They are most likely Gemini
non-determinism, not architecture signal. **Not a Story-2 win at F100
scale on this corpus shape.**

### Open work (v1.1)

- Chunk large artifacts before sending to `/v2/sources`. Either split
  the 20-F into N body sub-files (one per Item or section), or stream
  chunks via Nia's documented multi-part upload API if one exists.
  Without this, any artifact larger than ~10MB can't be indexed.
- Re-run the F100 stress test with chunked indexing.
- The 5-min SLA is comfortable at small scale; latency at F100 scale
  unknown until indexing succeeds.

### Decision impact

The recorded scale demo for the AS pilot conversation should NOT use
Nia mode on F100-shape corpora today. Either:

1. Demo the small-corpus Story-2 win (+33% demo fields on the existing
   investor-demo fixture set) and frame F100 scale as v1.1; OR
2. Demo truncation-only on F100 fixtures, framing the Nia layer as
   "infrastructure ready, indexing path needs chunked-upload work
   before flipping the flag at this scale."

Default to (1) — the existing demo already tells the cleaner story.

### Bug-fix attempt (2026-04-26 evening) — REVERTED

Diagnosed the failure mode and attempted a chunked-upload fix. Reverted
because end-to-end gate didn't pass.

**What the failure actually is.** Standalone bisect against
`POST /v2/sources` with the Unilever 20-F:

| Inline payload | HTTP | Time |
|---:|:---:|---:|
| 200 KB | 200 ✓ | 3.3s |
| 1 MB   | 200 ✓ | 5.9s |
| 4 MB   | 200 ✓ | 15.7s |
| 9 MB   | **400** | 33.1s — `"No valid files after filtering. Check for binary files, path issues, or ignored patterns."` |

The 14 MB inline body is rejected by Nia's server-side ingestion filter
(misleadingly worded as a binary-file message; it's a size-class trip).

**What was tried.**
1. `_split_into_parts()`: split any artifact whose UTF-8 body exceeded 4 MB
   into ~3.5 MB parts named `<artifact_id>_partN.txt`.
2. `_filename_to_artifact_id()`: extended to strip the `_partN` suffix on
   retrieval so chunks map back to the parent artifact.
3. Upload-POST timeout extended from a fixed 30s to
   `max(120s, 60s + total_bytes / (2 MB/s))` since the chunked POST itself
   takes ~50s for a 14 MB body.
4. `NIA_INDEX_TIMEOUT` raised to 900s.

The standalone POST then succeeded (HTTP 200, source_id returned in 53s).

**Why it still failed end-to-end.** The chunked POST is accepted, but
Nia's actual indexing of the 4 parts (~14 MB total) does not flip the
source's status to `indexed` within 15 minutes. The pipeline polls and
times out. v4 stress run on Unilever:

| Metric | Truncation baseline | Nia v4 |
|---:|:---:|:---:|
| Segments | 2 | 3 |
| Verbatims | 10 | 15 |
| Demos | 0 | 0 |
| Behavioral | 3 | 4 |
| Psychographic | 0 | 3 |
| Latency | 30.4s | **1011s (16.9 min)** |
| Index status | n/a | `nia_corpus_index_timeout` |

The Nia-vs-baseline deltas above are most likely Gemini stochasticity
(when polling times out, all extractors fall back to truncation, so
both runs effectively ran the 20-F in truncation mode). Latency of 16.9
minutes also blows past the 5-minute SLA the small-corpus demo holds.

**Honest verdict.** The chunked-upload code change is necessary but not
sufficient. Nia's *indexing throughput* on a 14 MB corpus is the real
bottleneck, and it's outside our code. Either:

- Nia adds a faster-path or a streaming upload API (vendor-side change).
- We chunk artifacts more aggressively into many smaller sources (one
  per logical section or page range), but that fragments retrieval and
  defeats the per-engagement-corpus design.
- We pre-index well-known artifacts ahead of time and cache by content
  hash; only fresh artifacts pay the indexing cost.

For the AS pilot demo: stays Path 1 — small-corpus Story 2 win is the
narrative; the F100 stress test is the v1.1 conversation.

The revert is on `validators/nia_corpus.py` only; the chunking helpers
and timeout-scaling logic are documented above so a future v1.1 attempt
doesn't have to rediscover the failure shape.

## v1.1 — Retrieval layer migrated Nia → ChromaDB (SHIPPED)

**Status:** Shipped on `main` (this commit). Replaces `validators/nia_corpus.py`
with `retrieval/chroma_corpus.py`. Same async surface
(`index_engagement_corpus` / `query_engagement_corpus` /
`teardown_engagement_corpus`); pipeline + segment/verbatim/demographic agents
import the new module under the existing `nia_corpus` alias so call-sites are
unchanged. Feature flag name `RCS_NIA_EXTRACTION_ENABLED` preserved for env
continuity (synonym `RCS_RETRIEVAL_ENABLED` accepted).

**What this resolves:** the Nia `nia_corpus_index_timeout` / inline-payload
ceiling that blocked the F100 stress test. Indexing now runs locally against
a `chromadb.PersistentClient` at `data/chromadb/`; embeddings come from
Gemini `gemini-embedding-001`. No remote indexing throughput limit.

**Smoke result (Unilever 20-F, this commit):**

| Metric                          | Nia v4 (last attempt) | ChromaDB |
|---------------------------------|----------------------:|---------:|
| Index outcome                   | `nia_corpus_index_timeout` (>15 min) | `indexed` in 25.2s |
| Corpus chars (post HTML strip)  | 1.0M | 1.0M |
| Per-agent query latency         | n/a (fell back to truncation) | 1.7–2.7s |
| Top-k chunks per agent          | n/a | 10 / 10 / 10 |

Smoke harness: `rcs-sidecar/tests/smoke_unilever_chroma.py`. Runs against
the gitignored fixture set `rcs-sidecar/fixtures/stress_test_f100/unilever/`.

**Validator-side Nia is unchanged.** `validators/semantic_validator.py` and
`validators/seed_nia.py` still query Nia against `canonical_vocabulary.json`
(67 keys, 5 families, ~350 aliases). That corpus is small, the Nia reranker
works fine for it, and the email/video pitch language about "Nia" remains
accurate in that scope.

## Architectural decisions

### Why ChromaDB for the retrieval layer (and not a Nia retry)

The v1 attempt tried to bypass Nia's inline-payload limit with chunked
uploads (commit 2123a3e, reverted). That attempt revealed the real ceiling
was *server-side indexing throughput* on a 14MB corpus, not the upload path:
the chunked POST succeeded in 53s, then Nia's downstream indexer never
flipped the source to `indexed` within 15 minutes. That is a vendor-side
bottleneck — no client-side change can fix it without fragmenting the
per-engagement corpus into many sources, which defeats the retrieval design.

ChromaDB sidesteps the entire remote-indexing path. With `PersistentClient`
the work is local, bounded by Gemini embeddings batch latency (seconds for
1MB corpora, scales linearly). The migration costs one new dependency
(`chromadb`) and ~150 LOC; in exchange F100-shape corpora become viable
without renegotiating throughput with a vendor.

The validator's tiny canonical-vocabulary corpus is the opposite shape —
small, static, indexed once via `seed_nia.py` — and Nia's reranker quality
is the value there, not throughput. So the validator stays on Nia.

## RESOLVED — F100 SEC-filing routing gap (commit `5cc3dec`)

**Symptom (flag-ON dry-run, 2026-05-04 Pfizer corpus):** the full
`pipeline.run_calibration` completed cleanly and the ChromaDB collection
was created and torn down, but the three retrieval-aware extractors
(`segment_extractor`, `verbatim_distiller`, `demographic_normalizer`) made
zero `query_engagement_corpus` calls. Result: `fields_validated = 2/11`
because the retrieval-aware agents short-circuited at `if not assigned:
return` before ever reaching the retrieval branch.

**Root cause:** SEC filings (`10-K`, `10-Q`, `20-F`, `8-K`, `6-K`,
`DEF14A`, `S-1/3/4`) classified as `ArtifactType.OTHER` — the only fit in
the existing 9-value enum. `FieldStateEngine.plan_extractions` only routes
`OTHER` to `behavioral_extractor` and `brand_tone_extractor`, so
segment/verbatim/demographic never got an `AgentAssignment`. The retrieval
module itself was healthy — the problem was upstream in triage/planner.

**Resolution:** Added `REGULATORY_FILING = "regulatory_filing"` to
`ArtifactType`, with three surgical edits:
- `schemas.py` — new enum value.
- `agents/triage.py` — filename heuristic (`^(10-?K|10-?Q|20-?F|8-?K|6-?K|DEF\s*14A|S-?[134])`,
  case-insensitive) and a category line in the LLM `SYSTEM_PROMPT`.
- `field_state.py` — `regulatory_filing` added to the type lists for
  `segment_artifacts`, `verbatim_artifacts`, `demographic_artifacts`,
  `behavioral_artifacts`, and `benchmark_artifacts`. (`brand_artifacts`
  is already universal.)

No changes to any extractor, the retrieval module, validators, or the
canonical vocabulary.

**Verification:**

| Path | Pre-fix | Post-fix |
|------|---------|----------|
| Flag-OFF demo (5 sample artifacts) | 9/11 validated, 4 segs, 20 verbs, 22 flagged, 76.1s | **9/11 validated, 4 segs, 20 verbs, 22 flagged, 65.4s** — unchanged |
| Flag-ON F100 Pfizer (10-K + 10-Q + 8-K + DEF14A, ~1.6M post-strip chars) | 2/11 validated, 3 segs, 15 verbs, 24 flagged, 112s, **0 query_calls** | **10/11 validated, 3 segs, 15 verbs, 18 flagged, 84.8s, 3 query_calls** |

ChromaDB lifecycle on the post-fix Pfizer run: `index=1 / query=3
(returned 20/20/30 chunks) / teardown=1`, leftover collections `[]`.

**Generalization verified (2026-05-05).** The same flag-ON harness, parameterized
as `tests/qa_f100_generalization.py`, was run across four industries (pharma,
financial services, tech, consumer goods) to confirm the fix is not
Pfizer-shaped:

| Corpus | Industry | Chars (post-strip) | fields_validated | elapsed | segments | query_calls |
|---|---|---:|---:|---:|---:|---:|
| Pfizer | Pharma | 1.6M | 10/11 | 84.8s | 3 | 3 |
| JPMorgan | Financial services | 2.9M | 10/11 | 152.9s | 5 | 3 |
| Microsoft | Tech | 0.7M | 10/11 | 93.3s | 3 | 3 |
| P&G | Consumer goods | 1.1M | 10/11 | 93.6s | 3 | 3 |

All four corpora pass every acceptance criterion (≥7/11 validated, retrieval
queries fired, <300s, ≥3 segments, no leftover ChromaDB collections).
