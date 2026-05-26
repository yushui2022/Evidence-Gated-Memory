"""Gate engine — turns rejection into actionable feedback.

Gate semantics (v0.1, kept intentionally small):

1. claim_requires_source         (built-in, always on)
   A claim of kind OBSERVED must have at least one evidence_ref.
   A claim of kind DERIVED must have at least one depends_on.

2. claim_type required evidence types (built-in, from schema.claim_type.required_evidence)
   The set of evidence_types attached must cover the declared required set.

3. evidence freshness            (built-in)
   All evidence refs supporting an OBSERVED claim must be at least STALE
   (and FRESH if claim_type.requires_fresh_evidence is true).

4. schema-declared GateRule      (declarative)
   Each rule matching the claim_type adds its own require_evidence_types /
   require_freshness checks.

5. llm_output_not_as_source      (built-in, always on)
   An evidence with source_system == "llm" is never an acceptable source ref.

6. derived facts must rest on live facts (built-in)
   For DERIVED claims, every depends_on Fact must not be invalidated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from evidence_gated_memory.core.freshness import freshness_of, is_usable
from evidence_gated_memory.core.models import (
    Claim,
    Evidence,
    Fact,
    FactKind,
    Freshness,
    GateResult,
    GateViolation,
)
from evidence_gated_memory.schemas.loader import DomainSchema


def check_gate(
    claim: Claim,
    evidence: list[Evidence],
    depends_on_facts: list[Fact],
    schema: DomainSchema,
    now: datetime | None = None,
) -> GateResult:
    now = now or datetime.now(timezone.utc)
    violations: list[GateViolation] = []

    # 1. structural requirement
    if claim.kind == FactKind.OBSERVED and not evidence:
        violations.append(GateViolation(
            gate="claim_requires_source",
            reason="observed claim has no evidence_refs",
            suggested_action="attach at least one Evidence ref before asserting this fact",
        ))
    if claim.kind == FactKind.DERIVED and not depends_on_facts:
        violations.append(GateViolation(
            gate="derived_requires_dependencies",
            reason="derived claim has no depends_on facts",
            suggested_action="declare which existing facts this conclusion is derived from",
        ))

    # 5. LLM-sourced evidence is never a valid fact source
    llm_refs = [e.id for e in evidence if (e.source_system or "").lower() == "llm"]
    if llm_refs:
        violations.append(GateViolation(
            gate="llm_output_not_as_source",
            reason=f"{len(llm_refs)} evidence ref(s) come from LLM output and cannot ground facts",
            stale_refs=llm_refs,
            suggested_action="ground this claim in evidence from a real source system (API, DB, human)",
        ))

    # 6. derived: all parent facts must be live
    dead_parents = [f.id for f in depends_on_facts if f.invalidated_at is not None]
    if dead_parents:
        violations.append(GateViolation(
            gate="derived_requires_live_parents",
            reason=f"depends on {len(dead_parents)} invalidated fact(s): {dead_parents}",
            suggested_action="re-derive this conclusion from currently valid facts",
        ))

    # 2 + 3. claim_type required evidence + freshness
    claim_type = schema.claim_type(claim.claim_type)
    required_freshness_strict = bool(claim_type and claim_type.requires_fresh_evidence)
    required_types: set[str] = set(claim_type.required_evidence) if claim_type else set()

    attached_types = {e.evidence_type for e in evidence}
    missing = sorted(required_types - attached_types)
    if missing:
        violations.append(GateViolation(
            gate="claim_type_required_evidence",
            reason=f"missing required evidence types: {missing}",
            missing_evidence_types=missing,
            suggested_action=_suggest_for_missing(missing),
        ))

    # freshness of attached evidence
    expired_refs = []
    stale_refs = []
    for e in evidence:
        f = freshness_of(e, schema, now=now)
        if f == Freshness.EXPIRED:
            expired_refs.append(e.id)
        elif f == Freshness.STALE:
            stale_refs.append(e.id)

    if expired_refs:
        violations.append(GateViolation(
            gate="expired_evidence_block",
            reason=f"{len(expired_refs)} evidence ref(s) have expired",
            expired_refs=expired_refs,
            suggested_action="re-fetch from source system to obtain fresh evidence",
        ))
    if stale_refs and required_freshness_strict:
        violations.append(GateViolation(
            gate="stale_evidence_block_strict",
            reason=f"claim_type requires fresh evidence but {len(stale_refs)} ref(s) are stale",
            stale_refs=stale_refs,
            suggested_action="re-fetch from source system to refresh evidence",
        ))

    # 4. declarative gates from schema
    for rule in schema.gates:
        if rule.when_claim_type and rule.when_claim_type != claim.claim_type:
            continue

        rule_missing = sorted(set(rule.require_evidence_types) - attached_types)
        if rule_missing:
            violations.append(GateViolation(
                gate=rule.name,
                reason=f"gate '{rule.name}' requires evidence types {rule_missing}",
                missing_evidence_types=rule_missing,
                suggested_action=rule.suggested_action or _suggest_for_missing(rule_missing),
            ))

        # gate-level freshness override
        for e in evidence:
            if e.evidence_type not in rule.require_evidence_types:
                continue
            f = freshness_of(e, schema, now=now)
            if not is_usable(f, rule.require_freshness):
                violations.append(GateViolation(
                    gate=rule.name,
                    reason=f"gate '{rule.name}' requires {rule.require_freshness} evidence; {e.id} is {f.value}",
                    expired_refs=[e.id] if f == Freshness.EXPIRED else [],
                    stale_refs=[e.id] if f == Freshness.STALE else [],
                    suggested_action=rule.suggested_action or "re-fetch evidence from source system",
                ))

    return GateResult(
        accepted=not violations,
        claim_id=claim.id,
        violations=violations,
    )


def _suggest_for_missing(missing_types: Iterable[str]) -> str:
    types = list(missing_types)
    if not types:
        return ""
    if len(types) == 1:
        return f"fetch evidence of type '{types[0]}' from the corresponding source system"
    return f"fetch evidence of types {types} from the corresponding source systems"
