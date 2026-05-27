"""EGM adapter for tau-bench: record tool results as evidence, gate conclusions.

Architecture:
  tau-bench Env  →  EGMTauAdapter  →  EGM (evidence + facts + context)
                         ↓
  tau-bench Agent (uses EGM context instead of raw message history)

Every tau-bench tool call produces a result. EGMTauAdapter records that result
as EGM evidence (refs/*.md + SQLite), indexed by task_id and tool name. When the
agent responds with a conclusion, it is gated through EGM's assert_fact — if the
required evidence is missing or stale, the conclusion is rejected with an
actionable message.

The A/B comparison measures:
  1. Task pass rate (tau-bench reward)
  2. Context token count (EGM vs. raw message history)
  3. Evidence coverage (what fraction of tool results are recorded as evidence)
  4. False-done rate (how often the agent claims done without sufficient evidence)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND


@dataclass
class AdapterMetrics:
    """Metrics collected during a tau-bench run with EGM."""

    tool_calls_recorded: int = 0
    tool_results_as_evidence: int = 0
    facts_asserted: int = 0
    facts_rejected: int = 0
    evidence_refs: List[str] = field(default_factory=list)
    fact_ids: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    context_token_estimate: int = 0
    raw_messages_token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls_recorded": self.tool_calls_recorded,
            "tool_results_as_evidence": self.tool_results_as_evidence,
            "facts_asserted": self.facts_asserted,
            "facts_rejected": self.facts_rejected,
            "evidence_coverage": (
                self.tool_results_as_evidence / max(self.tool_calls_recorded, 1)
            ),
            "fact_acceptance_rate": (
                self.facts_asserted / max(self.facts_asserted + self.facts_rejected, 1)
            ),
            "context_token_estimate": self.context_token_estimate,
            "raw_messages_token_estimate": self.raw_messages_token_estimate,
            "context_compression_ratio": (
                self.context_token_estimate / max(self.raw_messages_token_estimate, 1)
            ),
        }


# Map tau-bench retail tools to EGM evidence types in the REFUND schema
TOOL_TO_EVIDENCE_TYPE: dict[str, str] = {
    "get_order_details": "order_record",
    "get_user_details": "order_record",  # closest match in REFUND schema
    "get_product_details": "order_record",
    "find_user_id_by_email": "order_record",
    "find_user_id_by_name_zip": "order_record",
    "cancel_pending_order": "refund_api_response",
    "return_delivered_order_items": "refund_api_response",
    "exchange_delivered_order_items": "refund_api_response",
    "modify_pending_order_items": "refund_api_response",
    "modify_pending_order_payment": "refund_api_response",
    "modify_pending_order_address": "refund_api_response",
    "modify_user_address": "refund_api_response",
    "list_all_product_types": "refund_policy",
    "calculate": "refund_policy",
    "transfer_to_human_agents": "refund_api_response",
}

# Map tau-bench respond intents to EGM claim types
RESPOND_TO_CLAIM_TYPE: dict[str, str] = {
    "cancel": "refund_completed",
    "return": "refund_completed",
    "exchange": "refund_completed",
    "refund": "refund_completed",
    "modify": "refund_eligibility",
    "lookup": "refund_eligibility",
    "default": "refund_eligibility",
}


class EGMTauAdapter:
    """Wraps a tau-bench Env, routing tool results through EGM evidence gates.

    Usage with a tau-bench agent:

        adapter = EGMTauAdapter(env, memory)
        obs, info = adapter.reset(task_index=0)

        for step in range(max_steps):
            # Agent decides what to do (uses adapter context, not raw messages)
            action = agent_choose_action(adapter.build_egm_context())
            response = adapter.step(action)

            if response.done:
                break
    """

    def __init__(
        self,
        env: Any,  # tau_bench.envs.base.Env
        memory: EvidenceGatedMemory,
        tool_evidence_map: Optional[dict[str, str]] = None,
    ):
        self.env = env
        self.memory = memory
        self.tool_evidence_map = tool_evidence_map or TOOL_TO_EVIDENCE_TYPE
        self.metrics = AdapterMetrics()
        self._task_node: Any = None
        self._raw_messages: list[dict[str, Any]] = []
        self._task_id: str = ""
        self._current_obs: str = ""

    # ── lifecycle ─────────────────────────────────────────────────────────

    def reset(self, task_index: Optional[int] = None) -> tuple[str, dict[str, Any]]:
        """Reset the environment and create an EGM task node."""
        env_reset = self.env.reset(task_index=task_index)
        task = env_reset.info.task
        self._task_id = f"tau:{task.user_id}:{task_index or self.env.task_index}"
        self._current_obs = env_reset.observation
        self._raw_messages = [
            {"role": "system", "content": self.env.wiki},
            {"role": "user", "content": env_reset.observation},
        ]

        self._task_node = self.memory.create_task_node(
            self._task_id,
            "eligibility_check",
            f"tau-bench task {task_index}: {task.instruction[:120]}",
            anchors={
                "user_id": task.user_id,
                "task_index": str(task_index or 0),
            },
        )
        return env_reset.observation, env_reset.info.model_dump()

    def step(self, action: Any) -> Any:  # EnvResponse
        """Execute an action, recording tool results as EGM evidence."""
        from tau_bench.types import RESPOND_ACTION_NAME

        # Record action in raw message log for baseline comparison
        if action.name != RESPOND_ACTION_NAME:
            self._raw_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{self.metrics.tool_calls_recorded}",
                    "function": {"name": action.name, "arguments": json.dumps(action.kwargs)},
                }],
            })

        env_response = self.env.step(action)
        self._current_obs = env_response.observation
        self.metrics.tool_calls_recorded += 1

        # Record tool result as EGM evidence
        if action.name in self.tool_evidence_map:
            evidence_type = self.tool_evidence_map[action.name]
            source_system = self._source_system_for(evidence_type)
            try:
                ev = self.memory.record_evidence(
                    evidence_type=evidence_type,
                    source=action.name,
                    source_system=source_system,
                    content=json.dumps({
                        "tool": action.name,
                        "kwargs": action.kwargs,
                        "result": env_response.observation,
                    }),
                    metadata={
                        "tool_name": action.name,
                        "task_id": self._task_id,
                        "user_id": self.env.task.user_id,
                    },
                )
                self.metrics.evidence_refs.append(ev.id)
                self.metrics.tool_results_as_evidence += 1

                # Attach evidence to task node
                self.memory.attach_evidence_to_node(self._task_node.id, ev.id)
            except (ValueError, KeyError):
                pass  # evidence type not in schema — skip

            # Update raw messages
            self._raw_messages.append({
                "role": "tool",
                "tool_call_id": f"call_{self.metrics.tool_calls_recorded - 1}",
                "name": action.name,
                "content": env_response.observation,
            })
        elif action.name == RESPOND_ACTION_NAME:
            self._raw_messages.append({
                "role": "assistant",
                "content": action.kwargs.get("content", ""),
            })
            self._raw_messages.append({
                "role": "user",
                "content": env_response.observation,
            })

        # Gate the response if it's a conclusion
        if action.name == RESPOND_ACTION_NAME:
            self._gate_respond(action, env_response)

        return env_response

    def _gate_respond(self, action: Any, env_response: Any) -> None:
        """Try to assert the agent's respond as a gated fact."""
        content = action.kwargs.get("content", "")
        intent = self._classify_intent(content)
        claim_type = RESPOND_TO_CLAIM_TYPE.get(intent, "refund_eligibility")

        try:
            result = self.memory.assert_fact(
                f"tau-bench {self._task_id}: {content[:200]}",
                claim_type=claim_type,
                evidence=self.metrics.evidence_refs,  # type: ignore[arg-type]
            )
            if result.accepted and result.fact:
                self.metrics.facts_asserted += 1
                self.metrics.fact_ids.append(result.fact.id)
                self.memory.attach_fact_to_node(self._task_node.id, result.fact.id)
            else:
                self.metrics.facts_rejected += 1
                self.metrics.rejection_reasons.append(result.gate.rejection_reason)
        except (ValueError, KeyError):
            self.metrics.facts_rejected += 1

    # ── context ────────────────────────────────────────────────────────────

    def build_egm_context(self) -> str:
        """Build EGM context as a replacement for raw message history."""
        ctx = self.memory.build_context(
            query=self.env.task.instruction,
            task_id=self._task_id,
        )
        self.metrics.context_token_estimate = len(ctx) // 3  # rough token estimate
        self.metrics.raw_messages_token_estimate = (
            len(json.dumps(self._raw_messages)) // 3
        )
        return ctx

    def build_baseline_context(self) -> str:
        """Return the raw linear message history (baseline, no EGM)."""
        return json.dumps(self._raw_messages, indent=2)

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _source_system_for(evidence_type: str) -> str:
        """Return the trusted source_system for an evidence type."""
        defaults = {
            "order_record": "order_api",
            "refund_policy": "policy_db",
            "refund_api_response": "refund_api",
        }
        return defaults.get(evidence_type, "order_api")

    @staticmethod
    def _classify_intent(text: str) -> str:
        """Classify the agent's respond intent from text content."""
        text_lower = text.lower()
        for intent in ["cancel", "return", "exchange", "refund", "modify", "lookup"]:
            if intent in text_lower:
                return intent
        return "default"

    def transition_done(self) -> Any:
        """Attempt to transition the task node to DONE (gated)."""
        return self.memory.transition_node(
            self._task_node.id,
            TaskNodeStatus.DONE,
            evidence=self.metrics.evidence_refs,  # type: ignore[arg-type]
        )

    def close(self) -> None:
        self.memory.close()


