"""
Semantic validator for canonical attribute vocabulary.

Nia HTTP API contract (build-time, validated empirically 2026-04-25)
====================================================================
Base URL ........... https://apigcp.trynia.ai/v2
                     Override via NIA_API_URL env var.
Auth ............... Authorization: Bearer <NIA_API_KEY>
Endpoint used ...... POST /v2/search   (mode discriminator in body)

Request (the only call we make):
  {
    "mode": "query",
    "messages": [{"role": "user", "content": <extracted_value>}],
    "local_folders": [<family_source_id>],     // scopes retrieval to ONE family
    "include_sources": true,
    "stream": false,
    "skip_llm": true                            // we want raw retrieval, no LLM synthesis
  }

Response (with skip_llm=true):
  {
    "content": null,
    "sources": [
      {
        "content": "<chunk text>",
        "metadata": {
          "file_name": "<canonical_key>.txt",   // direct map to canonical key
          "file_path": "<canonical_key>.txt",
          "score": <float>,                     // reranker score, see scale note
          "local_folder_id": "<source_id>",
          "local_folder_name": "rcs_canonical_<family>",
          "chunk_index": <int>,
          "total_chunks": <int>,
          ...
        }
      },
      ...
    ],
    "follow_up_questions": [...],
    "retrieval_log_id": "<str>",
    "_cached": <bool>,
    ...
  }

Score scale note
----------------
Nia's `metadata.score` here is a reranker output, NOT raw cosine similarity.
Empirically, top correct matches land in the 0.55–0.90 range. The JSON's
match_threshold=0.85 was authored assuming a cosine backend; for the Nia
reranker we use NIA_MATCH_THRESHOLD (default 0.50). The ambiguity_window from
the JSON still applies. The JSON is left untouched per directive — this is a
deployment-time recalibration of the active embedding backend.

Vocabulary indexing
-------------------
Nia does not support inline corpus embedding. Vocabulary must be pre-indexed
as one local_folder source per family. Run validators/seed_nia.py once; it
writes validators/nia_sources.json with the per-family source IDs. The
validator reads that file at module load and uses local_folders=[<id>] to
scope retrieval.

When validators/nia_sources.json is missing AND no NIA_VOCAB_SOURCE_<FAMILY>
env var is set for a family, the validator falls back to difflib for that
family. The demo always has a working path — Nia setup is optional.

Rate limits / pagination
------------------------
Not directly observed during build. Each call carries a per-call cost; we cap
the call rate by guarding behind a feature flag and a hard 3-second timeout.
top_k=20 is sufficient for our embedding surface (~424 strings across 5
families, ~85 strings per family).

Operational contract
--------------------
1. Every call has a hard timeout (NIA_TIMEOUT_SECONDS, default 3s).
2. Every call is wrapped in try/except — any HTTP/parse error falls back.
3. Feature flag RCS_SEMANTIC_VALIDATION_ENABLED gates the entire HTTP path.
4. NIA_API_KEY missing → fall back, no HTTP attempt.
5. The fallback (difflib) ALWAYS produces a ValidationResult.

API key handling
----------------
NIA_API_KEY is read from the process env at module load. The key is never
logged, never raised in exception messages, and never echoed in
ValidationResult.fallback_reason.
"""

from __future__ import annotations

import os
import json
import asyncio
import difflib
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

VOCABULARY_PATH = Path(__file__).parent / "canonical_vocabulary.json"
NIA_SOURCES_PATH = Path(__file__).parent / "nia_sources.json"
NIA_API_KEY = os.getenv("NIA_API_KEY")
NIA_API_URL = os.getenv("NIA_API_URL", "https://apigcp.trynia.ai") + "/v2"
NIA_TIMEOUT = float(os.getenv("NIA_TIMEOUT_SECONDS", "5"))
SEMANTIC_VALIDATION_ENABLED = (
    os.getenv("RCS_SEMANTIC_VALIDATION_ENABLED", "true").lower() == "true"
)
FALLBACK_THRESHOLD = 0.7
NIA_MATCH_THRESHOLD = float(os.getenv("NIA_MATCH_THRESHOLD", "0.50"))

Family = Literal[
    "demographic", "psychographic", "behavioral", "brand_constraint", "campaign_benchmark"
]
FAMILY_VALUES = ("demographic", "psychographic", "behavioral", "brand_constraint", "campaign_benchmark")


@dataclass
class ValidationResult:
    status: Literal[
        "valid", "non_canonical", "ambiguous", "fallback_valid", "fallback_non_canonical"
    ]
    canonical_match: Optional[str] = None
    score: float = 0.0
    candidates: list[str] = field(default_factory=list)
    candidate_scores: list[float] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


# ───────────────────── vocabulary loading ─────────────────────

_vocab_cache: Optional[dict] = None


