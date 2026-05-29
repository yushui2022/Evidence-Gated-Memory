"""TaskGraph structured-object tests (M1 #28 + #30)."""

from __future__ import annotations

import json

import pytest

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND


def test_create_and_get_node(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        task_id="task_refund_ord123",
        node_type="eligibility_check",
        title="Check refund eligibility for ORD-123",
        anchors={"order_id": "ORD-123"},
    )
    assert node.id.startswith("node_")
    assert node.status == TaskNodeStatus.PENDING
    assert node.anchors == {"order_id": "ORD-123"}
    assert node.evidence_refs == []
    assert node.fact_refs == []

    fetched = memory.get_task_node(node.id)
    assert fetched is not None
    assert fetched.id == node.id
    assert fetched.title == node.title
    assert fetched.anchors == {"order_id": "ORD-123"}


def test_list_nodes_by_task_id(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_A", "step1", "A1")
    b = memory.create_task_node("task_A", "step2", "A2", parent_id=a.id)
    memory.create_task_node("task_B", "step1", "B1")

    nodes_a = memory.list_task_nodes(task_id="task_A")
    assert [n.id for n in nodes_a] == [a.id, b.id]  # ordered by created_at ASC

    nodes_b = memory.list_task_nodes(task_id="task_B")
    assert len(nodes_b) == 1


def test_create_node_rejects_missing_parent(memory: EvidenceGatedMemory) -> None:
    with pytest.raises(KeyError, match="parent task node not found"):
        memory.create_task_node("task_parent_missing", "step", "child", parent_id="node_missing")


def test_create_node_rejects_cross_task_parent(memory: EvidenceGatedMemory) -> None:
    parent = memory.create_task_node("task_parent_a", "step", "parent")

    with pytest.raises(ValueError, match="cross-task parent_id"):
        memory.create_task_node("task_parent_b", "step", "child", parent_id=parent.id)
    assert memory.get_task("task_parent_b") is None


def test_list_nodes_by_status(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_X", "n1", "n1")
    b = memory.create_task_node("task_X", "n2", "n2")
    memory.update_task_node_status(b.id, TaskNodeStatus.BLOCKED, blocked_reason="missing evidence")

    blocked = memory.list_task_nodes(status=TaskNodeStatus.BLOCKED)
    assert [n.id for n in blocked] == [b.id]
    assert blocked[0].blocked_reason == "missing evidence"

    pending = memory.list_task_nodes(status=TaskNodeStatus.PENDING)
    assert a.id in [n.id for n in pending]


def test_status_transition_clears_block_context_on_unblock(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_Y", "step", "Y1")

    blocked = memory.update_task_node_status(
        node.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing payment_record",
        suggested_action="call payment_api",
    )
    assert blocked.blocked_reason == "missing payment_record"
    assert blocked.suggested_action == "call payment_api"

    unblocked = memory.update_task_node_status(node.id, TaskNodeStatus.IN_PROGRESS)
    assert unblocked.status == TaskNodeStatus.IN_PROGRESS
    # leaving BLOCKED clears reason/action so stale context doesn't linger
    assert unblocked.blocked_reason is None
    assert unblocked.suggested_action is None


def test_attach_evidence_to_node(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_Z", "step", "Z1")

    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        content="{order_id: ORD-Z, status: PAID}",
    )
    memory.attach_evidence_to_node(node.id, ev.id)
    # idempotent: attaching the same evidence twice doesn't duplicate
    memory.attach_evidence_to_node(node.id, ev.id)

    refreshed = memory.get_task_node(node.id)
    assert refreshed.evidence_refs == [ev.id]


def test_attach_phantom_evidence_rejected(memory: EvidenceGatedMemory) -> None:
    """Attaching an evidence id that does not exist must raise — otherwise
    the node's drill-down promise (refs → real content) silently breaks."""
    node = memory.create_task_node("task_phantom", "step", "P1")
    with pytest.raises(KeyError, match="evidence not found"):
        memory.attach_evidence_to_node(node.id, "ref_does_not_exist")


def test_attach_real_gated_fact_to_node(memory: EvidenceGatedMemory) -> None:
    """A fact produced by assert_fact (i.e. one that passed the gate) can be
    attached and is observable on the node afterwards."""
    node = memory.create_task_node("task_real_fact", "step", "RF1")

    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-RF, status: PAID}",
        metadata={"order_id": "ORD-RF"},
    )
    result = memory.assert_fact(
        "Order ORD-RF status is PAID",
        claim_type="order_status",
        evidence=[ev],
    )
    assert result.accepted, result.gate.reason
    fact = result.fact
    assert fact is not None

    memory.attach_fact_to_node(node.id, fact.id)
    # idempotent
    memory.attach_fact_to_node(node.id, fact.id)

    refreshed = memory.get_task_node(node.id)
    assert refreshed.fact_refs == [fact.id]


def test_attach_phantom_fact_rejected(memory: EvidenceGatedMemory) -> None:
    """Attaching a fact id that does not exist must raise — same drill-down
    invariant as evidence."""
    node = memory.create_task_node("task_phantom_fact", "step", "PF1")
    with pytest.raises(KeyError, match="fact not found"):
        memory.attach_fact_to_node(node.id, "fact_does_not_exist")


def test_attach_invalidated_fact_rejected(memory: EvidenceGatedMemory) -> None:
    """A fact whose evidence has been revoked is cascade-invalidated and
    must not be attachable — a node's fact_refs are a live set."""
    node = memory.create_task_node("task_inv", "step", "I1")

    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-I, status: PAID}",
        metadata={"order_id": "ORD-I"},
    )
    result = memory.assert_fact(
        "Order ORD-I status is PAID",
        claim_type="order_status",
        evidence=[ev],
    )
    assert result.accepted
    fact = result.fact

    memory.revoke_evidence(ev.id, reason="superseded")
    assert memory.store.get_fact(fact.id).invalidated_at is not None

    with pytest.raises(ValueError, match="invalidated"):
        memory.attach_fact_to_node(node.id, fact.id)


