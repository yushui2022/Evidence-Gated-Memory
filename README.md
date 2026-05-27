<p align="center">
  <img src="assets/egm-banner.svg" alt="Evidence-Gated Memory" width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/evidence-gated-memory/"><img alt="PyPI" src="https://img.shields.io/pypi/v/evidence-gated-memory?color=0B1220&label=pypi"></a>
  <a href="https://pypi.org/project/evidence-gated-memory/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/evidence-gated-memory?color=0B1220"></a>
  <a href="#license"><img alt="License" src="https://img.shields.io/badge/license-MIT-0B1220"></a>
  <a href="#benchmarks"><img alt="Tests" src="https://img.shields.io/badge/tests-135%20passing-0F9F6E"></a>
  <a href="#benchmarks"><img alt="Status" src="https://img.shields.io/badge/status-alpha-E7B549"></a>
</p>

<p align="center">
  <b>Provenance-first graph memory for hard-anchor enterprise agents.</b><br>
  <sub>Every fact must pass a gate. Every state transition must pass a gate. Every conclusion drills down to raw evidence.</sub>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#architecture-at-a-glance">Architecture map</a> ·
  <a href="#why-egm">Why EGM</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="#how-it-compares">Comparison</a> ·
  <a href="docs/architecture.md">Architecture doc</a>
</p>

---

## TL;DR

**The goal is not to remember more text. The goal is to keep a compact task map while preserving a path back to the original evidence.**

---

## Architecture at a glance

```mermaid
flowchart TD
    subgraph INPUT["Agent runtime input"]
        A["Agent dialogue<br/>user requests / agent replies"]
        T["Tool calls and business systems<br/>API responses / search results / test logs / file content"]
    end

    subgraph SHORT["Short-term graph memory: foldable context for the current task"]
        R["refs/*.md raw evidence layer<br/>full tool results / API returns / logs / file fragments"]
        O["offload JSONL summary index<br/>tool_call_id / node_id / result_ref / summary / score"]
        G["TaskGraph<br/>task nodes / edges / status / dependencies / hard anchors"]
        M["Mermaid task canvas<br/>current_task_context<br/>high-level task map for the agent"]
    end

    subgraph LONG["Long-term semantic memory: cross-session background"]
        L0["L0 Conversation<br/>raw user / assistant dialogue"]
        L1["L1 Atom<br/>persona / episodic / instruction atoms"]
        L2["L2 Scenario<br/>scenario blocks / project files / historical decisions"]
        L3["L3 Persona<br/>user profile / long-term preferences / stable background"]
    end

    subgraph EGM["EGM evidence-gating layer: making graph state and facts trustworthy"]
        S["Domain Schema<br/>business rules: entities / evidence types / TTLs / state machine / gate rules"]
        E["Entity Anchor Index<br/>metadata → connector → regex → LLM fallback<br/>order_id / ticket_id / refund_id / task_id"]
        F["Fact Layer<br/>L1a observed facts<br/>L1b derived facts"]
        Q["Quality Gates<br/>evidence requirements / source allowlists / freshness / state-transition gates"]
        X["Actionable Rejection<br/>missing evidence / rejection reason / next tool to call"]
        AU["Audit & Replay<br/>evidence chains / rejection records / state changes / recoverable history"]
    end

    subgraph PROMPT["Prompt assembly: compact tokens, drillable evidence"]
        C["Context Builder<br/>selects the most relevant graph, facts, memory, and evidence pointers"]
        P["Agent Prompt<br/>L3 Persona + L2 Scene Navigation + L1 Relevant Memories<br/>+ Mermaid TaskGraph + Gated Facts + refs pointers"]
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

    Q -->|"pass: fact writable"| F
    Q -->|"pass: task state can transition"| G
    Q -->|"reject: missing, expired, or untrusted evidence"| X
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
    R -. "drill down by node_id / result_ref when verification is needed" .-> C

    C --> P
    P --> A
```

