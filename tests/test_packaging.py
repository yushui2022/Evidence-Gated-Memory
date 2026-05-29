"""Verification #1: built wheel must contain the builtin YAML schemas.

This test builds a wheel and inspects its contents. It does not install the
wheel, and it disables build isolation so local/CI test runs do not need network
access just to verify package data.
"""

import zipfile
from pathlib import Path

from setuptools import build_meta


REPO = Path(__file__).resolve().parents[1]


def test_wheel_contains_builtin_yaml(tmp_path: Path, monkeypatch):
    out = tmp_path / "dist"
    out.mkdir()
    monkeypatch.chdir(REPO)
    wheel_name = build_meta.build_wheel(str(out))

    wheels = [out / wheel_name]
    assert wheels, "wheel not produced"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    assert any(n.endswith("schemas/builtin/refund.yaml") for n in names), names
    assert any(n.endswith("schemas/builtin/coding.yaml") for n in names), names
