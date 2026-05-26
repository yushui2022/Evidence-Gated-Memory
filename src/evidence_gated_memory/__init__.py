"""Evidence-Gated Memory — provenance-first memory for high-stakes AI agents."""

from evidence_gated_memory.core.memory import EvidenceGatedMemory
from evidence_gated_memory.core.models import (
    Claim,
    Evidence,
    Event,
    Fact,
    FactKind,
    Freshness,
    GateResult,
)

__version__ = "0.1.1"

__all__ = [
    "EvidenceGatedMemory",
    "Event",
    "Evidence",
    "Claim",
    "Fact",
    "FactKind",
    "Freshness",
    "GateResult",
]
