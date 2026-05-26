"""Isolated install smoke test (Verification #1).

Creates a fresh venv, installs the locally built wheel, and imports the package
+ loads both builtin schemas. Fails non-zero on any error.

Usage:
    python scripts/smoke_install.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(">", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
    return p


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="egm_smoke_"))
    try:
        dist = tmp / "dist"
        dist.mkdir()
        r = _run([sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(dist)])
        if r.returncode != 0:
            return 1

        wheels = list(dist.glob("evidence_gated_memory-*.whl"))
        if not wheels:
            print("ERROR: no wheel built")
            return 1

        venv = tmp / "venv"
        r = _run([sys.executable, "-m", "venv", str(venv)])
        if r.returncode != 0:
            return 1

        if sys.platform == "win32":
            py = venv / "Scripts" / "python.exe"
            egm = venv / "Scripts" / "egm.exe"
        else:
            py = venv / "bin" / "python"
            egm = venv / "bin" / "egm"

        r = _run([str(py), "-m", "pip", "install", "--quiet", str(wheels[0]), "pydantic>=2.0", "PyYAML>=6.0"])
        if r.returncode != 0:
            return 1

        code = (
            "from evidence_gated_memory import EvidenceGatedMemory;"
            "from evidence_gated_memory.schemas.builtin import REFUND, CODING;"
            "from evidence_gated_memory.schemas.loader import load_schema;"
            "s1 = load_schema(REFUND);"
            "s2 = load_schema(CODING);"
            "assert s1.name == 'refund';"
            "assert s2.name == 'coding';"
            "print('SMOKE OK', s1.name, s2.name)"
        )
        r = _run([str(py), "-c", code])
        if r.returncode != 0:
            return 1
        sys.stdout.write(r.stdout)

        r = _run([str(egm), "--version"])
        if r.returncode != 0:
            return 1
        sys.stdout.write(r.stdout)
        print("SMOKE PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
