#!/bin/bash
# diagnose_ble.sh — collect everything needed to debug a failing BLE remote
# connection into a FOLDER of small per-section text files, so each file can be
# copied out through a clipboard (VDI without file transfer) and handed to an
# agent/human for offline analysis (see docs/agent/devices/BLUETOOTH.md).
#
# Usage (on the host, as root):
#   sudo bash diagnose_ble.sh                 # all adapters, journals of the last 30 min
#   sudo bash diagnose_ble.sh hci1            # single adapter
#   sudo bash diagnose_ble.sh hci1 15         # + 15s live btmon capture (press keys during it)
#   SINCE='2026-08-31 17:30' UNTIL='2026-08-31 18:45' sudo -E bash diagnose_ble.sh
#                                             # journals of a PAST window (needs -E to pass env)
#   MAX_LINES=200 sudo -E bash diagnose_ble.sh # cap every journal file (default 400)
#
# Output: /tmp/ble_diag_<hostname>_<timestamp>/NN_<section>.txt
#   00_INDEX.txt    — file list with line counts (copy this first)
#   00_SUMMARY.txt  — warnings + key facts extracted from the other files
#
# Journal noise is squashed (see squash()): sudo/pam audit lines are dropped,
# per-keypress chatter (Injecting / _bonded_peer_mac / conn-info / 0x0c2d) is
# COUNTED instead of printed, and consecutive identical lines are collapsed.
#
# Read-only: never restarts services, never touches bonds, never powers adapters.
# Bond key material (LTK/IRK/CSRK) is redacted from the report.

ONLY_HCI="$1"
BTMON_SECS="${2:-0}"
SINCE="${SINCE:--30 min}"
UNTIL="${UNTIL:-now}"
MAX_LINES="${MAX_LINES:-400}"

DIR="/tmp/ble_diag_$(hostname)_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DIR"
CUR=""

# ---------------------------------------------------------------- helpers
section() {                       # section NN name  → switches the current output file
    CUR="$DIR/${1}_${2}.txt"
    : > "$CUR"
    echo "== [$1] $2 == $(date '+%F %T')" >> "$CUR"
    echo "[$1] $2"
}
note() { echo "$*" >> "$CUR"; }
# btmgmt/bluetoothctl can wedge on stdin (§6.7.20) — every call below goes
# through timeout + explicit stdin redirection, same pattern as start.sh.
run() {
    {
        echo ""
        echo "----8<---- \$ $* ----"
        timeout 10 "$@" </dev/null 2>&1 || echo "[exit=$? — command failed or timed out]"
    } >> "$CUR"
}
# journal: squashed + capped journalctl into the current file
journal() {
    local tmp; tmp=$(mktemp)
    timeout 60 journalctl --no-pager -q --since "$SINCE" --until "$UNTIL" "$@" </dev/null 2>&1 | squash > "$tmp"
    local total; total=$(wc -l < "$tmp")
    {
        echo ""
        echo "----8<---- \$ journalctl --since '$SINCE' --until '$UNTIL' $* ----"
        if [ "$total" -gt "$MAX_LINES" ]; then
            echo "[truncated: showing last $MAX_LINES of $total squashed lines]"
            tail -n "$MAX_LINES" "$tmp"
        else
            cat "$tmp"
        fi
    } >> "$CUR"
    rm -f "$tmp"
}
# squash: drop audit noise, count per-keypress chatter, collapse consecutive duplicates.
# Works on journalctl short format ("Sep 02 10:01:59 host unit[pid]: msg") and dmesg.
squash() {
    awk '
    function ts(l) { return substr(l, 1, 15) }
    function key(l,  k) {
        k = l
        sub(/^[A-Za-z][A-Za-z][A-Za-z] [ 0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9] [^ ]+ /, "", k)  # journal ts+host
        sub(/^\[ *[0-9]+\.[0-9]+\] /, "", k)                                                       # dmesg ts
        gsub(/\[[0-9]+\]/, "[#]", k)                                                                # pids
        return k
    }
    function flush() {
        if (rep > 0) printf "    ... repeated %d more times, last at %s\n", rep, lastts
        rep = 0
    }
    BEGIN {
        drop = "pam_unix\\(sudo:session\\)|sudo\\[[0-9]+\\]: +root : PWD=|^Hint: You are currently not seeing|^ +Users in groups|^ +Pass -q to turn off"
        n = split("Injecting 0x;_bonded_peer_mac: [0-9]+ bonds;Opcode 0x0c2d failed: -22", cre, ";")
    }
    {
        if ($0 ~ drop) { dropped++; next }
        for (i = 1; i <= n; i++) if ($0 ~ cre[i]) {
            c[i]++; if (!(i in first)) first[i] = ts($0); last[i] = ts($0)
            if (i == 1 && match($0, /Injecting 0x[0-9A-Fa-f]+/)) keys[substr($0, RSTART + 10, RLENGTH - 10)]++
            if (i == 2 && !(key($0) in seen2)) { seen2[key($0)] = 1; print "[first occurrence] " $0 }
            next
        }
        k = key($0)
        if (k == prevk) { rep++; lastts = ts($0); next }
        flush()
        print; prevk = k; rep = 0
    }
    END {
        flush()
        for (i = 1; i <= n; i++) if (c[i] > 0)
            printf "[squash] %d lines matching /%s/ counted, not printed (first %s, last %s)\n", c[i], cre[i], first[i], last[i]
        for (k in keys) printf "[squash]   Injecting %s: %d\n", k, keys[k]
        if (dropped > 0) printf "[squash] %d sudo/pam/hint audit lines dropped\n", dropped
    }'
}

