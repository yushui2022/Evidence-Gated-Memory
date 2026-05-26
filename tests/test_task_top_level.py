"""Top-level Task model + TaskEdge tests (M1 #32)."""

from __future__ import annotations

import json

import pytest

from evidence_gated_memory import (
    EvidenceGatedMemory,
    Task,
    TaskEdgeKind,
    TaskStatus,
)


# ---------- Task lifecycle ----------


def test_create_task_explicit(memory: EvidenceGatedMemory) -> None:
    task = memory.create_task(
        "task_refund_ord123",
        title="Refund ORD-123",
        anchors={"order_id": "ORD-123"},
    )
    assert isinstance(task, Task)
    assert task.id == "task_refund_ord123"
    assert task.status == TaskStatus.OPEN
    assert task.anchors == {"order_id": "ORD-123"}

    fetched = memory.get_task("task_refund_ord123")
    assert fetched is not None
    assert fetched.title == "Refund ORD-123"


def test_create_task_node_auto_creates_task(memory: EvidenceGatedMemory) -> None:
    """Back-compat: a node created against a new task_id materialises the
    workflow row on the fly."""
    assert memory.get_task("task_auto") is None
    memory.create_task_node("task_auto", "step", "S1", anchors={"order_id": "ORD-A"})
    task = memory.get_task("task_auto")
    assert task is not None
    assert task.status == TaskStatus.OPEN
    assert task.anchors == {"order_id": "ORD-A"}


def test_create_task_idempotent_with_status_change(memory: EvidenceGatedMemory) -> None:
    memory.create_task("task_X", title="X")
    memory.create_task("task_X", title="X (updated)", status=TaskStatus.DONE)
    task = memory.get_task("task_X")
    assert task.title == "X (updated)"
    assert task.status == TaskStatus.DONE


def test_list_tasks_filters_by_status(memory: EvidenceGatedMemory) -> None:
    memory.create_task("task_open_1")
    memory.create_task("task_open_2")
    memory.create_task("task_done", status=TaskStatus.DONE)

    open_tasks = memory.list_tasks(status=TaskStatus.OPEN)
    assert {t.id for t in open_tasks} == {"task_open_1", "task_open_2"}

    done_tasks = memory.list_tasks(status=TaskStatus.DONE)
    assert [t.id for t in done_tasks] == ["task_done"]


# ---------- TaskEdge ----------


def test_add_edge_between_nodes_in_same_task(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_e", "step", "A")
    b = memory.create_task_node("task_e", "step", "B")
    edge = memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.DEPENDS_ON)

    assert edge.task_id == "task_e"
    assert edge.kind == TaskEdgeKind.DEPENDS_ON

    edges = memory.list_task_edges(task_id="task_e")
    assert len(edges) == 1
    assert edges[0].src_node_id == a.id
    assert edges[0].dst_node_id == b.id


def test_add_edge_idempotent(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_i", "step", "A")
    b = memory.create_task_node("task_i", "step", "B")
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.TRIGGERS)
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.TRIGGERS)  # dup, ignored

    edges = memory.list_task_edges(task_id="task_i")
    assert len(edges) == 1


def test_add_edge_rejects_phantom_endpoints(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_p", "step", "A")
    with pytest.raises(KeyError, match="task node not found"):
        memory.add_task_edge(a.id, "node_does_not_exist")
    with pytest.raises(KeyError, match="task node not found"):
        memory.add_task_edge("node_does_not_exist", a.id)


def test_add_edge_rejects_cross_task(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_A", "step", "A")
    b = memory.create_task_node("task_B", "step", "B")
    with pytest.raises(ValueError, match="cross-task edges"):
        memory.add_task_edge(a.id, b.id)


def test_add_edge_rejects_self_loop(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_s", "step", "A")
    with pytest.raises(ValueError, match="self-loop"):
        memory.add_task_edge(a.id, a.id)


def test_add_edge_writes_audit(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_au", "step", "A")
    b = memory.create_task_node("task_au", "step", "B")
    edge = memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.PRODUCES)

    details = [
        json.loads(r["detail"])
        for r in memory.store.list_audit(limit=200)
        if r["event_type"] == "task_edge_added"
    ]
    matching = [d for d in details if d["edge_id"] == edge.id]
    assert len(matching) == 1
    assert matching[0]["kind"] == "produces"
    assert matching[0]["src"] == a.id
    assert matching[0]["dst"] == b.id


# ---------- Mermaid rendering of typed edges ----------


def test_render_includes_typed_edges(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_r", "step", "A")
    b = memory.create_task_node("task_r", "step", "B")
    c = memory.create_task_node("task_r", "step", "C")
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.DEPENDS_ON)
    memory.add_task_edge(b.id, c.id, kind=TaskEdgeKind.TRIGGERS)

    out = memory.render_task_graph(task_id="task_r")
    assert f"{a.id} -. depends .-> {b.id}" in out
    assert f"{b.id} ==>|triggers| {c.id}" in out


def test_render_drops_edges_filtered_out(memory: EvidenceGatedMemory) -> None:
    """If a status filter removes an endpoint, the edge must not leak through."""
    from evidence_gated_memory import TaskNodeStatus

    a = memory.create_task_node("task_f", "step", "A")
    b = memory.create_task_node("task_f", "step", "B")
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.DEPENDS_ON)
    memory.update_task_node_status(b.id, TaskNodeStatus.BLOCKED, blocked_reason="x")

    out = memory.render_task_graph(task_id="task_f", status=TaskNodeStatus.BLOCKED)
    # A was filtered out -> edge must drop
    assert a.id not in out
    assert "depends" not in out


def test_render_without_task_id_skips_edges(memory: EvidenceGatedMemory) -> None:
    """Edges are only meaningful inside a single workflow — global render
    intentionally omits them."""
    a = memory.create_task_node("task_g1", "step", "A")
    b = memory.create_task_node("task_g1", "step", "B")
    memory.add_task_edge(a.id, b.id, kind=TaskEdgeKind.DEPENDS_ON)
    memory.create_task_node("task_g2", "step", "C")

    out = memory.render_task_graph()  # no task_id
    assert "depends" not in out
    assert "==>" not in out
