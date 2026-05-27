"""LoCoMo retrieval runner for EGM.

This runner evaluates an evidence-dialog retrieval subtask over LoCoMo-style
data. It does not generate answers and should not be reported as the official
LoCoMo QA score.
"""

from __future__ import annotations

import argparse
import json
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


def evaluate_locomo(
    data_path: Path,
    *,
    workspace_root: Optional[Path] = None,
    top_k: int = 5,
    limit_samples: Optional[int] = None,
    limit_questions: Optional[int] = None,
) -> dict[str, Any]:
    data = _load_json(data_path)
    if not isinstance(data, list):
        raise ValueError("LoCoMo data must be a JSON list")
    samples = data[:limit_samples] if limit_samples is not None else data

    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_locomo_") as tmp:
            return _evaluate_samples(samples, Path(tmp), top_k=top_k, limit_questions=limit_questions)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _evaluate_samples(samples, workspace_root, top_k=top_k, limit_questions=limit_questions)


def _evaluate_samples(
    samples: list[dict[str, Any]],
    workspace_root: Path,
    *,
    top_k: int,
    limit_questions: Optional[int],
) -> dict[str, Any]:
    evaluated = 0
    skipped_no_evidence = 0
    hits = 0
    mrr_total = 0.0
    details: list[dict[str, Any]] = []

    for sample_idx, sample in enumerate(samples):
        memory = EvidenceGatedMemory(_workspace(workspace_root, f"locomo_{sample_idx}"), REFUND)
        try:
            _seed_conversation(memory, sample)
            qas = _qa_items(sample)
            if limit_questions is not None:
                qas = qas[:limit_questions]
            for qa_idx, qa in enumerate(qas):
                evidence_ids = {str(value) for value in qa.get("evidence", [])}
                if not evidence_ids:
                    skipped_no_evidence += 1
                    continue
                ranked = memory.store.search_memory_atoms(str(qa.get("question", "")), limit=top_k)
                ranked_dialog_ids = [str(atom.metadata.get("dia_id", "")) for atom in ranked]
                rank = _first_hit_rank(ranked_dialog_ids, evidence_ids)
                hit = rank is not None
                evaluated += 1
                hits += int(hit)
                mrr_total += (1 / rank) if rank else 0.0
                details.append(
                    {
                        "sample_id": sample.get("sample_id", sample.get("id", sample_idx)),
                        "qa_index": qa_idx,
                        "evidence": sorted(evidence_ids),
                        "retrieved_dialog_ids": ranked_dialog_ids,
                        "hit": hit,
                        "rank": rank,
                    }
                )
        finally:
            memory.close()

    return {
        "benchmark": "locomo",
        "task": "evidence_dialog_retrieval_recall_at_k",
        "retriever": "egm_memory_atoms_fts",
        "top_k": top_k,
        "total_samples": len(samples),
        "evaluated_questions": evaluated,
        "skipped_no_evidence": skipped_no_evidence,
        "recall_at_k": hits / evaluated if evaluated else 0.0,
        "mrr": mrr_total / evaluated if evaluated else 0.0,
        "details": details,
        "note": "Retrieval-only runner; not an official LoCoMo generative QA score.",
    }


def _seed_conversation(memory: EvidenceGatedMemory, sample: dict[str, Any]) -> None:
    conversation = sample.get("conversation") or {}
    if isinstance(conversation, list):
        sessions = {"session_0": conversation}
    else:
        sessions = {
            key: value
            for key, value in conversation.items()
            if key.startswith("session") and isinstance(value, list)
        }

    sample_id = str(sample.get("sample_id", sample.get("id", "sample")))
    for session_name, turns in sessions.items():
        for turn_idx, turn in enumerate(turns):
            if not isinstance(turn, dict):
                text = str(turn)
                dia_id = f"{session_name}_{turn_idx}"
                speaker = "speaker"
            else:
                speaker = str(turn.get("speaker") or turn.get("role") or "speaker")
                text = str(turn.get("text") or turn.get("content") or turn.get("utterance") or "")
                dia_id = str(turn.get("dia_id") or turn.get("dialogue_id") or f"{session_name}_{turn_idx}")

            rendered = f"{speaker}: {text}"
            message = memory.record_conversation_message(
                "user",
                rendered,
                session_id=f"{sample_id}:{session_name}",
                metadata={
                    "benchmark": "locomo",
                    "sample_id": sample_id,
                    "session": session_name,
                    "dia_id": dia_id,
                },
            )
            memory.record_memory_atom(
                "episodic",
                rendered,
                source_messages=[message],
                metadata={
                    "benchmark": "locomo",
                    "sample_id": sample_id,
                    "session": session_name,
                    "dia_id": dia_id,
                },
            )


def _qa_items(sample: dict[str, Any]) -> list[dict[str, Any]]:
    qas = sample.get("qa") or sample.get("qa_pairs") or sample.get("questions") or []
    if isinstance(qas, dict):
        flattened = []
        for value in qas.values():
            if isinstance(value, list):
                flattened.extend(value)
        return flattened
    return qas if isinstance(qas, list) else []


def _first_hit_rank(ranked_ids: list[str], evidence_ids: set[str]) -> Optional[int]:
    for idx, dia_id in enumerate(ranked_ids, start=1):
        if dia_id in evidence_ids:
            return idx
    return None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _workspace(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run EGM evidence-dialog retrieval over LoCoMo-style data.")
    parser.add_argument("data", type=Path, help="Path to LoCoMo JSON data.")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-samples", type=int, default=None)
    parser.add_argument("--limit-questions", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    result = evaluate_locomo(
        args.data,
        workspace_root=args.workspace_root,
        top_k=args.top_k,
        limit_samples=args.limit_samples,
        limit_questions=args.limit_questions,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
