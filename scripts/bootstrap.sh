#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/bootstrap.sh <preset> [--venv .venv]

Presets:
  minimal   Install minimal library deps (pip -e .)
  full      Install full chain deps (pip -e '.[all]')
  dev       Install dev tools + full chain deps (pip -e '.[dev,all]')
  docs      Run docs smoke check (local links)

Options:
  --venv <path>   Create/use a virtualenv at <path> (default: .venv)

Notes:
  - If your Python is "externally managed" (PEP 668), you should use --venv.
  - This script is intentionally small; the real dependency graph lives in
    pyproject.toml extras.
  - To sanity-check documentation links: scripts/bootstrap.sh docs
USAGE
}

PRESET="${1:-}"
shift || true

VENV_PATH=".venv"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      VENV_PATH="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$PRESET" ]]; then
  usage
  exit 2
fi

case "$PRESET" in
  minimal) EXTRAS="" ;;
  full) EXTRAS="[all]" ;;
  dev) EXTRAS="[dev,all]" ;;
  docs)
    cd "$ROOT_DIR"
    python -m scripts.docs_smoke_check
    exit 0
    ;;
  *)
    echo "Unknown preset: $PRESET" >&2
    usage
    exit 2
    ;;
esac

cd "$ROOT_DIR"

python -m venv "$VENV_PATH"

# shellcheck disable=SC1090
source "$VENV_PATH/bin/activate"

python -m pip install -U pip

if [[ -z "$EXTRAS" ]]; then
  python -m pip install -e .
else
  python -m pip install -e ".${EXTRAS}"
fi

echo "[bootstrap] installed preset '$PRESET' into $VENV_PATH"
