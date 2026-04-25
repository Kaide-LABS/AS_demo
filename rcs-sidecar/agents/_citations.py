"""Shared citation coercion used by all extractors.

Model output varies in field names (page_locator, row, section_id, page, etc).
We normalize to SourceCitation via a few common aliases and fall back to a
synthetic citation tied to each assigned artifact when the model omits them.
"""
from typing import Iterable
from schemas import SourceArtifact, SourceCitation, ArtifactType

_LOCATOR_ALIASES = ("locator", "page_locator", "page", "row", "section_id", "section", "cell", "question_id")


def _artifact_index(artifacts: Iterable[SourceArtifact]) -> dict[str, SourceArtifact]:
    return {a.artifact_id: a for a in artifacts}


def coerce_citations(
    raw: list[dict] | None,
    filtered_artifacts: list[SourceArtifact],
    default_locator: str = "inline",
) -> list[SourceCitation]:
    """Turn a model-returned list of citation dicts into SourceCitation objects.
    Tolerates missing fields, aliases for locator, and wrong artifact_type values.
    Falls back to a synthetic per-artifact citation if `raw` is empty.
    """
    by_id = _artifact_index(filtered_artifacts)
    out: list[SourceCitation] = []

    for c in (raw or []):
        if not isinstance(c, dict):
            continue
        aid = c.get("artifact_id") or (next(iter(by_id), "") if by_id else "")
        # locator
        locator = ""
        for k in _LOCATOR_ALIASES:
            if k in c and c[k]:
                locator = str(c[k])
                break
        excerpt = str(c.get("excerpt", ""))[:500]
        # artifact_type
        a = by_id.get(aid)
        art_type = a.artifact_type if (a and a.artifact_type) else ArtifactType.OTHER
        if "artifact_type" in c:
            try:
                art_type = ArtifactType(c["artifact_type"])
            except ValueError:
                pass
        try:
            out.append(SourceCitation(
                artifact_id=aid or "unknown",
                artifact_type=art_type,
                locator=locator or default_locator,
                excerpt=excerpt,
            ))
        except Exception:
            continue

    if not out and filtered_artifacts:
        # Synthetic fallback: one citation per artifact so merger sees non-zero nodes.
        for a in filtered_artifacts:
            out.append(SourceCitation(
                artifact_id=a.artifact_id,
                artifact_type=a.artifact_type or ArtifactType.OTHER,
                locator=default_locator,
                excerpt=(a.raw_text[:300] if a.raw_text else "")[:500],
            ))
    return out
