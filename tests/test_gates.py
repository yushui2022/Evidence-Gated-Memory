from evidence_gated_memory import EvidenceGatedMemory


def _order_ref(memory: EvidenceGatedMemory):
    return memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-1","status":"PAID"}',
    )


def _policy_ref(memory: EvidenceGatedMemory):
    return memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="14-day refund window",
    )


def test_claim_without_evidence_is_rejected(memory):
    r = memory.assert_fact("Order is refundable", claim_type="refund_eligibility")
    assert r.accepted is False
    assert any(v.gate == "claim_requires_source" for v in r.gate.violations)
    # rejection must be actionable, not just a boolean
    assert r.suggested_action != ""


def test_missing_required_evidence_type_is_named(memory):
    only_order = _order_ref(memory)
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[only_order],
    )
    assert r.accepted is False
    missing_types: set[str] = set()
    for v in r.gate.violations:
        missing_types.update(v.missing_evidence_types)
    assert "refund_policy" in missing_types


def test_claim_with_full_evidence_is_accepted(memory):
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[_order_ref(memory), _policy_ref(memory)],
    )
    assert r.accepted is True
    assert r.fact is not None
    assert r.fact.evidence_refs


def test_llm_sourced_evidence_is_blocked(memory):
    llm_ref = memory.record_evidence(
        evidence_type="refund_policy",
        source="llm",
        source_system="llm",
        content="model thinks the policy says 14 days",
    )
    r = memory.assert_fact(
        "Order is refundable",
        claim_type="refund_eligibility",
        evidence=[_order_ref(memory), llm_ref],
    )
    assert r.accepted is False
    assert any(v.gate == "llm_output_not_as_source" for v in r.gate.violations)


def test_completion_requires_refund_api_evidence(memory):
    # eligibility evidence is NOT enough to claim completion
    r = memory.assert_fact(
        "Refund completed",
        claim_type="refund_completed",
        evidence=[_order_ref(memory), _policy_ref(memory)],
    )
    assert r.accepted is False
    missing: set[str] = set()
    for v in r.gate.violations:
        missing.update(v.missing_evidence_types)
    assert "refund_api_response" in missing
