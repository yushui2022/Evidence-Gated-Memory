"""Soft TaskState aggregation tests (M1 #21)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from evidence_gated_memory import EvidenceGatedMemory, TaskNodeStatus, TaskState
from evidence_gated_memory.storage.sqlite import SqliteStore


def test_task_with_no_nodes_is_open(memory: EvidenceGatedMemory) -> None:
    task = memory.create_task("task_empty", title="Empty workflow")

    assert task.current_state == TaskState.OPEN
    assert memory.get_task("task_empty").current_state == TaskState.OPEN


def test_pending_only_nodes_keep_task_open(memory: EvidenceGatedMemory) -> None:
    memory.create_task_node("task_pending", "step", "Waiting for work")

    task = memory.get_task("task_pending")
    assert task.current_state == TaskState.OPEN


def test_in_progress_node_sets_task_in_progress(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_working", "step", "Check order")

    memory.update_task_node_status(node.id, TaskNodeStatus.IN_PROGRESS)

    task = memory.get_task("task_working")
    assert task.current_state == TaskState.IN_PROGRESS


def test_blocked_node_takes_precedence(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_blocked", "step", "Check order")
    b = memory.create_task_node("task_blocked", "step", "Check payment")
    memory.update_task_node_status(a.id, TaskNodeStatus.IN_PROGRESS)

    memory.update_task_node_status(
        b.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing payment_record",
        suggested_action="call payment_api",
    )

    task = memory.get_task("task_blocked")
    assert task.current_state == TaskState.BLOCKED


def test_all_done_or_skipped_sets_task_done(memory: EvidenceGatedMemory) -> None:
    a = memory.create_task_node("task_done", "step", "Check order")
    b = memory.create_task_node("task_done", "step", "Optional fraud check")

    memory.update_task_node_status(a.id, TaskNodeStatus.DONE)
    assert memory.get_task("task_done").current_state == TaskState.OPEN

    memory.update_task_node_status(b.id, TaskNodeStatus.SKIPPED)

    task = memory.get_task("task_done")
    assert task.current_state == TaskState.DONE


def test_task_state_change_is_audited(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_audit_state", "step", "Check payment")

    memory.update_task_node_status(
        node.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing payment_record",
        suggested_action="call payment_api",
    )

    rows = [
        json.loads(row["detail"])
        for row in memory.store.list_audit(limit=200)
        if row["event_type"] == "task_state_changed"
    ]
    assert len(rows) == 1
    detail = rows[0]
    assert detail["task_id"] == "task_audit_state"
    assert detail["from_state"] == "open"
    assert detail["to_state"] == "blocked"
    assert detail["node_status_counts"] == {"blocked": 1}


def test_context_includes_current_task_state(memory: EvidenceGatedMemory) -> None:
    node = memory.create_task_node("task_ctx_state", "step", "Check payment")
    memory.update_task_node_status(
        node.id,
        TaskNodeStatus.BLOCKED,
        blocked_reason="missing payment_record",
    )

    ctx = memory.build_context(task_id="task_ctx_state")

    assert "<current_state>blocked</current_state>" in ctx


def test_sqlite_migrates_old_tasks_table_current_state(tmp_path: Path) -> None:
    workspace = tmp_path / "egm"
    workspace.mkdir()
    db_path = workspace / "egm.db"
    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                anchors TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL
            )"""
        )
        conn.execute(
            """INSERT INTO tasks(id, title, status, anchors, created_at, updated_at, metadata)
               VALUES (?,?,?,?,?,?,?)""",
            ("task_old", "Old workflow", "open", "{}", now, now, "{}"),
        )
        conn.commit()

    store = SqliteStore(workspace)
    try:
        columns = {
            row["name"]
            for row in store.conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        task = store.get_task("task_old")

        assert "current_state" in columns
        assert task.current_state == TaskState.OPEN
        assert store.get_schema_version() == 1
    finally:
        store.close()
