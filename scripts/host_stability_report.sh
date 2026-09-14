#!/usr/bin/env bash
# host_stability_report.sh — collect evidence that a backend_host box is
# STABLE (uptime, resource headroom, disk/SSD health, crash history, patch
# status) — NOT a configuration/functional check (that's diagnose_ble.sh).
# Ends with an automated OK/KO verdict table so you don't have to interpret
# the raw data by eye.
#
# Read-only: runs `apt-get update` (refreshes the package index, installs
# nothing) and otherwise only reads system state. Safe to run anytime,
# including on a live production host.
#
# Usage:
#   sudo bash host_stability_report.sh
#
# Output: /tmp/stability_<hostname>_<timestamp>.log (path printed at the end)
# Hand that file to the client as the "is this box golden-ready" evidence.
# Layout: VERDICT first, full details below it — checks run in order through
# the script (so the verdict can't be known until the end), but the report is
# reordered before it's written so you read the answer before the evidence.
# The terminal goes quiet during collection (a minute or two — apt-get update
# and du on a large disk are the slow parts) and dumps the full report at the end.

OUT="/tmp/stability_$(hostname)_$(date +%Y%m%d_%H%M%S).log"
DETAIL_FILE="$(mktemp)"
trap 'rm -f "$DETAIL_FILE"' EXIT

exec 3>&1 4>&2
exec > "$DETAIL_FILE" 2>&1

run() {
    echo ""
    echo "----8<---- \$ $* ----"
    timeout 20 "$@" </dev/null 2>&1 || echo "[exit=$? — command failed, timed out, or not installed]"
}

section() {
    echo ""
    echo "================================================================"
    echo "== $1"
    echo "================================================================"
}

# --- verdict table: every check below appends one row here, printed as a
# single OK/KO summary at the end (section 10) instead of making the reader
# interpret raw command output by eye. ---
VERDICT_ROWS=()
KO_COUNT=0
verdict() {
    local name="$1" status="$2" detail="$3"
    VERDICT_ROWS+=("$(printf '%-4s %-26s %s' "$status" "$name" "$detail")")
    [ "$status" = "KO" ] && KO_COUNT=$((KO_COUNT + 1))
}

section "0. Identity"
run hostname
run date
run cat /etc/os-release
run cat /etc/debian_version
run uname -a

section "1. Patch status (apt-get update is read-only — refreshes index, installs nothing)"
echo ""
echo "----8<---- \$ apt-get update ----"
APT_OUT="$(timeout 90 apt-get update </dev/null 2>&1)"
APT_RC=$?
echo "$APT_OUT"
[ "$APT_RC" -ne 0 ] && echo "[exit=$APT_RC — command failed or timed out; upgradable-count below is from a STALE/PARTIAL index]"

run bash -c "apt list --upgradable 2>/dev/null"
UPGRADABLE="$(apt list --upgradable 2>/dev/null | tail -n +2)"
N_UPGRADABLE=$(echo "$UPGRADABLE" | grep -c . || true)
echo ""
echo "Total upgradable packages: $N_UPGRADABLE"
KERNEL_BLUEZ=$(echo "$UPGRADABLE" | grep -iE '^(linux-image|linux-headers|bluez|bluetooth|firmware-)' || true)
if [ -n "$KERNEL_BLUEZ" ]; then
    echo ""
    echo "*** kernel/bluez/firmware packages pending — these need a reboot +"
    echo "*** BLE/IR revalidation pass before/after applying, not a casual"
    echo "*** apt upgrade on the live golden box: ***"
    echo "$KERNEL_BLUEZ"
fi
run systemctl is-enabled unattended-upgrades.service
run systemctl status unattended-upgrades.service --no-pager -l

if [ "$APT_RC" -ne 0 ]; then
    verdict "Patch status" "KO" "apt-get update failed/timed out — upgradable count NOT verified, re-run"
elif [ -n "$KERNEL_BLUEZ" ]; then
    verdict "Patch status" "OK" "$N_UPGRADABLE upgradable, incl. kernel/bluez — plan a reboot+BLE revalidation window, not blocking"
else
    verdict "Patch status" "OK" "$N_UPGRADABLE upgradable, none kernel/bluez/firmware"
fi

section "2. Boot / crash history — last 2 weeks (recent behavior is what matters for a go-live decision, not history from months back)"
run uptime
run who -b
SINCE_2W="$(date -d '-14 days' '+%Y-%m-%d')"
REBOOT_LOG="$(timeout 20 last -x reboot --since "$SINCE_2W" </dev/null 2>&1)"
echo ""
echo "----8<---- \$ last -x reboot --since $SINCE_2W ----"
echo "$REBOOT_LOG"
SHUTDOWN_LOG="$(timeout 20 last -x shutdown --since "$SINCE_2W" </dev/null 2>&1)"
echo ""
echo "----8<---- \$ last -x shutdown --since $SINCE_2W ----"
echo "$SHUTDOWN_LOG"
echo ""
echo "Looking for unclean shutdowns in journal for the boot immediately before this one"
echo "(NOTE: journald skips boots that never flushed data, e.g. near-instant re-reboots —"
echo "so '-b -1' may land on an older boot than the last entry above, not literally 'previous'):"
run journalctl -k -b -1 -n 20 --no-pager

