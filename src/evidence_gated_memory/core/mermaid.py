"""Mermaid projection of the TaskGraph.

The TaskGraph is the source of truth — a list of structured TaskNode rows.
Mermaid is one *readable projection* of it, suitable for embedding in the
agent prompt as a `<task_map>` block. It is intentionally lossy: the agent
reads the high-level map and drills down to evidence / facts via
node_id / result_ref only when needed.
"""

from __future__ import annotations

from typing import Iterable, Optional

from evidence_gated_memory.core.models import TaskEdge, TaskEdgeKind, TaskNode, TaskNodeStatus


# Mermaid classDef styles. Keeping them inline (instead of a separate stylesheet)
# means a rendered block is self-contained — paste it anywhere and it works.
_CLASS_DEFS = [
    "classDef pending fill:#f5f5f5,stroke:#999,color:#333",
    "classDef in_progress fill:#fff3cd,stroke:#d39e00,color:#333",
    "classDef blocked fill:#f8d7da,stroke:#c82333,color:#333",
    "classDef done fill:#d4edda,stroke:#28a745,color:#1b4d2b",
    "classDef skipped fill:#e2e3e5,stroke:#6c757d,color:#495057",
]

_STATUS_CLASS = {
    TaskNodeStatus.PENDING: "pending",
    TaskNodeStatus.IN_PROGRESS: "in_progress",
    TaskNodeStatus.BLOCKED: "blocked",
    TaskNodeStatus.DONE: "done",
    TaskNodeStatus.SKIPPED: "skipped",
}


# Each edge kind gets a distinct Mermaid arrow shape so the projection stays
# readable even with mixed semantics in one graph. PARENT keeps the plain
# arrow (matches the parent_id rendering); the others use dashed/thick/labelled
# variants so a glance distinguishes "is part of" from "must come after".
_EDGE_RENDER = {
    TaskEdgeKind.PARENT:     "-->",
    TaskEdgeKind.DEPENDS_ON: "-. depends .->",
    TaskEdgeKind.TRIGGERS:   "==>|triggers|",
    TaskEdgeKind.PRODUCES:   "-->|produces|",
    TaskEdgeKind.BLOCKS:     "-. blocks .->",
}


def _escape_label(text: str) -> str:
    """Mermaid node labels are wrapped in `["..."]`. Inner double-quotes and
    line breaks would break the parser, so neutralise them. We deliberately
    keep this minimal — anything fancier should live in the node's metadata,
    not its title."""
    return text.replace('"', "'").replace("\n", " ").strip()


def _short_id(node_id: str) -> str:
    """Mermaid node IDs must be alphanumeric/underscore. Our `node_xxxxxx`
    ids already qualify, so this is just a defensive pass-through."""
    return node_id.replace("-", "_")


def render_mermaid(
    nodes: Iterable[TaskNode],
    edges: Optional[Iterable[TaskEdge]] = None,
) -> str:
    """Render a list of TaskNodes (+ optional typed edges) as a Mermaid
    `flowchart TD` block.

    Pure function: takes a snapshot, returns a string. No I/O, no DB access.
    The empty case still returns a valid (empty) flowchart so callers can
    embed the result unconditionally.

    Edges whose endpoints aren't both in the node snapshot are dropped — a
    dangling reference would mislead the agent more than a missing one.
    """
    nodes = list(nodes)
    edges = list(edges or [])
    lines: list[str] = ["flowchart TD"]

    if not nodes:
        # Valid empty diagram — Mermaid is happy with just the header.
        return "\n".join(lines)

    known_ids = {n.id for n in nodes}

    for node in nodes:
        nid = _short_id(node.id)
        label = _escape_label(node.title)
        cls = _STATUS_CLASS[node.status]
        lines.append(f'    {nid}["{label}"]:::{cls}')

    # parent_id edges (the implicit tree)
    for node in nodes:
        if node.parent_id and node.parent_id in known_ids:
            lines.append(f"    {_short_id(node.parent_id)} --> {_short_id(node.id)}")

    # explicit typed edges
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        if edge.src_node_id not in known_ids or edge.dst_node_id not in known_ids:
            continue
        # Avoid duplicating the parent edge that's already rendered above.
        if edge.kind == TaskEdgeKind.PARENT:
            continue
        key = (edge.src_node_id, edge.dst_node_id, edge.kind.value)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        arrow = _EDGE_RENDER[edge.kind]
        lines.append(
            f"    {_short_id(edge.src_node_id)} {arrow} {_short_id(edge.dst_node_id)}"
        )

    lines.extend(f"    {d}" for d in _CLASS_DEFS)
    return "\n".join(lines)
