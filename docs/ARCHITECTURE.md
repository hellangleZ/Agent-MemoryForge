# Architecture

This repository is organized as a **4-surface product system**:

1) **Framework SDK** (`agent_memory_framework/`)
2) **Memory Service** (`agent_memory_service/`)
3) **Product Gateway** (`agent_runtime/product/`)
4) **Portal UI** (`portal-ui/`)

The goal is to keep agent logic testable and portable (SDK), keep persistence and
indexing isolated (Service), and keep authentication/workflows/ops UX
product-grade (Gateway + Portal).

---

## Components

### 1) Framework SDK (`agent_memory_framework/`)

Responsibilities:

- Build request context (`ContextAssembler`) and compact under budget.
- Execute single-agent turns (`Agent.run_turn`) and multi-agent coordination
  (`MultiAgentRuntime`).
- Own the **agent core runtime**: tool registry, execution loop, memory
  manager/context builder, and the reusable agent shell.
- Resolve/wire LLM providers.
- Provide adapters to external systems (e.g. HTTP memory service).
- Discover tools and agents for local/reference runtimes when explicitly enabled.

The SDK is **self-contained**: it has no import dependency on `agent_runtime`
(the product layer). The dependency direction is strictly
`agent_runtime` → `agent_memory_framework`.

Key modules:

- `agent_memory_framework/agent.py`: base `Agent` class (single agent root).
- `agent_memory_framework/demo_agent.py`: `DemoAgent`/`DemoRuntime` — a
  batteries-included `Agent` subclass used by the product gateway and templates.
- `agent_memory_framework/tools.py`: `ToolRegistry` (single source of truth).
- `agent_memory_framework/execution_loop.py`: `ExecutionLoop` tool-calling loop.
- `agent_memory_framework/memory_runtime/`: `MemoryManager`, `ContextBuilder`,
  context planner, memory policies (runtime-side memory orchestration).
- `agent_memory_framework/context.py`: message assembly + budget compaction.
  Optionally delegates to a pluggable builder via
  `AGENT_MEMORY_CONTEXT_BUILDER` / `config["context_builder"]`.
- `agent_memory_framework/multi_agent.py`: sequential/parallel coordinator.
- `agent_memory_framework/llm_clients.py` / `llm_resolver.py`: provider wiring.
- `agent_memory_framework/adapters/memory_service.py`: `MemoryServiceStore`
  adapter that talks to the memory service.
- `agent_memory_framework/trace.py`: spans for lightweight timing and debugging.

> Migration note (2026-06): the agent core (`ToolRegistry`, `ExecutionLoop`,
> the memory runtime, `DemoAgent`, and the LLM client factory) was moved out of
> `agent_runtime` into the SDK to remove an inverted dependency. `agent_runtime`
> now only hosts product concerns (gateway, auth, observability, templates); the
> obsolete `agent_runtime/core/` package was removed entirely.

### 2) Memory Service (`agent_memory_service/`)

Responsibilities:

- Persist and retrieve memories (STM/WM/LTM).
- Enforce **tenant/workspace scoping** at the API edge.
- Manage backend routing and derived indexes.

Recommended entrypoint:

- `agent_memory_service/app.py:create_app` (FastAPI app factory)

Notes:

- The app factory exists to avoid import-time side effects.
- The service requires `tenant_id` and `workspace_id` on every `/v1/memory/*` request.
- **Default backend is File-First (and the only backend)**: Markdown files are
  the source of truth, SQLite FTS is a derived index for search.

### 3) Product Gateway (`agent_runtime/product/`)

Responsibilities:

- Expose public product APIs (`/v1/memory/*` proxy, monitoring, portal APIs).
- Provide a portal UI shell under `/portal/*`.
- Enforce auth + tenancy routing.
- Provide an optional **full-chain control plane** for trusted operator
  start/stop/logs. This is disabled by default and is not a customer memory API.
- Host a reference chat runtime under `/v1/chat`. Customer-owned agents can
  bypass it and use the SDK or memory APIs directly.

Entrypoint:

- `uvicorn agent_runtime.product.agent_gateway:app --port 8080`

### 4) Portal UI (`portal-ui/`)

Responsibilities:

- Customer workspace setup: MCP config, workspace secrets, tool policy, agents,
  memory inspection.
- Admin setup: users, workspace membership, quotas, usage, monitoring, audit.
- Reference chat/test surface.

The portal configures product state; it is not required for SDK-only customers.

---

## Data flow vs control flow

### A) Reference chat data flow

High-level flow:

1. Client calls gateway `POST /v1/chat` (with workspace header).
2. Gateway resolves a reference agent spec and builds a scoped `MemoryClient`.
3. Reference agent/framework builds context and calls the LLM.
4. The runtime uses Memory Service for canonical read/write/search.
5. Gateway returns `ChatResponse` including `trace_id`.

