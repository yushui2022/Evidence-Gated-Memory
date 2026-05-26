"""TaskNode state-transition gate tests (M1 #22)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus


def _refund_api_ref(
    memory: EvidenceGatedMemory,
    *,
    observed_at: datetime | None = None,
    source_system: str = "refund_api",
):
    return memory.record_evidence(
        evidence_type="refund_api_response",
        source=source_system,
        source_system=source_system,
        content='{"refund_id":"REF-SG","status":"success"}',
        metadata={"refund_id": "REF-SG"},
        observed_at=observed_at,
    )


def test_refund_schema_loads_state_gates(memory: EvidenceGatedMemory) -> None:
    names = {rule.name for rule in memory.schema.state_gates}

    assert "refund_completion_done_requires_api_response" in names
    assert "eligibility_done_requires_order_and_policy" in names


def test_transition_to_done_without_required_evidence_is_rejected(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_state_gate_missing",
        "refund_completion",
        "Complete refund",
    )

    result = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)

    assert result.accepted is False
    assert result.node_id == node.id
    assert result.from_status == TaskNodeStatus.PENDING
    assert result.to_status == TaskNodeStatus.DONE
    assert memory.get_task_node(node.id).status == TaskNodeStatus.PENDING
    missing: set[str] = set()
    for violation in result.violations:
        missing.update(violation.missing_evidence_types)
    assert "refund_api_response" in missing
    assert "refund_api" in result.suggested_action


def test_transition_to_done_with_required_evidence_is_accepted(
    memory: EvidenceGatedMemory,
) -> None:
    node = memory.create_task_node(
        "task_state_gate_ok",
        "refund_completion",
        "Complete refund",
    )
    ev = _refund_api_ref(memory)
    memory.attach_evidence_to_node(node.id, ev.id)

    result = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)

    assert result.accepted is True
    assert result.violations == []


def test_transition_gate_enforces_freshness(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        "task_state_gate_stale",
        "refund_completion",
        "Complete refund",
    )
    stale_ref = _refund_api_ref(
        memory,
        observed_at=datetime.now(timezone.utc) - timedelta(minutes=3),
    )
    memory.attach_evidence_to_node(node.id, stale_ref.id)

    result = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)

    assert result.accepted is False
    assert any(stale_ref.id in v.stale_refs for v in result.violations)
    assert "fresh" in result.rejection_reason


def test_transition_gate_rejects_untrusted_source(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        "task_state_gate_source",
        "refund_completion",
        "Complete refund",
    )
    ev = _refund_api_ref(memory, source_system="cache")
    memory.attach_evidence_to_node(node.id, ev.id)

    result = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)

    assert result.accepted is False
    assert any(v.gate == "transition_source_system_not_allowed" for v in result.violations)


def test_transition_gate_writes_audit(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        "task_state_gate_audit",
        "refund_completion",
        "Complete refund",
    )

    result = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)

    rows = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == "state_gate_check"
    ]
    assert result.accepted is False
    assert len(rows) == 1
    assert rows[0]["node_id"] == node.id
    assert rows[0]["to_status"] == "done"
    assert rows[0]["violations"]


def test_update_task_node_status_remains_low_level_crud(
    memory: EvidenceGatedMemory,
) -> None:
    """#22 adds the gate checker but must not make CRUD status updates gated."""
    node = memory.create_task_node(
        "task_state_gate_crud",
        "refund_completion",
        "Complete refund",
    )
    gate = memory.check_node_transition_gate(node.id, TaskNodeStatus.DONE)
    assert gate.accepted is False

    updated = memory.update_task_node_status(node.id, TaskNodeStatus.DONE)

    assert updated.status == TaskNodeStatus.DONE
    assert memory.get_task("task_state_gate_crud").current_state.value == "done"
