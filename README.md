<p align="center">
  <img src="assets/egm-banner.svg" alt="EGM - Evidence-Gated Graph Memory" width="100%">
</p>

# Evidence-Gated Memory (EGM)

> **Graph-structured, evidence-gated memory for hard-anchor enterprise agents.**
>
> EGM folds long task histories into Mermaid task graphs, preserves raw evidence in `refs/`, and gates both fact writes and task-state transitions with schema-defined evidence rules.

Evidence-Gated Graph Memory turns a linear agent history into a layered, recoverable task memory.

It combines three ideas:

1. **Symbolic short-term memory** — heavy tool outputs are offloaded into `refs/*.md`, indexed by `node_id` / `result_ref`, and folded into a Mermaid task graph.
2. **Layered long-term memory** — the current foundation records L0 raw messages, manually promoted L1 atoms, L2 scenarios, and L3 persona profiles; `build_context()` injects L1-L3 with drill-down ids.
3. **Evidence-gated quality control** — business facts and task-state transitions must pass schema-defined gates for required evidence, trusted sources, freshness, and auditability.

**The goal is not to remember more text. The goal is to keep a compact task map while preserving a path back to the original evidence.**

---

## Why EGM

A long agent run produces a linear, ever-growing history. Three things go wrong with it:

- **Plain summaries lose evidence.** Once a tool result is summarized, you can't drill back down to the API response that justified a conclusion.
- **Plain memory lacks process structure.** Vector recall finds related text, but it can't tell you which task node is blocked, or why.
- **Enterprise agents need discipline, not just recall.** In refund, finance, compliance, medical, and coding agents, the cost of a wrong "done" is far higher than the cost of being slow. A conclusion must be backed by fresh, trusted, traceable evidence — or it must not become a fact at all.

EGM is built for **hard-anchor** workflows — those organized around stable business IDs like `order_id`, `ticket_id`, `refund_id`, `task_id` — not open-ended relationship-heavy dialogue. This is a deliberate trade: EGM gives up open persona-style long-term recall to gain provenance, freshness, and state discipline on enterprise processes.

---

## Architecture

> **TencentDB Agent Memory solves "how context becomes foldable, drillable, recoverable."**
> **EGM adds "evidence gating, evidence freshness, state-transition quality gates, and a hard-anchor enterprise task graph" on top of it.**

EGM does not discard the graph structure of TencentDB Agent Memory. It layers an enterprise-grade quality discipline on top of its short-term Mermaid task graph / `refs` / L0–L3 long-term memory.

For the stabilized M1 architecture, see [docs/architecture.md](docs/architecture.md).

```mermaid
flowchart TD
    subgraph INPUT["Agent 运行输入"]
        A["Agent 对话<br/>用户请求 / Agent 回复"]
        T["工具调用与业务系统返回<br/>API 响应 / 搜索结果 / 测试日志 / 文件内容"]
    end

    subgraph SHORT["短期图记忆：当前任务的可折叠上下文"]
        R["refs/*.md 原始证据层<br/>完整工具结果 / API 返回 / 日志 / 文件片段"]
        O["offload JSONL 摘要索引层<br/>tool_call_id / node_id / result_ref / summary / score"]
        G["TaskGraph 任务图<br/>任务节点 / 边 / 状态 / 依赖 / hard anchor"]
        M["Mermaid 任务画布<br/>current_task_context<br/>给 Agent 的高层任务地图"]
    end

    subgraph LONG["长期语义记忆：跨会话背景"]
        L0["L0 Conversation<br/>原始 user / assistant 对话"]
        L1["L1 Atom<br/>persona / episodic / instruction 原子记忆"]
        L2["L2 Scenario<br/>场景块 / 项目档案 / 历史决策"]
        L3["L3 Persona<br/>用户画像 / 长期偏好 / 稳定背景"]
    end

    subgraph EGM["EGM 证据门控层：让图结构和事实可信"]
        S["Domain Schema<br/>业务规则：实体 / 证据类型 / TTL / 状态机 / gate 规则"]
        E["Entity Anchor Index<br/>metadata → connector → regex → LLM fallback<br/>order_id / ticket_id / refund_id / task_id"]
        F["Fact Layer<br/>L1a observed facts<br/>L1b derived facts"]
        Q["Quality Gates<br/>证据要求 / source allowlist / freshness / 状态转移门控"]
        X["Actionable Rejection<br/>缺什么证据 / 为什么拒绝 / 下一步该调什么工具"]
        AU["Audit & Replay<br/>证据链 / 拒绝记录 / 状态变更 / 可恢复历史"]
    end

    subgraph PROMPT["Prompt 组装：少 token，但可下钻"]
        C["Context Builder<br/>选择当前最相关的图、事实、记忆和证据指针"]
        P["Agent Prompt<br/>L3 Persona + L2 Scene Navigation + L1 Relevant Memories<br/>+ Mermaid TaskGraph + Gated Facts + refs 指针"]
    end

    A --> L0
    A --> G

    T --> R
    T --> O
    R --> O
    O --> G
    G --> M

    L0 --> L1
    L1 --> L2
    L2 --> L3

    A --> E
    T --> E
    R --> E
    O --> E
    E --> G
    E --> F

    S --> E
    S --> Q

    R --> Q
    F --> Q
    G --> Q

    Q -->|"通过：事实可写入"| F
    Q -->|"通过：任务状态可流转"| G
    Q -->|"拒绝：证据不足 / 过期 / 来源不可信"| X
    X --> AU
    Q --> AU
    F --> AU
    G --> AU

    L3 --> C
    L2 --> C
    L1 --> C
    M --> C
    G --> C
    F --> C
    R -. "需要查证时按 node_id / result_ref 下钻" .-> C

    C --> P
    P --> A
```

