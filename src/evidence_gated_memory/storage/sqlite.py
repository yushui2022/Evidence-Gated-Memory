"""SQLite + FTS5 storage backend.

One workspace = one directory containing:
  - egm.db        SQLite file (events, evidence, claims, facts, audit)
  - refs/         markdown files holding raw evidence content
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from evidence_gated_memory.core.models import (
    Claim,
    Evidence,
    Event,
    Fact,
    FactKind,
    GateResult,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
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
    revoked_at TEXT
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
    metadata TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_facts_claim_type ON facts(claim_type);
CREATE INDEX IF NOT EXISTS idx_facts_invalidated ON facts(invalidated_at);
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
        self.db_path = self.workspace / "egm.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- Events ----------

    def insert_event(self, event: Event) -> None:
        self.conn.execute(
            "INSERT INTO events(id, created_at, role, content, metadata) VALUES (?,?,?,?,?)",
            (event.id, _iso(event.created_at), event.role, event.content, _dumps(event.metadata)),
        )
        self.conn.commit()

    # ---------- Evidence ----------

    def write_ref_content(self, evidence_id: str, content: str) -> str:
        path = self.refs_dir / f"{evidence_id}.md"
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.workspace))

    def read_ref_content(self, evidence_id: str) -> str:
        path = self.refs_dir / f"{evidence_id}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

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

    def invalidate_fact(self, fact_id: str, reason: str, at: datetime) -> None:
        self.conn.execute(
            "UPDATE facts SET invalidated_at=?, invalidation_reason=? WHERE id=?",
            (_iso(at), reason, fact_id),
        )
        self.conn.commit()

    def search_facts_fts(self, query: str, limit: int = 10) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT facts.* FROM facts JOIN facts_fts ON facts.id = facts_fts.id "
            "WHERE facts_fts MATCH ? AND facts.invalidated_at IS NULL "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [_row_to_fact(r) for r in rows]

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
    )
