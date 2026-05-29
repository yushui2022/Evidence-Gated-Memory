"""Repository-level secret hygiene checks."""

from __future__ import annotations

from pathlib import Path

from scripts.scan_secrets import scan_repository


REPO = Path(__file__).resolve().parents[1]


def test_repository_has_no_hardcoded_secrets() -> None:
    findings = scan_repository(REPO)

    assert findings == []