# ---------------------------------------------------------------- 01 host
section 01 host
run hostname
run date
run uptime -s
run uptime
run uname -a
run bluetoothd --version
# Patched-bluetoothd check (MULTI_INSTANCE install): stock vs CCC-patch build
for bd in /usr/libexec/bluetooth/bluetoothd /usr/lib/bluetooth/bluetoothd; do
    [ -e "$bd" ] && run sha256sum "$bd"
done
run ls -l /etc/systemd/system/bluetooth.service.d/
run cat /etc/systemd/system/bluetooth.service.d/override.conf
note ""
note "-- Journal retention (can we still see a past event?) --"
note "requested window: SINCE='$SINCE' UNTIL='$UNTIL'"
run journalctl --list-boots
run journalctl --disk-usage
run ls -la /var/log/journal /run/log/journal
run grep -rhE '^(Storage|SystemMaxUse|RuntimeMaxUse|MaxRetentionSec)' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/
JOURNAL_FROM=$(journalctl --list-boots --no-pager -q </dev/null 2>/dev/null | tail -1 | awk '{print $4, $5, $6}')
note "oldest entry of current boot: ${JOURNAL_FROM:-unknown}   (booted: $(uptime -s 2>/dev/null))"
note "-- Reboots / shutdowns (last -x) --"
run bash -c "last -x --time-format iso 2>/dev/null | head -20"
note "-- apt history mentioning bluez (package upgrade restarts bluetoothd → §6.7.28) --"
run bash -c "grep -hB3 -iE 'bluez|bluetooth' /var/log/apt/history.log* 2>/dev/null | tail -40"

# ---------------------------------------------------------------- 02 adapters
section 02 adapters
run hciconfig -a
run rfkill list
run lsusb
ADAPTERS=$(ls /sys/class/bluetooth 2>/dev/null | grep -E '^hci[0-9]+$')
[ -n "$ONLY_HCI" ] && ADAPTERS="$ONLY_HCI"
note ""
note "Adapters selected: $ADAPTERS"
for hci in $ADAPTERS; do
    idx="${hci#hci}"
    note ""
    note "== btmgmt info --index $idx (sticky BR/EDR + advertising state live in 'current settings')"
    run btmgmt --index "$idx" info
