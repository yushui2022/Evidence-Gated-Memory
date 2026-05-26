"""Long-term semantic memory foundation tests (M2 #29 first slice)."""

from __future__ import annotations

import json

import pytest

from evidence_gated_memory import EvidenceGatedMemory, MemoryAtomKind


def test_record_and_list_conversation_messages(memory: EvidenceGatedMemory) -> None:
    user = memory.record_conversation_message(
        "user",
        "We are designing an evidence-gated refund memory system.",
        session_id="session_A",
        metadata={"topic": "egm"},
    )
    assistant = memory.record_conversation_message(
        "assistant",
        "Keep TaskGraph separate from cross-session semantic memory.",
        session_id="session_A",
    )
    memory.record_conversation_message(
        "user",
        "Unrelated second session.",
        session_id="session_B",
    )

    session_a = memory.list_conversation_messages(session_id="session_A")

    assert [message.id for message in session_a] == [user.id, assistant.id]
    assert session_a[0].metadata == {"topic": "egm"}


def test_record_memory_atom_with_source_messages(memory: EvidenceGatedMemory) -> None:
    user = memory.record_conversation_message(
        "user",
        "For refunds, a payment record must exist before eligibility is trusted.",
    )
    assistant = memory.record_conversation_message(
        "assistant",
        "The gate should reject missing payment evidence with a suggested action.",
    )

    atom = memory.record_memory_atom(
        MemoryAtomKind.INSTRUCTION,
        "Refund eligibility claims need payment_record evidence and actionable rejection.",
        source_messages=[user, assistant.id],
        confidence=0.9,
        metadata={"domain": "refund"},
    )

    assert atom.kind == MemoryAtomKind.INSTRUCTION
    assert atom.source_message_ids == [user.id, assistant.id]
    assert atom.confidence == 0.9
    assert memory.list_memory_atoms()[0].metadata == {"domain": "refund"}


def test_record_memory_atom_rejects_missing_source_message(memory: EvidenceGatedMemory) -> None:
    with pytest.raises(KeyError, match="conversation message"):
        memory.record_memory_atom(
            "episodic",
            "This atom should not be stored because its source message is missing.",
            source_messages=["msg_does_not_exist"],
        )

    assert memory.list_memory_atoms() == []


def test_list_memory_atoms_filters_by_kind(memory: EvidenceGatedMemory) -> None:
    persona = memory.record_memory_atom("persona", "User prefers Chinese technical explanations.")
    instruction = memory.record_memory_atom(
        "instruction",
        "Do not auto-distill L1 atoms in the first #29 slice.",
    )
    episodic = memory.record_memory_atom(
        "episodic",
        "The project landed TaskGraph before long-term semantic memory.",
    )

    assert [atom.id for atom in memory.list_memory_atoms(kind="persona")] == [persona.id]
    assert [atom.id for atom in memory.list_memory_atoms(kind=MemoryAtomKind.INSTRUCTION)] == [
        instruction.id
    ]
    assert [atom.id for atom in memory.list_memory_atoms(kind="episodic")] == [episodic.id]


def test_search_memory_atoms_finds_relevant_text(memory: EvidenceGatedMemory) -> None:
    target = memory.record_memory_atom(
        "episodic",
        "Refund policy work uses hard anchors like order_id ORD-123 and ticket_id T-456.",
    )
    memory.record_memory_atom(
        "persona",
        "User prefers concise architecture handoffs.",
    )

    results = memory.search_memory_atoms("refund policy", limit=5)

    assert [atom.id for atom in results] == [target.id]


def test_memory_atom_record_writes_audit(memory: EvidenceGatedMemory) -> None:
    message = memory.record_conversation_message(
        "user",
        "Audit L1 memory atoms so promotion decisions are reviewable.",
    )

    atom = memory.record_memory_atom(
        "instruction",
        "Audit manually promoted long-term memory atoms.",
        source_messages=[message],
    )

    details = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == "memory_atom_recorded"
    ]

    assert len(details) == 1
    assert details[0]["atom_id"] == atom.id
    assert details[0]["source_message_ids"] == [message.id]


