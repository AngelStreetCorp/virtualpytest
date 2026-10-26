#!/usr/bin/env bash
# Run a command in its OWN process group and kill the whole group when it ends badly.
#
# Why: `timeout N cmd` only signals `cmd`. vitest's pool workers are grandchildren, so
# they survive, get adopted by launchd (PPID 1) and eat 150 MB-1.4 GB each until reboot.
# A detached watchdog kills the group on timeout AND if this wrapper is SIGKILLed
# (agent cancel / session archive), which no trap can catch.
#
# Usage: scripts/run-guarded.sh <timeout-seconds> -- <command> [args...]
set -uo pipefail

limit="${1:?usage: run-guarded.sh <timeout-seconds> -- cmd...}"; shift
[[ "${1:-}" == "--" ]] && shift
[[ $# -gt 0 ]] || { echo "usage: run-guarded.sh <timeout-seconds> -- cmd..." >&2; exit 64; }

set -m                          # job control: each background job gets its own pgid
"$@" &
child=$!
wrapper=$$

kill_group() {                  # TERM, then KILL anything still alive after 3 s
  kill -TERM -- "-$child" 2>/dev/null || return 0
  for _ in 1 2 3 4 5 6; do
    kill -0 -- "-$child" 2>/dev/null || return 0
    sleep 0.5
  done
  kill -KILL -- "-$child" 2>/dev/null || true
}

# Watchdog: outlives the wrapper on purpose.
(
  end=$(( $(date +%s) + limit ))
  while kill -0 "$child" 2>/dev/null; do
    if ! kill -0 "$wrapper" 2>/dev/null || [[ $(date +%s) -ge $end ]]; then
      kill_group
      exit 0
    fi
    sleep 2
  done
  kill_group                    # child exited: reap any workers it left behind
) >/dev/null 2>&1 &
disown

trap 'kill_group; exit 143' INT TERM HUP
wait "$child"; rc=$?
kill_group
exit "$rc"
