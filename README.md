# Evidence-Gated Memory

> **Memory that knows what it doesn't know.**
> Provenance-first memory for high-stakes AI agents.

Most agent memory systems focus on remembering more.
Evidence-Gated Memory focuses on **deciding which memories are allowed to become facts**.

## Core Principle

```
Raw events are append-only.
Facts are evidence-gated.
Prompt context is provenance-filtered.
```

- **L0 Events** — write-optimistic. Everything that happened.
- **L1a Observed Facts** — write-pessimistic. Must have a `source_ref`.
- **L1b Derived Facts** — write-pessimistic. Must declare supporting facts (cascading invalidation).
- **L2 Prompt Context** — provenance-filtered. Stale evidence is flagged; expired evidence is blocked.

## What it is

A Python library (`pip install evidence-gated-memory`) that adds an evidence-gated memory layer to any AI agent. Domain rules (entity types, TTLs, quality gates) are driven by YAML schemas — not hardcoded.

## What it is not

- Not an agent framework
- Not a vector database
- Not a chatbot memory layer

## Quick start

```python
from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.schemas.builtin import REFUND

memory = EvidenceGatedMemory(
    workspace=".egm",
    domain_schema=REFUND,
)

memory.record_event(role="user", content="Process refund for ORD-123")

order_ref = memory.record_evidence(
    evidence_type="order_record",
    source="order_api",
    source_system="order_api",
    content=order_api_result,
    metadata={"order_id": "ORD-123"},
)

policy_ref = memory.record_evidence(
    evidence_type="refund_policy",
    source="policy_db",
    source_system="policy_db",
    content=current_policy_text,
)

result = memory.assert_fact(
    "Order ORD-123 is eligible for refund",
    claim_type="refund_eligibility",
    evidence=[order_ref, policy_ref],
)

if not result.accepted:
    print(result.rejection_reason)   # e.g. "missing required evidence types: ['refund_policy']"
    print(result.suggested_action)   # e.g. "fetch the current refund_policy from policy_db"
```

## Differentiators

| | Mem0 / Zep / Letta | **EGM** |
|---|---|---|
| Default policy | write-optimistic | **write-pessimistic at fact layer** |
| Evidence required | optional | **mandatory** |
| Ref-level freshness | no | **yes (TTL per evidence type)** |
| Cascading invalidation | no | **yes (derived facts track dependencies)** |
| Gate rejection | boolean | **actionable (what's missing + what to do)** |

## Status

v0.1.1 — alpha hardening. Single-process SQLite backend. Built-in coding + refund schemas are packaged with the wheel. Schema-declared claim/evidence types fail closed, source_system allowlists are enforced, derived facts inherit support from live parent facts, and business-ID context queries such as `ORD-123` are safe.

## License

MIT
