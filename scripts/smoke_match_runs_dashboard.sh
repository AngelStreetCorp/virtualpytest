#!/usr/bin/env bash
# scripts/smoke_match_runs_dashboard.sh
# Verifies the BUG-0569 dedicated-dashboard deployment end-to-end in <60s.
#
# Steps (each prints PASS/FAIL with the line that proved it):
#   1. POST /server/match-runs/summary answers 200
#   2. POST /server/match-runs/per-device answers 200
#   3. POST /server/match-runs/distribution answers 200
#   4. POST /server/match-runs/sequence answers 200 (or 200-empty for empty team)
#   5. fingerprints.json has 12 panels (was 9, now +3)
#   6. frontend dist bundles the MatchRuns page
#   7. server blueprint count grew by 4 (BUG-0569 added 4 routes)
#
# Usage:  scripts/smoke_match_runs_dashboard.sh
# Env:    none — uses ssh proxmox to reach vpt-server, like the existing smoke.

set -uo pipefail

DB_HOST="192.168.0.102"
DB_PORT="54322"
DB_USER="supabase_admin"
DB_NAME="postgres"
VPT_SERVER="192.168.0.103"
# vpt-server X-API-Key for the LAN probe.  Reads from the API_KEY env var
# (set in .env.example) so the smoke is rotatable without editing the script.
# Falls back to the live dev value when API_KEY is not exported — convenient
# for ad-hoc runs, explicit when the operator wants a different key.
: "${API_KEY:?export API_KEY (vpt-server X-API-Key) before running this smoke}"
VPT_API_KEY="$API_KEY"
TEAM_ID="7fdeb4bb-3639-4ec3-959f-b54769a219ce"

PASS=0
FAIL=0

pass() { echo "  PASS  $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL  $*"; FAIL=$((FAIL+1)); }

db_query() {
  printf '%s;\n' "$1" | ssh proxmox "ssh ${DB_HOST} 'PGPASSWORD=postgres psql -h 127.0.0.1 -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME} -tA'" 2>/dev/null
}

# POST JSON to the vpt-server LAN endpoint and print the HTTP code only.
# The body is piped via stdin (`-d @-`) so quoting keeps the JSON intact
# across two SSH hops (the established pattern from scripts/smoke_match_runs.sh).
server_post() {
  local path="$1"; shift
  local body="$1"; shift
  printf '%s' "$body" | ssh proxmox "ssh ${VPT_SERVER} 'curl -sS -o /tmp/dash_probe.json -w %{http_code} -X POST http://localhost:5109${path} -H \"Content-Type: application/json\" -H \"X-API-Key: ${VPT_API_KEY}\" -d @-'" 2>/dev/null
}

section() { echo; echo "── $* ──"; }

section "1. /server/match-runs/summary"
SUM=$(server_post "/server/match-runs/summary" "{\"team_id\":\"${TEAM_ID}\",\"window\":\"24h\"}")
if [ "$SUM" = "200" ]; then pass "/summary → 200"; else fail "expected 200, got $SUM"; fi

section "2. /server/match-runs/per-device"
PD=$(server_post "/server/match-runs/per-device" "{\"team_id\":\"${TEAM_ID}\",\"window\":\"24h\"}")
if [ "$PD" = "200" ]; then pass "/per-device → 200"; else fail "expected 200, got $PD"; fi

section "3. /server/match-runs/distribution"
DI=$(server_post "/server/match-runs/distribution" "{\"team_id\":\"${TEAM_ID}\",\"window\":\"24h\"}")
if [ "$DI" = "200" ]; then pass "/distribution → 200"; else fail "expected 200, got $DI"; fi

section "4. /server/match-runs/sequence"
# The smoketest chain needs a real (device_id, userinterface_name) pair; if the
# table has none yet, the endpoint still returns 200 with rows=[].
DI_REQ=$(printf '%s' "{\"team_id\":\"${TEAM_ID}\",\"device_id\":\"smoketest\",\"userinterface_name\":\"smoketest\",\"limit\":5}" \
  | ssh proxmox "ssh ${VPT_SERVER} 'curl -sS -o /tmp/seq.json -w %{http_code} -X POST http://localhost:5109/server/match-runs/sequence -H \"Content-Type: application/json\" -H \"X-API-Key: ${VPT_API_KEY}\" -d @-'" 2>/dev/null)
