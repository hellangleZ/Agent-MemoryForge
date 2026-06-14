# Configuration Reference

This document is the authoritative reference for environment variables and
runtime feature flags.

If you are just trying to run the system locally, start with:

- `docs/RUN_FULL_CHAIN.md`

---

## Conventions

- **Gateway** = `agent_runtime/product/agent_gateway.py`
- **Memory service** = `agent_memory_service/app.py`
- **SDK/framework flags** = `agent_memory_framework/feature_flags.py`

---

## Ports and default URLs

Recommended local defaults:

- Gateway: `http://127.0.0.1:8080`
- Memory service: `http://127.0.0.1:8001`
- Embedding service: `http://127.0.0.1:7999`

Notes:

- `config/constants.py` contains older constant defaults (e.g. port 8000) and is
  kept as a low-level constants module for integration tests. Prefer the service
  app defaults and docs.

---

## Portal UI

- `NEXT_PUBLIC_SHOW_TOOL_TRACE` (`1`/`0`) — defaults to `0`. Keep MCP/tool-call
  traces hidden in ordinary chat. Set to `1` only when debugging agent tool
  routing in the portal.

---

## Gateway (Product layer)

### API key (optional)

- `AGENT_GATEWAY_API_KEY`
  - If set: gateway requires `x-api-key: <value>` for protected endpoints.
  - If unset: gateway does not enforce API key.

### Portal authentication and secret storage

- `AUTH_JWT_SECRET`
  - Required in production.
  - Must be a strong random value and must not use the development default.
- `AUTH_REFRESH_TOKEN_HASH_SECRET`
  - Required in production.
  - Used to HMAC refresh tokens before storage.
- `AUTH_REFRESH_TOKEN_TTL_S` (default: `2592000`)
  - Refresh token TTL in seconds.
- `PORTAL_SECRETS_KEY`
  - Required in production.
  - Encrypts tenant/workspace MCP secrets stored through the portal.
  - Must be distinct from `AUTH_JWT_SECRET`.

### Conversation retention

- `AGENT_CONVERSATION_TTL_SECONDS` (default: `86400`)
  - TTL for gateway conversation store (Redis). Used by
    `agent_runtime/product/agent_gateway.py`.

### Memory service URL

The gateway uses `config/agent_config.py` (`MEMORY_SERVICE_URL`, default
`http://127.0.0.1:8001`).

### Customer SDK / Gateway token

- `AGENT_MEMORY_GATEWAY_ACCESS_TOKEN`
  - Optional SDK convenience variable.
  - When set, `agent_memory_lib.MemoryClient` sends
    `Authorization: Bearer <token>` and `x-workspace-id` so customer-owned
    agents can call the scoped Gateway memory proxy.
  - Prefer this for customer applications. Do not distribute the internal
    `AGENT_MEMORY_SERVICE_API_KEY` to tenant applications.

### Reference runtime tools

- `AGENT_REFERENCE_RUNTIME_GLOBAL_TOOLS_ENABLED` (`1`/`0`, default: `0`)
  - Enables deployment-global plugin/MCP discovery for the built-in reference
    chat runtime.
  - Keep disabled in multi-tenant production. Tenant/workspace MCP configured
    in the portal remains available without this flag.
- `AGENT_MCP_TOOL_DISCOVERY_CACHE_TTL_S` (default: `300`)
  - Cache TTL for reference-runtime MCP tool discovery.

---

## Full-chain control plane (Gateway)

This feature exposes process-control endpoints.

### Enable/disable

- `FULL_CHAIN_CONTROL_ENABLED`
  - `1`: enable `/v1/full-chain/*`
  - otherwise: disabled

### RBAC headers (required)

For `/v1/full-chain/*` endpoints:

- `Authorization: Bearer <token>`
  - token must include a `tenant_id` claim
- `x-workspace-id: <workspace>`
- caller must be a platform admin

### Optional allowlists

- `FULL_CHAIN_CONTROL_ALLOWED_TENANTS='t1,t2'`
- `FULL_CHAIN_CONTROL_ALLOWED_WORKSPACES='ws1,ws2'`

### Optional action allowlist

- `FULL_CHAIN_CONTROL_ALLOWED_ACTIONS='status,services,start,stop,logs,logs_stream,restart'`

