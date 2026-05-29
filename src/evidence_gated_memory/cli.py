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

    candidates_p = sub.add_parser("candidates", help="List long-term memory candidates for review.")
    candidates_p.add_argument("workspace")
    candidates_p.add_argument("--status", choices=("candidate", "promoted", "pending_review", "rejected"), default=None)
    candidates_p.add_argument("--kind", choices=("persona", "episodic", "instruction"), default=None)
    candidates_p.add_argument("--format", choices=("text", "json"), default="text")
    candidates_p.set_defaults(func=_cmd_candidates)

    audit_p = sub.add_parser("audit", help="Show recent audit log entries.")
    audit_p.add_argument("workspace")
    audit_p.add_argument("--limit", type=int, default=20)
    audit_p.set_defaults(func=_cmd_audit)

    export_audit_p = sub.add_parser("export-audit", help="Export audit log entries as JSON or Markdown.")
    export_audit_p.add_argument("workspace")
    export_audit_p.add_argument("--format", choices=("json", "md"), default="json")
    export_audit_p.add_argument("--limit", type=int, default=100, help="Maximum latest rows to export; 0 means all.")
    export_audit_p.add_argument("--task-id", default=None)
    export_audit_p.add_argument("--claim-id", default=None)
    export_audit_p.add_argument("--fact-id", default=None)
    export_audit_p.add_argument("--evidence-id", default=None)
    export_audit_p.set_defaults(func=_cmd_export_audit)

    sweep_p = sub.add_parser("sweep", help="Invalidate facts whose required support expired.")
    sweep_p.add_argument("workspace")
    sweep_p.add_argument("--schema", required=True, help="Schema path, 'refund', or 'coding'.")
    sweep_p.set_defaults(func=_cmd_sweep)

    context_p = sub.add_parser("context", help="Build a provenance-filtered prompt context.")
    context_p.add_argument("workspace")
    context_p.add_argument("--schema", required=True, help="Schema path, 'refund', or 'coding'.")
    context_p.add_argument("--query", default=None)
    context_p.add_argument("--task-id", default=None, help="Include the Mermaid task map for this task.")
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
        print(f"schema_version: {_schema_version(conn)}")
        for table in (
            "events",
            "evidence",
            "claims",
            "facts",
            "tasks",
            "task_nodes",
            "task_edges",
            "conversation_messages",
            "memory_atom_candidates",
            "memory_atoms",
            "memory_scenarios",
            "memory_personas",
            "audit_log",
        ):
            print(f"{table}: {_count_if_exists(conn, table)}")
        active = _count_where_if_exists(conn, "facts", "invalidated_at IS NULL")
        invalidated = _count_where_if_exists(conn, "facts", "invalidated_at IS NOT NULL")
        print(f"facts_active: {active}")
        print(f"facts_invalidated: {invalidated}")
    print(f"offload_records: {_count_jsonl(workspace / 'offload' / 'offload.jsonl')}")
    refs = list((workspace / "refs").glob("*.md")) if (workspace / "refs").exists() else []
    print(f"refs: {len(refs)}")
    return 0


def _cmd_candidates(args: argparse.Namespace) -> int:
    db_path = Path(args.workspace) / "egm.db"
    if not db_path.exists():
        print("database: missing", file=sys.stderr)
        return 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = _load_candidate_rows(conn, status=args.status, kind=args.kind)
    exported = [_candidate_export_row(row) for row in rows]

    if args.format == "json":
        print(json.dumps(exported, ensure_ascii=False, indent=2))
        return 0

    print(f"memory_atom_candidates: {len(exported)}")
    for item in exported:
        decision = item["decision"] or "-"
        promoted = item["promoted_atom_id"] or "-"
        print(
            f"- {item['id']} status={item['status']} kind={item['kind']} "
            f"confidence={item['confidence']:.2f} decision={decision} "
            f"promoted_atom={promoted} text={_compact_text(item['text'], 96)}"
        )
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


def _cmd_export_audit(args: argparse.Namespace) -> int:
    db_path = Path(args.workspace) / "egm.db"
    if not db_path.exists():
        print("database: missing", file=sys.stderr)
        return 1

    filters = {
        "task_id": args.task_id,
        "claim_id": args.claim_id,
        "fact_id": args.fact_id,
        "evidence_id": args.evidence_id,
    }
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = _load_audit_rows(conn, limit=0 if any(filters.values()) else args.limit)

    exported: list[dict[str, object]] = []
    for row in rows:
        item = _audit_export_row(row)
        if _audit_export_matches(item, filters):
            exported.append(item)
    if args.limit > 0:
        exported = exported[: args.limit]
    exported = list(reversed(exported))

    if args.format == "json":
        print(json.dumps(exported, ensure_ascii=False, indent=2))
    else:
        print(_audit_export_markdown(exported))
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
        print(memory.build_context(query=args.query, max_facts=args.max_facts, task_id=args.task_id))
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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _count_if_exists(conn: sqlite3.Connection, table: str) -> int:
    return _count(conn, table) if _table_exists(conn, table) else 0


