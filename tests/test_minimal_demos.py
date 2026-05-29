"""Smoke tests for README-facing minimal demos."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _run_demo(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "examples" / name)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_refund_minimal_demo_runs() -> None:
    result = _run_demo("refund_minimal.py")

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "EGM Refund Demo" in out
    assert "completion_claim.accepted: false" in out
    assert "missing required evidence" in out
    assert "refund_api_response" in out
    assert "eligibility_claim.accepted: true" in out
    assert "completion_claim.accepted: true" in out
    assert "completion_transition.accepted: true" in out
    assert "Evidence-Gated Memory Context" in out


def test_coding_minimal_demo_runs() -> None:
    result = _run_demo("coding_minimal.py")

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "EGM Coding Demo" in out
    assert "file_claim.accepted: false" in out
    assert "file_read" in out
    assert "diagnosis_claim.accepted: false" in out
    assert "test_log" in out
    assert "done_claim.accepted: false" in out
    assert "done_claim.accepted: true" in out
    assert "task_transition.accepted: true" in out
    assert "Evidence-Gated Memory Context" in out
