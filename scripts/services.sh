#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PROJECT_NAME="agent-memory"

ACTION=""
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$DEFAULT_PROJECT_NAME}"
BUILD_IMAGES=0
EXTRA_ARGS=()

usage() {
  cat <<USAGE
Usage: scripts/services.sh [options] <command> [service...]

Commands:
  start        Stop old local project processes, then start the full Docker stack without rebuilding images
  build        Build Docker images for the selected compose file
  stop         Stop Docker stack and old local project processes
  restart      stop + start
  status       Show Docker services and old local project processes
  logs         Follow Docker logs; accepts optional service names
  ps           Alias for Docker compose ps
  config       Render Docker compose config
  kill-local   Stop only old local uvicorn/Next processes from this repo
  destroy      Stop stack and remove named volumes for this compose project

Options:
  --prod              Use docker-compose.prod.yml instead of docker-compose.yml
  --file <path>       Use a custom compose file
  --project <name>    Compose project name (default: agent-memory)
  --build             Rebuild images before start/restart
  -h, --help          Show this help

Default local ports:
  portal    http://127.0.0.1:${PORTAL_PORT:-3000}
  gateway   http://127.0.0.1:${GATEWAY_PORT:-8080}
  memory    internal Docker service memory:8001
  embedding disabled by default; enable with AGENT_MEMORY_VECTOR_ENABLED=1
  neo4j     http://127.0.0.1:${NEO4J_HTTP_PORT:-17474}
  postgres  127.0.0.1:${POSTGRES_PORT:-15432}
  redis     127.0.0.1:${REDIS_PORT:-16379}

Notes:
  - Local secrets are generated under .runtime/ when missing. Put real secrets
    in .env when needed.
  - Vector search is disabled by default for local startup unless you set
    AGENT_MEMORY_VECTOR_ENABLED=1 and HOST_MODEL_PATH to a real ONNX model root.
USAGE
}

log() {
  printf '[services] %s\n' "$*"
}

die() {
  printf '[services] ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)
      COMPOSE_FILE="docker-compose.prod.yml"; shift ;;
    --file)
      [[ $# -ge 2 ]] || die "--file requires a path"
      COMPOSE_FILE="$2"; shift 2 ;;
    --project|--project-name)
      [[ $# -ge 2 ]] || die "--project requires a name"
      PROJECT_NAME="$2"; shift 2 ;;
    --build)
      BUILD_IMAGES=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      if [[ -z "$ACTION" ]]; then
        ACTION="$1"
      else
        EXTRA_ARGS+=("$1")
      fi
      shift ;;
  esac
done

ACTION="${ACTION:-status}"

cd "$ROOT_DIR"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  die "compose file not found: $COMPOSE_FILE"
fi

if ! command -v docker >/dev/null 2>&1; then
  die "docker is required"
fi

if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required (docker compose)"
fi

export COMPOSE_PROJECT_NAME="$PROJECT_NAME"

is_prod_compose() {
  [[ "$(basename "$COMPOSE_FILE")" == "docker-compose.prod.yml" ]]
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    die "set $name in the environment or .env before using $COMPOSE_FILE"
  fi
}

dotenv_defines() {
  local name="$1"
  [[ -f .env ]] || return 1
  grep -Eq "^[[:space:]]*(export[[:space:]]+)?${name}[[:space:]]*=" .env
}

generate_secret() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import secrets; print(secrets.token_urlsafe(32))'
  else
    date +%s%N | sha256sum | awk '{print $1}'
  fi
}

ensure_dev_secret_file() {
  local name="$1"
  local path="$2"
  if [[ -n "${!name:-}" ]] || dotenv_defines "$name"; then
    return 0
  fi
  mkdir -p "$(dirname "$path")"
  if [[ ! -s "$path" ]]; then
    umask 077
    generate_secret >"$path"
  fi
  export "$name"="$(<"$path")"
}

if is_prod_compose; then
  case "$ACTION" in
    start|restart|build|config)
      require_env POSTGRES_PASSWORD
      require_env NEO4J_PASSWORD
      require_env AGENT_GATEWAY_API_KEY
      require_env AGENT_MEMORY_SERVICE_API_KEY
      require_env AUTH_JWT_SECRET
      require_env AUTH_REFRESH_TOKEN_HASH_SECRET
      require_env PORTAL_SECRETS_KEY
      require_env HOST_MODEL_PATH
      ;;
    *)
      # docker compose still expands required variables for stop/status/logs.
      export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-compose_parse_only}"
      export NEO4J_PASSWORD="${NEO4J_PASSWORD:-compose_parse_only}"
      export AGENT_GATEWAY_API_KEY="${AGENT_GATEWAY_API_KEY:-compose_parse_only}"
      export AGENT_MEMORY_SERVICE_API_KEY="${AGENT_MEMORY_SERVICE_API_KEY:-compose_parse_only}"
      export AUTH_JWT_SECRET="${AUTH_JWT_SECRET:-compose_parse_only}"
      export AUTH_REFRESH_TOKEN_HASH_SECRET="${AUTH_REFRESH_TOKEN_HASH_SECRET:-compose_parse_only}"
      export PORTAL_SECRETS_KEY="${PORTAL_SECRETS_KEY:-compose_parse_only}"
      export HOST_MODEL_PATH="${HOST_MODEL_PATH:-$ROOT_DIR/models}"
      ;;
  esac