CRASH_N=$(echo "$REBOOT_LOG" | grep -ci crash || true)
REBOOT_N=$(echo "$REBOOT_LOG" | grep -c '^reboot' || true)
if [ "$CRASH_N" -gt 0 ]; then
    verdict "Reboots (last 14d)" "KO" "$CRASH_N crash-marked entr(y/ies) among $REBOOT_N reboot(s)"
else
    verdict "Reboots (last 14d)" "OK" "$REBOOT_N reboot(s), none crash-marked"
fi

section "3. CPU"
NPROC_N="$(nproc)"
LOAD1="$(awk '{print $1}' /proc/loadavg)"
run nproc
run bash -c "cat /proc/loadavg"
run vmstat 1 3
run bash -c "top -bn1 | head -15"
if awk -v l="$LOAD1" -v n="$NPROC_N" 'BEGIN{exit !(l<n)}'; then
    verdict "CPU load" "OK" "load1=$LOAD1 across $NPROC_N cores"
else
    verdict "CPU load" "KO" "load1=$LOAD1 across $NPROC_N cores — at/over core count"
fi

section "4. Memory"
run free -h
MEM_TOTAL="$(free -m | awk '/^Mem:/{print $2}')"
MEM_AVAIL="$(free -m | awk '/^Mem:/{print $7}')"
echo ""
echo "OOM-kill events (if any — indicates the box has run out of memory under load):"
OOM_OUT="$(timeout 20 journalctl -k --no-pager -g 'Out of memory|oom-kill' </dev/null 2>&1)"
echo "$OOM_OUT"
if echo "$OOM_OUT" | grep -qi "no entries"; then OOM_N=0; else OOM_N=$(echo "$OOM_OUT" | grep -c .); fi
if [ "${MEM_AVAIL:-0}" -gt 1024 ] 2>/dev/null && [ "$OOM_N" -eq 0 ]; then
    verdict "Memory" "OK" "${MEM_AVAIL}MB available / ${MEM_TOTAL}MB total, 0 OOM-kills"
else
    verdict "Memory" "KO" "${MEM_AVAIL}MB available / ${MEM_TOTAL}MB total, OOM events=$OOM_N"
fi

section "5. Disk headroom"
DF_OUT="$(timeout 20 df -h -x tmpfs -x devtmpfs -x efivarfs </dev/null 2>&1)"
echo ""
echo "----8<---- \$ df -h (real filesystems only) ----"
echo "$DF_OUT"
run df -i
run lsblk
while IFS= read -r fsline; do
    usep="$(echo "$fsline" | awk '{print $5}' | tr -d '%')"
    mnt="$(echo "$fsline" | awk '{print $6}')"
    [ -z "$usep" ] && continue
    case "$usep" in ''|*[!0-9]*) continue ;; esac
    if [ "$usep" -ge 90 ]; then
        verdict "Disk $mnt" "KO" "${usep}% used (>=90% threshold)"
    else
        verdict "Disk $mnt" "OK" "${usep}% used"
    fi
done <<< "$(echo "$DF_OUT" | tail -n +2)"

section "6. /data usage breakdown — understand WHAT is using the space, not just that it's high"
DATA_PCT="$(echo "$DF_OUT" | awk '$NF=="/data"{gsub(/%/,"",$5); print $5}')"
echo ""
echo "Top consumers under /data (can take a while on a large, mostly-full drive):"
timeout 90 du -h --max-depth=2 /data 2>/dev/null | sort -rh | head -25

echo ""
echo "One level deeper — what KIND of content is filling each capture channel (recordings vs"
echo "references vs reports vs raw segments), not just which channel:"
timeout 120 du -h --max-depth=3 /data/stream 2>/dev/null | sort -rh | head -40

echo ""
echo "VPT's own capture pipeline expects segment_*.ts / capture_*.jpg under /data/stream to be"
echo "cleaned up within 24h (backend_host disk_usage_service.analyze_cleanup_health). Files"
echo "older than that mean cleanup is broken — that's a growth driver, not expected accumulation:"
OLD_SEGMENTS="$(timeout 30 find /data/stream -maxdepth 4 -name 'segment_*.ts' -mmin +1440 2>/dev/null | wc -l)"
OLD_CAPTURES="$(timeout 30 find /data/stream -maxdepth 4 -name 'capture_*.jpg' -mmin +1440 2>/dev/null | wc -l)"
echo "segment_*.ts older than 24h: $OLD_SEGMENTS"
echo "capture_*.jpg older than 24h: $OLD_CAPTURES"
if [ "$OLD_SEGMENTS" -eq 0 ] && [ "$OLD_CAPTURES" -eq 0 ]; then
    verdict "Capture cleanup" "OK" "no stale segment/capture files past the 24h retention window"
