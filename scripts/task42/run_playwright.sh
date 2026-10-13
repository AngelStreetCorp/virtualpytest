#!/usr/bin/env bash
# Serve the BUILT candidate frontend (frontend/dist from `vite build`) with `vite preview`
# and run the TASK-42 Playwright spec against it. Every /server/** call is intercepted by
# the spec's fixtures, so no backend, database or shared environment is touched.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${TASK42_PREVIEW_PORT:-4719}"
SPEC="${1:-specs/task42-run-management.spec.ts}"
[[ -f "$ROOT/frontend/dist/index.html" ]] || { echo "frontend/dist missing — run vite build first" >&2; exit 3; }
cd "$ROOT/frontend"
./node_modules/.bin/vite preview --port "$PORT" --strictPort --host 127.0.0.1 >"${TMPDIR:-/tmp}/task42_preview.log" 2>&1 &
PREVIEW=$!
trap 'kill $PREVIEW 2>/dev/null || true' EXIT
# vite preview serves HTTPS with a self-signed certificate whenever vite.config enables basicSsl.
for _ in $(seq 1 60); do curl -skf "https://127.0.0.1:$PORT/" >/dev/null && break; sleep 0.5; done
cd "$ROOT/tests/e2e/playwright"
E2E_BASE_URL="https://127.0.0.1:$PORT" TASK42_MOCKED=1 ./node_modules/.bin/playwright test --config task42.config.js "$SPEC"