def test_record_memory_scenario_with_atoms(memory: EvidenceGatedMemory) -> None:
    user = memory.record_conversation_message(
        "user",
        "Refund agents must keep eligibility and completion checks separate.",
    )
    eligibility = memory.record_memory_atom(
        "instruction",
        "Refund eligibility needs order_record and payment_record evidence.",
        source_messages=[user],
    )
    completion = memory.record_memory_atom(
        "instruction",
        "Refund completion needs refund_api_response evidence.",
        source_messages=[user],
    )

    scenario = memory.record_memory_scenario(
        "Refund evidence-gating rules",
        "A refund workflow has separate eligibility and completion evidence gates.",
        atoms=[eligibility, completion.id],
        metadata={"domain": "refund"},
    )

    assert scenario.id.startswith("scene_")
    assert scenario.atom_ids == [eligibility.id, completion.id]
    assert scenario.metadata == {"domain": "refund"}
    assert memory.get_memory_scenario(scenario.id).atom_ids == scenario.atom_ids
    assert memory.get_memory_atom(scenario.atom_ids[0]).source_message_ids == [user.id]
    assert memory.get_conversation_message(user.id).content.startswith("Refund agents")
    assert [scene.id for scene in memory.list_memory_scenarios()] == [scenario.id]


def test_record_memory_scenario_requires_source_atoms(memory: EvidenceGatedMemory) -> None:
    with pytest.raises(ValueError, match="requires at least one source atom"):
        memory.record_memory_scenario(
            "Ungrounded scenario",
            "This should be rejected because it points to no L1 atoms.",
            atoms=[],
        )

    assert memory.list_memory_scenarios() == []


def test_record_memory_scenario_rejects_missing_atom(memory: EvidenceGatedMemory) -> None:
    atom = memory.record_memory_atom(
        "episodic",
        "A real atom that should not mask the missing one.",
    )

    with pytest.raises(KeyError, match="memory atom"):
        memory.record_memory_scenario(
            "Partially grounded scenario",
            "This should be rejected because one atom id is missing.",
            atoms=[atom, "atom_does_not_exist"],
        )

    assert memory.list_memory_scenarios() == []


def test_search_memory_scenarios_finds_relevant_summary(memory: EvidenceGatedMemory) -> None:
    target_atom = memory.record_memory_atom(
        "episodic",
        "Refund escalation work uses ticket_id T-456 as the hard anchor.",
    )
    other_atom = memory.record_memory_atom(
        "persona",
        "User prefers concise architecture handoffs.",
    )
    target = memory.record_memory_scenario(
        "Refund escalation scenario",
        "Scenario for refund escalation workflows keyed by ticket_id and order_id.",
        atoms=[target_atom],
    )
    memory.record_memory_scenario(
        "Architecture handoff scenario",
        "Scenario for preserving project implementation decisions.",
        atoms=[other_atom],
    )

    results = memory.search_memory_scenarios("refund escalation", limit=5)

    assert [scene.id for scene in results] == [target.id]


def test_memory_scenario_record_writes_audit(memory: EvidenceGatedMemory) -> None:
    atom = memory.record_memory_atom(
        "instruction",
        "Scenario promotion decisions should be auditable.",
    )

    scenario = memory.record_memory_scenario(
        "Audit scenario",
        "Audit manually promoted L2 scenarios.",
        atoms=[atom],
    )

    details = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == "memory_scenario_recorded"
    ]

    assert len(details) == 1
    assert details[0]["scenario_id"] == scenario.id
    assert details[0]["atom_ids"] == [atom.id]


