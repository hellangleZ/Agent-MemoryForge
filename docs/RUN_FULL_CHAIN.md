# Full-chain run (local)

This project supports an end-to-end run with:

- Neo4j (KG)
- Redis (queue + conversation store)
- Optional: Local Embedding service (ONNX)
- Memory service (FastAPI)
- Product Gateway (FastAPI)
- Optional: Context Planner (cheap LLM)
- Optional: Async Distill Worker (cheap LLM)

This document lists the environment variables you need and the recommended
startup order.

## 0) Install dependencies

```bash
# Minimal (SDK + client utilities only)
python -m pip install -e .

# Full chain local run (recommended for this guide)
python -m pip install -e '.[all]'
```

You can also install only the parts you need:

- `python -m pip install -e '.[framework]'`
- `python -m pip install -e '.[memory-service]'`
- `python -m pip install -e '.[gateway]'`
- `python -m pip install -e '.[embedding]'`

## 1) Create local env files (do not commit)

Copy the examples and fill secrets locally:

```bash
cp config/openai_main.env.example config/openai_main.env
cp config/context_planner.env.example config/context_planner.env
cp config/distill_worker.env.example config/distill_worker.env
```

You can either `source` them in your shell, or use `python-dotenv` compatible
loading in your process.

### 1.1 Main reasoning LLM (OpenAI-compatible)

File: `config/openai_main.env`

Required:

- `OPENAI_BASE_URL` (Azure OpenAI OpenAI-compatible example: `https://<resource>.openai.azure.com/openai/v1/`)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (for Azure OpenAI OpenAI-compatible endpoints: use the *deployment name*)

Optional:

- `AZURE_OPENAI_API_VERSION` (some Azure OpenAI compatible endpoints require this as a query)
- `LLM_PROVIDER=openai-like`
- `OPENAI_API_STYLE=auto` (`chat` for Chat Completions-only compatible gateways)

### 1.2 Neo4j (KG)

Required:

- `NEO4J_URI` (default `bolt://localhost:7687`)
- `NEO4J_USER` (default `neo4j`)
- `NEO4J_PASSWORD`

### 1.3 Redis

Required:

- `REDIS_HOST` (default `localhost`)
- `REDIS_PORT` (default `6379`)
- `REDIS_DB` (default `0`)

Notes:

- For Docker-based local product testing, prefer `scripts/services.sh start`.
  It generates missing local secrets under `.runtime/` and starts the full
  stack with the current compose file.

### 1.4 Embedding service

Default local embedding service endpoint:

- `EMBEDDING_SERVICE_URL=http://127.0.0.1:7999/v1/embeddings`

Optional:

- `EMBEDDING_MODEL_NAME=qwen3-embedding-0___6b`
- `EMBEDDING_DIMENSION=1024`

Important:

- The embedding server needs local model files. Set `MODEL_PATH` to a folder
  that contains your ONNX model.

### 1.5 Memory distillation worker (cheap LLM)

File: `config/distill_worker.env`

Required to enable async (Option B):

- `MEMORY_DISTILL_ENABLED=1`
- `MEMORY_DISTILL_PROVIDER=openai-like`
- `MEMORY_DISTILL_OPENAI_BASE_URL`
- `MEMORY_DISTILL_OPENAI_API_KEY`
- `MEMORY_DISTILL_OPENAI_API_STYLE` (optional; falls back to `OPENAI_API_STYLE`)
- `MEMORY_DISTILL_MODEL`

Redis queue:

- `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB`

### 1.6 Context planner (cheap LLM)

File: `config/context_planner.env`

Required to enable:

- `CONTEXT_PLANNER_ENABLED=1`
- `CONTEXT_PLANNER_PROVIDER=openai-like`
- `CONTEXT_PLANNER_OPENAI_BASE_URL`
- `CONTEXT_PLANNER_OPENAI_API_KEY`
- `CONTEXT_PLANNER_OPENAI_API_STYLE` (optional; falls back to `OPENAI_API_STYLE`)
- `CONTEXT_PLANNER_MODEL`

## 2) Start infrastructure + memory service

If you want the current Docker stack, use the product service wrapper:

```bash
scripts/services.sh start
```

`start_services.sh` is a legacy helper for older non-compose local runs.

