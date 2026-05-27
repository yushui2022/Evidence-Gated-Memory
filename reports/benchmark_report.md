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
market. They are listed separately from EGM-owned synthetic benchmarks.
Small-batch smoke runs were attempted for tau-bench and tau2-bench on
2026-05-27. Neither produced a valid leaderboard-style score yet because the
external harness/model path failed before meaningful task evaluation. RAGAS-style
context grounding is currently measured with EGM's local hard-anchor contexts.

| Benchmark / metric family | Why it fits EGM | External metric(s) to report | EGM-specific metric(s) to add | Current measurement status |
|---|---|---|---|---|
| tau-bench | Best external fit for enterprise workflow agents: multi-turn user interaction, tools/APIs, domain policies, task completion. | Task success / pass rate, policy violation rate, tool-use correctness. | false done rate, unsupported claim block rate, evidence source coverage, actionable rejection rate, audit coverage. | **Smoke attempted, no valid score.** 1 retail task trial was started through the external harness, but failed before scoring with a LiteLLM/Anthropic `502 Bad Gateway`. Needs a stable model route and an EGM adapter before public reporting. |
| tau2-bench / Tau2-Bench | Best fit for dynamic enterprise state: user and environment can change state while the agent acts. | Task success under dynamic state, invalid action rate, policy consistency. | stale fact leakage rate, cascading invalidation correctness, fresh-evidence requirement satisfaction, state-transition gate accuracy. | **Smoke attempted, no valid score.** CLI installed and a 1-task mock run was attempted. The run exited without evaluated tasks because the minimal dummy-user/solo-agent setup hit an infra/config error: `DummyUser.__init__() got an unexpected keyword argument 'tools'`. |
| RAGAS / RAG evaluation metrics | Good fit for evaluating EGM's prompt context quality: context must be grounded, precise, and source-backed. | context precision, context recall, faithfulness / answer grounding. | evidence source coverage, ref drill-down coverage, stale fact leakage rate, context budget efficiency. | **Measured as RAGAS-style local metrics:** source coverage = 1.00, context bound = 1.00 over 12 hard-anchor source cases + 24 pressure cases. |

### Small-Batch External Smoke Run

| Benchmark | Small batch attempted | Result | What this means |
|---|---:|---|---|
| tau-bench | 1 `retail` task, 1 trial | Blocked before scoring: LiteLLM/Anthropic gateway returned `502 Bad Gateway` for `/v1/messages`. | No pass-rate can be claimed. This is an external model/harness path failure, not an EGM quality result. |
| tau2-bench / Tau2-Bench | 1 `mock` task, 1 trial, `max_steps=3` | Blocked before valid evaluation: `Evaluated 0`; infra error from `DummyUser.__init__()` receiving unexpected `tools`. | No reward can be claimed. Need a correct tau2 user simulator/agent config or a dedicated EGM adapter. |
| RAGAS-style grounding metrics | 12 hard-anchor source cases + 24 pressure cases | Measured locally: source coverage = 1.00, context bound = 1.00. | This is a RAGAS-style adapted metric family, not an official RAGAS package or leaderboard run. |

### tau / tau2 Diagnostic Update

The key technical finding is now clearer than the original smoke report:

- The local Claude proxy at `127.0.0.1:16661` is alive and returns `200` for direct `requests`-style POSTs to `/v1/messages`.
- The same proxy returns `502` when called through the `httpx` / `LiteLLM` client stack used by tau-bench and tau2-bench.
- That means the current blocker is client-stack compatibility, not model availability.
- To continue tau/tau2 seriously, the cleanest path is a direct provider API key that `LiteLLM` supports without the local proxy layer.

### Current Commands Used

```bash
python benchmarks/run_local.py --json > reports/local_benchmarks_latest.json
```

External smoke commands were run from cloned benchmark repositories on the F:
drive to avoid filling the system drive. Secrets are intentionally not recorded
in this report.

