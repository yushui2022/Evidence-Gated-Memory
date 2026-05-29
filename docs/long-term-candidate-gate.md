# Long-Term Memory Candidate Gate

EGM should not copy the Mem0/Letta pattern of letting an LLM directly write
long-term memory. The long-term memory path must follow the same discipline as
facts and task-state transitions:

```text
LLM extracts candidate -> deterministic gate -> promote / pending / reject -> audit
```

The LLM may propose a memory. It must not decide that the memory becomes an L1
atom.

## Why This Exists

The current L0/L1/L2/L3 memory pyramid is manual. That is safe, but it does not
scale to real agent workloads. A business agent can produce thousands of user
messages, tool results, and decisions per day. If every L1 memory atom requires
manual promotion, the long-term layer will stay mostly empty.

The right next step is not direct automatic distillation. The right step is a
candidate queue:

1. Store raw L0 conversation messages.
2. Let an extractor propose candidate atoms.
3. Require source spans, confidence, rationale, and conflict flags.
4. Run deterministic candidate gates.
5. Promote only candidates that satisfy policy.
6. Put ambiguous candidates into pending review.
7. Reject unsupported candidates.
8. Write audit for every decision.

## Non-Negotiable Principle

```text
Direct automatic L0 -> L1 promotion is forbidden.
```

Allowed:

```text
L0 message -> CandidateAtom -> CandidateGateResult -> MemoryAtom
```

Forbidden:

```text
L0 message -> LLM summary -> MemoryAtom
```

## CandidateAtom Draft

`CandidateAtom` is not prompt memory. It is a proposed memory item waiting for
gate decision.

Required fields:

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Candidate id, e.g. `cand_...`. |
| `kind` | yes | `persona`, `episodic`, or `instruction`. |
| `text` | yes | Proposed L1 memory text. |
| `source_message_ids` | yes | L0 messages used by extraction. |
| `source_spans` | yes | Exact spans proving the candidate. |
| `confidence` | yes | Extractor confidence, 0.0 to 1.0. |
| `extraction_rationale` | yes | Why the extractor proposed this candidate. |
| `conflict_flags` | yes | Possible conflicts with existing atoms. |
| `supersedes_atom_ids` | no | Existing atom ids this candidate replaces. |
| `metadata` | no | Adapter/domain metadata. |
| `created_at` | yes | Candidate creation time. |

## SourceSpan Draft

`source_spans` are mandatory. A source message id alone is too weak because a
large message can contain many claims.

Required fields:

| Field | Meaning |
|---|---|
| `message_id` | L0 conversation message id. |
| `start_char` | Inclusive character offset into the message content. |
| `end_char` | Exclusive character offset. |
| `quoted_text_hash` | Hash of the quoted source text. |

Validation rules:

- `message_id` must exist.
- `start_char` and `end_char` must be in range.
- `start_char < end_char`.
- The extracted substring hash must equal `quoted_text_hash`.
- At least one valid source span is required.

The hash should be deterministic and provider-independent. A future
implementation can use SHA-256 over the exact substring encoded as UTF-8.

## CandidateGateResult Draft

`CandidateGateResult` is the long-term-memory counterpart to `GateResult` and
`TransitionGateResult`.

Required fields:

| Field | Meaning |
|---|---|
| `accepted` | True only for candidates allowed to become L1 atoms. |
| `decision` | `promote`, `pending_review`, or `reject`. |
| `violations` | Structured policy violations. |
| `confidence_policy` | How confidence affected the decision. |
| `conflict_policy` | How conflicts/supersedes were handled. |
| `suggested_action` | How to repair or review a rejected/pending candidate. |
| `audit_id` | Audit row id once written. |

## Decision Policy

### Auto Promote

Auto promotion is allowed only when all are true:

- candidate has at least one valid source span;
- all source messages exist;
- `confidence` is at or above the configured high threshold;
- no conflict flags are present;
- `supersedes_atom_ids` is empty or explicitly valid;
- candidate kind is allowed by policy;
- text is non-empty and bounded.

Default high threshold should start conservative, e.g. `0.85`.

