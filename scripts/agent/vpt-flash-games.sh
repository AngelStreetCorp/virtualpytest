#!/usr/bin/env bash
# CoC Flash data runs on idle devices (TASK-164).
#
# One dispatcher tick a minute, and the dispatcher does the lease work: the tick claims the lease
# for the whole run (vpt-lease, never --force), renews it while the run lasts and releases it
# when the run ends. A busy lease is waited for, never forced.
#
# The dispatcher runs from the lane clone (~/.local/share/game-dispatch/repo), never from the shared
# checkout of ~/virtualpytest: the other Claude Code sessions on this host switch that checkout's
# branch under each other. The unit that runs this script syncs the clone before every tick.
#
# Stopping the unit (SIGTERM) ends the loop cleanly: the tick in flight is allowed to finish, no
# orphan process is left, and a run that is still on the device keeps its lease until the run's
# own TTL instead of losing the device to another agent.
#
# Logs: stdout goes to the journal (journalctl --user -u vpt-flash-games.service), the tick's own
# lines go to ~/.cache/game-dispatch/flash-loop.log, and every finished run is appended to
# ~/.cache/game-dispatch/runs.jsonl by the dispatcher.
set -uo pipefail

REPO="${REPO:-$HOME/.local/share/game-dispatch/repo}"
LOG="${LOG:-$HOME/.cache/game-dispatch/flash-loop.log}"
STATE="${STATE:-$HOME/.cache/game-dispatch/state.json}"
TICK_S="${TICK_S:-60}"

mkdir -p "$(dirname "${LOG}")"

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "${LOG}"; }

running() {
  python3 - "${STATE}" <<'PY' 2>/dev/null || echo ""
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("coc-flash", {}).get("phase", ""))
except Exception:
    print("")
PY
}

# Why the job is (not) starting right now — the same line `game_dispatch.py plan` prints. Without
# it the log is silent between the start slots and a quiet log looks like a dead loop.
reason() {
  GAME_JOBS=coc-flash python3 "${REPO}/scripts/agent/game_dispatch.py" plan 2>/dev/null | head -1
}

stopping() {
  if [ "$(running)" = "running" ]; then
    say "stopping: a CoC Flash run is still on the device - it keeps its lease until the run's own TTL"
  else
    say "stopping: no run in flight, every lease is released"
  fi
  exit 0
}
trap stopping TERM INT

say "flash game loop started (pid $$), one tick every ${TICK_S}s, dispatcher from ${REPO}"
while true; do
  GAME_JOBS=coc-flash GAME_MAX_CONCURRENT=2 python3 "${REPO}/scripts/agent/game_dispatch.py" tick >>"${LOG}" 2>&1
  say "tick: $(reason)"
  sleep "${TICK_S}" &
  wait $!    # so the trap above fires at once on SIGTERM instead of after the sleep
done