# ── A/B comparison runner ────────────────────────────────────────────────────


def run_single_task_comparison(
    env: Any,
    agent_solve_fn: Any,
    task_index: int,
    workspace: Path,
) -> dict[str, Any]:
    """Run a single tau-bench task with and without EGM, compare results.

    This is the core A/B harness. It runs the SAME agent on the SAME task twice:
      1. BASELINE: agent with raw linear message history
      2. EGM: agent with EGM's structured, evidence-gated context

    Args:
        env: A fresh tau-bench Env instance (will be reset)
        agent_solve_fn: Callable that implements the agent loop.
            Signature: (env, task_index) -> SolveResult
        task_index: Which task to run
        workspace: Directory for the EGM workspace

    Returns:
        Dictionary with baseline + EGM metrics for comparison
    """
    started = time.perf_counter()

    # Run baseline (no EGM)
    baseline_start = time.perf_counter()
    baseline_result = agent_solve_fn(env, task_index)
    baseline_duration = time.perf_counter() - baseline_start

    # Run with EGM
    egm_memory = EvidenceGatedMemory(
        workspace / f"tau_task_{task_index}",
        REFUND,
    )
    try:
        adapter = EGMTauAdapter(env, egm_memory)
        egm_result = agent_solve_fn(env, task_index, adapter=adapter)
        egm_metrics = adapter.metrics.to_dict()
    finally:
        egm_memory.close()

    egm_duration = time.perf_counter() - baseline_start - baseline_duration

    return {
        "task_index": task_index,
        "task_instruction": env.task.instruction[:200],
        "baseline": {
            "reward": baseline_result.reward,
            "messages_count": len(baseline_result.messages),
            "total_cost": baseline_result.total_cost or 0.0,
            "duration_s": round(baseline_duration, 2),
        },
        "egm": {
            "reward": egm_result.reward,
            "messages_count": len(egm_result.messages) if hasattr(egm_result, 'messages') else 0,
            "total_cost": egm_result.total_cost or 0.0,
            "duration_s": round(egm_duration, 2),
            **egm_metrics,
        },
        "total_duration_s": round(time.perf_counter() - started, 2),
    }


