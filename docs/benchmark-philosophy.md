# Benchmark Philosophy

EGM should be benchmarked against the behavior it exists to guarantee:
evidence-backed facts, gated task state, freshness discipline, cascade
invalidation, bounded context, and auditable rejection. It should not be sold as
a general conversational-memory leaderboard entry.

## What EGM Is Good At Measuring

EGM's native surface is process discipline:

- unsupported claim block rate;
- false-done block rate;
- actionable rejection rate;
- acceptance after required evidence appears;
- stale or expired evidence leakage;
- cascade invalidation correctness;
- source-system allowlist enforcement;
- context source coverage;
- audit coverage.

These are not proxy metrics for "nice chat memory." They are correctness guards
for agents that act on hard business anchors such as `order_id`, `ticket_id`,
`case_id`, `file`, `test`, or `refund_id`.

## Benchmark Families

| Family | What it measures | How EGM should use it |
|---|---|---|
| EGM deterministic probes | Gate correctness, state transitions, cascade, bounded context, audit. | Release blocker and CI guard. A failure is a regression bug. |
| tau-bench / tau2-bench | Downstream enterprise-agent task success under tools, policies, and multi-turn users. | A/B evidence for whether adding EGM helps an agent loop. Requires model key, adapter, sample size, and cost disclosure. |
| RAGAS-style metrics | Context precision, grounding, source support, faithfulness. | Supporting evidence for prompt context quality; do not call it official RAGAS unless the official package/protocol is used. |
| MemoryAgentBench | Agent memory retrieval, conflict, test-time learning, long-range understanding. | Useful as retrieval-only proxy today; full score needs generative protocol and task-specific evaluator. |
| LongMemEval-S / LoCoMo | Long-context and conversational memory recall. | Boundary diagnostics. Useful to show where EGM's hard-anchor FTS surface works or fails, not the primary proof of value. |

## Why tau-bench And tau2-bench Matter

tau-bench and tau2-bench are important because they evaluate complete agents,
not isolated memory search. They contain the kinds of things EGM cares about:

- tool calls;
- business policies;
- user goals;
- multi-step state;
- invalid action risk;
- task completion.

But they do not produce "an EGM score" by themselves. EGM is a memory and
gating layer inside an agent. The honest experiment is A/B:

```text
same model + same benchmark + same task split
baseline agent
vs.
agent with EGM recording evidence, gating facts, and building context
```

The result should report both downstream and EGM-native metrics:

- task success / reward;
- invalid actions;
- context token budget;
- evidence recorded;
- unsupported claims blocked;
- stale evidence blocked;
- audit records produced.

## Why MemoryAgentBench Is Currently A Retrieval Proxy

The current runner chunks official MemoryAgentBench context into EGM memory
atoms, retrieves top-k atoms for each question, and checks whether answer strings
appear in retrieved text. That is useful, but narrow.

It does not prove:

- conflict-resolution reasoning;
- generation quality;
- test-time learning;
- long-range synthesis.

Therefore public wording must be:

```text
retrieval-only proxy over official MemoryAgentBench data
```

not:

```text
official MemoryAgentBench score
```

## Why LoCoMo And LongMemEval Are Secondary

LoCoMo and LongMemEval-style tasks are valuable for broad conversational memory,
but EGM is not optimized for open-ended recall. EGM deliberately prefers:

- explicit anchors over vague semantic similarity;
- evidence refs over vector-only snippets;
- deterministic gate rejection over fuzzy memory acceptance;
- auditability over recall breadth.

Poor open-ended recall can indicate a retrieval-model gap, but it does not
invalidate EGM's core evidence-gating claim.

## Public Reporting Rules

Use `docs/benchmark-decision-protocol.md` as the reporting contract. In short:

- report sample size;
- report whether an LLM was used;
- report model/provider;
- report whether data is official, synthetic, or proxy;
- report limitations next to the score;
- never describe smoke tests as pass@k;
- never call retrieval-only proxy scores official leaderboard results.

## Release Interpretation

For v0.5, EGM should be judged primarily by deterministic correctness:

```text
Does it reject unsupported facts?
Does it reject unsupported DONE transitions?
Does it name the missing evidence?
Does it accept after evidence is attached?
Does it keep context bounded and source-backed?
Does it leave audit records?
```

Downstream agent benchmarks become more important in v0.7+, after generic agent
loop integration and adapters exist.
