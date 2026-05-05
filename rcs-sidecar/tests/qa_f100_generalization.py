"""Parameterized F100 generalization harness.

Mirrors qa_f100_pfizer_flag_on.py but accepts a company directory as a
CLI arg. Used to verify the REGULATORY_FILING routing fix generalizes
beyond the Pfizer baseline.

Usage:
    python tests/qa_f100_generalization.py <company>

where <company> is a subdirectory under fixtures/stress_test_f100/.
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

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "stress_test_f100"


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _make_uploads(corpus_dir: Path):
    uploads = []
    total_chars = 0
    files = sorted(corpus_dir.glob("*.htm"))
    if not files:
        raise SystemExit(f"no .htm files in {corpus_dir}")
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="ignore")
        text = _strip_html(raw)
        total_chars += len(text)
        out_name = f.name.replace(".htm", ".txt")
        uploads.append(UploadFile(filename=out_name, file=io.BytesIO(text.encode("utf-8"))))
    return uploads, total_chars, [f.name for f in files]


async def main():
    if len(sys.argv) < 2:
        print("usage: qa_f100_generalization.py <company>")
        sys.exit(2)
    company = sys.argv[1].lower()
    corpus_dir = ROOT / company
    if not corpus_dir.is_dir():
        print(f"FAIL: no fixture directory at {corpus_dir}")
        sys.exit(2)

    from retrieval import chroma_corpus
    chroma_corpus.EXTRACTION_ENABLED = True

    activity = {"index_calls": 0, "query_calls": 0, "teardown_calls": 0,
                "source_id": None, "queries": []}
    orig_index = chroma_corpus.index_engagement_corpus
    orig_query = chroma_corpus.query_engagement_corpus
    orig_teardown = chroma_corpus.teardown_engagement_corpus

    async def w_index(pid, arts):
        activity["index_calls"] += 1
        sid = await orig_index(pid, arts)
        activity["source_id"] = sid
        return sid

    async def w_query(sid, q, top_k=20):
        activity["query_calls"] += 1
        chunks = await orig_query(sid, q, top_k=top_k)
        activity["queries"].append({"query": q[:80], "top_k": top_k, "returned": len(chunks)})
        return chunks

    async def w_teardown(sid):
        activity["teardown_calls"] += 1
        return await orig_teardown(sid)

    chroma_corpus.index_engagement_corpus = w_index
    chroma_corpus.query_engagement_corpus = w_query
    chroma_corpus.teardown_engagement_corpus = w_teardown

    chroma_dir = Path("data/chromadb")
    pre = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []

    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    uploads, total_chars, filenames = _make_uploads(corpus_dir)
    company_label = company.capitalize()
    brief = (
        f"Calibrate audience segments for {company_label}'s most recent investor "
        "reporting cycle, focused on enterprise stakeholder personas evaluating "
        "the company's strategic positioning."
    )
    print(f"FLAG: RCS_NIA_EXTRACTION_ENABLED={os.getenv('RCS_NIA_EXTRACTION_ENABLED')}")
    print(f"Company: {company_label}")
    print(f"Corpus: {len(filenames)} filings, {total_chars:,} post-strip chars")
    print(f"Files: {filenames}")
    print(f"Brief: {brief}")
    print(f"Pre-run chroma entries: {len(pre)}")

    broadcaster = TheaterBroadcaster(f"qa-f100-{company}-{int(time.time())}")
    t0 = time.monotonic()
    try:
        result = await run_calibration(f"qa-f100-{company}", brief, uploads, broadcaster)
    except Exception:
        import traceback
        print("\nPIPELINE EXCEPTION:")
        traceback.print_exc()
        sys.exit(1)
    elapsed = time.monotonic() - t0

    post = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []
    new_collections = [c for c in post if c not in pre]
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
    n_total = len(fs) or 11
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
    print(f"fields_validated     = {n_validated}/{n_total}")
    print(f"coverage_gaps        = {len(coverage_gaps)}")
    print(f"segments_need_review = {requires_review}")
    print(f"anti_halluc_flagged  = {flagged}")

    print("\n=== ChromaDB lifecycle ===")
    print(f"index_calls          = {activity['index_calls']}")
    print(f"query_calls          = {activity['query_calls']}")
    print(f"teardown_calls       = {activity['teardown_calls']}")
    print(f"source_id            = {activity['source_id']}")
    print(f"new_collections      = {new_collections}")
    print(f"leftover_after_run   = {leftover}  (should be [])")
    for q in activity["queries"]:
        print(f"  query: top_k={q['top_k']:>2}  returned={q['returned']:>2}  '{q['query']}...'")

    fail = []
    if n_validated < 7:
        fail.append(f"fields_validated={n_validated}/{n_total} below 7/11")
    if activity["query_calls"] == 0:
        fail.append("query_calls=0 (retrieval not exercised)")
    if elapsed >= 300:
        fail.append(f"elapsed={elapsed:.1f}s exceeds 300s")
    if n_segs < 3:
        fail.append(f"segments={n_segs} below 3")
    if leftover:
        fail.append(f"leftover collections: {leftover}")
    print("\n" + ("PASS" if not fail else "FAIL: " + "; ".join(fail)))
    sys.exit(0 if not fail else 1)


if __name__ == "__main__":
    asyncio.run(main())
