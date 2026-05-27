"""Verification #2: unknown claim_type / evidence_type must fail closed at the API edge."""

import pytest

from evidence_gated_memory import EvidenceGatedMemory


def test_unknown_claim_type_is_rejected_before_claim_is_stored(memory: EvidenceGatedMemory):
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id": "ORD-1"}',
    )
    with pytest.raises(ValueError, match="unknown claim_type"):
        memory.assert_fact(
            "made-up claim",
            claim_type="totally_made_up_claim_type",
            evidence=[ev],
        )


def test_unknown_evidence_type_is_rejected_before_ref_is_written(memory: EvidenceGatedMemory):
    with pytest.raises(ValueError, match="unknown evidence_type"):
        memory.record_evidence(
            evidence_type="some_made_up_evidence_type",
            source="x",
            source_system="x",
            content="nothing",
        )

    assert list((memory.workspace / "refs").glob("*.md")) == []
