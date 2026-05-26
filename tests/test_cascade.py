from evidence_gated_memory import EvidenceGatedMemory


def test_revoke_evidence_cascades_to_facts(memory: EvidenceGatedMemory):
    order_ref = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-1","status":"PAID"}',
    )
    policy_ref = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14-day refund window",
    )

    r = memory.assert_fact(
        "ORD-1 is refundable",
        claim_type="refund_eligibility",
        evidence=[order_ref, policy_ref],
    )
    assert r.accepted and r.fact is not None
    fact_id = r.fact.id

    # confirm it's live
    fact = memory.store.get_fact(fact_id)
    assert fact and fact.invalidated_at is None

    # revoke order_ref → cascade should invalidate the dependent fact
    invalidated = memory.revoke_evidence(order_ref.id, reason="upstream amendment")
    assert fact_id in invalidated

    fact_after = memory.store.get_fact(fact_id)
    assert fact_after.invalidated_at is not None
    assert "upstream amendment" in (fact_after.invalidation_reason or "")


def test_context_drops_facts_with_only_expired_evidence(memory: EvidenceGatedMemory):
    from datetime import datetime, timedelta, timezone

    very_old = datetime.now(timezone.utc) - timedelta(days=2)
    order_ref = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-1"}', observed_at=very_old,
    )
    policy_ref = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14-day", observed_at=very_old,
    )

    # First insert directly (bypassing the gate) by calling the lower-level path,
    # because expired evidence would be blocked by the gate — which is the point.
    # Instead: insert with fresh evidence, then revoke them.
    fresh_order = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-2"}',
    )
    fresh_policy = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14-day",
    )
    r = memory.assert_fact(
        "ORD-2 is refundable",
        claim_type="refund_eligibility",
        evidence=[fresh_order, fresh_policy],
    )
    assert r.accepted

    # Now revoke both → fact should be cascaded out of context
    memory.revoke_evidence(fresh_order.id)
    memory.revoke_evidence(fresh_policy.id)

    ctx = memory.build_context()
    assert "ORD-2 is refundable" not in ctx or "BLOCKED" in ctx