else
  ensure_dev_secret_file NEO4J_PASSWORD "$ROOT_DIR/.runtime/dev_neo4j_password"
  ensure_dev_secret_file POSTGRES_PASSWORD "$ROOT_DIR/.runtime/dev_postgres_password"
  ensure_dev_secret_file AGENT_GATEWAY_API_KEY "$ROOT_DIR/.runtime/dev_gateway_api_key"
  ensure_dev_secret_file AGENT_MEMORY_SERVICE_API_KEY "$ROOT_DIR/.runtime/dev_memory_service_key"
  ensure_dev_secret_file AUTH_JWT_SECRET "$ROOT_DIR/.runtime/dev_auth_jwt_secret"
  ensure_dev_secret_file AUTH_REFRESH_TOKEN_HASH_SECRET "$ROOT_DIR/.runtime/dev_refresh_token_hash_secret"
  ensure_dev_secret_file PORTAL_SECRETS_KEY "$ROOT_DIR/.runtime/dev_portal_secrets_key"
  export HOST_MODEL_PATH="${HOST_MODEL_PATH:-$ROOT_DIR/models}"
  export PORTAL_PORT="${PORTAL_PORT:-3000}"
  export GATEWAY_PORT="${GATEWAY_PORT:-8080}"
  export MEMORY_PORT="${MEMORY_PORT:-8001}"
  export EMBEDDING_PORT="${EMBEDDING_PORT:-7999}"
  export POSTGRES_PORT="${POSTGRES_PORT:-15432}"
  export REDIS_PORT="${REDIS_PORT:-16379}"
  export NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-17474}"
  export NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-17687}"
  export AGENT_MEMORY_VECTOR_ENABLED="${AGENT_MEMORY_VECTOR_ENABLED:-0}"
  mkdir -p "$HOST_MODEL_PATH"
fi

export POSTGRES_DB="${POSTGRES_DB:-agent_memory}"
export POSTGRES_USER="${POSTGRES_USER:-agent_memory}"

if [[ "${AGENT_MEMORY_VECTOR_ENABLED:-0}" == "1" && "$COMPOSE_FILE" == "docker-compose.yml" ]]; then
  if [[ ",${COMPOSE_PROFILES:-}," != *",vector,"* ]]; then
    export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}vector"
  fi
fi

compose() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

compose_all_profiles() {
  COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}vector" \
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

process_matches_project() {
  local pid="$1"
  local cmd="$2"
  local cwd=""

  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  if [[ "$cwd" == "$ROOT_DIR"* ]]; then
    return 0
  fi
  if [[ "$cmd" == *"$ROOT_DIR"* ]]; then
    return 0
  fi
  return 1
}

project_pids() {
  local line pid cmd
  ps -eo pid=,command= | while read -r line; do
    pid="${line%% *}"
    cmd="${line#* }"
    [[ -n "$pid" && "$pid" != "$cmd" ]] || continue
    case "$cmd" in
      *scripts/services.sh*|*"scripts/services.sh"*|*" rg "*|*"ps -eo"*|*"bash -c"*|*"zsh -c"*)
        continue
        ;;
    esac
    case "$cmd" in
      *"python -m uvicorn agent_memory_service.app:create_app"*|*"python -m uvicorn agent_memory_service.gateway.app:app"*|*"python -m uvicorn agent_runtime.product.agent_gateway:app"*|*"scripts/memory_distill_worker.py"*|*"scripts.memory_distill_worker"*|*"node "*"/next"*" dev "*|*"next-server"*|*"npm run dev:custom"*)
        if process_matches_project "$pid" "$cmd"; then
          printf '%s\n' "$pid"
        fi
        ;;
    esac
  done
}

