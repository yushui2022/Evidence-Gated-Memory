from evidence_gated_memory.adapters import (
    evidence_event_metadata,
    fact_context_metadata,
    gate_result_metadata,
)
from evidence_gated_memory.core.models import Evidence, Fact, FactKind, Freshness, GateResult, GateViolation


def test_evidence_event_metadata_uses_stable_keys() -> None:
    evidence = Evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        summary="refund complete",
    )

    metadata = evidence_event_metadata(
        evidence,
        task_id="refund:ORD-1",
        node_id="node_1",
        tool_name="refund_api",
        audit_id=12,
    )

    assert metadata == {
        "task_id": "refund:ORD-1",
        "node_id": "node_1",
        "tool_name": "refund_api",
        "evidence_id": evidence.id,
        "evidence_type": "refund_api_response",
        "source_system": "refund_api",
        "audit_id": 12,
    }


def test_fact_context_metadata_uses_stable_keys() -> None:
    fact = Fact(
        claim_id="claim_1",
        text="Refund is complete",
        claim_type="refund_completed",
        kind=FactKind.OBSERVED,
        evidence_refs=["ref_1"],
        node_id="node_1",
    )

    metadata = fact_context_metadata(
        fact,
        task_id="refund:ORD-1",
        freshness=Freshness.FRESH,
        blocked=False,
    )

    assert metadata == {
        "fact_id": fact.id,
        "claim_type": "refund_completed",
        "fact_kind": "observed",
        "task_id": "refund:ORD-1",
        "node_id": "node_1",
        "evidence_refs": ["ref_1"],
        "freshness": "fresh",
        "blocked": False,
    }


def test_gate_result_metadata_preserves_rejection_details() -> None:
    gate = GateResult(
        accepted=False,
        claim_id="claim_1",
        violations=[
            GateViolation(
                gate="refund_completion_requires_api_response",
                reason="missing required evidence type 'refund_api_response'",
                missing_evidence_types=["refund_api_response"],
                suggested_action="call refund_api",
            )
        ],
    )

    metadata = gate_result_metadata(gate)

    assert metadata["accepted"] is False
    assert metadata["claim_id"] == "claim_1"
    assert metadata["rejection_reason"] == "missing required evidence type 'refund_api_response'"
    assert metadata["suggested_action"] == "call refund_api"
    assert metadata["violations"][0]["missing_evidence_types"] == ["refund_api_response"]
