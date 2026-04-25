import re
import math
import inspect
from typing import Awaitable, Callable, List, Tuple, Union
from schemas import RadiantPersonaCalibration, RuleViolation
from validators.semantic_validator import validate_canonical


def weights_sum_to_one(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    total = sum(seg.weight for seg in calibration.segments)
    if not (0.99 <= total <= 1.01):
        violations.append(RuleViolation(
            rule_name="weights_sum_to_one",
            field_path="segments",
            description=f"weights sum to {total}, must equal 1.0 ± 0.01"
        ))
    return violations

def every_attribute_has_citation(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    for s_idx, seg in enumerate(calibration.segments):
        attrs = seg.demographic_attributes + seg.psychographic_attributes + seg.behavioral_attributes
        for a_idx, attr in enumerate(attrs):
            if not attr.citations:
                violations.append(RuleViolation(
                    rule_name="every_attribute_has_citation",
                    field_path=f"segments[{s_idx}].attributes[{a_idx}]",
                    segment_id=seg.segment_id,
                    description=f"Attribute '{attr.key}' has 0 citations."
                ))
    return violations

def verbatims_per_segment_minimum(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    for s_idx, seg in enumerate(calibration.segments):
        if len(seg.verbatims) < 5:
            violations.append(RuleViolation(
                rule_name="verbatims_per_segment_minimum",
                field_path=f"segments[{s_idx}].verbatims",
                segment_id=seg.segment_id,
                description=f"Segment has {len(seg.verbatims)} verbatims (min 5)."
            ))
    return violations


_FAMILY_FOR_BUCKET = {
    "demographic_attributes": "demographic",
    "psychographic_attributes": "psychographic",
    "behavioral_attributes": "behavioral",
}


def _add_coverage_gap(calibration: RadiantPersonaCalibration, msg: str) -> None:
    """Append a soft warning to coverage_gaps without violating the contract."""
    if calibration.coverage_gaps is None:
        calibration.coverage_gaps = []
    if msg not in calibration.coverage_gaps:
        calibration.coverage_gaps.append(msg)


async def canonical_attribute_vocabulary(
    calibration: RadiantPersonaCalibration,
) -> List[RuleViolation]:
    """Family-scoped semantic validation of attribute keys.

    Walks each segment's three attribute buckets, validating each .key against
    the canonical vocabulary for its family. Replaces the old hardcoded
    CANONICAL_KEYS check, which mistakenly flagged demographic keys with a
    behavioral-only set.
    """
    violations: List[RuleViolation] = []
    for s_idx, seg in enumerate(calibration.segments):
        for bucket_name, family in _FAMILY_FOR_BUCKET.items():
            bucket = getattr(seg, bucket_name, []) or []
            for a_idx, attr in enumerate(bucket):
                result = await validate_canonical(attr.key, family)
                field_path = f"segments[{s_idx}].{bucket_name}[{a_idx}].key"
                if result.status == "valid":
                    continue
                if result.status == "non_canonical":
                    violations.append(RuleViolation(
                        rule_name="canonical_attribute_vocabulary",
                        field_path=field_path,
                        segment_id=seg.segment_id,
                        description=(
                            f"Key '{attr.key}' is not a canonical {family} key "
                            f"(top match: {result.canonical_match!r}, score={result.score:.2f})."
                        ),
                    ))
                elif result.status == "ambiguous":
                    candidates = ", ".join(
                        f"{c}({s:.2f})" for c, s in zip(result.candidates, result.candidate_scores)
                    )
                    violations.append(RuleViolation(
                        rule_name="canonical_attribute_vocabulary",
                        field_path=field_path,
                        segment_id=seg.segment_id,
                        description=(
                            f"Key '{attr.key}' is ambiguous between {family} canonicals: "
                            f"{candidates}. Pick one canonical form."
                        ),
                    ))
                elif result.status == "fallback_valid":
                    _add_coverage_gap(
                        calibration,
                        (
                            f"Semantic validator fell back to lexical match for "
                            f"'{attr.key}' in {family} (matched {result.canonical_match!r}, "
                            f"reason={result.fallback_reason})."
                        ),
                    )
                elif result.status == "fallback_non_canonical":
                    violations.append(RuleViolation(
                        rule_name="canonical_attribute_vocabulary",
                        field_path=field_path,
                        segment_id=seg.segment_id,
                        description=(
                            f"Key '{attr.key}' is not a canonical {family} key "
                            f"(lexical fallback, reason={result.fallback_reason})."
                        ),
                    ))
    return violations


def confidence_monotonic_with_sources(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    for s_idx, seg in enumerate(calibration.segments):
        attrs = seg.demographic_attributes + seg.psychographic_attributes + seg.behavioral_attributes
        for a_idx, attr in enumerate(attrs):
            max_conf = min(1.0, math.sqrt(len(attr.citations) / 10.0) + 0.1)
            if attr.confidence > max_conf:
                violations.append(RuleViolation(
                    rule_name="confidence_monotonic_with_sources",
                    field_path=f"segments[{s_idx}].attributes[{a_idx}].confidence",
                    segment_id=seg.segment_id,
                    description=f"Confidence {attr.confidence} exceeds bound {max_conf:.2f} for {len(attr.citations)} sources."
                ))
    return violations

def no_pii_in_verbatims(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    email_re = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    phone_re = re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b')
    ssn_re = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

    for s_idx, seg in enumerate(calibration.segments):
        for v_idx, verb in enumerate(seg.verbatims):
            text = verb.text
            if email_re.search(text) or phone_re.search(text) or ssn_re.search(text):
                violations.append(RuleViolation(
                    rule_name="no_pii_in_verbatims",
                    field_path=f"segments[{s_idx}].verbatims[{v_idx}]",
                    segment_id=seg.segment_id,
                    description=f"PII detected in verbatim: '{text[:50]}...'"
                ))
    return violations

def provenance_completeness(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    global_ids = {c.artifact_id for c in calibration.global_provenance}
    for s_idx, seg in enumerate(calibration.segments):
        seg_ids = set()
        attrs = seg.demographic_attributes + seg.psychographic_attributes + seg.behavioral_attributes
        for a in attrs:
            for c in a.citations:
                seg_ids.add(c.artifact_id)
        if not seg_ids.intersection(global_ids):
            violations.append(RuleViolation(
                rule_name="provenance_completeness",
                field_path=f"segments[{s_idx}]",
                segment_id=seg.segment_id,
                description="Segment citations do not map to any global provenance artifacts."
            ))
    return violations


async def brand_constraints_have_examples(
    calibration: RadiantPersonaCalibration,
) -> List[RuleViolation]:
    """Structural check + soft semantic check on each constraint's description.

    Hard violation: a constraint with zero examples (existing behavior).
    Soft warning: a constraint description that does not match any canonical
    brand_constraint vocabulary entry. Soft warnings land in coverage_gaps
    rather than violations because brand-language drift is expected.
    """
    violations: List[RuleViolation] = []
    for idx, bc in enumerate(calibration.brand_constraints):
        if not bc.examples:
            violations.append(RuleViolation(
                rule_name="brand_constraints_have_examples",
                field_path=f"brand_constraints[{idx}]",
                description="Brand constraint has 0 examples.",
            ))
            continue
        # Soft semantic augmentation
        try:
            result = await validate_canonical(bc.description, family="brand_constraint")
        except Exception:
            continue
        if result.status in ("non_canonical", "fallback_non_canonical"):
            _add_coverage_gap(
                calibration,
                (
                    f"brand_constraints[{idx}].description does not match any "
                    f"canonical brand_constraint key (top={result.canonical_match!r}, "
                    f"score={result.score:.2f}). Consider rewording."
                ),
            )
    return violations


SyncRule = Callable[[RadiantPersonaCalibration], List[RuleViolation]]
AsyncRule = Callable[[RadiantPersonaCalibration], Awaitable[List[RuleViolation]]]
Rule = Union[SyncRule, AsyncRule]

RULES: list[Rule] = [
    weights_sum_to_one,
    every_attribute_has_citation,
    verbatims_per_segment_minimum,
    canonical_attribute_vocabulary,           # async
    confidence_monotonic_with_sources,
    no_pii_in_verbatims,
    provenance_completeness,
    brand_constraints_have_examples,          # async (augmented)
]


async def validate(
    calibration: RadiantPersonaCalibration,
) -> Tuple[RadiantPersonaCalibration, List[RuleViolation]]:
    """Run all rules. Async because some rules call out to Nia."""
    violations: List[RuleViolation] = []
    for rule in RULES:
        if inspect.iscoroutinefunction(rule):
            violations.extend(await rule(calibration))
        else:
            violations.extend(rule(calibration))
    return calibration, violations