### Architecture posture and fit

EGM is designed for **hard-anchor enterprise agents**: tasks are not organized around open-ended conversation, but around stable business IDs and auditable workflows such as `order_id`, `ticket_id`, `refund_id`, `case_id`, and `task_id`. The core risk in these agents is not failing to recall a past sentence; it is turning missing, stale, or untrusted evidence into a completed conclusion.

Architecturally, EGM separates the active task into three concerns: the short-term `TaskGraph` keeps the workflow map, `refs/*.md` preserves drillable raw evidence, and the `Fact Layer` only accepts claims that pass schema-defined gates. Long-term memory remains an auditable L0/L1/L2/L3 pyramid: curated high-level memories enter the prompt by default, while raw L0 dialogue remains available for trace-back when needed.

In practice, EGM fits customer-support refunds, ticket handling, compliance review, finance approval, code repair, and test-verification workflows: domains with **strong process, strong evidence, and strong state constraints**. It is not trying to be a general chatbot memory or persona-memory system; it is built to make the agent obtain fresh, trusted, replayable evidence before saying "refund approved", "task complete", "tests passed", or "case closed".

---

## Quick start

```bash
pip install evidence-gated-memory
```

```python
from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus
from evidence_gated_memory.schemas.builtin import REFUND

memory = EvidenceGatedMemory(workspace=".egm", domain_schema=REFUND)

# 1. Record raw evidence — content is written to refs/<id>.md, indexed in SQLite.
order = memory.record_evidence(
    evidence_type="order_record",
    source="order_api", source_system="order_api",
    content='{"order_id":"ORD-123","status":"PAID"}',
)
policy = memory.record_evidence(
    evidence_type="refund_policy",
    source="policy_db", source_system="policy_db",
    content="Full refund within 14 days of purchase.",
)

# 2. Assert a fact — it goes through the gate before it can be written.
result = memory.assert_fact(
    "ORD-123 is eligible for refund under the 14-day policy",
    claim_type="refund_eligibility",
    evidence=[order, policy],
)

if not result.accepted:
    print(result.gate.rejection_reason)   # what's missing
    print(result.gate.suggested_action)   # what to do next
else:
    print(result.fact.id)                 # gated fact, ready for prompt context

memory.close()
```

That's the loop. **No evidence, no fact.** Stale or untrusted evidence is rejected with an actionable message, not silently accepted.

---

## Why EGM

A long-running agent produces a linear, ever-growing history. Three things go wrong with it:

- **Plain summaries lose evidence.** Once a tool result is summarized, you can't drill back to the API response that justified the conclusion.
- **Plain memory lacks process structure.** Vector recall finds related text, but it can't tell you which task node is blocked, or why.
- **Enterprise agents need discipline, not just recall.** In refund, finance, compliance, medical, and coding agents, the cost of a wrong "done" is far higher than the cost of being slow.

EGM is built for **hard-anchor** workflows — those organized around stable business IDs like `order_id`, `ticket_id`, `refund_id`, `task_id` — not open-ended persona-style dialogue. This is a deliberate trade: EGM gives up open relationship-heavy recall to gain **provenance, freshness, and state discipline** on enterprise processes.

---

## How it compares

|  | Mem0 / Zep / Letta | **EGM** |
|---|---|---|
| Default write policy | write-optimistic | **write-pessimistic at fact layer** |
| Evidence requirement | optional | **mandatory, per-claim-type** |
| Task structure | flat / graph-of-facts | **hard-anchor task graph + soft state machine** |
| Ref-level freshness | no | **fresh / stale / expired per evidence type** |
| Cascading invalidation | no | **derived facts track observed parents** |
| State-transition gating | no | **DONE / blocked / etc. all gated** |
| Rejection behavior | boolean | **actionable: what's missing + what to call** |
| Drill-down to raw evidence | usually lost | **`refs/<id>.md` preserved, indexed by `node_id`** |
| Best-fit domain | open dialogue, personas | **hard-anchor enterprise workflows** |

