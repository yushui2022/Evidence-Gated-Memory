"""Evidence-Gated Memory — provenance-first memory for high-stakes AI agents."""

from evidence_gated_memory.core.memory import EvidenceGatedMemory
from evidence_gated_memory.core.entities import ExtractedEntity
from evidence_gated_memory.core.models import (
    Claim,
    Evidence,
    Event,
    Fact,
    FactKind,
    Freshness,
    GateResult,
    Task,
    TaskEdge,
    TaskEdgeKind,
    TaskNode,
    TaskNodeStatus,
    TaskStatus,
)

__version__ = "0.2.0"

__all__ = [
    "EvidenceGatedMemory",
    "ExtractedEntity",
    "Event",
    "Evidence",
    "Claim",
    "Fact",
    "FactKind",
    "Freshness",
    "GateResult",
    "Task",
    "TaskEdge",
    "TaskEdgeKind",
    "TaskNode",
    "TaskNodeStatus",
    "TaskStatus",
]