### The three layers

**1. Short-term graph memory — foldable context for the current task**

Tool results are never dumped wholesale into the prompt. Instead:

```
refs 原文  →  offload JSONL 摘要索引  →  Mermaid 任务图
```

- `refs/*.md` is the **raw evidence layer**, not a summary. It holds complete tool calls, API responses, test logs, and file fragments.
- `offload JSONL` is the **mid-level index**. Each record carries `node_id`, `result_ref`, `tool_call_id`, `summary`, `score`, `timestamp`. Here `score` means "how well the summary can replace the original" — not fact confidence.
- `TaskGraph` is the **core short-term memory**. It is a structured object, not just Mermaid text:

  ```
  task_id / node_id / node_type / status / anchors
  refs / facts / dependencies / blocked_reason / suggested_action
  ```

  Mermaid is one readable projection of the TaskGraph. The agent attends to the high-level map and drills down to lower layers via `node_id` / `result_ref` only when needed.

**2. Long-term semantic memory — cross-session background**

User dialogue should not become flat embedding search. The target design is a semantic pyramid:

```
L0 Conversation  →  L1 Atom  →  L2 Scenario  →  L3 Persona
```

This answers "who is the user, what is the project background, what were the historical decisions." The current implementation has the full manual L0/L1/L2/L3 foundation: raw conversation messages, manually promoted persona / episodic / instruction atoms, scenario blocks that group related atoms, and persona profiles grounded in scenarios. `build_context()` injects L1-L3 summaries with source ids; L0 raw messages stay out of the prompt by default. Automatic LLM distillation is intentionally left out until it has a separate design.

**3. Evidence-gated quality layer — what makes the graph and facts trustworthy**

This is EGM's key enhancement over plain graph memory. TencentDB Agent Memory emphasizes traceability; EGM adds the discipline that **no conclusion becomes a fact without evidence**:

```
No payment_record        → cannot say the order is refundable.
No refund_api_response   → cannot say the refund is completed.
Expired refund_api_response → cannot keep using stale evidence.
source_system not allowlisted → cannot support a high-stakes fact.
A derived fact whose observed parent has expired → must also expire.
```

- **Domain Schema** is the business rulebook (entities, evidence types, trusted sources, TTLs, required evidence per claim, gates per state transition). This is where gate rules come from — they are configured per domain in YAML, not hardcoded.
- **Entity Anchor Index** resolves hard anchors via a chain: `metadata → connector → regex → LLM fallback`. LLM-extracted entities carry a source span and confidence and are stored as **low-trust annotations only** — they are never an acceptable source for fact grounding.
- **Quality Gates** enforce required evidence, source allowlists, freshness, and state-transition rules.
- **Actionable Rejection** never just returns `False`. It returns: what evidence is missing, why it was rejected, which tool to call, which source to query, and the `audit_id` of the rejection.
- **Audit & Replay** keeps the full evidence chain, rejection records, and state changes — so history is recoverable after a context wipe.

