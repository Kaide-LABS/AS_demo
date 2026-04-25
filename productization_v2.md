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