def load_vocabulary() -> dict:
    """Load and cache the canonical vocabulary JSON."""
    global _vocab_cache
    if _vocab_cache is None:
        with VOCABULARY_PATH.open("r", encoding="utf-8") as fh:
            _vocab_cache = json.load(fh)
    return _vocab_cache


def get_canonical_keys(family: Family) -> set[str]:
    """Return the set of canonical key names for a family.

    Used by extractors when building system prompts. Raises ValueError if the
    family is unknown, so callers fail fast at import time during prompt
    construction.
    """
    vocab = load_vocabulary()
    families = vocab.get("families", {})
    if family not in families:
        raise ValueError(f"unknown family: {family!r}")
    return {k["canonical"] for k in families[family]["keys"]}


def _build_embedding_surface(family: Family) -> list[tuple[str, str]]:
    """Return [(text, canonical_key), ...] for the family.

    Each canonical name and each alias contributes one row. This is the surface
    a semantic search would rank against if Nia accepted inline corpora.
    """
    vocab = load_vocabulary()
    keys = vocab["families"][family]["keys"]
    surface: list[tuple[str, str]] = []
    for entry in keys:
        canonical = entry["canonical"]
        surface.append((canonical, canonical))
        surface.append((canonical.replace("_", " "), canonical))
        for alias in entry.get("aliases", []):
            surface.append((alias, canonical))
    return surface


def _resolve_thresholds(
    threshold: Optional[float], backend: Literal["nia", "fallback"] = "nia"
) -> tuple[float, float]:
    """Pick the right threshold for the active backend.

    The JSON's match_threshold=0.85 is documented for a cosine-similarity
    backend. The Nia reranker we actually call returns scores on a different
    scale, so the deployed default for that backend is NIA_MATCH_THRESHOLD.
    Callers can still pass an explicit `threshold` to override.
    """
    vocab = load_vocabulary()
    if threshold is not None:
        match_threshold = threshold
    elif backend == "nia":
        match_threshold = NIA_MATCH_THRESHOLD
    else:
        match_threshold = float(vocab.get("match_threshold", 0.85))
    ambiguity_window = float(vocab.get("ambiguity_window", 0.05))
    return match_threshold, ambiguity_window


# ───────────────────── HTTP client (lazy singleton) ─────────────────────

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=httpx.Timeout(NIA_TIMEOUT))
    return _client


