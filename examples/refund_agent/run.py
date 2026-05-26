"""End-to-end refund-agent demo for Evidence-Gated Memory.

What this shows:

  1. A claim WITHOUT evidence is rejected with an actionable reason.
  2. A claim WITH evidence passes and becomes a Fact.
  3. The built context labels each fact with provenance + freshness.
  4. Revoking an evidence cascades — derived facts get invalidated automatically.

Run:
    python examples/refund_agent/run.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory, FactKind
from evidence_gated_memory.schemas.builtin import REFUND


WORKSPACE = Path(__file__).parent / "workspace"


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)

    memory = EvidenceGatedMemory(workspace=WORKSPACE, domain_schema=REFUND)

    memory.record_event(role="user", content="Please process the refund for ORD-123.")

    _section("STEP 1 — assert without evidence (should be rejected)")
    bad = memory.assert_fact(
        "Order ORD-123 is eligible for refund",
        claim_type="refund_eligibility",
    )
    print(f"accepted: {bad.accepted}")
    print(f"reason  : {bad.rejection_reason}")
    print(f"action  : {bad.suggested_action}")

    _section("STEP 2 — gather evidence from order_api and policy_db")
    order_ref = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content=json.dumps({
            "order_id": "ORD-123",
            "customer_id": "CUST-42",
            "amount": 199.0,
            "status": "PAID",
            "purchased_at": "2026-05-20T10:00:00Z",
        }, indent=2),
        summary="ORD-123 status=PAID amount=199 purchased 2026-05-20",
        metadata={"order_id": "ORD-123", "customer_id": "CUST-42"},
    )
    policy_ref = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="Standard refund policy: full refund within 14 days of purchase.",
        summary="14-day full refund window",
        metadata={"policy_version": "v2026-01"},
    )

    _section("STEP 3 — assert eligibility WITH evidence (should pass)")
    good = memory.assert_fact(
        "Order ORD-123 is eligible for refund under the 14-day policy",
        claim_type="refund_eligibility",
        evidence=[order_ref, policy_ref],
        metadata={"order_id": "ORD-123"},
    )
    print(f"accepted: {good.accepted}")
    if good.fact:
        print(f"fact_id : {good.fact.id}")

    _section("STEP 4 — try to claim DONE without a refund_api response (should fail)")
    premature = memory.assert_fact(
        "Refund for ORD-123 is completed",
        claim_type="refund_completed",
    )
    print(f"accepted: {premature.accepted}")
    print(f"reason  : {premature.rejection_reason}")
    print(f"action  : {premature.suggested_action}")

    _section("STEP 5 — attach refund_api response and re-assert DONE")
    refund_ref = memory.record_evidence(
        evidence_type="refund_api_response",
        source="refund_api",
        source_system="refund_api",
        content=json.dumps({
            "refund_id": "REF-9001",
            "order_id": "ORD-123",
            "status": "success",
            "amount": 199.0,
        }, indent=2),
        summary="refund REF-9001 status=success amount=199",
        metadata={"refund_id": "REF-9001", "order_id": "ORD-123"},
    )
    done = memory.assert_fact(
        "Refund for ORD-123 has been executed via REF-9001",
        claim_type="refund_completed",
        evidence=[refund_ref],
    )
    print(f"accepted: {done.accepted}")
    print(f"fact_id : {done.fact.id if done.fact else '-'}")

    _section("STEP 6 — derive a higher-level fact that depends on the previous one")
    if done.fact and good.fact:
        derived = memory.assert_fact(
            "Customer CUST-42 has been fully refunded for ORD-123",
            claim_type="refund_completed",          # reuse claim type for demo
            kind=FactKind.DERIVED,
            depends_on=[done.fact, good.fact],
        )
        print(f"accepted: {derived.accepted}")
        if not derived.accepted:
            print(f"reason  : {derived.rejection_reason}")

    _section("STEP 7 — build prompt context (note freshness tags)")
    print(memory.build_context(max_facts=5))

    _section("STEP 8 — revoke the order_record evidence and watch cascade")
    invalidated = memory.revoke_evidence(order_ref.id, reason="order record amended upstream")
    print(f"invalidated facts: {invalidated}")

    _section("STEP 9 — context after revocation")
    print(memory.build_context(max_facts=5))

    _section("STEP 10 — audit log (last 10 entries)")
    for entry in memory.audit_log(limit=10):
        print(f"- {entry['event_type']:18s} accepted={entry['accepted']} claim={entry['claim_id']} fact={entry['fact_id']}")

    memory.close()


if __name__ == "__main__":
    main()