def _count_where_if_exists(conn: sqlite3.Connection, table: str, where: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def _schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_meta"):
        return 0
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    return int(row[0])


def _load_candidate_rows(
    conn: sqlite3.Connection,
    *,
    status: Optional[str],
    kind: Optional[str],
) -> list[sqlite3.Row]:
    if not _table_exists(conn, "memory_atom_candidates"):
        return []
    clauses, args = [], []
    if status is not None:
        clauses.append("status = ?")
        args.append(status)
    if kind is not None:
        clauses.append("kind = ?")
        args.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(
        f"SELECT * FROM memory_atom_candidates {where} ORDER BY created_at DESC",
        args,
    ).fetchall()


def _candidate_export_row(row: sqlite3.Row) -> dict[str, object]:
    gate_result = json.loads(row["gate_result"]) if row["gate_result"] else None
    decision = (
        gate_result.get("decision")
        if isinstance(gate_result, dict)
        else None
    )
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "kind": row["kind"],
        "confidence": row["confidence"],
        "decision": decision,
        "promoted_atom_id": row["promoted_atom_id"],
        "source_message_ids": json.loads(row["source_message_ids"]),
        "conflict_flags": json.loads(row["conflict_flags"]),
        "supersedes_atom_ids": json.loads(row["supersedes_atom_ids"]),
        "text": row["text"],
    }


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _compact_json(raw: str, max_len: int = 160) -> str:
    try:
        rendered = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        rendered = raw
    return rendered if len(rendered) <= max_len else rendered[: max_len - 1] + "…"


def _compact_text(raw: object, max_len: int = 160) -> str:
    text = " ".join(str(raw).split())
    return text if len(text) <= max_len else text[: max_len - 1] + "..."


def _load_audit_rows(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    if not _table_exists(conn, "audit_log"):
        return []
    if limit > 0:
        return conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return conn.execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall()


def _audit_export_row(row: sqlite3.Row) -> dict[str, object]:
    try:
        detail: object = json.loads(row["detail"])
    except Exception:
        detail = row["detail"]
    accepted_raw = row["accepted"]
    accepted = None if accepted_raw is None else bool(accepted_raw)
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event_type": row["event_type"],
        "accepted": accepted,
        "claim_id": row["claim_id"],
        "fact_id": row["fact_id"],
        "detail": detail,
    }


def _audit_export_matches(
    item: dict[str, object],
    filters: dict[str, Optional[str]],
) -> bool:
    detail = item.get("detail")
    if filters["claim_id"] and item.get("claim_id") != filters["claim_id"]:
        if not _detail_contains(detail, ("claim_id",), filters["claim_id"]):
            return False
    if filters["fact_id"] and item.get("fact_id") != filters["fact_id"]:
        if not _detail_contains(detail, ("fact_id", "fact_refs", "depends_on"), filters["fact_id"]):
            return False
    if filters["task_id"]:
        if not _detail_contains(detail, ("task_id",), filters["task_id"]):
            return False
    if filters["evidence_id"]:
        if not _detail_contains(
            detail,
            ("evidence_id", "evidence_refs", "result_ref", "missing_evidence_refs"),
            filters["evidence_id"],
        ):
            return False
    return True


def _detail_contains(value: object, keys: tuple[str, ...], target: Optional[str]) -> bool:
    if target is None:
        return True
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and _value_matches(child, target):
                return True
            if _detail_contains(child, keys, target):
                return True
        return False
    if isinstance(value, list):
        return any(_detail_contains(child, keys, target) for child in value)
    return False


def _value_matches(value: object, target: str) -> bool:
    if isinstance(value, str):
        return value == target
    if isinstance(value, list):
        return any(_value_matches(child, target) for child in value)
    if isinstance(value, dict):
        return any(_value_matches(child, target) for child in value.values())
    return False


def _audit_export_markdown(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "_No audit rows matched._"
    lines = [
        "| id | created_at | event_type | accepted | claim_id | fact_id | detail |",
        "|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        detail = json.dumps(row["detail"], ensure_ascii=False, separators=(",", ":"))
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(row["id"]),
                    _md_cell(row["created_at"]),
                    _md_cell(row["event_type"]),
                    _md_cell(row["accepted"]),
                    _md_cell(row["claim_id"]),
                    _md_cell(row["fact_id"]),
                    _md_cell(_compact_json(detail, max_len=240)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _md_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
