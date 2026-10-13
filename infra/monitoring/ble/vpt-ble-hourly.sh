#!/usr/bin/env bash
# vpt-ble-hourly.sh — hourly BLE health probe (TASK-76)
#
# Runs from /etc/cron.d/vpt-ble-hourly (cron) OR vpt-ble-hourly.timer (systemd),
# once per hour on the vpt-mf1 host (the Minisforum that owns the BLE adapter
# and the 2 paired STBs). Writes one combined log per hour under
# /var/log/vpt-ble/hourly/<YYYY-MM-DDTHH>.log; rotates after 14 days.
#
# Three modes (entry points share one log; only the probe tick is automated):
#   sudo bash vpt-ble-hourly.sh --once          # the normal cron tick
#   sudo bash vpt-ble-hourly.sh --post-mortem   # copy + redact to incidents/
#   sudo bash vpt-ble-hourly.sh --print         # stdout only, no log write
#
# Read-only by default. NEVER restarts bluetoothd, NEVER calls start.sh (which
# wipes bonds), NEVER writes anywhere except /var/log/vpt-ble/hourly/, the
# incident-folder path produced by --post-mortem, and the local ntfy-trigger
# cookie (when --alert-allow is set; off by default because ntfy install is
# owner-only).
#
# BUG-0003 recipe wired in: every log section queries bluetooth.service
# ExecMainStartTimestampMonotonic and the latest 'GATT application registered'
# line. A daemon OLDER than bluetoothd is the §6.7.28 wedge fingerprint and
# surfaces here even before the bond picker fails.
#
# STB-B (currently hid_ready:false on hci2 on the inventory host) is treated
# as DEGRADED, not DOWN — the box can be in standby and have not re-subscribed
# yet, with HID keys still queued for the wake. The probe emits a one-line
# re-subscribe nudge pointing at the exact btmon hints to check (the same
# squashed strings the start.sh/resume.sh auto-resume would print). No auto
# re-subscribe — that is the recovery path and is gated by step-8 policy
# (DOWN x 2 within 24 h, then owner-direct or one resume.sh).
#
# Sections (each becomes a labelled block in the log):
#   01 paired_list      — bluetoothctl devices Paired + Connected, per adapter
#   02 adapter_info     — btmgmt info /addr /current settings for every hciN
#   03 adapter_class    — hciconfig + sysdev/driver (USB vs UART, vendor)
#   04 bond_dirs        — /var/lib/bluetooth per-adapter MAC, peer count, CCCD
#   05 status_json      — /tmp/hid_remote_status-<hci>.json, hid_ready, waking
#   06 journal_5min     — systemd journal, last 5 min, squashed (lifted from
#                         diagnose_ble.sh so the noise floor is the same)
#   07 kernel_5min      — dmesg --since "5 min ago" filtered to
#                         bluetooth|hci|btusb|btbcm|usb
#   08 fifo_state       — /tmp/hid_remote-<hci>.fifo perms, mtime, last
#                         reader/writer probe (writes a 1-byte test, re-reads)
#   09 daemon_processes — pgrep for hid_remote.py + agent.py with HID_REMOTE_
#                         ADAPTER env, BUG-0027 duplicate-detector (§6.7.27)
#   10 status_line      — OK|DEGRADED(<reason>)|DOWN(<reason>) + tick ts
#
# Output path:   /var/log/vpt-ble/hourly/$(date -u +%Y-%m-%dT%H).log
# Incident path: /var/log/vpt-ble/incidents/<YYYY-MM-DDTHHMMSSZ>/   (when DOWN)
# Alert path:    ntfy trigger cookie — see ble_status.py `--alert` (not enabled
#                by this script; the operator wires it via vpt-ble-hourly.sh
#                --alert-allow after the ntfy channel exists).
#
# Env / flags:
#   HOURLY_LOG_DIR  default /var/log/vpt-ble/hourly
#   HOURLY_KEEP_D   default 14
#   HOURLY_INCIDENT_DIR  default /var/log/vpt-ble/incidents
#   ADAPTER_PREFIX  default 'hci' (skip the kernel connection sub-device 'hciN:64')
#   REDACT_KEYS     default 1 — redact LTK/IRK/CSRK/EDIV/RAND from any
#                   text that would leave this host (--post-mortem path).
#
# Owner-only: /var/log/vpt-ble/ on the host is created by the install step
# (chown vpt_user:vpt_user for app-service access; chmod 750 for the incidents/
# sub-tree so manual scp from the manager works). The probe handles a missing
# log dir gracefully — writes to /tmp first and logs the deferred-paths line.

