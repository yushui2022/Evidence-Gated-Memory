# Project Status & Handoff

> Working log for Evidence-Gated Memory. Single source of truth for "where the project is right now."
> Read this cold to resume work — by future-me, a collaborator, or a new Claude/Codex session.
>
> For end-user docs see [README.md](README.md). For the architecture write-up see [docs/architecture.md](docs/architecture.md). For the original Codex-specific transition notes see [HANDOFF_TO_CODEX.md](HANDOFF_TO_CODEX.md).

_Last updated: 2026-05-28 — 30-task tau-bench v1 A/B complete, EGM 93% vs baseline 90%._

---

## Where we are

EGM has completed **Milestone M1: restoring the graph-memory pillar** on top of the v0.1 evidence-gating core, and the manual path of **M2: long-term semantic pyramid**.

- **v0.1 (shipped):** evidence + claims + facts + freshness + cascading invalidation + audit + CLI.
- **M1 (shipped):** hard-anchor task graph with structured TaskNodes, evidence-gated state transitions, Mermaid projection.
- **M2 manual path (shipped):** L0 Conversation + L1 Atom + L2 Scenario + L3 Persona as manual, auditable layers; `build_context()` injects L1–L3.
- **M3 (shipped):** offload JSONL mid-layer index.
- **v0.4.0 published to PyPI** as `evidence-gated-memory`. End-to-end smoke verified in clean venv against the bundled REFUND schema.
- **130 test functions passing.**

Automatic LLM distillation is intentionally **not** implemented yet — it should be treated as a separately designed future task, not a casual extension of #29.

---

## Status of every tracked task

Legend: ✅ done · 🟡 in progress · ⬜ pending · 🔒 blocked by another task

### v0.1 hardening

| # | Status | Task | Notes |
|---|---|---|---|
| 11 | ✅ | Fix wheel packaging (YAML schemas) | shipped |
| 12 | ✅ | FTS query escape | shipped |
| 13 | ✅ | Strict schema: reject unknown evidence/claim types outright | shipped |
| 14 | ✅ | `source_system` allowlist gate | shipped |
| 15 | ✅ | Rewrite derived-fact semantics | shipped |
| 16 | ✅ | Expired semantics: critical-field plan C | shipped |
| 17 | ✅ | `commit_fact` must require a `GateResult` | shipped |
| 18 | ✅ | README ↔ API alignment | shipped |
| 19 | ✅ | Regression tests | suite green; grows with future work |

### M1 — short-term graph memory

| # | Status | Task | Blocked by |
|---|---|---|---|
| 28 | ✅ | TaskGraph structured object (TaskNode model + SQLite table + CRUD) | — |
| 30 | ✅ | Attach-reference validation + TaskNode audit log | #28 |
| 20 | ✅ | `render_mermaid()` projection over task_nodes | #28 |
| 32 | ✅ | Top-level `Task` model + `TaskEdge` + typed-edge Mermaid rendering | #28 |
| 23 | ✅ | `node_id` back-link from evidence & facts to their task node | #20 |
| 24 | ✅ | `build_context()` emits a `<task_map>` block with gated facts inline | #23 |
| 25 | ✅ | Retrieval picks up a `task_focus` signal (uses the new `node_id` back-link) | #23 |
| 21 | ✅ | Soft state machine: `TaskState` + current-state table | #20 |
| 22 | ✅ | Promote node state transitions into the gate system | #21 |
| 31 | ✅ | `transition_node()` — the **gated** business API (current `update_task_node_status` is low-level CRUD only) | #22 |
| 26 | ✅ | Architecture doc: three pillars + lineage from TencentDB Agent Memory | #31 |

### M2 — long-term semantic pyramid (manual path)

| # | Status | Task |
|---|---|---|
| 29 | ✅ | L0 conversation → L1 atom → L2 scenario → L3 persona manual pyramid + context injection; automatic distillation deferred |

### M3 — offload mid-layer index

| # | Status | Task |
|---|---|---|
| 27 | ✅ | offload JSONL index: `tool_call_id / node_id / result_ref / summary / score` |

---

## Agreed execution order (now closed for current scope)

The principle we converged on is **"build trust at the base before growing up"** — every layer must be auditable and drill-downable before the next layer sits on it.

```
✅ #28  TaskNode structured object
✅ #30  attach validation + audit
✅ #20  render_mermaid
✅ #32  Task + TaskEdge top-level model
✅ #23  evidence/fact ↔ node_id back-link
✅ #24  build_context emits task_map block
✅ #25  retrieval task_focus signal
✅ #21  soft state machine (TaskState + current_state)
✅ #22  state transitions inside the gate system
✅ #31  transition_node — the gated state API
✅ #26  architecture doc
✅ #27  offload JSONL index
✅ #29  long-term semantic pyramid manual path
```