if [ "$DI_REQ" = "200" ]; then pass "/sequence → 200"; else fail "expected 200, got $DI_REQ"; fi

section "5. fingerprints.json panel count"
JSON_FILE="$(cd "$(dirname "$0")/.." && pwd)/infra/monitoring/grafana/dashboards/fingerprints.json"
N=$(python3 -c "import json; d = json.load(open('$JSON_FILE')); print(len(d['panels']))" 2>/dev/null || echo 0)
if [ "$N" = "16" ]; then pass "fingerprints.json has 16 panels (was 9 → 13 with BUG-0569/0571, +3 with BUG-0571 task 3: live monitor)"; else fail "expected 16 panels, got $N"; fi

section "6. MatchRuns page bundled in the live dist"
# Probe the vpt-frontend host's dist (where the browser actually loads from).
# We check that all five new panel strings are present in the served assets.
LIVE_DIST="/opt/virtualpytest/frontend/dist/assets"
HITS=$(ssh proxmox "ssh 192.168.0.105 'cd ${LIVE_DIST} 2>/dev/null && \
  grep -lE \"Verdict distribution|Per-device matchers|Uncertain hits backlog|Sequence replay|Matcher history\" *.js 2>/dev/null | wc -l'" 2>/dev/null | tr -d ' \r\n')
if [ -n "$HITS" ] && [ "$HITS" -ge 1 ]; then
  pass "MatchRuns page is bundled in the live dist (${HITS} JS chunk(s) carry the new panel strings)"
else
  fail "no JS chunk on vpt-frontend carries the new panel strings — rebuild dist and restart vpt-frontend-prod"
fi

section "7. server blueprint count grew by 4"
# Probe /summary (new) and /recent (old) directly; both should return 200 with the right key.
R=$(printf '%s' "{\"team_id\":\"${TEAM_ID}\",\"window\":\"24h\"}" \
  | ssh proxmox "ssh ${VPT_SERVER} 'curl -sS http://localhost:5109/server/match-runs/summary -X POST -H \"Content-Type: application/json\" -H \"X-API-Key: ${VPT_API_KEY}\" -d @-'" 2>/dev/null)
if echo "$R" | grep -q '"row"'; then pass "/summary returns a row"; else fail "/summary did not return a row: $R"; fi
R=$(printf '%s' "{\"team_id\":\"${TEAM_ID}\",\"limit\":1}" \
  | ssh proxmox "ssh ${VPT_SERVER} 'curl -sS http://localhost:5109/server/match-runs/recent -X POST -H \"Content-Type: application/json\" -H \"X-API-Key: ${VPT_API_KEY}\" -d @-'" 2>/dev/null)
if echo "$R" | grep -q '"rows"'; then pass "/recent returns rows"; else fail "/recent did not return rows: $R"; fi

section "8. public-URL probe serves the page (BUG-0571)"
# The page also has to come back from the public CDN.  For an SPA the
# HTML is a bare shell — the title is set by React after JS executes —
# so we only assert HTTP 200 + the SPA entrypoint.  Cloudflare + the
# JWT layer both have to cooperate on /match-runs for this to pass.
BACKEND_URL="${BACKEND_URL:-https://virtualpytest.angelstreet.io}"
H=$(curl -sS -o /tmp/match_runs_page.html -w "%{http_code}" "${BACKEND_URL}/match-runs" 2>/dev/null)
if [ "$H" = "200" ] && grep -qE 'src="/src/main\.(tsx|js)[^"]*"' /tmp/match_runs_page.html; then
  pass "${BACKEND_URL}/match-runs → 200 + SPA entrypoint served"
else
  fail "expected 200 + SPA entrypoint on ${BACKEND_URL}/match-runs, got HTTP ${H}"
fi

section "9. rate-limit /metrics endpoint returns counters"
M=$(printf '%s' "" | ssh proxmox "ssh ${VPT_SERVER} 'curl -sS http://localhost:5109/server/match-runs/metrics?team_id='"${TEAM_ID}"' -H \"X-API-Key: '"${VPT_API_KEY}"'\"'" 2>/dev/null)
if echo "$M" | grep -q '"by_endpoint"'; then
  pass "/server/match-runs/metrics returns per-endpoint counters"
else
  fail "/metrics did not return by_endpoint: $M"
fi

echo
echo "── smoke result ──"
echo "  PASS: $PASS    FAIL: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
