"""EGM ↔ tau-bench integration: evidence-gated memory adapter and A/B harness.

This module provides:
  - EGMTauAdapter: wraps a tau-bench Env, recording tool results as EGM evidence
  - run_ab_comparison: runs the same tau-bench task with/without EGM, comparing
    pass rate, context size, and evidence coverage

Run the smoke test (no API keys needed):
  python benchmarks/tau_bench/run_ab.py --smoke
"""

from benchmarks.tau_bench.adapter import EGMTauAdapter

__all__ = ["EGMTauAdapter"]
