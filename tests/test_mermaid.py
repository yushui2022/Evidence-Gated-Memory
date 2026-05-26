"""Mermaid projection tests (M1 #20)."""

from __future__ import annotations

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.core.mermaid import render_mermaid


def test_empty_graph_is_valid_flowchart(memory: EvidenceGatedMemory) -> None:
    out = memory.render_task_graph()
    # No nodes yet — must still be a syntactically valid Mermaid block,
    # not an empty string, so callers can embed it unconditionally.
    assert out == "flowchart TD"


def test_single_node_emits_status_class(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node(
        task_id="task_r",
        node_type="step",
        title="Check eligibility",
    )
    out = memory.render_task_graph()
    assert "flowchart TD" in out
    assert f'{node.id}["Check eligibility"]:::pending' in out
    # Class defs are inlined so the block is self-contained
    assert "classDef pending" in out


def test_status_classes_cover_all_states(memory: EvidenceGatedMemory) -> None:
    cases = {
        TaskNodeStatus.PENDING: "pending",
        TaskNodeStatus.IN_PROGRESS: "in_progress",
        TaskNodeStatus.BLOCKED: "blocked",
        TaskNodeStatus.DONE: "done",
        TaskNodeStatus.SKIPPED: "skipped",
    }
    created = {}
    for status, _ in cases.items():
        n = memory.create_task_node("task_s", "step", f"node-{status.value}")
        if status != TaskNodeStatus.PENDING:
            memory.update_task_node_status(n.id, status)
        created[status] = n.id

    out = memory.render_task_graph(task_id="task_s")
    for status, cls in cases.items():
        assert f"{created[status]}" in out
        assert f":::{cls}" in out


def test_parent_child_edges(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_e", "step", "A")
    b = memory.create_task_node("task_e", "step", "B", parent_id=a.id)
    c = memory.create_task_node("task_e", "step", "C", parent_id=b.id)
    out = memory.render_task_graph(task_id="task_e")
    assert f"{a.id} --> {b.id}" in out
    assert f"{b.id} --> {c.id}" in out


def test_task_id_filter_isolates_workflows(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_X", "step", "A in X")
    b = memory.create_task_node("task_Y", "step", "B in Y")

    out_x = memory.render_task_graph(task_id="task_X")
    assert a.id in out_x
    assert b.id not in out_x

    out_y = memory.render_task_graph(task_id="task_Y")
    assert b.id in out_y
    assert a.id not in out_y


def test_edge_to_out_of_scope_parent_is_dropped(memory: EvidenceGatedMemory) -> None:
    """If a filter excludes the parent, the edge must not be emitted —
    a dangling reference to a node the caller can't see is worse than no edge."""
    parent = memory.create_task_node("task_f", "step", "parent")
    child = memory.create_task_node("task_f", "step", "child", parent_id=parent.id)
    # Block only the child; render only blocked nodes — parent is filtered out
    memory.update_task_node_status(child.id, TaskNodeStatus.BLOCKED, blocked_reason="x")
    out = memory.render_task_graph(task_id="task_f", status=TaskNodeStatus.BLOCKED)
    assert child.id in out
    assert parent.id not in out
    assert f"{parent.id} --> {child.id}" not in out


def test_label_escaping_pure() -> None:
    """Quotes and newlines in titles would break Mermaid parsing — sanitize them."""
    from evidence_gated_memory.core.models import TaskNode

    n = TaskNode(
        task_id="t",
        node_type="step",
        title='He said "go"\nnow',
    )
    out = render_mermaid([n])
    # double-quotes inside the label are flattened to single-quotes,
    # newline collapsed to space
    assert '"He said \'go\' now"' in out
