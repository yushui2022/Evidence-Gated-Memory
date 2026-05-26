"""Context builder TaskGraph integration tests (M1 #24)."""

from __future__ import annotations

from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory, TaskEdgeKind
from evidence_gated_memory.cli import main
from evidence_gated_memory.schemas.builtin import REFUND


def test_context_includes_task_map_even_without_facts(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_ctx", "step", "Check order")
    b = memory.create_task_node("task_ctx", "step", "Check payment")
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.DEPENDS_ON)

    ctx = memory.build_context(task_id="task_ctx")

    assert "<task_map>" in ctx
    assert "task_id: task_ctx" in ctx
    assert "```mermaid" in ctx
    assert "flowchart TD" in ctx
    assert a.id in ctx
    assert b.id in ctx
    assert "depends" in ctx
    assert "no facts available" in ctx


def test_context_includes_node_backlinks_for_fact_and_evidence(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_fact_ctx", "step", "Check status")
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-CTX","status":"PAID"}',
        metadata={"order_id": "ORD-CTX"},
    )
    result = memory.assert_fact(
        "Order ORD-CTX status is PAID",
        claim_type="order_status",
        evidence=[ev],
    )
    assert result.accepted

    memory.attach_evidence_to_node(node.id, ev.id)
    memory.attach_fact_to_node(node.id, result.fact.id)

    ctx = memory.build_context(task_id="task_fact_ctx")

    assert "<task_map>" in ctx
    assert "Order ORD-CTX status is PAID" in ctx
    assert f"  node: {node.id}" in ctx
    assert f"node={node.id}" in ctx


def test_cli_context_accepts_task_id(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "egm"
    memory = EvidenceGatedMemory(workspace, REFUND)
    try:
        node = memory.create_task_node("task_cli_ctx", "step", "CLI task node")
        ev = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-CLI","status":"PAID"}',
            metadata={"order_id": "ORD-CLI"},
        )
        result = memory.assert_fact(
            "Order ORD-CLI status is PAID",
            claim_type="order_status",
            evidence=[ev],
        )
        assert result.accepted
        memory.attach_evidence_to_node(node.id, ev.id)
        memory.attach_fact_to_node(node.id, result.fact.id)
    finally:
        memory.close()

    assert main(["context", str(workspace), "--schema", "refund", "--task-id", "task_cli_ctx"]) == 0
    out = capsys.readouterr().out
    assert "<task_map>" in out
    assert "CLI task node" in out
    assert "ORD-CLI" in out


def test_task_focus_keeps_linked_fact_when_max_facts_is_tight(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_focus", "step", "Focused node")

    focused_ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-FOCUS","status":"PAID"}',
        metadata={"order_id": "ORD-FOCUS"},
    )
    focused_result = memory.assert_fact(
        "Order ORD-FOCUS status is PAID",
        claim_type="order_status",
        evidence=[focused_ev],
    )
    assert focused_result.accepted
    memory.attach_evidence_to_node(node.id, focused_ev.id)
    memory.attach_fact_to_node(node.id, focused_result.fact.id)

    unrelated_ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-OTHER","status":"PAID"}',
        metadata={"order_id": "ORD-OTHER"},
    )
    unrelated_result = memory.assert_fact(
        "Order ORD-OTHER status is PAID",
        claim_type="order_status",
        evidence=[unrelated_ev],
    )
    assert unrelated_result.accepted

    unfocused = memory.build_context(max_facts=1)
    assert "ORD-OTHER" in unfocused
    assert "ORD-FOCUS" not in unfocused

    focused = memory.build_context(task_id="task_focus", max_facts=1)
    assert "ORD-FOCUS" in focused
    assert "ORD-OTHER" not in focused
