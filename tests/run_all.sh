#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TESTS_DIR="$ROOT_DIR/tests"

run_backend_server() {
  if command -v pytest >/dev/null 2>&1; then
    echo "[tests] backend_server: running pytest suite"
    pytest "$TESTS_DIR/backend_server" -v
    # TASK-90: tv_app output of vpt-monitor-img must never change (replay of a recorded fixture)
    pytest "$TESTS_DIR/backend_host/test_monitor_replay.py" -v
  else
    echo "[tests] backend_server: pytest not installed (skipped)"
  fi
}

run_rollout() {
  # Rollout tooling (the customer bundle builder CLI), not the backend server. Pure unit logic:
  # no server, no device, no network.
  #
  # Prefers `python3 -m pytest` over a bare `pytest`: the module form finds the interpreter's own
  # pytest when the console script is not on PATH (a venv-less checkout), which is the common case
  # here — a bare `pytest` probe skips the suite instead of running it.
  if python3 -c "import pytest" >/dev/null 2>&1; then
    echo "[tests] rollout: running pytest suite"
    python3 -m pytest "$TESTS_DIR/rollout" -v
  else
    echo "[tests] rollout: pytest not installed (skipped)"
  fi
}

run_frontend() {
  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "[tests] frontend: node_modules missing in frontend/ (skipped)"
    return
  fi

  if (cd "$ROOT_DIR/frontend" && node -e "require.resolve('vitest/package.json')" >/dev/null 2>&1); then
    echo "[tests] frontend: running vitest component suite"
    (cd "$ROOT_DIR/frontend" && npx vitest run --config ../tests/frontend/vitest.config.ts)
  else
    echo "[tests] frontend: vitest not installed (install test deps first) (skipped)"
  fi
}

run_e2e() {
  local smoke_runner="$TESTS_DIR/e2e/playwright/run_e2e_smoke.sh"
  local viewport_runner="$TESTS_DIR/e2e/playwright/run_e2e_viewport.sh"

  if [[ -x "$smoke_runner" ]]; then
    echo "[tests] e2e/playwright: running smoke suite"
    "$smoke_runner"
  else
    echo "[tests] e2e/playwright: smoke runner not found ($smoke_runner) (skipped)"
  fi

  if [[ -x "$viewport_runner" ]]; then
    echo "[tests] e2e/playwright: running viewport suite"
    "$viewport_runner"
  else
    echo "[tests] e2e/playwright: viewport runner not found ($viewport_runner) (skipped)"
  fi
}

run_target() {
  case "$1" in
    backend_server) run_backend_server ;;
    rollout) run_rollout ;;
    frontend) run_frontend ;;
    e2e) run_e2e ;;
    *)
      echo "Unknown target: $1"
      echo "Usage: tests/run_all.sh [backend_server|rollout|frontend|e2e|all]"
      exit 2
      ;;
  esac
}

target="${1:-all}"

if [[ "$target" == "all" ]]; then
  run_backend_server
  run_rollout
  run_frontend
  run_e2e
else
  run_target "$target"
fi