### Pending Review

Use pending review when:

- confidence is medium;
- conflict flags are present but not fatal;
- candidate supersedes an existing atom;
- candidate affects long-lived behavior such as instruction/persona memory;
- source spans are valid but interpretation is not obvious.

Pending candidates must not enter `build_context()`.

### Reject

Reject when:

- source span is missing;
- source message does not exist;
- source span offsets are invalid;
- source hash does not match;
- confidence is below threshold;
- text is empty or too broad;
- candidate tries to create unsupported L2/L3 memory directly;
- conflict policy says the candidate cannot safely supersede existing memory.

Rejected candidates must not enter `build_context()`.

## Conflict Policy

Conflict detection can start simple and deterministic:

- same kind + high lexical overlap with different text -> conflict flag;
- explicit `supersedes_atom_ids` must reference existing atoms;
- a candidate must not supersede itself;
- persona/instruction conflicts default to pending review, not auto promote;
- episodic candidates may be rejected or pending depending on confidence.

LLM conflict detection can be added later, but it must only produce
`conflict_flags`. It must not decide promotion.

## Audit Events

Minimum audit events:

- `memory_candidate_created`
- `memory_candidate_gate_check`
- `memory_candidate_promoted`
- `memory_candidate_rejected`
- `memory_candidate_pending_review`

Each audit detail should include:

- `candidate_id`
- `decision`
- `kind`
- `source_message_ids`
- `source_spans`
- `confidence`
- `conflict_flags`
- `supersedes_atom_ids`
- `violations`
- `suggested_action`

## Prompt-Injection Boundary

Only promoted `MemoryAtom` records may enter `build_context()`.

These must not enter prompt context:

- raw L0 messages;
- candidate atoms;
- rejected candidates;
- pending-review candidates;
- extractor rationales;
- unverified conflict notes.

## API Sketch

The future implementation should keep manual promotion working and add a
candidate path beside it.

```python
candidate = memory.create_memory_candidate(
    kind="instruction",
    text="Refund completion requires fresh refund_api_response evidence.",
    source_spans=[...],
    confidence=0.92,
    extraction_rationale="The user stated this as a workflow rule.",
    conflict_flags=[],
)

gate = memory.check_memory_candidate_gate(candidate.id)

if gate.decision == "promote":
    atom = memory.promote_memory_candidate(candidate.id, gate)
elif gate.decision == "pending_review":
    memory.mark_memory_candidate_pending(candidate.id, gate)
else:
    memory.reject_memory_candidate(candidate.id, gate)
```

## Storage Sketch

First implementation can use one new table:

```text
memory_atom_candidates(
  id,
  created_at,
  kind,
  text,
  source_message_ids,
  source_spans,
  confidence,
  extraction_rationale,
  conflict_flags,
  supersedes_atom_ids,
  status,
  gate_result,
  promoted_atom_id,
  metadata
)
```

Status values:

- `candidate`
- `promoted`
- `pending_review`
- `rejected`

This table requires a versioned migration. Do not add it with an ad hoc
`CREATE TABLE IF NOT EXISTS` only.

## L2 And L3 Policy

L1 candidate gate is the first automated step. L2 scenario and L3 persona
automation should stay later and stricter.

Default policy:

- L1 episodic/instruction candidates may auto promote under strict conditions.
- L2 scenario candidates default to pending review.
- L3 persona candidates default to pending review or manual-only.

Persona memory has long-lived behavioral impact. It should not be auto-promoted
without a separate policy.

## Release Boundary

Current implementation status: the first L1 candidate-gate code path exists.
It includes `CandidateAtom`, `SourceSpan`, `CandidateGateResult`, schema v2
storage, source-span SHA-256 validation, promote / pending / reject APIs, and
audit events. This is not yet a full review workflow or L2/L3 automation.

For v0.7, this document is enough. It defines the design.

For v0.9, implementation must include:

- `CandidateAtom` model or equivalent;
- candidate storage migration;
- source-span validation;
- candidate gate result;
- promote / pending / reject APIs;
- audit for every decision;
- tests proving candidates do not enter context until promoted.