def test_attach_to_missing_node_raises(memory: EvidenceGatedMemory) -> None:
    with pytest.raises(KeyError):
        memory.attach_evidence_to_node("node_doesnotexist", "ref_x")
    with pytest.raises(KeyError):
        memory.attach_fact_to_node("node_doesnotexist", "fact_x")
    with pytest.raises(KeyError):
        memory.update_task_node_status("node_doesnotexist", TaskNodeStatus.DONE)


# ---------- Audit trail ----------


def _audit_event_types(memory: EvidenceGatedMemory) -> list[str]:
    return [row["event_type"] for row in memory.store.list_audit(limit=200)]


def _audit_details_for(memory: EvidenceGatedMemory, event_type: str) -> list[dict]:
    return [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == event_type
    ]


def test_audit_create_node(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        task_id="task_audit_c",
        node_type="step",
        title="audit create",
        anchors={"order_id": "ORD-AC"},
    )
    details = _audit_details_for(memory, "task_node_created")
    assert any(d["node_id"] == node.id and d["task_id"] == "task_audit_c" for d in details)


def test_audit_status_change_records_prev_state(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_audit_s", "step", "audit status")
    memory.update_task_node_status(
        node.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing payment_record",
        suggested_action="call payment_api",
    )
    memory.update_task_node_status(node.id, TaskNodeStatus.IN_PROGRESS)

    changes = [
        d for d in _audit_details_for(memory, "task_node_status_changed")
        if d["node_id"] == node.id
    ]
    assert len(changes) == 2

    # list_audit returns DESC by id, so reverse to get chronological order
    first, second = list(reversed(changes))
    assert first["from_status"] == "pending"
    assert first["to_status"] == "blocked"
    assert first["new_blocked_reason"] == "missing payment_record"

    assert second["from_status"] == "blocked"
    assert second["to_status"] == "in_progress"
    # prev state from the BLOCKED node is preserved in audit even though the
    # node row has cleared it
    assert second["prev_blocked_reason"] == "missing payment_record"
    assert second["prev_suggested_action"] == "call payment_api"
    assert second["new_blocked_reason"] is None


def test_audit_evidence_and_fact_attach(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_audit_a", "step", "audit attach")
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="{order_id: ORD-AA, status: PAID}",
        metadata={"order_id": "ORD-AA"},
    )
    memory.attach_evidence_to_node(node.id, ev.id)
    # second attach is a no-op and must NOT generate a second audit entry
    memory.attach_evidence_to_node(node.id, ev.id)

    ev_details = [
        d for d in _audit_details_for(memory, "task_node_evidence_attached")
        if d["node_id"] == node.id
    ]
    assert len(ev_details) == 1
    assert ev_details[0]["evidence_id"] == ev.id

    result = memory.assert_fact(
        "Order ORD-AA status is PAID",
        claim_type="order_status",
        evidence=[ev],
    )
    assert result.accepted
    memory.attach_fact_to_node(node.id, result.fact.id)
    memory.attach_fact_to_node(node.id, result.fact.id)  # idempotent

    fact_details = [
        d for d in _audit_details_for(memory, "task_node_fact_attached")
        if d["node_id"] == node.id
    ]
    assert len(fact_details) == 1
    assert fact_details[0]["fact_id"] == result.fact.id
