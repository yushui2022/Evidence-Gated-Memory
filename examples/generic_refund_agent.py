"""Generic agent-loop integration demo for Evidence-Gated Memory.

Run:

    python examples/generic_refund_agent.py

No API key is required. This is not a LangChain/LangGraph adapter. It shows the
plain Python integration points every adapter eventually needs:

  tool output -> record_evidence()
  conclusion  -> assert_fact()
  state change -> transition_node()
  next prompt -> build_context()
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus, TaskStatus  # noqa: E402
from evidence_gated_memory.schemas.builtin import REFUND  # noqa: E402


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    source_system: str
    evidence_type: str
    content: dict[str, object] | str
    summary: str
    metadata: dict[str, str]


class RefundLoop:
    def __init__(self, workspace: Path) -> None:
        self.memory = EvidenceGatedMemory(workspace, REFUND)
        self.task_id = "refund:ORD-777"
        self.eligibility = self.memory.create_task_node(
            self.task_id,
            "eligibility_check",
            "Check refund eligibility for ORD-777",
            anchors={"order_id": "ORD-777", "customer_id": "CUST-77"},
        )
        self.completion = self.memory.create_task_node(
            self.task_id,
            "refund_completion",
            "Execute refund for ORD-777",
            parent_id=self.eligibility.id,
            anchors={"order_id": "ORD-777", "refund_id": "REF-777"},
        )

    def close(self) -> None:
        self.memory.close()

    def run(self) -> bool:
        print("EGM Generic Agent Loop")
        print("======================")

        self._before_llm("initial prompt")

        print("\n[1. Agent proposes completion too early]")
        early = self.memory.assert_fact(
            "Refund for ORD-777 has been executed via REF-777",
            claim_type="refund_completed",
        )
        self._print_gate("early_completion_claim", early.accepted, early.rejection_reason, early.suggested_action)

        print("\n[2. Tools return order and policy evidence]")
        order_ref = self._record_tool_result(call_order_api("ORD-777"))
        policy_ref = self._record_tool_result(call_policy_db())
        eligibility = self.memory.assert_fact(
            "Order ORD-777 is eligible for refund under the current policy",
            claim_type="refund_eligibility",
            evidence=[order_ref, policy_ref],
            metadata={"order_id": "ORD-777"},
        )
        self._print_gate("eligibility_claim", eligibility.accepted, eligibility.rejection_reason, eligibility.suggested_action)
        if eligibility.fact:
            self.memory.attach_fact_to_node(self.eligibility.id, eligibility.fact.id)

        eligibility_done = self.memory.transition_node(
            self.eligibility.id,
            TaskNodeStatus.DONE,
            evidence=[order_ref, policy_ref],
        )
        self._print_gate(
            "eligibility_transition",
            eligibility_done.accepted,
            eligibility_done.rejection_reason,
            eligibility_done.suggested_action,
        )

        print("\n[3. State gate blocks DONE before refund API evidence]")
        blocked = self.memory.transition_node(self.completion.id, TaskNodeStatus.DONE)
        self._print_gate("completion_transition", blocked.accepted, blocked.rejection_reason, blocked.suggested_action)

        print("\n[4. Tool returns refund execution evidence]")
        refund_ref = self._record_tool_result(call_refund_api("ORD-777", "REF-777"))
        completed = self.memory.assert_fact(
            "Refund for ORD-777 has been executed via REF-777",
            claim_type="refund_completed",
            evidence=[refund_ref],
            metadata={"order_id": "ORD-777", "refund_id": "REF-777"},
        )
        self._print_gate("completion_claim", completed.accepted, completed.rejection_reason, completed.suggested_action)
        if completed.fact:
            self.memory.attach_fact_to_node(self.completion.id, completed.fact.id)

        completion_done = self.memory.transition_node(
            self.completion.id,
            TaskNodeStatus.DONE,
            evidence=[refund_ref],
        )
        self._print_gate(
            "completion_transition",
            completion_done.accepted,
            completion_done.rejection_reason,
            completion_done.suggested_action,
        )
        if completion_done.accepted:
            self.memory.update_task_status(self.task_id, TaskStatus.DONE)

        self._before_llm("next prompt")

        print("\n[5. Audit export preview]")
        for row in self.memory.audit_log(limit=5):
            print(f"audit: {row['event_type']}")

        return bool(completed.accepted and completion_done.accepted)

    def _record_tool_result(self, result: ToolResult):
        content = result.content if isinstance(result.content, str) else json.dumps(result.content, sort_keys=True)
        ref = self.memory.record_evidence(
            evidence_type=result.evidence_type,
            source=result.tool_name,
            source_system=result.source_system,
            content=content,
            summary=result.summary,
            metadata=result.metadata,
        )
        print(f"record_evidence: {result.tool_name} -> {ref.id}")
        return ref

    def _before_llm(self, label: str) -> None:
        context = self.memory.build_context(query="ORD-777", task_id=self.task_id, max_facts=4)
        lines = [line for line in context.splitlines() if line.strip()]
        print(f"build_context.{label}.lines: {len(lines)}")
        print(f"build_context.{label}.has_task_map: {str('<task_map>' in context).lower()}")

    @staticmethod
    def _print_gate(label: str, accepted: bool, reason: str | None, action: str | None) -> None:
        print(f"{label}.accepted: {str(bool(accepted)).lower()}")
        if not accepted:
            print(f"{label}.reason: {reason}")
            print(f"{label}.action: {action}")


def call_order_api(order_id: str) -> ToolResult:
    return ToolResult(
        tool_name="order_api",
        source_system="order_api",
        evidence_type="order_record",
        content={"order_id": order_id, "customer_id": "CUST-77", "status": "PAID", "amount": 88.5},
        summary=f"{order_id} status=PAID amount=88.5",
        metadata={"order_id": order_id, "customer_id": "CUST-77"},
    )


def call_policy_db() -> ToolResult:
    return ToolResult(
        tool_name="policy_db",
        source_system="policy_db",
        evidence_type="refund_policy",
        content="Policy v2026-02: paid orders are refundable within 14 days.",
        summary="14-day paid-order refund policy",
        metadata={"policy_version": "v2026-02"},
    )


def call_refund_api(order_id: str, refund_id: str) -> ToolResult:
    return ToolResult(
        tool_name="refund_api",
        source_system="refund_api",
        evidence_type="refund_api_response",
        content={"order_id": order_id, "refund_id": refund_id, "status": "success", "amount": 88.5},
        summary=f"{refund_id} status=success amount=88.5",
        metadata={"order_id": order_id, "refund_id": refund_id},
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="egm_generic_loop_") as tmp:
        loop = RefundLoop(Path(tmp))
        try:
            return 0 if loop.run() else 1
        finally:
            loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
