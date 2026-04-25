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