done
note "-- USB path per adapter (did a dongle re-enumerate / swap index? §6.7.24) --"
for hci in $ADAPTERS; do
    run bash -c "readlink -f /sys/class/bluetooth/$hci/device"
done
run journalctl --no-pager -q -u pin-bt-adapters -b

# ---------------------------------------------------------------- 03 units
section 03 units
run systemctl list-units --all --no-pager 'bluetooth*' 'hid-remote*' 'hid-agent*' 'ble-remote*' 'vpt-ble-remote*' 'pin-bt-adapters*' 'vpt-host*'
for unit in bluetooth.service vpt-host.service $(systemctl list-units --all --no-legend --plain 'hid-remote*' 'hid-agent*' 'ble-remote*' 'vpt-ble-remote*' 2>/dev/null | awk '{print $1}'); do
    run systemctl show "$unit" -p Id,ActiveState,SubState,ExecMainPID,ExecMainStartTimestamp,NRestarts
done
note ""
note "-- GATT-wipe check (§6.7.28): bluetoothd must have started BEFORE every hid-remote daemon --"
BT_START=$(systemctl show bluetooth.service -p ExecMainStartTimestampMonotonic --value 2>/dev/null)
note "bluetooth.service monotonic start: ${BT_START:-unknown}"
for unit in $(systemctl list-units --no-legend --plain --state=active 'hid-remote*' 2>/dev/null | awk '{print $1}'); do
    HR_START=$(systemctl show "$unit" -p ExecMainStartTimestampMonotonic --value 2>/dev/null)
    note "$unit monotonic start: ${HR_START:-unknown}"
    if [ -n "$BT_START" ] && [ -n "$HR_START" ] && [ "$BT_START" -gt "$HR_START" ] 2>/dev/null; then
        note "*** WARNING: bluetoothd restarted AFTER $unit — GATT registration wiped (§6.7.28). Keys will be silently dropped until $unit is restarted. ***"
    fi
    HR_PID=$(systemctl show "$unit" -p ExecMainPID --value 2>/dev/null)
    HR_START_S=$(date -d "$(systemctl show "$unit" -p ExecMainStartTimestamp --value 2>/dev/null)" +%s 2>/dev/null)
    OLDEST_S=$(date -d "$(journalctl -q -b -o short-iso </dev/null 2>/dev/null | head -1 | cut -d' ' -f1)" +%s 2>/dev/null)
    if [ -n "$HR_START_S" ] && [ -n "$OLDEST_S" ] && [ "$HR_START_S" -lt "$OLDEST_S" ] 2>/dev/null; then
        note "$unit: started before the oldest journal entry — 'GATT application registered' cannot be verified (journal rotated); use btmon during a keypress instead"
    else
        REG=$(journalctl --no-pager -q -u "$unit" _PID="$HR_PID" </dev/null 2>/dev/null | grep -c 'GATT application registered')
        [ "$REG" = "0" ] && note "*** WARNING: $unit current process never logged 'GATT application registered' (§6.7.28 definitive test) ***"
    fi
done
note ""
note "-- Duplicate-daemon check (§6.7.27): exactly ONE hid_remote.py per adapter --"
run pgrep -af hid_remote.py
run pgrep -af agent.py
N_DAEMONS=$(pgrep -cf hid_remote.py </dev/null 2>/dev/null || echo 0)
N_ADAPTERS=$(echo "$ADAPTERS" | wc -w)
note "hid_remote.py process count: $N_DAEMONS  (adapters: $N_ADAPTERS)"
[ "$N_DAEMONS" -gt "$N_ADAPTERS" ] 2>/dev/null && note "*** WARNING: more hid_remote.py processes than adapters — key stream split (§6.7.27) ***"

# ---------------------------------------------------------------- 04 tmp_state
section 04 tmp_state
run ls -l --time-style=full-iso /tmp/hid_remote*.fifo /tmp/hid_remote_status*.json /tmp/ble-remote-pairing*.lock /tmp/ble-*-env.list /tmp/ble-start-*.log /tmp/ble-resume-*.log
for f in /tmp/hid_remote_status*.json; do
    [ -e "$f" ] && run cat "$f"
