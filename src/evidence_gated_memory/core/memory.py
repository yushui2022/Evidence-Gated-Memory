"""EvidenceGatedMemory — the public entry point.

Two API surfaces:

  * Easy:    `assert_fact(text, claim_type, evidence=[...])`
             one call: propose → gate → commit (or reject with actionable feedback)

  * Detailed: propose_claim → check_gate → commit_fact(claim, gate_result)
             for advanced users who want to insert custom logic between steps
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from evidence_gated_memory.core.context import build_context
from evidence_gated_memory.core.entities import EntityFallback, ExtractedEntity, extract_entities
from evidence_gated_memory.core.freshness import freshness_of, is_usable
from evidence_gated_memory.core.gates import check_gate, check_state_transition_gate
from evidence_gated_memory.core.mermaid import render_mermaid
from evidence_gated_memory.core.models import (
    AssertResult,
    Claim,
    ConversationMessage,
    Evidence,
    Event,
    Fact,
    FactKind,
    Freshness,
    GateResult,
    MemoryAtom,
    MemoryAtomKind,
    MemoryPersona,
    MemoryScenario,
    OffloadRecord,
    Task,
    TaskEdge,
    TaskEdgeKind,
    TaskNode,
    TaskNodeStatus,
    TaskStatus,
    TransitionGateResult,
    TransitionResult,
    derive_task_state,
)
from evidence_gated_memory.schemas.loader import DomainSchema, load_schema, load_schema_dict
from evidence_gated_memory.storage.sqlite import SqliteStore


SchemaInput = Union[str, Path, dict, DomainSchema]


def _resolve_schema(schema: SchemaInput) -> DomainSchema:
    if isinstance(schema, DomainSchema):
        return schema
    if isinstance(schema, dict):
        return load_schema_dict(schema)
    return load_schema(schema)


class EvidenceGatedMemory:
    """Provenance-first memory layer.

    Sync API (SQLite is cheap enough that async wrapping adds complexity without speedup at v0.1).
    """

    def __init__(
        self,
        workspace: str | Path,
        domain_schema: SchemaInput,
        *,
        entity_fallback: Optional[EntityFallback] = None,
    ):
        self.workspace = Path(workspace)
        self.schema = _resolve_schema(domain_schema)
        self.entity_fallback = entity_fallback
        self.store = SqliteStore(self.workspace)

    def close(self) -> None:
        self.store.close()

    # ---------- L0: events & evidence ----------

    def record_event(self, role: str, content: str, **metadata: Any) -> Event:
        event = Event(role=role, content=content, metadata=metadata)
        self.store.insert_event(event)
        return event

    # ---------- Long-term memory: L0 conversation / L1 atoms ----------

    def record_conversation_message(
        self,
        role: str,
        content: str,
        *,
        session_id: str = "default",
        metadata: Optional[dict[str, Any]] = None,
    ) -> ConversationMessage:
        """Record a raw user/assistant message for cross-session memory.

        This is storage only. EGM does not auto-distill L1 atoms here; callers
        decide which conversation messages deserve promotion.
        """
        message = ConversationMessage(
            role=role,
            content=content,
            session_id=session_id,
            metadata=metadata or {},
        )
        self.store.insert_conversation_message(message)
        return message

    def list_conversation_messages(
        self,
        session_id: Optional[str] = None,
    ) -> list[ConversationMessage]:
        return self.store.list_conversation_messages(session_id=session_id)

    def get_conversation_message(self, message_id: str) -> Optional[ConversationMessage]:
        return self.store.get_conversation_message(message_id)

    def record_memory_atom(
        self,
        kind: Union[MemoryAtomKind, str],
        text: str,
        *,
        source_messages: Optional[list[Union[str, ConversationMessage]]] = None,
        confidence: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryAtom:
        """Record a manually curated L1 atom grounded in L0 messages."""
        source_ids = [
            message.id if isinstance(message, ConversationMessage) else message
            for message in (source_messages or [])
        ]
        existing = self.store.get_conversation_messages_many(source_ids)
        existing_ids = {message.id for message in existing}
        missing = [message_id for message_id in source_ids if message_id not in existing_ids]
        if missing:
            raise KeyError(f"conversation message(s) not found: {missing}")

        atom = MemoryAtom(
            kind=MemoryAtomKind(kind),
            text=text,
            source_message_ids=source_ids,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.store.insert_memory_atom(atom)
        self.store.append_audit(
            event_type="memory_atom_recorded",
            detail={
                "atom_id": atom.id,
                "kind": atom.kind.value,
                "source_message_ids": source_ids,
                "confidence": confidence,
            },
        )
        return atom

    def list_memory_atoms(
        self,
        kind: Optional[Union[MemoryAtomKind, str]] = None,
    ) -> list[MemoryAtom]:
        resolved_kind = MemoryAtomKind(kind) if kind is not None else None
        return self.store.list_memory_atoms(kind=resolved_kind)

    def get_memory_atom(self, atom_id: str) -> Optional[MemoryAtom]:
        return self.store.get_memory_atom(atom_id)

    def search_memory_atoms(self, query: str, limit: int = 10) -> list[MemoryAtom]:
        return self.store.search_memory_atoms(query=query, limit=limit)

    def record_memory_scenario(
        self,
        title: str,
        summary: str,
        *,
        atoms: list[Union[str, MemoryAtom]],
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryScenario:
        """Record a manually curated L2 scenario grounded in L1 atoms."""
        atom_ids = [atom.id if isinstance(atom, MemoryAtom) else atom for atom in atoms]
        if not atom_ids:
            raise ValueError("memory scenario requires at least one source atom")

        existing = self.store.get_memory_atoms_many(atom_ids)
        existing_ids = {atom.id for atom in existing}
        missing = [atom_id for atom_id in atom_ids if atom_id not in existing_ids]
        if missing:
            raise KeyError(f"memory atom(s) not found: {missing}")

        scenario = MemoryScenario(
            title=title,
            summary=summary,
            atom_ids=atom_ids,
            metadata=metadata or {},
        )
        self.store.insert_memory_scenario(scenario)
        self.store.append_audit(
            event_type="memory_scenario_recorded",
            detail={
                "scenario_id": scenario.id,
                "title": title,
                "atom_ids": atom_ids,
            },
        )
        return scenario

    def get_memory_scenario(self, scenario_id: str) -> Optional[MemoryScenario]:
        return self.store.get_memory_scenario(scenario_id)

    def list_memory_scenarios(self) -> list[MemoryScenario]:
        return self.store.list_memory_scenarios()

    def search_memory_scenarios(self, query: str, limit: int = 10) -> list[MemoryScenario]:
        return self.store.search_memory_scenarios(query=query, limit=limit)

    def record_memory_persona(
        self,
        name: str,
        summary: str,
        *,
        scenarios: list[Union[str, MemoryScenario]],
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryPersona:
        """Record a manually curated L3 persona grounded in L2 scenarios."""
        scenario_ids = [
            scenario.id if isinstance(scenario, MemoryScenario) else scenario
            for scenario in scenarios
        ]
        if not scenario_ids:
            raise ValueError("memory persona requires at least one source scenario")

        existing = self.store.get_memory_scenarios_many(scenario_ids)
        existing_ids = {scenario.id for scenario in existing}
        missing = [
            scenario_id for scenario_id in scenario_ids
            if scenario_id not in existing_ids
        ]
        if missing:
            raise KeyError(f"memory scenario(s) not found: {missing}")

        persona = MemoryPersona(
            name=name,
            summary=summary,
            scenario_ids=scenario_ids,
            metadata=metadata or {},
        )
        self.store.insert_memory_persona(persona)
        self.store.append_audit(
            event_type="memory_persona_recorded",
            detail={
                "persona_id": persona.id,
                "name": name,
                "scenario_ids": scenario_ids,
            },
        )
        return persona

    def get_memory_persona(self, persona_id: str) -> Optional[MemoryPersona]:
        return self.store.get_memory_persona(persona_id)

    def list_memory_personas(self) -> list[MemoryPersona]:
        return self.store.list_memory_personas()

    def search_memory_personas(self, query: str, limit: int = 10) -> list[MemoryPersona]:
        return self.store.search_memory_personas(query=query, limit=limit)

    def record_evidence(
        self,
        evidence_type: str,
        source: str,
        content: str,
        *,
        summary: str = "",
        source_system: Optional[str] = None,
        risk_level: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
        stale_after_seconds: Optional[int] = None,
        expired_after_seconds: Optional[int] = None,
    ) -> Evidence:
        type_def = self.schema.evidence_type(evidence_type)
        if type_def is None:
            raise ValueError(
                f"unknown evidence_type '{evidence_type}'; declare it in the domain schema"
            )
        resolved_risk = risk_level or type_def.risk
        resolved_metadata = dict(metadata or {})
        entities = extract_entities(content, resolved_metadata, self.schema, self.entity_fallback)
        if entities:
            resolved_metadata["entities"] = [e.model_dump() for e in entities]

        ev = Evidence(
            evidence_type=evidence_type,
            source=source,
            source_system=source_system or source,
            risk_level=resolved_risk,
            summary=summary or _auto_summary(content),
            observed_at=observed_at or datetime.now(timezone.utc),
            metadata=resolved_metadata,
            stale_after_seconds=stale_after_seconds,
            expired_after_seconds=expired_after_seconds,
        )
        ev.content_path = self.store.write_ref_content(ev.id, content)
        self.store.insert_evidence(ev)
        return ev

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self.store.get_evidence(evidence_id)

    def read_ref(self, evidence_id: str) -> str:
        return self.store.read_ref_content(evidence_id)

    def extract_entities(
        self,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[ExtractedEntity]:
        return extract_entities(content, metadata or {}, self.schema, self.entity_fallback)

    # ---------- Offload JSONL: tool result summary index ----------

    def record_offload(
        self,
        *,
        task_id: str,
        node_id: str,
        tool_call_id: str,
        result_ref: Union[str, Evidence],
        summary: str,
        score: int = 5,
        metadata: Optional[dict[str, Any]] = None,
    ) -> OffloadRecord:
        """Index a heavy tool result without turning it into a TaskNode.

        `result_ref` must point to an existing Evidence ref. The target node
        must exist and belong to `task_id`. On success, the evidence is attached
        to the node so the TaskGraph remains drill-downable.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")
        if node.task_id != task_id:
            raise ValueError(
                f"offload task_id does not match node task_id: {task_id} != {node.task_id}"
            )

        evidence_id = result_ref.id if isinstance(result_ref, Evidence) else result_ref
        if self.store.get_evidence(evidence_id) is None:
            raise KeyError(f"evidence not found: {evidence_id}")

        record = OffloadRecord(
            task_id=task_id,
            node_id=node_id,
            tool_call_id=tool_call_id,
            result_ref=evidence_id,
            summary=summary,
            score=score,
            metadata=metadata or {},
        )
        self.store.append_offload_record(record)
        self.attach_evidence_to_node(node_id, evidence_id)
        self.store.append_audit(
            event_type="offload_recorded",
            detail={
                "offload_id": record.id,
                "task_id": task_id,
                "node_id": node_id,
                "tool_call_id": tool_call_id,
                "result_ref": evidence_id,
                "score": score,
            },
        )
        return record

    def list_offloads(
        self,
        *,
        task_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> list[OffloadRecord]:
        return self.store.list_offload_records(task_id=task_id, node_id=node_id)

    # ---------- Task Graph ----------

    def create_task(
        self,
        task_id: str,
        title: str = "",
        *,
        anchors: Optional[dict[str, str]] = None,
        status: TaskStatus = TaskStatus.OPEN,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Task:
        """Create-or-update the workflow-level Task row.

        Most callers don't need to call this directly — `create_task_node`
        auto-creates a Task on first sight of a new `task_id`. Use this when
        you want to set the workflow title/anchors up-front. Prefer
        `update_task_status()` when only the explicit lifecycle status changes.
        """
        existing = self.store.get_task(task_id)
        if existing is None:
            task = Task(
                id=task_id,
                title=title,
                status=status,
                anchors=anchors or {},
                metadata=metadata or {},
            )
            self.store.upsert_task(task)
            self.store.append_audit(
                event_type="task_created",
                detail={
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "anchors": task.anchors,
                },
            )
            return task

        prev_status = existing.status
        if title:
            existing.title = title
        if anchors is not None:
            existing.anchors = anchors
        if metadata is not None:
            existing.metadata = metadata
        existing.status = status
        existing.updated_at = datetime.now(timezone.utc)
        self.store.upsert_task(existing)
        if prev_status != status:
            self.store.append_audit(
                event_type="task_status_changed",
                detail={
                    "task_id": existing.id,
                    "from_status": prev_status.value,
                    "to_status": status.value,
                },
            )
        return existing

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.store.get_task(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        return self.store.list_tasks(status=status)

    def update_task_status(self, task_id: str, status: Union[TaskStatus, str]) -> Task:
        """Set a Task's explicit lifecycle status.

        This is separate from `current_state`, which is derived from child
        TaskNode statuses by `refresh_task_state()`. For example, a cancelled
        task can still have child nodes whose last derived state was blocked.
        """
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")

        next_status = status if isinstance(status, TaskStatus) else TaskStatus(status)
        prev_status = task.status
        task.status = next_status
        task.updated_at = datetime.now(timezone.utc)
        self.store.upsert_task(task)
        if prev_status != next_status:
            self.store.append_audit(
                event_type="task_status_changed",
                detail={
                    "task_id": task.id,
                    "from_status": prev_status.value,
                    "to_status": next_status.value,
                },
            )
        return task

    def refresh_task_state(
        self,
        task_id: str,
        *,
        reason: str = "task graph changed",
    ) -> Task:
        """Recompute a Task's derived soft state from its child nodes.

        This is a snapshot refresh, not a gated state-transition API. The
        production transition gate lands later in `transition_node()` (#31).
        """
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")

        nodes = self.store.list_task_nodes(task_id=task_id)
        prev_state = task.current_state
        next_state = derive_task_state(node.status for node in nodes)

        task.current_state = next_state
        task.updated_at = datetime.now(timezone.utc)
        self.store.upsert_task(task)

        if prev_state != next_state:
            self.store.append_audit(
                event_type="task_state_changed",
                detail={
                    "task_id": task.id,
                    "from_state": prev_state.value,
                    "to_state": next_state.value,
                    "reason": reason,
                    "node_status_counts": _task_node_status_counts(nodes),
                },
            )
        return task

    def _ensure_task(self, task_id: str, *, anchors: Optional[dict[str, str]] = None) -> Task:
        """Back-compat: if a node is created against an unknown task_id,
        materialise the workflow row on the fly so the graph stays consistent."""
        existing = self.store.get_task(task_id)
        if existing is not None:
            return existing
        task = Task(id=task_id, title=task_id, anchors=anchors or {})
        self.store.upsert_task(task)
        self.store.append_audit(
            event_type="task_auto_created",
            detail={
                "task_id": task.id,
                "reason": "first task_node for this task_id",
                "anchors": task.anchors,
            },
        )
        return task

    def create_task_node(
        self,
        task_id: str,
        node_type: str,
        title: str,
        *,
        anchors: Optional[dict[str, str]] = None,
        parent_id: Optional[str] = None,
        status: TaskNodeStatus = TaskNodeStatus.PENDING,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TaskNode:
        if parent_id is not None:
            parent = self.store.get_task_node(parent_id)
            if parent is None:
                raise KeyError(f"parent task node not found: {parent_id}")
            if parent.task_id != task_id:
                raise ValueError(
                    f"cross-task parent_id is not allowed: {parent.task_id} != {task_id}"
                )
        # Materialise the workflow row after validating parent_id so invalid
        # cross-task children do not create orphan top-level Task rows.
        self._ensure_task(task_id, anchors=anchors)
        node = TaskNode(
            task_id=task_id,
            node_type=node_type,
            title=title,
            status=status,
            anchors=anchors or {},
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self.store.insert_task_node(node)
        self.store.append_audit(
            event_type="task_node_created",
            detail={
                "node_id": node.id,
                "task_id": node.task_id,
                "node_type": node.node_type,
                "title": node.title,
                "status": node.status.value,
                "anchors": node.anchors,
                "parent_id": node.parent_id,
            },
        )
        self.refresh_task_state(task_id, reason=f"task_node_created:{node.id}")
        return node

    def get_task_node(self, node_id: str) -> Optional[TaskNode]:
        return self.store.get_task_node(node_id)

    def list_task_nodes(
        self,
        task_id: Optional[str] = None,
        status: Optional[TaskNodeStatus] = None,
    ) -> list[TaskNode]:
        return self.store.list_task_nodes(task_id=task_id, status=status)

    def update_task_node_status(
        self,
        node_id: str,
        status: TaskNodeStatus,
        *,
        blocked_reason: Optional[str] = None,
        suggested_action: Optional[str] = None,
    ) -> TaskNode:
        """Low-level CRUD for a node's status field.

        This is **not** the gated business API. It mutates the node's status
        directly without consulting any quality gate. Use it for setup,
        recovery, or tests. The gated counterpart is `transition_node()`
        which enforces schema-defined transition rules.

        `blocked_reason` and `suggested_action` are only persisted while the
        target status is BLOCKED. Passing them with any other status is accepted
        but they are cleared before the node is stored; the prior BLOCKED
        context remains available in the audit entry.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")
        prev_status = node.status
        prev_blocked_reason = node.blocked_reason
        prev_suggested_action = node.suggested_action

        node.status = status
        if blocked_reason is not None:
            node.blocked_reason = blocked_reason
        if suggested_action is not None:
            node.suggested_action = suggested_action
        if status != TaskNodeStatus.BLOCKED:
            # leaving BLOCKED clears the current node's reason/action so the
            # snapshot reflects the new state; the previous values are
            # preserved in the audit entry below.
            node.blocked_reason = None
            node.suggested_action = None
        node.updated_at = datetime.now(timezone.utc)
        self.store.update_task_node(node)

        self.store.append_audit(
            event_type="task_node_status_changed",
            detail={
                "node_id": node.id,
                "task_id": node.task_id,
                "from_status": prev_status.value,
                "to_status": node.status.value,
                "prev_blocked_reason": prev_blocked_reason,
                "prev_suggested_action": prev_suggested_action,
                "new_blocked_reason": node.blocked_reason,
                "new_suggested_action": node.suggested_action,
            },
        )
        self.refresh_task_state(node.task_id, reason=f"task_node_status_changed:{node.id}")
        return node

    def check_node_transition_gate(
        self,
        node_id: str,
        to_status: TaskNodeStatus,
        *,
        evidence: Optional[list[Union[str, Evidence]]] = None,
    ) -> TransitionGateResult:
        """Check whether a node may move to `to_status` under schema gates.

        Read-only: this writes a gate-check audit entry but does not update
        the node. `transition_node()` (#31) will be the mutating business API.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")

        explicit_refs = [
            e.id if isinstance(e, Evidence) else e
            for e in (evidence or [])
        ]
        support_refs = _dedupe(list(node.evidence_refs) + explicit_refs)
        evs, missing_evidence_refs = self._resolve_evidence_refs(support_refs)
        result = check_state_transition_gate(
            node,
            to_status,
            evs,
            self.schema,
            missing_evidence_refs=missing_evidence_refs,
        )
        self.store.append_audit(
            event_type="state_gate_check",
            accepted=result.accepted,
            detail={
                "node_id": node.id,
                "task_id": node.task_id,
                "from_status": result.from_status.value,
                "to_status": result.to_status.value,
                "evidence_refs": support_refs,
                "violations": [v.model_dump() for v in result.violations],
            },
        )
        return result

    def transition_node(
        self,
        node_id: str,
        to_status: TaskNodeStatus,
        *,
        evidence: Optional[list[Union[str, Evidence]]] = None,
        blocked_reason: Optional[str] = None,
        suggested_action: Optional[str] = None,
    ) -> TransitionResult:
        """Gated business API for moving a TaskNode to a new status.

        Unlike `update_task_node_status`, this first runs schema-defined
        transition gates. Rejected transitions do not mutate the node.
        Accepted transitions attach any supplied evidence refs before the
        status change so the graph remains drill-downable.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")

        gate = self.check_node_transition_gate(
            node_id,
            to_status,
            evidence=evidence,
        )
        if not gate.accepted:
            return TransitionResult(accepted=False, node=node, gate=gate)

        for item in evidence or []:
            evidence_id = item.id if isinstance(item, Evidence) else item
            self.attach_evidence_to_node(node_id, evidence_id)

        updated = self.update_task_node_status(
            node_id,
            to_status,
            blocked_reason=blocked_reason,
            suggested_action=suggested_action,
        )
        return TransitionResult(accepted=True, node=updated, gate=gate)

    def attach_evidence_to_node(self, node_id: str, evidence_id: str) -> TaskNode:
        """Link an evidence ref to a task node.

        The evidence must already exist in the store — attaching a phantom ref
        would silently break the drill-down promise. Raises KeyError otherwise.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")
        if self.store.get_evidence(evidence_id) is None:
            raise KeyError(f"evidence not found: {evidence_id}")
        if evidence_id not in node.evidence_refs:
            node.evidence_refs.append(evidence_id)
            node.updated_at = datetime.now(timezone.utc)
            self.store.update_task_node(node)
            self.store.update_evidence_node_id(evidence_id, node.id)
            self.store.append_audit(
                event_type="task_node_evidence_attached",
                detail={
                    "node_id": node.id,
                    "task_id": node.task_id,
                    "evidence_id": evidence_id,
                },
            )
        return node

    def attach_fact_to_node(self, node_id: str, fact_id: str) -> TaskNode:
        """Link a gated fact to a task node.

        The fact must already exist and still be active (not invalidated).
        Attaching a phantom or invalidated fact would break EGM's promise
        that a node's fact_refs are always drillable to live evidence.
        """
        node = self.store.get_task_node(node_id)
        if node is None:
            raise KeyError(f"task node not found: {node_id}")
        fact = self.store.get_fact(fact_id)
        if fact is None:
            raise KeyError(f"fact not found: {fact_id}")
        if fact.invalidated_at is not None:
            raise ValueError(
                f"cannot attach invalidated fact {fact_id} "
                f"(reason: {fact.invalidation_reason})"
            )
        if fact_id not in node.fact_refs:
            node.fact_refs.append(fact_id)
            node.updated_at = datetime.now(timezone.utc)
            self.store.update_task_node(node)
            self.store.update_fact_node_id(fact_id, node.id)
            self.store.append_audit(
                event_type="task_node_fact_attached",
                detail={
                    "node_id": node.id,
                    "task_id": node.task_id,
                    "fact_id": fact_id,
                },
            )
        return node

    def add_task_edge(
        self,
        src_node_id: str,
        dst_node_id: str,
        *,
        kind: TaskEdgeKind = TaskEdgeKind.DEPENDS_ON,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TaskEdge:
        """Create a typed edge between two existing nodes.

        Both endpoints must exist (no phantom refs) and must belong to the
        same workflow — cross-task edges would muddy the per-task projection
        used by render_mermaid / build_context. Self-loops and multi-node
        cycles are rejected.
        """
        src = self.store.get_task_node(src_node_id)
        if src is None:
            raise KeyError(f"task node not found: {src_node_id}")
        dst = self.store.get_task_node(dst_node_id)
        if dst is None:
            raise KeyError(f"task node not found: {dst_node_id}")
        if src.task_id != dst.task_id:
            raise ValueError(
                f"cross-task edges are not allowed: {src.task_id} != {dst.task_id}"
            )
        if src_node_id == dst_node_id:
            raise ValueError("self-loop edges are not allowed")
        existing_edges = self.store.list_task_edges(task_id=src.task_id)
        if _task_edge_would_create_cycle(src_node_id, dst_node_id, existing_edges):
            raise ValueError(
                f"cycle edges are not allowed: adding {src_node_id} -> {dst_node_id} "
                "would make the TaskGraph cyclic"
            )

        edge = TaskEdge(
            task_id=src.task_id,
            src_node_id=src_node_id,
            dst_node_id=dst_node_id,
            kind=kind,
            metadata=metadata or {},
        )
        self.store.insert_task_edge(edge)
        self.store.append_audit(
            event_type="task_edge_added",
            detail={
                "edge_id": edge.id,
                "task_id": edge.task_id,
                "src": src_node_id,
                "dst": dst_node_id,
                "kind": kind.value,
            },
        )
        return edge

    def list_task_edges(
        self,
        task_id: Optional[str] = None,
        src_node_id: Optional[str] = None,
        dst_node_id: Optional[str] = None,
    ) -> list[TaskEdge]:
        return self.store.list_task_edges(
            task_id=task_id, src_node_id=src_node_id, dst_node_id=dst_node_id,
        )

    def render_task_graph(
        self,
        task_id: Optional[str] = None,
        status: Optional[TaskNodeStatus] = None,
    ) -> str:
        """Render the current TaskGraph as a Mermaid `flowchart TD` block.

        Filters compose: pass `task_id` to scope to one workflow, `status` to
        focus on (say) only BLOCKED nodes. The output is a string ready to
        drop into a prompt's `<task_map>` slot.
        """
        nodes = self.store.list_task_nodes(task_id=task_id, status=status)
        # Only fetch edges when we're scoped to a single task — global edge
        # rendering across tasks is meaningless (cross-task edges aren't allowed).
        edges = self.store.list_task_edges(task_id=task_id) if task_id else []
        return render_mermaid(nodes, edges=edges)

    # ---------- L1: claim → fact ----------

    def propose_claim(
        self,
        text: str,
        claim_type: str,
        *,
        kind: FactKind = FactKind.OBSERVED,
        evidence: Optional[list[Union[str, Evidence]]] = None,
        depends_on: Optional[list[Union[str, Fact]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Claim:
        if self.schema.claim_type(claim_type) is None:
            raise ValueError(
                f"unknown claim_type '{claim_type}'; declare it in the domain schema"
            )
        evidence_refs = [e.id if isinstance(e, Evidence) else e for e in (evidence or [])]
        dep_ids = [f.id if isinstance(f, Fact) else f for f in (depends_on or [])]
        claim = Claim(
            text=text,
            claim_type=claim_type,
            kind=kind,
            evidence_refs=evidence_refs,
            depends_on=dep_ids,
            metadata=metadata or {},
        )
        self.store.insert_claim(claim)
        return claim

    def check_gate(self, claim: Claim) -> GateResult:
        support_refs = self._support_evidence_refs_for_claim(claim)
        evs, missing_evidence_refs = self._resolve_evidence_refs(support_refs)
        parents, missing_depends_on = self._resolve_fact_refs(claim.depends_on)
        result = check_gate(
            claim,
            evs,
            parents,
            self.schema,
            missing_evidence_refs=missing_evidence_refs,
            missing_depends_on=missing_depends_on,
        )

        self.store.append_audit(
            event_type="gate_check",
            claim_id=claim.id,
            accepted=result.accepted,
            detail={
                "claim_type": claim.claim_type,
                "violations": [v.model_dump() for v in result.violations],
            },
        )
        return result

    def commit_fact(self, claim: Claim, gate_result: Optional[GateResult] = None) -> Fact:
        if gate_result is None:
            raise ValueError("commit_fact requires an accepted GateResult; use assert_fact for the safe one-shot path")
        if gate_result.claim_id != claim.id:
            raise ValueError("GateResult does not belong to this claim")
        if not gate_result.accepted:
            raise ValueError(f"cannot commit a rejected claim: {gate_result.rejection_reason}")

        fact = Fact(
            claim_id=claim.id,
            text=claim.text,
            claim_type=claim.claim_type,
            kind=claim.kind,
            evidence_refs=self._support_evidence_refs_for_claim(claim),
            depends_on=list(claim.depends_on),
            metadata=dict(claim.metadata),
        )
        self.store.insert_fact(fact)
        self.store.append_audit(
            event_type="fact_committed",
            claim_id=claim.id,
            fact_id=fact.id,
            accepted=True,
            detail={"claim_type": claim.claim_type, "text": claim.text},
        )
        return fact

    def assert_fact(
        self,
        text: str,
        claim_type: str,
        *,
        kind: FactKind = FactKind.OBSERVED,
        evidence: Optional[list[Union[str, Evidence]]] = None,
        depends_on: Optional[list[Union[str, Fact]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AssertResult:
        """One-shot: propose → gate → (commit | reject with actionable feedback)."""
        claim = self.propose_claim(
            text=text,
            claim_type=claim_type,
            kind=kind,
            evidence=evidence,
            depends_on=depends_on,
            metadata=metadata,
        )
        gate = self.check_gate(claim)
        if not gate.accepted:
            return AssertResult(accepted=False, claim=claim, gate=gate, fact=None)
        fact = self.commit_fact(claim, gate_result=gate)
        return AssertResult(accepted=True, claim=claim, gate=gate, fact=fact)

    # ---------- Cascading invalidation ----------

    def revoke_evidence(self, evidence_id: str, reason: str = "revoked") -> list[str]:
        """Mark an evidence as revoked and cascade-invalidate all dependent facts.

        Returns the list of invalidated fact ids (transitive closure).
        """
        now = datetime.now(timezone.utc)
        ev = self.store.get_evidence(evidence_id)
        if ev is None:
            return []
        # mark revoked
        self.store.conn.execute(
            "UPDATE evidence SET revoked_at=? WHERE id=?",
            (now.isoformat(), evidence_id),
        )
        self.store.conn.commit()

        return self._cascade_invalidate_from_evidence(evidence_id, reason, now)

    def sweep_expired(self) -> list[str]:
        """Re-check all active facts; invalidate those whose required support expired.

        Useful to call periodically (or on demand before build_context).
        """
        now = datetime.now(timezone.utc)
        invalidated: list[str] = []
        for fact in self.store.list_active_facts():
            reason = self._expiry_invalidation_reason(fact, now)
            if reason:
                self._invalidate(fact.id, reason, now)
                invalidated.append(fact.id)
                invalidated.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now))
        return invalidated

    def _cascade_invalidate_from_evidence(
        self,
        evidence_id: str,
        reason: str,
        now: datetime,
        seen: Optional[set[str]] = None,
    ) -> list[str]:
        seen = seen or set()
        affected: list[str] = []
        # invalidate observed facts that directly reference this evidence
        for fact in self.store.list_facts_using_evidence(evidence_id):
            if fact.id in seen:
                continue
            seen.add(fact.id)
            self._invalidate(fact.id, f"evidence {evidence_id} {reason}", now)
            affected.append(fact.id)
            affected.extend(self._cascade_invalidate_from_fact(fact.id, "parent fact invalidated", now, seen))
        return affected

    def _cascade_invalidate_from_fact(
        self,
        fact_id: str,
        reason: str,
        now: datetime,
        seen: Optional[set[str]] = None,
    ) -> list[str]:
        seen = seen or set()
        affected: list[str] = []
        for child in self.store.list_facts_depending_on(fact_id):
            if child.id in seen:
                continue
            seen.add(child.id)
            self._invalidate(child.id, f"{reason} ({fact_id})", now)
            affected.append(child.id)
            affected.extend(self._cascade_invalidate_from_fact(child.id, reason, now, seen))
        return affected

    def _invalidate(self, fact_id: str, reason: str, now: datetime) -> None:
        self.store.invalidate_fact(fact_id, reason, now)
        self.store.append_audit(
            event_type="fact_invalidated",
            fact_id=fact_id,
            accepted=False,
            detail={"reason": reason},
        )

    # ---------- L2: prompt context ----------

    def build_context(
        self,
        query: Optional[str] = None,
        max_facts: int = 10,
        *,
        task_id: Optional[str] = None,
        include_long_term: bool = True,
        max_memory_atoms: int = 5,
        max_memory_scenarios: int = 3,
        max_memory_personas: int = 2,
    ) -> str:
        return build_context(
            self.store,
            self.schema,
            query=query,
            task_id=task_id,
            max_facts=max_facts,
            include_long_term=include_long_term,
            max_memory_atoms=max_memory_atoms,
            max_memory_scenarios=max_memory_scenarios,
            max_memory_personas=max_memory_personas,
        )

    # ---------- audit ----------

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_audit(limit=limit)

    # ---------- internal resolution helpers ----------

    def _resolve_evidence_refs(self, refs: list[str]) -> tuple[list[Evidence], list[str]]:
        refs = _dedupe(refs)
        evs = self.store.get_evidence_many(refs)
        by_id = {e.id: e for e in evs}
        return [by_id[r] for r in refs if r in by_id], [r for r in refs if r not in by_id]

    def _resolve_fact_refs(self, refs: list[str]) -> tuple[list[Fact], list[str]]:
        refs = _dedupe(refs)
        facts = [self.store.get_fact(fid) for fid in refs]
        by_id = {f.id: f for f in facts if f is not None}
        return [by_id[r] for r in refs if r in by_id], [r for r in refs if r not in by_id]

    def _support_evidence_refs_for_claim(self, claim: Claim) -> list[str]:
        refs = list(claim.evidence_refs)
        if claim.kind == FactKind.DERIVED:
            parents, _ = self._resolve_fact_refs(claim.depends_on)
            for parent in parents:
                refs.extend(self._support_evidence_refs_for_fact(parent))
        return _dedupe(refs)

    def _support_evidence_refs_for_fact(self, fact: Fact, seen: Optional[set[str]] = None) -> list[str]:
        seen = seen or set()
        if fact.id in seen:
            return []
        seen.add(fact.id)

        refs = list(fact.evidence_refs)
        for parent_id in fact.depends_on:
            parent = self.store.get_fact(parent_id)
            if parent is not None:
                refs.extend(self._support_evidence_refs_for_fact(parent, seen))
        return _dedupe(refs)

    def _expiry_invalidation_reason(self, fact: Fact, now: datetime) -> Optional[str]:
        if fact.kind == FactKind.DERIVED:
            parents, missing = self._resolve_fact_refs(fact.depends_on)
            if missing:
                return f"parent fact missing: {missing}"
            dead = [p.id for p in parents if p.invalidated_at is not None]
            if dead:
                return f"parent fact invalidated: {dead}"

        claim_type = self.schema.claim_type(fact.claim_type)
        if claim_type is None:
            return f"claim_type '{fact.claim_type}' no longer declared in schema"

        refs = self._support_evidence_refs_for_fact(fact)
        evs, missing_refs = self._resolve_evidence_refs(refs)
        if missing_refs:
            return f"supporting evidence ref missing: {missing_refs}"

        requirements: list[tuple[str, str]] = []
        claim_freshness = "fresh" if claim_type.requires_fresh_evidence else "stale"
        requirements.extend((evidence_type, claim_freshness) for evidence_type in claim_type.required_evidence)
        for rule in self.schema.gates:
            if rule.when_claim_type and rule.when_claim_type != fact.claim_type:
                continue
            requirements.extend((evidence_type, rule.require_freshness) for evidence_type in rule.require_evidence_types)

        for evidence_type, required_freshness in requirements:
            candidates = [e for e in evs if e.evidence_type == evidence_type]
            if not candidates:
                return f"required evidence type '{evidence_type}' missing"
            if not any(is_usable(freshness_of(e, self.schema, now=now), required_freshness) for e in candidates):
                return f"required evidence type '{evidence_type}' no longer has {required_freshness} support"
        return None


def _auto_summary(content: str, max_len: int = 120) -> str:
    flat = " ".join(content.split())
    return flat if len(flat) <= max_len else flat[: max_len - 1] + "…"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _task_node_status_counts(nodes: list[TaskNode]) -> dict[str, int]:
    counts = {status.value: 0 for status in TaskNodeStatus}
    for node in nodes:
        counts[node.status.value] += 1
    return {status: count for status, count in counts.items() if count}


def _task_edge_would_create_cycle(
    src_node_id: str,
    dst_node_id: str,
    existing_edges: list[TaskEdge],
) -> bool:
    """Return True if adding src -> dst would create a directed cycle."""
    adjacency: dict[str, list[str]] = {}
    for edge in existing_edges:
        adjacency.setdefault(edge.src_node_id, []).append(edge.dst_node_id)

    stack = [dst_node_id]
    seen: set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id == src_node_id:
            return True
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(adjacency.get(node_id, []))
    return False
