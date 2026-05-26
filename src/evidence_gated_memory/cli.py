"""Command line interface for Evidence-Gated Memory."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from evidence_gated_memory import __version__
from evidence_gated_memory.core.memory import EvidenceGatedMemory
from evidence_gated_memory.schemas.builtin import CODING, REFUND
from evidence_gated_memory.schemas.loader import DomainSchema, load_schema


def main(argv: Optional[list[str]] = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="egm", description="Inspect and operate Evidence-Gated Memory workspaces.")
    parser.add_argument("--version", action="version", version=f"egm {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect", help="Show workspace counts and schema summary.")
    inspect_p.add_argument("workspace")
    inspect_p.add_argument("--schema", default=None, help="Schema path, 'refund', or 'coding'.")
    inspect_p.set_defaults(func=_cmd_inspect)

    audit_p = sub.add_parser("audit", help="Show recent audit log entries.")
    audit_p.add_argument("workspace")
    audit_p.add_argument("--limit", type=int, default=20)
    audit_p.set_defaults(func=_cmd_audit)

    sweep_p = sub.add_parser("sweep", help="Invalidate facts whose required support expired.")
    sweep_p.add_argument("workspace")
    sweep_p.add_argument("--schema", required=True, help="Schema path, 'refund', or 'coding'.")
    sweep_p.set_defaults(func=_cmd_sweep)

    context_p = sub.add_parser("context", help="Build a provenance-filtered prompt context.")
    context_p.add_argument("workspace")
    context_p.add_argument("--schema", required=True, help="Schema path, 'refund', or 'coding'.")
    context_p.add_argument("--query", default=None)
    context_p.add_argument("--max-facts", type=int, default=10)
    context_p.set_defaults(func=_cmd_context)

    refs_p = sub.add_parser("ref", help="Show raw evidence content.")
    refs_p.add_argument("workspace")
    refs_p.add_argument("ref_id")
    refs_p.set_defaults(func=_cmd_ref)

    schema_p = sub.add_parser("schema", help="Schema utilities.")
    schema_sub = schema_p.add_subparsers(dest="schema_command", required=True)
    validate_p = schema_sub.add_parser("validate", help="Validate and summarize a schema.")
    validate_p.add_argument("schema", help="Schema path, 'refund', or 'coding'.")
    validate_p.set_defaults(func=_cmd_schema_validate)

    return parser


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _cmd_inspect(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    db_path = workspace / "egm.db"
    print(f"workspace: {workspace}")
    if args.schema:
        schema = _load_schema_arg(args.schema)
        _print_schema_summary(schema)
    if not db_path.exists():
        print("database: missing")
        return 1

    with sqlite3.connect(db_path) as conn:
        print(f"database: {db_path}")
        for table in ("events", "evidence", "claims", "facts", "audit_log"):
            print(f"{table}: {_count(conn, table)}")
        active = conn.execute("SELECT COUNT(*) FROM facts WHERE invalidated_at IS NULL").fetchone()[0]
        invalidated = conn.execute("SELECT COUNT(*) FROM facts WHERE invalidated_at IS NOT NULL").fetchone()[0]
        print(f"facts_active: {active}")
        print(f"facts_invalidated: {invalidated}")
    refs = list((workspace / "refs").glob("*.md")) if (workspace / "refs").exists() else []
    print(f"refs: {len(refs)}")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    db_path = Path(args.workspace) / "egm.db"
    if not db_path.exists():
        print("database: missing", file=sys.stderr)
        return 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (args.limit,),
        ).fetchall()
    for row in rows:
        detail = _compact_json(row["detail"])
        print(
            f"{row['id']:04d} {row['event_type']} accepted={row['accepted']} "
            f"claim={row['claim_id']} fact={row['fact_id']} detail={detail}"
        )
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    memory = EvidenceGatedMemory(args.workspace, _load_schema_arg(args.schema))
    try:
        invalidated = memory.sweep_expired()
    finally:
        memory.close()
    print(f"invalidated: {len(invalidated)}")
    for fact_id in invalidated:
        print(f"- {fact_id}")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    memory = EvidenceGatedMemory(args.workspace, _load_schema_arg(args.schema))
    try:
        print(memory.build_context(query=args.query, max_facts=args.max_facts))
    finally:
        memory.close()
    return 0


def _cmd_ref(args: argparse.Namespace) -> int:
    path = Path(args.workspace) / "refs" / f"{args.ref_id}.md"
    if not path.exists():
        print(f"ref not found: {args.ref_id}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_schema_validate(args: argparse.Namespace) -> int:
    schema = _load_schema_arg(args.schema)
    print("schema: ok")
    _print_schema_summary(schema)
    return 0


def _load_schema_arg(value: str) -> DomainSchema:
    lowered = value.lower()
    if lowered in {"refund", "builtin:refund"}:
        return load_schema(REFUND)
    if lowered in {"coding", "builtin:coding"}:
        return load_schema(CODING)
    return load_schema(Path(value))


def _print_schema_summary(schema: DomainSchema) -> None:
    print(f"schema: {schema.name}")
    print(f"entities: {len(schema.entities)}")
    print(f"evidence_types: {len(schema.evidence_types)}")
    print(f"claim_types: {len(schema.claim_types)}")
    print(f"gates: {len(schema.gates)}")


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _compact_json(raw: str, max_len: int = 160) -> str:
    try:
        rendered = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        rendered = raw
    return rendered if len(rendered) <= max_len else rendered[: max_len - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
