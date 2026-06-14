# Service Operations

This is the operational entry point for running Agent-MemoryForge locally or on
a single development server. The product uses one supported service wrapper:

```bash
scripts/services.sh start
```

Older direct-process runners have been removed. They duplicated the Docker
stack, drifted from the real compose topology, and made it unclear which service
was authoritative. Use the commands below for development, QA, and operator
smoke tests.

---

## Service Model

The local stack starts these services through Docker Compose:

| Service | Role | Default host port |
| --- | --- | --- |
| `portal` | Next.js control plane UI | `3000` |
| `gateway` | Customer/API/portal boundary | `8080` |
| `memory` | Internal memory service | internal compose network |
| `distill_worker` | Async memory distillation worker | none |
| `postgres` | Metadata, auth, pgvector-ready storage | `15432` |
| `redis` | Queues, conversation state, metrics/audit cache | `16379` |
| `neo4j` | Knowledge graph backend | `17474`, `17687` |

The Memory Service is intentionally private in the compose network. Customer
integrations should call the Gateway or the Python SDK, not the internal memory
container.

---

## First Run

1. Copy local environment templates if you need custom providers:

```bash
cp .env.example .env
```

2. Edit `.env` locally. Do not commit real API keys, passwords, database URLs,
   or tenant secrets.

3. Start the stack:

```bash
scripts/services.sh start
```

4. Open the portal:

```text
http://127.0.0.1:3000
```

5. Check the Gateway:

```bash
curl http://127.0.0.1:8080/health
```

Use `--build` only after source or dependency changes:

```bash
scripts/services.sh --build start
```

---

## Daily Commands

```bash
# Show container state and mapped ports
scripts/services.sh status

# Restart without rebuilding images
scripts/services.sh restart

# Rebuild then restart after code changes
scripts/services.sh --build restart

# Stop containers without deleting persisted volumes
scripts/services.sh stop

# Stop and remove runtime containers for a clean local process state
scripts/services.sh down
```

`stop` is the normal shutdown path. `down` is for local cleanup when you want
Compose containers removed. Database volumes are not deleted unless you run an
explicit Docker volume cleanup command yourself.

---

## Health Checks

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/readyz
curl http://127.0.0.1:3000
```

Portal-facing checks should be run in a browser as well. At minimum verify:

- login succeeds
- `/admin/memory` renders without framework overlays or failed-fetch toasts
- memory empty states show `Empty` / `Not built`, not fake utilization
- tool and workspace pages save real configuration through the Gateway

---

## Full-chain Control Plane

The Gateway still includes optional `/v1/full-chain/*` process-control APIs for
trusted operator environments. They are disabled by default and are not a normal
customer integration path.

Enable only when you understand the operational boundary:

```bash
FULL_CHAIN_CONTROL_ENABLED=1
```

All full-chain endpoints require:

- platform-admin portal auth
- `x-workspace-id`
- tenant/workspace scope
- optional `x-api-key` if `AGENT_GATEWAY_API_KEY` is configured

Useful CLI commands call the Gateway control plane instead of starting a second
local stack:

```bash
python -m agent_runtime.product.cli full-chain-status \
  --auth-token "$AGENT_GATEWAY_AUTH_TOKEN" \
  --workspace-id "$AGENT_GATEWAY_WORKSPACE_ID"

python -m agent_runtime.product.cli full-chain-logs gateway --tail 100 \
  --auth-token "$AGENT_GATEWAY_AUTH_TOKEN" \
  --workspace-id "$AGENT_GATEWAY_WORKSPACE_ID"
```

Keep these APIs disabled in hosted multi-tenant production unless the Gateway is
running in a trusted internal operator network.

---

## Troubleshooting

If the portal is unreachable:

```bash
scripts/services.sh status
docker compose -p agent-memory ps
docker compose -p agent-memory logs portal --tail=100
```

If the Gateway is unhealthy:

```bash
docker compose -p agent-memory logs gateway --tail=100
docker compose -p agent-memory logs memory --tail=100
```

If memory distillation appears stalled:

```bash
docker compose -p agent-memory logs distill_worker --tail=100
docker compose -p agent-memory logs redis --tail=100
```

If a request fails in the portal, inspect both browser console output and the
Gateway logs. The portal should show scoped error states; raw stack traces and
secret values must never be displayed.