---

## Quick start

Install in editable mode while developing locally:

```bash
pip install -e ".[dev]"
```

```python
from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND

memory = EvidenceGatedMemory(workspace=".egm", domain_schema=REFUND)
try:
    memory.record_event(role="user", content="Process refund for ORD-123")

    node = memory.create_task_node(
        task_id="refund:ORD-123",
        node_type="eligibility_check",
        title="Check refund eligibility for ORD-123",
        anchors={"order_id": "ORD-123"},
    )

    order_ref = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"order_id":"ORD-123","status":"PAID"}',
        metadata={"order_id": "ORD-123"},
    )

    # The state gate rejects DONE because refund_policy is still missing.
    blocked = memory.transition_node(node.id, TaskNodeStatus.DONE, evidence=[order_ref])
    print(blocked.accepted)          # False
    print(blocked.rejection_reason)  # missing refund_policy

    policy_ref = memory.record_evidence(
        evidence_type="refund_policy",
        source="policy_db",
        source_system="policy_db",
        content="Full refund within 14 days of purchase.",
    )

    result = memory.assert_fact(
        "Order ORD-123 is eligible for refund under the 14-day policy",
        claim_type="refund_eligibility",
        evidence=[order_ref, policy_ref],
        metadata={"order_id": "ORD-123"},
    )
    if result.accepted and result.fact:
        memory.attach_fact_to_node(node.id, result.fact.id)
        memory.transition_node(node.id, TaskNodeStatus.DONE, evidence=[order_ref, policy_ref])

    print(memory.build_context(query="ORD-123", task_id="refund:ORD-123"))
finally:
    memory.close()
```

With an open `EvidenceGatedMemory` instance, long-term semantic memory is manual and auditable today:

```python
msg = memory.record_conversation_message(
    "user",
    "For refund agents, never claim completion without refund_api_response.",
)
atom = memory.record_memory_atom(
    "instruction",
    "Refund completion requires refund_api_response evidence.",
    source_messages=[msg],
)
scene = memory.record_memory_scenario(
    "Refund completion rules",
    "Completion claims need fresh refund API evidence.",
    atoms=[atom],
)
profile = memory.record_memory_persona(
    "Refund-agent operator",
    "Prefers evidence-gated completion and explicit audit trails.",
    scenarios=[scene],
)
```

---

## Refund demo — evidence-gated fact loop

`examples/refund_agent/run.py` walks the deterministic fact-gating loop:

```
用户要求退款 ORD-123
        ▼
assert refund_eligibility
        │  gate: 没有 evidence_refs
        ▼
[REJECTED] missing order_record + refund_policy
        ▼
工具返回 order_record + refund_policy → 写入 refs/*.md
        ▼
重新 assert refund_eligibility → 通过 → 写入 Fact Layer
        ▼
assert refund_completed
        │  gate: 缺 refund_api_response
        ▼
[REJECTED] refund_completed requires fresh refund_api_response
        ▼
补 refund_api_response 证据 → 重新 assert → 通过
        ▼
build_context()
        ▼
输出 = gated facts + refs 指针（带 fresh/stale/expired 标注）
        ▼
revoke_evidence(order_ref) → derived facts cascade-invalidate
```

Run it without any API key:

```bash
python examples/refund_agent/run.py
```

An optional DeepSeek-backed variant drafts the claims with a real LLM (EGM still decides acceptance):

```bash
python examples/deepseek_refund_agent/run.py --mock          # no key needed
DEEPSEEK_API_KEY=... python examples/deepseek_refund_agent/run.py
```

---

## What context looks like

`build_context()` returns a compact, provenance-labeled prompt. Pass `task_id` when you want the current Mermaid task map included; pass `query` when you want fact and long-term-memory recall narrowed by text/anchor.

````
# Evidence-Gated Memory Context
_query: ORD-123_
_task_id: refund:ORD-123_

<long_term_memory>
## L3 Personas
[PERSONA] Refund-agent operator
  id: persona_123
  summary: Prefers evidence-gated completion and explicit audit trails.
  scenario_ids: ['scene_123']