### Runtime isolation (logs/pids)

When full-chain control is enabled, the gateway creates per-scope directories:

- Logs: `logs/full_chain/t_<tenant>__ws_<workspace>/`
- PIDs: `.runtime/full_chain/t_<tenant>__ws_<workspace>/`

---

## Framework feature flags

These flags exist so you can safely roll back runtime behavior without code
changes.

- `AGENT_MEMORY_ENABLE_PARALLEL` (default: `1`)
  - `1`: allow parallel multi-agent coordination.
  - `0`: force sequential.

- `AGENT_MEMORY_PARALLEL_WORKERS` (default: unset)
  - If set to a positive integer: caps ThreadPoolExecutor workers.

- `AGENT_MEMORY_ENABLE_SCOPING` (default: `1`)
  - Keep enabled for product use. Disabling scoping is only for narrow local
    tests.

FAISS is not part of the supported product runtime. Use SQLite FTS for local
keyword search and Postgres/pgvector for production semantic vector search.

---

## Memory service configuration

### Backend selection (File-First default)

- `AGENT_MEMORY_BACKEND` (default: `file_first`)
  - `file_first`: Markdown truth + SQLite FTS derived index

Note: the service only supports the File-First backend.

### Internal service key

- `AGENT_MEMORY_SERVICE_API_KEY` or `MEMORY_SERVICE_API_KEY`
  - Memory Service requires `x-agent-memory-service-key`.
  - Required in production.
  - The gateway, worker, and trusted SDK clients must use the same value.
- `AGENT_MEMORY_SERVICE_ALLOW_UNAUTHENTICATED_LOCAL_DEV` (`1`/`0`, default: `0`)
  - Allows running Memory Service without an internal key only in non-production
    local development.
  - Do not set in production. `/v1/memory/status` and all `/v1/memory/*`
    endpoints use the same internal-key check.

### File-First storage

- `AGENT_MEMORY_FILE_ROOT` (default: `~/.agent_memory_service/workspaces`)
  - Workspace data lives under `t_<tenant>__ws_<workspace>/`

### Derived index controls

- `AGENT_MEMORY_INDEX_REBUILD_ENABLED`
  - `1`: enable `POST /v1/memory/index/rebuild`
  - otherwise: rebuild endpoint is disabled

- `AGENT_MEMORY_INDEX_AUTO_REBUILD` (default: off)
  - `1`: enable optional auto-healing for the derived SQLite FTS index.
  - This does not change the source of truth (Markdown). It only rebuilds the derived index.

- `AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_FAILURE` (default: off)
  - `1`: when search detects a corrupted/uninitialized index, rebuild once and retry the query.

- `AGENT_MEMORY_INDEX_AUTO_REBUILD_ON_STALE` (default: off)
  - `1`: when index is detected as stale (typically due to manual Markdown edits), trigger a background rebuild.

- `AGENT_MEMORY_INDEX_AUTO_REBUILD_FAILURE_BACKOFF_S` (default: `60`)
  - Minimum seconds between repeated rebuild attempts on failures (prevents rebuild storms).

- `AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_COOLDOWN_S` (default: `600`)
  - Minimum seconds between stale-triggered background rebuild attempts.

- `AGENT_MEMORY_INDEX_AUTO_REBUILD_STALE_CHECK_INTERVAL_S` (default: `30`)
  - Minimum seconds between filesystem mtime scans to decide staleness.

- `AGENT_MEMORY_GRAPH_ENABLED`
  - `1`: enable best-effort Neo4j derived graph ingestion for `kg_relation`
  - Markdown remains the source of truth regardless

### pgvector semantic index

- `AGENT_MEMORY_VECTOR_ENABLED` (`1`/`0`)
  - Enables semantic vector indexing/search.
- `AGENT_MEMORY_VECTOR_BACKEND`
  - Set to `pgvector` for production.
- `AGENT_MEMORY_PGVECTOR_DSN`
  - Postgres DSN with pgvector extension available.
- `AGENT_MEMORY_PGVECTOR_TABLE` (default: `agent_memory_vectors`)
  - Vector table name.
- `AGENT_MEMORY_PGVECTOR_DIM`
  - Embedding dimension. Must match the embedding model output.
- `AGENT_MEMORY_VECTOR_ASYNC_INDEX` (`1`/`0`)
  - Keeps vector indexing off the write request path when enabled.