### 2.1 One-command runner (recommended)

If you prefer a single command to start the chain, use either:

```bash
scripts/run_full_chain.sh --no-demo
```

or the Python runner (useful when you want to embed it as an API later):

```bash
python scripts/run_full_chain.py --no-demo
```

You can also run it via the product CLI (same runner, nicer "product" entry point):

```bash
python -m agent_runtime.product.cli run-full-chain --no-demo
```

Health checks:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:7999/health
```

## 3) Start product gateway

The gateway is the product API/control layer: auth, tenant/workspace routing,
reference chat, memory proxy, portal APIs, quotas, monitoring, and audit.

```bash
source config/openai_main.env
export MEMORY_SERVICE_URL=http://127.0.0.1:8001

uvicorn agent_runtime.product.agent_gateway:app --host 0.0.0.0 --port 8080
```

Optional gateway env:

- `AGENT_GATEWAY_API_KEY=...` (if set, gateway requires `x-api-key`)

## 3.1) Full-chain control plane (optional)

The gateway can optionally expose **process control endpoints** that start/stop
the local full-chain subprocesses (uvicorn memory service, gateway itself, and
optional distill worker) and provide log tail/stream.

Safety notes:

- Disabled by default.
- Requires `FULL_CHAIN_CONTROL_ENABLED=1`.
- If `AGENT_GATEWAY_API_KEY` is set, all endpoints require header `x-api-key`.
- Requires portal auth with platform-admin permission.
- Intended for local/operator use, not ordinary customer application traffic.

Enable:

```bash
export FULL_CHAIN_CONTROL_ENABLED=1
export AGENT_GATEWAY_API_KEY=secret
```

RBAC headers (required):

- `Authorization: Bearer <access_token>` (must include `tenant_id` claim)
- `x-workspace-id: <workspace>`

Optional allowlists:

```bash
export FULL_CHAIN_CONTROL_ALLOWED_TENANTS='t1,t2'
export FULL_CHAIN_CONTROL_ALLOWED_WORKSPACES='ws1,ws2'
```

Optional action allowlist:

```bash
export FULL_CHAIN_CONTROL_ALLOWED_ACTIONS='status,services,start,stop,logs,logs_stream,restart'
```

Endpoints:

- `GET /v1/full-chain/status` — running services + pid/log path
- `GET /v1/full-chain/services` — known service names
- `POST /v1/full-chain/start` — start group
- `POST /v1/full-chain/restart` — stop + start
- `POST /v1/full-chain/stop` — stop all
- `GET /v1/full-chain/logs?service=gateway&tail=200` — tail log lines
- `GET /v1/full-chain/logs/stream?service=gateway&tail=50&interval_s=0.2` — SSE stream

Example:

```bash
curl \
  -H 'x-api-key: secret' \
  -H 'authorization: Bearer <token>' \
  -H 'x-workspace-id: ws1' \
  http://127.0.0.1:8080/v1/full-chain/status

curl -H 'x-api-key: secret' -H 'authorization: Bearer <token>' -H 'x-workspace-id: ws1' \
  -X POST http://127.0.0.1:8080/v1/full-chain/restart \
  -H 'content-type: application/json' \
  -d '{"restart":true,"memory_port":8001,"gateway_port":8080,"start_distill_worker":false,"verbose":false}'

curl -N -H 'x-api-key: secret' -H 'authorization: Bearer <token>' -H 'x-workspace-id: ws1' \
  'http://127.0.0.1:8080/v1/full-chain/logs/stream?service=gateway&tail=50&interval_s=0.2'
```

## 4) Start async distill worker (Option B)

In a new terminal:

```bash
source config/distill_worker.env
python scripts/memory_distill_worker.py
```

## 5) Run the demo end-to-end

In a new terminal:

```bash
source config/openai_main.env
python examples/project_management_demo_real.py
```

## 6) Optional MCP servers

For hosted multi-tenant use, configure remote HTTPS MCP servers in the portal:

- workspace MCP server JSON
- workspace secrets such as `CONTEXT7_API_KEY`, `NEON_API_KEY`, or
  `SUPABASE_ACCESS_TOKEN`
- tool policy allowlist/denylist

Local stdio MCP is operator-only. Do not expose arbitrary tenant-provided local
commands in a hosted deployment.