else
    verdict "Capture cleanup" "KO" "$OLD_SEGMENTS old segment(s), $OLD_CAPTURES old capture(s) — cleanup not keeping up"
fi

section "7. SSD/NVMe hardware health (this is what actually proves the drive is fit to be cloned)"
for dev in /dev/nvme0n1 /dev/nvme1n1; do
    [ -e "$dev" ] || continue
    echo ""
    echo "-- $dev --"
    if command -v nvme >/dev/null; then
        SMART_OUT="$(timeout 20 nvme smart-log "$dev" </dev/null 2>&1)"
        echo "$SMART_OUT"
        CRIT="$(echo "$SMART_OUT" | awk -F': *' '/^critical_warning/{print $2}' | tr -d ' ')"
        MEDIA="$(echo "$SMART_OUT" | awk -F': *' '/^media_errors/{print $2}' | tr -d ' ')"
        PCTUSED="$(echo "$SMART_OUT" | awk -F': *' '/^percentage_used/{print $2}' | tr -d ' %')"
        if [ -n "$CRIT" ] && [ -n "$MEDIA" ]; then
            if [ "$CRIT" = "0" ] && [ "$MEDIA" = "0" ] && [ "${PCTUSED:-0}" -lt 80 ] 2>/dev/null; then
                verdict "SSD health $dev" "OK" "critical_warning=$CRIT media_errors=$MEDIA percentage_used=${PCTUSED:-?}%"
            else
                verdict "SSD health $dev" "KO" "critical_warning=$CRIT media_errors=$MEDIA percentage_used=${PCTUSED:-?}%"
            fi
        else
            verdict "SSD health $dev" "KO" "could not parse smart-log output — verify manually"
        fi
    elif command -v smartctl >/dev/null; then
        run smartctl -a "$dev"
        verdict "SSD health $dev" "KO" "only smartctl available (not auto-parsed) — review output above manually"
    else
        echo "[neither nvme-cli nor smartmontools installed — install one to get wear-level/media-error data: apt-get install nvme-cli]"
        verdict "SSD health $dev" "KO" "no SMART tool installed — cannot verify"
    fi
done

section "8. Kernel-level errors (I/O errors, filesystem errors, hardware faults — Bluetooth excluded, that's diagnose_ble.sh's job)"
KERNEL_ERRS="$(dmesg -T 2>/dev/null | grep -iE 'error|fail|i/o error|ata[0-9]|nvme.*error|segfault' | grep -viE 'bluetooth|hci[0-9]')"
echo "$KERNEL_ERRS" | tail -n 60
if [ -z "$KERNEL_ERRS" ]; then
    verdict "Kernel errors (non-BT)" "OK" "none found"
else
    N="$(echo "$KERNEL_ERRS" | grep -c .)"
    verdict "Kernel errors (non-BT)" "KO" "$N line(s) found — see section above"
fi

section "9. Failed systemd units (any service that's crash-looping or dead)"
FAILED_OUT="$(timeout 20 systemctl --failed --no-pager </dev/null 2>&1)"
echo "$FAILED_OUT"
if echo "$FAILED_OUT" | grep -q "^0 loaded units listed"; then
    verdict "Failed systemd units" "OK" "0 failed units"
else
    verdict "Failed systemd units" "KO" "see section above"
fi

# --- collection done — restore the terminal and write VERDICT-first, details-below ---
exec >&3 2>&4

{
    echo "================================================================"
    echo "== VERDICT — read this first"
    echo "================================================================"
    echo ""
    echo "host: $(hostname)   generated: $(date)"
    echo ""
    echo "Thresholds: disk >=90% used, SSD wear >=80% or any media/critical error, CPU load1 >= core"
    echo "count, memory <1GB available, any OOM-kill / non-BT kernel error / failed unit / crash-marked"
    echo "reboot / stale (>24h) capture file, or a failed data-collection step = KO."
    echo ""
    for row in "${VERDICT_ROWS[@]}"; do
        echo "$row"
    done
    echo ""
    if [ "$KO_COUNT" -eq 0 ]; then
        echo "OVERALL: OK — no failing checks. This covers host stability only;"
        echo "still confirm BLE/IR functionally with diagnose_ble.sh before calling it golden."
    else
        echo "OVERALL: KO — $KO_COUNT check(s) failing above. Resolve before treating this as golden."
    fi
    echo ""
    echo "================================================================"
    echo "== FULL DETAILS (sections 0-9) — evidence backing the verdict above"
    echo "================================================================"
    cat "$DETAIL_FILE"
    echo ""
    echo "================================================================"
    echo "Report written to: $OUT"
    echo "Copy it off the box with:  scp <host>:$OUT ."
} | tee "$OUT"
