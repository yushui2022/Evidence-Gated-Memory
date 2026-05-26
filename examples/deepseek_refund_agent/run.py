"""DeepSeek-backed refund-agent demo for Evidence-Gated Memory.

Default mode is deterministic and needs no API key:
    python examples/deepseek_refund_agent/run.py --mock

Real DeepSeek mode reads the key from the environment:
    set DEEPSEEK_API_KEY=...
    python examples/deepseek_refund_agent/run.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.schemas.builtin import REFUND


WORKSPACE = Path(__file__).parent / "workspace"


class ClaimWriter(Protocol):
    def claim(self, task: str, context: dict) -> str:
        ...


class ScriptedClaimWriter:
    def claim(self, task: str, context: dict) -> str:
        if task == "eligibility":
            return "Order ORD-123 is eligible for refund under the 14-day policy"
        if task == "premature_completion":
            return "Refund for ORD-123 is completed"
        if task == "completion":
            return "Refund for ORD-123 has been executed via REF-9001"
        return "No claim"


class DeepSeekClaimWriter:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def claim(self, task: str, context: dict) -> str:
        prompt = (
            "You are writing short factual claims for an evidence-gated refund agent. "
            "Return JSON only with shape {\"claim\":\"...\"}. "
            "Do not include facts not present in the provided context."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"task": task, "context": context}, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 120,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API error {exc.code}: {body}") from exc
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)["claim"]


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _writer(args: argparse.Namespace) -> ClaimWriter:
    if args.mock:
        return ScriptedClaimWriter()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set; falling back to --mock mode.", file=sys.stderr)
        return ScriptedClaimWriter()
    return DeepSeekClaimWriter(
        api_key,
        model=os.environ.get("DEEPSEEK_MODEL", args.model),
        base_url=os.environ.get("DEEPSEEK_API_BASE", args.base_url),
    )


def run(args: argparse.Namespace) -> int:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)

    writer = _writer(args)
    memory = EvidenceGatedMemory(workspace=WORKSPACE, domain_schema=REFUND)
    try:
        memory.record_event(role="user", content="Please process the refund for ORD-123.")

        _section("STEP 1 - LLM proposes eligibility before evidence")
        claim = writer.claim("eligibility", {"user_request": "refund ORD-123"})
        rejected = memory.assert_fact(claim, claim_type="refund_eligibility")
        print(f"claim   : {claim}")
        print(f"accepted: {rejected.accepted}")
        print(f"reason  : {rejected.rejection_reason}")
        print(f"action  : {rejected.suggested_action}")

        _section("STEP 2 - gather evidence")
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
            metadata={"order_id": "ORD-123", "customer_id": "CUST-42"},
        )
        policy_ref = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="Standard refund policy: full refund within 14 days of purchase.",
            metadata={"policy_version": "v2026-01"},
        )

        _section("STEP 3 - LLM proposes eligibility with evidence")
        claim = writer.claim("eligibility", {
            "order": order_ref.summary,
            "policy": policy_ref.summary,
        })
        eligibility = memory.assert_fact(
            claim,
            claim_type="refund_eligibility",
            evidence=[order_ref, policy_ref],
            metadata={"order_id": "ORD-123"},
        )
        print(f"claim   : {claim}")
        print(f"accepted: {eligibility.accepted}")

        _section("STEP 4 - LLM prematurely claims completion")
        claim = writer.claim("premature_completion", {"known_facts": memory.build_context(query="ORD-123")})
        premature = memory.assert_fact(claim, claim_type="refund_completed")
        print(f"claim   : {claim}")
        print(f"accepted: {premature.accepted}")
        print(f"reason  : {premature.rejection_reason}")

        _section("STEP 5 - attach refund_api response and assert completion")
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
            metadata={"refund_id": "REF-9001", "order_id": "ORD-123"},
        )
        claim = writer.claim("completion", {"refund_api_response": refund_ref.summary})
        completion = memory.assert_fact(claim, claim_type="refund_completed", evidence=[refund_ref])
        print(f"claim   : {claim}")
        print(f"accepted: {completion.accepted}")

        _section("STEP 6 - final context")
        print(memory.build_context(query="ORD-123", max_facts=5))
        return 0 if completion.accepted else 1
    finally:
        memory.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use deterministic scripted claim writer.")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