---

## Architecture

EGM has three pillars. They are independent layers that compose into one prompt at `build_context()` time.

### 1. Short-term graph memory — foldable context for the current task

```
tool result  →  refs/*.md (raw)  →  offload JSONL (summary index)  →  TaskGraph  →  Mermaid projection
```

- `refs/*.md` is the **raw evidence layer**. Full tool calls, API responses, logs, file fragments — never summarized away.
- `offload JSONL` is the **mid-level index**. Each record carries `node_id`, `result_ref`, `tool_call_id`, `summary`, `score`.
- `TaskGraph` is a **structured object** (`Task` / `TaskNode` / `TaskEdge`), not just Mermaid text. Mermaid is one readable projection.
- The agent reads the high-level map and drills down by `node_id` / `result_ref` only when needed.

### 2. Long-term semantic memory — cross-session background

```
L0 Conversation  →  L1 Atom  →  L2 Scenario  →  L3 Persona
```

A manually-promoted, auditable pyramid. Every L1 atom can point back to L0 source messages; every L2 scenario is grounded in real L1 ids; every L3 persona is grounded in real L2 ids. `build_context()` injects L1–L3 summaries with source ids; L0 raw messages stay out of the prompt by default. **Automatic LLM distillation is intentionally deferred** until it has its own design.

### 3. Evidence-gated quality layer — what makes the graph trustworthy

This is EGM's key differentiator. **No conclusion becomes a fact without evidence:**

```
No payment_record           → cannot say the order is refundable.
No refund_api_response      → cannot say the refund is completed.
Expired refund_api_response → cannot keep using stale evidence.
source_system not allowlisted → cannot support a high-stakes fact.
A derived fact whose observed parent expired → must also expire.
```

Components:

- **Domain Schema** (YAML) — entities, evidence types, trusted sources, TTLs, required evidence per claim, gates per state transition. **Business rules are configured, not hardcoded.**
- **Entity Anchor Index** — resolves hard anchors via `metadata → connector → regex → LLM fallback`. LLM-extracted entities are stored as **low-trust annotations only**; never an acceptable source for fact grounding.
- **Quality Gates** — enforce required evidence, source allowlists, freshness, and state-transition rules.
- **Actionable Rejection** — never just `False`. Returns what's missing, why, which tool to call next, and the `audit_id`.
- **Audit & Replay** — full evidence chain, rejection records, state changes. History recoverable after a context wipe.

Minimal schema shape:

```yaml
name: refund

entities:
  - name: order
    patterns: ["ORD-[0-9]+"]
    metadata_fields: ["order_id"]

evidence_types:
  order_record:
    stale_after: PT30M
    expired_after: PT24H
    source_systems: ["order_api"]
  refund_policy:
    stale_after: P7D
    expired_after: P30D
    source_systems: ["policy_db"]
  refund_api_response:
    stale_after: PT2M
    expired_after: PT15M
    source_systems: ["refund_api"]

claim_types:
  refund_eligibility:
    required_evidence: ["order_record", "refund_policy"]
  refund_completed:
    required_evidence: ["refund_api_response"]
    requires_fresh_evidence: true

state_gates:
  - name: refund_completion_done_requires_api_response
    when: { node_type: refund_completion, to_status: done }
    require:
      evidence_types: ["refund_api_response"]
      freshness: fresh
    suggested_action: "call refund_api and attach a fresh refund_api_response before marking refund completion done"
```

Full architecture document: [docs/architecture.md](docs/architecture.md).

---

## What context looks like

`build_context()` returns a single, compact, provenance-labeled prompt. Pass `task_id` for the Mermaid task map; pass `query` to narrow fact and long-term recall.

````
# Evidence-Gated Memory Context
_query: ORD-123_
_task_id: refund:ORD-123_

