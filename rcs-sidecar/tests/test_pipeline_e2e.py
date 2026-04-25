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

    print("\n>>> baseline run (truncation path)")
    base, base_t = await _run(enabled=False)
    base_segs = getattr(base, "segments", None) or getattr(getattr(base, "calibration", None), "segments", [])
    print(f"  elapsed={base_t:.1f}s  segments={len(base_segs)}")

    print("\n>>> nia run (extraction path)")
    nia, nia_t = await _run(enabled=True)
    nia_segs = getattr(nia, "segments", None) or getattr(getattr(nia, "calibration", None), "segments", [])
    print(f"  elapsed={nia_t:.1f}s  segments={len(nia_segs)}")

    print(f"\nbaseline: {len(base_segs)} segments in {base_t:.1f}s")
    print(f"nia:      {len(nia_segs)} segments in {nia_t:.1f}s")

    assert len(nia_segs) >= 1, "nia path produced no segments"
    assert nia_t < 300, f"nia path too slow: {nia_t:.1f}s"
    # Soft expectation: nia path produces at least as many segments as baseline
    assert len(nia_segs) >= max(1, len(base_segs) - 1), (
        f"nia path regressed segment count: {len(nia_segs)} vs baseline {len(base_segs)}"
    )
