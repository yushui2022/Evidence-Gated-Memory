"""Deterministic local benchmarks for Evidence-Gated Memory.

These are not official leaderboard runs. They are small, reproducible probes
that map public memory-benchmark shapes onto EGM's hard-anchor, evidence-gated
product surface.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from evidence_gated_memory import Evidence, EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND


MetricValue = int | float | bool | str


def run_all_benchmarks(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    """Run the local benchmark suite and return JSON-serializable results."""
    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_bench_") as tmp:
            return _run_suite(Path(tmp))
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _run_suite(workspace_root)


def _run_suite(workspace_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    results = [
        longmemeval_s_hard_anchor(workspace_root),
        locomo_style_semantic_pyramid(workspace_root),
        beam_lite_hard_anchor_pressure(workspace_root),
        false_done_gate_benchmark(workspace_root),
    ]
    return {
        "suite": "egm-local-benchmarks",
        "note": "Local deterministic probes, not official leaderboard scores.",
        "passed": all(result["passed"] for result in results),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "benchmarks": results,
    }


def longmemeval_s_hard_anchor(workspace_root: Path, cases: int = 12) -> dict[str, Any]:
    """LongMemEval-S-shaped probe: exact hard-anchor recall with source ids."""
    workspace = _workspace(workspace_root, "longmemeval_s")
    memory = EvidenceGatedMemory(workspace, REFUND)
    refs_by_order: dict[str, tuple[Evidence, Evidence]] = {}
    accepted = 0
    try:
        for idx in range(cases):
            order_id = f"ORD-{1000 + idx}"
            order, policy = _record_refund_eligibility(memory, order_id)
            refs_by_order[order_id] = (order, policy)
            result = memory.assert_fact(
                f"Order {order_id} is refundable under the 14-day policy",
                claim_type="refund_eligibility",
                evidence=[order, policy],
            )
            accepted += int(result.accepted)

        anchor_hits = 0
        source_hits = 0
        for order_id, (order, policy) in refs_by_order.items():
            ctx = memory.build_context(
                query=order_id,
                max_facts=1,
                include_long_term=False,
            )
            anchor_hits += int(order_id in ctx)
            source_hits += int(order.id in ctx and policy.id in ctx)

        unknown_ctx = memory.build_context(
            query="ORD-999999",
            max_facts=1,
            include_long_term=False,
        )
        metrics = {
            "cases": cases,
            "accepted_fact_rate": accepted / cases,
            "anchor_recall": anchor_hits / cases,
            "evidence_source_coverage": source_hits / cases,
            "unsupported_abstention_rate": float("[FACT]" not in unknown_ctx),
        }
        return _result(
            "longmemeval_s_hard_anchor",
            "Hard-anchor recall and evidence-source coverage, aligned with LongMemEval-S task shape.",
            metrics,
            {
                "accepted_fact_rate": 1.0,
                "anchor_recall": 1.0,
                "evidence_source_coverage": 1.0,
                "unsupported_abstention_rate": 1.0,
            },
        )
    finally:
        memory.close()


def locomo_style_semantic_pyramid(workspace_root: Path, cases: int = 4) -> dict[str, Any]:
    """LoCoMo-shaped diagnostic for the manual L0/L1/L2/L3 path.

    This does not claim LoCoMo leaderboard performance. It checks the narrower
    EGM promise: manually promoted long-term memories are recallable while raw
    L0 conversation text stays out of prompt context.
    """
    workspace = _workspace(workspace_root, "locomo_style")
    memory = EvidenceGatedMemory(workspace, REFUND)
    target_topic = "hard-anchor refund memory"
    raw_marker = "RAW-LOCOMO-ONLY"
    try:
        target_message = None
        target_atom = None
        target_scenario = None
        for idx in range(cases):
            topic = target_topic if idx == cases - 1 else f"unrelated memory topic {idx}"
            message = memory.record_conversation_message(
                "user",
                f"{raw_marker}-{idx}: project discussion about {topic}.",
                session_id=f"session_{idx}",
            )
            atom = memory.record_memory_atom(
                "episodic",
                f"Project decision: {topic} should remain drill-downable.",
                source_messages=[message],
            )
            scenario = memory.record_memory_scenario(
                f"Scenario {idx}: {topic}",
                f"The user discussed {topic} and source-grounded memory.",
                atoms=[atom],
            )
            memory.record_memory_persona(
                f"Persona {idx}",
                f"Maintains context for {topic}.",
                scenarios=[scenario],
            )
            if topic == target_topic:
                target_message = message
                target_atom = atom
                target_scenario = scenario

        ctx = memory.build_context(
            query=target_topic,
            max_facts=0,
            max_memory_atoms=2,
            max_memory_scenarios=2,
            max_memory_personas=2,
        )
        metrics = {
            "cases": cases,
            "target_atom_recall": float(target_atom is not None and target_atom.id in ctx),
            "target_scenario_recall": float(target_scenario is not None and target_scenario.id in ctx),
            "source_id_coverage": float(target_message is not None and target_message.id in ctx),
            "raw_l0_exclusion": float(raw_marker not in ctx),
        }
        return _result(
            "locomo_style_semantic_pyramid",
            "Manual long-term memory recall with L0 exclusion, inspired by LoCoMo-style cross-session memory.",
            metrics,
            {
                "target_atom_recall": 1.0,
                "target_scenario_recall": 1.0,
                "source_id_coverage": 1.0,
                "raw_l0_exclusion": 1.0,
            },
        )
    finally:
        memory.close()


def beam_lite_hard_anchor_pressure(workspace_root: Path, cases: int = 24) -> dict[str, Any]:
    """BEAM-lite-shaped pressure probe with many hard-anchor task records."""
    workspace = _workspace(workspace_root, "beam_lite")
    memory = EvidenceGatedMemory(workspace, REFUND)
    target_idx = cases - 3
    target: dict[str, Any] = {}
    try:
        for idx in range(cases):
            order_id = f"ORD-{3000 + idx}"
            task_id = f"refund:{order_id}"
            node = memory.create_task_node(
                task_id,
                "eligibility_check",
                f"Check eligibility for {order_id}",
                anchors={"order_id": order_id},
            )
            order, policy = _record_refund_eligibility(memory, order_id)
            fact = memory.assert_fact(
                f"Order {order_id} is refundable under the 14-day policy",
                claim_type="refund_eligibility",
                evidence=[order, policy],
            ).fact
            if fact is not None:
                memory.attach_fact_to_node(node.id, fact.id)
            memory.record_offload(
                task_id=task_id,
                node_id=node.id,
                tool_call_id=f"order_lookup_{idx}",
                result_ref=order,
                summary=f"order_api returned {order_id} status=PAID",
                score=8,
            )
            if idx == target_idx:
                target = {
                    "order_id": order_id,
                    "task_id": task_id,
                    "order_ref": order.id,
                    "policy_ref": policy.id,
                }

        ctx = memory.build_context(
            query=target["order_id"],
            task_id=target["task_id"],
            max_facts=1,
            include_long_term=False,
        )
        metrics = {
            "cases": cases,
            "target_anchor_recall": float(target["order_id"] in ctx),
            "target_source_coverage": float(
                target["order_ref"] in ctx and target["policy_ref"] in ctx
            ),
            "context_fact_bound": float(ctx.count("[FACT]") <= 1),
            "task_map_present": float("<task_map>" in ctx and "flowchart TD" in ctx),
            "target_offload_records": len(memory.list_offloads(task_id=target["task_id"])),
        }
        return _result(
            "beam_lite_hard_anchor_pressure",
            "Synthetic hard-anchor pressure test for bounded context and drill-down links.",
            metrics,
            {
                "target_anchor_recall": 1.0,
                "target_source_coverage": 1.0,
                "context_fact_bound": 1.0,
                "task_map_present": 1.0,
                "target_offload_records": 1.0,
            },
        )
    finally:
        memory.close()


def false_done_gate_benchmark(workspace_root: Path, cases: int = 6) -> dict[str, Any]:
    """Enterprise false-completion probe: reject unsupported DONE/completed claims."""
    workspace = _workspace(workspace_root, "false_done")
    memory = EvidenceGatedMemory(workspace, REFUND)
    claim_blocks = 0
    transition_blocks = 0
    actionable = 0
    accepted_after_evidence = 0
    try:
        for idx in range(cases):
            order_id = f"ORD-{5000 + idx}"
            refund_id = f"REF-{5000 + idx}"
            node = memory.create_task_node(
                f"refund:{order_id}",
                "refund_completion",
                f"Complete refund {refund_id}",
                anchors={"order_id": order_id, "refund_id": refund_id},
            )

            rejected_claim = memory.assert_fact(
                f"Refund {refund_id} has been completed",
                claim_type="refund_completed",
                evidence=[],
            )
            rejected_transition = memory.transition_node(node.id, TaskNodeStatus.DONE)
            claim_blocks += int(not rejected_claim.accepted)
            transition_blocks += int(not rejected_transition.accepted)
            actionable += int(
                "refund_api_response" in rejected_claim.rejection_reason
                and "refund_api" in rejected_claim.suggested_action
                and "refund_api_response" in rejected_transition.rejection_reason
                and "refund_api" in rejected_transition.suggested_action
            )

            refund_ref = memory.record_evidence(
                evidence_type="refund_api_response",
                source="refund_api",
                source_system="refund_api",
                content=f'{{"refund_id":"{refund_id}","status":"COMPLETED"}}',
                metadata={"order_id": order_id, "refund_id": refund_id},
            )
            accepted_claim = memory.assert_fact(
                f"Refund {refund_id} has been completed",
                claim_type="refund_completed",
                evidence=[refund_ref],
            )
            accepted_transition = memory.transition_node(
                node.id,
                TaskNodeStatus.DONE,
                evidence=[refund_ref],
            )
            accepted_after_evidence += int(accepted_claim.accepted and accepted_transition.accepted)

        metrics = {
            "cases": cases,
            "claim_false_done_block_rate": claim_blocks / cases,
            "transition_false_done_block_rate": transition_blocks / cases,
            "actionable_rejection_rate": actionable / cases,
            "acceptance_after_evidence_rate": accepted_after_evidence / cases,
        }
        return _result(
            "false_done_gate_benchmark",
            "Unsupported refund completion claims and DONE transitions must be blocked with actionable feedback.",
            metrics,
            {
                "claim_false_done_block_rate": 1.0,
                "transition_false_done_block_rate": 1.0,
                "actionable_rejection_rate": 1.0,
                "acceptance_after_evidence_rate": 1.0,
            },
        )
    finally:
        memory.close()


def _record_refund_eligibility(memory: EvidenceGatedMemory, order_id: str) -> tuple[Evidence, Evidence]:
    order = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content=f'{{"order_id":"{order_id}","status":"PAID"}}',
        metadata={"order_id": order_id},
    )
    policy = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="Orders paid within 14 days are eligible for refund.",
        metadata={"policy": "14-day-refund", "order_id": order_id},
    )
    return order, policy


def _workspace(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def _result(
    name: str,
    description: str,
    metrics: dict[str, MetricValue],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    passed = all(float(metrics[key]) >= threshold for key, threshold in thresholds.items())
    return {
        "name": name,
        "description": description,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
    }
