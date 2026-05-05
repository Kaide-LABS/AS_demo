"""Triage-only dry-run: classify the Pfizer fixture set, print
ArtifactType per artifact, no embedding / no extractors."""
from __future__ import annotations

import asyncio
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import UploadFile

CORPUS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "stress_test_f100" / "pfizer"
FILES = ["10-K_2026-02-26.htm", "10-Q_2025-11-04.htm", "8-K_2026-02-03.htm", "DEF14A_2026-03-12.htm"]


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def main():
    from theater import TheaterBroadcaster
    from parsers.detect import detect_and_parse
    from agents.triage import triage_agent
    from field_state import FieldStateEngine

    uploads = []
    for fname in FILES:
        raw = (CORPUS_DIR / fname).read_text(encoding="utf-8", errors="ignore")
        text = _strip_html(raw)
        out_name = fname.replace(".htm", ".txt")
        uploads.append(UploadFile(filename=out_name, file=io.BytesIO(text.encode("utf-8"))))

    artifacts = await asyncio.gather(*[detect_and_parse(f) for f in uploads])
    broadcaster = TheaterBroadcaster(f"qa-triage-{int(time.time())}")
    manifest = await triage_agent(artifacts, broadcaster)
    print("\n=== TRIAGE CLASSIFICATIONS ===")
    by_id = {a.artifact_id: a for a in artifacts}
    for c in manifest.classifications:
        a = by_id[c.artifact_id]
        print(f"  {a.filename:35s} -> {c.artifact_type.value:25s}  (conf={c.confidence:.2f})")

    plan = FieldStateEngine().plan_extractions(manifest)
    print("\n=== AGENT ASSIGNMENTS ===")
    for a in plan.assignments:
        print(f"  {a.agent_name:30s} <- {len(a.artifact_ids)} artifact(s)")
    assigned_agents = {a.agent_name for a in plan.assignments}
    for must in ["segment_extractor", "verbatim_distiller", "demographic_normalizer"]:
        mark = "ASSIGNED" if must in assigned_agents else "NOT ASSIGNED"
        print(f"  {must:30s} -> {mark}")


if __name__ == "__main__":
    asyncio.run(main())