# ── deterministic smoke test (no API keys, no LLM) ──────────────────────────


def run_smoke_test(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    """Run a deterministic smoke test that simulates the tau-bench agent loop.

    This uses EGM directly (not the real tau-bench Env) to verify the
    integration works end-to-end: evidence recording, fact gating, context
    building, and transition gating.

    No API keys, no LLM, no network — fully deterministic.
    """
    import tempfile
    from uuid import uuid4

    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_tau_smoke_") as tmp:
            return _run_smoke(Path(tmp))
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _run_smoke(workspace_root / f"smoke_{uuid4().hex[:8]}")


def _run_smoke(root: Path) -> dict[str, Any]:
    """Simulate a tau-bench retail refund task through EGM."""
    memory = EvidenceGatedMemory(root, REFUND)
    try:
        task_id = "tau:user-42:0"
        instruction = "Look up order ORD-TAU-001 and process a refund if eligible"

        # Phase 1: create task node (simulates tau-bench env.reset)
        node = memory.create_task_node(
            task_id,
            "eligibility_check",
            instruction,
            anchors={"user_id": "user-42", "order_id": "ORD-TAU-001"},
        )

        # Phase 2: simulate agent calling get_order_details → record as evidence
        order_ev = memory.record_evidence(
            evidence_type="order_record",
            source="get_order_details",
            source_system="order_api",
            content='{"order_id":"ORD-TAU-001","status":"PAID","total":99.99}',
            metadata={"tool_name": "get_order_details", "task_id": task_id},
        )
        memory.attach_evidence_to_node(node.id, order_ev.id)

        policy_ev = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="Full refund within 14 days for PAID orders.",
            metadata={"tool_name": "get_product_details", "task_id": task_id},
        )

        # Phase 3: agent tries to claim eligibility (must have order_record + refund_policy)
        r1 = memory.assert_fact(
            f"{task_id}: order ORD-TAU-001 is eligible for refund",
            claim_type="refund_eligibility",
            evidence=[order_ev, policy_ev],
        )
        eligibility_ok = r1.accepted
        if r1.fact:
            memory.attach_fact_to_node(node.id, r1.fact.id)

        # Phase 4: agent tries to claim refund complete WITHOUT refund_api_response
        r2 = memory.assert_fact(
            f"{task_id}: refund for ORD-TAU-001 has been completed",
            claim_type="refund_completed",
            evidence=[order_ev, policy_ev],
        )
        premature_blocked = not r2.accepted
        actionable = (
            "refund_api_response" in r2.gate.rejection_reason.lower()
            if not r2.accepted
            else False
        )

        # Phase 5: agent calls refund_api → records evidence → re-asserts
        refund_ev = memory.record_evidence(
            evidence_type="refund_api_response",
            source="refund_api",
            source_system="refund_api",
            content='{"refund_id":"REF-TAU-001","status":"COMPLETED"}',
            metadata={"tool_name": "return_delivered_order_items", "task_id": task_id},
        )
        memory.attach_evidence_to_node(node.id, refund_ev.id)

        r3 = memory.assert_fact(
            f"{task_id}: refund for ORD-TAU-001 has been completed (refund_id REF-TAU-001)",
            claim_type="refund_completed",
            evidence=[refund_ev],
        )
        completion_ok = r3.accepted
        if r3.fact:
            memory.attach_fact_to_node(node.id, r3.fact.id)

        # Phase 6: transition to DONE
        transition = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[order_ev, policy_ev, refund_ev],
        )

        # Phase 7: build context (what EGM would give the agent instead of raw messages)
        ctx = memory.build_context(query="ORD-TAU-001", task_id=task_id)
        raw_messages_sim = json.dumps([
            {"role": "system", "content": "wiki..."},
            {"role": "user", "content": instruction},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "get_order_details"}}]},
            {"role": "tool", "content": '{"order_id":"ORD-TAU-001","status":"PAID"}'},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "get_product_details"}}]},
            {"role": "tool", "content": "Full refund within 14 days for PAID orders."},
            {"role": "assistant", "content": "order ORD-TAU-001 is eligible for refund"},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "return_delivered_order_items"}}]},
            {"role": "tool", "content": '{"refund_id":"REF-TAU-001","status":"COMPLETED"}'},
            {"role": "assistant", "content": "refund for ORD-TAU-001 has been completed"},
        ])

        egm_tokens = len(ctx) // 3
        raw_tokens = len(raw_messages_sim) // 3

        metrics = {
            "eligibility_accepted": float(eligibility_ok),
            "premature_completion_blocked": float(premature_blocked),
            "rejection_actionable": float(actionable),
            "completion_accepted": float(completion_ok),
            "transition_accepted": float(transition.accepted),
            "context_has_order_id": float("ORD-TAU-001" in ctx),
            "context_has_fact": float("[FACT]" in ctx),
            "context_has_task_map": float("<task_map>" in ctx),
            "egm_context_tokens_est": egm_tokens,
            "raw_messages_tokens_est": raw_tokens,
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
            "name": "tau_bench_egm_smoke",
            "description": "Simulated tau-bench retail refund task through EGM gates. "
            "Verifies evidence recording, fact gating, context building, and transition gating "
            "all work correctly in the tau-bench integration model.",
            "passed": passed,
            "metrics": metrics,
            "thresholds": thresholds,
        }
    finally:
        memory.close()


if __name__ == "__main__":
    import json as _json

    report = run_smoke_test()
    print(f"passed: {report['passed']}")
    print(_json.dumps(report["metrics"], indent=2))
    if not report["passed"]:
        raise SystemExit(1)
