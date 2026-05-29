"""SQLite + FTS5 storage backend.

One workspace = one directory containing:
  - egm.db        SQLite file (events, evidence, claims, facts, audit)
  - refs/         markdown files holding raw evidence content
  - offload/      JSONL index for heavy tool results
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from evidence_gated_memory.core.models import (
    Claim,
    ConversationMessage,
    Evidence,
    Event,
    Fact,
    FactKind,
    GateResult,
    MemoryAtom,
    MemoryAtomKind,
    MemoryPersona,
    MemoryScenario,
    OffloadRecord,
    Task,
    TaskEdge,
    TaskEdgeKind,
    TaskNode,
    TaskNodeStatus,
    TaskState,
    TaskStatus,
)


SCHEMA_VERSION = 1
SQLITE_BUSY_TIMEOUT_MS = 5000


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_atoms (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_message_ids TEXT NOT NULL,
    confidence REAL NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_scenarios (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    atom_ids TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_personas (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL,
    scenario_ids TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_system TEXT,
    risk_level TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_path TEXT,
    metadata TEXT NOT NULL,
    stale_after_seconds INTEGER,
    expired_after_seconds INTEGER,
    revoked_at TEXT,
    node_id TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    kind TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    kind TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    invalidated_at TEXT,
    invalidation_reason TEXT,
    metadata TEXT NOT NULL,
    node_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    claim_id TEXT,
    fact_id TEXT,
    accepted INTEGER,
    detail TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    id UNINDEXED,
    summary,
    metadata_text,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    id UNINDEXED,
    text,
    claim_type,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_atoms_fts USING fts5(
    id UNINDEXED,
    text,
    kind,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_scenarios_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_personas_fts USING fts5(
    id UNINDEXED,
    name,
    summary,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS task_nodes (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    anchors TEXT NOT NULL,
    parent_id TEXT,
    evidence_refs TEXT NOT NULL,
    fact_refs TEXT NOT NULL,
    blocked_reason TEXT,
    suggested_action TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_facts_claim_type ON facts(claim_type);
CREATE INDEX IF NOT EXISTS idx_facts_invalidated ON facts(invalidated_at);
CREATE INDEX IF NOT EXISTS idx_conversation_session ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_atoms_kind ON memory_atoms(kind);
CREATE INDEX IF NOT EXISTS idx_task_nodes_task_id ON task_nodes(task_id);
CREATE INDEX IF NOT EXISTS idx_task_nodes_status ON task_nodes(status);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'open',
    anchors TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_edges (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    src_node_id TEXT NOT NULL,
    dst_node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL,
    UNIQUE(task_id, src_node_id, dst_node_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_task_edges_task_id ON task_edges(task_id);
CREATE INDEX IF NOT EXISTS idx_task_edges_src ON task_edges(src_node_id);
CREATE INDEX IF NOT EXISTS idx_task_edges_dst ON task_edges(dst_node_id);
"""


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


