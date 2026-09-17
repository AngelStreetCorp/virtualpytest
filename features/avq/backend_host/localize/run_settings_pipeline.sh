#!/bin/bash
# Autonomous settings-subtree pipeline: explore (loop until status=complete) -> validate -> push.
# Uses the explore EXIT CODE (10 = more work) for convergence, NOT a probe-count-stall — so pane
# DOWN frontiers (rows) get discovered even on rounds spent entirely on a re-anchor.
# Every device round-trip is timestamped ([HH:MM:SS +Ns]) so you can see where live time goes.
set -u
cd "$(dirname "$0")"
set -a; source ../../../../.env; set +a
export VPT_MCP_AUTHORIZATION="Bearer $MCP_SECRET_KEY"
PY=~/virtualpytest/venv/bin/python
RUN="${1:?usage: run_settings_pipeline.sh <run-dir> <ui-name>}"
UI="${2:?usage: run_settings_pipeline.sh <run-dir> <ui-name>}"
EXIT_MORE_WORK=10

echo "=== EXPLORE (loop until status=complete) ==="
for i in $(seq 1 60); do
  $PY -u auto_build_mcp_live.py explore --run-dir "$RUN" --under settings --max-depth 3 --max-actions 40
  rc=$?
  n=$($PY -c "import json;print(len(json.load(open('$RUN/state.json'))['nodes']))")
  echo "== ROUND $i rc=$rc nodes=$n =="
  [ "$rc" -eq 0 ] && { echo "explore COMPLETE"; break; }
  [ "$rc" -ne "$EXIT_MORE_WORK" ] && { echo "explore ERROR rc=$rc"; exit "$rc"; }
done

echo "=== VALIDATE ==="
$PY -u auto_build_mcp_live.py validate --run-dir "$RUN" --under settings --only-failed

echo "=== PUSH ==="
env $(grep -E "^(SUPABASE_URL|SUPABASE_ANON_KEY)=" ~/virtualpytest/.env | xargs) \
  $PY push_autobuild_to_db.py --run-dir "$RUN" --ui-name "$UI"
echo "PIPELINE_DONE"
