"""Stable metadata envelopes for framework adapters.

These helpers do not integrate with a framework by themselves. They make the
metadata shape stable so LangChain, LangGraph, OpenAI Agents, or a plain Python
loop can preserve the same provenance fields.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from evidence_gated_memory.core.models import Evidence, Fact, Freshness, GateResult, TransitionGateResult


def evidence_event_metadata(
    evidence: Evidence,
    *,
    task_id: Optional[str] = None,
    node_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    audit_id: Optional[int] = None,
) -> dict[str, Any]:
    """Metadata for a tool-output or callback event that produced evidence."""
    return _drop_none(
        {
            "task_id": task_id,
            "node_id": node_id or evidence.node_id,
            "tool_name": tool_name or evidence.source,
            "evidence_id": evidence.id,
            "evidence_type": evidence.evidence_type,
            "source_system": evidence.source_system,
            "audit_id": audit_id,
        }
    )


def fact_context_metadata(
    fact: Fact,
    *,
    task_id: Optional[str] = None,
    node_id: Optional[str] = None,
    freshness: Optional[Union[Freshness, str]] = None,
    blocked: bool = False,
) -> dict[str, Any]:
    """Metadata for a retrieved fact/context item."""
    freshness_value = freshness.value if isinstance(freshness, Freshness) else freshness
    return _drop_none(
        {
            "fact_id": fact.id,
            "claim_type": fact.claim_type,
            "fact_kind": fact.kind.value,
            "task_id": task_id,
            "node_id": node_id or fact.node_id,
            "evidence_refs": list(fact.evidence_refs),
            "freshness": freshness_value,
            "blocked": blocked,
        }
    )


def gate_result_metadata(gate: Union[GateResult, TransitionGateResult]) -> dict[str, Any]:
    """Metadata for an evidence gate or state-transition gate result."""
    payload: dict[str, Any] = {
        "accepted": gate.accepted,
        "rejection_reason": gate.rejection_reason,
        "suggested_action": gate.suggested_action,
        "violations": [violation.model_dump(mode="json") for violation in gate.violations],
    }
    if isinstance(gate, GateResult):
        payload["claim_id"] = gate.claim_id
    else:
        payload.update(
            {
                "node_id": gate.node_id,
                "from_status": gate.from_status.value,
                "to_status": gate.to_status.value,
            }
        )
    return payload


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
