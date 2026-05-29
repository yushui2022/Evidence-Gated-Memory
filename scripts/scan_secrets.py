"""Lightweight repository secret scanner.

The scanner is intentionally dependency-free so it can run in local shells and
CI before benchmark scripts or examples are published.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}

IGNORED_ENV_FILES = re.compile(r"^\.env(?:\..+)?$")

TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".css",
    ".example",
    ".gitignore",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_or_deepseek_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{16,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_legacy_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "literal_api_key_assignment",
        re.compile(
            r"\b(?:api[_-]?key|secret|token)\b\s*[:=]\s*['\"](?!\\.\\.\\.|<|your-|example|placeholder)[^'\"\s]{12,}['\"]",
            re.IGNORECASE,
        ),
    ),
    (
        "literal_bearer_header",
        re.compile(
            r"\bAuthorization\b\s*[:=]\s*['\"]Bearer\s+[A-Za-z0-9._-]{12,}",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    kind: str
    match: str


def scan_repository(root: Path) -> list[Finding]:
    """Return suspected secret findings under ``root``."""
    findings: list[Finding] = []
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")

        rel = path.relative_to(root).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    findings.append(
                        Finding(
                            file=rel,
                            line=line_no,
                            kind=kind,
                            match=_redact(match.group(0)),
                        )
                    )
    return findings


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS or part.startswith(".tmp") for part in rel_parts):
            continue
        if IGNORED_ENV_FILES.match(path.name) and path.name != ".env.example":
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > 2_000_000:
            continue
        yield path


def _redact(value: str) -> str:
    if len(value) <= 12:
        return "<redacted>"
    return f"{value[:6]}...{value[-4:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the repository for hardcoded secrets.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="Print machine-readable findings.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    findings = scan_repository(root)

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        if findings:
            print("Potential secrets found:")
            for finding in findings:
                print(f"{finding.file}:{finding.line}: {finding.kind}: {finding.match}")
        else:
            print("No hardcoded secrets found.")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
