import json
import hashlib
from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.cli import main
from evidence_gated_memory.schemas.builtin import REFUND


def _seed(workspace: Path) -> None:
    memory = EvidenceGatedMemory(workspace, REFUND)
    try:
        order = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-123","status":"PAID"}',
            metadata={"order_id": "ORD-123"},
        )
        policy = memory.record_evidence(
            evidence_type="refund_policy",
            source="policy_db",
            source_system="policy_db",
            content="14d",
        )
        result = memory.assert_fact(
            "Order ORD-123 is refundable",
            claim_type="refund_eligibility",
            evidence=[order, policy],
        )
        assert result.accepted
    finally:
        memory.close()


def test_cli_schema_validate_builtin(capsys):
    assert main(["schema", "validate", "refund"]) == 0
    out = capsys.readouterr().out
    assert "schema: ok" in out
    assert "schema: refund" in out


def test_cli_inspect_context_audit_and_ref(tmp_path: Path, capsys):
    workspace = tmp_path / "egm"
    _seed(workspace)

    assert main(["inspect", str(workspace), "--schema", "refund"]) == 0
    inspect_out = capsys.readouterr().out
    assert "schema_version: 2" in inspect_out
    assert "facts_active: 1" in inspect_out
    assert "evidence: 2" in inspect_out

    assert main(["context", str(workspace), "--schema", "refund", "--query", "ORD-123"]) == 0
    context_out = capsys.readouterr().out
    assert "ORD-123" in context_out
    assert "[FACT]" in context_out

    assert main(["audit", str(workspace), "--limit", "5"]) == 0
    audit_out = capsys.readouterr().out
    assert "gate_check" in audit_out
    assert "fact_committed" in audit_out

    ref_id = next((workspace / "refs").glob("*.md")).stem
    assert main(["ref", str(workspace), ref_id]) == 0
    ref_out = capsys.readouterr().out
    assert ref_out.strip()


def test_cli_inspect_includes_graph_offload_and_long_term_counts(tmp_path: Path, capsys):
    workspace = tmp_path / "egm"
    memory = EvidenceGatedMemory(workspace, REFUND)
    try:
        node_a = memory.create_task_node("task_cli_inspect", "check_order", "Check order")
        node_b = memory.create_task_node("task_cli_inspect", "check_payment", "Check payment")
        memory.add_task_edge(node_a.id, node_b.id)
        evidence = memory.record_evidence(
            evidence_type="order_record",
            source="order_api",
            source_system="order_api",
            content='{"order_id":"ORD-INSPECT","status":"PAID"}',
            metadata={"order_id": "ORD-INSPECT"},
        )
        memory.record_offload(
            task_id="task_cli_inspect",
            node_id=node_a.id,
            tool_call_id="call_cli_inspect",
            result_ref=evidence,
            summary="order_api returned ORD-INSPECT status=PAID",
        )
        message = memory.record_conversation_message(
            "user",
            "Refund workflows need explicit source ids.",
            session_id="session_cli_inspect",
        )
        atom = memory.record_memory_atom(
            "instruction",
            "Refund workflow context should stay drill-downable.",
            source_messages=[message],
        )
        scenario = memory.record_memory_scenario(
            "CLI inspect scenario",
            "Inspect should report long-term memory layers.",
            atoms=[atom],
        )
        memory.record_memory_persona(
            "CLI inspect persona",
            "Maintains evidence-gated memory diagnostics.",
            scenarios=[scenario],
        )
    finally:
        memory.close()

    assert main(["inspect", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "tasks: 1" in out
    assert "task_nodes: 2" in out
    assert "task_edges: 1" in out
    assert "offload_records: 1" in out
    assert "conversation_messages: 1" in out
    assert "memory_atom_candidates: 0" in out
    assert "memory_atoms: 1" in out
    assert "memory_scenarios: 1" in out
    assert "memory_personas: 1" in out

    assert main(["export-audit", str(workspace), "--format", "json", "--task-id", "task_cli_inspect"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported
    assert {row["event_type"] for row in exported} >= {
        "task_node_created",
        "task_edge_added",
        "offload_recorded",
    }

    assert main(["export-audit", str(workspace), "--format", "md", "--evidence-id", evidence.id]) == 0
    exported_md = capsys.readouterr().out
    assert "| id | created_at | event_type | accepted | claim_id | fact_id | detail |" in exported_md
    assert "offload_recorded" in exported_md


def test_cli_candidates_lists_review_queue(tmp_path: Path, capsys):
    workspace = tmp_path / "egm"
    memory = EvidenceGatedMemory(workspace, REFUND)
    try:
        content = "Refund completion usually needs a second review."
        message = memory.record_conversation_message("user", content)
        quoted = "Refund completion usually needs a second review"
        candidate = memory.create_memory_candidate(
            "instruction",
            "Refund completion usually needs a second review.",
            source_spans=[
                {
                    "message_id": message.id,
                    "start_char": 0,
                    "end_char": len(quoted),
                    "quoted_text_hash": hashlib.sha256(quoted.encode("utf-8")).hexdigest(),
                }
            ],
            confidence=0.72,
            extraction_rationale="The source is plausible but needs review.",
        )
        gate = memory.check_memory_candidate_gate(candidate.id)
        memory.mark_memory_candidate_pending(candidate.id, gate)
    finally:
        memory.close()

    assert main(["candidates", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "memory_atom_candidates: 1" in out
    assert candidate.id in out
    assert "status=pending_review" in out
    assert "decision=pending_review" in out

    assert main(["candidates", str(workspace), "--status", "pending_review", "--format", "json"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported[0]["id"] == candidate.id
    assert exported[0]["decision"] == "pending_review"
    assert exported[0]["source_message_ids"] == [message.id]


def test_cli_sweep(tmp_path: Path, capsys):
    workspace = tmp_path / "egm"
    _seed(workspace)
    assert main(["sweep", str(workspace), "--schema", "refund"]) == 0
    out = capsys.readouterr().out
    assert "invalidated: 0" in out
