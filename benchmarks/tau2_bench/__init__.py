"""EGM ↔ tau2-bench integration: evidence-gated memory adapter and A/B harness.

This module provides:
  - EGMTau2Adapter: wraps a tau2 Environment, recording tool results as EGM evidence
  - run_smoke_test: deterministic test, no API keys needed
  - run_ab: runs the same tau2 task with/without EGM, comparing metrics

Run the smoke test (no API keys needed):
  python benchmarks/tau2_bench/adapter.py
"""

from benchmarks.tau2_bench.adapter import EGMTau2Adapter

__all__ = ["EGMTau2Adapter"]
