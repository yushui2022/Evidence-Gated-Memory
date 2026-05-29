"""30-second refund demo for Evidence-Gated Memory.

Run from a source checkout or an installed environment:

    python examples/refund_minimal.py

No API key is required. The point is to show EGM's core loop:
unsupported claim -> gate rejection -> missing evidence -> accepted fact/state.
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
from evidence_gated_memory.schemas.builtin import REFUND  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="egm_refund_demo_") as tmp:
        memory = EvidenceGatedMemory(Path(tmp), REFUND)
        try:
            task_id = "refund:ORD-123"
            eligibility = memory.create_task_node(
                task_id,
                "eligibility_check",
                "Check refund eligibility for ORD-123",
                anchors={"order_id": "ORD-123", "customer_id": "CUST-42"},
            )
            completion = memory.create_task_node(
                task_id,
                "refund_completion",
                "Execute refund for ORD-123",
                parent_id=eligibility.id,
                anchors={"order_id": "ORD-123", "refund_id": "REF-9001"},
            )

            _title("EGM Refund Demo")

            _step("1. Unsupported completion claim")
            premature = memory.assert_fact(
                "Refund for ORD-123 has been completed",
                claim_type="refund_completed",
            )
            _print_assert("completion_claim", premature)

            _step("2. Add order and policy evidence")
            order_ref = memory.record_evidence(
                evidence_type="order_record",
                source="order_api",
                source_system="order_api",
                content=json.dumps(
                    {
                        "order_id": "ORD-123",
                        "customer_id": "CUST-42",
                        "status": "PAID",
                        "amount": 199.0,
                    },
                    sort_keys=True,
                ),
                summary="ORD-123 status=PAID amount=199.0",
                metadata={"order_id": "ORD-123", "customer_id": "CUST-42"},
            )
            policy_ref = memory.record_evidence(
                evidence_type="refund_policy",
                source="policy_db",
                source_system="policy_db",
                content="Refund policy v2026-01: paid orders are refundable within 14 days.",
                summary="14-day refund policy",
                metadata={"policy_version": "v2026-01"},
            )
            eligible = memory.assert_fact(
                "Order ORD-123 is eligible for refund under the 14-day policy",
                claim_type="refund_eligibility",
                evidence=[order_ref, policy_ref],
                metadata={"order_id": "ORD-123"},
            )
            _print_assert("eligibility_claim", eligible)
            if eligible.fact:
                memory.attach_fact_to_node(eligibility.id, eligible.fact.id)
            eligibility_done = memory.transition_node(
                eligibility.id,
                TaskNodeStatus.DONE,
                evidence=[order_ref, policy_ref],
            )
            _print_transition("eligibility_transition", eligibility_done)

            _step("3. DONE transition before execution evidence")
            blocked_done = memory.transition_node(completion.id, TaskNodeStatus.DONE)
            _print_transition("completion_transition", blocked_done)

            _step("4. Add refund API evidence")
            refund_ref = memory.record_evidence(
                evidence_type="refund_api_response",
                source="refund_api",
                source_system="refund_api",
                content=json.dumps(
                    {
                        "refund_id": "REF-9001",
                        "order_id": "ORD-123",
                        "status": "success",
                        "amount": 199.0,
                    },
                    sort_keys=True,
                ),
                summary="refund REF-9001 status=success amount=199.0",
                metadata={"refund_id": "REF-9001", "order_id": "ORD-123"},
            )
            completed = memory.assert_fact(
                "Refund for ORD-123 has been executed via REF-9001",
                claim_type="refund_completed",
                evidence=[refund_ref],
                metadata={"order_id": "ORD-123", "refund_id": "REF-9001"},
            )
            _print_assert("completion_claim", completed)
            if completed.fact:
                memory.attach_fact_to_node(completion.id, completed.fact.id)
            completion_done = memory.transition_node(
                completion.id,
                TaskNodeStatus.DONE,
                evidence=[refund_ref],
            )
            _print_transition("completion_transition", completion_done)
            memory.update_task_status(task_id, TaskStatus.DONE)

            _step("5. Final gated context")
            print(_compact_context(memory.build_context(query="ORD-123", task_id=task_id, max_facts=4)))

            _step("6. Audit tail")
            for entry in memory.audit_log(limit=6):
                print(f"audit: {entry['event_type']}")

            return 0 if completed.accepted and completion_done.accepted else 1
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
