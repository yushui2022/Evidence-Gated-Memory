"""Context builder — assembles prompt context from Facts, with provenance & freshness labels.

L2 of the EGM discipline: nothing reaches the model without a source tag,
and stale evidence is visibly marked so the agent can decide whether to reverify.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from evidence_gated_memory.core.freshness import freshness_of, is_usable
from evidence_gated_memory.core.models import Evidence, Fact, FactKind, Freshness
from evidence_gated_memory.schemas.loader import DomainSchema
from evidence_gated_memory.storage.sqlite import SqliteStore


_FRESHNESS_TAG = {
    Freshness.FRESH:   "fresh",
    Freshness.STALE:   "STALE",
    Freshness.EXPIRED: "EXPIRED",
    Freshness.UNKNOWN: "unknown-ttl",
}


def build_context(
    store: SqliteStore,
    schema: DomainSchema,
    query: Optional[str] = None,
    max_facts: int = 10,
    now: Optional[datetime] = None,
) -> str:
    """Render a markdown prompt context block.

    Strategy v0.1:
      - If `query` is given, FTS-search facts; otherwise list active facts (most recent first).
      - For each fact, resolve evidence and compute freshness.
      - Skip facts whose evidence is fully expired (they cannot ground a decision).
      - Mark stale evidence with a visible warning the LLM can act on.
    """
    now = now or datetime.now(timezone.utc)

    facts = store.search_facts_fts(query, limit=max_facts) if query else store.list_active_facts()[:max_facts]

    lines: list[str] = []
    lines.append("# Evidence-Gated Memory Context")
    if query:
        lines.append(f"_query: {query}_")
    lines.append("")

    if not facts:
        lines.append("_(no facts available — agent should gather evidence before drawing conclusions)_")
        return "\n".join(lines)

    blocked_any = False
    for fact in facts:
        parent_block = _parent_block_reason(store, fact)
        evs = store.get_evidence_many(fact.evidence_refs)
        states = [(e, freshness_of(e, schema, now=now)) for e in evs]
        support_block = _support_block_reason(fact, states, schema)

        # If required support is no longer usable, this fact should not influence decisions.
        if parent_block or support_block:
            blocked_any = True
            lines.append(f"[BLOCKED] {fact.text}")
            lines.append(f"  claim_type: {fact.claim_type}")
            lines.append(f"  reason: {parent_block or support_block}")
            lines.append(f"  action: re-fetch evidence before relying on this fact")
            lines.append("")
            continue

        tag = "FACT"
        if any(f == Freshness.STALE for _, f in states):
            tag = "FACT⚠"

        lines.append(f"[{tag}] {fact.text}")
        lines.append(f"  claim_type: {fact.claim_type}  kind: {fact.kind.value}")

        if not states:
            lines.append(f"  (no evidence resolved)")
        else:
            for ev, f in states:
                age_h = (now - ev.observed_at).total_seconds() / 3600
                age_str = f"{age_h:.1f}h ago" if age_h < 48 else f"{age_h/24:.1f}d ago"
                marker = ""
                if f == Freshness.STALE:
                    marker = "  ⚠ STALE — consider reverifying"
                elif f == Freshness.EXPIRED:
                    marker = "  ⛔ EXPIRED"
                lines.append(
                    f"  - ref={ev.id} type={ev.evidence_type} source={ev.source} "
                    f"observed={age_str} [{_FRESHNESS_TAG[f]}]{marker}"
                )
        lines.append("")

    if blocked_any:
        lines.append("---")
        lines.append("⚠ One or more facts were BLOCKED due to expired evidence. Do not assert conclusions that depend on them without reverification.")

    return "\n".join(lines)


def _parent_block_reason(store: SqliteStore, fact: Fact) -> Optional[str]:
    if fact.kind != FactKind.DERIVED:
        return None
    missing: list[str] = []
    invalidated: list[str] = []
    for parent_id in fact.depends_on:
        parent = store.get_fact(parent_id)
        if parent is None:
            missing.append(parent_id)
        elif parent.invalidated_at is not None:
            invalidated.append(parent_id)
    if missing:
        return f"parent fact(s) missing: {missing}"
    if invalidated:
        return f"parent fact(s) invalidated: {invalidated}"
    return None


def _support_block_reason(
    fact: Fact,
    states: list[tuple[Evidence, Freshness]],
    schema: DomainSchema,
) -> Optional[str]:
    claim_type = schema.claim_type(fact.claim_type)
    if claim_type is None:
        return f"claim_type '{fact.claim_type}' is not declared in schema"

    requirements: list[tuple[str, str]] = []
    claim_freshness = "fresh" if claim_type.requires_fresh_evidence else "stale"
    requirements.extend((evidence_type, claim_freshness) for evidence_type in claim_type.required_evidence)
    for rule in schema.gates:
        if rule.when_claim_type and rule.when_claim_type != fact.claim_type:
            continue
        requirements.extend((evidence_type, rule.require_freshness) for evidence_type in rule.require_evidence_types)

    for evidence_type, required_freshness in requirements:
        candidates = [state for ev, state in states if ev.evidence_type == evidence_type]
        if not candidates:
            return f"required evidence type '{evidence_type}' is missing"
        if not any(is_usable(state, required_freshness) for state in candidates):
            return f"required evidence type '{evidence_type}' has no {required_freshness} support"
    return None