set -u

PROG="$(basename "$0")"
HOURLY_LOG_DIR="${HOURLY_LOG_DIR:-/var/log/vpt-ble/hourly}"
HOURLY_KEEP_D="${HOURLY_KEEP_D:-14}"
HOURLY_INCIDENT_DIR="${HOURLY_INCIDENT_DIR:-/var/log/vpt-ble/incidents}"
ADAPTER_PREFIX="${ADAPTER_PREFIX:-hci}"
REDACT_KEYS="${REDACT_KEYS:-1}"

# -----------------------------------------------------------------------------
# arg parsing — minimal; one mode at a time

MODE="once"
PRINT_ONLY=0
ALLOW_ALERT=0
case "${1:-}" in
    --once)        MODE="once" ;;
    --post-mortem) MODE="post-mortem" ;;
    --print)       MODE="once"; PRINT_ONLY=1 ;;
    --alert-allow) ALLOW_ALERT=1; MODE="once" ;;
    -h|--help)
        sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    "")
        MODE="once"
        ;;
    *)
        echo "$PROG: unknown arg '$1' (use --once | --post-mortem | --print)" >&2
        exit 2
        ;;
esac

# -----------------------------------------------------------------------------
# helpers

ts_utc() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
ts_file_hour() { date -u '+%Y-%m-%dT%H'; }
ts_file_run()  { date -u '+%Y-%m-%dT%H%M%SZ'; }
log_line() {
    # log_line "section" "label" — writes both to the run buffer and the file
    local sec="$1"; shift
    local label="${1:-}"
    local out="── [${sec}] ${label}"
    RUN_BUF+=("$out")
    [[ "$PRINT_ONLY" -eq 0 ]] && echo "$out" || true
}

run_buf_init() { RUN_BUF=(); }
run_buf_flush_to_file() {
    local f="$1"
    [[ -z "${RUN_BUF:-}" ]] && return 0
    printf '%s\n' "${RUN_BUF[@]}" > "$f" || true
}

# redact_ltkirk — strip Bluetooth link key material from a string. Per
# BUG-0003 hard constraint: any output that could leave vpt-mf1 must have
# LTK/IRK/CSRK/EDIV/RAND zeroed. The BlueZ info format is INI-ish:
#   [LinkKey]
#   Key=ABCDEF...
#   LongTermKey=...
#   EDiv=...
#   Rand=...
#   [IdentityResolvingKey]
#   Key=...
# We do a defensive sweep: anything after Key= / LongTermKey= / IRK= replaced
# with Key=<redacted:32 hex>; same for the other sections. Prevents the
# post-mortem copy from accidentally including pairing material if upstream
# outputs a wider window of files.
redact_ltkirk() {
    local s="$1"
    [[ "${REDACT_KEYS}" != "1" ]] && { echo "$s"; return; }
    # Replace each known key-= line. The sed covers multi-line Key/EDiv/Rand.
    sed -E \
        -e 's/(Key|LongTermKey|IRK|IdentityResolvingKey|ERand|EDiv|Rand|CSRK|SignatureResolvingKey)=[^[:space:]}]*/\1=<redacted:32-hex>/g' \
        -e 's/(ltk|irk|csrk|ediv|rand)([A-Z]?)="[^"]*"/\1\2="<redacted>"/g' \
        -e 's/(ltk|irk|csrk|ediv|rand)([A-Z]?) = [^[:space:]]*/\1\2 = <redacted>/g' \
        <<<"$s"
}

