"""30-second ticket workflow demo for Evidence-Gated Memory.

Run:

    python examples/ticket_minimal.py

This demo uses an inline ticket schema to show how a non-refund domain can use
the same evidence -> gate -> fact/state pattern.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus, TaskStatus  # noqa: E402


TICKET_SCHEMA = {
    "name": "ticket",
    "description": "Support-ticket workflow schema for minimal demo.",
    "entities": [
        {
            "name": "ticket",
            "patterns": [r"TICK-[0-9]+"],
            "metadata_fields": ["ticket_id"],
        },
        {
            "name": "customer",
            "patterns": [r"CUST-[0-9]+"],
            "metadata_fields": ["customer_id"],
        },
        {
            "name": "escalation",
            "patterns": [r"ESC-[0-9]+"],
            "metadata_fields": ["escalation_id"],
        },
    ],
    "evidence_types": {
        "ticket_record": {
            "stale_after": "PT30M",
            "expired_after": "PT24H",
            "source_systems": ["ticket_api"],
            "risk": "medium",
        },
        "policy_article": {
            "stale_after": "P7D",
            "expired_after": "P30D",
            "source_systems": ["policy_db"],
            "risk": "medium",
        },
        "escalation_response": {
            "stale_after": "PT5M",
            "expired_after": "PT1H",
            "source_systems": ["escalation_api"],
            "risk": "high",
        },
    },
    "claim_types": {
        "resolution_eligibility": {
            "required_evidence": ["ticket_record", "policy_article"],
            "description": "Whether the ticket can be resolved under support policy.",
        },
        "escalation_completed": {
            "required_evidence": ["escalation_response"],
            "requires_fresh_evidence": True,
            "description": "Escalation has actually been completed.",
        },
    },
    "gates": [
        {
            "name": "resolution_requires_ticket_and_policy",
            "when": {"claim_type": "resolution_eligibility"},
            "require": {
                "evidence_types": ["ticket_record", "policy_article"],
                "freshness": "stale",
            },
            "suggested_action": "fetch ticket_record from ticket_api and policy_article from policy_db",
        },
        {
            "name": "escalation_requires_api_response",
            "when": {"claim_type": "escalation_completed"},
            "require": {
                "evidence_types": ["escalation_response"],
                "freshness": "fresh",
            },
            "suggested_action": "call escalation_api and attach a fresh escalation_response before declaring escalation complete",
        },
    ],
    "state_gates": [
        {
            "name": "triage_done_requires_ticket_record",
            "when": {"node_type": "triage", "to_status": "done"},
            "require": {"evidence_types": ["ticket_record"], "freshness": "stale"},
            "suggested_action": "fetch ticket_record from ticket_api before marking triage done",
        },
        {
            "name": "resolution_done_requires_ticket_and_policy",
            "when": {"node_type": "resolution_check", "to_status": "done"},
            "require": {
                "evidence_types": ["ticket_record", "policy_article"],
                "freshness": "stale",
            },
            "suggested_action": "fetch ticket_record and policy_article before marking resolution done",
        },
        {
            "name": "escalation_done_requires_response",
            "when": {"node_type": "escalation", "to_status": "done"},
            "require": {"evidence_types": ["escalation_response"], "freshness": "fresh"},
            "suggested_action": "attach a fresh escalation_response before marking escalation done",
        },
    ],
}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="egm_ticket_demo_") as tmp:
        memory = EvidenceGatedMemory(Path(tmp), TICKET_SCHEMA)
        try:
            task_id = "ticket:TICK-42"
            memory.create_task(
                task_id,
                "Resolve support ticket TICK-42",
                anchors={"ticket_id": "TICK-42", "customer_id": "CUST-9"},
                status=TaskStatus.IN_PROGRESS,
            )
            triage = memory.create_task_node(
                task_id,
                "triage",
                "Triage support ticket TICK-42",
                anchors={"ticket_id": "TICK-42"},
            )
            resolution = memory.create_task_node(
                task_id,
                "resolution_check",
                "Check whether TICK-42 can be resolved",
                parent_id=triage.id,
                anchors={"ticket_id": "TICK-42"},
            )
            escalation = memory.create_task_node(
                task_id,
                "escalation",
                "Escalate TICK-42 to policy desk",
                parent_id=resolution.id,
                anchors={"ticket_id": "TICK-42", "escalation_id": "ESC-7"},
            )

            _title("EGM Ticket Demo")

            _step("1. Resolution claim without evidence")
            early_resolution = memory.assert_fact(
                "TICK-42 can be resolved under support policy",
                claim_type="resolution_eligibility",
            )
            _print_assert("resolution_claim", early_resolution)

            _step("2. Add ticket and policy evidence")
            ticket_ref = memory.record_evidence(
                evidence_type="ticket_record",
                source="ticket_api",
                source_system="ticket_api",
                content=json.dumps(
                    {
                        "ticket_id": "TICK-42",
                        "customer_id": "CUST-9",
                        "status": "open",
                        "issue": "refund policy exception request",
                    },
                    sort_keys=True,
                ),
                summary="TICK-42 open refund policy exception request",
                metadata={"ticket_id": "TICK-42", "customer_id": "CUST-9"},
            )
            policy_ref = memory.record_evidence(
                evidence_type="policy_article",
                source="policy_db",
                source_system="policy_db",
                content="Policy P-17: refund policy exceptions require escalation approval.",
                summary="P-17 requires escalation approval",
                metadata={"policy_id": "P-17", "ticket_id": "TICK-42"},
            )
            resolution_ok = memory.assert_fact(
                "TICK-42 requires escalation approval before resolution",
                claim_type="resolution_eligibility",
                evidence=[ticket_ref, policy_ref],
                metadata={"ticket_id": "TICK-42"},
            )
            _print_assert("resolution_claim", resolution_ok)
            if resolution_ok.fact:
                memory.attach_fact_to_node(resolution.id, resolution_ok.fact.id)
            _print_transition(
                "triage_transition",
                memory.transition_node(triage.id, TaskNodeStatus.DONE, evidence=[ticket_ref]),
            )
            _print_transition(
                "resolution_transition",
                memory.transition_node(
                    resolution.id,
                    TaskNodeStatus.DONE,
                    evidence=[ticket_ref, policy_ref],
                ),
            )

            _step("3. Escalation DONE before API response")
            blocked_escalation = memory.transition_node(escalation.id, TaskNodeStatus.DONE)
            _print_transition("escalation_transition", blocked_escalation)

            _step("4. Add escalation API evidence")
            escalation_ref = memory.record_evidence(
                evidence_type="escalation_response",
                source="escalation_api",
                source_system="escalation_api",
                content=json.dumps(
                    {
                        "escalation_id": "ESC-7",
                        "ticket_id": "TICK-42",
                        "status": "approved",
                    },
                    sort_keys=True,
                ),
                summary="ESC-7 approved for TICK-42",
                metadata={"ticket_id": "TICK-42", "escalation_id": "ESC-7"},
            )
            escalation_done = memory.assert_fact(
                "Escalation ESC-7 for TICK-42 has been approved",
                claim_type="escalation_completed",
                evidence=[escalation_ref],
                metadata={"ticket_id": "TICK-42", "escalation_id": "ESC-7"},
            )
            _print_assert("escalation_claim", escalation_done)
            if escalation_done.fact:
                memory.attach_fact_to_node(escalation.id, escalation_done.fact.id)
            final_transition = memory.transition_node(
                escalation.id,
                TaskNodeStatus.DONE,
                evidence=[escalation_ref],
            )
            _print_transition("escalation_transition", final_transition)
            memory.update_task_status(task_id, TaskStatus.DONE)

            _step("5. Final gated context")
            print(_compact_context(memory.build_context(query="TICK-42", task_id=task_id, max_facts=4)))

            return 0 if escalation_done.accepted and final_transition.accepted else 1
        finally:
            memory.close()


def _title(text: str) -> None:
    print(text)
    print("=" * len(text))


def _step(text: str) -> None:
    print()
    print(f"[{text}]")


def _bool(value: object) -> str:
    return str(bool(value)).lower()


def _print_assert(label: str, result) -> None:
    print(f"{label}.accepted: {_bool(result.accepted)}")
    if result.fact:
        print(f"{label}.fact: {result.fact.id}")
    if not result.accepted:
        print(f"{label}.reason: {result.rejection_reason}")
        print(f"{label}.action: {result.suggested_action}")


def _print_transition(label: str, result) -> None:
    print(f"{label}.accepted: {_bool(result.accepted)}")
    print(f"{label}.status: {result.node.status.value}")
    if not result.accepted:
        print(f"{label}.reason: {result.rejection_reason}")
        print(f"{label}.action: {result.suggested_action}")


def _compact_context(context: str, max_lines: int = 24) -> str:
    lines = [line for line in context.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + ["..."])


if __name__ == "__main__":
    raise SystemExit(main())
