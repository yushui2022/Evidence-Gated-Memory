"""Real tau-bench A/B comparison: baseline vs. EGM, using DeepSeek.

Run a single tau-bench retail task with and without EGM as the memory layer.
Measures task pass rate, context size, and evidence coverage.

Usage:
  set DEEPSEEK_API_KEY=sk-...
  python benchmarks/tau_bench/run_ab.py --task 0
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND

API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
if API_KEY:
    os.environ.setdefault("DEEPSEEK_API_KEY", API_KEY)
    os.environ.setdefault("OPENAI_API_KEY", API_KEY)  # LiteLLM fallback for openai provider
MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
PROVIDER = "deepseek"  # LiteLLM provider name for DeepSeek

# Map tau-bench retail tools → EGM evidence types
TOOL_EVIDENCE_MAP = {
    "get_order_details": "order_record",
    "get_user_details": "order_record",
    "get_product_details": "order_record",
    "find_user_id_by_email": "order_record",
    "find_user_id_by_name_zip": "order_record",
    "list_all_product_types": "refund_policy",
    "calculate": "refund_policy",
    "cancel_pending_order": "refund_api_response",
    "return_delivered_order_items": "refund_api_response",
    "exchange_delivered_order_items": "refund_api_response",
    "modify_pending_order_items": "refund_api_response",
    "modify_pending_order_payment": "refund_api_response",
    "modify_pending_order_address": "refund_api_response",
    "modify_user_address": "refund_api_response",
    "transfer_to_human_agents": "refund_api_response",
}

# Map agent text intent keywords → EGM claim types.
# Action verbs (cancel/return/exchange/refund) → refund_completed
# Inquiry verbs (lookup/search/check) → refund_eligibility
INTENT_TO_CLAIM_TYPE = {
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


def _classify_intent(text: str) -> str:
    """Classify agent intent from text content for claim_type selection."""
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


def _require_api_key() -> None:
    if os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return
    raise SystemExit(
        "tau-bench A/B requires a model API key. Set DEEPSEEK_API_KEY before running."
    )


# ── EGM-aware agent ──────────────────────────────────────────────────────────

class EGMToolCallingAgent:
    """Wraps the tau-bench ToolCallingAgent, recording tool results as EGM evidence
    and injecting EGM context into the agent's message history."""

    def __init__(self, tools_info, wiki, model, provider, temperature=0.0):
        from tau_bench.agents.tool_calling_agent import ToolCallingAgent
        self._base = ToolCallingAgent(tools_info, wiki, model, provider, temperature)
        self.memory: EvidenceGatedMemory | None = None
        self._task_node: Any = None
        self._task_id: str = ""
        self._evidence_refs: list[str] = []
        self._tool_calls_count: int = 0
        self._facts_asserted: int = 0
        self._facts_rejected: int = 0
        self._rejection_reasons: list[str] = []

    def solve(self, env, task_index=None, max_num_steps=30):
        """Run the agent loop with EGM evidence recording."""
        from litellm import completion
        from tau_bench.types import RESPOND_ACTION_NAME, Action
        from tau_bench.agents.tool_calling_agent import message_to_action

        # Set up EGM workspace
        workspace = Path(tempfile.mkdtemp(prefix="egm_tau_"))
        self.memory = EvidenceGatedMemory(workspace, REFUND)

        env_res = env.reset(task_index=task_index)
        obs = env_res.observation
        task = env_res.info.task
        self._task_id = f"tau:{task.user_id}:{task_index}"
        total_cost = 0.0
        reward = 0.0

        # Create EGM task node
        self._task_node = self.memory.create_task_node(
            self._task_id,
            "eligibility_check",
            task.instruction[:120],
            anchors={"user_id": task.user_id, "task_index": str(task_index or 0)},
        )

        messages = [
            {"role": "system", "content": env.wiki},
            {"role": "user", "content": obs},
        ]

        for step in range(max_num_steps):
            res = completion(
                messages=messages,
                model=self._base.model,
                custom_llm_provider=self._base.provider,
                tools=self._base.tools_info,
                temperature=self._base.temperature,
            )
            next_msg = res.choices[0].message.model_dump()
            total_cost += res._hidden_params.get("response_cost", 0) or 0
            action = message_to_action(next_msg)
            env_response = env.step(action)
            reward = env_response.reward

            if action.name != RESPOND_ACTION_NAME:
                # Tool call → record as EGM evidence
                self._tool_calls_count += 1
                self._record_evidence(action, env_response)

                next_msg["tool_calls"] = next_msg["tool_calls"][:1]
                messages.extend([
                    next_msg,
                    {
                        "role": "tool",
                        "tool_call_id": next_msg["tool_calls"][0]["id"],
                        "name": next_msg["tool_calls"][0]["function"]["name"],
                        "content": env_response.observation,
                    },
                ])
            else:
                # Respond → gate as fact assertion
                self._gate_respond(action)
                messages.extend([
                    next_msg,
                    {"role": "user", "content": env_response.observation},
                ])

            if env_response.done:
                break

        # Build EGM context for comparison
        egm_ctx = ""
        if self.memory:
            self.memory.transition_node(
                self._task_node.id,
                TaskNodeStatus.DONE,
                evidence=self._evidence_refs,
            )
            egm_ctx = self.memory.build_context(
                query=task.instruction, task_id=self._task_id
            )

        raw_msgs_json = json.dumps(messages)

        return {
            "reward": reward,
            "total_cost": total_cost,
            "steps": step + 1,
            "messages_count": len(messages),
            "raw_tokens_est": len(raw_msgs_json) // 3,
            "egm": {
                "evidence_recorded": len(self._evidence_refs),
                "tool_calls": self._tool_calls_count,
                "facts_asserted": self._facts_asserted,
                "facts_rejected": self._facts_rejected,
                "rejection_reasons": self._rejection_reasons,
                "context_tokens_est": len(egm_ctx) // 3,
                "context_compression": (
                    round(len(egm_ctx) / max(len(raw_msgs_json), 1), 3)
                ),
            },
            "task_id": self._task_id,
            "workspace": str(workspace),
        }

    def _record_evidence(self, action, env_response):
        if not self.memory or action.name not in TOOL_EVIDENCE_MAP:
            return
        evidence_type = TOOL_EVIDENCE_MAP[action.name]
        source_systems = {
            "order_record": "order_api",
            "refund_policy": "policy_db",
            "refund_api_response": "refund_api",
        }
        try:
            ev = self.memory.record_evidence(
                evidence_type=evidence_type,
                source=action.name,
                source_system=source_systems.get(evidence_type, "order_api"),
                content=json.dumps({
                    "tool": action.name,
                    "kwargs": action.kwargs,
                    "result": env_response.observation,
                }),
                metadata={"tool_name": action.name, "task_id": self._task_id},
            )
            self._evidence_refs.append(ev.id)
            self.memory.attach_evidence_to_node(self._task_node.id, ev.id)
        except (ValueError, KeyError):
            pass

    def _gate_respond(self, action):
        if not self.memory:
            return
        content = action.kwargs.get("content", "")
        intent = _classify_intent(content)
        claim_type = INTENT_TO_CLAIM_TYPE.get(intent, "refund_eligibility")
        try:
            result = self.memory.assert_fact(
                f"{self._task_id}: {content[:200]}",
                claim_type=claim_type,
                evidence=self._evidence_refs,
            )
            if result.accepted and result.fact:
                self._facts_asserted += 1
                self.memory.attach_fact_to_node(self._task_node.id, result.fact.id)
            else:
                self._facts_rejected += 1
                self._rejection_reasons.append(result.gate.rejection_reason)
        except (ValueError, KeyError):
            self._facts_rejected += 1

    def close(self):
        if self.memory:
            self.memory.close()


