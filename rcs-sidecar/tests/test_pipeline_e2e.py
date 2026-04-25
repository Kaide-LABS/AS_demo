"""End-to-end pipeline test for the segment_extractor refactor.

Runs the full /v1/calibrate pipeline against a fixture set with
RCS_NIA_EXTRACTION_ENABLED toggled on and off, then compares.

Opt-in: requires NIA_LIVE_TEST=1, NIA_API_KEY, GEMINI_API_KEY.
Costs real Gemini money. Skipped in CI by default.
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import UploadFile

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_FILES = [
    ("kantar_brand_tracker.csv", "text/csv"),
    ("ipsos_segments.txt", "text/plain"),
    ("earnings_transcripts.txt", "text/plain"),
    ("crm_holders.csv", "text/csv"),
]


def _make_uploads():
    uploads = []
    for fname, _ct in FIXTURE_FILES:
        path = FIXTURES_DIR / fname
        with open(path, "rb") as f:
            data = f.read()
        uploads.append(UploadFile(filename=fname, file=io.BytesIO(data)))
    return uploads


async def _run(enabled: bool):
    os.environ["RCS_NIA_EXTRACTION_ENABLED"] = "true" if enabled else "false"
    # Force module-level re-read of the flag.
    from validators import nia_corpus
    nia_corpus.EXTRACTION_ENABLED = enabled

    from theater import TheaterBroadcaster
    from pipeline import run_calibration

    uploads = _make_uploads()
    broadcaster = TheaterBroadcaster(f"e2e-{int(time.time())}-{int(enabled)}")
    t0 = time.monotonic()
    result = await run_calibration("e2e-project", "Investor audience", uploads, broadcaster)
    elapsed = time.monotonic() - t0
    return result, elapsed


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("NIA_LIVE_TEST") != "1"
    or not os.getenv("NIA_API_KEY")
    or not os.getenv("GEMINI_API_KEY"),
    reason="set NIA_LIVE_TEST=1, NIA_API_KEY, GEMINI_API_KEY to run",
)
async def test_pipeline_with_and_without_nia_extraction():
    try:
        import magic  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("libmagic not available")

    def _counts(result):
        segs = getattr(result, "segments", None) or getattr(
            getattr(result, "calibration", None), "segments", []
        ) or []
        verbs = sum(len(getattr(s, "verbatims", []) or []) for s in segs)
        demos = sum(len(getattr(s, "demographic_attributes", []) or []) for s in segs)
        return segs, verbs, demos

    print("\n>>> baseline run (truncation path)")
    base, base_t = await _run(enabled=False)
    base_segs, base_verbs, base_demos = _counts(base)
    print(f"  elapsed={base_t:.1f}s  segments={len(base_segs)}  verbatims={base_verbs}  demographics={base_demos}")

    print("\n>>> nia run (extraction path)")
    nia, nia_t = await _run(enabled=True)
    nia_segs, nia_verbs, nia_demos = _counts(nia)
    print(f"  elapsed={nia_t:.1f}s  segments={len(nia_segs)}  verbatims={nia_verbs}  demographics={nia_demos}")

    print(f"\nbaseline: {len(base_segs)} segs / {base_verbs} verbs / {base_demos} demos in {base_t:.1f}s")
    print(f"nia:      {len(nia_segs)} segs / {nia_verbs} verbs / {nia_demos} demos in {nia_t:.1f}s")

    assert len(nia_segs) >= 1, "nia path produced no segments"
    assert nia_t < 300, f"nia path too slow: {nia_t:.1f}s"
    assert len(nia_segs) >= max(1, len(base_segs) - 1), (
        f"nia path regressed segment count: {len(nia_segs)} vs baseline {len(base_segs)}"
    )
    assert nia_verbs >= base_verbs, (
        f"nia path regressed verbatim count: {nia_verbs} vs baseline {base_verbs}"
    )
    assert nia_demos >= base_demos, (
        f"nia path regressed demographic count: {nia_demos} vs baseline {base_demos}"
    )
