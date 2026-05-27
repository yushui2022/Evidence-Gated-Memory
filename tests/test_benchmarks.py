"""Local benchmark regression tests."""

from __future__ import annotations

from benchmarks.local_benchmarks import run_all_benchmarks


def test_local_benchmark_suite_passes(tmp_path) -> None:
    result = run_all_benchmarks(tmp_path / "benchmarks")

    assert result["passed"]
    names = {item["name"] for item in result["benchmarks"]}
    assert names == {
        "longmemeval_s_hard_anchor",
        "locomo_style_semantic_pyramid",
        "beam_lite_hard_anchor_pressure",
        "false_done_gate_benchmark",
    }

    by_name = {item["name"]: item for item in result["benchmarks"]}
    assert by_name["longmemeval_s_hard_anchor"]["metrics"]["evidence_source_coverage"] == 1.0
    assert by_name["beam_lite_hard_anchor_pressure"]["metrics"]["target_source_coverage"] == 1.0
    assert by_name["false_done_gate_benchmark"]["metrics"]["actionable_rejection_rate"] == 1.0
