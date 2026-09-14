#!/usr/bin/env bash
#
# profile_remote_monitor.sh — sample-profile a long-running service on a
# remote VirtualPyTest host (vpt-monitor, vpt-stream wrapper, etc.) with
# py-spy, with zero code changes and no service restart.
#
# Why this exists: capture_monitor.py / run_ffmpeg.sh CPU problems are not
# obvious from htop (it just says "python 50%"). py-spy attributes that CPU
# to the actual Python call stacks. This script codifies the exact workflow
# used in the 2026-05-19 monitor optimization (see
# backend_host/scripts/OPTIMIZATION.md) so it can be repeated in seconds.
#
# Usage:
#   scripts/profile_remote_monitor.sh <ssh-host> [service] [duration_s] [min_uptime_s]
#
#   <ssh-host>      ssh alias from ~/.ssh/config (e.g. host1, host3)
#   service         systemd unit to profile        (default: vpt-monitor)
#   duration_s      py-spy sampling window          (default: 30)
#   min_uptime_s    wait until the process has been
#                   up at least this long before
#                   sampling (0 = sample now)       (default: 0)
#
# Examples:
#   scripts/profile_remote_monitor.sh host1
#   scripts/profile_remote_monitor.sh host1 vpt-monitor 30 240   # steady state
#   scripts/profile_remote_monitor.sh host3 vpt-stream 20
#
# Requirements (already true for host* hosts):
#   - ssh alias reachable, passwordless sudo on the host
#   - py-spy is installed *persistently* into the host venv on first run
#     (/opt/virtualpytest/venv/bin/py-spy) so it survives reboots — unlike
#     a /tmp install which is lost on reboot.
set -euo pipefail

HOST="${1:?usage: profile_remote_monitor.sh <ssh-host> [service] [duration_s] [min_uptime_s]}"
SERVICE="${2:-vpt-monitor}"
DURATION="${3:-30}"
MIN_UPTIME="${4:-0}"

echo "▶ profiling ${SERVICE} on ${HOST} (duration=${DURATION}s, min_uptime=${MIN_UPTIME}s)"

ssh "$HOST" "SERVICE='$SERVICE' DURATION='$DURATION' MIN_UPTIME='$MIN_UPTIME' bash -s" <<'REMOTE'
set -euo pipefail
PYSPY=/opt/virtualpytest/venv/bin/py-spy

# 1. Ensure py-spy is installed persistently in the host venv (not /tmp).
if [ ! -x "$PYSPY" ]; then
  echo "· py-spy not found — installing into venv (one-time, persists across reboots)"
  sudo /opt/virtualpytest/venv/bin/pip install --quiet py-spy
fi
echo "· py-spy: $($PYSPY --version)"

# 2. Resolve PID, optionally wait for steady state.
PID=$(systemctl show "$SERVICE" -p MainPID --value)
[ "$PID" != "0" ] || { echo "✗ $SERVICE not running"; exit 1; }
while [ "$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ')" -lt "$MIN_UPTIME" ] 2>/dev/null; do
  sleep 15
  PID=$(systemctl show "$SERVICE" -p MainPID --value)   # re-resolve in case it restarted
done
UP=$(ps -o etimes= -p "$PID" | tr -d ' ')
echo "· PID=$PID  uptime=${UP}s"
echo "· load:$(uptime | grep -oE 'load average.*')"

# 3. Process CPU% over a real 10s interval (not lifetime average).
CPU=$(top -b -d 10 -n 2 -p "$PID" | grep -E "^ *$PID " | tail -1 | awk '{print $9}')
echo "· ${SERVICE} CPU = ${CPU}% of one core"

# 4. Sample-profile and fold.
OUT=/tmp/pyspy_$SERVICE.folded
sudo timeout $((DURATION + 20)) "$PYSPY" record --pid "$PID" \
     --duration "$DURATION" --rate 120 --format raw --output "$OUT" 2>/dev/null
TOTAL=$(awk '{s+=$NF} END{print s+0}' "$OUT")
echo "· samples: $TOTAL over ${DURATION}s (≈ on-CPU time proxy)"

# 5. Category breakdown (the buckets that mattered in the 2026-05 work).
echo "· category breakdown:"
awk -v tot="$TOTAL" '
  { n=$NF
    if ($0 ~ /_flush_chunk_locked|_append_to_chunk|_load_chunk_from_disk|_flush_dirty_chunks|json\//) c["chunk/JSON"]+=n
    else if ($0 ~ /detect_issues|detector\.py/)                                                       c["detection (real CV)"]+=n
    else if ($0 ~ /event_gen|inotify/)                                                                c["inotify"]+=n
    else if ($0 ~ /_run_stall_watcher/)                                                               c["stall-watcher"]+=n
    else if ($0 ~ /_add_event_duration_metadata|incident_manager|redis/)                              c["incident/redis"]+=n
    else c["other"]+=n }
  END { for (k in c) printf "    %-22s %6d  %5.1f%%\n", k, c[k], (tot? 100*c[k]/tot:0) }
' "$OUT" | sort -t' ' -k2 -rn

# 6. Hottest individual stacks.
echo "· top stacks:"
sort "$OUT" | awk '{c=$NF; $NF=""; s[$0]+=c} END{for(k in s) print s[k], k}' \
  | sort -rn | head -8 | sed 's/^/    /'
REMOTE

echo "✔ done"
