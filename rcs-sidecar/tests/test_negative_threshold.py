"""
Negative test: queries that should NOT match any canonical key in any family.
Validates that NIA_MATCH_THRESHOLD is not so low that random text scores valid.
Run with: NIA_LIVE_TEST=1 NIA_API_KEY=<key> pytest tests/test_negative_threshold.py -v -s
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validators import semantic_validator as sv
from validators.semantic_validator import validate_canonical


NEGATIVE_QUERIES = [
    ("the Eiffel Tower is in Paris", "behavioral"),
    ("quarterly earnings report Q3", "demographic"),
    ("the cat sat on the mat", "psychographic"),
    ("blockchain consensus algorithm", "brand_constraint"),
    ("apple banana cherry fruit salad", "campaign_benchmark"),
    ("xyzzy plugh foobar baz", "behavioral"),
]


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("NIA_LIVE_TEST") != "1" or not os.getenv("NIA_API_KEY"),
    reason="set NIA_LIVE_TEST=1 and NIA_API_KEY to run",
)
async def test_negative_queries_do_not_match():
    """Random off-topic queries must NOT validate as canonical for any family."""
    sv._seeded_sources_cache = None
    sv.NIA_API_KEY = os.environ["NIA_API_KEY"]
    sv.SEMANTIC_VALIDATION_ENABLED = True

    false_positives = []
    for query, family in NEGATIVE_QUERIES:
        r = await validate_canonical(query, family)
        print(
            f"  [{family}] {query!r:50s} -> status={r.status:25s} "
            f"match={r.canonical_match} score={r.score:.3f}"
        )
        if r.status == "valid":
            false_positives.append((query, family, r.canonical_match, r.score))

    await sv.aclose()

    assert not false_positives, (
        f"NIA_MATCH_THRESHOLD={sv.NIA_MATCH_THRESHOLD} is too low. "
        f"False positives: {false_positives}. Bump to 0.55 or 0.60."
    )
