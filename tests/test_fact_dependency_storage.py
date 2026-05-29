"""Normalized fact dependency index tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory, FactKind
from evidence_gated_memory.storage.sqlite import SqliteStore


def test_fact_evidence_refs_index_populates_on_insert(memory: EvidenceGatedMemory) -> None:
    order = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-IDX","status":"PAID"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="14d",
    )

    result = memory.assert_fact(
        "Order ORD-IDX is refundable",
        claim_type="refund_eligibility",
        evidence=[order, policy],
    )

    assert result.accepted
    indexed = memory.store.conn.execute(
        "SELECT evidence_id FROM fact_evidence_refs WHERE fact_id=? ORDER BY evidence_id",
        (result.fact.id,),
    ).fetchall()
    assert [row["evidence_id"] for row in indexed] == sorted([order.id, policy.id])
    assert [fact.id for fact in memory.store.list_facts_using_evidence(order.id)] == [
        result.fact.id
    ]


def test_fact_dependencies_index_populates_on_derived_fact(memory: EvidenceGatedMemory) -> None:
    order = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-DER","status":"PAID"}',
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="14d",
    )
    refund = memory.record_evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        content='{"refund_id":"REF-DER","status":"success"}',
    )
    eligibility = memory.assert_fact(
        "ORD-DER eligible",
        claim_type="refund_eligibility",
        evidence=[order, policy],
    )
    completion = memory.assert_fact(
        "ORD-DER refund executed",
        claim_type="refund_completed",
        evidence=[refund],
    )
    derived = memory.assert_fact(
        "Customer fully refunded for ORD-DER",
        claim_type="refund_completed",
        kind=FactKind.DERIVED,
        depends_on=[eligibility.fact, completion.fact],
    )

    assert derived.accepted
    indexed = memory.store.conn.execute(
        "SELECT parent_fact_id FROM fact_dependencies WHERE child_fact_id=? ORDER BY parent_fact_id",
        (derived.fact.id,),
    ).fetchall()
    assert [row["parent_fact_id"] for row in indexed] == sorted([
        eligibility.fact.id,
        completion.fact.id,
    ])
    assert [fact.id for fact in memory.store.list_facts_depending_on(eligibility.fact.id)] == [
        derived.fact.id
    ]


def test_sqlite_migrates_v2_fact_dependency_indexes(tmp_path: Path) -> None:
    workspace = tmp_path / "egm"
    workspace.mkdir()
    db_path = workspace / "egm.db"
    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', '2')")
        conn.execute(
            """CREATE TABLE facts (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                text TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                kind TEXT NOT NULL,
                evidence_refs TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                invalidated_at TEXT,
                invalidation_reason TEXT,
                metadata TEXT NOT NULL,
                node_id TEXT
            )"""
        )
        conn.execute(
            """INSERT INTO facts(
                id, created_at, claim_id, text, claim_type, kind,
                evidence_refs, depends_on, invalidated_at, invalidation_reason,
                metadata, node_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "fact_parent",
                now,
                "claim_parent",
                "Parent fact",
                "refund_eligibility",
                "observed",
                '["ref_old"]',
                "[]",
                None,
                None,
                "{}",
                None,
            ),
        )
        conn.execute(
            """INSERT INTO facts(
                id, created_at, claim_id, text, claim_type, kind,
                evidence_refs, depends_on, invalidated_at, invalidation_reason,
                metadata, node_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "fact_child",
                now,
                "claim_child",
                "Child fact",
                "refund_completed",
                "derived",
                "[]",
                '["fact_parent"]',
                None,
                None,
                "{}",
                None,
            ),
        )
        conn.commit()

    store = SqliteStore(workspace)
    try:
        assert store.get_schema_version() == 3
        assert [fact.id for fact in store.list_facts_using_evidence("ref_old")] == [
            "fact_parent"
        ]
        assert [fact.id for fact in store.list_facts_depending_on("fact_parent")] == [
            "fact_child"
        ]
    finally:
        store.close()