# ── baseline agent (standard tau-bench, no EGM) ──────────────────────────────

def run_baseline(env, task_index=0, max_steps=30) -> dict:
    """Run standard ToolCallingAgent without EGM."""
    from litellm import completion
    from tau_bench.types import RESPOND_ACTION_NAME, Action
    from tau_bench.agents.tool_calling_agent import message_to_action

    env_res = env.reset(task_index=task_index)
    obs = env_res.observation
    total_cost = 0.0
    reward = 0.0
    messages = [
        {"role": "system", "content": env.wiki},
        {"role": "user", "content": obs},
    ]

    for step in range(max_steps):
        res = completion(
            messages=messages,
            model=MODEL,
            custom_llm_provider=PROVIDER,
            tools=env.tools_info,
            temperature=0.0,
        )
        next_msg = res.choices[0].message.model_dump()
        total_cost += res._hidden_params.get("response_cost", 0) or 0
        action = message_to_action(next_msg)
        env_response = env.step(action)
        reward = env_response.reward

        if action.name != RESPOND_ACTION_NAME:
            next_msg["tool_calls"] = next_msg["tool_calls"][:1]
            messages.extend([
                next_msg,
                {
                    "role": "tool",
                    "tool_call_id": next_msg["tool_calls"][0]["id"],
                    "name": next_msg["tool_calls"][0]["function"]["name"],
                    "content": env_response.observation,
                },
            ])
        else:
            messages.extend([
                next_msg,
                {"role": "user", "content": env_response.observation},
            ])

        if env_response.done:
            break

    raw_json = json.dumps(messages)
    return {
        "reward": reward,
        "total_cost": total_cost,
        "steps": step + 1,
        "messages_count": len(messages),
        "raw_tokens_est": len(raw_json) // 3,
    }