def test_record_memory_persona_with_scenarios(memory: EvidenceGatedMemory) -> None:
    message = memory.record_conversation_message(
        "user",
        "The user studies evidence-gated graph memory for enterprise agents.",
    )
    atom = memory.record_memory_atom(
        "persona",
        "User cares about hard-anchor enterprise agent memory.",
        source_messages=[message],
    )
    scenario = memory.record_memory_scenario(
        "Enterprise memory research",
        "The user is designing EGM around hard anchors, refs, and gates.",
        atoms=[atom],
    )

    persona = memory.record_memory_persona(
        "EGM project maintainer",
        "User prefers evidence-first architecture and careful handoff notes.",
        scenarios=[scenario],
        metadata={"language": "zh-CN"},
    )

    assert persona.id.startswith("persona_")
    assert persona.scenario_ids == [scenario.id]
    assert persona.metadata == {"language": "zh-CN"}
    assert memory.get_memory_persona(persona.id).scenario_ids == [scenario.id]
    assert memory.get_memory_scenario(persona.scenario_ids[0]).atom_ids == [atom.id]
    assert memory.get_memory_atom(atom.id).source_message_ids == [message.id]
    assert [profile.id for profile in memory.list_memory_personas()] == [persona.id]


def test_record_memory_persona_requires_source_scenarios(memory: EvidenceGatedMemory) -> None:
    with pytest.raises(ValueError, match="requires at least one source scenario"):
        memory.record_memory_persona(
            "Ungrounded persona",
            "This should be rejected because it points to no L2 scenarios.",
            scenarios=[],
        )

    assert memory.list_memory_personas() == []


def test_record_memory_persona_rejects_missing_scenario(memory: EvidenceGatedMemory) -> None:
    atom = memory.record_memory_atom(
        "episodic",
        "A real atom for a real scenario.",
    )
    scenario = memory.record_memory_scenario(
        "Real scenario",
        "A valid source scenario.",
        atoms=[atom],
    )

    with pytest.raises(KeyError, match="memory scenario"):
        memory.record_memory_persona(
            "Partially grounded persona",
            "This should be rejected because one scenario id is missing.",
            scenarios=[scenario, "scene_does_not_exist"],
        )

    assert memory.list_memory_personas() == []


def test_search_memory_personas_finds_relevant_summary(memory: EvidenceGatedMemory) -> None:
    target_atom = memory.record_memory_atom(
        "persona",
        "User values auditability and evidence gates.",
    )
    target_scenario = memory.record_memory_scenario(
        "Auditability scenario",
        "The user repeatedly asks for audit logs and guarded state changes.",
        atoms=[target_atom],
    )
    other_atom = memory.record_memory_atom(
        "persona",
        "User likes concise architecture handoffs.",
    )
    other_scenario = memory.record_memory_scenario(
        "Handoff scenario",
        "The user wants README status sections kept current.",
        atoms=[other_atom],
    )
    target = memory.record_memory_persona(
        "Evidence-first maintainer",
        "A profile centered on auditability, evidence gates, and rejection clarity.",
        scenarios=[target_scenario],
    )
    memory.record_memory_persona(
        "Documentation maintainer",
        "A profile centered on handoff notes and project status.",
        scenarios=[other_scenario],
    )

    results = memory.search_memory_personas("auditability evidence", limit=5)

    assert [profile.id for profile in results] == [target.id]


def test_memory_persona_record_writes_audit(memory: EvidenceGatedMemory) -> None:
    atom = memory.record_memory_atom(
        "persona",
        "Persona promotion decisions should be auditable.",
    )
    scenario = memory.record_memory_scenario(
        "Persona audit scenario",
        "Audit manually promoted L3 personas.",
        atoms=[atom],
    )

    persona = memory.record_memory_persona(
        "Audit persona",
        "Audit manually promoted L3 personas.",
        scenarios=[scenario],
    )

    details = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=300)
        if row["event_type"] == "memory_persona_recorded"
    ]

    assert len(details) == 1
    assert details[0]["persona_id"] == persona.id
    assert details[0]["scenario_ids"] == [scenario.id]
