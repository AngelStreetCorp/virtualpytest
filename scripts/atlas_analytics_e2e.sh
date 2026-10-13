#!/usr/bin/env bash
# Post-deploy regression suite for Atlas analytics + Agent Chat (real browser, deployed bundle, main + Pi server).
# Usage: scripts/atlas_analytics_e2e.sh [OUT_DIR]        (default /tmp/atlas-e2e-<timestamp>)
# Env: E2E_AUTO_SIGN_TOKEN (default: AUTO_SIGN_TOKEN from ~/virtualpytest/.env or ./.env; never printed),
#      E2E_BASE_URL, E2E_SERVERS=main,pi, E2E_ONLY, E2E_HEALTH_RETRY_LIVE=0 (older bundle), E2E_SKIP_HEALTH_RETRY=1,
#      E2E_GRAFANA_USER / E2E_GRAFANA_PASSWORD (environment only, never hard-coded or printed; without them the Grafana panel checks are NA),
#      SKIP_QUEUE_WAIT=1, QUEUE_WAIT_MAX_S (default 1800), PW_NODE_MODULES.
# Exit code: 0 = no FAIL (XFAIL/FLAKY allowed), 1 = at least one FAIL, 2/3 = setup error.
# Never takes device control; only sends chat prompts. See docs/agent/ai/ATLAS_ANALYTICS.md "Post-deploy check".
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC="$ROOT/tests/e2e/playwright/atlas/atlas_analytics_e2e.js"
OUT="${1:-${E2E_OUT_DIR:-/tmp/atlas-e2e-$(date +%Y%m%d-%H%M%S)}}"
mkdir -p "$OUT"

if [ -z "${E2E_AUTO_SIGN_TOKEN:-}" ]; then
  for f in "$ROOT/.env" "$HOME/virtualpytest/.env"; do
    [ -f "$f" ] && E2E_AUTO_SIGN_TOKEN="$(grep -m1 '^AUTO_SIGN_TOKEN=' "$f" | cut -d= -f2- | tr -d '"')" && [ -n "$E2E_AUTO_SIGN_TOKEN" ] && break
  done
fi
[ -n "${E2E_AUTO_SIGN_TOKEN:-}" ] || { echo "E2E_AUTO_SIGN_TOKEN not set and no AUTO_SIGN_TOKEN in .env" >&2; exit 2; }
export E2E_AUTO_SIGN_TOKEN E2E_OUT_DIR="$OUT"

# @playwright/test: the repo's own install, else any sibling worktree's.
if [ ! -d "$ROOT/tests/e2e/playwright/node_modules/@playwright/test" ] && [ -z "${PW_NODE_MODULES:-}" ]; then
  for d in "$ROOT"/../*/tests/e2e/playwright/node_modules "$ROOT/frontend/node_modules"; do
    [ -d "$d/@playwright/test" ] && PW_NODE_MODULES="$d" && break
  done
fi
export PW_NODE_MODULES="${PW_NODE_MODULES:-}"
[ -d "$ROOT/tests/e2e/playwright/node_modules/@playwright/test" ] || [ -n "$PW_NODE_MODULES" ] || { echo "no @playwright/test found: cd tests/e2e/playwright && npm ci" >&2; exit 2; }

# 1. wait for the deploy queue to be idle (a deploy mid-suite makes every result meaningless)
waited=0; max="${QUEUE_WAIT_MAX_S:-1800}"
if [ "${SKIP_QUEUE_WAIT:-0}" != 1 ]; then
  while :; do
    busy="$(ssh proxmox '~/bin/vpt-lease deploy list' 2>&1 | grep -E 'state=(running|queued|pending|approved|waiting|claimed|active)' || true)"
    [ -z "$busy" ] && break
    [ "$waited" -ge "$max" ] && { echo "deploy queue still busy after ${max}s:" >&2; echo "$busy" >&2; exit 2; }
    echo "deploy queue busy, waiting (${waited}s): $(echo "$busy" | head -1 | cut -c1-140)"
    sleep 30; waited=$((waited + 30))
  done
  echo "deploy queue idle"
fi
echo "device leases: $(ssh proxmox '~/bin/vpt-lease list' 2>&1 | head -5 | tr '\n' ';')  (suite takes no device control)"

# 2. what is deployed
echo "server   VERSION: $(ssh server 'head -1 /opt/virtualpytest/VERSION.txt' 2>&1)"
echo "vpt-pi1  VERSION: $(ssh vpt-pi1 'head -1 /opt/virtualpytest/VERSION.txt' 2>&1)"
echo "out dir: $OUT"

# 3. the suite (it prints the frontend build it sees in the page footer per server)
node "$SPEC" 2>&1 | tee "$OUT/run.log"
rc=${PIPESTATUS[0]}
{ echo; echo "server VERSION: $(ssh server 'head -1 /opt/virtualpytest/VERSION.txt' 2>&1) | vpt-pi1: $(ssh vpt-pi1 'head -1 /opt/virtualpytest/VERSION.txt' 2>&1)"; } >> "$OUT/summary.md" 2>/dev/null
echo "summary: $OUT/summary.md  screenshots: $OUT/*.png  exit=$rc"
exit "$rc"
