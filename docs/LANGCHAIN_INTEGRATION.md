# LangChain Integration

Agent-MemoryForge is a memory layer, not a replacement for a customer's LangChain or
LangGraph agent runtime.

## Recommended Mode: Memory Layer

The customer agent owns:

- LLM provider and model selection for planning and answering.
- Tool loop and business tools.
- When to call memory search, context build, and memory write.

Agent-MemoryForge owns:

- Tenant/workspace/actor-scoped memory storage.
- Preferences, STM, WM, semantic facts, and graph relations.
- Embedding, derived indexes, recall, async distillation, audit, and metrics.
- Enterprise-level model credentials for memory internals, configured by admins.

Use `agent_memory_lib.MemoryClient` against the Product Gateway:

```python
from agent_memory_lib import MemoryClient

memory = MemoryClient(
    "https://gateway.example.com",
    tenant_id="tenant_acme",
    workspace_id="dw_ops",
    access_token="<access_token>",
    shared_pool=True,
)

query = "finance_mrr freshness SLA and upstream dependencies?"
context = memory.build_context(
    query=query,
    user_id="alice",
    conversation_id="conv_123",
)

# Send context + user message to your own LangChain chat model.
messages = [*context, {"role": "user", "content": query}]
```

After a useful turn, write memory back through the same gateway:

```python
memory.store_stm("conv_123", 2, "User confirmed finance_mrr SLA ownership.")
memory.memory_write(
    tier="semantic",
    scope="project",
    content="finance_mrr SLA is 09:00 Asia/Shanghai and owner is Alice.",
    metadata={"source": "customer_agent"},
)
```

## Gateway-as-Tool Mode

`/v1/chat` can be wrapped as a LangChain tool when a customer wants our hosted
reference agent to produce the answer. This is useful for demos and validation,
but it is not the main enterprise integration contract because the customer is
then delegating the agent loop to our gateway.

## Verification

Run the preferred memory-layer E2E:

```bash
python examples/langchain_memory_layer_agent.py --mint-dev-token --load-requests 20 --concurrency 5
```

A passing run proves:

- The SDK can authenticate through the gateway.
- `/v1/memory/write` stores private and workspace memories with server-side scope.
- `build_context()` recalls preferences, STM, semantic facts, and graph facts.
- LangChain can own the agent step and use Agent-MemoryForge context.
- STM write-back works after the answer.
- Concurrent recall returns expected facts and reports p50/p95 latency.
