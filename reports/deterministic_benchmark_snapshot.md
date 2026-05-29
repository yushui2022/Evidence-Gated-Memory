# EGM Deterministic Benchmark Snapshot

Generated: `2026-05-29T04:35:00.090880+00:00`

Local deterministic EGM correctness probes. These are not official leaderboard scores and do not call external model APIs.

## Summary

| Metric | Value |
|---|---:|
| Suites passed | 4 / 4 |
| Checks passed | 21 / 21 |
| Overall passed | True |

## Suites

| Suite | Passed | Checks | Duration ms |
|---|---:|---:|---:|
| `egm-local-benchmarks` | True | 4 | 35412.9 |
| `egm-adversarial-probes` | True | 10 | 11571.54 |
| `egm-scenario-probes` | True | 6 | 47659.55 |
| `tau_bench_egm_smoke` | True | 1 |  |

## Interpretation

- This snapshot is a release correctness guard for EGM-native behavior.
- It is not a tau-bench, tau2-bench, LongMemEval, LoCoMo, or MemoryAgentBench leaderboard score.
- Public reports must pair these numbers with the benchmark decision protocol.

Related document: `docs/benchmark-decision-protocol.md`.
