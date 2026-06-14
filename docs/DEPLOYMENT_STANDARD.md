# Deployment (Standard / VM)

This guide describes a **non-Docker** deployment on a single VM/server.

If you prefer Docker, see `docs/DEPLOYMENT_DOCKER.md`.

---

## Target topology (single node)

- Gateway (FastAPI): `:8080`
- Memory service (FastAPI): `:8001`
- Embedding service (FastAPI): `:7999`
- Redis: `:6379`
- Neo4j: `:7687`

You can run Redis/Neo4j as managed services instead.

---

## 1) System prerequisites

- Python 3.11+ (tested on Python 3.12)
- `pip`, `venv`
- `curl`
- Redis (local or remote)
- Neo4j (local or remote)

Embedding service model files:

- Provide a local ONNX model folder and set `MODEL_PATH`.

---

## 2) Install

```bash
python -m venv .venv
source .venv/bin/activate

# Minimal (SDK + client utilities only)
python -m pip install -e .

# Recommended for a full deployment on one VM
python -m pip install -e '.[all]'

# Or install only the roles you run on this VM
# python -m pip install -e '.[gateway]'
# python -m pip install -e '.[memory-service]'
# python -m pip install -e '.[embedding]'
```

---

## 3) Configure env

Create a `.env` from `.env.template` (do not commit):

```bash
cp .env.template .env
```

For OpenAI-compatible providers:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional)
- `OPENAI_BASE_URL` (optional)

For Azure OpenAI:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_MODEL`

Service URLs:

- `MEMORY_SERVICE_URL=http://127.0.0.1:8001`
- `EMBEDDING_SERVICE_URL=http://127.0.0.1:7999/v1/embeddings`

---

## 4) Run services

### 4.1 Redis / Neo4j

Start Redis and Neo4j via your system service manager (systemd) or managed
services.

### 4.2 Embedding service

```bash
export MODEL_PATH=/path/to/onnx/model/folder
python -m uvicorn embedding_service:app --host 0.0.0.0 --port 7999
```

Health:

```bash
curl http://127.0.0.1:7999/health
```

### 4.3 Memory service

```bash
python -m uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port 8001
```

Health:

```bash
curl http://127.0.0.1:8001/health
```

### 4.4 Gateway

```bash
export MEMORY_SERVICE_URL=http://127.0.0.1:8001
python -m uvicorn agent_runtime.product.agent_gateway:app --host 0.0.0.0 --port 8080
```

Health:

```bash
curl http://127.0.0.1:8080/health
```

Portal:

- `http://127.0.0.1:3000` when using `scripts/services.sh start`
- `http://127.0.0.1:8080/portal` for the gateway-served fallback shell

---

## 5) systemd units (recommended)

Create three systemd services:

- `embedding-service.service`
- `agent-memory-service.service`
- `agent-gateway.service`

Each should:

- use a dedicated user (non-root)
- set `WorkingDirectory` to the repo root
- set `EnvironmentFile` to your `.env`
- restart on failure

---

## 6) Security baseline

- Bind services to `127.0.0.1` and expose only the gateway via a reverse proxy.
- Enable TLS at the proxy (Nginx/Caddy).
- Set `AGENT_GATEWAY_API_KEY` and treat bearer tokens as secrets.
- Avoid enabling `FULL_CHAIN_CONTROL_ENABLED` in production.
