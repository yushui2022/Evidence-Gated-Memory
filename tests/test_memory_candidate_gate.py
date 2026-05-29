"""L1 long-term memory candidate gate tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from evidence_gated_memory import (
    EvidenceGatedMemory,
    MemoryCandidateDecision,
    MemoryCandidateStatus,
    SourceSpan,
)
from evidence_gated_memory.storage.sqlite import SqliteStore


def _span(message_id: str, content: str, quoted: str) -> SourceSpan:
    start = content.index(quoted)
    end = start + len(quoted)
    return SourceSpan(
        message_id=message_id,
        start_char=start,
        end_char=end,
        quoted_text_hash=hashlib.sha256(quoted.encode("utf-8")).hexdigest(),
    )


def test_candidate_promotes_only_after_gate(memory: EvidenceGatedMemory) -> None:
    content = "Refund completion requires fresh refund_api_response evidence."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "instruction",
        "Refund completion requires fresh refund_api_response evidence.",
        source_spans=[_span(message.id, content, "Refund completion requires fresh refund_api_response evidence")],
        confidence=0.93,
        extraction_rationale="The user stated this as a workflow rule.",
    )

    before = memory.build_context(query="refund completion")
    assert candidate.text not in before

    gate = memory.check_memory_candidate_gate(candidate.id)
    assert gate.accepted is True
    assert gate.decision == MemoryCandidateDecision.PROMOTE
    assert gate.audit_id is not None

    atom = memory.promote_memory_candidate(candidate.id, gate)
    stored = memory.get_memory_candidate(candidate.id)
    assert stored.status == MemoryCandidateStatus.PROMOTED
    assert stored.promoted_atom_id == atom.id
    assert stored.gate_result["decision"] == "promote"

    after = memory.build_context(query="refund completion")
    assert "[ATOM:instruction] Refund completion requires fresh refund_api_response evidence." in after
    assert f"source_message_ids: ['{message.id}']" in after
    assert "The user stated this as a workflow rule." not in after

    events = [row["event_type"] for row in memory.store.list_audit(limit=20)]
    assert "memory_candidate_created" in events
    assert "memory_candidate_gate_check" in events
    assert "memory_candidate_promoted" in events


def test_candidate_without_source_span_rejects(memory: EvidenceGatedMemory) -> None:
    candidate = memory.create_memory_candidate(
        "episodic",
        "Refund memory without grounding should not promote.",
        source_spans=[],
        confidence=0.95,
        extraction_rationale="Extractor guessed this.",
    )

    gate = memory.check_memory_candidate_gate(candidate.id)
    assert gate.accepted is False
    assert gate.decision == MemoryCandidateDecision.REJECT
    assert "source span" in gate.rejection_reason

    rejected = memory.reject_memory_candidate(candidate.id, gate)
    assert rejected.status == MemoryCandidateStatus.REJECTED
    assert memory.list_memory_atoms() == []


def test_promoted_candidate_cannot_be_later_rejected(memory: EvidenceGatedMemory) -> None:
    content = "Refund completion requires a completion receipt."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "instruction",
        "Refund completion requires a completion receipt.",
        source_spans=[_span(message.id, content, "Refund completion requires a completion receipt")],
        confidence=0.95,
        extraction_rationale="The source text states the rule.",
    )
    gate = memory.check_memory_candidate_gate(candidate.id)
    memory.promote_memory_candidate(candidate.id, gate)

    with pytest.raises(ValueError, match="cannot reject candidate"):
        memory.reject_memory_candidate(candidate.id, gate)


def test_candidate_hash_mismatch_rejects(memory: EvidenceGatedMemory) -> None:
    content = "Use payment_record before trusting refund eligibility."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "instruction",
        "Use payment_record before trusting refund eligibility.",
        source_spans=[
            {
                "message_id": message.id,
                "start_char": 0,
                "end_char": len("Use payment_record"),
                "quoted_text_hash": "bad-hash",
            }
        ],
        confidence=0.96,
        extraction_rationale="The source text states the rule.",
    )

    gate = memory.check_memory_candidate_gate(candidate.id)

    assert gate.decision == MemoryCandidateDecision.REJECT
    assert "quoted_text_hash" in gate.rejection_reason


def test_medium_confidence_candidate_goes_pending(memory: EvidenceGatedMemory) -> None:
    content = "The refund team usually asks for extra policy checks."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "episodic",
        "Refund team usually asks for extra policy checks.",
        source_spans=[_span(message.id, content, "refund team usually asks for extra policy checks")],
        confidence=0.72,
        extraction_rationale="The source text is suggestive but not definitive.",
    )

    gate = memory.check_memory_candidate_gate(candidate.id)
    assert gate.decision == MemoryCandidateDecision.PENDING_REVIEW

    pending = memory.mark_memory_candidate_pending(candidate.id, gate)
    assert pending.status == MemoryCandidateStatus.PENDING_REVIEW
    assert memory.list_memory_candidates(status="pending_review") == [pending]
    assert memory.list_memory_atoms() == []


def test_conflict_flag_candidate_goes_pending(memory: EvidenceGatedMemory) -> None:
    content = "For this account, refund completion uses a manual exception."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "instruction",
        "Refund completion uses a manual exception for this account.",
        source_spans=[_span(message.id, content, "refund completion uses a manual exception")],
        confidence=0.94,
        extraction_rationale="The source text conflicts with default policy.",
        conflict_flags=["conflicts_with_default_refund_completion_rule"],
    )

    gate = memory.check_memory_candidate_gate(candidate.id)

    assert gate.decision == MemoryCandidateDecision.PENDING_REVIEW
    assert "conflict flags" in gate.rejection_reason


def test_persona_candidate_defaults_to_pending(memory: EvidenceGatedMemory) -> None:
    content = "The maintainer prefers conservative memory promotion."
    message = memory.record_conversation_message("user", content)
    candidate = memory.create_memory_candidate(
        "persona",
        "User prefers conservative memory promotion.",
        source_spans=[_span(message.id, content, "prefers conservative memory promotion")],
        confidence=0.99,
        extraction_rationale="The source text describes a long-lived preference.",
    )

    gate = memory.check_memory_candidate_gate(candidate.id)

    assert gate.decision == MemoryCandidateDecision.PENDING_REVIEW
    assert "persona candidates default" in gate.rejection_reason


def test_candidate_missing_source_message_rejects(memory: EvidenceGatedMemory) -> None:
    candidate = memory.create_memory_candidate(
        "episodic",
        "Missing source message should reject.",
        source_spans=[
            {
                "message_id": "msg_missing",
                "start_char": 0,
                "end_char": 7,
                "quoted_text_hash": hashlib.sha256(b"Missing").hexdigest(),
            }
        ],
        confidence=0.95,
        extraction_rationale="The source message id is bogus.",
    )

    gate = memory.check_memory_candidate_gate(candidate.id)

    assert gate.decision == MemoryCandidateDecision.REJECT
    assert "source message not found" in gate.rejection_reason


def test_sqlite_migrates_v1_workspace_to_memory_candidates(tmp_path: Path) -> None:
    workspace = tmp_path / "egm"
    workspace.mkdir()
    db_path = workspace / "egm.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')")
        conn.commit()

    store = SqliteStore(workspace)
    try:
        columns = {
            row["name"]
            for row in store.conn.execute("PRAGMA table_info(memory_atom_candidates)").fetchall()
        }
        assert store.get_schema_version() == 3
        assert {
            "id",
            "source_spans",
            "status",
            "gate_result",
            "promoted_atom_id",
        }.issubset(columns)
    finally:
        store.close()


def test_candidate_decision_audit_keeps_structured_detail(memory: EvidenceGatedMemory) -> None:
    candidate = memory.create_memory_candidate(
        "episodic",
        "Unsupported candidate should write structured audit detail.",
        source_spans=[],
        confidence=0.1,
        extraction_rationale="No real support.",
    )
    gate = memory.check_memory_candidate_gate(candidate.id)
    memory.reject_memory_candidate(candidate.id, gate)

    details = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=20)
        if row["event_type"] == "memory_candidate_rejected"
    ]

    assert details[0]["candidate_id"] == candidate.id
    assert details[0]["decision"] == "reject"
    assert details[0]["violations"]
