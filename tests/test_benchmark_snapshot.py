"""Benchmark snapshot generator tests."""

from __future__ import annotations

from scripts.generate_benchmark_snapshot import build_snapshot, write_markdown


def test_deterministic_benchmark_snapshot_passes(tmp_path) -> None:
    snapshot = build_snapshot(tmp_path / "workspaces")

    assert snapshot["benchmark_type"] == "deterministic-local"
    assert snapshot["summary"]["passed"] is True
    assert snapshot["summary"]["total_suites"] == 4
    assert snapshot["summary"]["total_checks"] >= 10


def test_benchmark_snapshot_markdown_contains_boundary(tmp_path) -> None:
    snapshot = {
        "generated_at": "2026-05-28T00:00:00+00:00",
        "note": "Local deterministic EGM correctness probes.",
        "summary": {
            "passed": True,
            "total_suites": 1,
            "passed_suites": 1,
            "total_checks": 1,
            "passed_checks": 1,
        },
        "suites": [{"suite": "example", "passed": True, "benchmarks": [{"passed": True}]}],
    }
    out = tmp_path / "snapshot.md"

    write_markdown(snapshot, out)

    text = out.read_text(encoding="utf-8")
    assert "not a tau-bench" in text
    assert "docs/benchmark-decision-protocol.md" in text
