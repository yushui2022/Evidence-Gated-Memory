"""EvidenceGatedMemory — the public entry point.

Two API surfaces:

  * Easy:    `assert_fact(text, claim_type, evidence=[...])`
             one call: propose → gate → commit (or reject with actionable feedback)

  * Detailed: propose_claim → check_gate → commit_fact(claim, gate_result)
             for advanced users who want to insert custom logic between steps
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from evidence_gated_memory.core.context import build_context
from evidence_gated_memory.core.freshness import freshness_of, is_usable
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
        support_refs = self._support_evidence_refs_for_claim(claim)
        evs, missing_evidence_refs = self._resolve_evidence_refs(support_refs)
        parents, missing_depends_on = self._resolve_fact_refs(claim.depends_on)
        result = check_gate(
            claim,
            evs,
            parents,
            self.schema,
            missing_evidence_refs=missing_evidence_refs,
            missing_depends_on=missing_depends_on,
        )

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

    def commit_fact(self, claim: Claim, gate_result: Optional[GateResult] = None) -> Fact:
        if gate_result is None:
            raise ValueError("commit_fact requires an accepted GateResult; use assert_fact for the safe one-shot path")
        if gate_result.claim_id != claim.id:
            raise ValueError("GateResult does not belong to this claim")
        if not gate_result.accepted:
            raise ValueError(f"cannot commit a rejected claim: {gate_result.rejection_reason}")

        fact = Fact(
            claim_id=claim.id,
            text=claim.text,
            claim_type=claim.claim_type,
            kind=claim.kind,
            evidence_refs=self._support_evidence_refs_for_claim(claim),
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
        fact = self.commit_fact(claim, gate_result=gate)
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
        """Re-check all active facts; invalidate those whose required support expired.

        Useful to call periodically (or on demand before build_context).
        """
        now = datetime.now(timezone.utc)
        invalidated: list[str] = []
        for fact in self.store.list_active_facts():
            reason = self._expiry_invalidation_reason(fact, now)
            if reason:
                self._invalidate(fact.id, reason, now)
                invalidated.append(fact.id)
                invalidated.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now))
        return invalidated

    def _cascade_invalidate_from_evidence(
        self,
        evidence_id: str,
        reason: str,
        now: datetime,
        seen: Optional[set[str]] = None,
    ) -> list[str]:
        seen = seen or set()
        affected: list[str] = []
        # invalidate observed facts that directly reference this evidence
        for fact in self.store.list_facts_using_evidence(evidence_id):
            if fact.id in seen:
                continue
            seen.add(fact.id)
            self._invalidate(fact.id, f"evidence {evidence_id} {reason}", now)
            affected.append(fact.id)
            affected.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now, seen))
        return affected

    def _cascade_invalidate_from_fact(
        self,
        fact_id: str,
        reason: str,
        now: datetime,
        seen: Optional[set[str]] = None,
    ) -> list[str]:
        seen = seen or set()
        affected: list[str] = []
        for child in self.store.list_facts_depending_on(fact_id):
            if child.id in seen:
                continue
            seen.add(child.id)
            self._invalidate(child.id, f"{reason} ({fact_id})", now)
            affected.append(child.id)
            affected.extend(self._cascade_invalidate_from_fact(child.id, reason, now, seen))
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

    # ---------- internal resolution helpers ----------

    def _resolve_evidence_refs(self, refs: list[str]) -> tuple[list[Evidence], list[str]]:
        refs = _dedupe(refs)
        evs = self.store.get_evidence_many(refs)
        by_id = {e.id: e for e in evs}
        return [by_id[r] for r in refs if r in by_id], [r for r in refs if r not in by_id]

    def _resolve_fact_refs(self, refs: list[str]) -> tuple[list[Fact], list[str]]:
        refs = _dedupe(refs)
        facts = [self.store.get_fact(fid) for fid in refs]
        by_id = {f.id: f for f in facts if f is not None}
        return [by_id[r] for r in refs if r in by_id], [r for r in refs if r not in by_id]

    def _support_evidence_refs_for_claim(self, claim: Claim) -> list[str]:
        refs = list(claim.evidence_refs)
        if claim.kind == FactKind.DERIVED:
            parents, _ = self._resolve_fact_refs(claim.depends_on)
            for parent in parents:
                refs.extend(self._support_evidence_refs_for_fact(parent))
        return _dedupe(refs)

    def _support_evidence_refs_for_fact(self, fact: Fact, seen: Optional[set[str]] = None) -> list[str]:
        seen = seen or set()
        if fact.id in seen:
            return []
        seen.add(fact.id)

        refs = list(fact.evidence_refs)
        for parent_id in fact.depends_on:
            parent = self.store.get_fact(parent_id)
            if parent is not None:
                refs.extend(self._support_evidence_refs_for_fact(parent, seen))
        return _dedupe(refs)

    def _expiry_invalidation_reason(self, fact: Fact, now: datetime) -> Optional[str]:
        if fact.kind == FactKind.DERIVED:
            parents, missing = self._resolve_fact_refs(fact.depends_on)
            if missing:
                return f"parent fact missing: {missing}"
            dead = [p.id for p in parents if p.invalidated_at is not None]
            if dead:
                return f"parent fact invalidated: {dead}"

        claim_type = self.schema.claim_type(fact.claim_type)
        if claim_type is None:
            return f"claim_type '{fact.claim_type}' no longer declared in schema"

        refs = self._support_evidence_refs_for_fact(fact)
        evs, missing_refs = self._resolve_evidence_refs(refs)
        if missing_refs:
            return f"supporting evidence ref missing: {missing_refs}"

        requirements: list[tuple[str, str]] = []
        claim_freshness = "fresh" if claim_type.requires_fresh_evidence else "stale"
        requirements.extend((evidence_type, claim_freshness) for evidence_type in claim_type.required_evidence)
        for rule in self.schema.gates:
            if rule.when_claim_type and rule.when_claim_type != fact.claim_type:
                continue
            requirements.extend((evidence_type, rule.require_freshness) for evidence_type in rule.require_evidence_types)

        for evidence_type, required_freshness in requirements:
            candidates = [e for e in evs if e.evidence_type == evidence_type]
            if not candidates:
                return f"required evidence type '{evidence_type}' missing"
            if not any(is_usable(freshness_of(e, self.schema, now=now), required_freshness) for e in candidates):
                return f"required evidence type '{evidence_type}' no longer has {required_freshness} support"
        return None


def _auto_summary(content: str, max_len: int = 120) -> str:
    flat = " ".join(content.split())
    return flat if len(flat) <= max_len else flat[: max_len - 1] + "…"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
