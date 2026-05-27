# EGM Benchmark Report

Date: 2026-05-27

This report separates two kinds of evaluation:

1. **Industry-recognized benchmarks / metric families** adapted to EGM.
2. **EGM-owned enterprise evidence-gated benchmarks** designed for the project's target use case.

EGM is a hard-anchor, evidence-gated memory layer for enterprise agents. It is
not optimized for open-ended conversational memory. Results below should be read
with that product boundary in mind.

## Industry-Recognized Benchmarks / Metric Families

These are the three external benchmark directions that best fit EGM's target
market. They are listed separately from EGM-owned synthetic benchmarks. tau-bench
and tau2-bench require their own agent/task harness and are not yet run in this
repository. RAGAS-style context grounding is currently measured with EGM's local
hard-anchor contexts.

| Benchmark / metric family | Why it fits EGM | External metric(s) to report | EGM-specific metric(s) to add | Current measurement status |
|---|---|---|---|---|
| tau-bench | Best external fit for enterprise workflow agents: multi-turn user interaction, tools/APIs, domain policies, task completion. | Task success / pass rate, policy violation rate, tool-use correctness. | false done rate, unsupported claim block rate, evidence source coverage, actionable rejection rate, audit coverage. | **Selected, not yet run.** Needs tau-bench adapter comparing baseline agent vs baseline + EGM. |
| tau2-bench / Tau2-Bench | Best fit for dynamic enterprise state: user and environment can change state while the agent acts. | Task success under dynamic state, invalid action rate, policy consistency. | stale fact leakage rate, cascading invalidation correctness, fresh-evidence requirement satisfaction, state-transition gate accuracy. | **Selected, not yet run.** Should follow tau-bench after the simpler adapter is stable. |
| RAGAS / RAG evaluation metrics | Good fit for evaluating EGM's prompt context quality: context must be grounded, precise, and source-backed. | context precision, context recall, faithfulness / answer grounding. | evidence source coverage, ref drill-down coverage, stale fact leakage rate, context budget efficiency. | **Measured as RAGAS-style local metrics:** source coverage = 1.00, context bound = 1.00 over 12 hard-anchor source cases + 24 pressure cases. |

### Current Commands Used

```bash
python benchmarks/run_local.py --json > reports/local_benchmarks_latest.json
```

LongMemEval-S and LoCoMo retrieval-only runners remain available under
`benchmarks/official/`, but they are boundary diagnostics for non-target
open-ended memory and are not part of the primary external benchmark table.

## EGM-Owned Enterprise Evidence-Gated Benchmarks

These are synthetic, deterministic benchmarks owned by the project. They are not
industry leaderboards. They are designed to test the behavior that EGM exists to
provide: hard anchors, evidence source coverage, false-completion resistance,
actionable gate rejection, bounded context, and raw L0 exclusion.

| EGM benchmark | Data measured | Primary metric(s) | Result | Interpretation |
|---|---:|---|---:|---|
| Hard-anchor source coverage | 12 refund-order cases | accepted fact rate, anchor recall, evidence source coverage, unsupported abstention | all = 1.00 | EGM performs well when the task has explicit `order_id` style anchors and required evidence refs. |
| Manual L0/L1/L2/L3 semantic pyramid | 4 promoted long-term memory topics | atom recall, scenario recall, source id coverage, raw L0 exclusion | all = 1.00 | The manual long-term path works as designed: promoted memories are recallable without leaking raw L0 text. |
| Synthetic hard-anchor pressure | 24 refund workflows | target anchor recall, target source coverage, bounded fact context, TaskGraph presence | all = 1.00 | Under CI-scale pressure, EGM keeps context focused and drill-downable for the target workflow. |
| False-done gate benchmark | 6 refund completion workflows, 24 gate/transition decisions | claim block rate, transition block rate, actionable rejection rate, acceptance after evidence | all = 1.00 | This is EGM's strongest target metric: unsupported completion is blocked, then accepted after fresh evidence is attached. |

## Bottom Line

tau-bench, tau2-bench, and RAGAS-style context metrics are the right external
benchmark directions for EGM. LongMemEval-S and LoCoMo remain useful boundary
diagnostics, but they are not primary benchmarks for EGM v0.4 because they
measure open-ended conversational memory rather than evidence-gated hard-anchor
enterprise workflows.

The primary public benchmark story should be:

> EGM is evaluated on enterprise evidence-gated workflow metrics: evidence source
> coverage, false-completion resistance, actionable rejection, stale-evidence
> leakage, cascading invalidation, hard-anchor recall, and audit coverage.

LongMemEval-S / LoCoMo should be presented as secondary diagnostics, not as the
main proof of value.