## L2 Scenarios
[SCENARIO] Refund completion rules
  id: scene_123
  summary: Completion claims need fresh refund API evidence.
  atom_ids: ['atom_123']

## L1 Atoms
[ATOM:instruction] Refund completion requires refund_api_response evidence.
  id: atom_123
  source_message_ids: ['msg_123']
</long_term_memory>

<task_map>
task_id: refund:ORD-123
```mermaid
flowchart TD
    node_abcd["Check refund eligibility for ORD-123<br/>type: eligibility_check<br/>status: done"]
```
</task_map>

<task_status>open</task_status>

<current_state>done</current_state>

[FACT] Order ORD-123 is eligible for refund under the 14-day policy
  claim_type: refund_eligibility  kind: observed
  node: node_abcd
  - ref=ref_123 type=order_record source=order_api observed=0.0h ago [fresh] node=node_abcd
  - ref=ref_456 type=refund_policy source=policy_db observed=0.0h ago [fresh] node=node_abcd
````

The agent reads the high-level map and long-term background; when it needs to verify, it drills down by `node_id`, `ref`, `atom_id`, `scenario_id`, `persona_id`, or `source_message_ids`. Gate rejections are returned by `assert_fact()` / `transition_node()` and recorded in the audit log; `build_context()` is the prompt snapshot, not the rejection API.

---

## CLI

```bash
egm schema validate refund
egm inspect .egm --schema refund
egm context .egm --schema refund --query ORD-123
egm context .egm --schema refund --task-id refund:ORD-123
egm audit .egm --limit 20
egm sweep .egm --schema refund            # expire stale evidence, cascade-invalidate
egm ref .egm ref_abc123                   # drill down to raw evidence
```

---

## What it is / is not

**It is:** a Python library (`pip install evidence-gated-memory`) that gives a hard-anchor enterprise agent a graph-structured, evidence-gated memory system. Domain rules are driven by YAML schemas, not hardcoded.

**It is not:** an agent framework, a vector database, or an open-ended chatbot memory. You orchestrate your agent with whatever you like (LangGraph, a hand-written loop); EGM manages its memory, evidence, and task state.

---

## Differentiators

