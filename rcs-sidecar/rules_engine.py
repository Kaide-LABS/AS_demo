import re
import math
from typing import List, Tuple
from schemas import RadiantPersonaCalibration, RuleViolation

CANONICAL_KEYS = {
    "media_consumption", "information_sources", "content_consumption_format",
    "social_media_usage", "digital_savviness",
    "purchase_frequency", "price_sensitivity", "brand_affinity",
    "channel_preference", "risk_tolerance", "trust_in_institutions",
    "environmental_concern", "health_consciousness", "political_engagement",
    "work_life_priority", "community_involvement", "education_aspiration",
    "decision_making_style", "technology_adoption", "financial_literacy",
}

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

def canonical_attribute_vocabulary(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    for s_idx, seg in enumerate(calibration.segments):
        attrs = seg.demographic_attributes + seg.psychographic_attributes + seg.behavioral_attributes
        for a_idx, attr in enumerate(attrs):
            if attr.key not in CANONICAL_KEYS:
                violations.append(RuleViolation(
                    rule_name="canonical_attribute_vocabulary",
                    field_path=f"segments[{s_idx}].attributes[{a_idx}].key",
                    segment_id=seg.segment_id,
                    description=f"Key '{attr.key}' not in CANONICAL_KEYS."
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

def brand_constraints_have_examples(calibration: RadiantPersonaCalibration) -> List[RuleViolation]:
    violations = []
    for idx, bc in enumerate(calibration.brand_constraints):
        if not bc.examples:
            violations.append(RuleViolation(
                rule_name="brand_constraints_have_examples",
                field_path=f"brand_constraints[{idx}]",
                description="Brand constraint has 0 examples."
            ))
    return violations

RULES = [
    weights_sum_to_one,
    every_attribute_has_citation,
    verbatims_per_segment_minimum,
    canonical_attribute_vocabulary,
    confidence_monotonic_with_sources,
    no_pii_in_verbatims,
    provenance_completeness,
    brand_constraints_have_examples,
]

def validate(calibration: RadiantPersonaCalibration) -> Tuple[RadiantPersonaCalibration, List[RuleViolation]]:
    violations = []
    for rule in RULES:
        violations.extend(rule(calibration))
    return calibration, violations