<long_term_memory>
[PERSONA] Refund-agent operator (id: persona_123)
[SCENARIO] Refund completion rules (id: scene_123)
[ATOM:instruction] Refund completion requires refund_api_response evidence. (id: atom_123)
</long_term_memory>

<task_map>
```mermaid
flowchart TD
    node_abcd["Check refund eligibility for ORD-123<br/>type: eligibility_check<br/>status: done"]
```
</task_map>

<task_status>open</task_status>
<current_state>done</current_state>

[FACT] Order ORD-123 is eligible for refund under the 14-day policy
  claim_type: refund_eligibility  kind: observed
  - ref=ref_123 type=order_record   source=order_api  observed=0.0h ago [fresh]
  - ref=ref_456 type=refund_policy  source=policy_db  observed=0.0h ago [fresh]
````

The agent reads the high-level map; when it needs to verify, it drills down by `node_id`, `ref`, `atom_id`, `scenario_id`, or `persona_id`. Gate rejections are returned by `assert_fact()` / `transition_node()` and recorded in the audit log — `build_context()` is the prompt snapshot, not the rejection API.

---

## Refund demo — full evidence-gated loop

`examples/refund_agent/run.py` runs the deterministic loop end-to-end:

```
User requests refund for ORD-123
        ▼
assert refund_eligibility       → gate: no evidence_refs
        ▼
[REJECTED] missing order_record + refund_policy
        ▼
fetch tools → order_record + refund_policy → refs/*.md
        ▼
re-assert refund_eligibility    → ✅ written to Fact Layer
        ▼
assert refund_completed         → gate: missing fresh refund_api_response
        ▼
[REJECTED] actionable: call refund_api
        ▼
fetch refund_api_response → re-assert → ✅
        ▼
build_context() → gated facts + refs (with fresh/stale/expired labels)
        ▼
revoke_evidence(order_ref) → derived facts cascade-invalidate
```

```bash
python examples/refund_agent/run.py                              # deterministic, no API key
python examples/deepseek_refund_agent/run.py --mock              # LLM-shaped, mocked
DEEPSEEK_API_KEY=... python examples/deepseek_refund_agent/run.py  # real LLM proposes; EGM decides
```

---

## CLI

```bash
egm schema validate refund
egm inspect .egm --schema refund            # TaskGraph + long-term + offload + schema_version
egm context .egm --schema refund --query ORD-123
egm context .egm --schema refund --task-id refund:ORD-123
egm audit .egm --limit 20                   # who wrote what, who got rejected and why
egm sweep .egm --schema refund              # expire stale evidence, cascade-invalidate
egm ref .egm ref_abc123                     # drill down to raw evidence
```

---

## Benchmarks

> We report what we run. We don't report what we haven't.

EGM runs on **two domain schemas** (REFUND + CODING) and reports results across six benchmark categories:

### 1. Adversarial probes — 10 attack vectors, 10 blocks

We actively try to break EGM and measure whether each attack is stopped. These are deterministic, run in CI, and need no API keys.

```bash
python benchmarks/run_local.py              # correctness + adversarial
python benchmarks/run_local.py --json       # machine-readable
python -m pytest tests/test_benchmarks.py -q
```

| Attack attempted | What EGM did |
|---|---|
| Ground a fact on LLM-generated evidence | **Blocked.** `llm_output_not_as_source` gate fired. |
| Assert a fact with expired required evidence | **Blocked.** `expired_evidence_block` gate fired. |
| Use evidence from a non-allowlisted source system | **Blocked.** `source_system_not_allowed` gate fired. |
| Call `commit_fact()` without a `GateResult` | **Blocked.** `ValueError` before any row is written. |
| Transition a node to DONE without required evidence | **Blocked.** Actionable rejection: "call refund_api, attach refund_api_response." |
| Attach a nonexistent evidence id to a node | **Blocked.** `KeyError` immediately. |
| Attach an already-invalidated fact to a node | **Blocked.** `ValueError` immediately. |
| Revoke root evidence — does cascade work? | **Blocked.** Observed fact AND derived child both invalidated. |
| Record evidence with an undeclared `evidence_type` | **Blocked.** `ValueError` before any disk write. |
| Assert a fact with an undeclared `claim_type` | **Blocked.** `ValueError` at the API edge. |