| | Mem0 / Zep / Letta | **EGM** |
|---|---|---|
| Default policy | write-optimistic | **write-pessimistic at fact layer** |
| Evidence required | optional | **mandatory** |
| Task structure | flat / graph-of-facts | **hard-anchor task graph + soft state machine** |
| Ref-level freshness | no | **yes (TTL per evidence type)** |
| Cascading invalidation | no | **yes (derived facts track observed parents)** |
| State-transition gating | no | **yes (e.g. DONE requires verification)** |
| Gate rejection | boolean | **actionable (what's missing + what to do)** |
| Drill-down to raw evidence | usually lost | **yes (refs preserved, indexed by node_id)** |

---

## Benchmarks

EGM now has a deterministic local benchmark suite under `benchmarks/`. These are
not official leaderboard submissions; they are CI-friendly probes that map
public memory-benchmark shapes onto EGM's hard-anchor, evidence-gated surface.

```bash
python benchmarks/run_local.py
python benchmarks/run_local.py --json
python -m pytest tests/test_benchmarks.py -q
```

Current local probes:

- `longmemeval_s_hard_anchor`: hard-anchor recall, evidence source coverage, and unsupported-query abstention.
- `locomo_style_semantic_pyramid`: manual L0/L1/L2/L3 recall with raw L0 exclusion.
- `beam_lite_hard_anchor_pressure`: bounded context and drill-down source coverage under synthetic hard-anchor pressure.
- `false_done_gate_benchmark`: false-completion claims and DONE transitions must be rejected with actionable feedback until fresh evidence is attached.

See [benchmarks/README.md](benchmarks/README.md) for scope and interpretation.

Historical signal from the predecessor `agent_memory_core` over continuous long-horizon sessions:

| Benchmark | Signal | Result |
|---|---|---|
| LongMemEval-S | Evidence Source Coverage | **0.87** (matches keyword FTS, with source-backed evidence constraints) |
| LongMemEval-S | False Fact Rate | **0.00** |
| BEAM-lite (100K tokens / 50 cases) | recall under pressure | stable on synthetic hard-anchor cases |
| LoCoMo10 | answer-term recall | **weak** — known limitation on relationship-heavy open dialogue |

The honest reading: EGM is strongest on **hard-anchor, strong-process, strong-evidence** enterprise workflows. It deliberately trades open-ended persona-style recall for provenance and process discipline. Symbolic short-term memory is **not** suited to weak-anchor, high-entanglement conversational products.

---

## Core principle

```
Raw events are append-only.
Facts are evidence-gated.
Task-state transitions are evidence-gated.
Prompt context is provenance-filtered and drillable.
```

A rejected claim must be actionable. Evidence can expire; facts must follow.

---

## License

MIT

---

## Project status & handoff (updated 2026-05-26, late-night session)

This section is the single source of truth for "where the project is right now."
It is meant to be read cold — by a future-me, a collaborator, or a new Claude/Codex session — and be enough to resume work without losing context.

### Where we are

EGM has completed **Milestone M1: restoring the graph-memory pillar** on top of the v0.1 evidence-gating core.

- **v0.1 (shipped):** evidence + claims + facts + freshness + cascading invalidation + audit + CLI. Tests green (49/49).
- **M1 complete:** the flat fact store now has a hard-anchor **task graph** with structured TaskNodes, evidence-gated state transitions, and a Mermaid projection that the agent can read as a task map.
- **M2 complete for the manual path:** L0 Conversation + L1 Atom + L2 Scenario + L3 Persona are implemented as manual, auditable layers, and `build_context()` injects L1-L3. Automatic LLM distillation is not implemented yet.

### Status of every tracked task

Legend: ✅ done · 🟡 in progress · ⬜ pending · 🔒 blocked by another task

#### v0.1 hardening (mostly cleanup of the original evidence-gating core)

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
| 19 | ✅ | Regression tests | current suite green; grows with future work |

#### M1 — short-term graph memory (current focus)

| # | Status | Task | Blocked by |
|---|---|---|---|
| 28 | ✅ | TaskGraph structured object (TaskNode model + SQLite table + CRUD) | — |
| 30 | ✅ | Attach-reference validation + TaskNode audit log | #28 |
| 20 | ✅ | `render_mermaid()` projection over task_nodes | #28 |
| 32 | ✅ | Top-level `Task` model + `TaskEdge` + typed-edge Mermaid rendering | #28 |
| 23 | ✅ | `node_id` back-link from evidence & facts to their task node | #20 |
| 24 | ✅ | `build_context()` emits a `<task_map>` block with gated facts inline | #23 |
| 25 | ✅ | Retrieval picks up a `task_focus` signal (uses the new `node_id` back-link) | #23 |
| 21 | ✅ | Soft state machine: `TaskState` + current-state table | #20 ✅ |
| 22 | ✅ | Promote node state transitions into the gate system | #21 ✅ |
| 31 | ✅ | `transition_node()` — the **gated** business API (current `update_task_node_status` is low-level CRUD only) | #22 ✅ |
| 26 | ✅ | Architecture doc: three pillars + lineage from TencentDB Agent Memory | #31 ✅ |

#### M2 — long-term semantic pyramid (manual path complete)

| # | Status | Task |
|---|---|---|
| 29 | ✅ | L0 conversation → L1 atom → L2 scenario → L3 persona manual pyramid + context injection; automatic distillation intentionally deferred |

#### M3 — offload mid-layer index

| # | Status | Task |
|---|---|---|
| 27 | ✅ | offload JSONL index: `tool_call_id / node_id / result_ref / summary / score` |

### Agreed execution order for the next sessions

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

M1, M2 manual path, M3, and the v0.1 hardening board are now closed for the current scope. Automatic LLM distillation should be treated as a separately designed future task, not a casual extension of #29. The pre-0.4 cleanup list is closed for the current scope.

### How to resume tomorrow

1. **Verify the baseline still works.**
   ```bash
   python -m pytest          # expect 127 passed
   ```
2. **Re-read this section** plus `src/evidence_gated_memory/core/memory.py`, `src/evidence_gated_memory/core/mermaid.py`, `src/evidence_gated_memory/core/context.py`.
3. **Pick the next release task.** Best candidates: packaging smoke, README/API polish pass, or cut a 0.4 tag.
4. Keep long-term semantic memory separate from the short-term TaskGraph: L0/L1/L2/L3 remembers cross-session user/project background; TaskGraph remembers the active hard-anchor workflow.

### Latest #29 slice

This slice intentionally completes the manual long-term semantic pyramid path:

- `ConversationMessage` stores L0 raw user / assistant messages by `session_id`.
- `MemoryAtom` stores manually promoted L1 atoms with `persona`, `episodic`, or `instruction` kind.
- L1 atoms can point back to source L0 message ids; missing source ids are rejected.
- L1 atom search uses the same safe FTS pattern as fact search, with LIKE fallback.
- `MemoryScenario` stores manually promoted L2 scenario blocks backed by real L1 atom ids.
- L2 scenario search uses safe FTS with LIKE fallback.
- `MemoryPersona` stores manually promoted L3 persona profiles backed by real L2 scenario ids.
- L3 persona search uses safe FTS with LIKE fallback.
- `build_context()` injects matching L1 atoms, L2 scenarios, and L3 personas into `<long_term_memory>`.
- L0 raw messages are not injected by default; context carries `source_message_ids` for drill-down.
- `include_long_term=False` disables the block, and `max_memory_*` limits bound prompt size.
- `memory_atom_recorded` audit entries preserve promotion decisions.
- `memory_scenario_recorded` audit entries preserve scenario promotion decisions.
- `memory_persona_recorded` audit entries preserve persona promotion decisions.
- Automatic LLM distillation is not implemented yet.
- Suite total after this slice: **123 passed**.

### Latest CLI inspect slice

- `egm inspect` now reports TaskGraph counts: `tasks`, `task_nodes`, and `task_edges`.
- It reports long-term semantic memory counts: `conversation_messages`, `memory_atoms`, `memory_scenarios`, and `memory_personas`.
- It reports `offload_records` from `offload/offload.jsonl`.
- Missing tables in old workspaces are counted as zero instead of crashing inspect.
- Suite total after this slice: **124 passed**.

### Latest Task lifecycle slice

- `update_task_status(task_id, status)` is the explicit API for workflow lifecycle changes.
- `Task.status` stays separate from derived `Task.current_state`; status is user/system intent, current_state is recomputed from child TaskNodes.
- `build_context(task_id=...)` now emits both `<task_status>` and `<current_state>` so prompt consumers can see the distinction.
- Suite total after this slice: **127 passed**.

### Latest schema-version slice

- SQLite workspaces now include a `schema_meta` table.
- `SqliteStore.get_schema_version()` returns the current schema version.
- Existing workspaces are stamped during startup after lightweight migrations run.
- `egm inspect` prints `schema_version`, using `0` for pre-version databases that are inspected without opening through `SqliteStore`.
- Suite total after this slice: **127 passed**.

### Latest hardening slice

- #13 now fails closed at the public API edge:
  - unknown `evidence_type` is rejected by `record_evidence()` before a ref file is written
  - unknown `claim_type` is rejected by `propose_claim()` / `assert_fact()` before a claim row is stored
- Gate-level unknown-type checks remain in place as defense in depth for old data and lower-level calls.
- The status board also marks #14 and #17 done because both are already implemented and covered by tests.
- #18 aligns README examples with the current API surface:
  - `record_evidence()` examples include required `source`
  - quick start shows `transition_node()` and `build_context(task_id=...)`
  - demo docs no longer claim the deterministic refund example creates TaskGraph/offload rows
  - the CLI section no longer lists the nonexistent `egm graph` command

### Key design decisions worth not re-litigating

These were debated and settled; revisit only with new evidence, not just second thoughts.

- **TaskNode granularity = business node** (e.g. "check refund eligibility"), not per-message or per-tool-call.
- **TaskNodes are created by explicit API call**, not auto-derived from events.
- **`update_task_node_status` is low-level CRUD.** It does not consult any gate. The gated counterpart is `transition_node()` (#31). This split is intentional — keep tests/setup unblocked, keep production paths gated.
- **`attach_*_to_node` validates the target exists** (and for facts: is not invalidated). A node's `evidence_refs` / `fact_refs` are a live, drillable set — phantom refs would silently break EGM's core promise.
- **Every TaskNode mutation writes an audit entry.** No silent state change.
- **Build the validation/audit floor before the Mermaid projection.** Rendering a graph that contains un-audited state changes or ghost references would contradict the whole point of EGM.
