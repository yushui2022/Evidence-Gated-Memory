"""EvidenceGatedMemory — the public entry point.

Two API surfaces:

  * Easy:    `assert_fact(text, claim_type, evidence=[...])`
             one call: propose → gate → commit (or reject with actionable feedback)

  * Detailed: propose_claim → check_gate → commit_fact
             for advanced users who want to insert custom logic between steps
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from evidence_gated_memory.core.context import build_context
from evidence_gated_memory.core.freshness import freshness_of
from evidence_gated_memory.core.gates import check_gate
from evidence_gated_memory.core.models import (
    AssertResult,
    Claim,
    Evidence,
    Event,
    Fact,
    FactKind,
    Freshness,
    GateResult,
)
from evidence_gated_memory.schemas.loader import DomainSchema, load_schema, load_schema_dict
from evidence_gated_memory.storage.sqlite import SqliteStore


SchemaInput = Union[str, Path, dict, DomainSchema]


def _resolve_schema(schema: SchemaInput) -> DomainSchema:
    if isinstance(schema, DomainSchema):
        return schema
    if isinstance(schema, dict):
        return load_schema_dict(schema)
    return load_schema(schema)


class EvidenceGatedMemory:
    """Provenance-first memory layer.

    Sync API (SQLite is cheap enough that async wrapping adds complexity without speedup at v0.1).
    """

    def __init__(self, workspace: str | Path, domain_schema: SchemaInput):
        self.workspace = Path(workspace)
        self.schema = _resolve_schema(domain_schema)
        self.store = SqliteStore(self.workspace)

    def close(self) -> None:
        self.store.close()

    # ---------- L0: events & evidence ----------

    def record_event(self, role: str, content: str, **metadata: Any) -> Event:
        event = Event(role=role, content=content, metadata=metadata)
        self.store.insert_event(event)
        return event

    def record_evidence(
        self,
        evidence_type: str,
        source: str,
        content: str,
        *,
        summary: str = "",
        source_system: Optional[str] = None,
        risk_level: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
        stale_after_seconds: Optional[int] = None,
        expired_after_seconds: Optional[int] = None,
    ) -> Evidence:
        type_def = self.schema.evidence_type(evidence_type)
        resolved_risk = risk_level or (type_def.risk if type_def else "medium")
        ev = Evidence(
            evidence_type=evidence_type,
            source=source,
            source_system=source_system or source,
            risk_level=resolved_risk,
            summary=summary or _auto_summary(content),
            observed_at=observed_at or datetime.now(timezone.utc),
            metadata=metadata or {},
            stale_after_seconds=stale_after_seconds,
            expired_after_seconds=expired_after_seconds,
        )
        ev.content_path = self.store.write_ref_content(ev.id, content)
        self.store.insert_evidence(ev)
        return ev

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self.store.get_evidence(evidence_id)

    def read_ref(self, evidence_id: str) -> str:
        return self.store.read_ref_content(evidence_id)

    # ---------- L1: claim → fact ----------

    def propose_claim(
        self,
        text: str,
        claim_type: str,
        *,
        kind: FactKind = FactKind.OBSERVED,
        evidence: Optional[list[Union[str, Evidence]]] = None,
        depends_on: Optional[list[Union[str, Fact]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Claim:
        evidence_refs = [e.id if isinstance(e, Evidence) else e for e in (evidence or [])]
        dep_ids = [f.id if isinstance(f, Fact) else f for f in (depends_on or [])]
        claim = Claim(
            text=text,
            claim_type=claim_type,
            kind=kind,
            evidence_refs=evidence_refs,
            depends_on=dep_ids,
            metadata=metadata or {},
        )
        self.store.insert_claim(claim)
        return claim

    def check_gate(self, claim: Claim) -> GateResult:
        evs = self.store.get_evidence_many(claim.evidence_refs)
        parents = [f for f in (self.store.get_fact(fid) for fid in claim.depends_on) if f is not None]
        result = check_gate(claim, evs, parents, self.schema)

        self.store.append_audit(
            event_type="gate_check",
            claim_id=claim.id,
            accepted=result.accepted,
            detail={
                "claim_type": claim.claim_type,
                "violations": [v.model_dump() for v in result.violations],
            },
        )
        return result

    def commit_fact(self, claim: Claim) -> Fact:
        fact = Fact(
            claim_id=claim.id,
            text=claim.text,
            claim_type=claim.claim_type,
            kind=claim.kind,
            evidence_refs=list(claim.evidence_refs),
            depends_on=list(claim.depends_on),
            metadata=dict(claim.metadata),
        )
        self.store.insert_fact(fact)
        self.store.append_audit(
            event_type="fact_committed",
            claim_id=claim.id,
            fact_id=fact.id,
            accepted=True,
            detail={"claim_type": claim.claim_type, "text": claim.text},
        )
        return fact

    def assert_fact(
        self,
        text: str,
        claim_type: str,
        *,
        kind: FactKind = FactKind.OBSERVED,
        evidence: Optional[list[Union[str, Evidence]]] = None,
        depends_on: Optional[list[Union[str, Fact]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AssertResult:
        """One-shot: propose → gate → (commit | reject with actionable feedback)."""
        claim = self.propose_claim(
            text=text,
            claim_type=claim_type,
            kind=kind,
            evidence=evidence,
            depends_on=depends_on,
            metadata=metadata,
        )
        gate = self.check_gate(claim)
        if not gate.accepted:
            return AssertResult(accepted=False, claim=claim, gate=gate, fact=None)
        fact = self.commit_fact(claim)
        return AssertResult(accepted=True, claim=claim, gate=gate, fact=fact)

    # ---------- Cascading invalidation ----------

    def revoke_evidence(self, evidence_id: str, reason: str = "revoked") -> list[str]:
        """Mark an evidence as revoked and cascade-invalidate all dependent facts.

        Returns the list of invalidated fact ids (transitive closure).
        """
        now = datetime.now(timezone.utc)
        ev = self.store.get_evidence(evidence_id)
        if ev is None:
            return []
        # mark revoked
        self.store.conn.execute(
            "UPDATE evidence SET revoked_at=? WHERE id=?",
            (now.isoformat(), evidence_id),
        )
        self.store.conn.commit()

        return self._cascade_invalidate_from_evidence(evidence_id, reason, now)

    def sweep_expired(self) -> list[str]:
        """Re-check all active facts; invalidate those whose evidence has fully expired.

        Useful to call periodically (or on demand before build_context).
        """
        now = datetime.now(timezone.utc)
        invalidated: list[str] = []
        for fact in self.store.list_active_facts():
            if fact.kind == FactKind.OBSERVED and fact.evidence_refs:
                evs = self.store.get_evidence_many(fact.evidence_refs)
                if evs and all(freshness_of(e, self.schema, now=now) == Freshness.EXPIRED for e in evs):
                    self._invalidate(fact.id, "all evidence expired", now)
                    invalidated.append(fact.id)
                    invalidated.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now))
        return invalidated

    def _cascade_invalidate_from_evidence(self, evidence_id: str, reason: str, now: datetime) -> list[str]:
        affected: list[str] = []
        # invalidate observed facts that directly reference this evidence
        for fact in self.store.list_facts_using_evidence(evidence_id):
            self._invalidate(fact.id, f"evidence {evidence_id} {reason}", now)
            affected.append(fact.id)
            affected.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now))
        return affected

    def _cascade_invalidate_from_fact(self, fact_id: str, reason: str, now: datetime) -> list[str]:
        affected: list[str] = []
        for child in self.store.list_facts_depending_on(fact_id):
            self._invalidate(child.id, f"{reason} ({fact_id})", now)
            affected.append(child.id)
            affected.extend(self._cascade_invalidate_from_fact(child.id, reason, now))
        return affected

    def _invalidate(self, fact_id: str, reason: str, now: datetime) -> None:
        self.store.invalidate_fact(fact_id, reason, now)
        self.store.append_audit(
            event_type="fact_invalidated",
            fact_id=fact_id,
            accepted=False,
            detail={"reason": reason},
        )

    # ---------- L2: prompt context ----------

    def build_context(self, query: Optional[str] = None, max_facts: int = 10) -> str:
        return build_context(self.store, self.schema, query=query, max_facts=max_facts)

    # ---------- audit ----------

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_audit(limit=limit)


def _auto_summary(content: str, max_len: int = 120) -> str:
    flat = " ".join(content.split())
    return flat if len(flat) <= max_len else flat[: max_len - 1] + "…"
