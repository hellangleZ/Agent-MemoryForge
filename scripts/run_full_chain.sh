#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf "[run_full_chain] %s\n" "$*"
}

die() {
  printf "[run_full_chain] ERROR: %s\n" "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: scripts/run_full_chain.sh [options]

Runs the recommended local full-chain flow:
  - ./start_services.sh start
  - memory service (uvicorn)
  - product gateway (uvicorn)
  - optional distill worker
  - optional demo

Options:
  --main-env <path>        Source env file for main reasoning LLM (default: config/openai_main.env)
  --planner-env <path>     Source env file for context planner (default: config/context_planner.env)
  --distill-env <path>     Source env file for distill worker (default: config/distill_worker.env)
  --memory-url <url>       Memory service URL (default: http://127.0.0.1:8001)
  --gateway-port <port>    Gateway port (default: 8080)
  --no-planner             Do not source planner env
  --no-distill             Do not start distill worker
  --no-demo                Do not run demo
  --once                   Start services, run demo once, then stop
  --verbose                Do not suppress child process output

Examples:
  scripts/run_full_chain.sh
  scripts/run_full_chain.sh --no-distill --no-demo
  scripts/run_full_chain.sh --once
USAGE
}

MAIN_ENV="config/openai_main.env"
PLANNER_ENV="config/context_planner.env"
DISTILL_ENV="config/distill_worker.env"
MEMORY_URL="http://127.0.0.1:8001"
MEMORY_PORT="8001"
GATEWAY_PORT="8080"
NO_PLANNER="0"
NO_DISTILL="0"
NO_DEMO="0"
ONCE="0"
VERBOSE="0"

PIDS=()

cleanup() {
  if ((${#PIDS[@]})); then
    log "stopping child processes..."
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done
    sleep 0.5
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    done
  fi
}

trap cleanup EXIT INT TERM

while [[ $# -gt 0 ]]; do
  case "$1" in
    --main-env)
      MAIN_ENV="$2"; shift 2 ;;
    --planner-env)
      PLANNER_ENV="$2"; shift 2 ;;
    --distill-env)
      DISTILL_ENV="$2"; shift 2 ;;
    --memory-url)
      MEMORY_URL="$2"; shift 2 ;;
    --gateway-port)
      GATEWAY_PORT="$2"; shift 2 ;;
    --no-planner)
      NO_PLANNER="1"; shift 1 ;;
    --no-distill)
      NO_DISTILL="1"; shift 1 ;;
    --no-demo)
      NO_DEMO="1"; shift 1 ;;
    --once)
      ONCE="1"; shift 1 ;;
    --verbose)
      VERBOSE="1"; shift 1 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "unknown argument: $1" ;;
  esac
done

if command -v python >/dev/null 2>&1; then
  MEMORY_PORT="$(MEMORY_URL="$MEMORY_URL" python - <<'PY'
from urllib.parse import urlparse
import os

u = os.environ.get('MEMORY_URL', 'http://127.0.0.1:8001')
p = urlparse(u)
if p.port:
    print(p.port)
PY
  )"
fi

cd "$ROOT_DIR"

if [[ ! -f "$MAIN_ENV" ]]; then
  die "missing main env file: $MAIN_ENV (see docs/RUN_FULL_CHAIN.md)"
fi

log "starting infrastructure via ./start_services.sh start"
./start_services.sh start

log "loading env: $MAIN_ENV"
set -a
# shellcheck disable=SC1090
source "$MAIN_ENV"
set +a

if [[ "$NO_PLANNER" == "0" && -f "$PLANNER_ENV" ]]; then
  log "loading env: $PLANNER_ENV"
  set -a
  # shellcheck disable=SC1090
  source "$PLANNER_ENV"
  set +a
fi

export MEMORY_SERVICE_URL="$MEMORY_URL"

log "starting memory service (uvicorn create_app --factory)"
if [[ "$VERBOSE" == "1" ]]; then
  python -m uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port "$MEMORY_PORT" &
else
  python -m uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port "$MEMORY_PORT" >/dev/null 2>&1 &
fi
PIDS+=("$!")

log "waiting for memory service health"
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 60); do
    if curl -fsS "$MEMORY_URL/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
fi

log "starting gateway (uvicorn)"
if [[ "$VERBOSE" == "1" ]]; then
  python -m uvicorn agent_runtime.product.agent_gateway:app --host 0.0.0.0 --port "$GATEWAY_PORT" &
else
  python -m uvicorn agent_runtime.product.agent_gateway:app --host 0.0.0.0 --port "$GATEWAY_PORT" >/dev/null 2>&1 &
fi
PIDS+=("$!")

log "waiting for gateway health"
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$GATEWAY_PORT/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.2
  done
fi

if [[ "$NO_DISTILL" == "0" && -f "$DISTILL_ENV" ]]; then
  log "loading env: $DISTILL_ENV"
  set -a
  # shellcheck disable=SC1090
  source "$DISTILL_ENV"
  set +a

  log "starting distill worker"
  if [[ "$VERBOSE" == "1" ]]; then
    python -m scripts.memory_distill_worker &
  else
    python -m scripts.memory_distill_worker >/dev/null 2>&1 &
  fi
  PIDS+=("$!")
fi

if [[ "$NO_DEMO" == "0" ]]; then
  log "running demo"
  python examples/project_management_demo_real.py
fi

if [[ "$ONCE" == "1" ]]; then
  log "--once completed"
  exit 0
fi

log "services are running (Ctrl+C to stop)"
while true; do
  sleep 5
done