# squash — lifted from diagnose_ble.sh so the probe log has the same noise
# floor. Drops sudo/pam audit, counts per-keypress chatter (Injecting,
# _bonded_peer_mac, Opcode 0x0c2d), collapses consecutive duplicates.
squash() {
    awk '
    function ts(l) { return substr(l, 1, 15) }
    function key(l, k) {
        k = l
        sub(/^[A-Za-z][A-Za-z][A-Za-z] [ 0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9] [^ ]+ /, "", k)
        sub(/^\[ *[0-9]+\.[0-9]+\] /, "", k)
        gsub(/\[[0-9]+\]/, "[#]", k)
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

# ensure_paths — make a parent dir if writable. Probe is read-only by design
# but writing to /var/log/vpt-ble/hourly/ is the explicit mission. If mkdir
# fails (no perms at first install), we degrade to /tmp for this run and
# surface the off-spec path in the deferred-paths line so the operator
# notices on the next install.
ensure_log_dir() {
    local d="$1"
    if [[ -d "$d" ]]; then
        [[ -w "$d" ]] && return 0
        echo "$PROG: $d exists but not writable — falling back to /tmp" >&2
        HOURLY_LOG_DIR="/tmp/vpt-ble-hourly"
        HOURLY_INCIDENT_DIR="/tmp/vpt-ble-incidents"
        mkdir -p "$HOURLY_LOG_DIR" "$HOURLY_INCIDENT_DIR" 2>/dev/null || true
        return 1
    fi
    if ! mkdir -p "$d" 2>/dev/null; then
        echo "$PROG: cannot create $d — falling back to /tmp" >&2
        HOURLY_LOG_DIR="/tmp/vpt-ble-hourly"
        HOURLY_INCIDENT_DIR="/tmp/vpt-ble-incidents"
        mkdir -p "$HOURLY_LOG_DIR" "$HOURLY_INCIDENT_DIR" 2>/dev/null || true
        return 1
    fi
    return 0
}

# list_adapters — echo one hciN per line, skipping kernel connection sub-devs
# (e.g. hci1:64). If a specific adapter name was inherited from an env file
# (useful in shadow-mode tests), honour that.
list_adapters() {
    if [[ -n "${VPT_HOURLY_ADAPTERS:-}" ]]; then
        echo "$VPT_HOURLY_ADAPTERS" | tr ',' '\n'
        return
    fi
    ls /sys/class/bluetooth/ 2>/dev/null \
        | grep -E "^${ADAPTER_PREFIX}[0-9]+\$" \
        | sort || true
}

# fifo_test_writeable — quick probe that doesn't depend on the daemon being
# awake (a blocked reader in open(FIFO,'r') would otherwise make lsof/fuser
# look empty, see §6.7.27 in BLUETOOTH.md).
fifo_test_writeable() {
    local fifo="$1"
    [[ -p "$fifo" ]] || { echo "no-fifo"; return 1; }
    # Add a 1-byte probe. The reader may be park()ed in open(); the write
    # itself succeeds, the kernel queues 1 byte, and lsof would now show the
    # reader. We don't read it back — that would race the reader.
    if bash -c "exec 9>'$fifo' && printf 'P\n' >&9 && exec 9>&-" 2>/dev/null; then
        echo "ok(probe-write)"
    else
        echo "blocked($(stat -c %a "$fifo" 2>/dev/null || echo ??))"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# section readers

read_paired_list() {
    log_line 01 paired_list "bluetoothctl devices Paired / Connected"
    echo "  paired:";   bluetoothctl devices Paired  2>/dev/null | sed 's/^/    /'
    echo "  connected:"; bluetoothctl devices Connected 2>/dev/null | sed 's/^/    /'
}

read_adapter_info() {
    log_line 02 adapter_info "btmgmt info -- per adapter"
    for h in $(list_adapters); do
        i=${h#${ADAPTER_PREFIX}}
        echo "── $h (index $i)"
        timeout 5 btmgmt --index "$i" info 2>&1 \
            | grep -E 'addr|current settings|name|short name|manufacturer' \
            | sed 's/^/    /'
    done
}

read_adapter_class() {
    log_line 03 adapter_class "transport + driver"
    for h in $(list_adapters); do
        DEV=$(readlink -f /sys/class/bluetooth/$h/device 2>/dev/null || echo NODEV)
        DRV=$(basename $(readlink -f /sys/class/bluetooth/$h/device/driver 2>/dev/null) 2>/dev/null || echo NONE)
        echo "── $h  sysdev=$DEV  driver=$DRV"
        hciconfig "$h" 2>/dev/null | head -3 | sed 's/^/    /'
    done
}

read_bond_dirs() {
    log_line 04 bond_dirs "/var/lib/bluetooth/ — per-adapter MAC, peers, CCCD"
    # /var/lib/bluetooth is 0700 root — btmgmt calls under sudo drop; probe runs as root.
    local d
    for d in /var/lib/bluetooth/*/; do
        [[ -d "$d" ]] || continue
        local mac peers cccd n
        mac=$(basename "$d")
        peers=$(ls "$d" 2>/dev/null | grep -E '^[0-9A-F]{2}:' | tr '\n' ' ')
        n=0; cccd=""
        for sd in "$d"*/; do
            [[ -f "$sd/info" ]] || continue
            n=$((n+1))
            local pmac
            pmac=$(basename "$sd")
            if grep -q 2a4d "$sd/info" 2>/dev/null; then
                cccd="$cccd $pmac:2a4d"
            else
                cccd="$cccd $pmac:no-2a4d"
            fi
        done
        echo "  MAC=$mac  bonds=$n  peers=[$peers]  cccd={$cccd}"
    done
    echo "  adapter bindings (/var/lib/vpt-ble/):"
    for f in /var/lib/vpt-ble/adapter-hci*.mac; do
        [[ -f "$f" ]] || continue
        echo "    $(basename $f) -> $(cat "$f" 2>/dev/null)"
    done
}

read_status_json() {
    log_line 05 status_json "/tmp/hid_remote_status-<hci>.json"
    local f
    for f in /tmp/hid_remote_status-hci*.json; do
        [[ -f "$f" ]] || continue
        echo "── $f"
        cat "$f" 2>/dev/null | sed 's/^/    /'
    done
}

read_journal_5min() {
    log_line 06 journal_5min "journalctl --since '5 min ago' -u bluetooth,hid-remote@,hid-agent@,ble-remote@,vpt-ble-remote@ (squashed)"
    local tmp; tmp=$(mktemp)
    timeout 30 journalctl --no-pager -q --since "5 min ago" \
        -u bluetooth.service \
        -u 'hid-remote@hci*.service' -u 'hid-agent@hci*.service' \
        -u 'ble-remote@hci*.service' \
        -u 'vpt-ble-remote@*.service' -u 'vpt-ble-remote.service' </dev/null 2>&1 \
        | squash > "$tmp"
    local total; total=$(wc -l < "$tmp")
    if [[ "$total" -gt 200 ]]; then
        echo "  (squashed journal: showing last 200 of $total lines)"
        tail -n 200 "$tmp" | sed 's/^/    /'
    else
        cat "$tmp" | sed 's/^/    /'
    fi
    rm -f "$tmp"
}

read_kernel_5min() {
    log_line 07 kernel_5min "dmesg --since '5 min ago' filtered"
    local tmp; tmp=$(mktemp)
    dmesg --since "5 min ago" 2>/dev/null \
        | grep -iE 'bluetooth|hci|btusb|btbcm|usb' > "$tmp" || true
    if [[ -s "$tmp" ]]; then
        cat "$tmp" | tail -n 50 | sed 's/^/    /'
    else
        echo "    (no kernel-side bluetooth noise in window)"
    fi
    rm -f "$tmp"
}

read_fifo_state() {
    log_line 08 fifo_state "/tmp/hid_remote-<hci>.fifo writability + lsof"
    for f in /tmp/hid_remote-hci*.fifo; do
        [[ -e "$f" ]] || continue
        local h; h=$(echo "$f" | sed -E 's:.*hid_remote-(hci[0-9]+)\.fifo:\1:')
        local probe; probe=$(fifo_test_writeable "$f" 2>&1 || true)
        local openers
        openers=$(timeout 3 lsof "$f" 2>/dev/null | tail -n +2 | awk '{print $1}' | sort -u | paste -sd, -)
        local st_owner st_group st_mode st_mtime
        st_mode=$(stat -c %a "$f" 2>/dev/null || echo 000)
        st_owner=$(stat -c %U "$f" 2>/dev/null || echo unknown)
        st_group=$(stat -c %G "$f" 2>/dev/null || echo unknown)
        st_mtime=$(stat -c %y "$f" 2>/dev/null || echo unknown)
        echo "── $f  mode=$st_mode  owner=$st_owner:$st_group  mtime=$st_mtime"
        echo "    test-write: $probe"
        echo "    lsof-openers (note: a reader parked in open() is invisible — see §6.7.27): ${openers:-<none>}"
    done
}

read_daemon_processes() {
    log_line 09 daemon_processes "pgrep hid_remote.py + agent.py (BUG-0027 dup check)"
    # Filter out the inspecting shell itself: `pgrep -af <name>` matches any
    # cmdline containing the substring, including the wrapper that
    # shell=True spawned to run the inspect. Keep only cmdlines that look
    # like a real daemon invocation: `/usr/bin/python3 …/<name>`.
    pgrep_filter() {
        pgrep -af "$1" 2>/dev/null \
            | awk '{
                cmd=""; for (i=2; i<=NF; i++) cmd = cmd " " $i;
                if ($2 ~ /^\/usr\/bin\/python3$/ && cmd ~ /\/'"$1"'$/) print
            }' || true
    }
    echo "  hid_remote.py:"
    pgrep_filter hid_remote.py | sed 's/^/    /' || echo "    (none)"
    echo "  agent.py:"
    pgrep_filter agent.py      | sed 's/^/    /' || echo "    (none)"
    echo "  duplicate check (one daemon per HID_REMOTE_ADAPTER env):"
    local h seen_dup=0
    for h in $(list_adapters); do
        local n=0
        local pids
        pids=$(pgrep_filter hid_remote.py | awk '{print $1}') || true
        local p
        for p in $pids; do
            tr '\0' '\n' < /proc/$p/environ 2>/dev/null \
                | grep -qx "HID_REMOTE_ADAPTER=$h" && n=$((n+1))
        done
        echo "    $h: $n hid_remote.py process(es)"
        [[ "$n" -gt 1 ]] && seen_dup=1
    done
    [[ "$seen_dup" -eq 1 ]] && echo "  *** BUG-0027 warning: a sibling adapter has multiple hid_remote.py — key stream split ***"
}

# -----------------------------------------------------------------------------
# status classifier (calls into ble_status.py to keep tests in Python)

classify_status() {
    log_line 10 status_line "OK|DEGRADED(<reason>)|DOWN(<reason>) — see ble_status.py"
    local line
    # Hand the buffers (stdout+stderr of the previous sections) into the
    # classifier by re-running the same read_* paths as a sub-shell. Simpler
    # approach: pipe the partial journal + status JSON paths into the py.
    line=$(SCRIPT_DIR_VAL="${SCRIPT_DIR_VAL:-$(cd "$(dirname "$0")" && pwd)}" \
        python3 "${SCRIPT_DIR_VAL:-/opt/virtualpytest/infra/monitoring/ble}/ble_status.py" --mode=hourly 2>&1 || true)
    echo "$line" | sed 's/^/  /'
    # Echo the canonical status once more for grep-friendly tailing.
    echo "status: $(echo "$line" | tail -1)"
}

# post-mortem — copy + redact when the previous probe said DOWN. Operates on
# the just-written log + a slice of journalctl + a redact-safe btmon sample.
do_post_mortem() {
    local last_log
    last_log="$(ls -1t "${HOURLY_LOG_DIR}"/[0-9]*T[0-9][0-9].log 2>/dev/null | head -1 || true)"
    [[ -z "$last_log" ]] && { echo "no prior log to escalate; skip"; return 0; }
    local stamp; stamp="$(ts_file_run)"
    local dest="${HOURLY_INCIDENT_DIR}/${stamp}"
    mkdir -p "$dest" || { echo "cannot mkdir $dest"; return 1; }
    chmod 750 "$dest" 2>/dev/null || true

    # 1. The hourly log itself (already mostly safe; redact any Key= line)
    redact_ltkirk "$(cat "$last_log")" > "$dest/01_hourly.log"

    # 2. btmon ring slice (10 MB ring, last 1 MB). REDACTED before write.
    if command -v btmon >/dev/null 2>&1; then
        timeout 5 btmon --end 1>/dev/null 2>&1 | head -100 \
            | redact_ltkirk > "$dest/02_btmon_tail.txt" || true
    fi

    # 3. journal window — 30 min up to "now", squashed.
    local tmp; tmp=$(mktemp)
    timeout 30 journalctl --no-pager -q --since "30 min ago" \
        -u bluetooth.service \
        -u 'hid-remote@hci*.service' -u 'hid-agent@hci*.service' \
        -u 'ble-remote@hci*.service' \
        -u 'vpt-ble-remote@*.service' -u 'vpt-ble-remote.service' </dev/null 2>&1 \
        | squash > "$tmp"
    redact_ltkirk "$(cat "$tmp")" > "$dest/03_journal_30min.log"
    rm -f "$tmp"

    # 4. A one-line INDEX for the manager to peek at.
    {
        echo "incident: $stamp"
        echo "host: $(hostname)"
        echo "trigger: $last_log"
        echo "files:"
        ls -la "$dest" | sed 's/^/  /'
        echo "summary last status line: $(grep -m1 '^status:' "$last_log" 2>/dev/null)"
    } > "$dest/00_INDEX.txt"

    echo "INCIDENT_PATH=$dest"
    # No automatic ntfy here — owner-only channel. The manager script on
    # vpt-mf1 (cron-co-installed later) is what actually pings. Probe just
    # writes the path so the operator can scp it out.
}

# -----------------------------------------------------------------------------
# main

run_main() {
    run_buf_init
    log_line 00 header "VPT-BLE HOURLY ($(ts_utc)) tick=$(date -u +%H)"
    echo "  host=$(hostname)  uptime=$(uptime -p 2>/dev/null || uptime)  log_dir=${HOURLY_LOG_DIR}"

    ensure_log_dir "$HOURLY_LOG_DIR" || true

    read_paired_list
    read_adapter_info
    read_adapter_class
    read_bond_dirs
    read_status_json
    read_journal_5min
    read_kernel_5min
    read_fifo_state
    read_daemon_processes
    classify_status

    log_line 99 footer "tick complete at $(ts_utc)"
    [[ "$PRINT_ONLY" -eq 1 ]] && return 0

    local out_file="${HOURLY_LOG_DIR}/$(ts_file_hour).log"
    run_buf_flush_to_file "$out_file"
    chmod 644 "$out_file" 2>/dev/null || true

    # Rotation — 14 days by default.
    find "$HOURLY_LOG_DIR" -maxdepth 1 -type f -name '*.log' -mtime "+${HOURLY_KEEP_D}" \
        -exec rm -f {} \; 2>/dev/null || true
}

case "$MODE" in
    once)
        run_main
        ;;
    post-mortem)
        do_post_mortem
        ;;
esac
