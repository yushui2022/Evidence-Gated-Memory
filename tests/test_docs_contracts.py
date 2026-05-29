from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_long_term_candidate_gate_doc_preserves_core_contract() -> None:
    text = (REPO / "docs" / "long-term-candidate-gate.md").read_text(encoding="utf-8")

    required_phrases = [
        "Direct automatic L0 -> L1 promotion is forbidden.",
        "CandidateAtom",
        "source_spans",
        "quoted_text_hash",
        "CandidateGateResult",
        "promote",
        "pending_review",
        "reject",
        "memory_candidate_promoted",
        "Only promoted `MemoryAtom` records may enter `build_context()`.",
    ]
    for phrase in required_phrases:
        assert phrase in text
