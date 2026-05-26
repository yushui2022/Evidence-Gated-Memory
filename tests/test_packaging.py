"""Verification #1: built wheel must contain the builtin YAML schemas.

This test builds a wheel and inspects its contents — it does NOT install it,
to avoid polluting the dev environment. The isolated install smoke is in
scripts/smoke_install.py and run manually in CI.
"""

import subprocess
import sys
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_wheel_contains_builtin_yaml(tmp_path: Path):
    out = tmp_path / "dist"
    out.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    wheels = list(out.glob("evidence_gated_memory-*.whl"))
    assert wheels, "wheel not produced"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    assert any(n.endswith("schemas/builtin/refund.yaml") for n in names), names
    assert any(n.endswith("schemas/builtin/coding.yaml") for n in names), names
