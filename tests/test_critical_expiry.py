"""Verification #6: option C — required evidence controls expiry semantics.

- Required evidence with no usable non-expired ref -> BLOCK and invalidate.
- Optional expired evidence may remain attached but should surface as a warning.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from evidence_gated_memory import EvidenceGatedMemory, FactKind, Freshness


@pytest.fixture
def crit_schema(tmp_path: Path) -> Path:
    p = tmp_path / "crit.yaml"
    p.write_text(
        """
name: crit_demo
evidence_types:
  payment_record:
    stale_after: PT5M
    expired_after: PT1H
    source_systems: ["payment_api"]
    risk: high
  policy_doc:
    stale_after: P30D
    expired_after: P365D
    source_systems: ["policy_db"]
    risk: medium
  audit_note:
    stale_after: P30D
    expired_after: P365D
    source_systems: ["audit_log"]
    risk: low
claim_types:
  payout_made:
    required_evidence: ["payment_record", "policy_doc"]
gates: []
""",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def crit_memory(tmp_path: Path, crit_schema: Path) -> EvidenceGatedMemory:
    m = EvidenceGatedMemory(workspace=tmp_path / "egm_crit", domain_schema=crit_schema)
    yield m
    m.close()


def _fresh_pair(crit_memory):
    pay = crit_memory.record_evidence(
        evidence_type="payment_record", source="payment_api", source_system="payment_api",
        content='{"txn":"T1"}',
    )
    pol = crit_memory.record_evidence(
        evidence_type="policy_doc", source="policy_db", source_system="policy_db",
        content="policy v1",
    )
    return pay, pol


def test_required_expired_blocks_assertion(crit_memory):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    expired_pay = crit_memory.record_evidence(
        evidence_type="payment_record", source="payment_api", source_system="payment_api",
        content='{"txn":"T1"}', observed_at=old,
    )
    pol = crit_memory.record_evidence(
        evidence_type="policy_doc", source="policy_db", source_system="policy_db",
        content="policy",
    )
    r = crit_memory.assert_fact(
        "payout made",
        claim_type="payout_made",
        evidence=[expired_pay, pol],
    )
    assert r.accepted is False
    assert any(v.gate == "expired_evidence_block" for v in r.gate.violations)


def test_required_expired_invalidates_existing_fact(crit_memory):
    pay, pol = _fresh_pair(crit_memory)
    r = crit_memory.assert_fact(
        "payout made", claim_type="payout_made", evidence=[pay, pol],
    )
    assert r.accepted
    fact_id = r.fact.id

    # backdate payment to simulate expiry by sweep
    very_old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    crit_memory.store.conn.execute(
        "UPDATE evidence SET observed_at=? WHERE id=?", (very_old, pay.id),
    )
    crit_memory.store.conn.commit()

    invalidated = crit_memory.sweep_expired()
    assert fact_id in invalidated
    after = crit_memory.store.get_fact(fact_id)
    assert after.invalidated_at is not None


def test_optional_expired_keeps_fact_with_warning(crit_memory):
    pay, pol = _fresh_pair(crit_memory)
    audit = crit_memory.record_evidence(
        evidence_type="audit_note", source="audit_log", source_system="audit_log",
        content="operator note",
    )
    r = crit_memory.assert_fact(
        "payout made", claim_type="payout_made", evidence=[pay, pol, audit],
    )
    assert r.accepted
    fact_id = r.fact.id

    # expire only the optional audit note
    very_old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    crit_memory.store.conn.execute(
        "UPDATE evidence SET observed_at=? WHERE id=?", (very_old, audit.id),
    )
    crit_memory.store.conn.commit()

    invalidated = crit_memory.sweep_expired()
    assert fact_id not in invalidated

    after = crit_memory.store.get_fact(fact_id)
    assert after.invalidated_at is None

    ctx = crit_memory.build_context()
    assert "payout made" in ctx
    # non-critical expired evidence should at least surface as a warning
    assert ("STALE" in ctx) or ("EXPIRED" in ctx) or ("⚠" in ctx)