class SqliteStore:
    """Synchronous SQLite store. EGM exposes an async API on top (run_in_executor not needed for SQLite at this scale)."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.refs_dir = self.workspace / "refs"
        self.refs_dir.mkdir(exist_ok=True)
        self.offload_dir = self.workspace / "offload"
        self.offload_dir.mkdir(exist_ok=True)
        self.offload_path = self.offload_dir / "offload.jsonl"
        self.db_path = self.workspace / "egm.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._configure_connection()
        self.conn.executescript(SCHEMA)
        self._migrate_schema()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _configure_connection(self) -> None:
        """Set conservative local-workspace SQLite pragmas.

        WAL improves the single-writer / many-reader shape EGM targets today.
        It is not a multi-writer guarantee; callers still need to coordinate
        writes at the application layer.
        """
        self.conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        self.conn.execute("PRAGMA journal_mode=WAL")

    def _migrate_schema(self) -> None:
        """Run pending schema migrations in version order."""
        current_version = self.get_schema_version()
        if current_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"workspace schema_version {current_version} is newer than "
                f"this package supports ({SCHEMA_VERSION})"
            )
        for version, migration in self._migration_plan():
            if current_version >= version:
                continue
            migration()
            self._set_schema_version(version)
            current_version = version

    def _migration_plan(self):
        return (
            (1, self._migrate_to_v1),
        )

    def _migrate_to_v1(self) -> None:
        """Add derived task state for workspaces created before Task.current_state."""
        self._ensure_column("tasks", "current_state", "TEXT NOT NULL DEFAULT 'open'")

    def get_schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def _set_schema_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ---------- Events ----------

    def insert_event(self, event: Event) -> None:
        self.conn.execute(
            "INSERT INTO events(id, created_at, role, content, metadata) VALUES (?,?,?,?,?)",
            (event.id, _iso(event.created_at), event.role, event.content, _dumps(event.metadata)),
        )
        self.conn.commit()

    # ---------- Long-term memory: L0 conversation / L1 atoms ----------

    def insert_conversation_message(self, message: ConversationMessage) -> None:
        self.conn.execute(
            """INSERT INTO conversation_messages(
                id, created_at, session_id, role, content, metadata
            ) VALUES (?,?,?,?,?,?)""",
            (
                message.id, _iso(message.created_at), message.session_id,
                message.role, message.content, _dumps(message.metadata),
            ),
        )
        self.conn.commit()

    def get_conversation_message(self, message_id: str) -> Optional[ConversationMessage]:
        row = self.conn.execute(
            "SELECT * FROM conversation_messages WHERE id=?",
            (message_id,),
        ).fetchone()
        return _row_to_conversation_message(row) if row else None

    def get_conversation_messages_many(self, ids: Iterable[str]) -> list[ConversationMessage]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM conversation_messages WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [_row_to_conversation_message(r) for r in rows]

    def list_conversation_messages(
        self,
        session_id: Optional[str] = None,
    ) -> list[ConversationMessage]:
        if session_id is None:
            rows = self.conn.execute(
                "SELECT * FROM conversation_messages ORDER BY created_at ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM conversation_messages WHERE session_id=? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_conversation_message(r) for r in rows]

    def insert_memory_atom(self, atom: MemoryAtom) -> None:
        self.conn.execute(
            """INSERT INTO memory_atoms(
                id, created_at, kind, text, source_message_ids, confidence, metadata
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                atom.id, _iso(atom.created_at), atom.kind.value, atom.text,
                _dumps(atom.source_message_ids), atom.confidence, _dumps(atom.metadata),
            ),
        )
        self.conn.execute(
            "INSERT INTO memory_atoms_fts(id, text, kind) VALUES (?,?,?)",
            (atom.id, atom.text, atom.kind.value),
        )
        self.conn.commit()

    def get_memory_atom(self, atom_id: str) -> Optional[MemoryAtom]:
        row = self.conn.execute(
            "SELECT * FROM memory_atoms WHERE id=?",
            (atom_id,),
        ).fetchone()
        return _row_to_memory_atom(row) if row else None

    def get_memory_atoms_many(self, ids: Iterable[str]) -> list[MemoryAtom]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM memory_atoms WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [_row_to_memory_atom(r) for r in rows]

    def list_memory_atoms(self, kind: Optional[MemoryAtomKind] = None) -> list[MemoryAtom]:
        if kind is None:
            rows = self.conn.execute(
                "SELECT * FROM memory_atoms ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memory_atoms WHERE kind=? ORDER BY created_at DESC",
                (kind.value,),
            ).fetchall()
        return [_row_to_memory_atom(r) for r in rows]

    def search_memory_atoms(self, query: str, limit: int = 10) -> list[MemoryAtom]:
        safe = _sanitize_fts_query(query)
        if safe:
            try:
                rows = self.conn.execute(
                    "SELECT memory_atoms.* FROM memory_atoms "
                    "JOIN memory_atoms_fts ON memory_atoms.id = memory_atoms_fts.id "
                    "WHERE memory_atoms_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (safe, limit),
                ).fetchall()
                if rows:
                    return [_row_to_memory_atom(r) for r in rows]
            except sqlite3.OperationalError:
                pass
            relaxed = _sanitize_fts_query(query, joiner="OR")
            if relaxed != safe:
                try:
                    rows = self.conn.execute(
                        "SELECT memory_atoms.* FROM memory_atoms "
                        "JOIN memory_atoms_fts ON memory_atoms.id = memory_atoms_fts.id "
                        "WHERE memory_atoms_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (relaxed, limit),
                    ).fetchall()
                    if rows:
                        return [_row_to_memory_atom(r) for r in rows]
                except sqlite3.OperationalError:
                    pass

        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM memory_atoms WHERE text LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (like, limit),
        ).fetchall()
        return [_row_to_memory_atom(r) for r in rows]

    def insert_memory_scenario(self, scenario: MemoryScenario) -> None:
        self.conn.execute(
            """INSERT INTO memory_scenarios(
                id, created_at, updated_at, title, summary, atom_ids, metadata
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                scenario.id, _iso(scenario.created_at), _iso(scenario.updated_at),
                scenario.title, scenario.summary, _dumps(scenario.atom_ids),
                _dumps(scenario.metadata),
            ),
        )
        self.conn.execute(
            "INSERT INTO memory_scenarios_fts(id, title, summary) VALUES (?,?,?)",
            (scenario.id, scenario.title, scenario.summary),
        )
        self.conn.commit()

    def get_memory_scenario(self, scenario_id: str) -> Optional[MemoryScenario]:
        row = self.conn.execute(
            "SELECT * FROM memory_scenarios WHERE id=?",
            (scenario_id,),
        ).fetchone()
        return _row_to_memory_scenario(row) if row else None

    def get_memory_scenarios_many(self, ids: Iterable[str]) -> list[MemoryScenario]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM memory_scenarios WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [_row_to_memory_scenario(r) for r in rows]

    def list_memory_scenarios(self) -> list[MemoryScenario]:
        rows = self.conn.execute(
            "SELECT * FROM memory_scenarios ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_to_memory_scenario(r) for r in rows]

    def search_memory_scenarios(self, query: str, limit: int = 10) -> list[MemoryScenario]:
        safe = _sanitize_fts_query(query)
        if safe:
            try:
                rows = self.conn.execute(
                    "SELECT memory_scenarios.* FROM memory_scenarios "
                    "JOIN memory_scenarios_fts ON memory_scenarios.id = memory_scenarios_fts.id "
                    "WHERE memory_scenarios_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (safe, limit),
                ).fetchall()
                if rows:
                    return [_row_to_memory_scenario(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM memory_scenarios WHERE title LIKE ? OR summary LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [_row_to_memory_scenario(r) for r in rows]

    def insert_memory_persona(self, persona: MemoryPersona) -> None:
        self.conn.execute(
            """INSERT INTO memory_personas(
                id, created_at, updated_at, name, summary, scenario_ids, metadata
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                persona.id, _iso(persona.created_at), _iso(persona.updated_at),
                persona.name, persona.summary, _dumps(persona.scenario_ids),
                _dumps(persona.metadata),
            ),
        )
        self.conn.execute(
            "INSERT INTO memory_personas_fts(id, name, summary) VALUES (?,?,?)",
            (persona.id, persona.name, persona.summary),
        )
        self.conn.commit()

    def get_memory_persona(self, persona_id: str) -> Optional[MemoryPersona]:
        row = self.conn.execute(
            "SELECT * FROM memory_personas WHERE id=?",
            (persona_id,),
        ).fetchone()
        return _row_to_memory_persona(row) if row else None

    def list_memory_personas(self) -> list[MemoryPersona]:
        rows = self.conn.execute(
            "SELECT * FROM memory_personas ORDER BY updated_at DESC"
        ).fetchall()
        return [_row_to_memory_persona(r) for r in rows]

    def search_memory_personas(self, query: str, limit: int = 10) -> list[MemoryPersona]:
        safe = _sanitize_fts_query(query)
        if safe:
            try:
                rows = self.conn.execute(
                    "SELECT memory_personas.* FROM memory_personas "
                    "JOIN memory_personas_fts ON memory_personas.id = memory_personas_fts.id "
                    "WHERE memory_personas_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (safe, limit),
                ).fetchall()
                if rows:
                    return [_row_to_memory_persona(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM memory_personas WHERE name LIKE ? OR summary LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [_row_to_memory_persona(r) for r in rows]

    # ---------- Evidence ----------

    def write_ref_content(self, evidence_id: str, content: str) -> str:
        path = self.refs_dir / f"{evidence_id}.md"
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.workspace))

    def read_ref_content(self, evidence_id: str) -> str:
        path = self.refs_dir / f"{evidence_id}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ---------- Offload JSONL ----------

    def append_offload_record(self, record: OffloadRecord) -> None:
        with self.offload_path.open("a", encoding="utf-8") as f:
            f.write(_dumps(record.model_dump()) + "\n")

    def list_offload_records(
        self,
        task_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> list[OffloadRecord]:
        if not self.offload_path.exists():
            return []

        records: list[OffloadRecord] = []
        for line in self.offload_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = OffloadRecord(**json.loads(line))
            if task_id is not None and record.task_id != task_id:
                continue
            if node_id is not None and record.node_id != node_id:
                continue
            records.append(record)
        return sorted(records, key=lambda r: r.timestamp)

    def insert_evidence(self, ev: Evidence) -> None:
        self.conn.execute(
            """INSERT INTO evidence(
                id, created_at, observed_at, evidence_type, source, source_system,
                risk_level, summary, content_path, metadata,
                stale_after_seconds, expired_after_seconds, revoked_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ev.id, _iso(ev.created_at), _iso(ev.observed_at),
                ev.evidence_type, ev.source, ev.source_system,
                ev.risk_level, ev.summary, ev.content_path, _dumps(ev.metadata),
                ev.stale_after_seconds, ev.expired_after_seconds,
                _iso(ev.revoked_at) if ev.revoked_at else None,
            ),
        )
        self.conn.execute(
            "INSERT INTO evidence_fts(id, summary, metadata_text) VALUES (?,?,?)",
            (ev.id, ev.summary, _dumps(ev.metadata)),
        )
        self.conn.commit()

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        row = self.conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        return _row_to_evidence(row) if row else None

    def get_evidence_many(self, ids: Iterable[str]) -> list[Evidence]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM evidence WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [_row_to_evidence(r) for r in rows]

    def update_evidence_node_id(self, evidence_id: str, node_id: str) -> None:
        self.conn.execute(
            "UPDATE evidence SET node_id=? WHERE id=?",
            (node_id, evidence_id),
        )
        self.conn.commit()

    # ---------- Claims ----------

    def insert_claim(self, claim: Claim) -> None:
        self.conn.execute(
            """INSERT INTO claims(id, created_at, text, claim_type, kind, evidence_refs, depends_on, metadata)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                claim.id, _iso(claim.created_at), claim.text, claim.claim_type, claim.kind.value,
                _dumps(claim.evidence_refs), _dumps(claim.depends_on), _dumps(claim.metadata),
            ),
        )
        self.conn.commit()

    # ---------- Facts ----------

    def insert_fact(self, fact: Fact) -> None:
        self.conn.execute(
            """INSERT INTO facts(
                id, created_at, claim_id, text, claim_type, kind,
                evidence_refs, depends_on, invalidated_at, invalidation_reason, metadata
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fact.id, _iso(fact.created_at), fact.claim_id, fact.text, fact.claim_type, fact.kind.value,
                _dumps(fact.evidence_refs), _dumps(fact.depends_on),
                _iso(fact.invalidated_at) if fact.invalidated_at else None,
                fact.invalidation_reason, _dumps(fact.metadata),
            ),
        )
        self.conn.execute(
            "INSERT INTO facts_fts(id, text, claim_type) VALUES (?,?,?)",
            (fact.id, fact.text, fact.claim_type),
        )
        self.conn.commit()

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        row = self.conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
        return _row_to_fact(row) if row else None

    def list_active_facts(self) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE invalidated_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def list_facts_depending_on(self, fact_id: str) -> list[Fact]:
        # JSON LIKE match is good enough for v0.1.
        like = f'%"{fact_id}"%'
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE invalidated_at IS NULL AND depends_on LIKE ?",
            (like,),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def list_facts_using_evidence(self, evidence_id: str) -> list[Fact]:
        like = f'%"{evidence_id}"%'
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE invalidated_at IS NULL AND evidence_refs LIKE ?",
            (like,),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def update_fact_node_id(self, fact_id: str, node_id: str) -> None:
        self.conn.execute(
            "UPDATE facts SET node_id=? WHERE id=?",
            (node_id, fact_id),
        )
        self.conn.commit()

    def invalidate_fact(self, fact_id: str, reason: str, at: datetime) -> None:
        self.conn.execute(
            "UPDATE facts SET invalidated_at=?, invalidation_reason=? WHERE id=?",
            (_iso(at), reason, fact_id),
        )
        self.conn.commit()

    def search_facts_fts(self, query: str, limit: int = 10) -> list[Fact]:
        """Search facts. FTS5 is finicky about punctuation (ORD-123, colons,
        operator words). Try FTS first; on any syntax error or empty result,
        fall back to a safe LIKE scan so business-ID queries never crash."""
        safe = _sanitize_fts_query(query)
        if safe:
            try:
                rows = self.conn.execute(
                    "SELECT facts.* FROM facts JOIN facts_fts ON facts.id = facts_fts.id "
                    "WHERE facts_fts MATCH ? AND facts.invalidated_at IS NULL "
                    "ORDER BY rank LIMIT ?",
                    (safe, limit),
                ).fetchall()
                if rows:
                    return [_row_to_fact(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE invalidated_at IS NULL AND text LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (like, limit),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

    # ---------- Task Graph ----------

    def insert_task_node(self, node: TaskNode) -> None:
        self.conn.execute(
            """INSERT INTO task_nodes(
                id, task_id, node_type, title, status, anchors, parent_id,
                evidence_refs, fact_refs, blocked_reason, suggested_action,
                created_at, updated_at, metadata
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                node.id, node.task_id, node.node_type, node.title, node.status.value,
                _dumps(node.anchors), node.parent_id,
                _dumps(node.evidence_refs), _dumps(node.fact_refs),
                node.blocked_reason, node.suggested_action,
                _iso(node.created_at), _iso(node.updated_at), _dumps(node.metadata),
            ),
        )
        self.conn.commit()

    def get_task_node(self, node_id: str) -> Optional[TaskNode]:
        row = self.conn.execute("SELECT * FROM task_nodes WHERE id=?", (node_id,)).fetchone()
        return _row_to_task_node(row) if row else None

    def list_task_nodes(
        self,
        task_id: Optional[str] = None,
        status: Optional[TaskNodeStatus] = None,
    ) -> list[TaskNode]:
        clauses, args = [], []
        if task_id is not None:
            clauses.append("task_id = ?")
            args.append(task_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM task_nodes {where} ORDER BY created_at ASC", args
        ).fetchall()
        return [_row_to_task_node(r) for r in rows]

    def update_task_node(self, node: TaskNode) -> None:
        self.conn.execute(
            """UPDATE task_nodes SET
                node_type=?, title=?, status=?, anchors=?, parent_id=?,
                evidence_refs=?, fact_refs=?, blocked_reason=?, suggested_action=?,
                updated_at=?, metadata=?
               WHERE id=?""",
            (
                node.node_type, node.title, node.status.value,
                _dumps(node.anchors), node.parent_id,
                _dumps(node.evidence_refs), _dumps(node.fact_refs),
                node.blocked_reason, node.suggested_action,
                _iso(node.updated_at), _dumps(node.metadata),
                node.id,
            ),
        )
        self.conn.commit()

    # ---------- Tasks ----------

    def upsert_task(self, task: Task) -> None:
        """Insert-or-update by id. Callers use this for both creation and
        status/title updates — the workflow row is small enough that we
        always write the full snapshot."""
        self.conn.execute(
            """INSERT INTO tasks(
                id, title, status, current_state, anchors, created_at, updated_at, metadata
            )
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title,
                 status=excluded.status,
                 current_state=excluded.current_state,
                 anchors=excluded.anchors,
                 updated_at=excluded.updated_at,
                 metadata=excluded.metadata""",
            (
                task.id, task.title, task.status.value,
                task.current_state.value, _dumps(task.anchors),
                _iso(task.created_at), _iso(task.updated_at), _dumps(task.metadata),
            ),
        )
        self.conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY created_at ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY created_at ASC",
                (status.value,),
            ).fetchall()
        return [_row_to_task(r) for r in rows]

    # ---------- Task Edges ----------

    def insert_task_edge(self, edge: TaskEdge) -> None:
        """Insert an edge. The UNIQUE constraint on
        (task_id, src, dst, kind) makes this idempotent at the SQL level —
        callers can re-emit the same edge without worrying about duplicates."""
        self.conn.execute(
            """INSERT OR IGNORE INTO task_edges(
                id, task_id, src_node_id, dst_node_id, kind, created_at, metadata
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                edge.id, edge.task_id, edge.src_node_id, edge.dst_node_id,
                edge.kind.value, _iso(edge.created_at), _dumps(edge.metadata),
            ),
        )
        self.conn.commit()

    def list_task_edges(
        self,
        task_id: Optional[str] = None,
        src_node_id: Optional[str] = None,
        dst_node_id: Optional[str] = None,
    ) -> list[TaskEdge]:
        clauses, args = [], []
        if task_id is not None:
            clauses.append("task_id = ?")
            args.append(task_id)
        if src_node_id is not None:
            clauses.append("src_node_id = ?")
            args.append(src_node_id)
        if dst_node_id is not None:
            clauses.append("dst_node_id = ?")
            args.append(dst_node_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM task_edges {where} ORDER BY created_at ASC", args
        ).fetchall()
        return [_row_to_task_edge(r) for r in rows]

    # ---------- Audit ----------

    def append_audit(
        self,
        event_type: str,
        detail: dict[str, Any],
        claim_id: Optional[str] = None,
        fact_id: Optional[str] = None,
        accepted: Optional[bool] = None,
        at: Optional[datetime] = None,
    ) -> None:
        from datetime import timezone
        at = at or datetime.now(timezone.utc)
        self.conn.execute(
            "INSERT INTO audit_log(created_at, event_type, claim_id, fact_id, accepted, detail) "
            "VALUES (?,?,?,?,?,?)",
            (_iso(at), event_type, claim_id, fact_id,
             None if accepted is None else (1 if accepted else 0),
             _dumps(detail)),
        )
        self.conn.commit()

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
_FTS_TOKEN_RE = re.compile(r"\w+")


def _sanitize_fts_query(query: str, *, joiner: str = "AND") -> str:
    """Turn arbitrary user input into a safe FTS5 MATCH expression.

    Strategy: extract alphanumeric tokens (incl. CJK), drop operator keywords,
    quote each token. Empty result -> caller falls back to LIKE."""
    if not query:
        return ""
    if joiner not in {"AND", "OR"}:
        raise ValueError("joiner must be AND or OR")
    tokens = [t for t in _FTS_TOKEN_RE.findall(query) if t.upper() not in _FTS_OPERATORS]
    if not tokens:
        return ""
    if joiner == "AND":
        return " ".join(f'"{t}"' for t in tokens)
    return " OR ".join(f'"{t}"' for t in tokens)


def _row_to_conversation_message(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        metadata=json.loads(row["metadata"]),
    )


def _row_to_memory_atom(row: sqlite3.Row) -> MemoryAtom:
    return MemoryAtom(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        kind=MemoryAtomKind(row["kind"]),
        text=row["text"],
        source_message_ids=json.loads(row["source_message_ids"]),
        confidence=row["confidence"],
        metadata=json.loads(row["metadata"]),
    )


def _row_to_memory_scenario(row: sqlite3.Row) -> MemoryScenario:
    return MemoryScenario(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        title=row["title"],
        summary=row["summary"],
        atom_ids=json.loads(row["atom_ids"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_memory_persona(row: sqlite3.Row) -> MemoryPersona:
    return MemoryPersona(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        name=row["name"],
        summary=row["summary"],
        scenario_ids=json.loads(row["scenario_ids"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_evidence(row: sqlite3.Row) -> Evidence:
    return Evidence(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        observed_at=_from_iso(row["observed_at"]),
        evidence_type=row["evidence_type"],
        source=row["source"],
        source_system=row["source_system"],
        risk_level=row["risk_level"],
        summary=row["summary"],
        content_path=row["content_path"],
        metadata=json.loads(row["metadata"]),
        stale_after_seconds=row["stale_after_seconds"],
        expired_after_seconds=row["expired_after_seconds"],
        revoked_at=_from_iso(row["revoked_at"]),
        node_id=row["node_id"],
    )


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=row["id"],
        created_at=_from_iso(row["created_at"]),
        claim_id=row["claim_id"],
        text=row["text"],
        claim_type=row["claim_type"],
        kind=FactKind(row["kind"]),
        evidence_refs=json.loads(row["evidence_refs"]),
        depends_on=json.loads(row["depends_on"]),
        invalidated_at=_from_iso(row["invalidated_at"]),
        invalidation_reason=row["invalidation_reason"],
        metadata=json.loads(row["metadata"]),
        node_id=row["node_id"],
    )


def _row_to_task_node(row: sqlite3.Row) -> TaskNode:
    return TaskNode(
        id=row["id"],
        task_id=row["task_id"],
        node_type=row["node_type"],
        title=row["title"],
        status=TaskNodeStatus(row["status"]),
        anchors=json.loads(row["anchors"]),
        parent_id=row["parent_id"],
        evidence_refs=json.loads(row["evidence_refs"]),
        fact_refs=json.loads(row["fact_refs"]),
        blocked_reason=row["blocked_reason"],
        suggested_action=row["suggested_action"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        status=TaskStatus(row["status"]),
        current_state=TaskState(row["current_state"]),
        anchors=json.loads(row["anchors"]),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        metadata=json.loads(row["metadata"]),
    )


def _row_to_task_edge(row: sqlite3.Row) -> TaskEdge:
    return TaskEdge(
        id=row["id"],
        task_id=row["task_id"],
        src_node_id=row["src_node_id"],
        dst_node_id=row["dst_node_id"],
        kind=TaskEdgeKind(row["kind"]),
        created_at=_from_iso(row["created_at"]),
        metadata=json.loads(row["metadata"]),
    )
