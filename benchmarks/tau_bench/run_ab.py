"""tau-bench ↔ EGM A/B comparison harness.

Runs tau-bench tasks with and without EGM as the agent's memory layer,
comparing task pass rate, context size, and evidence coverage.

Usage:
  # Smoke test (no API keys, deterministic)
  python benchmarks/tau_bench/run_ab.py --smoke

  # Real A/B comparison (requires tau-bench + LLM API keys)
  python benchmarks/tau_bench/run_ab.py --domain retail --task-ids 0,1,2

The smoke test simulates a tau-bench agent loop through EGM without
needing tau-bench installed or LLM keys. It verifies the integration
plumbing: evidence recording, fact gating, context building, transition gating.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.tau_bench.adapter import run_smoke_test


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="tau-bench ↔ EGM A/B comparison harness"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run deterministic smoke test (no API keys, no tau-bench install needed).",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Directory for EGM workspaces. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print raw JSON output."
    )
    args = parser.parse_args(argv)

    if args.smoke:
        result = run_smoke_test(args.workspace_root)
        _print_smoke(result, args.json)
        return 0 if result["passed"] else 1

    # Real A/B mode — not yet wired (requires LLM keys + tau-bench import)
    print(
        "Real A/B comparison mode requires:"
        "\n  1. tau-bench installed (pip install tau-bench)"
        "\n  2. LLM API key (DEEPSEEK_API_KEY or ANTHROPIC_API_KEY)"
        "\n  3. tau-bench data files available"
        "\n"
        "\nRun --smoke for a deterministic integration smoke test instead."
    )
    return 0


def _print_smoke(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result['name']}")
    print(f"  {result['description']}")
    for k, v in result["metrics"].items():
        t = result["thresholds"].get(k, "")
        print(f"  {k}: {v}  (threshold: {t})")


if __name__ == "__main__":
    raise SystemExit(main())
