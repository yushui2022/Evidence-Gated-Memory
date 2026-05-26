"""Context builder — assembles prompt context from Facts, with provenance & freshness labels.

L2 of the EGM discipline: nothing reaches the model without a source tag,
and stale evidence is visibly marked so the agent can decide whether to reverify.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from evidence_gated_memory.core.freshness import freshness_of
from evidence_gated_memory.core.models import Evidence, Fact, Freshness
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
        evs = store.get_evidence_many(fact.evidence_refs)
        states = [(e, freshness_of(e, schema, now=now)) for e in evs]

        # If every attached evidence is expired, this fact should not influence decisions.
        if states and all(f == Freshness.EXPIRED for _, f in states):
            blocked_any = True
            lines.append(f"[BLOCKED] {fact.text}")
            lines.append(f"  claim_type: {fact.claim_type}")
            lines.append(f"  reason: all {len(states)} supporting evidence ref(s) are expired")
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
