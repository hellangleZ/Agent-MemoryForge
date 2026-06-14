# API Reference

This document describes the HTTP APIs exposed by:

- Memory Service (`agent_memory_service/`)
- Product Gateway (`agent_runtime/product/`)

For local startup instructions, see `docs/SERVICE_OPERATIONS.md`.

---

## Memory Service API (FastAPI)

Base URL (local): `http://127.0.0.1:8001`

Production posture:

- Keep the Memory Service on an internal network.
- Let the Product Gateway or trusted SDK clients call it.
- `AGENT_MEMORY_SERVICE_API_KEY` or `MEMORY_SERVICE_API_KEY` is required by
  default. Callers must send `x-agent-memory-service-key: <value>`.
- Local unauthenticated development requires the explicit escape hatch
  `AGENT_MEMORY_SERVICE_ALLOW_UNAUTHENTICATED_LOCAL_DEV=1`.

### `GET /health`

Returns:

```json
{"status":"healthy","message":"Memory service is running"}
```

### File-First (Markdown truth) APIs

These endpoints treat Markdown files as the source of truth and return citations
as `path` + `line`.

### `POST /v1/memory/write`

Body:

```json
{
  "tenant_id": "t1",
  "workspace_id": "ws1",
  "tier": "semantic",
  "scope": "project",
  "content": "We decided to make Markdown the source of truth.",
  "metadata": {"tags":["decision"],"source":"chat"},
  "target": "daily"
}
```

Returns:

```json
{"status":"success","data":{"entry_id":"...","path":"memory/2026-02-08.md","created_at":"...","line_start":1}}
```

### `POST /v1/memory/search`

Body:

```json
{"tenant_id":"t1","workspace_id":"ws1","query":"source of truth","top_k":5,"tiers":["semantic"],"memory_kinds":["semantic_fact"],"path_prefixes":["memory/"]}
```

Returns:

```json
{"status":"success","data":{"hits":[{"score":1.23,"snippet":"...","path":"memory/2026-02-08.md","line":1,"entry_id":"..."}]}}
```

Errors:

- `422`: invalid request (e.g. `top_k` out of range, invalid search query syntax after normalization)
- `503`: search index unavailable/corrupted (rebuild the index; see `/v1/memory/index/rebuild`)

Notes:

- `top_k` is clamped by validation (`1..100`).

### `POST /v1/memory/get`

Body:

```json
{"tenant_id":"t1","workspace_id":"ws1","path":"memory/2026-02-08.md","start_line":1,"max_lines":200}
```

Returns:

```json
{"status":"success","data":{"path":"memory/2026-02-08.md","content":"<!-- am:entry ... -->\\n..." }}
```

### `GET /v1/memory/status`

Returns backend selection and file-root configuration. This endpoint requires
the same internal service key as the write/search/read APIs.

### `POST /v1/memory/index/rebuild` (disabled by default)

Requires `AGENT_MEMORY_INDEX_REBUILD_ENABLED=1`.

### `POST /v1/memory/read`

Direct reads are for state-like tiers: `stm`, `wm`, `preferences`, and `graph`.
Semantic facts are retrieved through `/v1/memory/search`.

Preference body:

```json
{"tenant_id":"t1","workspace_id":"ws1","tier":"preferences","user_id":"u1","key":"language"}
```

STM body:

```json
{"tenant_id":"t1","workspace_id":"ws1","tier":"stm","conversation_id":"conv_123","limit":15}
```

WM body:

```json
{"tenant_id":"t1","workspace_id":"ws1","tier":"wm","task_id":"task_123"}
```

### `POST /v1/memory/stats`

Body:

```json
{"tenant_id":"t1","workspace_id":"ws1"}
```

Returns per-tier counts and derived index status.

The Memory Service is data plane only. It does not expose agent discovery or MCP
tool discovery endpoints.

Private tiers (`preferences`, `stm`, `wm`) support `actor_user_id` and
`actor_role` request fields for service-side RBAC. Ordinary users can only read
or write their own private-tier memory; `admin`, `system`, and `service` actors
can access workspace-private memory for operational flows. Shared workspace
knowledge belongs in `semantic` and `graph`.

---

## Product Gateway API (FastAPI)

Base URL (local): `http://127.0.0.1:8080`

### `GET /health`

Returns:

```json
{"ok":true}
```

### Portal UI (HTML shell)

- `GET /portal`
- `GET /portal/*`

The portal is a gateway-served UI shell that calls API endpoints.

---

## Chat

### `POST /v1/chat` (reference runtime)

This endpoint hosts the built-in reference agent runtime. It is useful for
portal validation, demos, and smoke tests, but customer production agents do not
need to use it. Customer agents can call the Gateway memory proxy, SDK, or memory
MCP facade directly.

Headers:

- `authorization: Bearer <portal_access_token>` (required)
- `x-workspace-id: <workspace>` (required)
- `x-api-key: <key>` (required only if `AGENT_GATEWAY_API_KEY` is set)

Body (`agent_runtime/product/gateway_models.py`):

```json
{
  "agent": "pm-minimal",
  "user_id": "u_1",
  "conversation_id": "c_1",
  "messages": [{"role":"user","content":"Hello"}],
  "temperature": 0.2,
  "max_tool_turns": 12,
  "stm_top_k": 5,
  "stm_max_summaries": 15,
  "stm_relevance_threshold": 0.3
}
```

