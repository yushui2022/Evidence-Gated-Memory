"""Verification #5: derived facts inherit support from live parent facts, and cascade on parent invalidation."""

from evidence_gated_memory import EvidenceGatedMemory, FactKind


def _make_parent_facts(memory: EvidenceGatedMemory):
    order = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-1","status":"PAID"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14d",
    )
    refund = memory.record_evidence(
        evidence_type="refund_api_response", source="refund_api", source_system="refund_api",
        content='{"refund_id":"REF-1","status":"success"}',
    )
    eligibility = memory.assert_fact(
        "ORD-1 eligible",
        claim_type="refund_eligibility",
        evidence=[order, policy],
    )
    completion = memory.assert_fact(
        "ORD-1 refund executed",
        claim_type="refund_completed",
        evidence=[refund],
    )
    assert eligibility.accepted and completion.accepted
    return eligibility.fact, completion.fact, order, refund


def test_derived_inherits_evidence_from_parents(memory: EvidenceGatedMemory):
    elig, completion, _, _ = _make_parent_facts(memory)
    derived = memory.assert_fact(
        "Customer fully refunded for ORD-1",
        claim_type="refund_completed",          # same claim_type used at higher level
        kind=FactKind.DERIVED,
        depends_on=[elig, completion],
    )
    assert derived.accepted is True, derived.gate.violations
    assert derived.fact is not None
    assert derived.fact.kind == FactKind.DERIVED


def test_derived_cascades_when_parent_invalidated(memory: EvidenceGatedMemory):
    elig, completion, order_ref, _ = _make_parent_facts(memory)
    derived = memory.assert_fact(
        "Customer fully refunded for ORD-1",
        claim_type="refund_completed",
        kind=FactKind.DERIVED,
        depends_on=[elig, completion],
    )
    assert derived.accepted

    # revoke the order evidence -> eligibility fact invalidated -> derived must cascade
    invalidated = memory.revoke_evidence(order_ref.id, reason="upstream change")
    assert elig.id in invalidated
    assert derived.fact.id in invalidated

    after = memory.store.get_fact(derived.fact.id)
    assert after.invalidated_at is not None


def test_derived_with_dead_parent_is_rejected(memory: EvidenceGatedMemory):
    elig, completion, order_ref, _ = _make_parent_facts(memory)
    memory.revoke_evidence(order_ref.id)   # kills eligibility

    derived = memory.assert_fact(
        "Customer fully refunded for ORD-1",
        claim_type="refund_completed",
        kind=FactKind.DERIVED,
        depends_on=[elig, completion],
    )
    assert derived.accepted is False
    assert any(v.gate == "derived_requires_live_parents" for v in derived.gate.violations)
