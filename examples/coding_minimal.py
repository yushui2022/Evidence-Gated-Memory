"""30-second coding-agent demo for Evidence-Gated Memory.

Run:

    python examples/coding_minimal.py

No API key is required. The demo shows a coding agent cannot claim file facts
or task completion until the required file/test evidence exists.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus, TaskStatus  # noqa: E402
from evidence_gated_memory.schemas.builtin import CODING  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="egm_coding_demo_") as tmp:
        memory = EvidenceGatedMemory(Path(tmp), CODING)
        try:
            task_id = "bugfix:auth-timeout"
            node = memory.create_task_node(
                task_id,
                "diagnosis",
                "Fix authentication timeout in src/auth/login.py",
                anchors={"file": "src/auth/login.py", "test": "tests/test_login.py"},
            )

            _title("EGM Coding Demo")

            _step("1. File claim without file evidence")
            file_claim = memory.assert_fact(
                "src/auth/login.py contains a hardcoded 5 second timeout",
                claim_type="file_content",
            )
            _print_assert("file_claim", file_claim)

            _step("2. Add file_read evidence")
            file_ref = memory.record_evidence(
                evidence_type="file_read",
                source="filesystem",
                source_system="filesystem",
                content=(
                    "def authenticate(user, password):\n"
                    "    timeout = 5\n"
                    "    return auth_client.login(user, password, timeout=timeout)\n"
                ),
                summary="src/auth/login.py contains timeout=5 in authenticate()",
                metadata={"file": "src/auth/login.py"},
            )
            file_fact = memory.assert_fact(
                "src/auth/login.py contains a hardcoded 5 second timeout",
                claim_type="file_content",
                evidence=[file_ref],
                metadata={"file": "src/auth/login.py"},
            )
            _print_assert("file_claim", file_fact)
            if file_fact.fact:
                memory.attach_fact_to_node(node.id, file_fact.fact.id)

            _step("3. Diagnosis without test evidence")
            diagnosis_without_test = memory.assert_fact(
                "The login timeout failure is caused by the hardcoded timeout",
                claim_type="error_diagnosis",
            )
            _print_assert("diagnosis_claim", diagnosis_without_test)

            _step("4. Add failing test_log evidence")
            failing_test = memory.record_evidence(
                evidence_type="test_log",
                source="pytest",
                source_system="test_runner",
                content="FAILED tests/test_login.py::test_login_timeout - took 5.2s, expected < 1.0s",
                summary="test_login_timeout failed: took 5.2s",
                metadata={"test": "tests/test_login.py::test_login_timeout"},
            )
            diagnosis = memory.assert_fact(
                "The login timeout failure is caused by the hardcoded timeout",
                claim_type="error_diagnosis",
                evidence=[failing_test],
            )
            _print_assert("diagnosis_claim", diagnosis)
            if diagnosis.fact:
                memory.attach_fact_to_node(node.id, diagnosis.fact.id)

            _step("5. Done claim without fresh completion evidence")
            done_without_test = memory.assert_fact(
                "auth-timeout bug fix is complete",
                claim_type="task_done",
            )
            _print_assert("done_claim", done_without_test)

            _step("6. Add fresh passing test_log evidence")
            passing_test = memory.record_evidence(
                evidence_type="test_log",
                source="pytest",
                source_system="test_runner",
                content="PASSED tests/test_login.py::test_login_timeout - completed in 0.3s",
                summary="test_login_timeout passed in 0.3s",
                metadata={"test": "tests/test_login.py::test_login_timeout"},
            )
            done = memory.assert_fact(
                "auth-timeout bug fix is complete",
                claim_type="task_done",
                evidence=[passing_test],
            )
            _print_assert("done_claim", done)
            if done.fact:
                memory.attach_fact_to_node(node.id, done.fact.id)

            transition = memory.transition_node(
                node.id,
                TaskNodeStatus.DONE,
                evidence=[passing_test],
            )
            _print_transition("task_transition", transition)
            memory.update_task_status(task_id, TaskStatus.DONE)

            _step("7. Final gated context")
            print(_compact_context(memory.build_context(query="auth-timeout", task_id=task_id, max_facts=4)))

            return 0 if done.accepted and transition.accepted else 1
        finally:
            memory.close()


def _title(text: str) -> None:
    print(text)
    print("=" * len(text))


def _step(text: str) -> None:
    print()
    print(f"[{text}]")


def _bool(value: object) -> str:
    return str(bool(value)).lower()


def _print_assert(label: str, result) -> None:
    print(f"{label}.accepted: {_bool(result.accepted)}")
    if result.fact:
        print(f"{label}.fact: {result.fact.id}")
    if not result.accepted:
        print(f"{label}.reason: {result.rejection_reason}")
        print(f"{label}.action: {result.suggested_action}")


def _print_transition(label: str, result) -> None:
    print(f"{label}.accepted: {_bool(result.accepted)}")
    print(f"{label}.status: {result.node.status.value}")
    if not result.accepted:
        print(f"{label}.reason: {result.rejection_reason}")
        print(f"{label}.action: {result.suggested_action}")


def _compact_context(context: str, max_lines: int = 24) -> str:
    lines = [line for line in context.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + ["..."])


if __name__ == "__main__":
    raise SystemExit(main())
