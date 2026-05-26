from pathlib import Path

import pytest

from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.schemas.builtin import REFUND


@pytest.fixture
def memory(tmp_path: Path) -> EvidenceGatedMemory:
    m = EvidenceGatedMemory(workspace=tmp_path / "egm", domain_schema=REFUND)
    yield m
    m.close()
