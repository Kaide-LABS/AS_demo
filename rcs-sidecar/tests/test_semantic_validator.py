"""Stress tests for validators.semantic_validator and the rules_engine that
calls it. Eight tests as specified in the directive.

Tests do not require a live Nia API. Tests 1, 3, and 7 monkeypatch the HTTP
path so we can assert behavior deterministically without paying for real
embedding calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validators import semantic_validator as sv
from validators.semantic_validator import ValidationResult, validate_canonical


# ───────────────────── helpers ─────────────────────


def _reset_module_env(monkeypatch, *, nia_key="test-key", enabled=True, timeout="3"):
    """Re-bind module-level env-derived state so tests are deterministic."""
    monkeypatch.setattr(sv, "NIA_API_KEY", nia_key)
    monkeypatch.setattr(sv, "SEMANTIC_VALIDATION_ENABLED", enabled)
    monkeypatch.setattr(sv, "NIA_TIMEOUT", float(timeout))
    # Also clear any cached vocab so threshold reads reflect current JSON.
    sv._vocab_cache = None


def _fake_sources(canonical: str, score: float = 0.7) -> list[dict]:
    """Build a fake Nia /search mode=query `sources` array that the aggregator
    can map back to `canonical`. Mimics the real response shape:
    metadata.file_name=`<canonical>.txt`, metadata.score=<reranker score>."""
    return [
        {
            "content": f"canonical: {canonical}\n",
            "metadata": {
                "file_name": f"{canonical}.txt",
                "file_path": f"{canonical}.txt",
                "score": score,
                "local_folder_id": "test-source-id",
                "local_folder_name": "rcs_test",
            },
        }
    ]


def _configure_test_sources(monkeypatch, families: list[str]):
    """Point the validator at fake source IDs via env vars (avoids touching
    nia_sources.json which may exist locally)."""
    # Bypass the on-disk seeded sources file if it happens to exist.
    monkeypatch.setattr(sv, "_seeded_sources_cache", {})
    for fam in families:
        monkeypatch.setenv(f"NIA_VOCAB_SOURCE_{fam.upper()}", "test-source-id")


# ───────────────────── tests ─────────────────────


@pytest.mark.asyncio
async def test_1_happy_path_with_nia_enabled(monkeypatch):
    """Full validation walks a representative calibration with Nia enabled.
    Demographic, psychographic, and behavioral keys all accepted; no
    canonical_attribute_vocabulary violations raised."""
    from schemas import (
        RadiantPersonaCalibration, PersonaSegment, BehavioralAttribute,
        Verbatim, SourceCitation, ArtifactType,
    )

    _reset_module_env(monkeypatch, nia_key="test-key", enabled=True)
    _configure_test_sources(monkeypatch, ["demographic", "psychographic", "behavioral"])

    async def fake_search(query: str, source_ids: list[str]):
        # Echo the query as the matching canonical key (the calibration uses
        # already-canonical keys so query==canonical).
        return _fake_sources(query, score=0.85)

    monkeypatch.setattr(sv, "_nia_query_search", fake_search)

    cit = SourceCitation(
        artifact_id="a1", artifact_type=ArtifactType.SEGMENTATION_STUDY,
        locator="p1", excerpt="ex",
    )
    demo_attr = BehavioralAttribute(key="age_range", value="35-54", confidence=0.5, citations=[cit])
    psy_attr = BehavioralAttribute(key="risk_tolerance", value="moderate", confidence=0.5, citations=[cit])
    beh_attr = BehavioralAttribute(key="media_consumption", value="high", confidence=0.5, citations=[cit])
    seg = PersonaSegment(
        segment_id="s1", label="Seg", description="d", weight=1.0,
        demographic_attributes=[demo_attr],
        psychographic_attributes=[psy_attr],
        behavioral_attributes=[beh_attr],
        information_sources=["x"],
        verbatims=[Verbatim(text="A representative quote of sufficient length for validation.",
                            sentiment="neutral", citation=cit) for _ in range(5)],
        overall_confidence=0.5,
    )
    calibration = RadiantPersonaCalibration(
        project_id="p", target_audience_brief="b",
        segments=[seg], global_provenance=[cit],
    )

    from rules_engine import canonical_attribute_vocabulary
    violations = await canonical_attribute_vocabulary(calibration)
    assert violations == [], f"unexpected violations: {[v.description for v in violations]}"


@pytest.mark.asyncio
async def test_2_family_scoping_correctness(monkeypatch):
    """age_range is valid in demographic but non_canonical in behavioral."""
    _reset_module_env(monkeypatch, enabled=False)  # force fallback path

    r_demo = await validate_canonical("age_range", family="demographic")
    assert r_demo.status in ("fallback_valid", "valid")
    assert r_demo.canonical_match == "age_range"

    r_beh = await validate_canonical("age_range", family="behavioral")
    assert r_beh.status in ("fallback_non_canonical", "non_canonical"), r_beh


@pytest.mark.asyncio
async def test_3_lexical_variant_detection(monkeypatch):
    """Nia-enabled mode: 'warm and conversational' resolves to tone_approachable
    via aliases. 'buying frequency' resolves to purchase_frequency. Both are
    matches difflib alone could not reliably make."""
    _reset_module_env(monkeypatch, nia_key="test-key", enabled=True)
    _configure_test_sources(monkeypatch, ["brand_constraint", "behavioral"])

    async def fake_search(query: str, source_ids: list[str]):
        q = query.lower()
        if "warm" in q or "conversational" in q:
            return _fake_sources("tone_approachable", score=0.72)
        if "buying" in q or "purchase" in q:
            return _fake_sources("purchase_frequency", score=0.68)
        return []

    monkeypatch.setattr(sv, "_nia_query_search", fake_search)

    r1 = await validate_canonical("warm and conversational", family="brand_constraint")
    assert r1.status == "valid", r1
    assert r1.canonical_match == "tone_approachable"
    assert r1.score >= sv.NIA_MATCH_THRESHOLD

    r2 = await validate_canonical("buying frequency", family="behavioral")
    assert r2.status == "valid", r2
    assert r2.canonical_match == "purchase_frequency"


@pytest.mark.asyncio
async def test_4_feature_flag_disabled(monkeypatch, caplog):
    _reset_module_env(monkeypatch, nia_key="test-key", enabled=False)

    import logging
    caplog.set_level(logging.INFO, logger=sv.logger.name)

    result = await validate_canonical("media_consumption", family="behavioral")
    assert result.fallback_used is True
    assert result.fallback_reason == "feature_disabled"
    assert any(
        rec.message == "semantic_validator_fallback"
        and getattr(rec, "fallback_reason", None) == "feature_disabled"
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_5_api_key_missing(monkeypatch, caplog):
    _reset_module_env(monkeypatch, nia_key=None, enabled=True)

    import logging
    caplog.set_level(logging.INFO, logger=sv.logger.name)

    result = await validate_canonical("media_consumption", family="behavioral")
    assert result.fallback_used is True
    assert result.fallback_reason == "api_key_missing"


@pytest.mark.asyncio
async def test_6_nia_http_failure(monkeypatch):
    _reset_module_env(monkeypatch, nia_key="test-key", enabled=True)
    _configure_test_sources(monkeypatch, ["behavioral"])

    async def boom(query: str, source_ids: list[str]):
        raise httpx.ConnectError("simulated connection failure")

    monkeypatch.setattr(sv, "_nia_query_search", boom)

    result = await validate_canonical("media_consumption", family="behavioral")
    assert result.fallback_used is True
    assert result.fallback_reason and result.fallback_reason.startswith("nia_error: ConnectError")


@pytest.mark.asyncio
async def test_7_timeout_fires(monkeypatch):
    _reset_module_env(monkeypatch, nia_key="test-key", enabled=True, timeout="0.5")
    _configure_test_sources(monkeypatch, ["behavioral"])

    async def slow(query: str, source_ids: list[str]):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(sv, "_nia_query_search", slow)

    t0 = time.monotonic()
    result = await validate_canonical("media_consumption", family="behavioral")
    elapsed = time.monotonic() - t0
    assert result.fallback_used is True
    assert result.fallback_reason == "timeout"
    assert elapsed < 1.5, f"timeout fallback took too long: {elapsed:.2f}s"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("NIA_LIVE_TEST") != "1" or not os.getenv("NIA_API_KEY"),
    reason="set NIA_LIVE_TEST=1 and NIA_API_KEY to run",
)
async def test_live_nia_resolves_known_lexical_variants():
    """Hits the real Nia API end-to-end. Requires validators/nia_sources.json
    populated by validators/seed_nia.py. Skipped in CI by default."""
    sources_path = sv.NIA_SOURCES_PATH
    assert sources_path.exists(), f"run validators/seed_nia.py first to create {sources_path}"
    sv._seeded_sources_cache = None  # force reload of nia_sources.json
    sv.NIA_API_KEY = os.environ["NIA_API_KEY"]
    sv.SEMANTIC_VALIDATION_ENABLED = True
    cases = [
        ("buying frequency", "behavioral", "purchase_frequency"),
        ("eco-consciousness", "psychographic", "environmental_concern"),
        ("NPS", "campaign_benchmark", "net_promoter_score"),
    ]
    for value, family, expected in cases:
        r = await validate_canonical(value, family)
        assert r.canonical_match == expected, f"{value!r} ({family}) -> {r}"
        assert r.status in ("valid", "fallback_valid"), r
    await sv.aclose()


@pytest.mark.asyncio
async def test_8_determinism(monkeypatch):
    """Same input across 5 runs → identical verdict and canonical match.
    Threshold + ambiguity logic must absorb minor score variance from Nia."""
    _reset_module_env(monkeypatch, nia_key="test-key", enabled=True)
    _configure_test_sources(monkeypatch, ["behavioral"])

    # Vary the score slightly per call to simulate Nia's stochasticity.
    counter = {"n": 0}

    async def jittered(query: str, source_ids: list[str]):
        counter["n"] += 1
        score = 0.70 + (counter["n"] % 3) * 0.005  # 0.700, 0.705, 0.710 cycle
        return _fake_sources("media_consumption", score=score)

    monkeypatch.setattr(sv, "_nia_query_search", jittered)

    verdicts = []
    for _ in range(5):
        r = await validate_canonical("media diet", family="behavioral")
        verdicts.append((r.status, r.canonical_match))
    assert len(set(verdicts)) == 1, f"non-deterministic verdicts: {verdicts}"
    assert verdicts[0] == ("valid", "media_consumption")
