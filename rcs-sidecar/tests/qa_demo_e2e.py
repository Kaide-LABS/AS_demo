"""QA verification: end-to-end demo run with RCS_NIA_EXTRACTION_ENABLED=false.

Confirms the post-migration main is transparent for the pitched 5-artifact
~90s magic-moment scenario. Flag OFF -> truncation path; ChromaDB and the
retrieval module must not be touched.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["RCS_NIA_EXTRACTION_ENABLED"] = "false"

from fastapi import UploadFile

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo" / "sample_artifacts"
FILES = [
    "executive_report.md",
    "interview_transcripts.md",
    "persona_brief.txt",
    "screener.qsf",
    "survey_responses.csv",
]


def _make_uploads():
    uploads = []
    for fname in FILES:
        path = DEMO_DIR / fname
        with open(path, "rb") as f:
            data = f.read()
        uploads.append(UploadFile(filename=fname, file=io.BytesIO(data)))
    return uploads


async def main():
    # Sentinel: mark retrieval module so any unexpected call sets a flag.
    from retrieval import chroma_corpus
    chroma_corpus._QA_TOUCHED = False
    orig_index = chroma_corpus.index_engagement_corpus
    orig_query = chroma_corpus.query_engagement_corpus
    orig_teardown = chroma_corpus.teardown_engagement_corpus

    async def _trip_index(*a, **kw):
        chroma_corpus._QA_TOUCHED = True
        return await orig_index(*a, **kw)

    async def _trip_query(*a, **kw):
        chroma_corpus._QA_TOUCHED = True
        return await orig_query(*a, **kw)

    async def _trip_teardown(*a, **kw):
        chroma_corpus._QA_TOUCHED = True
        return await orig_teardown(*a, **kw)

    chroma_corpus.index_engagement_corpus = _trip_index
    chroma_corpus.query_engagement_corpus = _trip_query
    chroma_corpus.teardown_engagement_corpus = _trip_teardown

    chroma_dir = Path("data/chromadb")
    pre_collections = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []

    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    uploads = _make_uploads()
    broadcaster = TheaterBroadcaster(f"qa-{int(time.time())}")
    print(f"FLAG: RCS_NIA_EXTRACTION_ENABLED={os.getenv('RCS_NIA_EXTRACTION_ENABLED')}")
    print(f"Artifacts: {len(uploads)} from {DEMO_DIR}")
    print(f"Pre-run chroma entries: {len(pre_collections)}")

    t0 = time.monotonic()
    result = await run_calibration(
        "qa-project", "Investor audience for AS pilot", uploads, broadcaster
    )
    elapsed = time.monotonic() - t0

    post_collections = sorted([p.name for p in chroma_dir.iterdir()]) if chroma_dir.exists() else []
    new_collections = [c for c in post_collections if c not in pre_collections]

    segs = getattr(result, "segments", None) or []
    if not segs and getattr(result, "calibration", None):
        segs = result.calibration.segments
    n_segs = len(segs)
    n_verbs = sum(len(getattr(s, "verbatims", []) or []) for s in segs)
    n_demos = sum(len(getattr(s, "demographic_attributes", []) or []) for s in segs)
    n_behav = sum(len(getattr(s, "behavioral_attributes", []) or []) for s in segs)
    n_psych = sum(len(getattr(s, "psychographic_attributes", []) or []) for s in segs)

    fs = getattr(result, "field_state_summary", {}) or {}
    n_validated = sum(1 for v in fs.values() if getattr(v, "value", str(v)).lower() == "validated")
    n_total_fields = len(fs) or 11
    coverage_gaps = getattr(result, "coverage_gaps", []) or []

    requires_review = sum(1 for s in segs if getattr(s, "requires_human_review", False))
    flagged = len(coverage_gaps) + requires_review

    print("\n=== RESULT ===")
    print(f"elapsed_s             = {elapsed:.1f}")
    print(f"segments              = {n_segs}")
    print(f"verbatims             = {n_verbs}")
    print(f"demographics          = {n_demos}")
    print(f"behavioral            = {n_behav}")
    print(f"psychographic         = {n_psych}")
    print(f"fields_validated      = {n_validated}/{n_total_fields}")
    print(f"coverage_gaps         = {len(coverage_gaps)}")
    print(f"segments_need_review  = {requires_review}")
    print(f"anti_halluc_flagged   = {flagged}")
    print(f"chroma_module_touched = {chroma_corpus._QA_TOUCHED}")
    print(f"chroma_new_collections= {new_collections}")

    fail = []
    if not segs:
        fail.append("no segments produced")
    if elapsed > 90:
        fail.append(f"latency {elapsed:.1f}s exceeds 90s SLA")
    if chroma_corpus._QA_TOUCHED:
        fail.append("retrieval module was called with flag OFF")
    if new_collections:
        fail.append(f"new chroma collections created: {new_collections}")

    if fail:
        print("\nQA FAIL: " + "; ".join(fail))
        sys.exit(1)
    print("\nQA PASS")


if __name__ == "__main__":
    asyncio.run(main())
