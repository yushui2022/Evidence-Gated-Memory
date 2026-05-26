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


def test_cli_sweep(tmp_path: Path, capsys):
    workspace = tmp_path / "egm"
    _seed(workspace)
    assert main(["sweep", str(workspace), "--schema", "refund"]) == 0
    out = capsys.readouterr().out
    assert "invalidated: 0" in out
