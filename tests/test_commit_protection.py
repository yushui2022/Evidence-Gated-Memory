"""Verification #7: commit_fact must require an accepted GateResult."""

import pytest

from evidence_gated_memory import EvidenceGatedMemory


def test_commit_without_gate_result_raises(memory: EvidenceGatedMemory):
    claim = memory.propose_claim(
        text="Order is refundable",
        claim_type="refund_eligibility",
        evidence=[],
    )
    with pytest.raises(Exception):
        memory.commit_fact(claim)   # no gate result -> must refuse


def test_commit_with_rejected_gate_result_raises(memory: EvidenceGatedMemory):
    claim = memory.propose_claim(
        text="Order is refundable",
        claim_type="refund_eligibility",
        evidence=[],
    )
    gate = memory.check_gate(claim)
    assert gate.accepted is False
    with pytest.raises(Exception):
        memory.commit_fact(claim, gate_result=gate)


def test_commit_with_accepted_gate_result_succeeds(memory: EvidenceGatedMemory):
    order = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-1"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14d",
    )
    claim = memory.propose_claim(
        text="Order is refundable",
        claim_type="refund_eligibility",
        evidence=[order, policy],
    )
    gate = memory.check_gate(claim)
    assert gate.accepted is True
    fact = memory.commit_fact(claim, gate_result=gate)
    assert fact.id
