"""Gated transition_node API tests (M1 #31)."""

from __future__ import annotations

import json

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus


def _refund_api_ref(memory: EvidenceGatedMemory):
    return memory.record_evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        content='{"refund_id":"REF-TN","status":"success"}',
        metadata={"refund_id": "REF-TN"},
    )


def test_transition_node_rejects_without_required_evidence(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_reject",
        "refund_completion",
        "Complete refund",
    )

    result = memory.transition_node(node.id, TaskNodeStatus.DONE)

    assert result.accepted is False
    assert result.node.status == TaskNodeStatus.PENDING
    assert "refund_api_response" in result.rejection_reason
    assert "refund_api" in result.suggested_action
    assert memory.get_task_node(node.id).status == TaskNodeStatus.PENDING
    assert memory.get_task("task_transition_reject").current_state.value == "open"


def test_transition_node_accepts_attaches_evidence_and_updates_state(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_accept",
        "refund_completion",
        "Complete refund",
    )
    ev = _refund_api_ref(memory)

    result = memory.transition_node(node.id, TaskNodeStatus.DONE, evidence=[ev])

    assert result.accepted is True
    assert result.node.status == TaskNodeStatus.DONE
    assert result.node.evidence_refs == [ev.id]
    assert memory.get_task("task_transition_accept").current_state.value == "done"


def test_transition_node_uses_already_attached_evidence(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_existing_ref",
        "refund_completion",
        "Complete refund",
    )
    ev = _refund_api_ref(memory)
    memory.attach_evidence_to_node(node.id, ev.id)

    result = memory.transition_node(node.id, TaskNodeStatus.DONE)

    assert result.accepted is True
    assert result.node.status == TaskNodeStatus.DONE
    assert result.node.evidence_refs == [ev.id]


def test_transition_node_can_mark_blocked_with_actionable_context(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_blocked",
        "refund_completion",
        "Complete refund",
    )

    result = memory.transition_node(
        node.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing refund_api_response",
        suggested_action="call refund_api",
    )

    assert result.accepted is True
    assert result.node.status == TaskNodeStatus.BLOCKED
    assert result.node.blocked_reason == "missing refund_api_response"
    assert result.node.suggested_action == "call refund_api"
    assert memory.get_task("task_transition_blocked").current_state.value == "blocked"


def test_transition_node_missing_explicit_ref_rejects_without_mutation(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_missing_ref",
        "refund_completion",
        "Complete refund",
    )

    result = memory.transition_node(
        node.id,
        TaskNodeStatus.DONE,
        evidence=["ref_does_not_exist"],
    )

    assert result.accepted is False
    assert any(v.gate == "missing_transition_evidence_refs" for v in result.gate.violations)
    refreshed = memory.get_task_node(node.id)
    assert refreshed.status == TaskNodeStatus.PENDING
    assert refreshed.evidence_refs == []


def test_transition_node_writes_gate_and_status_audit(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_transition_audit",
        "refund_completion",
        "Complete refund",
    )
    ev = _refund_api_ref(memory)

    memory.transition_node(node.id, TaskNodeStatus.DONE, evidence=[ev])

    rows = memory.store.list_audit(limit=200)
    state_checks = [
        row for row in rows
        if row["event_type"] == "state_gate_check"
        and json.loads(row["detail"])["node_id"] == node.id
    ]
    status_changes = [
        row for row in rows
        if row["event_type"] == "task_node_status_changed"
        and json.loads(row["detail"])["node_id"] == node.id
    ]

    assert len(state_checks) == 1
    assert state_checks[0]["accepted"] == 1
    assert len(status_changes) == 1
