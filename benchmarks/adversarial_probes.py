"""Adversarial probes for Evidence-Gated Memory.

These are *attack-vector* tests: each one deliberately tries to bypass, poison,
or circumvent EGM's gates, then verifies the gate held.

They are deterministic, no API keys needed, and runnable in CI. The convincing
story is not "EGM scores 1.00 on its own surface" — it's "EGM blocks all 10
attack vectors we threw at it."
"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from evidence_gated_memory import (
    Evidence,
    EvidenceGatedMemory,
    Fact,
    FactKind,
    TaskNodeStatus,
)
from evidence_gated_memory.core.models import Claim, GateResult
from evidence_gated_memory.schemas.builtin import REFUND


MetricValue = int | float | bool | str


# ── suite runner ────────────────────────────────────────────────────────────


def run_all_adversarial(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    """Run all adversarial probes and return JSON-serializable results."""
    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_adv_") as tmp:
            return _run(Path(tmp))
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _run(workspace_root)


def _run(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    probes = [
        probe_1_llm_evidence_rejected,
        probe_2_expired_evidence_blocked,
        probe_3_source_system_allowlist,
        probe_4_commit_fact_requires_gate_result,
        probe_5_transition_done_without_evidence_blocked,
        probe_6_phantom_evidence_attach_rejected,
        probe_7_invalidated_fact_attach_rejected,
        probe_8_cascading_invalidation_on_revoke,
        probe_9_unknown_evidence_type_rejected,
        probe_10_unknown_claim_type_rejected,
    ]
    results = [probe(root) for probe in probes]
    return {
        "suite": "egm-adversarial-probes",
        "note": "Attack-vector tests. Each probe tries to bypass EGM's gates and verifies the gate held.",
        "passed": all(r["passed"] for r in results),
        "blocked": sum(r["metrics"].get("attack_blocked", 0) for r in results),
        "total": len(results),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "probes": results,
    }


# ── probe implementations ───────────────────────────────────────────────────


def probe_1_llm_evidence_rejected(root: Path) -> dict[str, Any]:
    """LLM-sourced evidence must never ground a fact.

    Attack: record evidence with source_system='llm', try to assert a fact with it.
    Expected: gate rejects with 'llm_output_not_as_source'.
    """
    memory = EvidenceGatedMemory(_ws(root, "p1"), REFUND)
    try:
        llm_ev = memory.record_evidence(
            evidence_type="order_record",
            source="llm",
            source_system="llm",
            content="The LLM thinks ORD-1 is PAID.",
        )
        result = memory.assert_fact(
            "ORD-1 is refundable",
            claim_type="refund_eligibility",
            evidence=[llm_ev],
        )
        blocked = not result.accepted
        correct_gate = any(
            "llm_output_not_as_source" == v.gate for v in result.gate.violations
        )
        return _probe(
            "1. LLM evidence rejected",
            "Evidence from source_system='llm' must never ground a fact.",
            passed=blocked and correct_gate,
            metrics={
                "attack": "llm_sourced_evidence",
                "attack_blocked": int(blocked),
                "correct_gate_triggered": int(correct_gate),
                "fact_was_written": int(not blocked),
            },
        )
    finally:
        memory.close()


def probe_2_expired_evidence_blocked(root: Path) -> dict[str, Any]:
    """Expired required evidence must block fact assertion.

    Attack: backdate order_record past its expired_after (PT24H), assert a fact.
    Expected: gate rejects — STALE would be accepted (PT30M+), but EXPIRED must block.
    """
    memory = EvidenceGatedMemory(_ws(root, "p2"), REFUND)
    try:
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14-day refund window.",
        )
        # Backdate order_record to 25 hours ago (expired_after = PT24H, stale_after = PT30M)
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        order = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-1","status":"PAID"}',
            observed_at=old_time,
        )

        result = memory.assert_fact(
            "ORD-1 is refundable",
            claim_type="refund_eligibility",
            evidence=[order, policy],
        )
        blocked = not result.accepted
        has_expired_gate = any(
            "expired" in v.gate.lower() for v in result.gate.violations
        )
        return _probe(
            "2. Expired evidence blocked",
            "Expired required evidence must block fact assertion.",
            passed=blocked and has_expired_gate,
            metrics={
                "attack": "expired_required_evidence",
                "attack_blocked": int(blocked),
                "expired_gate_triggered": int(has_expired_gate),
                "fact_was_written": int(not blocked),
            },
        )
    finally:
        memory.close()


def probe_3_source_system_allowlist(root: Path) -> dict[str, Any]:
    """Evidence from a non-allowlisted source_system must be rejected.

    Attack: record evidence_type 'order_record' with source_system='untrusted_hack'.
    The REFUND schema declares order_record.source_systems = ['order_api'].
    Expected: gate rejects with 'source_system_not_allowed'.
    """
    memory = EvidenceGatedMemory(_ws(root, "p3"), REFUND)
    try:
        # record_evidence itself does NOT validate source_system allowlist
        # (it stores raw evidence and trusts the gate layer).
        # The gate check happens at assert_fact time.
        bad = memory.record_evidence(
            evidence_type="order_record",
            source="untrusted_hack",
            source_system="untrusted_hack",
            content="Pretend this came from order_api.",
        )
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14 days.",
        )
        result = memory.assert_fact(
            "ORD-1 is refundable",
            claim_type="refund_eligibility",
            evidence=[bad, policy],
        )
        blocked = not result.accepted
        correct_gate = any(
            "source_system_not_allowed" == v.gate for v in result.gate.violations
        )
        return _probe(
            "3. Source-system allowlist enforced",
            "Evidence from a non-allowlisted source must be rejected at gate time.",
            passed=blocked and correct_gate,
            metrics={
                "attack": "untrusted_source_system",
                "attack_blocked": int(blocked),
                "correct_gate_triggered": int(correct_gate),
                "fact_was_written": int(not blocked),
            },
        )
    finally:
        memory.close()


def probe_4_commit_fact_requires_gate_result(root: Path) -> dict[str, Any]:
    """commit_fact() without an accepted GateResult must raise ValueError.

    Attack: call commit_fact(claim) directly, skipping the gate.
    Expected: ValueError raised.
    """
    memory = EvidenceGatedMemory(_ws(root, "p4"), REFUND)
    try:
        claim = Claim(
            text="ORD-1 is refundable",
            claim_type="refund_eligibility",
            evidence_refs=["ref_nonexistent"],
        )
        attack_blocked = 0
        try:
            memory.commit_fact(claim)  # no gate_result → must raise
        except ValueError:
            attack_blocked = 1

        # Also verify: passing a rejected GateResult must raise
        gate = GateResult(accepted=False, claim_id=claim.id, violations=[])
        second_bypass_blocked = 0
        try:
            memory.commit_fact(claim, gate_result=gate)
        except ValueError:
            second_bypass_blocked = 1

        # Verify: passing a GateResult for a DIFFERENT claim must raise
        gate_ok = GateResult(accepted=True, claim_id=claim.id, violations=[])
        other_claim = Claim(
            text="something else",
            claim_type="refund_eligibility",
            evidence_refs=[],
        )
        mismatch_blocked = 0
        try:
            memory.commit_fact(other_claim, gate_result=gate_ok)
        except ValueError:
            mismatch_blocked = 1

        all_blocked = attack_blocked and second_bypass_blocked and mismatch_blocked
        return _probe(
            "4. commit_fact requires GateResult",
            "commit_fact must reject: no gate, rejected gate, or mismatched gate.",
            passed=bool(all_blocked),
            metrics={
                "attack": "bypass_gate_direct_commit",
                "attack_blocked": attack_blocked,
                "rejected_gate_blocked": second_bypass_blocked,
                "mismatched_gate_blocked": mismatch_blocked,
                "fact_was_written": int(not all_blocked),
            },
        )
    finally:
        memory.close()


def probe_5_transition_done_without_evidence_blocked(root: Path) -> dict[str, Any]:
    """Transitioning a refund_completion node to DONE without refund_api_response must be blocked.

    Attack: create a refund_completion node, try transition_node(DONE) without evidence.
    Expected: gate rejects, actionable message mentions refund_api_response.
    """
    memory = EvidenceGatedMemory(_ws(root, "p5"), REFUND)
    try:
        node = memory.create_task_node(
            "refund:ORD-5",
            "refund_completion",
            "Complete refund REF-5",
            anchors={"order_id": "ORD-5", "refund_id": "REF-5"},
        )
        result = memory.transition_node(node.id, TaskNodeStatus.DONE)
        blocked = not result.accepted
        actionable = (
            "refund_api_response" in result.rejection_reason
            and "refund_api" in result.suggested_action
        )
        # Now attach the missing evidence → must pass
        refund_ev = memory.record_evidence(
            evidence_type="refund_api_response",
            source="refund_api",
            source_system="refund_api",
            content='{"refund_id":"REF-5","status":"COMPLETED"}',
        )
        second = memory.transition_node(
            node.id,
            TaskNodeStatus.DONE,
            evidence=[refund_ev],
        )
        accepted_after = second.accepted
        return _probe(
            "5. DONE transition blocked without evidence",
            "refund_completion→DONE must be blocked, then accepted once evidence is attached.",
            passed=blocked and actionable and accepted_after,
            metrics={
                "attack": "transition_done_without_evidence",
                "attack_blocked": int(blocked),
                "actionable_rejection": int(actionable),
                "accepted_after_evidence": int(accepted_after),
            },
        )
    finally:
        memory.close()


def probe_6_phantom_evidence_attach_rejected(root: Path) -> dict[str, Any]:
    """Attaching a non-existent evidence id to a node must raise KeyError.

    Attack: create a node, call attach_evidence_to_node with a fake id.
    Expected: KeyError.
    """
    memory = EvidenceGatedMemory(_ws(root, "p6"), REFUND)
    try:
        node = memory.create_task_node(
            "refund:ORD-6",
            "eligibility_check",
            "Check ORD-6",
            anchors={"order_id": "ORD-6"},
        )
        attack_blocked = 0
        try:
            memory.attach_evidence_to_node(node.id, "ref_does_not_exist")
        except KeyError:
            attack_blocked = 1

        return _probe(
            "6. Phantom evidence attach rejected",
            "Attaching a nonexistent evidence ref must raise KeyError immediately.",
            passed=bool(attack_blocked),
            metrics={
                "attack": "phantom_evidence_ref",
                "attack_blocked": attack_blocked,
            },
        )
    finally:
        memory.close()


def probe_7_invalidated_fact_attach_rejected(root: Path) -> dict[str, Any]:
    """Attaching an already-invalidated fact to a node must raise ValueError.

    Attack: create a fact, invalidate it, then try attach_fact_to_node.
    Expected: ValueError.
    """
    memory = EvidenceGatedMemory(_ws(root, "p7"), REFUND)
    try:
        node = memory.create_task_node(
            "refund:ORD-7",
            "eligibility_check",
            "Check ORD-7",
            anchors={"order_id": "ORD-7"},
        )
        order = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-7","status":"PAID"}',
        )
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14 days.",
        )
        result = memory.assert_fact(
            "ORD-7 refundable",
            claim_type="refund_eligibility",
            evidence=[order, policy],
        )
        assert result.fact is not None

        # Invalidate by revoking the order evidence
        memory.revoke_evidence(order.id, reason="order was fraudulent")

        attack_blocked = 0
        try:
            memory.attach_fact_to_node(node.id, result.fact.id)
        except ValueError:
            attack_blocked = 1

        return _probe(
            "7. Invalidated fact attach rejected",
            "Attaching a fact that has been invalidated must raise ValueError.",
            passed=bool(attack_blocked),
            metrics={
                "attack": "attach_invalidated_fact",
                "attack_blocked": attack_blocked,
            },
        )
    finally:
        memory.close()


def probe_8_cascading_invalidation_on_revoke(root: Path) -> dict[str, Any]:
    """Revoking a parent evidence must cascade-invalidate all derived facts.

    Attack: build observed → derived fact chain, revoke the root evidence.
    Expected: the derived fact is also invalidated.
    """
    memory = EvidenceGatedMemory(_ws(root, "p8"), REFUND)
    try:
        # Build: order_record + refund_policy → observed fact
        order = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-8","status":"PAID"}',
        )
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14 days.",
        )
        observed = memory.assert_fact(
            "ORD-8 eligible",
            claim_type="refund_eligibility",
            evidence=[order, policy],
        )
        assert observed.fact is not None

        # Build derived fact on top
        refund_ev = memory.record_evidence(
            evidence_type="refund_api_response",
            source="refund_api",
            source_system="refund_api",
            content='{"refund_id":"REF-8","status":"COMPLETED"}',
        )
        derived = memory.assert_fact(
            "ORD-8 fully refunded",
            claim_type="refund_completed",
            kind=FactKind.DERIVED,
            depends_on=[observed.fact],
            evidence=[refund_ev],
        )
        assert derived.fact is not None

        # Attack: revoke the root order evidence
        invalidated_ids = memory.revoke_evidence(order.id, reason="order voided")

        observed_dead = observed.fact.id in invalidated_ids
        derived_dead = derived.fact.id in invalidated_ids

        obs_after = memory.store.get_fact(observed.fact.id)
        der_after = memory.store.get_fact(derived.fact.id)
        obs_nulled = obs_after is not None and obs_after.invalidated_at is not None
        der_nulled = der_after is not None and der_after.invalidated_at is not None

        cascade_worked = observed_dead and derived_dead and obs_nulled and der_nulled
        return _probe(
            "8. Cascading invalidation on evidence revoke",
            "Revoking root evidence must invalidate both the observed fact and its derived child.",
            passed=cascade_worked,
            metrics={
                "attack": "revoke_root_evidence",
                "attack_blocked": 1 if cascade_worked else 0,
                "observed_invalidated": int(observed_dead),
                "derived_invalidated": int(derived_dead),
                "cascade_depth": 2 if cascade_worked else (1 if observed_dead else 0),
            },
        )
    finally:
        memory.close()


def probe_9_unknown_evidence_type_rejected(root: Path) -> dict[str, Any]:
    """Recording evidence with an undeclared evidence_type must raise ValueError.

    Attack: call record_evidence with evidence_type='fake_type_not_in_schema'.
    Expected: ValueError raised BEFORE any ref file is written.
    """
    memory = EvidenceGatedMemory(_ws(root, "p9"), REFUND)
    try:
        attack_blocked = 0
        try:
            memory.record_evidence(
                evidence_type="fake_type_not_in_schema",
                source="somewhere",
                content="bogus evidence",
            )
        except ValueError:
            attack_blocked = 1

        return _probe(
            "9. Unknown evidence_type rejected at API edge",
            "record_evidence must reject undeclared types before writing to disk.",
            passed=bool(attack_blocked),
            metrics={
                "attack": "unknown_evidence_type",
                "attack_blocked": attack_blocked,
                "ref_file_written": int(not attack_blocked),
            },
        )
    finally:
        memory.close()


def probe_10_unknown_claim_type_rejected(root: Path) -> dict[str, Any]:
    """Asserting a fact with an undeclared claim_type must be rejected.

    Attack: call assert_fact with claim_type='fake_claim_not_in_schema'.
    Expected: rejected with 'unknown_claim_type' gate violation.
    """
    memory = EvidenceGatedMemory(_ws(root, "p10"), REFUND)
    try:
        order = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-10","status":"PAID"}',
        )
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14 days.",
        )
        attack_blocked = 0
        try:
            memory.assert_fact(
                "ORD-10 is something",
                claim_type="fake_claim_not_in_schema",
                evidence=[order, policy],
            )
        except ValueError:
            # #13 strict schema: propose_claim raises ValueError directly
            # for unknown claim_types — fail-closed at the API edge.
            attack_blocked = 1

        return _probe(
            "10. Unknown claim_type rejected at API edge",
            "assert_fact must reject undeclared claim_types before storing a claim row.",
            passed=bool(attack_blocked),
            metrics={
                "attack": "unknown_claim_type",
                "attack_blocked": attack_blocked,
                "fact_was_written": int(not attack_blocked),
            },
        )
    finally:
        memory.close()


# ── helpers ─────────────────────────────────────────────────────────────────


def _ws(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def _probe(
    name: str, description: str, passed: bool, metrics: dict[str, MetricValue]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": passed,
        "metrics": metrics,
    }


# ── entry point ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import json as _json

    report = run_all_adversarial()
    print(f"suite: {report['suite']}")
    print(f"passed: {report['passed']}")
    print(f"blocked: {report['blocked']}/{report['total']} attack vectors")
    print(f"duration_ms: {report['duration_ms']}")
    for p in report["probes"]:
        status = "PASS" if p["passed"] else "FAIL"
        print(f"\n[{status}] {p['name']}")
        print(f"  {p['description']}")
        for k, v in p["metrics"].items():
            print(f"  {k}: {v}")
    if not report["passed"]:
        raise SystemExit(1)
