# Official Dataset Runners

This directory contains entry points for running EGM against public benchmark
datasets. These runners are **not** part of the default pytest suite and do not
ship benchmark data in the repository.

The current runners evaluate retrieval sub-tasks:

- LongMemEval-S style: retrieve an answer-supporting session into top-k memory
  atoms.
- LoCoMo style: retrieve an evidence dialogue turn into top-k memory atoms.
- MemoryAgentBench style: retrieve answer-supporting context chunks into top-k
  memory atoms and check answer-string coverage.

They do **not** compute full generative QA leaderboard scores. Treat them as
reproducible evidence-retrieval reports for EGM, not as official benchmark
submissions.

## LongMemEval-S

Reference: https://arxiv.org/abs/2410.10813

Prepare an official LongMemEval-style JSON file, then run:

```bash
python benchmarks/official/longmemeval_s.py path/to/longmemeval_s.json --top-k 5 --output reports/longmemeval_s_egm.json
```

For a quick smoke run:

```bash
python benchmarks/official/longmemeval_s.py path/to/longmemeval_s.json --top-k 5 --limit 25
```

Expected input fields are flexible but should contain:

- `question`
- `haystack_sessions` or `sessions`
- `haystack_session_ids` or `session_ids`
- `answer_session_ids`

## LoCoMo

Reference: https://aclanthology.org/2024.acl-long.747/

Prepare an official LoCoMo JSON file, then run:

```bash
python benchmarks/official/locomo.py path/to/locomo.json --top-k 5 --output reports/locomo_egm.json
```

For a quick smoke run:

```bash
python benchmarks/official/locomo.py path/to/locomo.json --top-k 5 --limit-samples 2 --limit-questions 20
```

Expected input fields are flexible but should contain:

- `conversation`, with `session_*` lists of dialogue turns
- `qa`, `qa_pairs`, or `questions`
- each QA item should include `question` and `evidence`
- dialogue turns should include `dia_id` and `text` or compatible field names

## Interpretation

EGM v0.4 is hard-anchor and evidence-gated. These official-data runners are
expected to be most informative when benchmark questions contain lexical anchors
or source ids. Poor scores on open-ended natural-language recall should be read
as a retrieval-model gap, not as evidence-gating failure.

If these reports are used publicly, state the task precisely:

> EGM retrieval-only Recall@K over LongMemEval-S / LoCoMo evidence fields.

Do not call these official LongMemEval or LoCoMo leaderboard scores.

## MemoryAgentBench

Reference: https://openreview.net/forum?id=DT7JyQC3MR

Prepare an official MemoryAgentBench parquet split, then run:

```bash
python benchmarks/official/memory_agent_bench.py path/to/Conflict_Resolution.parquet --top-k 5 --output reports/memory_agent_bench_conflict.json
```

For a quick smoke run:

```bash
python benchmarks/official/memory_agent_bench.py path/to/Conflict_Resolution.parquet --top-k 5 --limit-samples 1 --limit-questions 20
```

This runner is intentionally narrow:

- It chunks `context` into EGM memory atoms.
- It retrieves top-k atoms for each question.
- It counts a hit when any gold answer string appears in retrieved text.

It is a retrieval-only proxy over official data, not an official
MemoryAgentBench submission.