```powershell
# tau-bench smoke run, external repo: F:\bench_repos\tau-bench
python run.py --agent-strategy tool-calling --env retail --model claude-sonnet-4-6 --model-provider anthropic --user-model claude-sonnet-4-6 --user-model-provider anthropic --user-strategy llm --task-ids 0 --num-trials 1 --max-concurrency 1 --log-dir F:/egm_bench_reports/tau_bench_retail_smoke

# tau2-bench smoke run, external repo: F:\bench_repos\tau2-bench
uv run tau2 run --domain mock --task-set-name mock --num-tasks 1 --num-trials 1 --max-steps 3 --max-concurrency 1 --agent llm_agent_solo --agent-llm claude-sonnet-4-6 --user dummy_user --save-to egm_tau2_mock_solo_smoke --log-level ERROR
```

LongMemEval-S and LoCoMo retrieval-only runners remain available under
`benchmarks/official/`, but they are boundary diagnostics for non-target
open-ended memory and are not part of the primary external benchmark table.

## Official Memory-Benchmark Data Runs

These runs use official benchmark data, but EGM is currently evaluated with
retrieval-only proxy runners rather than full generative leaderboard protocols.
That distinction matters.

| Official dataset | Split | Batch size | Result | Interpretation |
|---|---|---:|---|---|
| MemoryAgentBench | `Conflict_Resolution` | 8 samples / 800 questions | answer coverage@5 = `0.66875`, MRR = `0.46856` | This is the most informative official memory result so far because CR is close to EGM's freshness/conflict-update problem. It shows EGM can recover answer-bearing evidence chunks reasonably often with plain local FTS, but it is not yet a full conflict-resolution reasoning score. |
| MemoryAgentBench | `Accurate_Retrieval` | 1 sample / 20 questions | answer coverage@5 = `0.70`, MRR = `0.59583` | This aligns with EGM's current strengths: source-grounded retrieval over hard evidence. |
| MemoryAgentBench | `Test_Time_Learning` | 1 sample / 20 questions | answer coverage@5 = `0.00`, MRR = `0.00` | Expected failure for the current architecture. EGM does not yet implement a test-time learning mechanism that converts interaction examples into reusable task policy or latent skill. A retrieval proxy alone is insufficient here. |
| MemoryAgentBench | `Long_Range_Understanding` | not run | not scored | The official LRU split is summarization/generation-oriented. The current EGM proxy runner is retrieval-only, so forcing a score here would be misleading. |

### MemoryAgentBench Notes

- Data source used locally: `D:\bench_repos\MemoryAgentBench_modelscope`
- Runner: [benchmarks/official/memory_agent_bench.py](C:/Users/xiaoy/Desktop/Evidence-Gated-Memory/benchmarks/official/memory_agent_bench.py)
- Proxy metric definition: chunk `context` into memory atoms, retrieve top-k atoms for each question, then check whether any gold answer string appears in retrieved text.
- These are not official leaderboard numbers and should be labeled `retrieval-only proxy over official MemoryAgentBench data`.

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
benchmark directions for EGM. The first smoke runs show that tau-bench and
tau2-bench need adapter/model-route work before any public score should be
claimed. LongMemEval-S and LoCoMo remain useful boundary diagnostics, but they
are not primary benchmarks for EGM v0.4 because they measure open-ended
conversational memory rather than evidence-gated hard-anchor enterprise
workflows.

MemoryAgentBench is currently the strongest official benchmark fit for EGM's
memory layer itself. The early results already separate EGM's strengths and
gaps cleanly:

- `Conflict_Resolution`: meaningful and moderately strong under a retrieval proxy.
- `Accurate_Retrieval`: reasonably strong with local FTS only.
- `Test_Time_Learning`: currently unsupported by architecture, not just under-tuned.
- `Long_Range_Understanding`: needs a generative evaluator, not a retrieval-only proxy.

The primary public benchmark story should be:

> EGM is evaluated on enterprise evidence-gated workflow metrics: evidence source
> coverage, false-completion resistance, actionable rejection, stale-evidence
> leakage, cascading invalidation, hard-anchor recall, and audit coverage.

LongMemEval-S / LoCoMo should be presented as secondary diagnostics, not as the
main proof of value.