**Result: 10/10 attacks blocked.** These are not "EGM scores 1.00 on its own surface." They are "we tried 10 ways to slip something past the gate; the gate held every time."

### 2. Scenario probes — end-to-end domain workflows

Six scenarios across two domains exercise the full EGM loop. Three for refund, three for coding — same architecture, different schema.

```bash
python benchmarks/scenario_probes.py                # run directly
python benchmarks/run_local.py --scenarios-only     # via runner
```

**Refund domain** (`refund.yaml` — 6 evidence types, 3 claim types, 2 state gates):

| Scenario | What it exercises | Result |
|---|---|---|
| Full refund lifecycle (3 orders) | eligibility → rejection → evidence → acceptance → completion → transition → context → cascade | 9/9 thresholds |
| Multi-order concurrency (20 workflows) | Task isolation, no cross-contamination of facts, context, or anchors | All boundaries hold |
| Partial-evidence rejection loop | try → reject with actionable feedback → fetch → retry → accept | 5 rounds, 3 rejections (100% actionable) |

**Coding domain** (`coding.yaml` — 4 evidence types, 3 claim types, 2 state gates):

| Scenario | What it exercises | Result |
|---|---|---|
| File → diagnosis → done (6 rounds) | file_read → file_content → test_log → error_diagnosis → fresh test_log → task_done | 3 rejections (100% actionable), 3 acceptances |
| Stale evidence gate | `file_content` accepts stale file_read; `task_done` rejects stale test_log (requires fresh) | Same evidence, different outcomes — correctly gated |
| Multi-file concurrency (10 workflows) | 10 files repaired concurrently; verify anchor isolation and context boundary | No cross-contamination |

**Result: 6/6 scenarios pass at every threshold.** EGM's schema system works identically across domains — the gates, freshness rules, and context isolation are schema-driven, not hardcoded for refund.

### 3. Correctness probes — product-surface validation

Four deterministic probes verify the happy-path core promises hold:

| Probe | What it verifies |
|---|---|
| Hard-anchor recall + evidence coverage | Every fact is recallable by its business ID; every evidence ref appears in context |
| L0→L3 semantic pyramid | Promoted atoms/scenarios/personas are recallable; raw L0 stays out of prompt |
| Bounded context under pressure | 24 concurrent workflows, no cross-bleed of facts or task maps |
| False-done gate | A claim without evidence is blocked; with fresh evidence, it's accepted |

A score below 1.00 on any of these **is a regression bug**. They are correctness guards, not competitive metrics.

### 4. Retrieval proxy over MemoryAgentBench (ICLR 2026)

We run EGM's local FTS retrieval against official [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) data as a **retrieval-only proxy**. This is not a leaderboard submission — it measures how well EGM's current retrieval surface maps onto a published benchmark.

| MAB split | Samples | Questions | Coverage@5 | MRR |
|---|---|---|---|---|
| Conflict Resolution | 8 | 800 | **0.67** | **0.47** |
| Accurate Retrieval | 3 | 300 | **0.48** | **0.40** |

Two splits that the retrieval-only proxy does **not** fit:

- **Test-Time Learning** — requires incremental knowledge updates across sessions; retrieval-only is the wrong instrument.
- **Long-Range Understanding** — requires multi-hop summarization; EGM does not generate answers, it retrieves evidence.

The Conflict Resolution result is the most representative: 800 questions over evidence-backed updates and stale-information conflicts — exactly the surface EGM is built for.

