"""Generate deterministic EGM benchmark snapshots.

This script is the P0 benchmark artifact generator. It runs only local,
deterministic probes and writes both JSON and Markdown summaries. It never calls
an external model API.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from benchmarks.adversarial_probes import run_all_adversarial  # noqa: E402
from benchmarks.local_benchmarks import run_all_benchmarks  # noqa: E402
from benchmarks.scenario_probes import run_all_scenarios  # noqa: E402
from benchmarks.tau_bench.adapter import run_smoke_test as run_tau_smoke  # noqa: E402


def build_snapshot(workspace_root: Path | None = None) -> dict[str, Any]:
    """Run deterministic benchmark suites and return a serializable snapshot."""
    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_snapshot_") as tmp:
            return build_snapshot(Path(tmp))

    workspace_root.mkdir(parents=True, exist_ok=True)
    suites = [
        run_all_benchmarks(workspace_root / "local"),
        run_all_adversarial(workspace_root / "adversarial"),
        run_all_scenarios(workspace_root / "scenarios"),
        run_tau_smoke(workspace_root / "tau_smoke"),
    ]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_type": "deterministic-local",
        "note": (
            "Local deterministic EGM correctness probes. These are not official "
            "leaderboard scores and do not call external model APIs."
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summary": _summarize(suites),
        "suites": suites,
    }


def write_markdown(snapshot: dict[str, Any], path: Path) -> None:
    """Write a compact Markdown report for README/release note consumption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = snapshot["summary"]
    lines = [
        "# EGM Deterministic Benchmark Snapshot",
        "",
        f"Generated: `{snapshot['generated_at']}`",
        "",
        snapshot["note"],
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Suites passed | {summary['passed_suites']} / {summary['total_suites']} |",
        f"| Checks passed | {summary['passed_checks']} / {summary['total_checks']} |",
        f"| Overall passed | {summary['passed']} |",
        "",
        "## Suites",
        "",
        "| Suite | Passed | Checks | Duration ms |",
        "|---|---:|---:|---:|",
    ]

    for suite in snapshot["suites"]:
        suite_name = suite.get("suite") or suite.get("name")
        checks = _suite_checks(suite)
        lines.append(
            f"| `{suite_name}` | {suite.get('passed')} | {checks} | {suite.get('duration_ms', '')} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This snapshot is a release correctness guard for EGM-native behavior.",
            "- It is not a tau-bench, tau2-bench, LongMemEval, LoCoMo, or MemoryAgentBench leaderboard score.",
            "- Public reports must pair these numbers with the benchmark decision protocol.",
            "",
            "Related document: `docs/benchmark-decision-protocol.md`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _summarize(suites: list[dict[str, Any]]) -> dict[str, Any]:
    total_checks = sum(_suite_checks(suite) for suite in suites)
    passed_checks = sum(_suite_passed_checks(suite) for suite in suites)
    passed_suites = sum(1 for suite in suites if suite.get("passed"))
    return {
        "passed": all(bool(suite.get("passed")) for suite in suites),
        "total_suites": len(suites),
        "passed_suites": passed_suites,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
    }


def _suite_items(suite: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("benchmarks", "probes", "scenarios"):
        items = suite.get(key)
        if isinstance(items, list):
            return items
    return [suite]


def _suite_checks(suite: dict[str, Any]) -> int:
    return len(_suite_items(suite))


def _suite_passed_checks(suite: dict[str, Any]) -> int:
    return sum(1 for item in _suite_items(suite) if item.get("passed"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic EGM benchmark snapshot.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Optional temporary workspace root for benchmark databases.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "reports" / "deterministic_benchmark_snapshot.json",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ROOT / "reports" / "deterministic_benchmark_snapshot.md",
    )
    args = parser.parse_args(argv)

    snapshot = build_snapshot(args.workspace_root)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(snapshot, args.md_out)

    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    return 0 if snapshot["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
