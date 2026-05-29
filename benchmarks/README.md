# EGM Local Benchmarks

These benchmarks are deterministic local probes for Evidence-Gated Memory. They
are **not official leaderboard runs** and should not be reported as LongMemEval,
LoCoMo, or BEAM scores.

The suite maps well-known memory benchmark shapes onto EGM's product surface:

- `longmemeval_s_hard_anchor` checks exact hard-anchor recall, evidence source
  coverage, and unsupported-query abstention. This is aligned with the
  LongMemEval / LongMemEval-S family of long-term-memory tasks.
- `locomo_style_semantic_pyramid` checks the manual L0/L1/L2/L3 path: promoted
  memories are recallable, source ids are shown, and raw L0 dialogue stays out
  of prompt context. This is a narrow LoCoMo-style diagnostic, not an open
  dialogue leaderboard run.
- `beam_lite_hard_anchor_pressure` seeds many hard-anchor workflows and verifies
  bounded context, TaskGraph presence, and drill-down source coverage under
  synthetic pressure.
- `false_done_gate_benchmark` is EGM-specific: unsupported completion claims and
  DONE transitions must be rejected with actionable guidance, then accepted once
  fresh evidence is attached.

Reference task families:

- LongMemEval: https://arxiv.org/abs/2410.10813
- LoCoMo: https://aclanthology.org/2024.acl-long.747/

Run from the repository root:

```bash
python benchmarks/run_local.py
python benchmarks/run_local.py --json
```

Generate release-ready deterministic benchmark artifacts:

```bash
python scripts/generate_benchmark_snapshot.py
```

This writes:

- `reports/deterministic_benchmark_snapshot.json`
- `reports/deterministic_benchmark_snapshot.md`

CI coverage:

```bash
python -m pytest tests/test_benchmarks.py -q
```

The benchmark suite intentionally uses no external model or hosted dataset. That
keeps it fast enough for pull requests while still checking the behavior that
matters for EGM's target market: hard anchors, source coverage, bounded context,
gate rejection, and false-completion resistance.

## Official Dataset Runners

For public-facing reports, use the optional runners in `benchmarks/official/`.
They load real benchmark files but are not included in the default test suite at
full scale:

```bash
python benchmarks/official/longmemeval_s.py path/to/longmemeval_s.json --top-k 5 --output reports/longmemeval_s_egm.json
python benchmarks/official/locomo.py path/to/locomo.json --top-k 5 --output reports/locomo_egm.json
```

These runners compute retrieval-only Recall@K / MRR over official evidence
fields. They are still not leaderboard submissions because they do not generate
answers or run the official judge pipeline. See
`benchmarks/official/README.md` before using the numbers in public material.

## Public Reporting Protocol

Before moving any benchmark number into README, release notes, PyPI text, or a
social post, apply the rules in `docs/benchmark-decision-protocol.md`.

Short version:

- deterministic local probes are EGM correctness guards, not leaderboard scores;
- official-data runners in this repo are retrieval-only proxies unless the
  official judge pipeline is run;
- tau-bench and tau2-bench are downstream agent A/B evaluations, so every result
  must include task count, model route, cost/budget, and limitations;
- failed harness/model routes must be reported as "blocked/no valid score", not
  as quality results.
