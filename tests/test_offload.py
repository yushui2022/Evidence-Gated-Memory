"""Offload JSONL index tests (M3 #27)."""

from __future__ import annotations

import json

import pytest

from evidence_gated_memory import EvidenceGatedMemory


def _order_ref(memory: EvidenceGatedMemory, order_id: str = "ORD-OFF"):
    return memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content=f'{{"order_id":"{order_id}","status":"PAID"}}',
        metadata={"order_id": order_id},
    )


def test_record_offload_writes_jsonl_and_attaches_ref(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_offload", "check_order", "Check order")
    ev = _order_ref(memory)

    record = memory.record_offload(
        task_id="task_offload",
        node_id=node.id,
        tool_call_id="tool_call_001",
        result_ref=ev,
        summary="order_api returned ORD-OFF status=PAID",
        score=8,
    )

    assert record.task_id == "task_offload"
    assert record.node_id == node.id
    assert record.result_ref == ev.id
    assert record.score == 8

    offload_path = memory.workspace / "offload" / "offload.jsonl"
    assert offload_path.exists()
    lines = offload_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["result_ref"] == ev.id

    refreshed = memory.get_task_node(node.id)
    assert refreshed.evidence_refs == [ev.id]


def test_list_offloads_filters_by_task_and_node(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_A", "check_order", "A")
    b = memory.create_task_node("task_A", "check_payment", "B")
    c = memory.create_task_node("task_B", "check_order", "C")

    ev_a = _order_ref(memory, "ORD-A")
    ev_b = _order_ref(memory, "ORD-B")
    ev_c = _order_ref(memory, "ORD-C")

    rec_a = memory.record_offload(
        task_id="task_A",
        node_id=a.id,
        tool_call_id="call_A",
        result_ref=ev_a,
        summary="A",
    )
    rec_b = memory.record_offload(
        task_id="task_A",
        node_id=b.id,
        tool_call_id="call_B",
        result_ref=ev_b,
        summary="B",
    )
    rec_c = memory.record_offload(
        task_id="task_B",
        node_id=c.id,
        tool_call_id="call_C",
        result_ref=ev_c,
        summary="C",
    )

    assert [r.id for r in memory.list_offloads(task_id="task_A")] == [rec_a.id, rec_b.id]
    assert [r.id for r in memory.list_offloads(node_id=b.id)] == [rec_b.id]
    assert [r.id for r in memory.list_offloads(task_id="task_B")] == [rec_c.id]


def test_record_offload_rejects_missing_node(memory: EvidenceGatedMemory) -> None:
    ev = _order_ref(memory)

    with pytest.raises(KeyError, match="task node not found"):
        memory.record_offload(
            task_id="task_missing",
            node_id="node_does_not_exist",
            tool_call_id="call_missing",
            result_ref=ev,
            summary="missing",
        )


def test_record_offload_rejects_missing_result_ref(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_missing_ref", "check_order", "Check order")

    with pytest.raises(KeyError, match="evidence not found"):
        memory.record_offload(
            task_id="task_missing_ref",
            node_id=node.id,
            tool_call_id="call_missing_ref",
            result_ref="ref_does_not_exist",
            summary="missing ref",
        )


def test_record_offload_rejects_cross_task_node(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_real", "check_order", "Check order")
    ev = _order_ref(memory)

    with pytest.raises(ValueError, match="does not match node task_id"):
        memory.record_offload(
            task_id="task_wrong",
            node_id=node.id,
            tool_call_id="call_cross",
            result_ref=ev,
            summary="wrong task",
        )


def test_record_offload_writes_audit(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_audit_offload", "check_order", "Check order")
    ev = _order_ref(memory)

    record = memory.record_offload(
        task_id="task_audit_offload",
        node_id=node.id,
        tool_call_id="call_audit",
        result_ref=ev,
        summary="audit",
    )

    details = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == "offload_recorded"
    ]
    assert len(details) == 1
    assert details[0]["offload_id"] == record.id
    assert details[0]["result_ref"] == ev.id
