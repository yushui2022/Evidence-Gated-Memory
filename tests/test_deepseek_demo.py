import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_deepseek_demo_mock_mode_runs():
    result = subprocess.run(
        [sys.executable, str(REPO / "examples" / "deepseek_refund_agent" / "run.py"), "--mock"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "STEP 1" in result.stdout
    assert "accepted: False" in result.stdout
    assert "accepted: True" in result.stdout
    assert "Evidence-Gated Memory Context" in result.stdout