done
for f in /tmp/hid_remote*.fifo; do
    [ -e "$f" ] && run lsof "$f"
    # NOTE: zero openers is NOT proof of zero readers — a reader blocked in
    # open() doesn't show in lsof (§6.7.27). The pgrep count in 03 is authoritative.
done
for f in /tmp/ble-*-env.list; do
    [ -e "$f" ] && run cat "$f"
done
note ""
note "-- start.sh / resume.sh logs (mtime matters: was there really a fresh pair? §6.7.29) --"
for f in /tmp/ble-start-*.log /tmp/ble-resume-*.log; do
    if [ -e "$f" ]; then
        run stat -c '%y %n' "$f"
        run tail -n 60 "$f"
    fi
done

# ---------------------------------------------------------------- 05 bonds
section 05 bonds
run ls -la --time-style=full-iso /var/lib/bluetooth/
for adir in /var/lib/bluetooth/*/; do
    [ -d "$adir" ] || continue
    run ls -la --time-style=full-iso "$adir"
    NB=0
    for ddir in "$adir"*/; do
        [ -f "$ddir/info" ] || continue
        NB=$((NB + 1))
        note ""
        note "----8<---- bond info: $ddir  (mtime $(stat -c '%y' "$ddir")) ----"
        # Multi-bond picker (§6.7.29): the bond to keep is the one with 2a4d in [Cccs]
        sed 's/^Key=.*/Key=<redacted>/' "$ddir/info" >> "$CUR"
        grep -q 2a4d "$ddir/info" && note "[has HID Input Report CCCD 2a4d → this is the bond the picker prefers]" || note "[NO 2a4d CCCD → battery-only / stale bond]"
    done
    [ "$NB" -gt 1 ] && note "*** WARNING: $NB bonds under $adir — STB self-re-paired (§6.7.29); remove the stale one(s) ***"
done

# ---------------------------------------------------------------- 06 bluetoothctl
section 06 bluetoothctl
run bluetoothctl list
for hci in $ADAPTERS; do
    MAC=$(hciconfig "$hci" 2>/dev/null | awk '/BD Address/{print $3}')
    note ""
    note "== adapter $hci ($MAC)"
    [ -n "$MAC" ] && run bluetoothctl --timeout 5 -- select "$MAC"
done
run bluetoothctl devices
bluetoothctl devices </dev/null 2>/dev/null | awk '{print $2}' | while read -r dev; do
    [ -n "$dev" ] && run bluetoothctl info "$dev"
done
for hci in $ADAPTERS; do
    run hcitool -i "$hci" con
done

# ---------------------------------------------------------------- 07 journals (window)
section 07 journal_bluetooth
journal -u bluetooth
for unit in $(systemctl list-units --all --no-legend --plain 'hid-remote*' 'hid-agent*' 'ble-remote*' 'vpt-ble-remote*' 2>/dev/null | awk '{print $1}'); do
    section 07 "journal_${unit%.service}"
    journal -u "$unit"
done
section 07 journal_kernel
note "(USB disconnect/re-enumeration and hci errors in the window — a dongle replug reverts the spoofed MAC and can swap hci indices)"
tmp=$(mktemp)
timeout 60 journalctl --no-pager -q -k --since "$SINCE" --until "$UNTIL" </dev/null 2>&1 | grep -iE 'usb|hci|bluetooth|xhci' | squash | tail -n "$MAX_LINES" > "$tmp"
cat "$tmp" >> "$CUR"; rm -f "$tmp"
section 07 journal_system
note "(reboots, package upgrades, adapter pinning, host service restarts in the window)"
journal -u pin-bt-adapters -u apt-daily-upgrade -u unattended-upgrades -u systemd-udevd
journal -u vpt-host --grep 'Started|Stopped|Stopping|Starting|Failed'

