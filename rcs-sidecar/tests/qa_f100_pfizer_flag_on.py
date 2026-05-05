"""F100 end-to-end QA: full pipeline.run_calibration() with flag ON.

Verifies the post-migration retrieval path works through the real
/v1/calibrate entrypoint, against a fresh F100 corpus (Pfizer, NOT
Unilever) so we don't accidentally pass on a corpus the smoke harness
already touched.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["RCS_NIA_EXTRACTION_ENABLED"] = "true"

from fastapi import UploadFile

CORPUS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "stress_test_f100" / "pfizer"
FILES = [
    "10-K_2026-02-26.htm",
    "10-Q_2025-11-04.htm",
    "8-K_2026-02-03.htm",
    "DEF14A_2026-03-12.htm",
]
BRIEF = (
    "Calibrate audience segments for Pfizer's FY2026 investor relations "
    "positioning, focused on institutional shareholders, sell-side analysts, "
    "and ESG-mandate funds evaluating large-cap pharmaceutical equity."
)


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _make_uploads():
    """Pre-strip HTML to plain text so the demo parser path receives uploadable
    content. We send .txt because the demo's pdf/docx/etc parsers don't ingest
    raw .htm; this matches what a prospect would send if they pre-converted."""
    uploads = []
    total_chars = 0
    for fname in FILES:
        raw = (CORPUS_DIR / fname).read_text(encoding="utf-8", errors="ignore")
        text = _strip_html(raw)
        total_chars += len(text)
        out_name = fname.replace(".htm", ".txt")
        uploads.append(UploadFile(filename=out_name, file=io.BytesIO(text.encode("utf-8"))))
    return uploads, total_chars


async def main():
    # Wrap retrieval module so we can OBSERVE (not block) calls.
    from retrieval import chroma_corpus
    chroma_corpus.EXTRACTION_ENABLED = True

    activity = {
        "index_calls": 0,
        "query_calls": 0,
        "teardown_calls": 0,
        "source_id": None,
        "queries": [],
    }

    orig_index = chroma_corpus.index_engagement_corpus
    orig_query = chroma_corpus.query_engagement_corpus
    orig_teardown = chroma_corpus.teardown_engagement_corpus

    async def wrapped_index(project_id, artifacts):
        activity["index_calls"] += 1
        sid = await orig_index(project_id, artifacts)
        activity["source_id"] = sid
        return sid

    async def wrapped_query(source_id, query, top_k=20):
        activity["query_calls"] += 1
        chunks = await orig_query(source_id, query, top_k=top_k)
        activity["queries"].append({
            "query": query[:80],
            "top_k": top_k,
            "returned": len(chunks),
        })
        return chunks

    async def wrapped_teardown(source_id):
        activity["teardown_calls"] += 1
        return await orig_teardown(source_id)

    chroma_corpus.index_engagement_corpus = wrapped_index
    chroma_corpus.query_engagement_corpus = wrapped_query
    chroma_corpus.teardown_engagement_corpus = wrapped_teardown

    chroma_dir = Path("data/chromadb")
    pre_collections = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []

    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    uploads, total_chars = _make_uploads()
    print(f"FLAG: RCS_NIA_EXTRACTION_ENABLED={os.getenv('RCS_NIA_EXTRACTION_ENABLED')}")
    print(f"Corpus: Pfizer (4 filings, {total_chars:,} post-strip chars)")
    print(f"Brief: {BRIEF}")
    print(f"Pre-run chroma entries: {len(pre_collections)}")

    broadcaster = TheaterBroadcaster(f"qa-f100-{int(time.time())}")
    t0 = time.monotonic()
    try:
        result = await run_calibration("qa-f100-pfizer", BRIEF, uploads, broadcaster)
    except Exception as e:
        import traceback
        print("\nPIPELINE EXCEPTION:")
        traceback.print_exc()
        sys.exit(1)
    elapsed = time.monotonic() - t0

    post_collections = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []
    new_collections = [c for c in post_collections if c not in pre_collections]
    leftover = [c for c in new_collections if c == activity["source_id"]]

    segs = getattr(result, "segments", None) or []
    if not segs and getattr(result, "calibration", None):
        segs = result.calibration.segments
    n_segs = len(segs)
    n_verbs = sum(len(getattr(s, "verbatims", []) or []) for s in segs)
    n_demos = sum(len(getattr(s, "demographic_attributes", []) or []) for s in segs)
    n_behav = sum(len(getattr(s, "behavioral_attributes", []) or []) for s in segs)
    n_psych = sum(len(getattr(s, "psychographic_attributes", []) or []) for s in segs)
    per_seg_verbs = [len(getattr(s, "verbatims", []) or []) for s in segs]

    fs = getattr(result, "field_state_summary", {}) or {}
    n_validated = sum(1 for v in fs.values() if getattr(v, "value", str(v)).lower() == "validated")
    n_total_fields = len(fs) or 11
    coverage_gaps = getattr(result, "coverage_gaps", []) or []
    requires_review = sum(1 for s in segs if getattr(s, "requires_human_review", False))
    flagged = len(coverage_gaps) + requires_review

    print("\n=== RESULT ===")
    print(f"elapsed_s            = {elapsed:.1f}")
    print(f"segments             = {n_segs}")
    print(f"  verbatims/seg      = {per_seg_verbs}")
    print(f"verbatims (total)    = {n_verbs}")
    print(f"demographics         = {n_demos}")
    print(f"behavioral           = {n_behav}")
    print(f"psychographic        = {n_psych}")
    print(f"fields_validated     = {n_validated}/{n_total_fields}")
    print(f"coverage_gaps        = {len(coverage_gaps)}")
    print(f"segments_need_review = {requires_review}")
    print(f"anti_halluc_flagged  = {flagged}")

    print("\n=== ChromaDB lifecycle ===")
    print(f"index_calls          = {activity['index_calls']}")
    print(f"query_calls          = {activity['query_calls']}")
    print(f"teardown_calls       = {activity['teardown_calls']}")
    print(f"source_id (created)  = {activity['source_id']}")
    print(f"new_collections      = {new_collections}")
    print(f"leftover_after_run   = {leftover}  (should be [])")
    for q in activity["queries"]:
        print(f"  query: top_k={q['top_k']:>2}  returned={q['returned']:>2}  '{q['query']}...'")


if __name__ == "__main__":
    asyncio.run(main())
