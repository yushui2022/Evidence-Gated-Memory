"""MemoryAgentBench retrieval proxy runner for EGM.

This runner uses official MemoryAgentBench parquet splits but evaluates a
narrow retrieval proxy:

1. Chunk each sample's context into EGM L1 memory atoms.
2. Retrieve top-k atoms for each question with EGM's local FTS search.
3. Count a hit when any gold answer string appears in retrieved atom text.

It is not the official MemoryAgentBench leaderboard score. It is a
source-grounding smoke test for EGM over official benchmark data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evidence_gated_memory import EvidenceGatedMemory  # noqa: E402
from evidence_gated_memory.schemas.builtin import REFUND  # noqa: E402


def evaluate_memory_agent_bench(
    data_path: Path,
    *,
    workspace_root: Optional[Path] = None,
    top_k: int = 5,
    limit_samples: Optional[int] = None,
    limit_questions: Optional[int] = None,
    chunk_chars: int = 1800,
    chunk_overlap: int = 200,
) -> dict[str, Any]:
    df = _read_parquet(data_path)
    if limit_samples is not None:
        df = df.head(limit_samples)

    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_mab_") as tmp:
            return _evaluate_df(
                df,
                Path(tmp),
                data_path=data_path,
                top_k=top_k,
                limit_questions=limit_questions,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            )
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _evaluate_df(
        df,
        workspace_root,
        data_path=data_path,
        top_k=top_k,
        limit_questions=limit_questions,
        chunk_chars=chunk_chars,
        chunk_overlap=chunk_overlap,
    )


def _evaluate_df(
    df: Any,
    workspace_root: Path,
    *,
    data_path: Path,
    top_k: int,
    limit_questions: Optional[int],
    chunk_chars: int,
    chunk_overlap: int,
) -> dict[str, Any]:
    evaluated_questions = 0
    answer_hits = 0
    answer_mrr_total = 0.0
    total_chunks = 0
    details: list[dict[str, Any]] = []

    for sample_idx, row in df.iterrows():
        questions = list(row["questions"])
        answers = list(row["answers"])
        if limit_questions is not None:
            questions = questions[:limit_questions]
            answers = answers[:limit_questions]

        memory = EvidenceGatedMemory(_workspace(workspace_root, f"mab_{sample_idx}"), REFUND)
        try:
            chunks = _chunk_text(
                str(row["context"]),
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            )
            total_chunks += len(chunks)
            for chunk_idx, chunk in enumerate(chunks):
                message = memory.record_conversation_message(
                    "user",
                    chunk,
                    session_id=f"sample_{sample_idx}",
                    metadata={
                        "benchmark": "memory_agent_bench",
                        "sample_idx": int(sample_idx),
                        "chunk_idx": chunk_idx,
                    },
                )
                memory.record_memory_atom(
                    "episodic",
                    chunk,
                    source_messages=[message],
                    metadata={
                        "benchmark": "memory_agent_bench",
                        "sample_idx": int(sample_idx),
                        "chunk_idx": chunk_idx,
                    },
                )

            for question_idx, question in enumerate(questions):
                gold_answers = _flatten_answers(answers[question_idx])
                ranked = memory.store.search_memory_atoms(str(question), limit=top_k)
                rank = _answer_hit_rank([atom.text for atom in ranked], gold_answers)
                hit = rank is not None
                evaluated_questions += 1
                answer_hits += int(hit)
                answer_mrr_total += (1 / rank) if rank else 0.0
                details.append(
                    {
                        "sample_idx": int(sample_idx),
                        "question_idx": question_idx,
                        "question": str(question)[:240],
                        "gold_answers": gold_answers[:10],
                        "retrieved_chunk_ids": [
                            atom.metadata.get("chunk_idx") for atom in ranked
                        ],
                        "hit": hit,
                        "rank": rank,
                    }
                )
        finally:
            memory.close()

    return {
        "benchmark": "memory_agent_bench",
        "split_file": str(data_path),
        "task": "retrieval_proxy_answer_coverage_at_k",
        "retriever": "egm_memory_atoms_fts",
        "top_k": top_k,
        "samples": int(len(df)),
        "evaluated_questions": evaluated_questions,
        "total_chunks": total_chunks,
        "answer_coverage_at_k": answer_hits / evaluated_questions
        if evaluated_questions
        else 0.0,
        "answer_mrr": answer_mrr_total / evaluated_questions
        if evaluated_questions
        else 0.0,
        "details": details,
        "note": (
            "Retrieval-only proxy over official MemoryAgentBench data; not an "
            "official leaderboard score."
        ),
    }


def _read_parquet(path: Path) -> Any:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("pandas is required to read MemoryAgentBench parquet files") from exc

    try:
        return pd.read_parquet(path)
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pyarrow or fastparquet is required. Install pyarrow or set PYTHONPATH "
            "to a directory containing it."
        ) from exc


def _chunk_text(text: str, *, chunk_chars: int, chunk_overlap: int) -> list[str]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_chars:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_chars")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_chars].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_chars - chunk_overlap
    return chunks


def _flatten_answers(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_answers(item))
        return flattened
    try:
        return _flatten_answers(list(value))
    except TypeError:
        return [str(value)]


def _answer_hit_rank(retrieved_texts: list[str], answers: list[str]) -> Optional[int]:
    normalized_answers = [_normalize(answer) for answer in answers if str(answer).strip()]
    normalized_answers = [answer for answer in normalized_answers if answer]
    if not normalized_answers:
        return None
    for rank, text in enumerate(retrieved_texts, start=1):
        normalized_text = _normalize(text)
        if any(answer in normalized_text for answer in normalized_answers):
            return rank
    return None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def _workspace(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run EGM retrieval proxy over a MemoryAgentBench parquet split."
    )
    parser.add_argument("data", type=Path, help="Path to a MemoryAgentBench parquet file.")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-samples", type=int, default=None)
    parser.add_argument("--limit-questions", type=int, default=None)
    parser.add_argument("--chunk-chars", type=int, default=1800)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    result = evaluate_memory_agent_bench(
        args.data,
        workspace_root=args.workspace_root,
        top_k=args.top_k,
        limit_samples=args.limit_samples,
        limit_questions=args.limit_questions,
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
