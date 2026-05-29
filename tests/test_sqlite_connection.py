from pathlib import Path

from evidence_gated_memory.storage.sqlite import SQLITE_BUSY_TIMEOUT_MS, SqliteStore


def test_sqlite_connection_uses_busy_timeout_and_wal(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "egm")
    try:
        busy_timeout = store.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        store.close()

    assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
    assert journal_mode.lower() == "wal"
