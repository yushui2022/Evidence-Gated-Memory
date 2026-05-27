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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic local EGM benchmarks.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Optional directory for benchmark workspaces. Defaults to a temporary directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON output.")
    args = parser.parse_args(argv)

    result = run_all_benchmarks(args.workspace_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"suite: {result['suite']}")
        print(f"passed: {result['passed']}")
        print(f"duration_ms: {result['duration_ms']}")
        for item in result["benchmarks"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"\n[{status}] {item['name']}")
            print(item["description"])
            for key, value in item["metrics"].items():
                print(f"  {key}: {value}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