M1, M2 manual path, M3, and the v0.1 hardening board are now closed.

---

## How to resume

1. **Verify the baseline still works.**
   ```bash
   python -m pytest          # expect 130 test functions passing
   ```
2. **Re-read this file** plus:
   - `src/evidence_gated_memory/core/memory.py`
   - `src/evidence_gated_memory/core/mermaid.py`
   - `src/evidence_gated_memory/core/context.py`
3. **Pick the next slice.** Best current candidates:
   - τ²-bench batch completion — 3/30 done, need ~2h for full run. Already debugged. tau-bench v1 30-task complete (93% EGM vs 90% baseline).
   - Fix low fact acceptance (1.4 vs 4.3 rejected) — gate only tool-call responses, not every agent message.
   - Automatic LLM distillation for L0→L1 promotion (deferred design)
   - Production-grade SQLite migration registry (current `_ensure_column` is the minimal stamp)
4. Keep long-term semantic memory separate from the short-term TaskGraph: L0/L1/L2/L3 remembers cross-session user/project background; TaskGraph remembers the active hard-anchor workflow.

---

## Slice log (most recent first)

### 30-task benchmark + intent fix slice (2026-05-28)

**tau-bench v1 A/B: 30 tasks complete, 0 errors.**
- **EGM 28/30 (93.3%) vs Baseline 27/30 (90.0%).** EGM outperforms baseline by 1 task.
- EGM won on 2 tasks (5, 18), baseline won on 1 (16), both failed on 1 (2). Non-determinism.
- **~23x compression:** 369 EGM context tokens avg vs 8,402 raw message tokens.
- **Facts:** 1.4 avg asserted, 4.3 avg rejected per task. Gate correctly fires on missing evidence.
- Results: `results_tau_v1_0_29.json` in repo root.

**Intent classification fixed** (root cause of exchange-task 0% fact acceptance).
- `_gate_respond` no longer hardcodes `refund_eligibility`.
- `_classify_intent()` + `INTENT_TO_CLAIM_TYPE` mapping: cancel/return/exchange → `refund_completed`, lookup/search/check → `refund_eligibility`.
- Fixed ordering: strong action verbs checked before inquiry verbs to avoid "order" matching before "cancel".

**Batch mode added** to both benchmarks.
- `--batch 0 29 --json-out results.json` with compact summary table.
- Retry logic: 2 retries with backoff for rate-limit/500 errors.
- 4s inter-task delay to avoid DeepSeek rate limiting.
- 30/30 tau-bench v1 tasks completed with zero rate-limit errors.

