# HANDOFF — to whoever picks this project up next

> Written by Claude Opus 4.7 on 2026-05-26, at the close of the session that
> brought EGM from "evidence-gating core" to "graph-memory pillar standing on
> its own". The user (yushui2022) may not be able to keep paying for Opus,
> so the next sessions will likely be Codex 5.5 with occasional Opus review.
>
> This file is **not** a re-statement of the README. The README explains the
> system. This file explains **what to be careful about when changing it**,
> based on mistakes already made and conversations already had.

---

## 0. Read this first, before touching code

1. Read the **`## Project status & handoff`** section at the bottom of `README.md`. It is the live status board — task table, ordering, what to resume on.
2. Read this file all the way through. It is short.
3. Run `python -m pytest`. You must see **73 passed**. If you don't, stop and figure out why before changing anything.
4. Look at the actual API surface in `src/evidence_gated_memory/core/memory.py` once — don't trust this doc or the README to be exact on signatures; trust the code.

---

## 1. The three things that are easy to get wrong

These are not stylistic preferences. They are load-bearing invariants. Every one of them was discussed, sometimes argued, and settled.

### 1.1 `update_task_node_status` is **NOT** the gated API

It is intentionally low-level CRUD. It does not consult any gate. It exists for setup, tests, and recovery.

The gated counterpart is `transition_node()` and lives in **task #31**, which is still pending. When #31 lands, the rule will be:

- Production code paths (the agent, the orchestrator) call `transition_node()` — it goes through a state-transition gate and can return a rejection with `suggested_action`.
- Tests, fixtures, and recovery scripts may still call `update_task_node_status()` to skip gating.

**If you find yourself wanting `update_task_node_status` to "just check one thing first" — stop.** That's the camel's nose. The split is the whole point. Add the check to `transition_node` instead.

### 1.2 Facts must never bypass the gate

`commit_fact(claim)` currently accepts an optional `gate_result` argument and will fall back to computing one. Task **#17** is to make `gate_result` **required**. Until #17 lands, do not add new internal call sites that pass `claim` alone — they will silently bypass the gate if the gate logic ever has a bug.

If you're writing a new internal API that produces facts, take the `GateResult` as a parameter and pass it down. Don't recompute.

### 1.3 Attach calls validate the target — keep it that way

`attach_evidence_to_node` and `attach_fact_to_node` do three things that look paranoid but aren't:

- evidence id must exist → `KeyError`
- fact id must exist → `KeyError`
- fact must not be invalidated → `ValueError`

The reason: a TaskNode's `evidence_refs` / `fact_refs` are the agent's drill-down handles into raw evidence. A phantom or invalidated ref silently breaks EGM's core promise that the graph is auditable.

If a test or new feature wants to skip this check, that is the moment to push back and ask **why** the caller doesn't have a real id.

---

## 2. Things that have already been argued and decided — don't relitigate

Each of these was a real debate, often with Codex on the other side. Don't re-open without new evidence.

