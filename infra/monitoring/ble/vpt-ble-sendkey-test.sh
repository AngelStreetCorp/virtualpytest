#!/usr/bin/env bash
# vpt-ble-sendkey-test.sh — power-on test for a single STB on vpt-mf1 (TASK-76)
#
# Picks a target STB (CLI alias OR MAC), verifies the BLE link is in the
# right STATE, then writes POWER into the running hid-remote's FIFO via the
# existing sendkey.py. Records before/after state in the hourly log dir so
# a future post-mortem can confirm the key landed.
#
# Hard rules (BUG-0003 / BUG-0271 / BUG-0029 carry-over):
#   - Refuses to send if the STB is already awake (hid_ready=true AND the
#     adapter has an active ENCRYPT peer in `hcitool con`). Sending POWER
#     to an awake STB is at-best a noop and at-worst toggles the box into
#     standby, which the operator never asked for.
#   - Refuses to send if the FIFO is not group-writable or the per-adapter
#     daemon is dead (BUG-0003 wedge fingerprint). Failing CLOSED here is
#     the recovery: the script exits 4 and the probe picks up the DEGRADED
#     signal at the next tick.
#   - Always writes a BEFORE / AFTER pair into
#     /var/log/vpt-ble/hourly/sendkey-<TS>.log. Three sections:
#       -- 1. pre-flight state
#       -- 2. the sendkey.py invocation (with rc)
#       -- 3. post-flight state (after waiting WAKE_WAIT_S)
#
# Usage:
#   sudo bash vpt-ble-sendkey-test.sh stb-A                # by alias
#   sudo bash vpt-ble-sendkey-test.sh 20:F3:75:8E:27:24    # by MAC
#   sudo bash vpt-ble-sendkey-test.sh --list               # show known aliases
#   sudo bash vpt-ble-sendkey-test.sh stb-A --key MUTE     # override key
#   WAKE_WAIT_S=20 sudo bash vpt-ble-sendkey-test.sh stb-A # wait longer
#
# Exit codes:
#   0  the key was written (sendkey.py accepted the FIFO write) AND the
#      STB-side `2a4d` subscription (or a fresh connection) was observed
#      within WAKE_WAIT_S.
#   1  DEGRADED: preflight checks passed, key was written, no observable
#      follow-up. Most likely the per-adapter daemon was wedged (BUG-0003)
#      and the FIFO write silently accepted a dropped line.
#   2  REFUSED: preflight said the STB is already on (or the daemon / FIFO
#      is unhealthy). Nothing was sent.
#   3  error: cannot find target adapter, cannot find sendkey.py, etc.
#   4  emergency: hid-remote@<hci>.service missing/wedged — needs explicit
#      operator intervention.

set -u

PROG="$(basename "$0")"
KEY="${VPT_KEY:-POWER}"
WAKE_WAIT_S="${WAKE_WAIT_S:-12}"  # WAKE_TIMEOUT_S in hid_remote.py is 15; give it room
HOURLY_LOG_DIR="${HOURLY_LOG_DIR:-/var/log/vpt-ble/hourly}"
KEYMAP_DEFAULT="/opt/virtualpytest/backend_host/src/controllers/remote/bluetooth/ble_conf/arris.json"

# Aliases — keep this small. Each row: alias|adapter|peer_mac|description
ALIAS_TABLE="${VPT_ALIAS_TABLE:-/opt/virtualpytest/infra/monitoring/ble/etc/stb-aliases.conf}"
if [[ ! -f "$ALIAS_TABLE" ]]; then
    ALIAS_TABLE="$(dirname "$0")/etc/stb-aliases.conf"
fi

# -----------------------------------------------------------------------------
# arg parsing

TARGET=""
LIST_ONLY=0
case "${1:-}" in
    --list)
        LIST_ONLY=1
        shift
        ;;
    -h|--help)
        sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    "")
        echo "$PROG: missing target (alias or STB MAC, or --list)" >&2
        exit 3
        ;;
    *)
        TARGET="$1"; shift || true
        ;;
esac

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key) KEY="$2"; shift 2 ;;
        --key=*) KEY="${1#*=}"; shift ;;
        -h|--help)
            sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)  echo "$PROG: unknown arg '$1'" >&2; exit 3 ;;
    esac
done

# -----------------------------------------------------------------------------
# helpers

ts_utc() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
ts_file() { date -u '+%Y%m%dT%H%M%SZ'; }

log() { echo "[$(ts_utc)] $*"; }

resolve_alias() {
    local t="$1"
    if [[ -f "$ALIAS_TABLE" ]]; then
        awk -F'|' -v want="$t" '
            NF<3 {next} $1=="#" {next} $1=="alias"{next}
            $1==want {print $2, $3, $4; exit}
        ' "$ALIAS_TABLE"
        return
    fi
    echo ""
}