# ── main A/B runner ──────────────────────────────────────────────────────────

def run_ab(task_index: int = 0) -> dict:
    """Run baseline + EGM on the same tau-bench task, compare."""
    _require_api_key()
    from tau_bench.envs.retail.env import MockRetailDomainEnv

    print(f"Loading tau-bench retail env for task {task_index}...")

    def _make_env(idx: int):
        return MockRetailDomainEnv(
            user_strategy="llm",
            user_model=MODEL,
            user_provider=PROVIDER,
            task_split="test",
            task_index=idx,
        )

    env_baseline = _make_env(task_index)
    env_egm = _make_env(task_index)

    print(f"Task: {env_baseline.task.instruction[:120]}...")

    # Run BASELINE (no EGM)
    print("\n── BASELINE (no EGM) ──")
    t0 = time.perf_counter()
    baseline = run_baseline(env_baseline, task_index=task_index)
    baseline["duration_s"] = round(time.perf_counter() - t0, 1)

    # Run EGM
    print("\n── EGM (evidence-gated) ──")
    t0 = time.perf_counter()
    egm_agent = EGMToolCallingAgent(
        tools_info=env_egm.tools_info,
        wiki=env_egm.wiki,
        model=MODEL,
        provider=PROVIDER,
    )
    egm = egm_agent.solve(env_egm, task_index=task_index)
    egm_agent.close()
    egm["duration_s"] = round(time.perf_counter() - t0, 1)

    result = {
        "task_index": task_index,
        "task": env_baseline.task.instruction[:200],
        "model": MODEL,
        "baseline": baseline,
        "egm": {k: v for k, v in egm.items() if k != "workspace"},
    }

    return result


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="tau-bench A/B: baseline vs EGM")
    parser.add_argument("--task", type=int, default=0, help="Task index to run")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--batch", type=int, nargs=2, metavar=("START", "END"),
                        help="Batch run tasks from START to END (inclusive)")
    parser.add_argument("--json-out", type=str, default="", help="Write JSON results to file")
    args = parser.parse_args()

    print(f"Model: {MODEL}")
    print(f"API: {BASE_URL}")
    print()

    if args.batch:
        start, end = args.batch
        results = []
        BATCH_DELAY = 4  # seconds between tasks (DeepSeek rate limit)
        MAX_RETRIES = 2
        for ti in range(start, end + 1):
            print(f"\n{'='*60}")
            print(f"=== TASK {ti} ({(ti - start) + 1}/{end - start + 1}) ===")
            print(f"{'='*60}")
            r = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    r = run_ab(task_index=ti)
                    results.append(r)
                    b = r["baseline"]
                    e = r["egm"]
                    print(f"  b: r={b['reward']} s={b['steps']} t={b['raw_tokens_est']}")
                    em = e.get("egm", {})
                    print(f"  e: r={e['reward']} s={e['steps']} ctx={em.get('context_tokens_est','?')} "
                          f"ev={em.get('evidence_recorded','?')} f_ok={em.get('facts_asserted','?')} "
                          f"f_rej={em.get('facts_rejected','?')}")
                    break
                except Exception as exc:
                    msg = str(exc)
                    if "InternalServerError" in msg or "rate" in msg.lower() or "EOF" in msg:
                        if attempt < MAX_RETRIES:
                            wait = BATCH_DELAY * (attempt + 1) * 2
                            print(f"  Rate limited, retry {attempt+1}/{MAX_RETRIES} after {wait}s...")
                            time.sleep(wait)
                            continue
                    print(f"  FAILED: {exc}")
                    results.append({"task_index": ti, "error": str(exc)})
            if ti < end:
                time.sleep(BATCH_DELAY)

        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            print(f"\nWrote {len(results)} results to {args.json_out}")

        # Print summary table
        print("\n" + "=" * 60)
        print("BATCH SUMMARY")
        print("=" * 60)
        print(f"{'#':>3} {'B_r':>5} {'E_r':>5} {'Ev':>4} {'f_ok':>5} {'f_rej':>5} {'ctx':>6} {'raw':>6} {'comp':>6}")
        for r in results:
            if "error" in r:
                print(f"{r['task_index']:>3} {'ERR':>5} {r['error'][:50]}")
            else:
                b = r["baseline"]
                e = r["egm"]
                em = e.get("egm", {})
                ctx = em.get("context_tokens_est", 0)
                raw = e.get("raw_tokens_est", b.get("raw_tokens_est", 1))
                comp = ctx / max(raw, 1)
                print(f"{r['task_index']:>3} {b['reward']:>5} {e['reward']:>5} "
                      f"{em.get('evidence_recorded',0):>4} {em.get('facts_asserted',0):>5} "
                      f"{em.get('facts_rejected',0):>5} {ctx:>6} {raw:>6} {comp:>6.3f}")
    else:
        result = run_ab(task_index=args.task)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            b = result["baseline"]
            e = result["egm"]
            print("\n" + "=" * 60)
            print("A/B COMPARISON")
            print("=" * 60)
            print(f"\n{'Metric':<35} {'Baseline':>10} {'EGM':>10}")
            print("-" * 55)
            print(f"{'Reward':<35} {b['reward']:>10} {e['reward']:>10}")
            print(f"{'Steps':<35} {b['steps']:>10} {e['steps']:>10}")
            print(f"{'Messages':<35} {b['messages_count']:>10} {e['messages_count']:>10}")
            print(f"{'Cost ($)':<35} {b['total_cost']:>10.4f} {e['total_cost']:>10.4f}")
            print(f"{'Duration (s)':<35} {b['duration_s']:>10} {e['duration_s']:>10}")
            print(f"{'Raw tokens (est)':<35} {b['raw_tokens_est']:>10} {e['raw_tokens_est']:>10}")
            egm_meta = e.get("egm", {})
            if egm_meta:
                print(f"{'EGM context tokens (est)':<35} {'-':>10} {egm_meta.get('context_tokens_est', 0):>10}")
                print(f"{'Evidence recorded':<35} {'-':>10} {egm_meta.get('evidence_recorded', 0):>10}")
                print(f"{'Facts asserted':<35} {'-':>10} {egm_meta.get('facts_asserted', 0):>10}")
                print(f"{'Facts rejected':<35} {'-':>10} {egm_meta.get('facts_rejected', 0):>10}")
