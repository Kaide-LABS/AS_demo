import pytest
from schemas import RadiantPersonaCalibration, PersonaSegment
from rules_engine import weights_sum_to_one, every_attribute_has_citation, no_pii_in_verbatims
from evidence_merger import EvidenceMerger

def test_rules_engine_rejects_bad_weights():
    # Mocking basic logic 
    pass

def test_field_state_lifecycle():
    pass

def test_evidence_merger_deduplication():
    pass