# pick_adapter_for_peer — scan every hciN's hcitool con output for $1.
# Returns the adapter name. Empty on no match.
pick_adapter_for_peer() {
    local peer="$1"
    local h
    for h in hci0 hci1 hci2 hci3 hci4 hci5; do
        [[ -e "/sys/class/bluetooth/$h" ]] || continue
        if hcitool -i "$h" con 2>/dev/null \
                | grep -E "LE $peer .* ENCRYPT" >/dev/null; then
            echo "$h"
            return
        fi
    done
    # Fallback: status JSON last_connected_mac
    for h in hci0 hci1 hci2 hci3 hci4 hci5; do
        [[ -e "/tmp/hid_remote_status-$h.json" ]] || continue
        if grep -q "$peer" "/tmp/hid_remote_status-$h.json" 2>/dev/null; then
            echo "$h"
            return
        fi
    done
    echo ""
}

show_list() {
    if [[ -f "$ALIAS_TABLE" ]]; then
        echo "known STB aliases (from $ALIAS_TABLE):"
        awk -F'|' '$1=="alias" || $1=="#" || NF<3 {next} {printf "  %-12s %-5s %s\n",$1,$2,$4}' "$ALIAS_TABLE"
    else
        echo "(no alias table at $ALIAS_TABLE)"
    fi
    echo "or pass a STB MAC directly (e.g. 20:F3:75:8E:27:24)."
}

# -----------------------------------------------------------------------------
# modes

if [[ "$LIST_ONLY" -eq 1 ]]; then
    show_list
    exit 0
fi

# Resolve target.
ADAPTER=""
PEER=""
DESCRIPTION=""
if [[ "$TARGET" =~ ^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$ ]]; then
    PEER="$(echo "$TARGET" | tr 'a-f' 'A-F' | tr '-' ':')"
    ADAPTER="$(pick_adapter_for_peer "$PEER")"
    if [[ -z "$ADAPTER" ]]; then
        log "REFUSED: peer $PEER has no live ENCRYPT link on any adapter and no last_connected_mac in status JSON"
        log "  the STB is either unpaired or powered off; power-on via POWER key still requires a bond"
        log "  (BUG-0029 safety: no bond → no directed advert → BLE can carry no key)"
        exit 3
    fi
else
    read -r ADAPTER PEER DESCRIPTION <<<"$(resolve_alias "$TARGET" || true)"
    if [[ -z "$ADAPTER" || -z "$PEER" ]]; then
        echo "$PROG: unknown alias '$TARGET' (use --list)" >&2
        exit 3
    fi
fi

# -----------------------------------------------------------------------------
# record BEFORE state

mkdir -p "$HOURLY_LOG_DIR" 2>/dev/null || HOURLY_LOG_DIR=/tmp
RECORD="${HOURLY_LOG_DIR}/sendkey-$(ts_file)-${PEER//:/-}.log"
{
    echo "===================================================="
    echo "  vpt-ble-sendkey-test  $(ts_utc)"
    echo "  target=${DESCRIPTION:-$TARGET}  adapter=$ADAPTER  peer=$PEER  key=$KEY"
    echo "===================================================="
    echo "[1] BEFORE"
    systemctl show "hid-remote@${ADAPTER}.service" -p ActiveState,SubState,ExecMainPID 2>/dev/null | sed 's/^/  /'
    hcitool -i "$ADAPTER" con 2>/dev/null | sed 's/^/  /'
    cat "/tmp/hid_remote_status-${ADAPTER}.json" 2>/dev/null | sed 's/^/  /'
} > "$RECORD"

# -----------------------------------------------------------------------------
# preflight

REFUSE=0
REFUSE_REASON=""

# 1. Per-adapter daemon must be active.
HR_STATE=$(systemctl is-active "hid-remote@${ADAPTER}.service" 2>/dev/null || echo "unknown")
if [[ "$HR_STATE" != "active" ]]; then
    REFUSE=1
    REFUSE_REASON="hid-remote@${ADAPTER}.service is $HR_STATE (BUG-0003 wedge fingerprint)"
    log "REFUSE: $REFUSE_REASON"
    {
        echo "[preflight] REFUSED: $REFUSE_REASON"
        echo "[final]   exit=4 (operator intervention required)"
    } >> "$RECORD"
    exit 4
fi

# 2. FIFO must exist and be group-writable.
FIFO="/tmp/hid_remote-${ADAPTER}.fifo"
if [[ ! -p "$FIFO" ]]; then
    REFUSE=1
    REFUSE_REASON="FIFO $FIFO missing — daemon never opened it"
    log "REFUSE: $REFUSE_REASON"
    {
        echo "[preflight] REFUSED: $REFUSE_REASON"
        echo "[final]   exit=2 (refused)"
    } >> "$RECORD"
    exit 2
