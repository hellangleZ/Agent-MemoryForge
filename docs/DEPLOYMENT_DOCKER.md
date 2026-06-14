# Deployment (Docker)

This guide provides a Docker-based deployment.

- `docker-compose.yml`: local/dev defaults (ports exposed)
- `docker-compose.prod.yml`: production-like defaults (internal network + reverse proxy)

For non-Docker deployments, see `docs/DEPLOYMENT_STANDARD.md`.

---

## One-command local control

For local product testing, prefer the wrapper script:

```bash
scripts/services.sh start     # start Redis, Neo4j, Postgres/pgvector, memory, gateway, portal
scripts/services.sh build     # rebuild compose images explicitly
scripts/services.sh --build restart
scripts/services.sh status
scripts/services.sh logs gateway
scripts/services.sh stop
```

The script uses `docker-compose.yml` by default and project name `agent-memory`.
`start` and `restart` do not rebuild images unless `--build` is passed; use that
flag after code or dependency changes.
Use `scripts/services.sh --prod start` only when you intentionally want the
production-like compose file.

Local vector search is disabled by default, so the embedding container is not
started unless `AGENT_MEMORY_VECTOR_ENABLED=1` is set. When vector search is
enabled, set `HOST_MODEL_PATH` to a valid ONNX model root; the wrapper adds the
`vector` compose profile automatically.

For local/dev, the script generates missing service keys, database passwords,
gateway API key, JWT secret, refresh-token hash secret, and portal encryption
key under `.runtime/`. Real deployments should put explicit values in `.env` or
a secret manager.


## 0) Prerequisites

- Docker
- Docker Compose v2 (`docker compose`)

Install model (optional):

- The image installs Python dependencies via `pyproject.toml` extras.
- By default, the `Dockerfile` installs `.[all]` (full chain dependencies).

Embedding model files:

- You need a host folder with your ONNX model assets.

---

## 1) Local/dev deployment

```bash
scripts/services.sh start
```

After changing backend, portal, or dependency code, rebuild once and restart:

```bash
scripts/services.sh --build restart
```

Health checks:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:7999/health
```

Portal:

- `http://127.0.0.1:3000` (Next.js portal)
- `http://127.0.0.1:8080/portal` (gateway-served fallback shell)

Enable local vector search only when model files are present:

```bash
AGENT_MEMORY_VECTOR_ENABLED=1 HOST_MODEL_PATH=/path/to/models scripts/services.sh --build restart
```

---

## 2) Production-like deployment (recommended Docker pattern)

This mode:

- puts Redis, Neo4j, Postgres/pgvector, embedding, memory, and gateway on a private docker network
- exposes only ports 80/443 through a reverse proxy
- mounts a persistent volume for memory artifacts
- *requires secrets* to be set (no default passwords)

### 2.1 Prepare environment

Copy the example env:

```bash
cp deploy/.env.docker.example .env
```

Edit `.env` and set:

- `POSTGRES_PASSWORD`
- `NEO4J_PASSWORD`
- `AGENT_GATEWAY_API_KEY`
- `AGENT_MEMORY_SERVICE_API_KEY`
- `AUTH_JWT_SECRET`
- `AUTH_REFRESH_TOKEN_HASH_SECRET`
- `PORTAL_SECRETS_KEY`
- `HOST_MODEL_PATH` (absolute host path)

### 2.2 Start

```bash
scripts/services.sh --prod start
```

### 2.3 Verify

If you keep the proxy on port 80 locally:

```bash
curl http://127.0.0.1/health
```

If you deploy under a domain with TLS, replace `http://127.0.0.1` with your
`https://<domain>`.

---

## 3) Persistence

`docker-compose.prod.yml` mounts `memory_data` at `/data` and stores Markdown memory workspaces under:

- `AGENT_MEMORY_FILE_ROOT=/data/workspaces`

To back up memory truth, snapshot `/data/workspaces`. Also back up Postgres, Redis, and Neo4j volumes if you rely on their derived indexes or runtime state.

---

## 4) Security baseline

Required:

- Set `AGENT_GATEWAY_API_KEY`.
- Set `AGENT_MEMORY_SERVICE_API_KEY`.
- Set strong, distinct `AUTH_JWT_SECRET`, `AUTH_REFRESH_TOKEN_HASH_SECRET`, and
  `PORTAL_SECRETS_KEY`.
- Keep `FULL_CHAIN_CONTROL_ENABLED=0` in Docker production.
- Do not expose Redis/Neo4j to the public internet.

Recommended:

- Terminate TLS in the reverse proxy (`deploy/Caddyfile`).
- Bind only 80/443 publicly.
- Put secrets in your secret manager (not a committed `.env`).

---

## 5) Managed services (optional)

In serious production setups, run Redis/Neo4j as managed services.

If you do, remove the `redis`/`neo4j` services from the compose file and set:

- `REDIS_HOST`, `REDIS_PORT`
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