### Required per-request fields

The canonical memory service API requires these fields at the top level for
`/v1/memory/write`, `/v1/memory/search`, `/v1/memory/read`,
`/v1/memory/get`, `/v1/memory/stats`, and `/v1/memory/index/rebuild`:

- `tenant_id`
- `workspace_id`

### Embedding service

- `EMBEDDING_SERVICE_URL` (default: `http://127.0.0.1:7999/v1/embeddings`)
- `EMBEDDING_PROVIDER` (default: `local`) - `local` uses `EMBEDDING_SERVICE_URL`, `azure` uses `AZURE_EMBEDDING_*`
- `AZURE_EMBEDDING_BASE_URL` - Azure OpenAI-compatible base URL (should end with `/openai/v1/`)
- `AZURE_EMBEDDING_API_KEY` - API key for Azure embeddings endpoint
- `AZURE_EMBEDDING_DEPLOYMENT` - embedding deployment name (e.g. `text-embedding-3-small`)
- `EMBEDDING_MODEL_NAME` (default: `qwen3-embedding-0___6b`)
- `EMBEDDING_DIMENSION` (default: `1024`)

### Redis

- `REDIS_HOST` (default: `localhost`)
- `REDIS_PORT` (default: `6379`)
- `REDIS_DB` (default: `0`)

### Neo4j

- `NEO4J_URI` (default: `bolt://localhost:7687`)
- `NEO4J_USER` (default: `neo4j`)
- `NEO4J_PASSWORD`

Notes:

- When `AGENT_MEMORY_BACKEND=file_first`, Redis/embeddings/Neo4j are optional.
- Redis/embeddings/Neo4j are never required for basic File-First operation.

---

## LLM provider selection

The framework supports selecting the LLM provider via config or environment.

Supported modes:

- Azure OpenAI
- OpenAI-like (OpenAI-compatible API gateways)

API style:

- `OPENAI_API_STYLE` (`auto`/`responses`/`chat`, default: `auto`)
  - `auto`: prefer Responses API and fall back to Chat Completions only when the
    provider clearly does not support Responses.
  - `responses`: force Responses API and fail if unavailable.
  - `chat`: force Chat Completions. Use this for OpenAI-compatible gateways that
    only expose `/chat/completions`.
- `AZURE_OPENAI_API_STYLE`
  - Optional Azure-specific override. Falls back to `OPENAI_API_STYLE` or
    `LLM_API_STYLE`.
- `LLM_API_STYLE`
  - Optional fleet-wide fallback for components that do not have a more specific
    API-style override.

See `docs/USER_GUIDE.md` for wiring examples.

### Context planner LLM

The optional context planner can use a cheaper model to decide which memory
tiers should be recalled before the main LLM call.

- `CONTEXT_PLANNER_ENABLED` (`1`/`0`, default: `0`)
- `CONTEXT_PLANNER_PROVIDER` (`openai-like`/`azure`, default: `openai-like`)
- `CONTEXT_PLANNER_MODEL`
- `CONTEXT_PLANNER_OPENAI_BASE_URL`
- `CONTEXT_PLANNER_OPENAI_API_KEY`
- `CONTEXT_PLANNER_OPENAI_API_STYLE` (`auto`/`responses`/`chat`)
  - Optional planner override; falls back to `OPENAI_API_STYLE`/`LLM_API_STYLE`.
- `CONTEXT_PLANNER_AZURE_OPENAI_ENDPOINT`
- `CONTEXT_PLANNER_AZURE_OPENAI_API_KEY`
- `CONTEXT_PLANNER_AZURE_OPENAI_DEPLOYMENT`
- `CONTEXT_PLANNER_AZURE_OPENAI_API_VERSION`

## Workspace MCP

Tenant/workspace MCP configuration is stored through portal APIs, not process
environment variables in normal multi-tenant use.

- Portal secrets are encrypted with `PORTAL_SECRETS_KEY`.
- Config should reference secrets as placeholders, for example
  `${CONTEXT7_API_KEY}`.
- Remote HTTPS MCP servers are the customer self-service path.
- Local stdio MCP is operator-only and requires explicit backend allowlists.
- Secret placeholders are allowed in env/header values. Workspace stdio args may
  not contain secret placeholders; pass secrets through env/header fields so
  they can be stored encrypted and kept out of process command lines.

