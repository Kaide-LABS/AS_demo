"""
Semantic validator for canonical attribute vocabulary.

Nia HTTP API discovery (build-time, 2026-04-25)
================================================
Base URL ........... https://apigcp.trynia.ai/v2
                     Override via NIA_API_URL env var.
Auth ............... Authorization: Bearer <NIA_API_KEY>
Endpoint used ...... POST /v2/search

Two relevant request modes:

1. mode = "universal"
   Body: {
     "mode": "universal",
     "query": <str>,
     "top_k": <int>,
     "include_repos": <bool>,
     "include_docs": <bool>
   }
   Hybrid vector + BM25 across all globally indexed sources. Response shape:
     {
       "results": [
         {
           "content": <str>,
           "score": <float, 0..1, post-rerank>,
           "source": {
             "type": "documentation" | "repository" | ...,
             "namespace": <str>,
             "display_name": <str>,
             "document_name": <str>,
             "initial_score": <float>,
             "reranker_score": <float>,
             ...
           },
           "summary": <str>
         }, ...
       ],
       "sources_searched": <int>,
       "query_time_ms": <int>,
       "errors": [...],
       "retrieval_log_id": <str>
     }
   The top-level `score` is on a 0..1 scale. We use this as the cosine-similarity
   proxy for threshold/ambiguity comparisons.

2. mode = "query"
   Body includes data_sources=[<source_id>, ...]. The endpoint synthesizes an
   LLM answer plus a `sources` array of file paths/URLs. With skip_llm=true the
   response collapses to {content: null, sources: []} — no per-source scores.
   We do NOT use this mode for scoring; only universal exposes scores.

Inline corpus support
---------------------
Nia does NOT support inline corpus embedding (you cannot pass the vocabulary
to-be-matched in the request body). Vocabulary must be PRE-INDEXED as one
source per family. Two routes exist for that:

  a) Index each family's text corpus as a private global source (via
     POST /v2/sources or via the equivalent of `repos.sh index` /
     `sources.sh index`) and pass the resulting source IDs to the validator
     via env vars NIA_VOCAB_SOURCE_<FAMILY>.
  b) Index each family as a "local folder" with a unique namespace per family
     (e.g., rcs_canonical_demographic_v1) and pass NIA_VOCAB_NAMESPACE_<FAMILY>
     so the validator can filter universal results by namespace.

Either path is OUT OF SCOPE for this validator. When a family has no source ID
or namespace configured, the validator falls back to difflib.SequenceMatcher.
This is by design — the demo must work with no Nia setup at all.

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
NIA_API_KEY = os.getenv("NIA_API_KEY")
NIA_API_URL = os.getenv("NIA_API_URL", "https://apigcp.trynia.ai") + "/v2"
NIA_TIMEOUT = float(os.getenv("NIA_TIMEOUT_SECONDS", "3"))
SEMANTIC_VALIDATION_ENABLED = (
    os.getenv("RCS_SEMANTIC_VALIDATION_ENABLED", "true").lower() == "true"
)
FALLBACK_THRESHOLD = 0.7
TOP_K = 20

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


def _resolve_thresholds(threshold: Optional[float]) -> tuple[float, float]:
    vocab = load_vocabulary()
    match_threshold = threshold if threshold is not None else float(
        vocab.get("match_threshold", 0.85)
    )
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


def _family_source_ids(family: Family) -> list[str]:
    """Per-family source IDs (env var: NIA_VOCAB_SOURCE_<FAMILY>, csv)."""
    raw = os.getenv(f"NIA_VOCAB_SOURCE_{family.upper()}", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _family_namespace(family: Family) -> Optional[str]:
    """Per-family namespace filter (env var: NIA_VOCAB_NAMESPACE_<FAMILY>)."""
    val = os.getenv(f"NIA_VOCAB_NAMESPACE_{family.upper()}", "").strip()
    return val or None


def _can_use_nia(family: Family) -> Optional[str]:
    """Return a fallback_reason if Nia is not usable for this family, else None."""
    if not SEMANTIC_VALIDATION_ENABLED:
        return "feature_disabled"
    if not NIA_API_KEY:
        return "api_key_missing"
    if not _family_source_ids(family) and not _family_namespace(family):
        return "no_vocab_source_configured"
    return None


# ───────────────────── Nia HTTP path ─────────────────────


async def _nia_universal_search(query: str) -> list[dict]:
    """Hit /v2/search mode=universal. Returns list of result dicts (may be empty)."""
    client = await _get_client()
    body = {
        "mode": "universal",
        "query": query,
        "top_k": TOP_K,
        "include_repos": True,
        "include_docs": True,
        "compress_output": False,
    }
    headers = {
        "Authorization": f"Bearer {NIA_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = await client.post(f"{NIA_API_URL}/search", json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", []) or []


def _filter_results_for_family(results: list[dict], family: Family) -> list[dict]:
    """Keep only results that belong to this family's vocabulary corpus."""
    source_ids = set(_family_source_ids(family))
    namespace = _family_namespace(family)
    out: list[dict] = []
    for r in results:
        src = r.get("source") or {}
        if source_ids:
            sid = src.get("id") or src.get("source_id") or src.get("namespace")
            if sid in source_ids:
                out.append(r)
                continue
        if namespace and src.get("namespace") == namespace:
            out.append(r)
    return out


def _aggregate_scores(results: list[dict], family: Family) -> dict[str, float]:
    """Map Nia results back to canonical keys via the embedding surface.

    Strategy: each Nia result has `content` and/or `source.document_name`. We
    scan that text for a substring match against the family's surface entries
    and credit the parent canonical key with the result's `score`. Per-canonical
    score = max across all matching results.
    """
    surface = _build_embedding_surface(family)
    per_canonical: dict[str, float] = {}
    for r in results:
        score = float(r.get("score", 0.0) or 0.0)
        text_blob = " ".join(
            str(x).lower() for x in (
                r.get("content"),
                (r.get("source") or {}).get("document_name"),
                (r.get("source") or {}).get("display_name"),
                r.get("summary"),
            ) if x
        )
        if not text_blob:
            continue
        for text, canonical in surface:
            if text.lower() in text_blob:
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

    match_threshold, ambiguity_window = _resolve_thresholds(threshold)

    skip_reason = _can_use_nia(family)
    if skip_reason:
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

    fallback_reason: Optional[str] = None
    try:
        results = await asyncio.wait_for(
            _nia_universal_search(extracted_value), timeout=NIA_TIMEOUT
        )
        scoped = _filter_results_for_family(results, family)
        per_canonical = _aggregate_scores(scoped, family)
        verdict = _verdict_from_scores(per_canonical, match_threshold, ambiguity_window)
        if verdict.status == "non_canonical" and not per_canonical:
            # Nia returned nothing useful for this family — fall back so we get
            # at least a lexical signal instead of a flat reject.
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