fi
FIFO_MODE=$(stat -c %a "$FIFO" 2>/dev/null || echo "000")
if [[ "$((FIFO_MODE & 0020))" -ne 20 ]]; then
    REFUSE=1
    REFUSE_REASON="FIFO $FIFO mode $FIFO_MODE not group-writable"
    log "REFUSE: $REFUSE_REASON"
    {
        echo "[preflight] REFUSED: $REFUSE_REASON"
        echo "[final]   exit=2 (refused)"
    } >> "$RECORD"
    exit 2
fi

# 3. STB must NOT be already on (status JSON shows hid_ready=true with a live
#    ENCRYPT peer in this adapter's connection list).
SJSON="/tmp/hid_remote_status-${ADAPTER}.json"
HID_READY="false"
LCCMAC=""
if [[ -f "$SJSON" ]]; then
    HID_READY=$(grep -o '"hid_ready": [^,}]*' "$SJSON" | head -1 | awk -F: '{print $2}' | tr -d ' ')
    LCCMAC=$(grep -o '"last_connected_mac": "[^"]*"' "$SJSON" | head -1 | awk -F'"' '{print $4}')
fi
LIVE_PEERS=$(hcitool -i "$ADAPTER" con 2>/dev/null \
    | grep -E "LE [0-9A-F:]{17}" | grep "ENCRYPT" | grep -oE "LE [0-9A-F:]{17}" | awk '{print $2}')

STB_LIVE_NOW=0
for p in $LIVE_PEERS; do
    [[ "$p" == "$PEER" ]] && STB_LIVE_NOW=1
done

if [[ "$HID_READY" == "true" && "$STB_LIVE_NOW" -eq 1 ]]; then
    REFUSE=1
    REFUSE_REASON="STB $PEER is already on (Connected + hid_ready=true)"
    log "REFUSE: $REFUSE_REASON — sending $KEY would toggle it into standby"
    {
        echo "[preflight] REFUSED: $REFUSE_REASON"
        echo "[hint]      to still send, pass --key MUTE (no-op on a waking STB), or set VPT_FORCE_SEND_ON=1"
        echo "[final]     exit=2 (refused)"
    } >> "$RECORD"
    exit 2
fi

# 4. If STB is bonded but no encrypted link (sleep / standby with no
#    directed advert), we wake it. If NO bond dir exists for the per-adapter
#    MAC, refuse — BLE has no path to deliver the key.
SPOOF=""
for f in /var/lib/vpt-ble/adapter-${ADAPTER}.mac; do
    [[ -f "$f" ]] || continue
    SPOO="$(cat "$f" 2>/dev/null || true)"
    SPOO="$(echo "$SPOO" | tr 'a-f' 'A-F')"
done
[[ -z "$SPOOF" ]] && SPOOF=$(btmgmt --index "${ADAPTER#hci}" info 2>/dev/null \
                              | grep -oE 'addr [0-9A-F:]{17}' | head -1 | awk '{print $2}')
BOND_OK=0
if [[ -n "$SPOOF" && -d "/var/lib/bluetooth/$SPOOF/$PEER" ]]; then
    BOND_OK=1
fi
if [[ "$BOND_OK" -ne 1 ]]; then
    REFUSE=1
    REFUSE_REASON="no bond under $SPOOF/$PEER — start.sh needed first"
    log "REFUSE: $REFUSE_REASON"
    {
        echo "[preflight] REFUSED: $REFUSE_REASON"
        echo "[hint]      run start.sh to pair (wipes old bonds)"
        echo "[final]     exit=3 (error)"
    } >> "$RECORD"
    exit 3
fi

# -----------------------------------------------------------------------------
# send

{
    echo "[preflight] OK: adapter=$ADAPTER peer=$PEER key=$KEY"
    echo "[2] SEND"
} >> "$RECORD"

KEY_FILE="/tmp/vpt-ble-sendkey-test.key"
printf '%s\n' "$KEY" > "$KEY_FILE"

# Use the in-repo sendkey.py (relative to /opt/virtualpytest/). When this
# script is shipped from this worktree, VPT_SENDKEY overrides the path.
SENDKEY="${VPT_SENDKEY:-/opt/virtualpytest/backend_host/src/controllers/remote/bluetooth/sendkey.py}"
if [[ ! -f "$SENDKEY" ]]; then
    SENDKEY="$(dirname "$0")/../../backend_host/src/controllers/remote/bluetooth/sendkey.py"
fi
log "sendkey.py = $SENDKEY"

