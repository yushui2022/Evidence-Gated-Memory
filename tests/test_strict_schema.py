"""Verification #2: unknown claim_type / evidence_type must fail-closed."""

from evidence_gated_memory import EvidenceGatedMemory


def test_unknown_claim_type_is_rejected(memory: EvidenceGatedMemory):
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id": "ORD-1"}',
    )
    r = memory.assert_fact(
        "made-up claim",
        claim_type="totally_made_up_claim_type",
        evidence=[ev],
    )
    assert r.accepted is False
    assert any(v.gate == "unknown_claim_type" for v in r.gate.violations), r.gate.violations


def test_unknown_evidence_type_is_rejected(memory: EvidenceGatedMemory):
    ev = memory.record_evidence(
        evidence_type="some_made_up_evidence_type",
        source="x",
        source_system="x",
        content="nothing",
    )
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[ev],
    )
    assert r.accepted is False
    assert any(v.gate == "unknown_evidence_type" for v in r.gate.violations), r.gate.violations
