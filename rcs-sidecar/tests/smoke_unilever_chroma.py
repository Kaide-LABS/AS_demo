"""F100 smoke test: ChromaDB indexes the full Unilever 20-F corpus that
hit the Nia indexing throughput ceiling.

Pre-req env:
  GEMINI_API_KEY=...
  RCS_NIA_EXTRACTION_ENABLED=true

Run:
  cd rcs-sidecar
  python tests/smoke_unilever_chroma.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class FakeArtifact:
    def __init__(self, artifact_id: str, raw_text: str, filename: str):
        self.artifact_id = artifact_id
        self.raw_text = raw_text
        self.filename = filename


async def main():
    if not os.getenv("GEMINI_API_KEY"):
        print("FAIL: GEMINI_API_KEY not set")
        sys.exit(2)
    os.environ["RCS_NIA_EXTRACTION_ENABLED"] = "true"

    from retrieval import chroma_corpus
    chroma_corpus.EXTRACTION_ENABLED = True

    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "stress_test_f100" / "unilever"
    files = sorted(fixture_dir.glob("*.htm"))
    if not files:
        print(f"FAIL: no fixtures in {fixture_dir}")
        sys.exit(2)

    artifacts = []
    total_chars = 0
    for f in files:
        raw_html = f.read_text(encoding="utf-8", errors="ignore")
        text = _strip_html(raw_html)
        total_chars += len(text)
        artifacts.append(FakeArtifact(
            artifact_id=f.stem.replace("-", "_"),
            raw_text=text,
            filename=f.name,
        ))
        print(f"  loaded {f.name}: {len(text):,} chars")

    print(f"\nTotal corpus: {total_chars:,} chars across {len(artifacts)} files")

    # ---- Index ----
    t0 = time.monotonic()
    source_id = await chroma_corpus.index_engagement_corpus("unilever_smoke", artifacts)
    index_elapsed = time.monotonic() - t0
    if not source_id:
        print(f"FAIL: indexing returned None (elapsed {index_elapsed:.1f}s)")
        sys.exit(1)
    print(f"\nINDEX OK: source_id={source_id}  elapsed={index_elapsed:.1f}s")

    # ---- Query ----
    queries = [
        ("segment_extractor", "audience segments, customer types, named market subgroups"),
        ("verbatim_distiller", "direct quotes, statements, what executives or customers said"),
        ("demographic_normalizer", "demographic breakdown, geographic region, income bracket"),
    ]
    all_ok = True
    for label, q in queries:
        t1 = time.monotonic()
        chunks = await chroma_corpus.query_engagement_corpus(source_id, q, top_k=10)
        q_elapsed = time.monotonic() - t1
        if not chunks:
            print(f"  [{label}] FAIL: 0 chunks (elapsed {q_elapsed:.2f}s)")
            all_ok = False
            continue
        scores = [c["score"] for c in chunks]
        print(f"  [{label}] {len(chunks)} chunks  elapsed={q_elapsed:.2f}s  "
              f"score range={min(scores):.2f}–{max(scores):.2f}  "
              f"top artifact={chunks[0]['artifact_id']}")

    # ---- Teardown ----
    await chroma_corpus.teardown_engagement_corpus(source_id)
    print("\nTEARDOWN OK")

    if not all_ok:
        sys.exit(1)
    print("\nSMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
