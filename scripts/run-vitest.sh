#!/usr/bin/env bash
# Run the frontend vitest suite with the whole worker tree reaped on timeout/cancel.
#   scripts/run-vitest.sh [vitest args]       e.g. scripts/run-vitest.sh Rec DeviceControl
# Timeout: VPT_VITEST_TIMEOUT seconds (default 400). Run from any directory.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/frontend"
exec "$root/scripts/run-guarded.sh" "${VPT_VITEST_TIMEOUT:-400}" -- \
  ./node_modules/.bin/vitest run --config ../tests/frontend/vitest.config.ts "$@"
