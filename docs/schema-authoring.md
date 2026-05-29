# Schema Authoring Guide

EGM's behavior is driven by domain schemas. A schema defines which evidence
types exist, which claim types require which evidence, which source systems are
trusted, and which task-state transitions are allowed.

This guide shows how to write a new schema without modifying EGM's core code.

## Minimal Mental Model

```text
evidence_type
  declares what raw evidence can be recorded

claim_type
  declares what evidence is required before a fact can be committed

gate
  adds deterministic rules and actionable rejection messages

state_gate
  blocks task-node status transitions until required evidence exists

entity
  extracts hard anchors such as order_id, ticket_id, case_id, file, test
```

The LLM may propose text. The schema decides whether that text becomes memory.

## Example: Ticket Schema

```yaml
name: ticket
description: Support-ticket workflow schema for evidence-gated agents.

entities:
  - name: ticket
    patterns: ["TICK-[0-9]+"]
    metadata_fields: ["ticket_id"]
  - name: customer
    patterns: ["CUST-[0-9]+"]
    metadata_fields: ["customer_id"]
  - name: escalation
    patterns: ["ESC-[0-9]+"]
    metadata_fields: ["escalation_id"]

evidence_types:
  ticket_record:
    stale_after: PT30M
    expired_after: PT24H
    source_systems: ["ticket_api"]
    risk: medium

  customer_record:
    stale_after: PT1H
    expired_after: P7D
    source_systems: ["crm"]
    risk: medium

  policy_article:
    stale_after: P7D
    expired_after: P30D
    source_systems: ["policy_db"]
    risk: medium

  escalation_response:
    stale_after: PT5M
    expired_after: PT1H
    source_systems: ["escalation_api"]
    risk: high

claim_types:
  ticket_status:
    required_evidence: ["ticket_record"]
    description: Current state of a support ticket.

  resolution_eligibility:
    required_evidence: ["ticket_record", "policy_article"]
    description: Whether the ticket can be resolved under support policy.

  escalation_completed:
    required_evidence: ["escalation_response"]
    requires_fresh_evidence: true
    description: Escalation has actually been completed.

gates:
  - name: resolution_requires_policy
    when: { claim_type: resolution_eligibility }
    require:
      evidence_types: ["ticket_record", "policy_article"]
      freshness: stale
    suggested_action: "fetch ticket_record from ticket_api and policy_article from policy_db"

  - name: escalation_completion_requires_api_response
    when: { claim_type: escalation_completed }
    require:
      evidence_types: ["escalation_response"]
      freshness: fresh
    suggested_action: "call escalation_api and attach a fresh escalation_response before declaring escalation complete"

state_gates:
  - name: resolution_done_requires_ticket_and_policy
    when: { node_type: resolution_check, to_status: done }
    require:
      evidence_types: ["ticket_record", "policy_article"]
      freshness: stale
    suggested_action: "fetch ticket_record and policy_article before marking resolution done"

  - name: escalation_done_requires_response
    when: { node_type: escalation, to_status: done }
    require:
      evidence_types: ["escalation_response"]
      freshness: fresh
    suggested_action: "attach a fresh escalation_response before marking escalation done"
```

## Design Rules

### Evidence Types

Evidence types should map to concrete systems or artifacts:

- API response;
- database record;
- policy document;
- file read;
- test log;
- command output;
- approval record.

Avoid vague evidence types such as `memory`, `reasoning`, or `llm_output`.
EGM's core rule is that LLM output is not source evidence.

### Source Allowlists

Every important evidence type should declare `source_systems`.

```yaml
source_systems: ["ticket_api"]
```

This prevents an agent from grounding a ticket fact in an untrusted source such
as `llm`, `user_guess`, or `scratchpad`.

### Freshness

Use two TTLs:

- `stale_after`: evidence is old but may still be usable for some claims;
- `expired_after`: evidence is too old and must block required support.

High-risk completion claims should usually require fresh evidence:

```yaml
claim_types:
  escalation_completed:
    required_evidence: ["escalation_response"]
    requires_fresh_evidence: true
```

### Claim Types

A claim type should correspond to a business statement the agent may want to
write into memory:

- `ticket_status`;
- `resolution_eligibility`;
- `escalation_completed`;
- `file_content`;
- `task_done`.

Do not make one generic `fact` claim type. It weakens gate precision.

### Suggested Actions

Good suggested actions are operational:

```text
call escalation_api and attach a fresh escalation_response
```

Weak suggested actions are vague:

```text
get more information
```

The rejection should tell the agent which tool or system to call next.

## Validation Checklist

Before publishing a schema:

- unknown evidence types should raise before writing refs;
- unknown claim types should fail closed;
- missing required evidence should reject with the evidence type name;
- wrong source systems should reject;
- expired required evidence should reject;
- state transitions to `done` should reject without required evidence;
- rejection should include a useful `suggested_action`;
- at least one demo should show reject -> fetch evidence -> accept.

## How To Use A Schema

```python
from pathlib import Path
from evidence_gated_memory import EvidenceGatedMemory
from evidence_gated_memory.schemas.loader import load_schema

schema = load_schema(Path("ticket.yaml"))
memory = EvidenceGatedMemory("workspace", schema)
```

Then use the same EGM APIs:

```python
node = memory.create_task_node(
    "ticket:TICK-123",
    "resolution_check",
    "Check whether TICK-123 can be resolved",
    anchors={"ticket_id": "TICK-123"},
)

result = memory.assert_fact(
    "TICK-123 can be resolved under support policy",
    claim_type="resolution_eligibility",
    evidence=[],
)

assert result.accepted is False
print(result.suggested_action)
```

The schema should make the next required tool call obvious.
