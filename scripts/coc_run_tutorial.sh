#!/bin/bash
# Submit /server/script/execute on vpt-pi1 (the host's local backend at :5109).
# Reads API key + team UUID from /opt/virtualpytest/.env. Polls /server/script/status/<id>.
# Requires device1 (S21 FE over HDMI).
#
# Usage:
#   coc_run_tutorial.sh                          # 1800s tutorial, 60 cycles
#   coc_run_tutorial.sh 600 30                   # shorter
#   SCRIPT=game_clashofclans coc_run_tutorial.sh # run the farm bot instead
set -eu

DURATION="${1:-1800}"
CYCLES="${2:-60}"
SCRIPT="${SCRIPT:-game_clashofclans_tutorial}"
TEAM_UUID="${TEAM_UUID:-7fdeb4bb-3639-4ec3-959f-b54769a219ce}"

API_KEY=$(sudo -n cat /opt/virtualpytest/.env | grep '^API_KEY=' | tail -1 | cut -d= -f2 | tr -d '"' | tr -d "'")
SERVER="${SERVER_URL:-http://localhost:5109}"

PARAMS="--userinterface clashofclans-android-mobile --max_runtime $DURATION --max_cycles $CYCLES --attack_opt_in false"

BODY=$(cat <<JSON
{"host_name":"vpt-pi1","device_id":"device1","script_name":"$SCRIPT","userinterface_name":"clashofclans-android-mobile","parameters":"$PARAMS"}
JSON
)

echo "POST $SERVER/server/script/execute?team_id=$TEAM_UUID"
echo "  script=$SCRIPT  duration=${DURATION}s  cycles=${CYCLES}"
RESP=$(curl -sS -X POST "$SERVER/server/script/execute?team_id=$TEAM_UUID" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY")
TASK_ID=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('task_id',d.get('id','')))")
echo "task_id=$TASK_ID"
echo "$RESP" | python3 -m json.tool 2>/dev/null | head -25

if [ -z "${TASK_ID:-}" ]; then
  echo "ERROR: no task_id in response" >&2
  exit 2
fi

echo "polling $SERVER/server/script/status/$TASK_ID every 8s..."
SECS=0
while [ "$SECS" -lt "$((DURATION+30))" ]; do
  sleep 8
  SECS=$((SECS+8))
  STAT=$(curl -sS "$SERVER/server/script/status/$TASK_ID?team_id=$TEAM_UUID" \
    -H "X-API-Key: $API_KEY" 2>&1)
  STATUS=$(echo "$STAT" | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)
  if isinstance(d, dict):
    t = d.get('task') or {}
    print(t.get('status') or d.get('status') or '')
except Exception:
  print('')
")
  echo "[t+${SECS}s] status=$STATUS"
  case "$STATUS" in
    completed|failed|error|canceled) break;;
  esac
done

echo
echo "final status:"
curl -sS "$SERVER/server/script/status/$TASK_ID?team_id=$TEAM_UUID" \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool 2>/dev/null | head -80
