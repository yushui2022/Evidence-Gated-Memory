# Generic Agent Loop Integration

EGM is not an agent framework. It is a memory and state kernel that should sit
inside an existing agent loop at four stable points.

## The Four Calls

| Agent moment | EGM call | Purpose |
|---|---|---|
| A tool returns raw data | `record_evidence()` | Persist drill-downable evidence before the model reasons over it. |
| The agent wants to state a business conclusion | `assert_fact()` | Accept only claims backed by schema-required evidence. |
| The agent wants to mark a workflow step done or blocked | `transition_node()` | Enforce state gates before mutating task state. |
| The agent is about to call an LLM again | `build_context()` | Inject only gated facts, task state, freshness, and long-term memory. |

The loop should not let an LLM directly write facts, mark nodes done, or promote
long-term memory. The LLM can propose candidates. EGM decides what can be
committed.

## Minimal Shape

```python
memory = EvidenceGatedMemory(workspace, REFUND)

tool_result = call_order_api(order_id)
order_ref = memory.record_evidence(
    evidence_type="order_record",
    source="order_api",
    source_system="order_api",
    content=tool_result.raw_json,
    summary=tool_result.summary,
    metadata={"order_id": order_id},
)

claim = memory.assert_fact(
    f"Order {order_id} is eligible for refund",
    claim_type="refund_eligibility",
    evidence=[order_ref, policy_ref],
)
if not claim.accepted:
    return claim.suggested_action

transition = memory.transition_node(
    eligibility_node.id,
    TaskNodeStatus.DONE,
    evidence=[order_ref, policy_ref],
)
if not transition.accepted:
    return transition.suggested_action

prompt_context = memory.build_context(query=order_id, task_id=task_id)
```

## Integration Rules

- Record evidence before asking the model to rely on it.
- Treat gate rejection as a normal control-flow result, not an exception.
- Show `rejection_reason` and `suggested_action` to the agent or caller.
- Attach accepted facts to task nodes when the fact explains node progress.
- Use `transition_node()` for production state changes.
- Keep `update_task_node_status()` for setup, recovery, and tests.
- Build context before each LLM call instead of passing raw chat history.
- Keep tool output in refs/offload instead of flattening it into summaries.

## What An Adapter Should Do

A framework adapter should only map framework events to the four calls above.
It should not weaken EGM gates or invent a second memory policy.

Callback/event metadata should preserve:

- `task_id`
- `node_id`
- `tool_name`
- `evidence_id`
- `fact_id`
- `gate_result`

Retriever/context metadata should preserve:

- `fact_id`
- `claim_type`
- `fact_kind`
- `task_id`
- `node_id`
- `evidence_refs`
- `freshness`
- `blocked`

The runnable example is `examples/generic_refund_agent.py`.
The stable metadata contract for adapters is `docs/adapter-contract.md`.
