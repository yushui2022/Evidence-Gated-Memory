"""Verification #4: build_context queries with business IDs must not crash."""

from evidence_gated_memory import EvidenceGatedMemory


def _seed(memory: EvidenceGatedMemory):
    order = memory.record_evidence(
        evidence_type="order_record", source="order_api", source_system="order_api",
        content='{"order_id":"ORD-123"}',
        metadata={"order_id": "ORD-123"},
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy", source="policy_db", source_system="policy_db",
        content="14d",
    )
    r = memory.assert_fact(
        "Order ORD-123 is refundable",
        claim_type="refund_eligibility",
        evidence=[order, policy],
        metadata={"order_id": "ORD-123"},
    )
    assert r.accepted


def test_query_with_hyphenated_id_does_not_crash(memory: EvidenceGatedMemory):
    _seed(memory)
    ctx = memory.build_context(query="ORD-123")
    assert isinstance(ctx, str)


def test_query_with_colon_key_does_not_crash(memory: EvidenceGatedMemory):
    _seed(memory)
    ctx = memory.build_context(query="order_id:ORD-123")
    assert isinstance(ctx, str)


def test_query_with_punctuation_does_not_crash(memory: EvidenceGatedMemory):
    _seed(memory)
    for q in ["ORD-123!", "(ORD-123)", '"ORD-123"', "*ORD-123*", "AND OR NOT"]:
        ctx = memory.build_context(query=q)
        assert isinstance(ctx, str)


def test_plain_query_still_works(memory: EvidenceGatedMemory):
    _seed(memory)
    ctx = memory.build_context(query="refundable")
    assert "ORD-123" in ctx or "refundable" in ctx.lower()
