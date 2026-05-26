"""Gate engine — turns rejection into actionable feedback.

Gate semantics (v0.1, kept intentionally small):

1. claim_requires_source         (built-in, always on)
   A claim of kind OBSERVED must have at least one evidence_ref.
   A claim of kind DERIVED must have at least one depends_on.

2. schema strictness             (built-in, always on)
   Unknown claim_type / evidence_type are rejected; declared source_systems
   are enforced as an allowlist.

3. claim_type required evidence types (built-in, from schema.claim_type.required_evidence)
   The set of supporting evidence_types must cover the declared required set.

4. evidence freshness            (built-in)
   Required evidence must not be expired; claim types marked
   requires_fresh_evidence require fresh evidence.

5. schema-declared GateRule      (declarative)
   Each rule matching the claim_type adds its own require_evidence_types /
   require_freshness checks.

6. llm_output_not_as_source      (built-in, always on)
   An evidence with source_system == "llm" is never an acceptable source ref.

7. derived facts must rest on live facts (built-in)
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
    missing_evidence_refs: list[str] | None = None,
    missing_depends_on: list[str] | None = None,
) -> GateResult:
    now = now or datetime.now(timezone.utc)
    violations: list[GateViolation] = []
    missing_evidence_refs = missing_evidence_refs or []
    missing_depends_on = missing_depends_on or []

    # 1. structural requirement
    if claim.kind == FactKind.OBSERVED and not evidence:
        violations.append(GateViolation(
            gate="claim_requires_source",
            reason="observed claim has no evidence_refs",
            suggested_action="attach at least one Evidence ref before asserting this fact",
        ))
    if missing_evidence_refs:
        violations.append(GateViolation(
            gate="missing_evidence_refs",
            reason=f"{len(missing_evidence_refs)} evidence ref(s) could not be resolved: {missing_evidence_refs}",
            suggested_action="attach only existing Evidence refs before asserting this fact",
        ))
    if claim.kind == FactKind.DERIVED and not claim.depends_on:
        violations.append(GateViolation(
            gate="derived_requires_dependencies",
            reason="derived claim has no depends_on facts",
            suggested_action="declare which existing facts this conclusion is derived from",
        ))
    if missing_depends_on:
        violations.append(GateViolation(
            gate="missing_dependency_facts",
            reason=f"{len(missing_depends_on)} parent fact(s) could not be resolved: {missing_depends_on}",
            suggested_action="derive only from existing Fact ids",
        ))

    # 2. schema strictness for claim and evidence.
    claim_type = schema.claim_type(claim.claim_type)
    if claim_type is None:
        violations.append(GateViolation(
            gate="unknown_claim_type",
            reason=f"claim_type '{claim.claim_type}' is not declared in the domain schema",
            suggested_action="add this claim_type to the domain schema or use a declared claim_type",
        ))

    for e in evidence:
        type_def = schema.evidence_type(e.evidence_type)
        if type_def is None:
            violations.append(GateViolation(
                gate="unknown_evidence_type",
                reason=f"evidence_type '{e.evidence_type}' is not declared in the domain schema",
                suggested_action="add this evidence_type to the domain schema or attach declared evidence",
            ))
            continue
        if type_def.source_systems:
            source_system = e.source_system or e.source
            if source_system not in type_def.source_systems:
                violations.append(GateViolation(
                    gate="source_system_not_allowed",
                    reason=(
                        f"evidence {e.id} type '{e.evidence_type}' came from source_system "
                        f"'{source_system}', expected one of {type_def.source_systems}"
                    ),
                    suggested_action=f"fetch '{e.evidence_type}' from an allowed source system",
                ))

    # 6. LLM-sourced evidence is never a valid fact source
    llm_refs = [e.id for e in evidence if (e.source_system or "").lower() == "llm"]
    if llm_refs:
        violations.append(GateViolation(
            gate="llm_output_not_as_source",
            reason=f"{len(llm_refs)} evidence ref(s) come from LLM output and cannot ground facts",
            stale_refs=llm_refs,
            suggested_action="ground this claim in evidence from a real source system (API, DB, human)",
        ))

    # 7. derived: all parent facts must be live
    dead_parents = [f.id for f in depends_on_facts if f.invalidated_at is not None]
    if dead_parents:
        violations.append(GateViolation(
            gate="derived_requires_live_parents",
            reason=f"depends on {len(dead_parents)} invalidated fact(s): {dead_parents}",
            suggested_action="re-derive this conclusion from currently valid facts",
        ))

    # 3 + 4. claim_type required evidence + freshness
    required_types: set[str] = set(claim_type.required_evidence) if claim_type else set()
    required_freshness = "fresh" if bool(claim_type and claim_type.requires_fresh_evidence) else "stale"

    attached_types = {e.evidence_type for e in evidence}
    missing = sorted(required_types - attached_types)
    if missing:
        violations.append(GateViolation(
            gate="claim_type_required_evidence",
            reason=f"missing required evidence types: {missing}",
            missing_evidence_types=missing,
            suggested_action=_suggest_for_missing(missing),
        ))

    for evidence_type in sorted(required_types & attached_types):
        violations.extend(_freshness_violations_for_type(
            gate="expired_evidence_block" if required_freshness != "fresh" else "stale_evidence_block_strict",
            evidence_type=evidence_type,
            evidence=evidence,
            schema=schema,
            now=now,
            required_freshness=required_freshness,
            suggested_action="re-fetch from source system to refresh evidence",
            strict_reason=(
                f"claim_type requires fresh evidence for '{evidence_type}'"
                if required_freshness == "fresh"
                else f"required evidence type '{evidence_type}' has no usable non-expired refs"
            ),
        ))

    # 5. declarative gates from schema
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
        for evidence_type in sorted(set(rule.require_evidence_types) & attached_types):
            violations.extend(_freshness_violations_for_type(
                gate=rule.name,
                evidence_type=evidence_type,
                evidence=evidence,
                schema=schema,
                now=now,
                required_freshness=rule.require_freshness,
                suggested_action=rule.suggested_action or "re-fetch evidence from source system",
                strict_reason=f"gate '{rule.name}' requires {rule.require_freshness} evidence for '{evidence_type}'",
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


def _freshness_violations_for_type(
    *,
    gate: str,
    evidence_type: str,
    evidence: list[Evidence],
    schema: DomainSchema,
    now: datetime,
    required_freshness: str,
    suggested_action: str,
    strict_reason: str,
) -> list[GateViolation]:
    """Return a violation if no ref of `evidence_type` satisfies freshness.

    Multiple refs of the same type are allowed. A required support type is usable
    if at least one attached ref of that type satisfies the freshness threshold.
    Optional expired refs do not block the claim.
    """
    refs = [e for e in evidence if e.evidence_type == evidence_type]
    if not refs:
        return []

    states = [(e, freshness_of(e, schema, now=now)) for e in refs]
    usable = [(e, state) for e, state in states if is_usable(state, required_freshness)]
    if usable:
        return []

    expired_refs = [e.id for e, state in states if state == Freshness.EXPIRED]
    stale_refs = [e.id for e, state in states if state == Freshness.STALE]
    violation_gate = "expired_evidence_block" if expired_refs and len(expired_refs) == len(states) else gate
    return [GateViolation(
        gate=violation_gate,
        reason=strict_reason,
        expired_refs=expired_refs,
        stale_refs=stale_refs,
        suggested_action=suggested_action,
    )]
