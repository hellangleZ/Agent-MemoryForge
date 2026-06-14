# Product Overview

Agent-MemoryForge is a memory infrastructure product for enterprise agent
systems. It gives each tenant and workspace a durable memory layer that can be
used by external agent frameworks, internal copilots, and the included reference
agent runtime.

## What The Product Does

- Stores scoped agent memory across `tenant_id + workspace_id`.
- Retrieves relevant preferences, recent context, semantic facts, working
  state, and graph relations before an LLM call.
- Writes durable memory after useful work through explicit APIs or async
  distillation.
- Provides portal administration for users, quotas, workspaces, MCP secrets,
  tool policy, memory inspection, monitoring, and audit.
- Provides REST API integration and an official Python SDK so customers can keep
  their own agent orchestration stack.

## What The Product Is Not

- It is not the customer's only possible agent runtime.
- It is not a generic hosted MCP marketplace.
- It does not require customers to rewrite LangChain, LangGraph, OpenAI Agents,
  CrewAI, AutoGen, or custom agent systems.
- It does not use Redis, pgvector, or Neo4j as the authoritative memory store.

## Customer Scenarios

Good fits:

- Data warehouse or BI assistants that need dataset ownership, SLA, schema, and
  business decision memory.
- Support or success copilots that need tenant-specific procedures and customer
  preferences.
- Coding or operations agents that need project decisions and current task
  state across sessions.
- Multi-agent workflows that need shared working memory and auditable artifacts.

Poor fits:

- A stateless chatbot that never needs durable state.
- A customer that only wants a tool router with no memory product.
- Workloads that require arbitrary tenant-provided local processes in a hosted
  SaaS environment.

## Product Surfaces

| Surface | Role | Customer contract |
| --- | --- | --- |
| Memory Service | Internal data plane | Scoped `/v1/memory/*`; keep private in production |
| Product Gateway | Public API/control plane | Auth, workspace routing, memory proxy, chat reference, portal APIs |
| Portal | Admin/customer UI | Users, quotas, workspaces, tools, secrets, monitoring |
| Official Python SDK | Integration client | Build memory context and write memory from customer agents |
| Reference runtime | Demo/test runtime | Optional proof environment, not required for customer agents |

## Tenant And Workspace Model

The product scope is `tenant_id + workspace_id`.

- A tenant is the enterprise/customer account.
- A workspace is the operational boundary inside that tenant, for example
  `dw_ops`, `support_cn`, or `platform_engineering`.
- Users are members of workspaces and can have workspace-specific quotas.
- Workspace MCP servers, secrets, tool policy, custom reference-agent prompts,
  and memory are all attached to explicit workspace records.

This is why customer agents should call the Gateway memory proxy or official
Python SDK with a workspace token/header instead of connecting directly to the
Memory Service.

There are three primary isolation levels:

1. **Tenant**: the enterprise/customer account boundary.
2. **Workspace**: the operational boundary inside a tenant.
3. **Actor/user**: the private memory boundary for preferences, STM, and WM.

RBAC, workspace membership, quota enforcement, usage accounting, encrypted MCP
secrets, and tool policy are governance controls layered on top of those data
boundaries.

## Integration Patterns

### Bring Your Own Agent

The expected enterprise integration is:

1. Customer agent receives a user request.
2. Agent calls the official Python SDK or Gateway memory APIs to build context.
3. Agent sends memory context plus the user request to its chosen LLM stack.
4. Agent writes task state, facts, preferences, or graph relations after useful
   work.

### Portal Reference Agent

The portal chat validates product behavior quickly:

- memory retrieval and context selection
- async distillation
- token/quota accounting
- workspace MCP configuration
- tool policy and routing behavior

It is intentionally simple. Production customers can use their own agent design.

### MCP

Remote HTTPS MCP servers are workspace configuration. Secrets are entered in the
portal and stored encrypted. Common presets include Context7, Neon, and
Supabase. Local stdio MCP is operator-only and not a normal tenant self-service
feature in hosted multi-tenant deployments.

## Memory Tiers

| Tier | Purpose | Example |
| --- | --- | --- |
| `stm` | Conversation checkpoints | "In this thread, the user is planning the DW migration." |
| `wm` | Active task state | Current plan, accepted steps, task artifacts |
| `preferences` | Durable user preferences | "Reply in Chinese for this user." |
| `semantic` | Long-term facts and decisions | "finance_mrr refresh SLA is T+1 by 09:00." |
| `graph` | Relationship facts | `finance_mrr -> depends_on -> raw_invoices` |

Access model:

- `preferences`, `stm`, and `wm` are private by actor unless the caller is an
  admin/system/service actor.
- `semantic` and `graph` are shared workspace knowledge.
- Automatic distillation is asynchronous. Chat requests enqueue extraction work;
  the worker decides what should become STM, semantic facts, graph facts, or
  preferences based on grounded evidence and the configured policy.

## Storage Roles

- Markdown workspace: authoritative memory truth.
- SQLite FTS: local derived text index.
- Postgres/pgvector: production semantic vector index.
- Neo4j: optional derived relation index.
- Redis: runtime queue, conversation window, observability, and cache.

## Deployment Posture

Production should run:

- Gateway public, Memory Service private.
- `APP_ENV=production`.
- `AGENT_MEMORY_SERVICE_API_KEY` configured for gateway/worker/service calls.
- Strong, distinct `AUTH_JWT_SECRET`, `AUTH_REFRESH_TOKEN_HASH_SECRET`, and
  `PORTAL_SECRETS_KEY`.
- pgvector enabled for enterprise semantic search.
- async distillation worker enabled if automatic memory extraction is required.
- full-chain control endpoints disabled unless used by a trusted operator plane.

See [Architecture](ARCHITECTURE.md), [API Reference](API_REFERENCE.md), and
[Configuration Reference](CONFIG_REFERENCE.md).
