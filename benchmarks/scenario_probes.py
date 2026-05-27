"""Scenario probes: end-to-end domain workflows for Evidence-Gated Memory.

Each scenario exercises the full EGM loop in a specific enterprise domain —
record evidence → assert fact → gate rejection → attach missing evidence →
re-assert → task transition → drill-down context.

These are not unit tests. They are narrative probes that show EGM's value
in the domains it was built for.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from evidence_gated_memory import EvidenceGatedMemory, FactKind, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import CODING, REFUND


MetricValue = int | float | bool | str


# ── suite runner ────────────────────────────────────────────────────────────


def run_all_scenarios(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_scenario_") as tmp:
            return _run(Path(tmp))
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _run(workspace_root)


def _run(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    probes = [
        scenario_refund_full_lifecycle,
        scenario_refund_multi_order_concurrency,
        scenario_refund_partial_evidence_rejection_loop,
        scenario_coding_file_to_diagnosis,
        scenario_coding_stale_rejection,
        scenario_coding_multi_file_workflow,
    ]
    results = [probe(root) for probe in probes]
    return {
        "suite": "egm-scenario-probes",
        "note": "End-to-end enterprise workflow probes. Each scenario exercises the full EGM loop.",
        "passed": all(r["passed"] for r in results),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "scenarios": results,
    }


# ── scenario 1: full refund lifecycle ───────────────────────────────────────


def scenario_refund_full_lifecycle(root: Path) -> dict[str, Any]:
    """Complete refund agent workflow: 3 orders, each through eligibility → completion.

    The workflow:
      1. Create task nodes for each order
      2. Try to assert eligibility without evidence → must be rejected
      3. Attach evidence → re-assert → must pass
      4. Try to assert completion without refund_api_response → must be rejected
      5. Attach refund_api_response → re-assert → must pass
      6. Transition each node to DONE (gated)
      7. Verify context contains all facts with provenance
      8. Revoke one order's evidence → verify cascade

    Measures: rejection accuracy, gate precision, context completeness, cascade correctness.
    """
    memory = EvidenceGatedMemory(_ws(root, "refund_lifecycle"), REFUND)
    try:
        orders = ["ORD-101", "ORD-102", "ORD-103"]
        nodes: dict[str, Any] = {}
        facts: dict[str, Any] = {}
        evidence: dict[str, Any] = {}

        # Phase 1: create task nodes
        for oid in orders:
            node = memory.create_task_node(
                f"refund:{oid}",
                "eligibility_check",
                f"Check refund eligibility for {oid}",
                anchors={"order_id": oid},
            )
            nodes[oid] = node

        # Phase 2: assert eligibility WITHOUT evidence → must all be rejected
        premature_rejections = 0
        for oid in orders:
            r = memory.assert_fact(
                f"Order {oid} is eligible for refund",
                claim_type="refund_eligibility",
                evidence=[],
            )
            if not r.accepted:
                premature_rejections += 1
                # Verify it tells you what's missing
                assert "order_record" in r.gate.rejection_reason.lower(), (
                    f"Expected rejection to mention order_record, got: {r.gate.rejection_reason}"
                )

        # Phase 3: attach evidence → assert → must pass
        eligibility_facts = 0
        for oid in orders:
            order_ev = memory.record_evidence(
                evidence_type="order_record",
                source="order_api",
                source_system="order_api",
                content=f'{{"order_id":"{oid}","status":"PAID"}}',
                metadata={"order_id": oid},
            )
            policy_ev = memory.record_evidence(
                evidence_type="refund_policy",
                source="policy_db",
                source_system="policy_db",
                content="Full refund within 14 days of purchase.",
            )
            evidence[oid] = {"order": order_ev, "policy": policy_ev}

            r = memory.assert_fact(
                f"Order {oid} is eligible for refund under the 14-day policy",
                claim_type="refund_eligibility",
                evidence=[order_ev, policy_ev],
            )
            if r.accepted and r.fact:
                eligibility_facts += 1
                memory.attach_fact_to_node(nodes[oid].id, r.fact.id)
                facts[f"eligibility_{oid}"] = r.fact

        # Phase 4: try to assert completion without refund_api_response → must be rejected
        completion_rejections = 0
        for oid in orders:
            r = memory.assert_fact(
                f"Refund for {oid} has been completed",
                claim_type="refund_completed",
                evidence=[],
            )
            if not r.accepted:
                completion_rejections += 1

        # Phase 5: attach refund_api_response → assert → must pass
        completion_facts = 0
        for oid in orders:
            refund_ev = memory.record_evidence(
                evidence_type="refund_api_response",
                source="refund_api",
                source_system="refund_api",
                content=f'{{"refund_id":"REF-{oid}","status":"COMPLETED"}}',
                metadata={"order_id": oid},
            )
            evidence[oid]["refund_api"] = refund_ev

            r = memory.assert_fact(
                f"Order {oid} refund has been completed (refund_api confirmed)",
                claim_type="refund_completed",
                evidence=[refund_ev],
            )
            if r.accepted and r.fact:
                completion_facts += 1
                facts[f"completion_{oid}"] = r.fact

        # Phase 6: transition each eligibility node to DONE (gated)
        transitions_accepted = 0
        for oid in orders:
            result = memory.transition_node(
                nodes[oid].id,
                TaskNodeStatus.DONE,
                evidence=[evidence[oid]["order"], evidence[oid]["policy"]],
            )
            if result.accepted:
                transitions_accepted += 1

        # Phase 7: verify context for one order
        target = "ORD-101"
        ctx = memory.build_context(query=target, task_id=f"refund:{target}")
        ctx_has_fact = f"eligible for refund" in ctx
        ctx_has_ref = evidence[target]["order"].id in ctx
        ctx_has_task_map = "<task_map>" in ctx and "flowchart TD" in ctx

        # Phase 8: revoke one order's evidence → cascade
        revoked_ids = memory.revoke_evidence(
            evidence["ORD-103"]["order"].id,
            reason="order was cancelled by customer",
        )
        cascade_worked = facts["eligibility_ORD-103"].id in revoked_ids

        metrics = {
            "orders_processed": len(orders),
            "premature_eligibility_rejection_rate": premature_rejections / len(orders),
            "eligibility_acceptance_with_evidence_rate": eligibility_facts / len(orders),
            "premature_completion_rejection_rate": completion_rejections / len(orders),
            "completion_acceptance_with_evidence_rate": completion_facts / len(orders),
            "gated_transition_acceptance_rate": transitions_accepted / len(orders),
            "context_fact_recall": float(ctx_has_fact),
            "context_ref_drilldown": float(ctx_has_ref),
            "context_task_map_present": float(ctx_has_task_map),
            "cascade_on_revoke": float(cascade_worked),
        }
        thresholds = {
            "premature_eligibility_rejection_rate": 1.0,
            "eligibility_acceptance_with_evidence_rate": 1.0,
            "premature_completion_rejection_rate": 1.0,
            "completion_acceptance_with_evidence_rate": 1.0,
            "gated_transition_acceptance_rate": 1.0,
            "context_fact_recall": 1.0,
            "context_ref_drilldown": 1.0,
            "context_task_map_present": 1.0,
            "cascade_on_revoke": 1.0,
        }

        return _scenario(
            "refund_full_lifecycle",
            "3 orders through the complete refund workflow: eligibility → rejection → "
            "evidence → acceptance → completion → transition → context → revoke cascade.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── scenario 2: multi-order concurrency ─────────────────────────────────────


def scenario_refund_multi_order_concurrency(root: Path) -> dict[str, Any]:
    """Stress test: 20 concurrent refund workflows, verify no cross-contamination.

    Measures: anchor isolation, fact-to-node binding, context boundary.
    """
    N = 20
    memory = EvidenceGatedMemory(_ws(root, "refund_concurrency"), REFUND)
    try:
        target_idx = N - 3  # pick one to verify in detail
        target_oid = f"ORD-{2000 + target_idx}"
        target_rid = f"REF-{2000 + target_idx}"

        for idx in range(N):
            oid = f"ORD-{2000 + idx}"
            rid = f"REF-{2000 + idx}"
            node = memory.create_task_node(
                f"refund:{oid}",
                "eligibility_check",
                f"Check refund eligibility for {oid}",
                anchors={"order_id": oid, "refund_id": rid},
            )
            order_ev = memory.record_evidence(
                evidence_type="order_record",
                source="order_api",
                source_system="order_api",
                content=f'{{"order_id":"{oid}","status":"PAID"}}',
                metadata={"order_id": oid},
            )
            policy_ev = memory.record_evidence(
                evidence_type="refund_policy",
                source="policy_db",
                source_system="policy_db",
                content="14-day refund policy v3.",
            )
            result = memory.assert_fact(
                f"Order {oid} is eligible for refund",
                claim_type="refund_eligibility",
                evidence=[order_ev, policy_ev],
            )
            if result.fact:
                memory.attach_fact_to_node(node.id, result.fact.id)

            refund_ev = memory.record_evidence(
                evidence_type="refund_api_response",
                source="refund_api",
                source_system="refund_api",
                content=f'{{"refund_id":"{rid}","status":"COMPLETED"}}',
                metadata={"order_id": oid, "refund_id": rid},
            )
            comp = memory.assert_fact(
                f"Order {oid} refund completed (refund {rid})",
                claim_type="refund_completed",
                evidence=[refund_ev],
            )
            if comp.fact:
                memory.attach_fact_to_node(node.id, comp.fact.id)

            memory.transition_node(
                node.id,
                TaskNodeStatus.DONE,
                evidence=[order_ev, policy_ev],
            )

        # Verify target workflow — query by task_id to include all linked facts
        ctx = memory.build_context(query=target_oid, task_id=f"refund:{target_oid}")
        target_in_ctx = target_oid in ctx
        target_refund_fact_in_ctx = f"Order {target_oid} refund completed" in ctx

        # Check no cross-contamination: context for target should NOT contain
        # a fact text from a different order
        wrong_oid = "ORD-2001"
        cross_contamination = (
            target_idx != 1 and f"Order {wrong_oid} refund" in ctx
        )

        workflows = len(memory.list_task_nodes(task_id=f"refund:{target_oid}"))
        offloads = len(memory.list_offloads(task_id=f"refund:{target_oid}"))

        metrics = {
            "concurrent_workflows": N,
            "target_anchor_recall": float(target_in_ctx),
            "target_refund_fact_recall": float(target_refund_fact_in_ctx),
            "no_cross_contamination": float(not cross_contamination),
            "target_workflow_nodes": workflows,
            "total_facts_in_context": ctx.count("[FACT]"),
        }
        thresholds = {
            "target_anchor_recall": 1.0,
            "target_refund_fact_recall": 1.0,
            "no_cross_contamination": 1.0,
        }
        return _scenario(
            "refund_multi_order_concurrency",
            f"{N} concurrent refund workflows. Verify the target workflow is recallable without cross-contamination.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── scenario 3: partial evidence rejection loop ─────────────────────────────


def scenario_refund_partial_evidence_rejection_loop(root: Path) -> dict[str, Any]:
    """Simulate the real agent loop: try → reject → fetch → retry → accept.

    This is the narrative the README refund demo tells, made into a benchmark.
    It explicitly counts how many rounds of rejection happen before each fact
    is accepted, and verifies that every rejection is actionable.

    Measures: rejection actionability rate, rounds-to-accept, final acceptance.
    """
    memory = EvidenceGatedMemory(_ws(root, "refund_rejection_loop"), REFUND)
    try:
        order_id = "ORD-301"
        refund_id = "REF-301"
        rounds: list[dict[str, Any]] = []

        # Round 1: assert eligibility with NO evidence
        r1 = memory.assert_fact(
            f"Order {order_id} is eligible for refund",
            claim_type="refund_eligibility",
            evidence=[],
        )
        rounds.append({
            "goal": "eligibility",
            "accepted": r1.accepted,
            "actionable": int(
                r1.gate.suggested_action != "" and r1.gate.rejection_reason != ""
            ) if not r1.accepted else 1,
        })

        # Round 2: attach partial evidence (only order_record, no policy)
        order_ev = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content=f'{{"order_id":"{order_id}","status":"PAID"}}',
            metadata={"order_id": order_id},
        )
        r2 = memory.assert_fact(
            f"Order {order_id} is eligible",
            claim_type="refund_eligibility",
            evidence=[order_ev],
        )
        rounds.append({
            "goal": "eligibility (partial evidence)",
            "accepted": r2.accepted,
            "actionable": int(
                r2.gate.suggested_action != "" and "refund_policy" in r2.gate.rejection_reason.lower()
            ) if not r2.accepted else 0,
        })

        # Round 3: attach full evidence → must pass
        policy_ev = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14-day refund policy.",
        )
        r3 = memory.assert_fact(
            f"Order {order_id} is eligible for refund under the 14-day policy",
            claim_type="refund_eligibility",
            evidence=[order_ev, policy_ev],
        )
        rounds.append({
            "goal": "eligibility (full evidence)",
            "accepted": r3.accepted,
            "actionable": 1,
        })
        eligibility_fact = r3.fact

        # Round 4: assert completion with NO evidence
        r4 = memory.assert_fact(
            f"Order {order_id} refund ({refund_id}) has been completed",
            claim_type="refund_completed",
            evidence=[],
        )
        rounds.append({
            "goal": "completion (no evidence)",
            "accepted": r4.accepted,
            "actionable": int(
                r4.gate.suggested_action != "" and "refund_api_response" in r4.gate.rejection_reason.lower()
            ) if not r4.accepted else 0,
        })

        # Round 5: attach refund_api_response → must pass
        refund_ev = memory.record_evidence(
            evidence_type="refund_api_response",
            source="refund_api",
            source_system="refund_api",
            content=f'{{"refund_id":"{refund_id}","status":"COMPLETED"}}',
            metadata={"order_id": order_id, "refund_id": refund_id},
        )
        r5 = memory.assert_fact(
            f"Order {order_id} refund ({refund_id}) has been completed",
            claim_type="refund_completed",
            evidence=[refund_ev],
        )
        rounds.append({
            "goal": "completion (full evidence)",
            "accepted": r5.accepted,
            "actionable": 1,
        })
        completion_fact = r5.fact

        # Task graph
        node = memory.create_task_node(
            f"refund:{order_id}",
            "eligibility_check",
            f"Check eligibility for {order_id}",
            anchors={"order_id": order_id, "refund_id": refund_id},
        )
        if eligibility_fact:
            memory.attach_fact_to_node(node.id, eligibility_fact.id)
        transition = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[order_ev, policy_ev],
        )

        ctx = memory.build_context(query=order_id, task_id=f"refund:{order_id}")

        rejection_rounds = [r for r in rounds if not r["accepted"]]
        acceptance_rounds = [r for r in rounds if r["accepted"]]
        actionable_rejections = [r for r in rejection_rounds if r["actionable"]]

        metrics = {
            "total_rounds": len(rounds),
            "rejection_rounds": len(rejection_rounds),
            "acceptance_rounds": len(acceptance_rounds),
            "actionable_rejection_rate": (
                len(actionable_rejections) / len(rejection_rounds)
                if rejection_rounds
                else 1.0
            ),
            "eligibility_accepted": float(r3.accepted),
            "completion_accepted": float(r5.accepted),
            "transition_accepted": float(transition.accepted),
            "context_has_eligibility": float("eligible" in ctx.lower()),
            "context_has_completion": float("completed" in ctx.lower()),
            "context_has_both_fact_kinds": float(
                "[FACT]" in ctx and "observed" in ctx and "derived" not in ctx
            ),
        }
        thresholds = {
            "total_rounds": 5.0,
            "rejection_rounds": 3.0,  # rounds 1 (no evidence), 2 (partial), 4 (no completion evidence)
            "actionable_rejection_rate": 1.0,
            "eligibility_accepted": 1.0,
            "completion_accepted": 1.0,
            "transition_accepted": 1.0,
            "context_has_eligibility": 1.0,
            "context_has_completion": 1.0,
        }
        return _scenario(
            "refund_partial_evidence_rejection_loop",
            "The canonical refund agent loop: try → reject with actionable feedback → "
            "fetch evidence → retry → accept. Verifies every rejection is actionable.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── scenario 4: coding file → diagnosis → done ──────────────────────────────


def scenario_coding_file_to_diagnosis(root: Path) -> dict[str, Any]:
    """Coding agent workflow: read file → claim content → diagnose error → mark done.

    The workflow:
      1. Create a task node for a bug fix
      2. Try to claim file_content without evidence → must be rejected
      3. Attach file_read → re-assert → must pass
      4. Try to claim error_diagnosis without test_log → must be rejected
      5. Attach test_log → re-assert → must pass
      6. Try to claim task_done without fresh test_log → must be rejected
      7. Attach fresh test_log → re-assert → must pass
      8. Transition node to DONE → must pass
      9. Verify context contains all facts with provenance

    Measures: rejection accuracy, gate precision, context completeness across
    a different domain schema (coding, not refund).
    """
    memory = EvidenceGatedMemory(_ws(root, "coding_diag"), CODING)
    try:
        task_id = "bugfix:auth-timeout"
        rounds: list[dict[str, Any]] = []

        node = memory.create_task_node(
            task_id,
            "diagnosis",
            "Fix authentication timeout in login flow",
            anchors={"file": "src/auth/login.py", "function": "authenticate"},
        )

        # Round 1: claim file_content with NO evidence
        r1 = memory.assert_fact(
            "auth-timeout bug: src/auth/login.py contains a 5-second hardcoded timeout in authenticate()",
            claim_type="file_content",
            evidence=[],
        )
        rounds.append({
            "goal": "file_content (no evidence)",
            "accepted": r1.accepted,
            "actionable": int(
                "file_read" in r1.gate.rejection_reason.lower()
            ) if not r1.accepted else 0,
        })

        # Round 2: attach file_read → must pass
        file_ev = memory.record_evidence(
            evidence_type="file_read",
            source="filesystem",
            source_system="filesystem",
            content=(
                'def authenticate(user, pw):\n'
                '    time.sleep(5)  # hardcoded timeout\n'
                '    return db.check(user, pw)\n'
            ),
            metadata={"file": "src/auth/login.py"},
        )
        r2 = memory.assert_fact(
            "auth-timeout bug: src/auth/login.py contains a 5-second hardcoded timeout in authenticate()",
            claim_type="file_content",
            evidence=[file_ev],
        )
        rounds.append({
            "goal": "file_content (with file_read)",
            "accepted": r2.accepted,
            "actionable": 1,
        })
        file_fact = r2.fact

        # Round 3: claim error_diagnosis with NO evidence
        r3 = memory.assert_fact(
            "auth-timeout bug: login timeout is caused by hardcoded time.sleep(5) instead of configurable timeout",
            claim_type="error_diagnosis",
            evidence=[],
        )
        rounds.append({
            "goal": "error_diagnosis (no evidence)",
            "accepted": r3.accepted,
            "actionable": int(
                "test_log" in r3.gate.rejection_reason.lower()
            ) if not r3.accepted else 0,
        })

        # Round 4: attach test_log → must pass
        test_ev = memory.record_evidence(
            evidence_type="test_log",
            source="test_runner",
            source_system="test_runner",
            content="FAILED test_login_timeout - assert response_time < 1.0, got 5.2s",
            metadata={"file": "tests/test_login.py"},
        )
        r4 = memory.assert_fact(
            "auth-timeout bug: login timeout is caused by hardcoded time.sleep(5) instead of configurable timeout",
            claim_type="error_diagnosis",
            evidence=[test_ev],
        )
        rounds.append({
            "goal": "error_diagnosis (with test_log)",
            "accepted": r4.accepted,
            "actionable": 1,
        })
        diag_fact = r4.fact

        # Round 5: claim task_done with NO evidence
        r5 = memory.assert_fact(
            "auth-timeout bug fix complete: replaced hardcoded timeout with config setting",
            claim_type="task_done",
            evidence=[],
        )
        rounds.append({
            "goal": "task_done (no evidence)",
            "accepted": r5.accepted,
            "actionable": int(
                "test_log" in r5.gate.rejection_reason.lower()
            ) if not r5.accepted else 0,
        })

        # Round 6: attach fresh test_log → must pass
        pass_ev = memory.record_evidence(
            evidence_type="test_log",
            source="test_runner",
            source_system="test_runner",
            content="PASSED test_login_timeout - response_time=0.3s",
            metadata={"file": "tests/test_login.py"},
        )
        r6 = memory.assert_fact(
            "auth-timeout bug fix complete: replaced hardcoded timeout with config setting",
            claim_type="task_done",
            evidence=[pass_ev],
        )
        rounds.append({
            "goal": "task_done (with fresh test_log)",
            "accepted": r6.accepted,
            "actionable": 1,
        })
        done_fact = r6.fact

        # Attach facts to node
        if file_fact:
            memory.attach_fact_to_node(node.id, file_fact.id)
        if diag_fact:
            memory.attach_fact_to_node(node.id, diag_fact.id)

        # Transition to DONE
        transition = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[pass_ev],
        )

        ctx = memory.build_context(query="auth-timeout", task_id=task_id)

        rejection_rounds = [r for r in rounds if not r["accepted"]]
        acceptance_rounds = [r for r in rounds if r["accepted"]]
        actionable_rejections = [r for r in rejection_rounds if r["actionable"]]

        metrics = {
            "total_rounds": len(rounds),
            "rejection_rounds": len(rejection_rounds),
            "acceptance_rounds": len(acceptance_rounds),
            "actionable_rejection_rate": (
                len(actionable_rejections) / len(rejection_rounds)
                if rejection_rounds
                else 1.0
            ),
            "file_content_accepted": float(r2.accepted),
            "error_diagnosis_accepted": float(r4.accepted),
            "task_done_accepted": float(r6.accepted),
            "transition_accepted": float(transition.accepted),
            "context_has_file_content": float("hardcoded timeout" in ctx),
            "context_has_diagnosis": float("configurable timeout" in ctx),
            "context_has_task_map": float("<task_map>" in ctx),
        }
        thresholds = {
            "total_rounds": 6.0,
            "rejection_rounds": 3.0,  # rounds 1 (no file_read), 3 (no test_log), 5 (no fresh test_log)
            "actionable_rejection_rate": 1.0,
            "file_content_accepted": 1.0,
            "error_diagnosis_accepted": 1.0,
            "task_done_accepted": 1.0,
            "transition_accepted": 1.0,
            "context_has_file_content": 1.0,
            "context_has_diagnosis": 1.0,
            "context_has_task_map": 1.0,
        }
        return _scenario(
            "coding_file_to_diagnosis",
            "Full coding agent loop: file_read → file_content → test_log → "
            "error_diagnosis → fresh test_log → task_done. 6 rounds, 3 rejections, all actionable.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── scenario 5: coding stale evidence gate ──────────────────────────────────


def scenario_coding_stale_rejection(root: Path) -> dict[str, Any]:
    """Coding agent: verify that stale evidence is gated correctly.

    coding.yaml rules:
      - file_content: requires file_read, freshness=stale (stale ok, expired blocks)
      - task_done: requires test_log, requires_fresh_evidence=true (only FRESH allowed)

    This scenario:
      1. Record a file_read → assert file_content → must pass
      2. Backdate a test_log past PT10M stale_after (but within PT2H expired_after)
      3. Assert task_done with stale test_log → must be rejected (requires fresh)
      4. Assert error_diagnosis with stale test_log → must pass (stale is ok)
      5. Record a fresh test_log → task_done → must pass

    Measures: freshness threshold difference between claim types in the same schema.
    """
    from datetime import datetime, timedelta, timezone

    memory = EvidenceGatedMemory(_ws(root, "coding_stale"), CODING)
    try:
        task_id = "bugfix:stale-test"

        node = memory.create_task_node(
            task_id,
            "diagnosis",
            "Verify stale evidence handling in coding domain",
            anchors={"file": "src/utils.py"},
        )

        # Phase 1: file_content with fresh file_read → must pass
        file_ev = memory.record_evidence(
            evidence_type="file_read",
            source="filesystem",
            source_system="filesystem",
            content="def parse_config(path): return yaml.safe_load(open(path))",
            metadata={"file": "src/utils.py"},
        )
        r1 = memory.assert_fact(
            "src/utils.py contains a parse_config function using yaml.safe_load",
            claim_type="file_content",
            evidence=[file_ev],
        )
        file_content_ok = r1.accepted

        # Phase 2: backdate a test_log to 15 min ago (past PT10M stale_after, within PT2H expired)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        stale_test = memory.record_evidence(
            evidence_type="test_log",
            source="test_runner",
            source_system="test_runner",
            content="PASSED test_parse_config - all assertions passed",
            observed_at=old_time,
        )

        # Phase 3: task_done with stale test_log → must be REJECTED (requires_fresh_evidence: true)
        r2 = memory.assert_fact(
            "Bug fix is complete: parse_config now handles missing files",
            claim_type="task_done",
            evidence=[stale_test],
        )
        task_done_blocked = not r2.accepted
        freshness_gate_fired = any(
            "freshness" in v.gate.lower() or "stale" in v.gate.lower()
            for v in r2.gate.violations
        )

        # Phase 4: error_diagnosis with stale test_log → must PASS (stale is ok)
        r3 = memory.assert_fact(
            "parse_config crashes on missing config file because open() is unchecked",
            claim_type="error_diagnosis",
            evidence=[stale_test],
        )
        diagnosis_with_stale_ok = r3.accepted

        # Phase 5: task_done with FRESH test_log → must pass
        fresh_test = memory.record_evidence(
            evidence_type="test_log",
            source="test_runner",
            source_system="test_runner",
            content="PASSED test_parse_config_missing_file - handles FileNotFound gracefully",
        )
        r4 = memory.assert_fact(
            "Bug fix is complete: parse_config now handles missing files",
            claim_type="task_done",
            evidence=[fresh_test],
        )
        task_done_fresh_ok = r4.accepted

        # Transition with fresh test_log
        transition = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[fresh_test],
        )

        ctx = memory.build_context(query="parse_config", task_id=task_id)

        metrics = {
            "file_content_with_fresh_ok": float(file_content_ok),
            "task_done_with_stale_blocked": float(task_done_blocked),
            "freshness_gate_fired": float(freshness_gate_fired),
            "diagnosis_with_stale_ok": float(diagnosis_with_stale_ok),
            "task_done_with_fresh_ok": float(task_done_fresh_ok),
            "transition_accepted": float(transition.accepted),
            "context_has_parse_config": float("parse_config" in ctx),
            "context_has_task_map": float("<task_map>" in ctx),
        }
        thresholds = {
            "file_content_with_fresh_ok": 1.0,
            "task_done_with_stale_blocked": 1.0,
            "freshness_gate_fired": 1.0,
            "diagnosis_with_stale_ok": 1.0,
            "task_done_with_fresh_ok": 1.0,
            "transition_accepted": 1.0,
            "context_has_parse_config": 1.0,
            "context_has_task_map": 1.0,
        }
        return _scenario(
            "coding_stale_rejection",
            "Freshness threshold is claim-type-specific: file_content accepts stale, "
            "task_done requires fresh. Same evidence, different outcomes — correctly.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── scenario 6: coding multi-file workflow ──────────────────────────────────


def scenario_coding_multi_file_workflow(root: Path) -> dict[str, Any]:
    """Coding agent: 10 concurrent bug fixes, verify no cross-contamination.

    Each file goes through: read → diagnosis → fix → test → done.
    Measures: anchor isolation, fact-to-node binding, context boundary.
    """
    N = 10
    memory = EvidenceGatedMemory(_ws(root, "coding_multi"), CODING)
    try:
        target_idx = N - 2
        target_file = f"src/module_{target_idx}.py"

        for idx in range(N):
            file_path = f"src/module_{idx}.py"
            task_id = f"bugfix:{file_path}"
            node = memory.create_task_node(
                task_id,
                "diagnosis",
                f"Fix bug in {file_path}",
                anchors={"file": file_path, "function": f"func_{idx}"},
            )

            file_ev = memory.record_evidence(
                evidence_type="file_read",
                source="filesystem",
                source_system="filesystem",
                content=f"def func_{idx}(): return None  # buggy",
                metadata={"file": file_path},
            )
            file_result = memory.assert_fact(
                f"{file_path} contains func_{idx} which returns None instead of expected dict",
                claim_type="file_content",
                evidence=[file_ev],
            )
            if file_result.fact:
                memory.attach_fact_to_node(node.id, file_result.fact.id)

            test_ev = memory.record_evidence(
                evidence_type="test_log",
                source="test_runner",
                source_system="test_runner",
                content=f"FAILED test_func_{idx} - expected dict, got None",
                metadata={"file": f"tests/test_module_{idx}.py"},
            )
            diag_result = memory.assert_fact(
                f"func_{idx} returns None because it has no implementation body",
                claim_type="error_diagnosis",
                evidence=[test_ev],
            )
            if diag_result.fact:
                memory.attach_fact_to_node(node.id, diag_result.fact.id)

            pass_ev = memory.record_evidence(
                evidence_type="test_log",
                source="test_runner",
                source_system="test_runner",
                content=f"PASSED test_func_{idx} - returns correct dict",
                metadata={"file": f"tests/test_module_{idx}.py"},
            )
            done_result = memory.assert_fact(
                f"Bug fix for {file_path} is complete: func_{idx} now returns correct dict",
                claim_type="task_done",
                evidence=[pass_ev],
            )
            if done_result.fact:
                memory.attach_fact_to_node(node.id, done_result.fact.id)

            memory.transition_node(
                node.id,
                TaskNodeStatus.DONE,
                evidence=[pass_ev],
            )

        # Verify target workflow
        ctx = memory.build_context(query=target_file, task_id=f"bugfix:{target_file}")
        target_in_ctx = target_file in ctx
        target_func_in_ctx = f"func_{target_idx}" in ctx

        # Check no cross-contamination
        wrong_file = "src/module_0.py"
        wrong_func = "func_0"
        cross_contamination = (
            target_idx != 0
            and f"Bug fix for {wrong_file}" in ctx
        )

        workflows = len(memory.list_task_nodes(task_id=f"bugfix:{target_file}"))

        metrics = {
            "concurrent_workflows": N,
            "target_anchor_recall": float(target_in_ctx),
            "target_function_recall": float(target_func_in_ctx),
            "no_cross_contamination": float(not cross_contamination),
            "target_workflow_nodes": workflows,
            "total_facts_in_context": ctx.count("[FACT]"),
        }
        thresholds = {
            "target_anchor_recall": 1.0,
            "target_function_recall": 1.0,
            "no_cross_contamination": 1.0,
        }
        return _scenario(
            "coding_multi_file_workflow",
            f"{N} concurrent bug-fix workflows. Verify the target workflow is recallable "
            "without cross-contamination — proving EGM scales across domains.",
            metrics,
            thresholds,
        )
    finally:
        memory.close()


# ── helpers ─────────────────────────────────────────────────────────────────


def _ws(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def _scenario(
    name: str,
    description: str,
    metrics: dict[str, MetricValue],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    passed = all(
        float(metrics.get(key, 0.0)) >= threshold
        for key, threshold in thresholds.items()
    )
    return {
        "name": name,
        "description": description,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
    }


if __name__ == "__main__":
    import json as _json

    report = run_all_scenarios()
    print(f"suite: {report['suite']}")
    print(f"passed: {report['passed']}")
    print(f"duration_ms: {report['duration_ms']}")
    for s in report["scenarios"]:
        status = "PASS" if s["passed"] else "FAIL"
        print(f"\n[{status}] {s['name']}")
        print(f"  {s['description']}")
        for k, v in s["metrics"].items():
            t = s["thresholds"].get(k, "")
            print(f"  {k}: {v}  (threshold: {t})")
    if not report["passed"]:
        raise SystemExit(1)