Tenant/workspace MCP safety flags:

- `AGENT_WORKSPACE_MCP_HTTP_ALLOWED_HOSTS`
  - Comma-separated allowlist for portal-configured HTTP MCP hosts.
  - Default allowlist includes Context7, Neon, and Supabase MCP hosts.
  - Supports exact hosts and wildcard/domain suffix entries such as
    `*.example.com` or `.example.com`.
- `AGENT_WORKSPACE_MCP_HTTP_ALLOW_PRIVATE` (`1`/`0`, default: `0`)
  - Allows private or non-HTTPS MCP URLs only for trusted operator deployments.
  - Keep disabled in hosted multi-tenant production.
- `AGENT_WORKSPACE_MCP_STDIO_ENABLED` (`1`/`0`, default: `0`)
  - Allows portal-configured workspace stdio MCP only when explicitly enabled.
  - Hosted multi-tenant deployments should keep this disabled and use HTTP MCP.
- `AGENT_WORKSPACE_MCP_STDIO_ALLOWED_COMMANDS`
  - Required when workspace stdio is enabled.
  - Comma-separated command names or absolute paths. Path entries are resolved
    canonically; an attacker cannot bypass the allowlist with a different path
    that happens to share an allowed basename.
- `AGENT_WORKSPACE_MCP_USE_OPERATOR_FALLBACK` (`1`/`0`, default: `0`)
  - Allows a tenant workspace with no MCP config to inherit operator/global MCP
    env configuration.
  - Keep disabled in production multi-tenant SaaS unless the deployment is a
    trusted single-tenant/operator demo.

Legacy/operator MCP env variables:

- `AGENT_MEMORY_MCP_SERVERS`
- `AGENT_MEMORY_MCP_STDIO`
- `MCP_ENABLED`
- `MCP_STDIO_COMMAND`
- `MCP_STDIO_ARGS`
- `MCP_NAMESPACE`

Use these only for trusted operator-managed runtimes.



## Async Memory Distillation

The gateway does not run automatic memory distillation inside `/v1/chat`. After a successful assistant turn it only enqueues a Redis job; `scripts/memory_distill_worker.py` consumes that job and writes durable STM, semantic facts, and graph relations. This keeps user-visible latency isolated from extraction, LLM validation, and memory-store failures.

Environment variables:
- `MEMORY_DISTILL_ENABLED` (`1`/`0`) — enables gateway enqueueing and the worker. Docker compose defaults this to `1`; set it to `0` only when you intentionally want no automatic distillation.
- `MEMORY_DISTILL_EVERY_N_ROUNDS` (integer) — enqueue cadence by completed assistant turns. Defaults to `1`.
- `MEMORY_DISTILL_PROVIDER` (`openai-like`/`azure`) — optional worker override; falls back to `LLM_PROVIDER`.
- `MEMORY_DISTILL_MODEL` — optional worker model/deployment override; falls back to `OPENAI_MODEL` or `AZURE_OPENAI_DEPLOYMENT`.
- `MEMORY_DISTILL_OPENAI_API_STYLE` (`auto`/`responses`/`chat`) — optional worker override; falls back to `OPENAI_API_STYLE`/`LLM_API_STYLE`.
- `MEMORY_DISTILL_TIMEOUT_S` (seconds) — per-provider-call timeout for the background worker. Defaults to `45`.
- `MEMORY_DISTILL_STORE_PREFERENCES` (`1`/`0`) — defaults to `1`. Preference writes are still evidence-gated and must be grounded in the user's own message.
- `MEMORY_DISTILL_PREFERENCE_REQUIRE_CONFIRMATION` (`1`/`0`) — defaults to `0`. Set to `1` only when the deployment wants a manual confirmation step for preference writes.

## Preference Persistence

Automatic preference extraction is handled by async distillation rather than the chat request path. The worker may persist a preference automatically when it is grounded in the user's own message and passes safety filters. Manual confirmation is an optional deployment mode, not the product default.

Environment variable:
- `PREFERENCE_REQUIRE_CONFIRMATION` (`1`/`0`) — controls explicit pending-preference confirmation handling. Defaults to `0`; set it to `1` for deployments that require manual preference approval.
