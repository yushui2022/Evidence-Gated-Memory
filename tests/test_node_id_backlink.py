"""evidence/fact ↔ node_id back-link tests (M1 #23)."""

from __future__ import annotations

from evidence_gated_memory import EvidenceGatedMemory


def test_evidence_node_id_is_none_until_attached(memory: EvidenceGatedMemory) -> None:
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-1, status: PAID}",
    )
    fetched = memory.get_evidence(ev.id)
    assert fetched.node_id is None


def test_evidence_node_id_set_on_attach(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_bl", "step", "S")
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-1, status: PAID}",
    )
    memory.attach_evidence_to_node(node.id, ev.id)

    fetched = memory.get_evidence(ev.id)
    assert fetched.node_id == node.id


def test_fact_node_id_set_on_attach(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_bf", "step", "S")
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-2, status: PAID}",
        metadata={"order_id": "ORD-2"},
    )
    result = memory.assert_fact(
        "Order ORD-2 status is PAID",
        claim_type="order_status",
        evidence=[ev],
    )
    assert result.accepted
    fact = result.fact
    assert memory.store.get_fact(fact.id).node_id is None

    memory.attach_fact_to_node(node.id, fact.id)
    refreshed = memory.store.get_fact(fact.id)
    assert refreshed.node_id == node.id


def test_idempotent_reattach_keeps_node_id_stable(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_idem", "step", "S")
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-3}",
    )
    memory.attach_evidence_to_node(node.id, ev.id)
    memory.attach_evidence_to_node(node.id, ev.id)  # no-op second attach
    assert memory.get_evidence(ev.id).node_id == node.id
