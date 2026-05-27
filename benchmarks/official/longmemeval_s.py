"""LongMemEval-S retrieval runner for EGM.

This runner expects an official LongMemEval-style JSON file. It evaluates a
retrieval subtask: can EGM retrieve at least one answer-supporting session into
the top-k long-term memory atoms for a question?

It is not a full generative QA score and should not be reported as a leaderboard
result.
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


def evaluate_longmemeval_s(
    data_path: Path,
    *,
    workspace_root: Optional[Path] = None,
    top_k: int = 5,
    limit: Optional[int] = None,
    include_abstention: bool = False,
) -> dict[str, Any]:
    data = _load_json(data_path)
    if not isinstance(data, list):
        raise ValueError("LongMemEval data must be a JSON list")
    items = data[:limit] if limit is not None else data

    if workspace_root is None:
        with tempfile.TemporaryDirectory(prefix="egm_lme_") as tmp:
            return _evaluate_items(items, Path(tmp), top_k=top_k, include_abstention=include_abstention)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return _evaluate_items(items, workspace_root, top_k=top_k, include_abstention=include_abstention)


def _evaluate_items(
    items: list[dict[str, Any]],
    workspace_root: Path,
    *,
    top_k: int,
    include_abstention: bool,
) -> dict[str, Any]:
    evaluated = 0
    skipped_abstention = 0
    hits = 0
    mrr_total = 0.0
    details: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        answer_ids = {str(value) for value in item.get("answer_session_ids", [])}
        if not answer_ids and not include_abstention:
            skipped_abstention += 1
            continue

        memory = EvidenceGatedMemory(_workspace(workspace_root, f"lme_{idx}"), REFUND)
        try:
            _seed_sessions(memory, item)
            ranked = memory.store.search_memory_atoms(str(item.get("question", "")), limit=top_k)
        finally:
            memory.close()

        ranked_session_ids = [str(atom.metadata.get("session_id", "")) for atom in ranked]
        rank = _first_hit_rank(ranked_session_ids, answer_ids)
        hit = rank is not None if answer_ids else not ranked_session_ids
        evaluated += 1
        hits += int(hit)
        mrr_total += (1 / rank) if rank else 0.0
        details.append(
            {
                "question_id": item.get("question_id", item.get("id", idx)),
                "answer_session_ids": sorted(answer_ids),
                "retrieved_session_ids": ranked_session_ids,
                "hit": hit,
                "rank": rank,
            }
        )

    return {
        "benchmark": "longmemeval_s",
        "task": "session_retrieval_recall_at_k",
        "retriever": "egm_memory_atoms_fts",
        "top_k": top_k,
        "total_items": len(items),
        "evaluated_items": evaluated,
        "skipped_abstention": skipped_abstention,
        "recall_at_k": hits / evaluated if evaluated else 0.0,
        "mrr": mrr_total / evaluated if evaluated else 0.0,
        "details": details,
        "note": "Retrieval-only runner; not an official LongMemEval leaderboard score.",
    }


def _seed_sessions(memory: EvidenceGatedMemory, item: dict[str, Any]) -> None:
    sessions = item.get("haystack_sessions") or item.get("sessions") or []
    session_ids = item.get("haystack_session_ids") or item.get("session_ids") or []
    if not session_ids:
        session_ids = [f"session_{idx}" for idx in range(len(sessions))]
    for idx, session in enumerate(sessions):
        session_id = str(session_ids[idx]) if idx < len(session_ids) else f"session_{idx}"
        text = _render_session(session)
        message = memory.record_conversation_message(
            "user",
            text,
            session_id=session_id,
            metadata={"benchmark": "longmemeval_s", "session_id": session_id},
        )
        memory.record_memory_atom(
            "episodic",
            text,
            source_messages=[message],
            metadata={"benchmark": "longmemeval_s", "session_id": session_id},
        )


def _render_session(session: Any) -> str:
    if isinstance(session, str):
        return session
    if isinstance(session, dict):
        return json.dumps(session, ensure_ascii=False, sort_keys=True)
    if isinstance(session, list):
        lines = []
        for turn in session:
            if isinstance(turn, dict):
                speaker = turn.get("role") or turn.get("speaker") or turn.get("name") or "speaker"
                content = turn.get("content") or turn.get("text") or turn.get("utterance") or ""
                lines.append(f"{speaker}: {content}")
            else:
                lines.append(str(turn))
        return "\n".join(lines)
    return str(session)


def _first_hit_rank(ranked_ids: list[str], answer_ids: set[str]) -> Optional[int]:
    for idx, session_id in enumerate(ranked_ids, start=1):
        if session_id in answer_ids:
            return idx
    return None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _workspace(root: Path, name: str) -> Path:
    return root / f"{name}_{uuid4().hex[:8]}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run EGM retrieval over LongMemEval-S-style data.")
    parser.add_argument("data", type=Path, help="Path to LongMemEval JSON data.")
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-abstention", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    result = evaluate_longmemeval_s(
        args.data,
        workspace_root=args.workspace_root,
        top_k=args.top_k,
        limit=args.limit,
        include_abstention=args.include_abstention,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