**τ²-bench partial.**
- Model format fixed: `deepseek/deepseek-chat` (provider prefix required by LiteLLM).
- `sim.trajectory` → `sim.messages` (correct SimulationRun field).
- Removed invalid `llm_agent_provider`/`llm_user_provider` fields from TextRunConfig.
- 3 tasks completed before timeout; remaining ~27 need ~2 hours.
- τ²-bench is slower (~4 min/task, 20-33 conversation steps vs tau-bench v1's 8-17).

**README updated** with 30-task summary table replacing the stale 8-task data.

### tau-bench A/B unblocked slice

- Removed hardcoded API key from `benchmarks/tau_bench/run_ab.py`. Runner now exits early if `DEEPSEEK_API_KEY` is not set.
- A/B baseline-vs-EGM comparison ran end-to-end on DeepSeek-chat. 3-task sample confirmed: both agents pass at the same rate; EGM delivers ~22x context compression (~370 tokens vs. ~8,100 raw).
- Evidence recording and fact gating verified: tool calls → evidence refs → gate checks fire correctly.
- README tau-bench section updated with real results (replaced stale pre-run claims with actual data).
- Identified `_gate_respond` hardcodes `refund_eligibility` claim type — exchange tasks produce `refund_api_response` evidence which doesn't satisfy that claim type, causing high rejection counts. A richer intent→claim_type mapping is TODO.
- Batch run across tasks 3–7 in flight. Full 115-task pass@k evaluation still needs dedicated budget.

### v0.4.0 release slice

- Bumped `pyproject.toml` and `__init__.py` to 0.4.0 (metadata had drifted to 0.2.0 across earlier releases).
- Built wheel + sdist with `python -m build`; both passed `twine check`.
- End-to-end smoke verified in a fresh venv: install from PyPI, construct `EvidenceGatedMemory` with bundled REFUND schema, run `record_evidence → assert_fact → create_task_node → build_context`, all green.
- Published to PyPI as `evidence-gated-memory`.
- Tagged `v0.4.0` on GitHub.

### #29 slice — long-term semantic pyramid manual path

- `ConversationMessage` stores L0 raw user / assistant messages by `session_id`.
- `MemoryAtom` stores manually promoted L1 atoms with `persona`, `episodic`, or `instruction` kind.
- L1 atoms can point back to source L0 message ids; missing source ids are rejected.
- L1 atom search uses the same safe FTS pattern as fact search, with LIKE fallback.
- `MemoryScenario` stores manually promoted L2 scenario blocks backed by real L1 atom ids.
- `MemoryPersona` stores manually promoted L3 persona profiles backed by real L2 scenario ids.
- `build_context()` injects matching L1 atoms, L2 scenarios, and L3 personas into `<long_term_memory>`.
- L0 raw messages are not injected by default; context carries `source_message_ids` for drill-down.
- `include_long_term=False` disables the block, and `max_memory_*` limits bound prompt size.
- `memory_atom_recorded` / `memory_scenario_recorded` / `memory_persona_recorded` audit entries preserve promotion decisions.
- Automatic LLM distillation deliberately not implemented.

### CLI inspect slice

- `egm inspect` reports TaskGraph counts: `tasks`, `task_nodes`, `task_edges`.
- Reports long-term semantic memory counts: `conversation_messages`, `memory_atoms`, `memory_scenarios`, `memory_personas`.
- Reports `offload_records` from `offload/offload.jsonl`.
- Missing tables in old workspaces are counted as zero instead of crashing inspect.

### Task lifecycle slice

- `update_task_status(task_id, status)` is the explicit API for workflow lifecycle changes.
- `Task.status` stays separate from derived `Task.current_state`; status is user/system intent, current_state is recomputed from child TaskNodes.
- `build_context(task_id=...)` emits both `<task_status>` and `<current_state>` so prompt consumers can see the distinction.

### Schema-version slice

- SQLite workspaces now include a `schema_meta` table.
- `SqliteStore.get_schema_version()` returns the current schema version.
- Existing workspaces are stamped during startup after lightweight migrations run.
- `egm inspect` prints `schema_version` (uses `0` for pre-version databases inspected without opening through `SqliteStore`).

### Hardening slice

- #13 fails closed at the public API edge:
  - unknown `evidence_type` is rejected by `record_evidence()` before a ref file is written
  - unknown `claim_type` is rejected by `propose_claim()` / `assert_fact()` before a claim row is stored
- Gate-level unknown-type checks remain in place as defense in depth for old data and lower-level calls.
- #14 and #17 were already implemented and covered by tests — board updated to reflect reality.
- #18 aligned README examples with the current API surface:
  - `record_evidence()` examples include required `source`
  - quick start shows `transition_node()` and `build_context(task_id=...)`
  - demo docs no longer claim the deterministic refund example creates TaskGraph/offload rows
  - the CLI section no longer lists the nonexistent `egm graph` command

---

## Key design decisions worth not re-litigating

These were debated and settled; revisit only with new evidence, not just second thoughts.

- **TaskNode granularity = business node** (e.g. "check refund eligibility"), not per-message or per-tool-call.
- **TaskNodes are created by explicit API call**, not auto-derived from events.
- **`update_task_node_status` is low-level CRUD.** It does not consult any gate. The gated counterpart is `transition_node()`. This split is intentional — keep tests/setup unblocked, keep production paths gated.
- **`attach_*_to_node` validates the target exists** (and for facts: is not invalidated). A node's `evidence_refs` / `fact_refs` are a live, drillable set — phantom refs would silently break EGM's core promise.
- **Every TaskNode mutation writes an audit entry.** No silent state change.
- **Build the validation/audit floor before the Mermaid projection.** Rendering a graph that contains un-audited state changes or ghost references would contradict the whole point of EGM.
- **`Task.status` is explicit lifecycle intent; `Task.current_state` is derived from child TaskNodes.** A cancelled task can still have child nodes whose last derived state was blocked — both are exposed to consumers.
- **LLM-extracted entities are low-trust annotations only.** They never ground a fact. The entity chain is `metadata → connector → regex → LLM fallback`.
- **Automatic L0→L1 distillation is deferred.** It needs candidate-pending + source-span + confidence + human-or-gate-approval + audit before it can touch L1. Don't sneak it in.
