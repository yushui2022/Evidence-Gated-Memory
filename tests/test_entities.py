from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.core.entities import extract_entities
from evidence_gated_memory.schemas.builtin import REFUND
from evidence_gated_memory.schemas.loader import load_schema


def test_metadata_entities_are_stored(memory: EvidenceGatedMemory):
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content='{"status":"PAID"}',
        metadata={"order_id": "ORD-123"},
    )
    entities = ev.metadata["entities"]
    assert {"entity_type": "order", "value": "ORD-123", "source": "metadata", "field": "order_id", "pattern": None} in entities


def test_regex_entities_are_extracted_from_content():
    schema = load_schema(REFUND)
    entities = extract_entities(
        "Customer CUST-42 requested refund REF-9 for order ORD-123.",
        metadata={},
        schema=schema,
    )
    found = {(e.entity_type, e.value, e.source) for e in entities}
    assert ("customer", "CUST-42", "regex") in found
    assert ("refund", "REF-9", "regex") in found
    assert ("order", "ORD-123", "regex") in found


def test_metadata_wins_over_duplicate_regex(memory: EvidenceGatedMemory):
    ev = memory.record_evidence(
        evidence_type="order_record",
        source="order_api",
        source_system="order_api",
        content="Order ORD-123 is paid",
        metadata={"order_id": "ORD-123"},
    )
    order_entities = [e for e in ev.metadata["entities"] if e["entity_type"] == "order" and e["value"] == "ORD-123"]
    assert len(order_entities) == 1
    assert order_entities[0]["source"] == "metadata"


def test_llm_fallback_is_optional_annotation(tmp_path: Path):
    schema = {
        "name": "fallback_demo",
        "entities": [
            {"name": "ticket", "llm_fallback": True},
        ],
        "evidence_types": {
            "ticket_note": {
                "source_systems": ["helpdesk"],
            },
        },
        "claim_types": {
            "ticket_status": {
                "required_evidence": ["ticket_note"],
            },
        },
    }

    def fallback(content, entity_def, metadata):
        assert entity_def.name == "ticket"
        return ["TICK-7"]

    memory = EvidenceGatedMemory(tmp_path / "egm", schema, entity_fallback=fallback)
    try:
        ev = memory.record_evidence(
            evidence_type="ticket_note",
            source="helpdesk",
            source_system="helpdesk",
            content="The ticket is waiting on support.",
        )
    finally:
        memory.close()

    assert ev.metadata["entities"][0]["entity_type"] == "ticket"
    assert ev.metadata["entities"][0]["value"] == "TICK-7"
    assert ev.metadata["entities"][0]["source"] == "llm_fallback"
