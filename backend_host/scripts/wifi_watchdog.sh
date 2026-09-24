#!/usr/bin/env bash
# =============================================================================
# wifi_watchdog.sh — recover a WiFi-attached host when the radio degrades
# =============================================================================
# Run every 3 minutes as root from /etc/cron.d/wifi-watchdog. Installed on the
# off-site hosts that reach the network over WiFi rather than ethernet, and that
# are only reachable through reverse SSH tunnels — a dead radio takes them off
# the frontend entirely while nothing server-side looks wrong.
#
# The fleet's original watchdog asked a binary question: "did any of 3 pings come
# back?". That is blind to the failure that took vpt-pi4 off the air on
# 2026-09-22 — a radio still associated and still answering ~30% of the time.
# Three pings almost always found one survivor, so the old check called the link
# healthy, and its post-repair check (the same 3 pings) logged "WiFi recovered"
# over a link that was still unusable.
#
# So this version measures LOSS over a larger sample, and escalates until the
# loss is actually low again:
#   1. bounce the interface   2. restart NetworkManager   3. reboot (rate-limited)
#
# Healthy runs write nothing, so an absent log means healthy. Nothing here starts
# a service that was not already running.
#
# See docs/agent/infra/WIFI_WATCHDOG.md for the full write-up.
set -uo pipefail

LOG=/var/log/wifi-watchdog.log
STATE=/var/lib/wifi-watchdog
LOCK=/var/lock/wifi-watchdog.lock
LAST_REBOOT="${STATE}/last-reboot"

# A run must not overlap the previous one: a reboot escalation can take minutes and
# cron fires every 3. Second instance exits silently rather than stacking repairs.
exec 9>"${LOCK}"
flock -n 9 || exit 0

mkdir -p "${STATE}"

# --- tunables -----------------------------------------------------------------
PING_COUNT=10          # sample size — 3 is far too few to measure loss
PING_INTERVAL=0.3      # a full sample costs ~3s
PING_TIMEOUT=2         # seconds per probe
FAIL_LOSS=60           # >= this % loss means "act"
OK_LOSS=30             # <  this % loss means "repaired"
SETTLE=12              # seconds to let the link come back before re-measuring
REBOOT_MIN_INTERVAL=21600   # 6h — never loop on reboots
MIN_UPTIME=300         # don't judge the link in the first 5 min after boot
MAX_LOG_BYTES=262144   # 256K, then roll once

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): $*" >> "${LOG}"; }

# Keep the log from growing without bound — one roll, no logrotate dependency.
if [[ -f "${LOG}" ]] && (( $(stat -c %s "${LOG}" 2>/dev/null || echo 0) > MAX_LOG_BYTES )); then
    mv -f "${LOG}" "${LOG}.1"
fi

# Gateway and wifi device are discovered, not hardcoded, so the same file works on
# a host whose interface is not wlan0 (vpt-nipogi's is wlp2s0) without editing.
GATEWAY="$(ip route show default 2>/dev/null | awk '/default/{print $3; exit}')"
WIFI_DEV="$(nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
[[ -n "${GATEWAY}"  ]] || { log "no default gateway — nothing to test against"; exit 0; }
[[ -n "${WIFI_DEV}" ]] || { log "no wifi device found — not a wifi host?"; exit 0; }

# Percentage of probes lost. 100 when ping cannot run at all.
loss_pct() {
    local out
    out="$(ping -c "${PING_COUNT}" -i "${PING_INTERVAL}" -W "${PING_TIMEOUT}" \
              "${GATEWAY}" 2>/dev/null)" || true
    local pct
    pct="$(printf '%s\n' "${out}" | grep -oE '[0-9]+(\.[0-9]+)?% packet loss' | grep -oE '^[0-9]+')"
    [[ -n "${pct}" ]] && echo "${pct}" || echo 100
}

# True once the link is genuinely usable again, not merely answering.
repaired() {
    sleep "${SETTLE}"
    local l; l="$(loss_pct)"
    if (( l < OK_LOSS )); then
        log "recovered after $1 — loss now ${l}%"
        return 0
    fi
    log "still degraded after $1 — loss ${l}%"
    return 1
}

# autossh holds these boxes' only inbound path. After a link flap it sits in a
# backoff that reaches ~3 minutes, so nudge the tunnels rather than waiting them
# out. Only units that are already active are touched.
restart_tunnels() {
    local u
    for u in vpt-tunnel.service vpt-tunnel-rpi1.service; do
        if systemctl is-active --quiet "${u}"; then
            systemctl restart "${u}" && log "  restarted ${u}"
        fi
    done
}

# --- run ----------------------------------------------------------------------
UPTIME=$(awk '{print int($1)}' /proc/uptime)
(( UPTIME < MIN_UPTIME )) && exit 0

LOSS="$(loss_pct)"
(( LOSS < FAIL_LOSS )) && exit 0   # healthy: log nothing, stay quiet

log "link degraded — ${LOSS}% loss to ${GATEWAY} over ${WIFI_DEV} (threshold ${FAIL_LOSS}%)"

# 1 — bounce the interface
log "step 1: bouncing ${WIFI_DEV}"
nmcli device disconnect "${WIFI_DEV}" >/dev/null 2>&1
sleep 2
nmcli device connect "${WIFI_DEV}" >/dev/null 2>&1
if repaired "interface bounce"; then restart_tunnels; exit 0; fi

# 2 — restart NetworkManager
log "step 2: restarting NetworkManager"
systemctl restart NetworkManager
if repaired "NetworkManager restart"; then restart_tunnels; exit 0; fi

# 3 — reboot, but never more than once per REBOOT_MIN_INTERVAL. A radio this far
# gone has needed a full reboot before; a boot loop would be worse than a dead Pi.
NOW=$(date +%s)
LAST=0
[[ -f "${LAST_REBOOT}" ]] && LAST="$(cat "${LAST_REBOOT}" 2>/dev/null || echo 0)"
if (( NOW - LAST < REBOOT_MIN_INTERVAL )); then
    log "step 3: reboot SUPPRESSED — last one $(( (NOW - LAST) / 60 ))m ago, minimum $(( REBOOT_MIN_INTERVAL / 60 ))m. Needs a human."
    exit 1
fi
echo "${NOW}" > "${LAST_REBOOT}"
log "step 3: rebooting — interface bounce and NetworkManager restart both failed"
sync
systemctl reboot
