# DAG Invariants

EGM's README describes three directed dependency surfaces:

1. Task graph: `TaskNode -> TaskNode`
2. Fact lineage: `Evidence -> observed fact -> derived fact`
3. Memory provenance: `L0 -> CandidateAtom -> L1 -> L2 -> L3`

These are DAG-style today. That wording is intentional. EGM already rejects some
illegal edges, but it does not yet enforce complete multi-node cycle detection
across every surface.

## Current Implemented Guarantees

### TaskGraph

Implemented today:

- task nodes belong to a `task_id`;
- explicit task edges reject self-loops;
- explicit task edges reject cross-task endpoints;
- explicit task edges reject multi-node cycles;
- `parent_id` rejects missing or cross-task parents;
- Mermaid rendering drops out-of-scope edges;
- task state is derived from child node status;
- gated `transition_node()` runs state gates before mutation.

Not fully implemented yet:

- `parent_id` ancestor-cycle rejection;
- inspect warnings for pre-existing illegal graphs.

### Fact Lineage

Implemented today:

- observed facts are grounded in evidence refs;
- derived facts can depend on parent facts;
- derived facts inherit parent evidence for gate checks;
- revoking evidence cascades to dependent facts;
- derived facts with invalidated parents are rejected.

Not fully implemented yet:

- normalized `fact_dependencies(parent_id, child_id)` storage;
- self-dependency rejection for every path;
- multi-node dependency cycle detection;
- fast indexed reverse-dependency lookup.

### Long-Term Memory Provenance

Implemented today:

- L0 raw conversation messages can be recorded;
- L1 atoms cite source messages;
- L2 scenarios cite L1 atoms;
- L3 personas cite L2 scenarios;
- build_context can include promoted long-term memory with source ids.

Planned:

- `CandidateAtom` model;
- candidate gate result;
- L0 -> CandidateAtom extraction interface;
- promote / pending review / reject API;
- audit for every candidate decision.

## Public Wording Rules

Allowed today:

```text
DAG-style task graph
directed dependency surfaces
fact lineage graph
memory provenance chain
cycle enforcement planned
```

Not allowed yet:

```text
fully enforced DAG
cycle-proof graph memory
complete DAG constraints
guaranteed acyclic lineage across all surfaces
```

README may describe the target architecture, but it must also point to
`plan.md` when the target is not fully implemented.

## Required Future Enforcement

### TaskGraph Cycle Rejection

When adding an edge:

```text
A -> B
B -> C
```

the system must reject:

```text
C -> A
```

It must also reject:

```text
A -> A
```

self-loop rejection already exists and must remain covered.

### Parent Chain Rejection

If:

```text
parent(A) = B
parent(B) = C
```

then:

```text
parent(C) = A
```

must be rejected.

### Fact Dependency Rejection

The system must reject:

```text
fact_a depends_on fact_a
fact_a -> fact_b -> fact_c -> fact_a
```

This likely requires normalized dependency storage so reverse traversal is
indexed and reliable.

### Memory Provenance Rejection

Future CandidateAtom promotion must reject:

- missing source messages;
- source spans that do not exist;
- candidates that supersede themselves;
- candidate promotion paths that create provenance loops;
- LLM-produced atoms without source span, confidence, rationale, and conflict flags.

## Audit Requirements

Every accepted or rejected graph mutation should leave an audit entry:

- edge accepted;
- edge rejected;
- reason;
- affected node/fact/atom ids;
- source evidence or parent references;
- suggested action when rejection can be repaired.

Cycle rejection should be auditable for the same reason gate rejection is
auditable: an agent should know what dependency it tried to create and why it
was not allowed.

## Roadmap Mapping

| Invariant | Current state | Planned landing |
|---|---|---|
| TaskEdge self-loop rejection | Implemented | Keep covered in tests |
| TaskEdge cross-task rejection | Implemented | Keep covered in tests |
| TaskGraph multi-node cycle rejection | Implemented for explicit TaskEdge rows | Keep covered in tests |
| parent_id missing/cross-task rejection | Implemented | Keep covered in tests |
| parent_id ancestor-cycle rejection | Missing | P3-09 |
| Fact depends_on cascade invalidation | Implemented | Harden with normalized storage |
| Fact dependency cycle rejection | Partial / missing | P3-09 / P3-10 |
| CandidateAtom provenance gate | Missing | P2-07 design, P3-08 implementation |
| Full enforced DAG wording | Not allowed yet | Only after enforcement lands |