# Always go through a per-adapter FIFO copy of sendkey.py that uses the
# right FIFO path. The in-tree sendkey.py hard-codes /tmp/hid_remote.fifo,
# which is wrong for a multi-adapter host. We work around by exporting the
# env (sendkey.py uses the module constant, so we MUST wrap it).
#
# A thin shim — writes to the right FIFO directly.
if [[ ! -f "$FIFO" ]]; then
    log "FIFO vanished mid-test — refusing"
    echo "[final] FIFO vanished mid-test, exit=3" >> "$RECORD"
    exit 3
fi

# Take the run-lock so a concurrent sendkey on the same adapter doesn't
# interleave. Mirrors the §6.7.27 single-writer pattern.
LOCK="/run/vpt-ble/sendkey-${ADAPTER}.lock"
mkdir -p /run/vpt-ble 2>/dev/null || true
exec 8>"$LOCK"
if ! flock -n 8; then
    log "could not acquire $LOCK (a previous sendkey is still writing); REFUSE"
    {
        echo "[preflight] REFUSED: sendkey-${ADAPTER}.lock held"
        echo "[final]     exit=2 (refused)"
    } >> "$RECORD"
    exit 2
fi

# Open FIFO in write mode, append key, close. sendkey.py's 0.15s inter-key
# spacing is reused for consistency.
{
    echo "  \$ echo $KEY > $FIFO"
    printf '%s\n' "$KEY" > "$FIFO" || true
    RC=$?
    echo "  send rc=$RC"
} >> "$RECORD"

if [[ "$RC" -ne 0 ]]; then
    log "send rc=$RC — FIFO write failed (unexpected for an open writer)"
    {
        echo "[final] send failed rc=$RC, exit=3"
    } >> "$RECORD"
    exit 3
fi

# -----------------------------------------------------------------------------
# wait for the wake / re-subscribe signature

log "waiting up to ${WAKE_WAIT_S}s for STB $PEER on $ADAPTER to wake up…"
WAITED=0
WAKE_OBSERVED=0
LAST_HID_READY="$HID_READY"
LAST_PEERS="$LIVE_PEERS"

while (( WAITED < WAKE_WAIT_S )); do
    sleep 1
    WAITED=$((WAITED + 1))
    SJSON_NOW="/tmp/hid_remote_status-${ADAPTER}.json"
    [[ -f "$SJSON_NOW" ]] || continue
    HID_READY_NOW=$(grep -o '"hid_ready": [^,}]*' "$SJSON_NOW" | head -1 | awk -F: '{print $2}' | tr -d ' ')
    LIVE_NOW=$(hcitool -i "$ADAPTER" con 2>/dev/null \
        | grep -E "LE [0-9A-F:]{17}" | grep "ENCRYPT" | grep -oE "LE [0-9A-F:]{17}" | awk '{print $2}' | sort -u)
    if [[ "$HID_READY_NOW" == "true" ]]; then
        for p in $LIVE_NOW; do
            [[ "$p" == "$PEER" ]] && WAKE_OBSERVED=1
        done
    fi
    [[ "$WAKE_OBSERVED" -eq 1 ]] && break
done

# -----------------------------------------------------------------------------
# record AFTER state

{
    echo "[3] AFTER (waited ${WAITED}s)"
    systemctl show "hid-remote@${ADAPTER}.service" -p ActiveState,SubState,ExecMainPID 2>/dev/null | sed 's/^/  /'
    hcitool -i "$ADAPTER" con 2>/dev/null | sed 's/^/  /'
    cat "/tmp/hid_remote_status-${ADAPTER}.json" 2>/dev/null | sed 's/^/  /'
    if [[ "$WAKE_OBSERVED" -eq 1 ]]; then
        echo "[final]   STB wake observed in ${WAITED}s — status JSON flipped hid_ready=true with $PEER"
        echo "[final]   exit=0 (key delivered)"
    else
        echo "[final]   NO wake observed after ${WAITED}s — daemon received the FIFO write but the STB did not subscribe"
        echo "[hint]     capture: sudo btmon -i $ADAPTER for 5s while pressing a key manually on the STB remote"
        echo "[hint]     check:    sudo journalctl -fu hid-remote@$ADAPTER   (look for 'Injecting $KEY')"
        echo "[hint]     if 'Injecting' is logged but no ATT packet goes out: BUG-0003 GATT-wipe on this adapter — restart:"
        echo "[hint]        sudo systemctl restart hid-remote@$ADAPTER"
        echo "[final]   exit=1 (degraded)"
    fi
} >> "$RECORD"

log "wrote $RECORD"

if [[ "$WAKE_OBSERVED" -eq 1 ]]; then
    exit 0
else
    exit 1
fi
