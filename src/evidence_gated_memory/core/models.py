"""Core data models for Evidence-Gated Memory.

The three-layer discipline:

- L0 Event       — raw, append-only record of what happened.
- L1a Observed   — structured claim grounded in exactly one Evidence ref.
- L1b Derived    — agent's inferred conclusion grounded in other Facts (cascades).
- L2 Context     — assembled from Facts, filtered by freshness/provenance.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Freshness(str, enum.Enum):
    """Evidence freshness tri-state. The heart of EGM."""

    FRESH = "fresh"                # within TTL, use directly
    STALE = "stale"                # past stale_after, usable with warning
    EXPIRED = "expired"            # past expired_after, hard-blocked
    UNKNOWN = "unknown"            # no TTL declared


class FactKind(str, enum.Enum):
    OBSERVED = "observed"   # L1a — grounded in a single Evidence
    DERIVED = "derived"     # L1b — grounded in other Facts


class TaskNodeStatus(str, enum.Enum):
    """Soft state for a task graph node. Not a strict workflow — transitions go through gates."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED = "skipped"


class TaskStatus(str, enum.Enum):
    """Top-level workflow status. Aggregated from child node states."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskEdgeKind(str, enum.Enum):
    """How two task nodes relate.

    `parent` is the implicit tree edge already carried on TaskNode.parent_id;
    it is mirrored here only when the caller explicitly creates an edge,
    so the edge table doesn't shadow the column. The other kinds are
    semantic relationships that don't fit a tree.
    """

    PARENT = "parent"           # structural containment
    DEPENDS_ON = "depends_on"   # A cannot start until B is DONE
    TRIGGERS = "triggers"       # finishing A schedules B
    PRODUCES = "produces"       # A's output is B's input
    BLOCKS = "blocks"           # A explicitly blocks B (e.g. compliance hold)


class Event(BaseModel):
    """L0 — raw append-only log entry. Never gated."""

    id: str = Field(default_factory=lambda: _new_id("evt"))
    created_at: datetime = Field(default_factory=_utcnow)
    role: str                      # "user" | "assistant" | "tool" | "system"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """L0 — a piece of raw evidence with provenance and TTL.

    The raw content is stored on disk at `refs/<id>.md`; this object is the index.
    """

    id: str = Field(default_factory=lambda: _new_id("ref"))
    created_at: datetime = Field(default_factory=_utcnow)
    observed_at: datetime = Field(default_factory=_utcnow)

    evidence_type: str                       # declared in domain schema
    source: str                              # e.g. "order_api", "crm", "human"
    source_system: Optional[str] = None      # used for trust judgments
    risk_level: str = "medium"               # low | medium | high

    summary: str = ""                        # short human-readable summary
    content_path: Optional[str] = None       # path to refs/<id>.md
    metadata: dict[str, Any] = Field(default_factory=dict)  # extracted entities, etc.

    # If null, falls back to schema-declared TTLs for this evidence_type.
    stale_after_seconds: Optional[int] = None
    expired_after_seconds: Optional[int] = None

    revoked_at: Optional[datetime] = None

    # Back-link to the task node this evidence is attached to, if any.
    # Set lazily by `attach_evidence_to_node`. Lets retrieval and
    # build_context light up `task_focus` (#25) without a join.
    node_id: Optional[str] = None


class Claim(BaseModel):
    """A proposed assertion. Becomes a Fact only after passing the gate."""

    id: str = Field(default_factory=lambda: _new_id("clm"))
    created_at: datetime = Field(default_factory=_utcnow)

    text: str
    claim_type: str                           # declared in domain schema
    kind: FactKind = FactKind.OBSERVED

    # For OBSERVED: list of Evidence ids.
    # For DERIVED: list of Fact ids it depends on.
    evidence_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)


class Fact(BaseModel):
    """A committed, gate-approved Claim. Eligible for prompt injection (subject to freshness)."""

    id: str = Field(default_factory=lambda: _new_id("fact"))
    created_at: datetime = Field(default_factory=_utcnow)

    claim_id: str
    text: str
    claim_type: str
    kind: FactKind

    evidence_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    # Back-link to the task node this fact is attached to, if any.
    # Set lazily by `attach_fact_to_node`. Symmetric with Evidence.node_id.
    node_id: Optional[str] = None


class TaskNode(BaseModel):
    """A node in the hard-anchor task graph.

    The TaskGraph is the structured object; Mermaid is one readable projection of it.
    Nodes are created explicitly by the orchestrator and carry hard anchors
    (order_id, ticket_id, ...) plus links to the evidence and facts behind them.
    """

    id: str = Field(default_factory=lambda: _new_id("node"))
    task_id: str
    node_type: str                                     # business-defined, e.g. "eligibility_check"
    title: str
    status: TaskNodeStatus = TaskNodeStatus.PENDING

    anchors: dict[str, str] = Field(default_factory=dict)   # {"order_id": "ORD-123"}
    parent_id: Optional[str] = None

    evidence_refs: list[str] = Field(default_factory=list)  # populated as evidence attaches
    fact_refs: list[str] = Field(default_factory=list)

    blocked_reason: Optional[str] = None
    suggested_action: Optional[str] = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    """The workflow-level object — a `task_id` made first-class.

    Until #32 the workflow only existed as a free-form string carried on each
    TaskNode. That works for grouping but hides the lifecycle: who opened the
    task, when, against which anchor, and where it stands overall. `Task`
    makes that explicit so build_context, audit, and retrieval can reason
    about whole workflows, not just nodes.

    Auto-created on first `create_task_node(task_id=...)` for back-compat.
    """

    id: str                                            # the same string used as TaskNode.task_id
    title: str = ""
    status: TaskStatus = TaskStatus.OPEN
    anchors: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskEdge(BaseModel):
    """Typed edge between two TaskNodes.

    Parent/child containment is already on `TaskNode.parent_id` — TaskEdge is
    for relationships that don't fit a tree: `depends_on`, `triggers`,
    `produces`, `blocks`. Edges are directional: `src -> dst`.
    """

    id: str = Field(default_factory=lambda: _new_id("edge"))
    task_id: str                                       # the workflow both nodes belong to
    src_node_id: str
    dst_node_id: str
    kind: TaskEdgeKind = TaskEdgeKind.DEPENDS_ON
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateViolation(BaseModel):
    """A specific reason a claim was rejected. Actionable, not just boolean."""

    gate: str                          # gate rule name
    reason: str                        # human-readable
    missing_evidence_types: list[str] = Field(default_factory=list)
    stale_refs: list[str] = Field(default_factory=list)
    expired_refs: list[str] = Field(default_factory=list)
    suggested_action: Optional[str] = None


class GateResult(BaseModel):
    """Result of running quality gates on a claim. The soul of EGM."""

    accepted: bool
    claim_id: str
    violations: list[GateViolation] = Field(default_factory=list)

    @property
    def rejection_reason(self) -> str:
        if self.accepted:
            return ""
        return "; ".join(v.reason for v in self.violations)

    @property
    def suggested_action(self) -> str:
        actions = [v.suggested_action for v in self.violations if v.suggested_action]
        return " | ".join(actions)


class AssertResult(BaseModel):
    """Result of the one-shot `assert_fact` API: propose → gate → commit."""

    accepted: bool
    claim: Claim
    gate: GateResult
    fact: Optional[Fact] = None

    @property
    def rejection_reason(self) -> str:
        return self.gate.rejection_reason

    @property
    def suggested_action(self) -> str:
        return self.gate.suggested_action
