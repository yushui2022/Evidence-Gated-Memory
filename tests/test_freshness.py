from datetime import datetime, timedelta, timezone

from evidence_gated_memory import EvidenceGatedMemory, Freshness
from evidence_gated_memory.core.freshness import freshness_of
from evidence_gated_memory.schemas.builtin import REFUND
from evidence_gated_memory.schemas.loader import load_schema


def test_freshness_tri_state():
    schema = load_schema(REFUND)
    now = datetime.now(timezone.utc)

    # refund_api_response: stale_after=PT2M, expired_after=PT15M
    from evidence_gated_memory.core.models import Evidence

    fresh = Evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        observed_at=now - timedelta(seconds=30),
    )
    stale = Evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        observed_at=now - timedelta(minutes=5),
    )
    expired = Evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        observed_at=now - timedelta(minutes=30),
    )

    assert freshness_of(fresh, schema, now=now) == Freshness.FRESH
    assert freshness_of(stale, schema, now=now) == Freshness.STALE
    assert freshness_of(expired, schema, now=now) == Freshness.EXPIRED


def test_expired_evidence_blocks_completion(memory: EvidenceGatedMemory):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    expired_ref = memory.record_evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        content='{"refund_id":"REF-1","status":"success"}',
        observed_at=old,
    )
    r = memory.assert_fact(
        "Refund done",
        claim_type="refund_completed",
        evidence=[expired_ref],
    )
    assert r.accepted is False
    assert any(v.gate == "expired_evidence_block" for v in r.gate.violations)


def test_strict_fresh_requirement_blocks_stale(memory: EvidenceGatedMemory):
    # claim_type 'refund_completed' has requires_fresh_evidence=True
    five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    stale_ref = memory.record_evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        content='{"refund_id":"REF-1","status":"success"}',
        observed_at=five_min_ago,
    )
    r = memory.assert_fact(
        "Refund done",
        claim_type="refund_completed",
        evidence=[stale_ref],
    )
    assert r.accepted is False
    # may show up under either the strict gate or the schema gate
    blocked_gates = {v.gate for v in r.gate.violations}
    assert (
        "stale_evidence_block_strict" in blocked_gates
        or "refund_completion_requires_api_response" in blocked_gates
    )
