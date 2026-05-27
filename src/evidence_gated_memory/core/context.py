"""Context builder — assembles prompt context from Facts, with provenance & freshness labels.

L2 of the EGM discipline: nothing reaches the model without a source tag,
and stale evidence is visibly marked so the agent can decide whether to reverify.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from evidence_gated_memory.core.freshness import freshness_of, is_usable
from evidence_gated_memory.core.mermaid import render_mermaid
from evidence_gated_memory.core.models import (
    Evidence,
    Fact,
    FactKind,
    Freshness,
    MemoryAtom,
    MemoryPersona,
    MemoryScenario,
    derive_task_state,
)
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
    task_id: Optional[str] = None,
    max_facts: int = 10,
    include_long_term: bool = True,
    max_memory_atoms: int = 5,
    max_memory_scenarios: int = 3,
    max_memory_personas: int = 2,
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

    facts = _select_facts(store, query=query, task_id=task_id, max_facts=max_facts)

    lines: list[str] = []
    lines.append("# Evidence-Gated Memory Context")
    if query:
        lines.append(f"_query: {query}_")
    if task_id:
        lines.append(f"_task_id: {task_id}_")
    lines.append("")

    if include_long_term:
        lines.extend(_long_term_memory_block(
            store,
            query=query,
            max_atoms=max_memory_atoms,
            max_scenarios=max_memory_scenarios,
            max_personas=max_memory_personas,
        ))

    if task_id:
        lines.extend(_task_map_block(store, task_id))

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
        if fact.node_id:
            lines.append(f"  node: {fact.node_id}")

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
                    f"observed={age_str} [{_FRESHNESS_TAG[f]}]"
                    f"{' node=' + ev.node_id if ev.node_id else ''}{marker}"
                )
        lines.append("")

    if blocked_any:
        lines.append("---")
        lines.append("⚠ One or more facts were BLOCKED due to expired evidence. Do not assert conclusions that depend on them without reverification.")

    return "\n".join(lines)


def _long_term_memory_block(
    store: SqliteStore,
    *,
    query: Optional[str],
    max_atoms: int,
    max_scenarios: int,
    max_personas: int,
) -> list[str]:
    personas = _select_personas(store, query=query, limit=max_personas)
    scenarios = _select_scenarios(store, query=query, limit=max_scenarios)
    atoms = _select_atoms(store, query=query, limit=max_atoms)
    if not personas and not scenarios and not atoms:
        return []

    lines: list[str] = ["<long_term_memory>"]
    if personas:
        lines.append("## L3 Personas")
        for persona in personas:
            lines.extend(_render_persona(persona))
    if scenarios:
        lines.append("## L2 Scenarios")
        for scenario in scenarios:
            lines.extend(_render_scenario(scenario))
    if atoms:
        lines.append("## L1 Atoms")
        for atom in atoms:
            lines.extend(_render_atom(atom))
    lines.append("</long_term_memory>")
    lines.append("")
    return lines


def _select_personas(
    store: SqliteStore,
    *,
    query: Optional[str],
    limit: int,
) -> list[MemoryPersona]:
    if limit <= 0:
        return []
    personas = (
        store.search_memory_personas(query, limit=limit)
        if query
        else store.list_memory_personas()
    )
    return personas[:limit]


def _select_scenarios(
    store: SqliteStore,
    *,
    query: Optional[str],
    limit: int,
) -> list[MemoryScenario]:
    if limit <= 0:
        return []
    scenarios = (
        store.search_memory_scenarios(query, limit=limit)
        if query
        else store.list_memory_scenarios()
    )
    return scenarios[:limit]


def _select_atoms(
    store: SqliteStore,
    *,
    query: Optional[str],
    limit: int,
) -> list[MemoryAtom]:
    if limit <= 0:
        return []
    atoms = (
        store.search_memory_atoms(query, limit=limit)
        if query
        else store.list_memory_atoms()
    )
    return atoms[:limit]


def _render_persona(persona: MemoryPersona) -> list[str]:
    return [
        f"[PERSONA] {persona.name}",
        f"  id: {persona.id}",
        f"  summary: {persona.summary}",
        f"  scenario_ids: {persona.scenario_ids}",
        "",
    ]


def _render_scenario(scenario: MemoryScenario) -> list[str]:
    return [
        f"[SCENARIO] {scenario.title}",
        f"  id: {scenario.id}",
        f"  summary: {scenario.summary}",
        f"  atom_ids: {scenario.atom_ids}",
        "",
    ]


def _render_atom(atom: MemoryAtom) -> list[str]:
    return [
        f"[ATOM:{atom.kind.value}] {atom.text}",
        f"  id: {atom.id}",
        f"  source_message_ids: {atom.source_message_ids}",
        "",
    ]


def _task_map_block(store: SqliteStore, task_id: str) -> list[str]:
    nodes = store.list_task_nodes(task_id=task_id)
    edges = store.list_task_edges(task_id=task_id)
    task = store.get_task(task_id)
    task_status = task.status.value if task else "unknown"
    current_state = (
        task.current_state.value
        if task
        else derive_task_state(node.status for node in nodes).value
    )
    mermaid = render_mermaid(nodes, edges=edges)
    return [
        "<task_map>",
        f"task_id: {task_id}",
        "```mermaid",
        mermaid,
        "```",
        "</task_map>",
        "",
        f"<task_status>{task_status}</task_status>",
        "",
        f"<current_state>{current_state}</current_state>",
        "",
    ]


def _select_facts(
    store: SqliteStore,
    *,
    query: Optional[str],
    task_id: Optional[str],
    max_facts: int,
) -> list[Fact]:
    """Return facts with task-linked facts boosted when task_id is supplied.

    This is deliberately a small ranking layer, not a new retrieval backend:
    task focus is a prompt-context signal. If facts are linked to the active
    task's nodes, show them first and keep them when max_facts is tight; then
    fill the remaining slots with the normal recency/FTS result.
    """
    search_limit = max_facts if not task_id else max(max_facts * 5, 50)
    facts = store.search_facts_fts(query, limit=search_limit) if query else store.list_active_facts()
    if not task_id:
        return facts[:max_facts]

    node_ids = {node.id for node in store.list_task_nodes(task_id=task_id)}
    if not node_ids:
        return facts[:max_facts]

    focused = [fact for fact in facts if fact.node_id in node_ids]
    focused_ids = {fact.id for fact in focused}
    rest = [fact for fact in facts if fact.id not in focused_ids]
    return (focused + rest)[:max_facts]


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