```
Client
  └── POST /v1/chat
        └── Gateway (auth, tenancy)
              ├── Agent runtime (framework)
              │     ├── ContextAssembler
              │     ├── LLM provider
              │     └── MemoryServiceStore (adapter)
              └── Memory service (write/search/read)
                    └── Markdown truth + SQLite FTS (default)
                         └── (optional) Neo4j / vectors / Redis cache
```

### B) Full-chain control flow (optional ops feature)

This is a *control plane* to start/stop the local subprocesses behind a guarded
gateway endpoint.

- Disabled by default.
- Requires `FULL_CHAIN_CONTROL_ENABLED=1`.
- Requires portal auth, platform-admin permission, and workspace headers.
- Writes logs/pids **under a tenant/workspace scoped directory**.
- Intended for local/operator environments, not normal customer application
  traffic.

See `docs/RUN_FULL_CHAIN.md` and `docs/API_REFERENCE.md`.

---

## Isolation model

The isolation boundary is:

- `tenant_id` + `workspace_id`

Where it is enforced:

- Gateway: requires `x-workspace-id` and uses a tenant claim in the bearer token.
- Workspace registry: workspaces are explicit tenant resources under
  `workspaces[tenant_id][workspace_id]`; legacy prompt/MCP/member config is
  migrated into that model on write/list.
- Memory service: rejects requests missing `tenant_id`/`workspace_id`.
- Memory service private-tier RBAC: `preferences`, `stm`, and `wm` use
  `actor_user_id`/`actor_role`; ordinary users can only access their own private
  memory. `semantic` and `graph` are shared workspace knowledge.
- Framework adapter: can be configured to refuse read/write when scoping is
  disabled (feature flag).

---

## Parallel multi-agent

`MultiAgentRuntime` supports:

- `sequential`: deterministic safe default
- `parallel`: thread pool execution

Engineering requirements for parallel mode:

- Trace collector must be thread-safe.
- Memory HTTP client must not share a single `requests.Session` across threads.

The framework enforces these by:

- Recording spans via a locked `TraceCollector`.
- Cloning `MemoryClient` per agent runtime.

---

## Dynamic orchestration (TaskGraph)

`MultiAgentRuntime` is intentionally a low-level “broadcast” primitive (same
query fan-out to multiple agents). For real collaboration, this repo adds a
dynamic **TaskGraph orchestrator**:

- Coordinator (LLM) emits a **TaskGraph JSON** program (DAG)
- Executor validates the DAG and runs tasks with optional parallel groups
- Each step can persist an **artifact** to File-First memory (`wm` by default)
- Executor also persists **Task Run snapshots** (a Markdown checklist) so UIs
  can show progress as tasks move `pending → running → done`
- Final output is deterministic: it is taken from `final.task_id`

Key modules:

- `agent_memory_framework/task_graph.py`: schema + validator
- `agent_memory_framework/orchestrator.py`: planner + executor + artifact persistence
- `agent_memory_framework/subagents.py`: in-process parallel runner
- `workflows/AUTO_TASK_GRAPH.md`: markdown-first coordinator instructions

Runner:

- `python scripts/run_task_graph.py --message "..." --tenant-id t1 --workspace-id ws1`

### Task tracking (Task Run snapshots)

When tracking is enabled (default), the executor writes a small “task list”
Markdown snapshot to File-First WM at key transitions:

- initial plan accepted (`all pending`)
- before a parallel batch starts (`running`)
- after a batch completes (`done`)

Implementation notes:

- Stored via `memory_write(tier="wm", scope="orchestration")`
- Metadata includes `kind="task_run_snapshot"` and `run_id`
- In `per_role` isolation mode, snapshots are written to the **base workspace**
  (not the derived `__role__...` workspaces), so progress is shared
- The orchestrator result JSON includes snapshot citations under
  `orchestration_trace.task_list_snapshots`

---

## Product Boundary Notes

- The Memory Service is a data plane. It does not expose agent or external tool
  discovery endpoints.
- External MCP belongs to tenant/workspace configuration used by the reference
  runtime or by customer-owned agents. It is not core memory storage.
- Tenant/reference chat does not inherit deployment-global MCP servers or plugin
  tools by default. Operator/global fallback must be explicitly enabled for
  trusted demos.
- The built-in `DemoAgent` is a test/reference runtime. Customer agents can
  integrate via SDK, REST, or an MCP facade without subclassing it.
- Async distillation runs outside the chat request path. Chat latency should not
  wait on memory extraction.

## Removed storage paths

Multi-backend storage (Redis/Faiss/Neo4j "heavy stack") and the old
all-in-one `agent_memory_system.py` module have been removed. The supported
runtime is File-First only (Markdown truth + derived indexes).

For product usage, prefer:

- Memory service: `agent_memory_service/app.py:create_app`
- Gateway: `agent_runtime/product/agent_gateway.py`

For memory persistence/search, prefer the File-First endpoints documented in:

- `docs/API_REFERENCE.md`
