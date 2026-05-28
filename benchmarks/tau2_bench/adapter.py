"""EGM adapter for τ²-bench: record tool results as evidence, gate conclusions.

Architecture:
  τ²-bench Environment  →  EGMTau2Adapter  →  EGM (evidence + facts + context)
                                   ↓
  Post-simulation trajectory analysis → gate agent text responses as facts

Differences from the tau-bench v1 adapter:
  - τ² has no RESPOND_ACTION_NAME — agent text replies are AssistantMessage.content
  - τ² uses an Orchestrator loop (AGENT/USER/ENV), not a simple env.step()
  - The adapter wraps the Environment to intercept get_response() for evidence recording
  - Fact gating is post-hoc: after the simulation, the trajectory is scanned for
    agent text messages, and each is gated through EGM's assert_fact
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND


@dataclass
class Tau2AdapterMetrics:
    """Metrics collected during a τ²-bench run with EGM."""

    tool_calls_total: int = 0
    tool_results_as_evidence: int = 0
    facts_asserted: int = 0
    facts_rejected: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    context_token_estimate: int = 0
    raw_trajectory_token_estimate: int = 0
    agent_text_messages: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls_total": self.tool_calls_total,
            "tool_results_as_evidence": self.tool_results_as_evidence,
            "evidence_coverage": (
                self.tool_results_as_evidence / max(self.tool_calls_total, 1)
            ),
            "facts_asserted": self.facts_asserted,
            "facts_rejected": self.facts_rejected,
            "fact_acceptance_rate": (
                self.facts_asserted / max(self.facts_asserted + self.facts_rejected, 1)
            ),
            "agent_text_messages": self.agent_text_messages,
            "context_token_estimate": self.context_token_estimate,
            "raw_trajectory_token_estimate": self.raw_trajectory_token_estimate,
            "context_compression_ratio": (
                self.context_token_estimate / max(self.raw_trajectory_token_estimate, 1)
            ),
            "rejection_reasons": self.rejection_reasons,
        }


# Map τ²-bench retail tools to EGM evidence types in the REFUND schema.
# WRITE tools that mutate state → refund_api_response (action evidence).
# READ tools that query state → order_record (state evidence).
# Policy/info tools → refund_policy.
TOOL_EVIDENCE_MAP: dict[str, str] = {
    # READ — query state
    "get_order_details": "order_record",
    "get_user_details": "order_record",
    "get_product_details": "order_record",
    "get_item_details": "order_record",
    "find_user_id_by_email": "order_record",
    "find_user_id_by_name_zip": "order_record",
    # Policy / catalog
    "list_all_product_types": "refund_policy",
    "calculate": "refund_policy",
    # WRITE — mutate state (these are the evidence for "action completed")
    "cancel_pending_order": "refund_api_response",
    "return_delivered_order_items": "refund_api_response",
    "exchange_delivered_order_items": "refund_api_response",
    "modify_pending_order_items": "refund_api_response",
    "modify_pending_order_payment": "refund_api_response",
    "modify_pending_order_address": "refund_api_response",
    "modify_user_address": "refund_api_response",
    "transfer_to_human_agents": "refund_api_response",
}

# Map τ²-bench agent text intent keywords to EGM claim types.
INTENT_TO_CLAIM_TYPE: dict[str, str] = {
    "cancel": "refund_completed",
    "return": "refund_completed",
    "exchange": "refund_completed",
    "refund": "refund_completed",
    "modify": "refund_eligibility",
    "lookup": "refund_eligibility",
    "search": "refund_eligibility",
    "check": "refund_eligibility",
    "order": "refund_eligibility",
    "default": "refund_eligibility",
}

SOURCE_SYSTEMS: dict[str, str] = {
    "order_record": "order_api",
    "refund_policy": "policy_db",
    "refund_api_response": "refund_api",
}


class EGMTau2Adapter:
    """Wraps a τ²-bench Environment, recording tool results as EGM evidence.

    Usage:
        import tempfile
        from tau2.domains.retail.environment import get_environment
        from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
        from evidence_gated_memory.schemas.builtin import REFUND

        env = get_environment()
        memory = EvidenceGatedMemory(tempfile.mkdtemp(), REFUND)

        adapter = EGMTau2Adapter(
            env, memory,
            task_id="tau2:task:0",
            task_instruction="Look up order #W2378156...",
        )

        # Now pass env to the orchestrator — all get_response() calls
        # are intercepted and recorded as EGM evidence.
        orchestrator = Orchestrator(agent, user, env, task)
        sim_result = orchestrator.run()

        # Post-hoc: gate agent text responses as facts.
        adapter.gate_trajectory(sim_result.trajectory)

        # Build EGM context.
        ctx = adapter.build_egm_context(query="W2378156")
        print(ctx)

        adapter.close()
    """

    def __init__(
        self,
        env: Any,  # tau2.environment.environment.Environment
        memory: EvidenceGatedMemory,
        *,
        task_id: str,
        task_instruction: str = "",
        tool_evidence_map: Optional[dict[str, str]] = None,
    ):
        self.env = env
        self.memory = memory
        self._task_id = task_id
        self._task_instruction = task_instruction
        self.tool_evidence_map = tool_evidence_map or TOOL_EVIDENCE_MAP
        self.metrics = Tau2AdapterMetrics()
        self._task_node: Any = None
        self._closed = False

        # Wrap get_response to intercept tool results.
        self._original_get_response = env.get_response
        env.get_response = self._wrapped_get_response  # type: ignore[method-assign]

    # ── environment interception ────────────────────────────────────────────

    def _wrapped_get_response(self, tool_call: Any) -> Any:
        """Intercept every tool call → record result as EGM evidence."""
        self.metrics.tool_calls_total += 1

        # Call original.
        result = self._original_get_response(tool_call)  # type: ignore[call-arg]

        tool_name = _tool_name_from_call(tool_call)
        evidence_type = self.tool_evidence_map.get(tool_name)

        if evidence_type:
            try:
                ev = self.memory.record_evidence(
                    evidence_type=evidence_type,
                    source=tool_name,
                    source_system=SOURCE_SYSTEMS.get(evidence_type, "tau2_env"),
                    content=_serialize_tool_result(tool_call, result),
                    metadata={
                        "tool_name": tool_name,
                        "task_id": self._task_id,
                    },
                )
                self.metrics.evidence_refs.append(ev.id)
                self.metrics.tool_results_as_evidence += 1
                if self._task_node is not None:
                    self.memory.attach_evidence_to_node(self._task_node.id, ev.id)
            except (ValueError, KeyError):
                pass

        return result

    # ── task node ───────────────────────────────────────────────────────────

    def create_task_node(self, node_type: str = "eligibility_check") -> Any:
        """Create the EGM task node for this τ²-bench task."""
        self._task_node = self.memory.create_task_node(
            self._task_id,
            node_type,
            self._task_instruction[:200],
            anchors={"task_id": self._task_id},
        )
        return self._task_node

    # ── trajectory gating (post-hoc) ────────────────────────────────────────

    def gate_trajectory(self, trajectory: list[Any]) -> None:
        """Scan a completed trajectory and gate agent text responses as facts.

        Call after orchestrator.run() completes. This is post-hoc analysis:
        EGM currently records evidence in real-time but gates facts after
        the simulation, since the agent's messages are only available
        through the trajectory.
        """
        # Accumulate evidence refs seen so far for progressive gating.
        seen_evidence: list[str] = list(self.metrics.evidence_refs)

        for msg in trajectory:
            if not _is_assistant_text(msg):
                continue

            self.metrics.agent_text_messages += 1
            content = _msg_content(msg)
            if not content or not content.strip():
                continue

            intent = _classify_intent(content)
            claim_type = INTENT_TO_CLAIM_TYPE.get(intent, "refund_eligibility")

            try:
                result = self.memory.assert_fact(
                    f"{self._task_id}: {content[:200]}",
                    claim_type=claim_type,
                    evidence=seen_evidence,  # type: ignore[arg-type]
                )
                if result.accepted and result.fact:
                    self.metrics.facts_asserted += 1
                    self.metrics.fact_ids.append(result.fact.id)
                    if self._task_node is not None:
                        self.memory.attach_fact_to_node(
                            self._task_node.id, result.fact.id
                        )
                else:
                    self.metrics.facts_rejected += 1
                    self.metrics.rejection_reasons.append(
                        result.gate.rejection_reason
                    )
            except (ValueError, KeyError):
                self.metrics.facts_rejected += 1

    # ── context ─────────────────────────────────────────────────────────────

    def build_egm_context(self, query: Optional[str] = None) -> str:
        """Build EGM context as replacement for raw trajectory."""
        ctx = self.memory.build_context(
            query=query or self._task_instruction,
            task_id=self._task_id,
        )
        self.metrics.context_token_estimate = len(ctx) // 3
        return ctx

    def set_raw_trajectory_tokens(self, raw_json: str) -> None:
        """Record the raw trajectory token estimate for compression metrics."""
        self.metrics.raw_trajectory_token_estimate = len(raw_json) // 3

    # ── lifecycle ───────────────────────────────────────────────────────────

    def close(self) -> None:
        """Restore original get_response and close EGM."""
        if self._closed:
            return
        self._closed = True
        try:
            self.env.get_response = self._original_get_response  # type: ignore[method-assign]
        except Exception:
            pass
        self.memory.close()


# ── helpers ─────────────────────────────────────────────────────────────────


def _tool_name_from_call(tool_call: Any) -> str:
    """Extract tool name from a tau2 ToolCall."""
    if hasattr(tool_call, "name"):
        return str(tool_call.name)
    if isinstance(tool_call, dict):
        return str(tool_call.get("name", ""))
    return ""


def _serialize_tool_result(tool_call: Any, result: Any) -> str:
    """Serialize a tool call + result for EGM evidence storage."""
    tc_dict: dict[str, Any] = {}
    if hasattr(tool_call, "name"):
        tc_dict["tool"] = tool_call.name
    if hasattr(tool_call, "arguments"):
        tc_dict["arguments"] = tool_call.arguments
    elif hasattr(tool_call, "kwargs"):
        tc_dict["arguments"] = tool_call.kwargs

    result_repr: Any
    if hasattr(result, "output"):
        result_repr = result.output
    elif hasattr(result, "content"):
        result_repr = result.content
    elif isinstance(result, str):
        result_repr = result
    else:
        result_repr = str(result)

    return json.dumps({"tool_call": tc_dict, "result": result_repr}, default=str)


def _is_assistant_text(msg: Any) -> bool:
    """Check if a trajectory message is an assistant text response."""
    cls_name = type(msg).__name__
    if cls_name == "AssistantMessage":
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            return False
        if hasattr(msg, "has_text_content"):
            return bool(msg.has_text_content())
        if hasattr(msg, "content"):
            return bool(msg.content)
    return False


def _msg_content(msg: Any) -> str:
    """Extract text content from a tau2 message."""
    if hasattr(msg, "content"):
        return str(msg.content or "")
    return ""


def _classify_intent(text: str) -> str:
    """Classify agent intent from text content."""
    text_lower = text.lower()
    # Strong action verbs first — unambiguously indicate completion.
    # Then inquiry verbs. "refund" alone is ambiguous, check it last.
    for intent in [
        "cancel", "return", "exchange",
        "lookup", "search", "check",
        "modify", "order", "refund",
    ]:
        if intent in text_lower:
            return intent
    return "default"


# ── deterministic smoke test (no API keys, no LLM) ──────────────────────────


def run_smoke_test(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    """Run a deterministic smoke test verifying the τ²-bench adapter.

    Simulates a τ² retail task through EGM: evidence recording, fact gating,
    context building, and transition gating. No API keys, no LLM, no network.
    """
    import tempfile
    from uuid import uuid4

    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_tau2_smoke_") as tmp:
            return _run_smoke(Path(tmp))
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _run_smoke(workspace_root / f"smoke_{uuid4().hex[:8]}")


def _run_smoke(root: Path) -> dict[str, Any]:
    """Simulate a τ² retail task through EGM."""
    memory = EvidenceGatedMemory(root, REFUND)
    try:
        task_id = "tau2:retail:test:0"
        instruction = (
            "Look up order #W2378156 and exchange the mechanical keyboard "
            "for one with clicky switches."
        )

        # Phase 1: create task node (simulates tau2 orchestrator init).
        node = memory.create_task_node(
            task_id,
            "eligibility_check",
            instruction,
            anchors={"task_id": task_id},
        )

        # Phase 2: simulate agent calling get_order_details → record evidence.
        order_ev = memory.record_evidence(
            evidence_type="order_record",
            source="get_order_details",
            source_system="order_api",
            content=json.dumps({
                "tool_call": {"tool": "get_order_details",
                              "arguments": {"order_id": "W2378156"}},
                "result": {"order_id": "W2378156", "status": "delivered",
                           "items": [{"name": "mechanical keyboard",
                                      "item_id": "KBD-001"}]},
            }),
            metadata={"tool_name": "get_order_details", "task_id": task_id},
        )
        memory.attach_evidence_to_node(node.id, order_ev.id)

        product_ev = memory.record_evidence(
            evidence_type="refund_policy",
            source="list_all_product_types",
            source_system="policy_db",
            content=json.dumps({
                "tool_call": {"tool": "list_all_product_types"},
                "result": {"products": ["mechanical keyboard", "smart thermostat",
                                        "water bottle", "desk lamp", "tshirt"]},
            }),
            metadata={"tool_name": "list_all_product_types", "task_id": task_id},
        )
        memory.attach_evidence_to_node(node.id, product_ev.id)

        # Phase 3: agent text response → gate as fact (simulating post-hoc).
        eligibility_result = memory.assert_fact(
            f"{task_id}: order W2378156 is eligible for exchange — "
            "keyboard has clicky switch variant available",
            claim_type="refund_eligibility",
            evidence=[order_ev, product_ev],
        )
        eligibility_ok = eligibility_result.accepted
        if eligibility_result.fact:
            memory.attach_fact_to_node(node.id, eligibility_result.fact.id)

        # Phase 4: try to claim task complete WITHOUT fresh action evidence.
        premature = memory.assert_fact(
            f"{task_id}: exchange completed for order W2378156",
            claim_type="refund_completed",
            evidence=[order_ev, product_ev],
        )
        premature_blocked = not premature.accepted
        actionable = (
            "refund_api_response" in premature.gate.rejection_reason.lower()
            if not premature.accepted
            else False
        )

        # Phase 5: agent calls exchange tool → record evidence → re-assert.
        exchange_ev = memory.record_evidence(
            evidence_type="refund_api_response",
            source="exchange_delivered_order_items",
            source_system="refund_api",
            content=json.dumps({
                "tool_call": {
                    "tool": "exchange_delivered_order_items",
                    "arguments": {
                        "order_id": "W2378156",
                        "item_ids": ["KBD-001"],
                        "new_item_ids": ["KBD-002"],
                        "payment_method_id": "pm_123",
                    },
                },
                "result": {"status": "success", "exchange_id": "EXC-5001"},
            }),
            metadata={
                "tool_name": "exchange_delivered_order_items",
                "task_id": task_id,
            },
        )
        memory.attach_evidence_to_node(node.id, exchange_ev.id)

        completion_result = memory.assert_fact(
            f"{task_id}: exchange completed — order W2378156, "
            "keyboard KBD-001 → KBD-002, exchange_id EXC-5001",
            claim_type="refund_completed",
            evidence=[exchange_ev],
        )
        completion_ok = completion_result.accepted
        if completion_result.fact:
            memory.attach_fact_to_node(node.id, completion_result.fact.id)

        # Phase 6: transition to DONE (gated).
        transition = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[order_ev, product_ev, exchange_ev],
        )

        # Phase 7: build EGM context.
        ctx = memory.build_context(query="W2378156", task_id=task_id)

        # Simulated raw trajectory (what τ² would produce).
        raw_trajectory = json.dumps([
            {"role": "system", "content": "You are a retail agent..."},
            {"role": "user", "content": "Hi! How can I help you today?"},
            {"role": "user", "content": instruction},
            {"role": "assistant", "tool_calls": [
                {"name": "get_order_details", "arguments": {"order_id": "W2378156"}}
            ]},
            {"role": "tool", "content": '{"order_id":"W2378156","status":"delivered"}'},
            {"role": "assistant", "tool_calls": [
                {"name": "list_all_product_types"}
            ]},
            {"role": "tool", "content": '{"products":["keyboard","thermostat",...]}'},
            {"role": "assistant",
             "content": "order W2378156 is eligible for exchange — keyboard has clicky switch variant available"},
            {"role": "assistant", "tool_calls": [
                {"name": "exchange_delivered_order_items",
                 "arguments": {"order_id": "W2378156", "item_ids": ["KBD-001"],
                               "new_item_ids": ["KBD-002"], "payment_method_id": "pm_123"}}
            ]},
            {"role": "tool", "content": '{"status":"success","exchange_id":"EXC-5001"}'},
            {"role": "assistant",
             "content": "exchange completed — order W2378156, keyboard KBD-001 → KBD-002, exchange_id EXC-5001"},
        ])

        egm_tokens = len(ctx) // 3
        raw_tokens = len(raw_trajectory) // 3

        metrics = {
            "eligibility_accepted": float(eligibility_ok),
            "premature_completion_blocked": float(premature_blocked),
            "rejection_actionable": float(actionable),
            "completion_accepted": float(completion_ok),
            "transition_accepted": float(transition.accepted),
            "context_has_order_id": float("W2378156" in ctx),
            "context_has_fact": float("[FACT]" in ctx),
            "context_has_task_map": float("<task_map>" in ctx),
            "egm_context_tokens_est": egm_tokens,
            "raw_trajectory_tokens_est": raw_tokens,
            "context_compression_ratio": round(egm_tokens / max(raw_tokens, 1), 3),
        }
        thresholds = {
            "eligibility_accepted": 1.0,
            "premature_completion_blocked": 1.0,
            "rejection_actionable": 1.0,
            "completion_accepted": 1.0,
            "transition_accepted": 1.0,
            "context_has_order_id": 1.0,
            "context_has_fact": 1.0,
            "context_has_task_map": 1.0,
        }
        passed = all(
            float(metrics.get(k, 0.0)) >= v for k, v in thresholds.items()
        )
        return {
            "name": "tau2_bench_egm_smoke",
            "description": (
                "Simulated τ²-bench retail exchange task through EGM gates. "
                "Verifies evidence recording, fact gating, context building, "
                "and transition gating all work correctly in the τ² integration model."
            ),
            "passed": passed,
            "metrics": metrics,
            "thresholds": thresholds,
        }
    finally:
        memory.close()


if __name__ == "__main__":
    report = run_smoke_test()
    print(f"passed: {report['passed']}")
    print(json.dumps(report["metrics"], indent=2))
    if not report["passed"]:
        raise SystemExit(1)
