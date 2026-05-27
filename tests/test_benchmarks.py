"""Local benchmark regression tests."""

from __future__ import annotations

from benchmarks.adversarial_probes import run_all_adversarial
from benchmarks.local_benchmarks import run_all_benchmarks
from benchmarks.scenario_probes import run_all_scenarios


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


def test_scenario_probes_all_pass(tmp_path) -> None:
    result = run_all_scenarios(tmp_path / "scenarios")

    assert result["passed"]
    names = {s["name"] for s in result["scenarios"]}
    assert names == {
        "refund_full_lifecycle",
        "refund_multi_order_concurrency",
        "refund_partial_evidence_rejection_loop",
        "coding_file_to_diagnosis",
        "coding_stale_rejection",
        "coding_multi_file_workflow",
    }

    by_name = {s["name"]: s for s in result["scenarios"]}
    # Refund scenarios
    lifecycle = by_name["refund_full_lifecycle"]
    assert lifecycle["metrics"]["premature_eligibility_rejection_rate"] == 1.0
    assert lifecycle["metrics"]["cascade_on_revoke"] == 1.0

    concurrency = by_name["refund_multi_order_concurrency"]
    assert concurrency["metrics"]["no_cross_contamination"] == 1.0

    rejection = by_name["refund_partial_evidence_rejection_loop"]
    assert rejection["metrics"]["actionable_rejection_rate"] == 1.0
    assert rejection["metrics"]["rejection_rounds"] == 3
    assert rejection["metrics"]["acceptance_rounds"] == 2

    # Coding scenarios
    coding_diag = by_name["coding_file_to_diagnosis"]
    assert coding_diag["metrics"]["actionable_rejection_rate"] == 1.0
    assert coding_diag["metrics"]["file_content_accepted"] == 1.0
    assert coding_diag["metrics"]["task_done_accepted"] == 1.0

    coding_stale = by_name["coding_stale_rejection"]
    assert coding_stale["metrics"]["task_done_with_stale_blocked"] == 1.0
    assert coding_stale["metrics"]["diagnosis_with_stale_ok"] == 1.0

    coding_multi = by_name["coding_multi_file_workflow"]
    assert coding_multi["metrics"]["no_cross_contamination"] == 1.0


def test_adversarial_probes_block_all_attacks(tmp_path) -> None:
    result = run_all_adversarial(tmp_path / "adversarial")

    assert result["passed"]
    assert result["blocked"] == result["total"], (
        f"Expected all {result['total']} attack vectors blocked, got {result['blocked']}"
    )
    assert result["total"] == 10
