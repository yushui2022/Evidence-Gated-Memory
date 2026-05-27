"""Context builder long-term semantic memory tests."""

from __future__ import annotations

from evidence_gated_memory import EvidenceGatedMemory


def _seed_long_term_memory(memory: EvidenceGatedMemory):
    message = memory.record_conversation_message(
        "user",
        "RAW-L0-ONLY: never copy this raw sentence into prompt context.",
        session_id="session_ctx_ltm",
    )
    atom = memory.record_memory_atom(
        "instruction",
        "Refund completion requires fresh refund_api_response evidence.",
        source_messages=[message],
    )
    scenario = memory.record_memory_scenario(
        "Refund completion scenario",
        "Refund completion work needs a fresh refund API response.",
        atoms=[atom],
    )
    persona = memory.record_memory_persona(
        "Evidence-first refund operator",
        "Prefers refund completion claims backed by fresh API evidence.",
        scenarios=[scenario],
    )
    return message, atom, scenario, persona


def test_context_includes_relevant_long_term_memory(memory: EvidenceGatedMemory) -> None:
    message, atom, scenario, persona = _seed_long_term_memory(memory)
    unrelated_atom = memory.record_memory_atom(
        "persona",
        "User likes concise architecture handoffs.",
    )

    ctx = memory.build_context(query="refund completion")

    assert "<long_term_memory>" in ctx
    assert "[PERSONA] Evidence-first refund operator" in ctx
    assert f"id: {persona.id}" in ctx
    assert f"scenario_ids: ['{scenario.id}']" in ctx
    assert "[SCENARIO] Refund completion scenario" in ctx
    assert f"atom_ids: ['{atom.id}']" in ctx
    assert "[ATOM:instruction] Refund completion requires fresh refund_api_response evidence." in ctx
    assert f"source_message_ids: ['{message.id}']" in ctx

    # Context carries drill-down ids, not raw L0 conversation text.
    assert "RAW-L0-ONLY" not in ctx
    assert unrelated_atom.id not in ctx


def test_context_can_disable_long_term_memory(memory: EvidenceGatedMemory) -> None:
    _seed_long_term_memory(memory)

    ctx = memory.build_context(query="refund completion", include_long_term=False)

    assert "<long_term_memory>" not in ctx
    assert "Refund completion scenario" not in ctx


def test_context_respects_long_term_limits(memory: EvidenceGatedMemory) -> None:
    _seed_long_term_memory(memory)
    for idx in range(3):
        memory.record_memory_atom(
            "instruction",
            f"Refund completion auxiliary atom {idx}",
        )

    ctx = memory.build_context(
        query="refund completion",
        max_memory_atoms=1,
        max_memory_scenarios=0,
        max_memory_personas=0,
    )

    assert ctx.count("[ATOM:") == 1
    assert "[SCENARIO]" not in ctx
    assert "[PERSONA]" not in ctx
