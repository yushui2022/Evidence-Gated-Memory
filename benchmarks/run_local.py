"""Run EGM local benchmarks from a source checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from benchmarks.local_benchmarks import run_all_benchmarks  # noqa: E402
from benchmarks.adversarial_probes import run_all_adversarial  # noqa: E402
from benchmarks.scenario_probes import run_all_scenarios  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic local EGM benchmarks.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Optional directory for benchmark workspaces. Defaults to a temporary directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON output.")
    parser.add_argument("--adversarial-only", action="store_true", help="Run only adversarial probes.")
    parser.add_argument("--scenarios-only", action="store_true", help="Run only scenario probes.")
    args = parser.parse_args(argv)

    all_passed = True

    if args.adversarial_only:
        adv = run_all_adversarial(args.workspace_root)
        _print_result(adv, args.json)
        return 0 if adv["passed"] else 1

    if args.scenarios_only:
        sc = run_all_scenarios(args.workspace_root)
        _print_result(sc, args.json)
        return 0 if sc["passed"] else 1

    result = run_all_benchmarks(args.workspace_root)
    _print_result(result, args.json)
    all_passed = all_passed and result["passed"]

    adv = run_all_adversarial(args.workspace_root)
    _print_result(adv, args.json)
    all_passed = all_passed and adv["passed"]

    sc = run_all_scenarios(args.workspace_root)
    _print_result(sc, args.json)
    all_passed = all_passed and sc["passed"]

    return 0 if all_passed else 1


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"\nsuite: {result['suite']}")
    print(f"passed: {result['passed']}")
    print(f"duration_ms: {result['duration_ms']}")
    items = result.get("benchmarks") or result.get("probes") or result.get("scenarios") or []
    for item in items:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"\n[{status}] {item['name']}")
        print(f"  {item['description']}")
        for key, value in item["metrics"].items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
