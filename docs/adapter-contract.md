# Adapter Metadata Contract

EGM adapters must preserve provenance. A framework adapter can change object
types, but it must not drop the fields needed to drill from a prompt item back
to facts, evidence, task nodes, and audit entries.

The contract below is the minimum shared shape for generic loops, LangChain,
LangGraph, OpenAI Agents, and future adapters.

## Stable Helper Functions

The zero-dependency helper module is:

```python
from evidence_gated_memory.adapters import (
    evidence_event_metadata,
    fact_context_metadata,
    gate_result_metadata,
)
```

Use these helpers when building framework-specific `Document.metadata`,
callback payloads, trace events, or tool-result envelopes.

## Context / Retriever Metadata

Every fact-like context item should preserve:

| Field | Meaning |
|---|---|
| `fact_id` | Committed EGM fact id. |
| `claim_type` | Schema claim type used by the gate. |
| `fact_kind` | `observed` or `derived`. |
| `task_id` | Workflow id when the fact is task-scoped. |
| `node_id` | TaskNode id when attached. |
| `evidence_refs` | Evidence ids backing the fact. |
| `freshness` | `fresh`, `stale`, `expired`, or `unknown` when known. |
| `blocked` | Whether the item is being surfaced as blocked/non-usable context. |

Example:

```python
metadata = fact_context_metadata(
    fact,
    task_id="refund:ORD-777",
    node_id=fact.node_id,
    freshness="fresh",
    blocked=False,
)
```

## Callback / Event Metadata

Every tool-output or callback event that records evidence should preserve:

| Field | Meaning |
|---|---|
| `task_id` | Workflow id if known. |
| `node_id` | TaskNode id if known. |
| `tool_name` | Tool or callback source name. |
| `evidence_id` | Evidence id written by `record_evidence()`. |
| `evidence_type` | Schema evidence type. |
| `source_system` | Trusted source-system name used by gates. |
| `audit_id` | Audit id when the adapter has it. |

Example:

```python
metadata = evidence_event_metadata(
    evidence,
    task_id="refund:ORD-777",
    node_id=node.id,
    tool_name="refund_api",
)
```

## Gate Result Metadata

Every rejected or accepted gate result should preserve:

| Field | Meaning |
|---|---|
| `accepted` | Boolean gate outcome. |
| `rejection_reason` | Human-readable reason. Empty when accepted. |
| `suggested_action` | Repair instruction when rejection is actionable. |
| `violations` | Structured violation list. |
| `claim_id` | Present for fact gates. |
| `node_id` | Present for state-transition gates. |
| `from_status` / `to_status` | Present for state-transition gates. |

Example:

```python
metadata = gate_result_metadata(assert_result.gate)
```

## Adapter Rules

- Do not rename these fields inside framework metadata unless the framework
  forces a wrapper; if wrapped, keep the original field names inside an `egm`
  object.
- Do not replace `evidence_refs` with summaries.
- Do not expose a fact to a model without `fact_id` and `evidence_refs`.
- Do not mark a state transition as successful if `gate_result_metadata()`
  says `accepted` is false.
- Do not treat adapter metadata as a new source of truth. The database and refs
  remain the source of truth.

## Current Scope

This contract is stable enough for early adapters. It does not yet define:

- streaming callback chunk metadata;
- hosted service trace envelopes;
- signed audit export format;
- vector-store-specific metadata limits.