| Decision | Why | Where it lives |
|---|---|---|
| TaskNode granularity = business node, not per-message or per-tool-call | Per-message granularity makes the graph noise; per-tool-call makes it event log. Business node is the only level where "blocked / done / skipped" means anything. | `create_task_node()` semantics |
| TaskNodes are created by explicit API, not auto-derived from events | Auto-derivation requires a heuristic; heuristics drift; drift in a memory-of-record is poison. | `create_task_node()` is the only entry |
| `update_task_node_status` is CRUD, gated transitions are `transition_node` (#31) | See §1.1 | `memory.py` docstring on `update_task_node_status` |
| Build the validation/audit floor before the Mermaid projection | A graph that contains un-audited state changes or phantom refs would contradict EGM's whole point. | Why #30 was done before #20 |
| Mermaid is **a projection**, not the source of truth | The TaskGraph is structured rows. Mermaid is one renderable view. Anything that treats Mermaid as authoritative will lose data. | `core/mermaid.py` is pure, no DB |
| Cross-task edges are forbidden | A TaskEdge between two workflows muddies every per-task projection. If you need to express "this workflow blocks that workflow", model it on the Task level, not the node level. | `add_task_edge()` in `memory.py` |
| Edges are only rendered when `task_id` filter is set | Global render across tasks is meaningless once edges exist. | `render_task_graph()` in `memory.py` |
| Every TaskNode mutation writes an audit entry | No silent state change. Period. | search for `append_audit` in `memory.py` |

---

## 3. The execution order, and why it is what it is

Current order (also in README):

```
✅ #28 #30 #20 #32 #23      ← landed
⬜ #24 #25 #21              ← unblocked, pick any
⬜ #22                       (needs #21)
⬜ #31                       (needs #22)
⬜ #26                       (architecture doc, last)
```

**Why this order and not another:**

- **#28 → #30 → #20**: structure first, validation second, projection last. Render before validation = pretty pictures of an untrustworthy graph. This was the explicit ask, and it's worth defending.
- **#32 before #21**: typed edges are pure additions (no behavior change to existing rows); the soft state machine touches every status transition. Touch additive things first.
- **#23 before #24, #25**: build_context and retrieval both want the `node_id` back-link. Doing #23 first means #24 and #25 are independent and parallelizable.
- **#22 strictly after #21**: gating state transitions requires knowing what valid transitions look like — that's what #21 defines.
- **#31 strictly after #22**: `transition_node` is the public face of the gate system from #22.
- **#26 last**: architecture documentation written *before* the architecture stabilizes is technical debt with a doc string on it.

If Codex wants to reorder, the question to ask is: *which invariant would be temporarily violated?* If any of §1 or §2 would be, don't reorder.

---

## 4. Risks, by area

### 4.1 SQLite schema drift

The codebase has `CREATE TABLE IF NOT EXISTS`. That means **adding a column to an existing table will silently do nothing on databases created before that release**. New columns added so far (`node_id` on `evidence` and `facts`) shipped together with tests that exercise them on fresh DBs only.

**If you add a column to an existing table**, you must either:
- bump the workspace format and refuse to open older DBs, or
- add an `ALTER TABLE ADD COLUMN` migration that runs on open.

Right now there is **no migration story**. The workspace is treated as ephemeral. If a real user ever deploys this and creates a long-lived workspace, the next schema change will quietly corrupt their data.

### 4.2 FTS5 query escaping

Already a footgun — see commit `c2b8fda` and earlier. Search code lives in `search_facts_fts`. Any new FTS query path must go through `_sanitize_fts_query` and fall back to LIKE. Don't roll your own.

### 4.3 Domain schema YAML — there is no strict mode yet

Task **#13** is "strict schema: reject unknown evidence/claim types outright". Until that lands, a typo in YAML (`order_recrod` instead of `order_record`) will silently produce evidence that no gate ever requires. Be paranoid when editing the schemas in `src/evidence_gated_memory/schemas/builtin/*.yaml`.

### 4.4 Cascading invalidation is correct but not cheap

`revoke_evidence` does a JSON `LIKE` scan of `facts.depends_on`. Fine at 10k facts, will not be fine at 10M. Don't fix it preemptively — the right fix is a join table, but it's a refactor, not a tweak.

### 4.5 Audit log is append-only and unbounded

Every TaskNode/Task/Edge mutation appends a row. There is no rotation. Long sessions will grow `audit_log` indefinitely. This is intentional for now (audit is part of EGM's value), but at some point a retention policy will be needed.

### 4.6 LLM entity extraction is a low-trust annotation

`extract_entities` has a chain: metadata → connector → regex → LLM fallback. The LLM result is **never** acceptable as a source for fact grounding. If someone tries to use `entities["llm_extracted"]` as evidence, refuse. This invariant is currently enforced by convention, not by the type system. Watch for code that crosses the line.

### 4.7 The `_ensure_task` auto-create has a subtle assumption

When `create_task_node("task_X", ...)` is called for an unknown `task_X`, the workflow row is auto-materialized with `title=task_id`. If a caller later calls `create_task("task_X", title="real title")`, the title is overwritten. This is intentional (back-compat) but means **explicit `create_task` calls should come before any `create_task_node` calls** if you care about the title being right from the start.

---

## 5. What to ask Opus to review (if/when you can afford another session)

These are the moments where the cost of a wrong call is high enough that a second opinion is probably worth it. Bring the diff and ask.

1. **Before #22 (gating state transitions)** — the design of which transitions go through the gate, and what evidence each requires. Getting this wrong locks the agent into states it can't leave, or lets it claim DONE without proof. **High blast radius.**
2. **Before #21 (TaskState aggregation rules)** — how `Task.status` is derived from its child node statuses. Easy to write a rule that disagrees with itself in edge cases (one child BLOCKED, another DONE — is the Task BLOCKED or IN_PROGRESS?). Worth a careful pass.
3. **Before #17 (`commit_fact` requires `GateResult`)** — touches every internal call site that produces a fact. Easy to miss one and silently bypass the gate.
4. **Before #15 (rewrite derived-fact semantics)** — derived facts depend on observed parents; cascading invalidation depends on this being right. Easy to get the closure wrong.
5. **Before writing the architecture doc (#26)** — it locks in vocabulary. Worth one pass to make sure the diagram and the README and the doc agree.
6. **Before bumping to 0.3.0 or anything that pretends to be stable** — full surface review of the public API.

Don't ask Opus for help with:
- writing more tests (Codex is fine)
- adding new evidence types or claim types (Codex is fine)
- writing the Mermaid CSS / projection details (it's pure-function, easy to verify)
- routine refactors with clear test coverage

The rule: ask Opus when **the cost of being wrong is paid by future selves**, not when the cost is paid by the current PR.

---

## 6. The vibe to maintain

This part is the soft stuff. Skip if you only want rules.

EGM's value is **trustworthiness, not throughput**. Every time you find yourself thinking "we can skip the check here for now" — that is exactly the moment the system stops being valuable. Mem0 and Zep are write-optimistic; that's why we exist as an alternative. If EGM becomes write-optimistic too, there is nothing left.

The user (yushui2022) has been clear and consistent about this: build the floor first, then the next floor. They corrected me twice in our sessions when I drifted toward "ship the feature, harden later." They were right both times.

Also: the user thinks carefully and reads what you write. They will catch sloppiness. Don't dump options on them when one is clearly better — make a recommendation and explain the trade. Don't pretend a hard problem is easy.

---

## 7. If you only remember three things

1. **`update_task_node_status` is CRUD, not gated.** The gated path is `transition_node` (#31).
2. **Attach validates, gates gate, derived facts cascade.** These are the load-bearing invariants. Breaking any of them silently breaks the whole product.
3. **The README's "Project status & handoff" section is the live truth. Update it when you land work.** This file is the philosophy; that file is the state.

Good luck. The bones are good.

— Opus 4.7
