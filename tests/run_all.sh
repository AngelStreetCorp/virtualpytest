#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TESTS_DIR="$ROOT_DIR/tests"

run_backend_server() {
  if command -v pytest >/dev/null 2>&1; then
    echo "[tests] backend_server: running pytest suite"
    pytest "$TESTS_DIR/backend_server" -v
  else
    echo "[tests] backend_server: pytest not installed (skipped)"
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
    frontend) run_frontend ;;
    e2e) run_e2e ;;
    *)
      echo "Unknown target: $1"
      echo "Usage: tests/run_all.sh [backend_server|frontend|e2e|all]"
      exit 2
      ;;
  esac
}

target="${1:-all}"

if [[ "$target" == "all" ]]; then
  run_backend_server
  run_frontend
  run_e2e
else
  run_target "$target"
fi
