"""τ²-bench A/B comparison: baseline vs. EGM, using DeepSeek.

Runs the same τ² retail task twice — once with the standard agent
(raw trajectory), once with EGM (evidence-gated context).

Usage:
  set DEEPSEEK_API_KEY=sk-...
  python benchmarks/tau2_bench/run_ab.py --task 0
  python benchmarks/tau2_bench/run_ab.py --task 0 --json
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

API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    print("DEEPSEEK_API_KEY not set. Set it before running.", file=sys.stderr)
    sys.exit(1)
os.environ.setdefault("DEEPSEEK_API_KEY", API_KEY)
os.environ.setdefault("OPENAI_API_KEY", API_KEY)

MODEL = "deepseek/deepseek-chat"

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_config(task_id: int) -> Any:
    """Build a TextRunConfig for a single τ²-bench retail task."""
    from tau2.data_model.simulation import TextRunConfig

    return TextRunConfig(
        domain="retail",
        agent="llm_agent",
        user="user_simulator",
        task_set_name="retail",
        task_split_name="test",
        task_ids=[str(task_id)],
        llm_agent=MODEL,
        llm_user=MODEL,
        num_trials=1,
        max_steps=30,
        max_errors=3,
        seed=42,
        save_to="",
    )


def _load_task(task_id: int) -> Any:
    """Load a specific τ² task by index."""
    from tau2.domains.retail.environment import get_tasks

    tasks = get_tasks("test")
    if task_id >= len(tasks):
        raise IndexError(f"task {task_id} out of range ({len(tasks)} tasks)")
    return tasks[task_id]


def _run_tau2_simulation(config: Any, task: Any, adapter: Any = None) -> dict[str, Any]:
    """Run a single τ²-bench simulation and return metrics.

    If `adapter` is an EGMTau2Adapter, the environment will be wrapped for
    EGM evidence recording. Post-simulation trajectory gating is performed
    before returning.
    """
    from tau2.runner.build import build_text_orchestrator

    t0 = time.perf_counter()

    orchestrator = build_text_orchestrator(config, task)

    # If adapter provided, swap environment with EGM wrapper.
    if adapter is not None:
        adapter.create_task_node()
        # The adapter already monkey-patched get_response in __init__.
        # We just need to swap the orchestrator's reference.
        orchestrator.environment = adapter.env

    sim = orchestrator.run()
    duration = time.perf_counter() - t0

    # Post-hoc gating if adapter is active.
    egm_metrics: dict[str, Any] = {}
    if adapter is not None and sim.messages:
        adapter.gate_trajectory(sim.messages)
        raw_json = json.dumps(
            [m.model_dump() if hasattr(m, "model_dump") else str(m)
             for m in sim.messages],
            default=str,
        )
        adapter.set_raw_trajectory_tokens(raw_json)
        adapter.build_egm_context()
        egm_metrics = adapter.metrics.to_dict()

    cost = _extract_cost(sim)
    reward = _extract_reward(sim)

    return {
        "reward": reward,
        "total_cost": cost,
        "steps": _count_steps(sim),
        "messages_count": len(sim.messages) if sim.messages else 0,
        "raw_tokens_est": _estimate_tokens(sim),
        "duration_s": round(duration, 1),
        **({"egm": egm_metrics} if egm_metrics else {}),
    }


def _extract_cost(sim: Any) -> float:
    """Extract total LLM cost from a SimulationRun."""
    if hasattr(sim, "agent_cost") and hasattr(sim, "user_cost"):
        return float(getattr(sim, "agent_cost", 0) or 0) + float(
            getattr(sim, "user_cost", 0) or 0
        )
    return 0.0


def _extract_reward(sim: Any) -> float:
    """Extract reward from a SimulationRun."""
    if hasattr(sim, "reward_info") and sim.reward_info:
        return float(getattr(sim.reward_info, "reward", 0.0) or 0.0)
    if hasattr(sim, "reward"):
        return float(sim.reward or 0.0)
    return 0.0


def _count_steps(sim: Any) -> int:
    """Count steps in a SimulationRun."""
    if hasattr(sim, "step_count"):
        return sim.step_count
    if hasattr(sim, "messages") and sim.messages:
        return len(sim.messages)
    return 0


def _estimate_tokens(sim: Any) -> int:
    """Rough token estimate from messages."""
    if not hasattr(sim, "messages") or not sim.messages:
        return 0
    raw = json.dumps(
        [m.model_dump() if hasattr(m, "model_dump") else str(m)
         for m in sim.messages],
        default=str,
    )
    return len(raw) // 3


# ── A/B runner ───────────────────────────────────────────────────────────────


def run_ab(task_index: int = 0) -> dict[str, Any]:
    """Run baseline + EGM on the same τ² task, compare."""
    from evidence_gated_memory import EvidenceGatedMemory
    from evidence_gated_memory.schemas.builtin import REFUND
    from benchmarks.tau2_bench.adapter import EGMTau2Adapter

    print(f"Loading τ²-bench retail task {task_index}...")
    task = _load_task(task_index)
    instruction = str(task.user_scenario) if hasattr(task, "user_scenario") else ""
    print(f"Task: {instruction[:120]}...")

    # ── BASELINE (no EGM) ──
    print("\n── BASELINE (no EGM) ──")
    config_b = _make_config(task_index)
    baseline = _run_tau2_simulation(config_b, task)

    # ── EGM (evidence-gated) ──
    print("\n── EGM (evidence-gated) ──")
    config_e = _make_config(task_index)
    task_e = _load_task(task_index)

    workspace = Path(tempfile.mkdtemp(prefix="egm_tau2_"))
    memory = EvidenceGatedMemory(workspace, REFUND)
    task_id = f"tau2:retail:test:{task_index}"

    # Build orchestrator first to get the environment.
    from tau2.runner.build import build_text_orchestrator

    orchestrator_e = build_text_orchestrator(config_e, task_e)

    # Wrap environment with EGM adapter.
    adapter = EGMTau2Adapter(
        orchestrator_e.environment,
        memory,
        task_id=task_id,
        task_instruction=instruction,
    )

    try:
        egm = _run_tau2_simulation(config_e, task_e, adapter=adapter)
    finally:
        adapter.close()

    return {
        "task_index": task_index,
        "task": instruction[:200],
        "model": MODEL,
        "baseline": baseline,
        "egm": {k: v for k, v in egm.items() if k != "workspace"},
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    # Force UTF-8 on Windows to avoid GBK encoding errors with τ² character
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="τ²-bench A/B: baseline vs EGM")
    parser.add_argument("--task", type=int, default=0, help="Task index to run")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--batch", type=int, nargs=2, metavar=("START", "END"),
                        help="Batch run tasks from START to END (inclusive)")
    parser.add_argument("--json-out", type=str, default="", help="Write JSON results to file")
    args = parser.parse_args()

    print(f"Model: {MODEL}")
    print(f"τ²-bench retail domain")
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
                    print(f"  e: r={e['reward']} s={e['steps']} ctx={em.get('context_token_estimate','?')} "
                          f"ev={em.get('tool_results_as_evidence','?')} f_ok={em.get('facts_asserted','?')} "
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
                ctx = em.get("context_token_estimate", 0)
                raw = em.get("raw_trajectory_token_estimate", e.get("raw_tokens_est", 1))
                comp = ctx / max(raw, 1)
                print(f"{r['task_index']:>3} {b['reward']:>5} {e['reward']:>5} "
                      f"{em.get('tool_results_as_evidence',0):>4} {em.get('facts_asserted',0):>5} "
                      f"{em.get('facts_rejected',0):>5} {ctx:>6} {raw:>6} {comp:>6.3f}")
    else:
        result = run_ab(task_index=args.task)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            b = result["baseline"]
            e = result["egm"]
            print("\n" + "=" * 60)
            print("τ²-BENCH A/B COMPARISON")
            print("=" * 60)
            print(f"\n{'Metric':<35} {'Baseline':>10} {'EGM':>10}")
            print("-" * 55)
            print(f"{'Reward':<35} {b['reward']:>10} {e['reward']:>10}")
            print(f"{'Steps':<35} {b['steps']:>10} {e['steps']:>10}")
            print(f"{'Messages':<35} {b['messages_count']:>10} {e['messages_count']:>10}")
            print(f"{'Cost ($)':<35} {b['total_cost']:>10.4f} {e['total_cost']:>10.4f}")
            print(f"{'Duration (s)':<35} {b['duration_s']:>10} {e['duration_s']:>10}")
            egm_meta = e.get("egm", {})
            if egm_meta:
                ctx_tokens = egm_meta.get("context_token_estimate", 0)
                raw_tokens = egm_meta.get("raw_trajectory_token_estimate", 0)
                ev_count = egm_meta.get("tool_results_as_evidence", 0)
                f_ok = egm_meta.get("facts_asserted", 0)
                f_rej = egm_meta.get("facts_rejected", 0)
                comp = egm_meta.get("context_compression_ratio", 0)
                print(f"{'EGM context tokens (est)':<35} {'-':>10} {ctx_tokens:>10}")
                print(f"{'Raw trajectory tokens (est)':<35} {'-':>10} {raw_tokens:>10}")
                print(f"{'Context compression':<35} {'-':>10} {comp:>10.3f}")
                print(f"{'Evidence recorded':<35} {'-':>10} {ev_count:>10}")
                print(f"{'Facts asserted':<35} {'-':>10} {f_ok:>10}")
                print(f"{'Facts rejected':<35} {'-':>10} {f_rej:>10}")