Response:

```json
{
  "status": "success",
  "conversation_id": "c_1",
  "trace_id": "...",
  "answer": "...",
  "messages": []
}
```

---

## Gateway Memory Proxy

The gateway exposes scoped memory APIs for customer integrations that should not
call the internal Memory Service directly.

- `POST /v1/memory/write`
- `POST /v1/memory/search`
- `POST /v1/memory/read`
- `POST /v1/memory/get`
- `POST /v1/memory/index/rebuild`

Headers:

- `authorization: Bearer <portal_access_token>` (required)
- `x-workspace-id: <workspace>` (required)
- `x-api-key: <key>` (required only if `AGENT_GATEWAY_API_KEY` is set)

The gateway derives `tenant_id` from the authenticated token and enforces
workspace access before proxying to the Memory Service. It also forwards the
authenticated user as `actor_user_id`, so private tiers remain user-scoped even
when searched through the proxy.

Removed endpoints:

- `/v1/jobs`
- `/v1/jobs/{job_id}`
- `/v1/jobs/{job_id}/artifacts`

These were placeholder workflow APIs and now return 404.

---

## Monitoring

- `GET /portal/v1/monitoring/metrics`
- `GET /portal/v1/monitoring/audit`

---

## Full-chain control plane (optional)

All `/v1/full-chain/*` endpoints:

- are **disabled by default**
- require `FULL_CHAIN_CONTROL_ENABLED=1`
- require RBAC headers:
  - `Authorization: Bearer <token>` (must include `tenant_id` claim)
  - `x-workspace-id: <workspace>`
- require platform-admin permission
- may also require `x-api-key` if `AGENT_GATEWAY_API_KEY` is set

### `GET /v1/full-chain/dependencies`

Returns structured dependency probes:

```json
{
  "status":"success",
  "data":{
    "ok":true,
    "dependencies":{
      "redis":{"ok":true},
      "embedding":{"ok":true},
      "neo4j":{"ok":true},
      "memory":{"ok":true}
    }
  }
}
```

### `GET /v1/full-chain/status`

Reports running service status and scoped log/pid paths.

### `GET /v1/full-chain/services`

Returns known service names.

### `POST /v1/full-chain/start`

Body:

```json
{
  "memory_port": 8001,
  "gateway_port": 8080,
  "memory_url": "http://127.0.0.1:8001",
  "verbose": false,
  "start_distill_worker": false,
  "restart": false,
  "require_dependencies_healthy": true
}
```

### `POST /v1/full-chain/restart`

Stop then start.

### `POST /v1/full-chain/stop`

Stop all in-scope services.

### `GET /v1/full-chain/logs?service=gateway&tail=200`

Tail logs.

### `GET /v1/full-chain/logs/stream?service=gateway&tail=50&interval_s=0.2`

Server-sent events stream:

- lines are emitted as `data: <line>`

---

## Python SDK Integration

The official Python SDK is designed so customers can keep their own agent
runtime. They do not need to use the hosted demo agent.

```python
from agent_memory_lib import MemoryClient

memory = MemoryClient(
    "https://gateway.example.com",
    tenant_id="tenant_acme",
    workspace_id="dw_ops",
    access_token="<gateway_access_token>",
    shared_pool=True,
)

query = "finance_mrr 的 freshness SLA 是什么？它上游依赖什么？"
memory_context = memory.build_context(
    query=query,
    user_id="user_123",
    conversation_id="conv_123",
    system_prompt="You are a data warehouse assistant.",
)

# Use with LangChain, LangGraph, OpenAI Agents SDK, or a custom LLM caller.
messages = [
    *memory_context,
    {"role": "user", "content": query},
]

# After a useful turn, write back short-term memory or durable facts.
memory.store_stm("conv_123", 2, "The user confirmed finance_mrr SLA ownership.")
memory.memory_write(
    tier="semantic",
    scope="project",
    content="finance_mrr SLA is 09:00 Asia/Shanghai and owner is Alice.",
    metadata={"source": "customer_agent"},
)
```

`build_context()` reads preferences, recent STM, semantic facts, and graph facts
through the scoped Gateway memory proxy. The SDK sends `Authorization: Bearer
<gateway_access_token>` and `x-workspace-id` when configured. It fails open by
default: if memory is unavailable, it still returns a small system message with
memory-use rules so the customer's agent can continue without blocking on the
memory service. It does not include internal memory paths by default; pass
`include_sources=True` when a source-citation workflow needs them. For
natural-language questions, the SDK tries the full query first and then falls
back to one high-signal identifier such as `finance_mrr`, which improves recall
without turning one customer turn into many backend searches.

### LangChain Memory-Layer E2E

Use this example for the preferred enterprise integration shape, where the
customer's LangChain agent owns the LLM and Agent-MemoryForge is only the memory
layer:

```bash
python examples/langchain_memory_layer_agent.py \
  --gateway-url http://127.0.0.1:8080 \
  --tenant-id t_zhouboyang \
  --workspace-id ws_default \
  --user-id zhouboyang \
  --mint-dev-token \
  --load-requests 20 \
  --concurrency 5
```

The script writes test memories through `/v1/memory/write`, builds context
through the SDK, runs a deterministic LangChain `RunnableLambda` in the customer
LLM slot, writes back STM, and reports end-to-end and concurrent recall latency.
Replace the deterministic Runnable with a real LangChain chat model in customer
code.