# ---------------------------------------------------------------- 08 dmesg
section 08 dmesg
dmesg 2>/dev/null | grep -iE 'bluetooth|hci|usb [0-9]|xhci' | squash | tail -n "$MAX_LINES" >> "$CUR"

# ---------------------------------------------------------------- 09 btmon (optional live)
if [ "$BTMON_SECS" -gt 0 ] 2>/dev/null; then
    for hci in $ADAPTERS; do
        section 09 "btmon_$hci"
        note "Live btmon capture on $hci for ${BTMON_SECS}s — PRESS SOME KEYS NOW (sendkey.py or UI)"
        echo "    >>> press keys on $hci now (${BTMON_SECS}s) <<<"
        timeout "$BTMON_SECS" btmon -i "$hci" </dev/null 2>&1 | grep -vE '^= (New|Open|Index) ' | tail -n 300 >> "$CUR"
        note "(look for 'Handle Value Notification' = keys reached the wire; absence while hid-remote logs 'Injecting' = CCCD/GATT problem)"
    done
fi

# ---------------------------------------------------------------- 00 summary + index
section 00 SUMMARY
note "host: $(hostname)   collected: $(date '+%F %T')   window: '$SINCE' → '$UNTIL'"
note "booted: $(uptime -s 2>/dev/null)   oldest journal entry of this boot: ${JOURNAL_FROM:-unknown}"
WIN_S=$(date -d "$SINCE" +%s 2>/dev/null); OLD_S=$(date -d "$(journalctl -q -b -o short-iso </dev/null 2>/dev/null | head -1 | cut -d' ' -f1)" +%s 2>/dev/null)
if [ -n "$WIN_S" ] && [ -n "$OLD_S" ] && [ "$WIN_S" -lt "$OLD_S" ] 2>/dev/null; then
    note "*** WARNING: requested window starts BEFORE the oldest journal entry — the journal files in 07_* are EMPTY for this event. Fix retention (BUG-0039: persistent journal + SystemMaxUse) and cut the log flood. ***"
fi
note "adapters: $ADAPTERS"
note ""
note "-- WARNINGS --"
grep -h '\*\*\* WARNING' "$DIR"/0[1-8]_*.txt >> "$CUR" 2>/dev/null || true
grep -c '\*\*\* WARNING' "$DIR"/0[1-8]_*.txt 2>/dev/null | grep -qv ':0$' || note "(none)"
note ""
note "-- bonds per adapter --"
for adir in /var/lib/bluetooth/*/; do
    [ -d "$adir" ] || continue
    BONDS=$(ls "$adir" 2>/dev/null | grep -E '^([0-9A-F]{2}:){5}[0-9A-F]{2}$' | tr '\n' ' ')
    NB=$(echo "$BONDS" | wc -w)
    [ "$NB" -gt 0 ] && note "$(basename "$adir"): $NB bond(s): $BONDS$( [ "$NB" -gt 1 ] && echo '  <-- DUPLICATE (§6.7.29)')"
done
note "(adapter dirs with no bond: $(for d in /var/lib/bluetooth/*/; do n=$(ls "$d" 2>/dev/null | grep -cE '^([0-9A-F]{2}:){5}[0-9A-F]{2}$'); [ "$n" = 0 ] && basename "$d"; done | tr '\n' ' '))"
note ""
note "-- squash counters (per journal file) --"
grep -H '^\[squash\]' "$DIR"/07_*.txt "$DIR"/08_*.txt 2>/dev/null | sed "s|$DIR/||" >> "$CUR"

section 00 INDEX
note "Report folder: $DIR"
note "Copy 00_SUMMARY.txt first, then any file the analyst asks for. Lines per file:"
wc -l "$DIR"/*.txt | sed "s|$DIR/||" >> "$CUR"

echo ""
echo "Report written to: $DIR"
echo "  cat $DIR/00_INDEX.txt        # file list"
echo "  cat $DIR/00_SUMMARY.txt      # warnings + key facts"
echo "  scp -r <host>:$DIR .         # if file transfer is allowed"
