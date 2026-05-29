# Benchmark Decision Protocol

EGM benchmarks must prove the right thing. The project is an evidence-gated
graph-memory kernel for hard-anchor enterprise agents, not a general chatbot
memory benchmark entry. Public reporting must therefore separate core EGM
correctness from downstream agent performance.

## Benchmark Classes

| Class | What it answers | Default status | Public wording |
|---|---|---|---|
| EGM-native deterministic probes | Does the EGM kernel preserve its gates, provenance, freshness, cascade, task state, and bounded context invariants? | Required for CI and releases. | "Deterministic EGM correctness probes." |
| Official-data retrieval proxies | Can EGM retrieve answer-bearing evidence from published memory datasets with its current retrieval surface? | Optional diagnostic. | "Retrieval-only proxy over official data, not a leaderboard submission." |
| Downstream agent A/B | Does adding EGM to an agent loop improve task success, evidence discipline, or context budget on tau/tau2-style workflows? | Optional and budget-dependent. | "Agent A/B with sample size, model route, and limitations." |
| RAGAS-style grounding metrics | Is assembled context precise, source-backed, and bounded? | Useful supporting metric. | "RAGAS-style local grounding metrics unless the official RAGAS package and protocol are used." |

## Release Gates

### Required For v0.5

- Local deterministic benchmark suite passes.
- Adversarial probes pass.
- Scenario probes pass.
- tau-bench adapter smoke test passes without an API key.
- A benchmark snapshot can be generated from a fresh checkout.
- README and reports include sample size, metric definitions, and limitations.
- No result is described as an official leaderboard score unless the official
  harness and judge were run end-to-end.

### Not Required For v0.5

- Full tau-bench pass@k.
- Full tau2-bench pass@k.
- Full MemoryAgentBench generative evaluation.
- Paid LLM runs in CI.

Those are useful downstream evidence, but they should not block the credible
alpha release if the EGM-native behavior is already verified.

## Reporting Rules

Every public benchmark table must include:

1. Benchmark or probe name.
2. Dataset or synthetic case count.
3. Metric definition.
4. Model and provider when an LLM is used.
5. Whether the run is deterministic.
6. Date of run.
7. Main limitation.
8. Raw result file path when available.

Never report:

- "EGM beats tau-bench" from a smoke run.
- "Official LongMemEval / LoCoMo / MemoryAgentBench score" from retrieval-only
  proxies.
- A pass rate without task count.
- A model comparison without model name and route.
- A benchmark claim that cannot be regenerated from a command or documented
  external setup.

## Current Public Story

The current strong claims are EGM-native:

- unsupported completion claims are rejected;
- DONE transitions can be gated on fresh evidence;
- expired or disallowed evidence fails closed;
- derived facts cascade when upstream evidence is revoked;
- context remains bounded and drill-downable;
- audit records explain gate decisions.

The current external benchmark story is deliberately narrower:

- tau-bench and tau2-bench are the right downstream agent benchmark directions,
  but public pass-rate claims require stable A/B runs with sample size and
  budget disclosed.
- MemoryAgentBench results in this repository are retrieval-only proxies over
  official data, not full generative leaderboard scores.
- LongMemEval-S and LoCoMo runners are useful boundary diagnostics for
  retrieval, not the primary proof of EGM's enterprise workflow value.

## Decision Matrix

| Situation | Allowed action |
|---|---|
| Deterministic local benchmark passes | Can be listed as a release correctness guard. |
| Official-data retrieval proxy passes | Can be listed as retrieval-only diagnostic with dataset size. |
| tau/tau2 harness fails before scoring | Must be reported as blocked/no valid score. |
| tau/tau2 small batch completes | Can report as small-sample A/B, not pass@k proof. |
| Full official harness + judge completes | Can report official-style result, with exact protocol and raw artifacts. |
| Result cannot be reproduced | Do not put it in README headline tables. |
