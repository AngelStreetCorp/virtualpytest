#!/usr/bin/env bash
# Wait until the live debug server is stable before a CI job tests against it.
# Agents redeploy node1-vpt many times a day (update_core.sh restarts the server, nginx answers 500
# meanwhile); CI used to start regardless and fail with HTTP 500 / "Failed to fetch".
#
# Signal: GET $SERVER_URL/server/health must answer 200 STABLE_N times in a row, STEP_S apart.
# This only guards the START of a job. The jobs that sweep the live server also hold the
# node1-vpt lease for the duration (scripts/ci/lease_guard.sh), so update_core.sh queues the
# deploy instead of restarting the server mid-run; that closes the window this script cannot see.
# Never fails the job: after MAX_WAIT_S it prints why and lets the tests run (they report the outage).
set -u
SERVER_URL="${SERVER_URL:-${E2E_BASE_URL:-}}"
SERVER_URL="${SERVER_URL%/}"
STABLE_N="${STABLE_N:-3}"
STEP_S="${STEP_S:-5}"
MAX_WAIT_S="${MAX_WAIT_S:-900}"

if [ -z "$SERVER_URL" ]; then
  echo "wait_for_server: SERVER_URL not set - not waiting."
  exit 0
fi

start=$(date +%s)
ok=0
last="no answer"
while :; do
  code=$(curl -sk -L -o /dev/null -m 10 -w '%{http_code}' "$SERVER_URL/server/health" 2>/dev/null || true)
  if [ "$code" = "200" ]; then
    ok=$((ok + 1))
    if [ "$ok" -ge "$STABLE_N" ]; then
      echo "wait_for_server: $SERVER_URL/server/health answered 200 x$STABLE_N after $(( $(date +%s) - start ))s."
      exit 0
    fi
  else
    ok=0
    last="HTTP ${code:-000}"
    echo "wait_for_server: health -> $last (a deploy is probably restarting the server), waiting..."
  fi
  if [ $(( $(date +%s) - start )) -ge "$MAX_WAIT_S" ]; then
    echo "wait_for_server: gave up after ${MAX_WAIT_S}s (last: $last, stable ${ok}/${STABLE_N}); running the tests anyway."
    exit 0
  fi
  sleep "$STEP_S"
done
