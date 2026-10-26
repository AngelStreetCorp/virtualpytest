#!/usr/bin/env bash
# Kill orphaned vitest processes left behind when an interrupted test run's
# parent (bash wrapper / npm exec) died. The vitest forks become children of
# launchd (PPID 1) and keep running until killed.
#
# Usage:
#   scripts/kill-orphan-vitest.sh            # list orphans
#   scripts/kill-orphan-vitest.sh --kill      # kill orphans only (safe — only PPID=1)
#   scripts/kill-orphan-vitest.sh --kill-all  # kill orphans AND any active vitest run
#
# Safe to invoke any time. PPID=1 means the original parent already exited, so
# those workers have no live test behind them and killing them never interrupts
# a run you care about.

set -euo pipefail

action="${1:-list}"

list_orphans() {
    # `node (vitest N)` are the per-file worker forks tinypool spawns under
    # `pool: 'forks'`. They show up as plain "(vitest)" too (no number) when
    # they are the very first fork (vitest parent) — also kill those if PPID=1.
    ps -axo pid,ppid,etime,rss,command |
        awk '$1 ~ /^[0-9]+$/ && $2 == "1" && /vitest/ && !/awk/ {print}'
}

list_all_vitest() {
    ps -axo pid,etime,pcpu,rss,command |
        awk '$1 ~ /^[0-9]+$/ && /vitest/ {print}'
}

kill_pids() {
    # SIGTERM lets tinypool clean up; fall back to SIGKILL after 2s
    local pids=( "$@" )
    if [[ ${#pids[@]} -eq 0 ]]; then
        echo "no vitest processes match"
        return 0
    fi
    echo "killing: ${pids[*]}"
    kill "${pids[@]}" 2>/dev/null || true
    sleep 2
    local still=( )
    for pid in "${pids[@]}"; do
        if ps -p "$pid" >/dev/null 2>&1; then
            still+=( "$pid" )
        fi
    done
    if [[ ${#still[@]} -gt 0 ]]; then
        echo "force-killing: ${still[*]}"
        kill -9 "${still[@]}" 2>/dev/null || true
    fi
}

case "$action" in
    list)
        echo "=== orphaned vitest (PPID=1) ==="
        list_orphans
        orphans=$(list_orphans | awk '{print $1}')
        if [[ -z "$orphans" ]]; then
            echo "(none — clean)"
        fi
        ;;
    --kill|-k)
        orphans=$(list_orphans | awk '{print $1}')
        if [[ -z "$orphans" ]]; then
            echo "no orphan vitest to kill"
            exit 0
        fi
        echo "orphans to kill:"
        list_orphans
        kill_pids $orphans
        echo "after kill:"
        ps -axo pid,ppid,command | awk '$2 == "1" && /vitest/' || true
        ;;
    --kill-all|-K)
        all=$(list_all_vitest | awk '{print $1}')
        if [[ -z "$all" ]]; then
            echo "no vitest running"
            exit 0
        fi
        echo "ALL vitest to kill:"
        list_all_vitest
        kill_pids $all
        ;;
    *)
        echo "usage: $0 [list|--kill|--kill-all]" >&2
        exit 64
        ;;
esac