async def aclose() -> None:
    """Close the module-level HTTP client. Optional — used by tests / shutdown."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None


_seeded_sources_cache: Optional[dict] = None


def _seeded_sources() -> dict:
    """Load nia_sources.json (written by validators/seed_nia.py). Cached."""
    global _seeded_sources_cache
    if _seeded_sources_cache is None:
        if NIA_SOURCES_PATH.exists():
            try:
                _seeded_sources_cache = json.loads(NIA_SOURCES_PATH.read_text(encoding="utf-8"))
            except Exception:
                _seeded_sources_cache = {}
        else:
            _seeded_sources_cache = {}
    return _seeded_sources_cache


def _family_source_ids(family: Family) -> list[str]:
    """Per-family source IDs. Prefers nia_sources.json, falls back to
    NIA_VOCAB_SOURCE_<FAMILY> env var (csv)."""
    seeded = _seeded_sources().get(family)
    if seeded:
        return [seeded] if isinstance(seeded, str) else list(seeded)
    raw = os.getenv(f"NIA_VOCAB_SOURCE_{family.upper()}", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _can_use_nia(family: Family) -> Optional[str]:
    """Return a fallback_reason if Nia is not usable for this family, else None."""
    if not SEMANTIC_VALIDATION_ENABLED:
        return "feature_disabled"
    if not NIA_API_KEY:
        return "api_key_missing"
    if not _family_source_ids(family):
        return "no_vocab_source_configured"
    return None


# ───────────────────── Nia HTTP path ─────────────────────


async def _nia_query_search(query: str, local_folder_ids: list[str]) -> list[dict]:
    """Hit POST /v2/search with mode=query, scoped to specific local_folders,
    skip_llm=true so we get raw ranked retrieval without LLM synthesis.

    Returns the `sources` list. Each entry has `metadata.file_name` (mapping
    directly to the canonical key) and `metadata.score` (reranker score)."""
    client = await _get_client()
    body = {
        "mode": "query",
        "messages": [{"role": "user", "content": query}],
        "local_folders": local_folder_ids,
        "include_sources": True,
        "stream": False,
        "skip_llm": True,
    }
    headers = {
        "Authorization": f"Bearer {NIA_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = await client.post(f"{NIA_API_URL}/search", json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("sources", []) or []


def _aggregate_scores_from_sources(sources: list[dict]) -> dict[str, float]:
    """Map Nia source chunks back to canonical keys.

    Each chunk's metadata.file_name is `<canonical_key>.txt` because that's
    how validators/seed_nia.py wrote them. Per-canonical score = max across
    all chunks that resolve to the same canonical key.
    """
    per_canonical: dict[str, float] = {}
    for s in sources:
        if not isinstance(s, dict):
            continue
        meta = s.get("metadata") or {}
        fname = meta.get("file_name") or ""
        if not fname.endswith(".txt"):
            continue
        canonical = fname[:-4]
        score = float(meta.get("score") or 0.0)
        if score > per_canonical.get(canonical, 0.0):
            per_canonical[canonical] = score
    return per_canonical


def _verdict_from_scores(
    per_canonical: dict[str, float], threshold: float, ambiguity_window: float
) -> ValidationResult:
    if not per_canonical:
        return ValidationResult(status="non_canonical", score=0.0)
    ranked = sorted(per_canonical.items(), key=lambda kv: kv[1], reverse=True)
    top_key, top_score = ranked[0]
    if top_score < threshold:
        return ValidationResult(
            status="non_canonical", canonical_match=top_key, score=top_score
        )
    near = [(k, s) for k, s in ranked if (top_score - s) <= ambiguity_window]
    if len(near) > 1:
        return ValidationResult(
            status="ambiguous",
            candidates=[k for k, _ in near],
            candidate_scores=[s for _, s in near],
            score=top_score,
        )
    return ValidationResult(status="valid", canonical_match=top_key, score=top_score)


# ───────────────────── difflib fallback ─────────────────────


def _difflib_fallback(value: str, family: Family, fallback_reason: str) -> ValidationResult:
    surface = _build_embedding_surface(family)
    per_canonical: dict[str, float] = {}
    needle = (value or "").strip().lower()
    if not needle:
        return ValidationResult(
            status="fallback_non_canonical",
            score=0.0,
            fallback_used=True,
            fallback_reason=fallback_reason,
        )
    for text, canonical in surface:
        ratio = difflib.SequenceMatcher(a=needle, b=text.lower(), autojunk=False).ratio()
        if ratio > per_canonical.get(canonical, 0.0):
            per_canonical[canonical] = ratio
    if not per_canonical:
        return ValidationResult(
            status="fallback_non_canonical",
            score=0.0,
            fallback_used=True,
            fallback_reason=fallback_reason,
        )
    top_key, top_score = max(per_canonical.items(), key=lambda kv: kv[1])
    status = "fallback_valid" if top_score >= FALLBACK_THRESHOLD else "fallback_non_canonical"
    return ValidationResult(
        status=status,
        canonical_match=top_key if status == "fallback_valid" else None,
        score=top_score,
        fallback_used=True,
        fallback_reason=fallback_reason,
    )


# ───────────────────── public API ─────────────────────


async def validate_canonical(
    extracted_value: str,
    family: Family,
    threshold: Optional[float] = None,
) -> ValidationResult:
    """Validate `extracted_value` against the family's canonical vocabulary.

    Three layers of safety guard the Nia HTTP call:
      1. Hard timeout via asyncio.wait_for (NIA_TIMEOUT_SECONDS).
      2. try/except Exception around HTTP + parse + scoring.
      3. Feature-flag + API-key checks before any HTTP attempt.
    Any safety trigger routes to the difflib fallback, which always returns a
    ValidationResult.
    """
    if family not in FAMILY_VALUES:
        raise ValueError(f"unknown family: {family!r}")

    skip_reason = _can_use_nia(family)
    if skip_reason:
        match_threshold, _ = _resolve_thresholds(threshold, backend="fallback")
        result = _difflib_fallback(extracted_value, family, skip_reason)
        logger.info(
            "semantic_validator_fallback",
            extra={
                "extracted_value": extracted_value,
                "family": family,
                "fallback_reason": skip_reason,
                "result_status": result.status,
            },
        )
        return result

    match_threshold, ambiguity_window = _resolve_thresholds(threshold, backend="nia")
    fallback_reason: Optional[str] = None
    try:
        sources = await asyncio.wait_for(
            _nia_query_search(extracted_value, _family_source_ids(family)),
            timeout=NIA_TIMEOUT,
        )
        per_canonical = _aggregate_scores_from_sources(sources)
        verdict = _verdict_from_scores(per_canonical, match_threshold, ambiguity_window)
        if verdict.status == "non_canonical" and not per_canonical:
            # Nia returned nothing for this family — fall back so we still get
            # a lexical signal instead of a flat reject.
            fallback_reason = "nia_empty_for_family"
            raise _NiaUnusable()
        return verdict
    except asyncio.TimeoutError:
        fallback_reason = "timeout"
    except _NiaUnusable:
        pass
    except Exception as e:
        fallback_reason = f"nia_error: {type(e).__name__}: {str(e)[:150]}"

    result = _difflib_fallback(extracted_value, family, fallback_reason or "unknown_error")
    logger.info(
        "semantic_validator_fallback",
        extra={
            "extracted_value": extracted_value,
            "family": family,
            "fallback_reason": result.fallback_reason,
            "result_status": result.status,
        },
    )
    return result


class _NiaUnusable(Exception):
    """Internal sentinel: Nia path executed but yielded no useful signal."""