kill_local() {
  local pids remaining pid
  pids=()
  while IFS= read -r pid; do
    pids+=("$pid")
  done < <(project_pids | sort -u)
  if ((${#pids[@]} == 0)); then
    log "no old local project processes found"
    return 0
  fi

  log "stopping old local project processes: ${pids[*]}"
  for pid in "${pids[@]}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  sleep 2

  remaining=()
  while IFS= read -r pid; do
    remaining+=("$pid")
  done < <(project_pids | sort -u)
  if ((${#remaining[@]})); then
    log "force stopping old local project processes: ${remaining[*]}"
    for pid in "${remaining[@]}"; do
      kill -9 "$pid" >/dev/null 2>&1 || true
    done
  fi

  rm -f memory_service.pid agent_gateway.pid distill_worker.pid portal-ui.pid
}

wait_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-120}"

  if ! command -v curl >/dev/null 2>&1; then
    log "curl not found; skipping wait for $name"
    return 0
  fi

  log "waiting for $name: $url"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is reachable"
      return 0
    fi
    sleep 1
  done
  log "$name did not become reachable in time; check: scripts/services.sh logs $name"
  return 1
}

wait_compose_http() {
  local name="$1"
  local service="$2"
  local url="$3"
  local attempts="${4:-120}"

  log "waiting for $name inside compose service '$service': $url"
  for _ in $(seq 1 "$attempts"); do
    if compose exec -T "$service" curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is reachable"
      return 0
    fi
    sleep 1
  done
  log "$name did not become reachable in time; check: scripts/services.sh logs $service"
  return 1
}

print_urls() {
  cat <<URLS

Services are starting/running:
  Portal:    http://127.0.0.1:${PORTAL_PORT:-3000}
  Gateway:   http://127.0.0.1:${GATEWAY_PORT:-8080}
  Memory:    internal Docker service memory:8001
  Embedding: disabled unless AGENT_MEMORY_VECTOR_ENABLED=1
  Neo4j:     http://127.0.0.1:${NEO4J_HTTP_PORT:-7474}

Useful commands:
  scripts/services.sh status
  scripts/services.sh logs gateway
  scripts/services.sh stop
  scripts/services.sh --build restart
URLS
}

build_stack() {
  log "building compose project '$PROJECT_NAME' using $COMPOSE_FILE"
  compose build
}

start_stack() {
  kill_local
  if [[ "$BUILD_IMAGES" == "1" ]]; then
    log "starting compose project '$PROJECT_NAME' using $COMPOSE_FILE with image rebuild"
    compose up -d --build
  else
    log "starting compose project '$PROJECT_NAME' using $COMPOSE_FILE without image rebuild"
    compose up -d
  fi

  if [[ "$COMPOSE_FILE" == "docker-compose.yml" ]]; then
    wait_compose_http "memory" "memory" "http://127.0.0.1:8001/health" 120 || true
    wait_http "gateway" "http://127.0.0.1:${GATEWAY_PORT:-8080}/health" 120 || true
    wait_http "portal" "http://127.0.0.1:${PORTAL_PORT:-3000}" 180 || true
  fi

  print_urls
}

stop_stack() {
  log "stopping compose project '$PROJECT_NAME' using $COMPOSE_FILE"
  compose_all_profiles down --remove-orphans
  kill_local
}

case "$ACTION" in
  start)
    start_stack ;;
  build)
    build_stack ;;
  stop)
    stop_stack ;;
  restart)
    stop_stack
    start_stack ;;
  status|ps)
    compose ps
    mapfile -t pids < <(project_pids | sort -u)
    if ((${#pids[@]})); then
      log "old local project processes still running: ${pids[*]}"
    fi ;;
  logs)
    compose logs -f --tail=200 "${EXTRA_ARGS[@]}" ;;
  config)
    compose config ;;
  kill-local)
    kill_local ;;
  destroy)
    stop_stack
    log "removing named volumes for compose project '$PROJECT_NAME'"
    compose down -v --remove-orphans ;;
  *)
    usage
    die "unknown command: $ACTION" ;;
esac