```bash
python benchmarks/official/memory_agent_bench.py path/to/Conflict_Resolution.parquet --top-k 5
```

### 5. Agent benchmark integration (tau-bench / τ²-bench)

EGM's tau-bench adapter wraps a tau-bench environment, routing every tool result through EGM's evidence layer and gating agent conclusions before they become facts. The integration code is ready; the A/B scores are blocked on two prerequisites.

**What's done:**

```bash
python benchmarks/tau_bench/run_ab.py --smoke    # deterministic, no API keys
python benchmarks/run_local.py --tau-smoke        # via unified runner
python -m pytest tests/test_benchmarks.py -q      # includes tau smoke test
```

The smoke test simulates a complete tau-bench retail refund task through EGM: tool calls → evidence recording → fact assertion → gate rejection (premature completion blocked) → re-assert with evidence → transition to DONE → context building. **8/8 thresholds pass.**

**EGM adapter capabilities** (`benchmarks/tau_bench/adapter.py`):
- `EGMTauAdapter`: wraps any tau-bench Env, records tool results as EGM evidence
- Tracks evidence coverage, fact acceptance rate, context compression ratio
- `run_single_task_comparison()`: A/B harness — runs the same task with and without EGM

**What's blocked:**

| Prerequisite | Status |
|---|---|
| tau-bench installed + data files | ZIP archives available (`D:/bench_repos/`) |
| LLM API key (DeepSeek / Anthropic) | Not configured |
| Real A/B run across task set | **Blocked** on the two items above |

**When unblocked**, the A/B harness measures:
- **Task pass rate** — does EGM help or hurt task completion?
- **Context compression** — EGM context vs. raw message history (token count)
- **Evidence coverage** — what fraction of tool results are recorded as evidence
- **False-done rate** — how often the agent claims completion without sufficient evidence

The adapter is architected to work with any tau-bench domain (retail, airline, mock) — it maps tool names to EGM evidence types via a configurable dictionary. When real A/B scores exist they will be reported here.

### What this adds up to

EGM is strongest on **hard-anchor, strong-evidence, conflict-dense** enterprise workflows. It deliberately trades open-ended persona recall for provenance and gate discipline:

| Strength | Evidence |
|---|---|
| Evidence-gated retrieval | 10/10 attack vectors blocked; 0 false acceptances across 134 tests |
| Actionable rejection | Every gate rejection names what's missing and what tool to call next |
| Bounded task context | 20 concurrent refund workflows, 10 concurrent coding workflows — zero cross-bleed |
| Cascading invalidation | Revoke root evidence → observed + derived facts both invalidated |
| Multi-domain | Same architecture, two schemas (REFUND + CODING), identical correctness guarantees |
| Freshness discipline | Fresh/stale/expired per evidence type; claim-type-specific thresholds enforced |

**Not yet measured:** end-to-end agent task success with EGM as the memory layer (tau-bench / τ²-bench A/B comparison).

See [benchmarks/README.md](benchmarks/README.md) and [reports/benchmark_report.md](reports/benchmark_report.md).

---

## What it is / is not

**It is.** A Python library (`pip install evidence-gated-memory`) that gives a hard-anchor enterprise agent a graph-structured, evidence-gated memory system. Domain rules are driven by YAML schemas, not hardcoded.

**It is not.** An agent framework, a vector database, or an open-ended chatbot memory. You orchestrate your agent however you like (LangGraph, a hand-written loop, anything else); EGM manages its memory, evidence, and task state.

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

## Citation

If you use EGM in research, please cite:

```bibtex
@software{egm2026,
  title  = {Evidence-Gated Memory: Provenance-First Graph Memory for Hard-Anchor Enterprise Agents},
  author = {yushui2022},
  year   = {2026},
  url    = {https://github.com/yushui2022/Evidence-Gated-Memory}
}
```

---

## License

MIT
