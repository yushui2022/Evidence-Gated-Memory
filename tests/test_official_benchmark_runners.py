"""Tiny fixture tests for official-dataset benchmark runners."""

from __future__ import annotations

import json

from benchmarks.official.locomo import evaluate_locomo
from benchmarks.official.longmemeval_s import evaluate_longmemeval_s
from benchmarks.official.memory_agent_bench import evaluate_memory_agent_bench


def test_longmemeval_s_runner_on_tiny_fixture(tmp_path) -> None:
    data = [
        {
            "question_id": "q1",
            "question": "ORD-777 PAID",
            "haystack_session_ids": ["session_noise", "session_answer"],
            "haystack_sessions": [
                [{"role": "user", "content": "The customer asked about an unrelated delivery."}],
                [{"role": "assistant", "content": "Order ORD-777 is PAID and eligible."}],
            ],
            "answer_session_ids": ["session_answer"],
        }
    ]
    path = tmp_path / "longmemeval_s.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = evaluate_longmemeval_s(path, workspace_root=tmp_path / "lme_ws", top_k=1)

    assert result["evaluated_items"] == 1
    assert result["recall_at_k"] == 1.0
    assert result["mrr"] == 1.0


def test_locomo_runner_on_tiny_fixture(tmp_path) -> None:
    data = [
        {
            "sample_id": "sample_1",
            "conversation": {
                "session_1": [
                    {"speaker": "Alice", "dia_id": "d1", "text": "Alice Seattle relocation plan."},
                    {"speaker": "Bob", "dia_id": "d2", "text": "Bob discussed dinner."},
                ]
            },
            "qa": [
                {
                    "question": "Alice Seattle relocation",
                    "answer": "Alice planned a Seattle relocation.",
                    "evidence": ["d1"],
                }
            ],
        }
    ]
    path = tmp_path / "locomo.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    result = evaluate_locomo(path, workspace_root=tmp_path / "locomo_ws", top_k=1)

    assert result["evaluated_questions"] == 1
    assert result["recall_at_k"] == 1.0
    assert result["mrr"] == 1.0


def test_memory_agent_bench_runner_on_tiny_fixture(tmp_path, monkeypatch) -> None:
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "context": "Alpha fact. Belgium is the citizenship country for the spouse.",
                "questions": ["What is the country of citizenship of the spouse?"],
                "answers": [["Belgium"]],
                "metadata": {"source": "tiny_fixture"},
            }
        ]
    )

    monkeypatch.setattr(
        "benchmarks.official.memory_agent_bench._read_parquet",
        lambda path: df,
    )

    result = evaluate_memory_agent_bench(
        tmp_path / "fixture.parquet",
        workspace_root=tmp_path / "mab_ws",
        top_k=1,
        limit_samples=1,
        limit_questions=1,
        chunk_chars=200,
        chunk_overlap=0,
    )

    assert result["samples"] == 1
    assert result["evaluated_questions"] == 1
    assert result["answer_coverage_at_k"] == 1.0
    assert result["answer_mrr"] == 1.0
