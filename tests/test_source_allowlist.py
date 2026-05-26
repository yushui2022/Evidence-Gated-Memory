"""Verification #3: schema source_systems allowlist must be enforced."""

from evidence_gated_memory import EvidenceGatedMemory


def test_unlisted_source_system_is_rejected(memory: EvidenceGatedMemory):
    # refund.yaml: order_record.source_systems = ["order_api"]
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="random_thing",
        source_system="unknown_system",
        content='{"order_id":"ORD-1"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="14d",
    )
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[ev, policy],
    )
    assert r.accepted is False
    assert any(v.gate == "source_system_not_allowed" for v in r.gate.violations), r.gate.violations


def test_listed_source_system_is_accepted(memory: EvidenceGatedMemory):
    order = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-1"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="14d",
    )
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[order, policy],
    )
    assert r.accepted is True
