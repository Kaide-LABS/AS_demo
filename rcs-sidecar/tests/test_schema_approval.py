import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import SectionStatus


def test_section_approve_sets_status():
    section = SectionStatus(
        section_id="seg1", section_name="Segments",
        status="approved", field_count=5, approved_count=5,
    )
    assert section.status == "approved"
    assert section.approved_count == section.field_count


def test_section_reject_includes_reason():
    section = SectionStatus(
        section_id="seg1", section_name="Segments",
        status="rejected", field_count=5, approved_count=0,
        rejection_reason="Segment weights seem incorrect",
    )
    assert section.status == "rejected"
    assert section.rejection_reason is not None
    assert "weight" in section.rejection_reason.lower()


def test_pending_section_has_zero_approvals():
    section = SectionStatus(
        section_id="dem1", section_name="Demographics",
        status="pending", field_count=3, approved_count=0,
    )
    assert section.status == "pending"
    assert section.approved_count == 0


def test_section_status_validates_literal():
    with pytest.raises(Exception):
        SectionStatus(
            section_id="x", section_name="X",
            status="invalid_status", field_count=1, approved_count=0,
        )
