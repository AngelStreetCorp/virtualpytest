#!/usr/bin/env bash
# Start (or restart) the BLE HID remote peripheral.
#
# Wipes all host-side pairing state so the next STB pair attempt starts
# from zero: stops the peripheral services, removes every bonded device,
# clears the BlueZ on-disk cache for the adapter, restarts bluetooth,
# reapplies LE-only + NoInputNoOutput, and launches hid-agent + hid-remote
# as transient systemd units.
#
# Usage:  sudo ~/ble-remote/start.sh
#
# Adapter selection (ADAPTER_HCI env, default hci0):
#   - Pi (host1, host3):   ADAPTER_HCI=hci0   (onboard BCM4345C0, UART)
#   - Minisforum (host3) Belkin dongle:   ADAPTER_HCI=hci1   (Broadcom, USB)
# The firmware-reset step auto-detects UART vs USB from
# /sys/class/bluetooth/$ADAPTER_HCI/device.
#
# After this runs, the STB must also forget the remote on its side and
# start a fresh pairing flow — we cannot clear the STB's cache from here.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"

# ----- Adapter selection -----
ADAPTER_HCI="${ADAPTER_HCI:-hci0}"
ADAPTER_INDEX="${ADAPTER_HCI#hci}"
BLE_TYPE="${BLE_TYPE:-arris}"

# Mirror all stdout+stderr to a per-adapter file so the run is tailable in
# real time even when this script is launched via subprocess.run with
# capture_output=True (which buffers output until exit, hiding progress).
# Per-adapter naming because multi-device hosts can run several start.sh
# instances in parallel (one per BLE controller); a shared file would
# interleave them illegibly. Tail with: `tail -f /tmp/ble-start-hciN.log`
exec > >(tee -a "/tmp/ble-start-${ADAPTER_HCI}.log") 2>&1
# Force our own stdin to an empty, already-closed pipe — NEVER /dev/null.
# On the bluetoothd 5.82 build (Debian 13) every `btmgmt` invocation WEDGES
# (blocks until killed, rc=124) when its stdin is /dev/null, but returns
# immediately with full output when stdin is a pipe (verified 2026-06-01:
# `btmgmt le on </dev/null` → rc=124; `btmgmt le on < <(:)` → rc=0). Our
# btmgmt calls run inside `$(…)` command substitutions, which inherit the
# script's stdin — so whatever fd0 we get here is what every btmgmt sees.
# When launched by gunicorn (Flask Pair button) or by the boot unit
# ble-remote@.service, that inherited fd0 is the service's StandardInput=null
# = /dev/null, which silently wedged every adapter-config call (le on, MAC
# spoof, power on) → the radio never advertised → no pair, no resume. A TTY
# (manual run) didn't hit this, which is why "works by hand, hangs from the
# UI" looked like a gunicorn-vs-terminal mystery for so long. Overriding fd0
# to a pipe here makes start.sh launcher-independent. Do NOT change this to
# `< /dev/null`. See BLUETOOTH.md §6.7.23 (stdin wedge).
exec < <(:)
echo "===== start.sh begin $(date -Is) (pid=$$ adapter=${ADAPTER_HCI}) ====="
echo "  invoked as uid=$(id -u) euid=$EUID user=$(id -un) sudo_user=${SUDO_USER:-none} tty=$(tty 2>/dev/null || echo none)"
echo "  PATH=$PATH"

# Trace every command from here on. The "Reapplying adapter settings" block
# fires eight silent btmgmt calls back-to-back; without xtrace the log
# jumps straight from the section header to the next header with no clue
# which command actually hung. With `set -x` every command is logged to
# the same tee'd file as `+ btmgmt --index 1 power off`, so the LAST line
# in the log when the controller's 60s timeout fires is the wedged call.
# Output goes to stderr — already merged into the log by the exec above.
set -x

SPOOF_MAC_PREFIX="20:21:41:00:1F"

# Reuse THIS adapter's already-assigned MAC if one is persisted — BEFORE any
# auto-pick. Re-pairing must NOT march to a fresh byte: the STB's bond is
# stored on disk UNDER the adapter's MAC, so changing the MAC orphans the bond
# (frontend shows "No Bluetooth pairing found" even though the bond is intact)
# and accelerates a runaway 1F:01 -> 02 -> 03 -> ... march, because each prior
# bond dir then counts as a "used" byte. The persisted
# /var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac IS the adapter's stable identity:
# reuse it, and only auto-pick a fresh byte the FIRST time an adapter has no
# binding. See BLUETOOTH.md §6.7.26.
if [[ -z "${ADAPTER_MAC:-}" ]]; then
    _own_bind="/var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac"
    if [[ -f "$_own_bind" ]]; then
        _cand="$(tr -d '[:space:]' < "$_own_bind" 2>/dev/null || true)"
        if [[ "$_cand" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:[0-9A-Fa-f]{2}$ ]]; then
            ADAPTER_MAC="$_cand"
            echo "== Reusing ${ADAPTER_HCI}'s assigned MAC $ADAPTER_MAC (no march) =="
        fi
    fi
fi

# Auto-pick a fresh byte ONLY for a brand-new adapter (no valid binding above).
if [[ -z "${ADAPTER_MAC:-}" ]]; then
    declare -A USED_BYTES=()
    # (1) Bytes that have a persisted bond dir on disk
    for entry in /var/lib/bluetooth/*; do
        [[ -d "$entry" ]] || continue
        base="$(basename "$entry")"
        if [[ "$base" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:([0-9A-Fa-f]{2})$ ]]; then
            USED_BYTES["${BASH_REMATCH[1]^^}"]=1
        fi
    done
    # (2) Bytes currently advertised by SIBLING adapters on this host
    # (multi-instance safety, §6.7.22-followup-9).
    # /var/lib/bluetooth/ alone is insufficient: if hci2 is freshly
    # configured to 20:21:41:00:1F:08 but hasn't paired yet, no dir
    # exists for that MAC, and this script would happily pick :08 for
    # hci1 → both chips end up with the same MAC, the STB sees a
    # collision, get_pairing_status returns nonsense, and no peer can
    # bond. Querying `btmgmt info` for every sibling closes that gap.
    for sysdir in /sys/class/bluetooth/hci*; do
        [[ -d "$sysdir" ]] || continue
        other_hci="$(basename "$sysdir")"
        # Skip kernel connection sub-devices like `hci1:64` (created by
        # the L2CAP layer when an STB is connected). They share a prefix
        # with the real controller and would re-mark the parent's byte.
        [[ "$other_hci" =~ ^hci[0-9]+$ ]] || continue
        [[ "$other_hci" == "$ADAPTER_HCI" ]] && continue
        other_idx="${other_hci#hci}"
        other_addr=$(timeout 5 btmgmt --index "$other_idx" info 2>&1 \
            | grep -oE 'addr [0-9A-F:]{17}' | head -1 | awk '{print $2}')
        if [[ "$other_addr" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:([0-9A-Fa-f]{2})$ ]]; then
            USED_BYTES["${BASH_REMATCH[1]^^}"]=1
            echo "  marking sibling $other_hci current spoof byte ${BASH_REMATCH[1]^^} as used"
        fi
    done
    # (3) MACs PERSISTED as belonging to a sibling adapter. Survives reboot
    # and covers the window where a sibling's chip isn't configured yet, so
    # step (2)'s `btmgmt info` can't see its address. Without this, two
    # adapters booting together could both auto-pick the same free byte.
    for macfile in /var/lib/vpt-ble/adapter-hci*.mac; do
        [[ -f "$macfile" ]] || continue
        [[ "$macfile" == "/var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac" ]] && continue
        sib_mac="$(tr -d '[:space:]' < "$macfile" 2>/dev/null || true)"
        if [[ "$sib_mac" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:([0-9A-Fa-f]{2})$ ]]; then
            USED_BYTES["${BASH_REMATCH[1]^^}"]=1
            echo "  marking persisted sibling MAC $sib_mac (byte ${BASH_REMATCH[1]^^}) as used"
        fi
    done
    USED_BYTES["91"]=1   # real UE remote
    PICKED=""
    for i in $(seq 1 255); do
        hex=$(printf "%02X" "$i")
        if [[ -z "${USED_BYTES[$hex]:-}" ]]; then
            PICKED="$hex"
            break
        fi
    done
    if [[ -z "$PICKED" ]]; then
        echo "ERROR: all 254 spoof MAC bytes in $SPOOF_MAC_PREFIX:XX are burned" >&2
        exit 2
    fi
    ADAPTER_MAC="$SPOOF_MAC_PREFIX:$PICKED"
    echo "== Auto-picked fresh adapter MAC: $ADAPTER_MAC =="
fi

# Persist the hci -> spoofed-MAC binding so resume.sh can re-apply THIS
# adapter's MAC deterministically after a reboot, instead of guessing from
# the shared /var/lib/bluetooth/${SPOOF_MAC_PREFIX}:* glob. With two adapters
# sharing the prefix, that glob let hci1 grab hci2's bond and vice-versa —
# the multi-adapter resume-collision bug. Written unconditionally (covers an
# explicit ADAPTER_MAC override too). See BLUETOOTH.md §6.7.23-followup.
mkdir -p /var/lib/vpt-ble 2>/dev/null || true
printf '%s\n' "$ADAPTER_MAC" > "/var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac" 2>/dev/null || true
echo "== Persisted adapter binding: ${ADAPTER_HCI} -> ${ADAPTER_MAC} =="

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo)." >&2
    exit 1
fi

LOCKFILE="/tmp/ble-remote-pairing-${ADAPTER_HCI}.lock"
# Per-adapter lockfile (§6.7.22-followup-5): the previous global
# `/tmp/ble-remote-pairing.lock` serialised pair attempts across
# adapters, which broke multi-adapter hosts (a host can run both an
# onboard hci0 and a USB Belkin hci1). With a global lock the
# second adapter's run exited 4 even though both were legitimate
# independent operations. Scoping to ADAPTER_HCI lets parallel runs
# proceed on different controllers — the `BT_RESTART_LOCK` below
# still serialises the bluetoothd restart so the two scripts don't
# bounce each other's daemon state.
if [[ -f "$LOCKFILE" ]]; then
    lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCKFILE" 2>/dev/null || echo 0) ))
    if [[ $lock_age -lt 60 ]]; then
        echo "ERROR: start.sh already ran ${lock_age}s ago on $ADAPTER_HCI (lock: $LOCKFILE)." >&2
        echo "Wait $((60 - lock_age))s or remove $LOCKFILE to force." >&2
        exit 4
    fi
fi
echo $$ > "$LOCKFILE"
chmod 666 "$LOCKFILE"
# Hand ownership to the invoking user so the controller's
# _clear_pairing_lock() (bluetooth.py) can unlink it on the next re-pair
# attempt. Without this the file is root-owned, /tmp's sticky bit blocks
# non-root unlink, and consecutive Repair clicks within 120s silently no-op
# because the lockfile check refuses to run start.sh again.
if [[ -n "${SUDO_USER:-}" ]]; then
    chown "${SUDO_USER}:" "$LOCKFILE" 2>/dev/null || true
fi

# Per-adapter daemon unit names — multi-instance support. Each adapter
# runs its own hid-remote / hid-agent so two BLE peripherals can coexist
# on one host (host3: hci1 Belkin + hci2 second Belkin).
# Singletons were the original design; switched to per-adapter as part
# of §6.7.22-followup-6.
# Persistent template units (hid-remote@.service / hid-agent@.service),
# replacing the old transient hid-remote-${ADAPTER_HCI}.service that
# `systemd-run` created. A persistent unit file is never deleted, so the
# stop/relaunch every re-pair performs no longer storms systemd with
# "Failed to open /run/systemd/transient/...". See BLUETOOTH.md §6.7.25.
HID_REMOTE_UNIT="hid-remote@${ADAPTER_HCI}.service"
HID_AGENT_UNIT="hid-agent@${ADAPTER_HCI}.service"

echo "== Stopping peripheral services ($HID_REMOTE_UNIT, $HID_AGENT_UNIT) =="
systemctl stop "$HID_REMOTE_UNIT" "$HID_AGENT_UNIT" 2>/dev/null || true
systemctl reset-failed "$HID_REMOTE_UNIT" "$HID_AGENT_UNIT" 2>/dev/null || true

# Self-heal the §6.7.25 unit rename. Before §6.7.25 the daemons were transient
# systemd-run units named hid-remote-<hci>/hid-agent-<hci> (+ an old global
# hid-remote/hid-agent singleton). On a host upgraded in place without a reboot
# those keep running ALONGSIDE the new @ units — two hid_remote.py on one chip
# stomp each other's raw-HCI advertising so the standby wake never lands
# (§6.7.26-followup-2). Stop the leftovers for THIS adapter (per-adapter so a
# sibling's canonical @ daemon is never touched); a no-op once they're gone.
systemctl stop "hid-remote-${ADAPTER_HCI}.service" "hid-agent-${ADAPTER_HCI}.service" \
               hid-remote.service hid-agent.service 2>/dev/null || true
systemctl reset-failed "hid-remote-${ADAPTER_HCI}.service" "hid-agent-${ADAPTER_HCI}.service" \
                       hid-remote.service hid-agent.service 2>/dev/null || true

# ----- Read controller info (for the factory-MAC cache cleanup below) -----
# Every adapter in the fleet is a Broadcom BCM4345C0 — onboard UART on the
# Raspberry Pis (enumerates as Cypress mfr 305) and the Belkin USB dongle
# on the Minisforum (mfr 15). There is therefore no vendor branching: the
# §6.7.13 firmware reset is always correct and is gated only on transport
# (UART vs USB) below. We still read `btmgmt info` once because the
# factory-MAC cache cleanup downstream parses the `addr <MAC>` line from it.
mfr_out=$(timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>&1 || true)
echo "== Adapter $ADAPTER_HCI (Broadcom BCM4345C0) =="

# Detect a sibling-adapter pairing or live peripheral on this host.
# `bluetoothd` is a single process serving every controller, so if any
# sibling adapter has either a fresh start.sh lockfile OR a running
# hid-remote daemon we MUST NOT do `systemctl stop bluetooth` — that
# would yank the daemon out from under the other adapter mid-flight
# AND, for Broadcom adapters where advertising is driven via raw HCI,
# wipe the chip's advertising state so the STB silently loses its link
# (§6.7.22-followup-10: paired hci1 then paired hci2 → bluetoothd
# restart killed hci1's raw-HCI advertising, STB couldn't reconnect
# even though the bond was still on disk).
#
# Two signals trip "active sibling":
#   1. /tmp/ble-remote-pairing-hciN.lock newer than 60s (start.sh
#      currently running for that sibling)
#   2. hid-remote-hciN.service is active (sibling daemon alive)
# (2) is the case we missed before — bonds survive the lockfile's
# 60s window, so once a successful pair is older than that, the
# sibling's lockfile alone won't protect it.
OTHER_RUN_ACTIVE=0
for f in /tmp/ble-remote-pairing-hci*.lock; do
    [[ -f "$f" ]] || continue
    [[ "$f" == "$LOCKFILE" ]] && continue
    other_age=$(( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ))
    if (( other_age < 60 )); then
        OTHER_RUN_ACTIVE=1
        echo "== Concurrent start.sh detected ($(basename "$f"), age ${other_age}s) =="
        echo "  this run will skip the bluetoothd restart"
        break
    fi
done
if (( OTHER_RUN_ACTIVE == 0 )); then
    while IFS= read -r unit; do
        [[ -z "$unit" ]] && continue
        [[ "$unit" == "$HID_REMOTE_UNIT" ]] && continue
        OTHER_RUN_ACTIVE=1
        echo "== Active sibling daemon detected ($unit) =="
        echo "  this run will skip the bluetoothd restart to keep the sibling alive"
        break
    done < <(systemctl list-units --no-legend --type=service --state=active \
                'hid-remote@hci*.service' 2>/dev/null | awk '{print $1}')
fi

# Reset the radio firmware.
#
# This is TWO operations with DIFFERENT blast radii — gate them separately
# (§6.7.26-followup-3, the two-adapter firmware-wedge fix):
#
#   1. `systemctl stop/start bluetooth` — restarts the SHARED bluetoothd, which
#      wipes EVERY adapter's raw-HCI advertising state. Must be skipped when a
#      sibling daemon is active or the sibling's STB silently loses its link
#      (§6.7.22-followup-10). Stays gated on OTHER_RUN_ACTIVE == 0.
#
#   2. btusb unbind/rebind of THIS adapter's own USB interface — ISOLATED to
#      this one dongle. It does not restart bluetoothd and does not touch the
#      sibling's USB device (a different interface), so it is SAFE even with a
#      sibling daemon running. Previously this was skipped together with (1)
#      whenever a sibling was active — which on host3 (hci2's daemon runs
#      permanently) meant a wedged hci1 dongle (btmgmt public-addr → 0x0b,
#      power on → 0x05, raw-adv enable → 0x0C) could NEVER be un-wedged. Every
#      subsequent re-pair then landed the STB in the battery-only trap (§6.7.9)
#      on the still-wedged adapter. The USB reset now runs regardless of
#      OTHER_RUN_ACTIVE so a wedged dongle self-heals on the next start/resume.
#
# UART (Pi onboard) stays gated on no-sibling: those hosts are single-adapter,
# and a UART unbind without the surrounding bluetoothd stop is the less-tested
# path — OTHER_RUN_ACTIVE is always 0 there anyway, so nothing is lost.
echo "== Resetting radio firmware =="
if (( OTHER_RUN_ACTIVE == 0 )); then
    systemctl stop bluetooth 2>/dev/null || true
else
    echo "  sibling daemon active — NOT restarting shared bluetoothd"
    echo "  (an isolated per-USB-device reset will still run if this adapter is USB)"
fi

DEV_LINK="/sys/class/bluetooth/$ADAPTER_HCI/device"
DEV_PATH=""
[[ -L "$DEV_LINK" ]] && DEV_PATH="$(readlink -f "$DEV_LINK")"

UART_DRV="/sys/bus/serial/drivers/hci_uart_bcm"
UART_DEV="serial0-0"
USB_DRV="/sys/bus/usb/drivers/btusb"

if [[ "$DEV_PATH" == *"/usb"* && -d "$USB_DRV" ]]; then
    # USB-attached: find the btusb interface name (X-Y[.Z]:I.J). Resetting it is
    # isolated to THIS dongle, so it runs regardless of OTHER_RUN_ACTIVE.
    hciconfig "$ADAPTER_HCI" down 2>/dev/null || true
    USB_IFACE=""
    cur="$DEV_PATH"
    while [[ "$cur" != "/" && "$cur" != "/sys" ]]; do
        b="$(basename "$cur")"
        if [[ "$b" =~ ^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$ ]]; then
            USB_IFACE="$b"; break
        fi
        cur="$(dirname "$cur")"
    done
    if [[ -n "$USB_IFACE" ]]; then
        echo "  USB transport: btusb unbind/rebind $USB_IFACE (isolated to this dongle)"
        echo "$USB_IFACE" > "$USB_DRV/unbind" 2>/dev/null || true
        sleep 2
        echo "$USB_IFACE" > "$USB_DRV/bind" 2>/dev/null || true
        for _ in $(seq 1 20); do
            hciconfig "$ADAPTER_HCI" >/dev/null 2>&1 && break
            sleep 0.25
        done
        sleep 1
    else
        echo "  could not derive btusb interface for $ADAPTER_HCI ($DEV_PATH) — skipping firmware reset" >&2
    fi
elif [[ -d "$UART_DRV" ]]; then
    if (( OTHER_RUN_ACTIVE == 0 )); then
        echo "  UART transport: hci_uart_bcm unbind/rebind $UART_DEV"
        hciconfig "$ADAPTER_HCI" down 2>/dev/null || true
        echo "$UART_DEV" > "$UART_DRV/unbind" 2>/dev/null || true
        sleep 3
        echo "$UART_DEV" > "$UART_DRV/bind" 2>/dev/null || true
        for _ in $(seq 1 20); do
            hciconfig "$ADAPTER_HCI" >/dev/null 2>&1 && break
            sleep 0.25
        done
        sleep 1
    else
        echo "  UART transport but sibling daemon active — skipping UART reset (shared bluetoothd)"
    fi
else
    echo "  $ADAPTER_HCI: no recognised transport (no btusb, no hci_uart_bcm) — skipping firmware reset" >&2
fi

echo "== Disconnecting and removing every bonded device =="
if (( OTHER_RUN_ACTIVE == 0 )); then
    systemctl start bluetooth
    sleep 2
else
    echo "  skipping systemctl start bluetooth (sibling run owns the daemon)"
fi

# Wait for the kernel to register the controller into MGMT before any
# btmgmt or bluetoothctl call. After a btusb unbind/rebind (USB Broadcom
# dongle on host3 hci1) the MGMT index takes longer to settle than
# the fixed `sleep 2` above — on the Pi's onboard UART chip (hci0) it's
# instant, on USB it can be several seconds.
#
# Two positive signals satisfy us:
#   - `btmgmt info` output contains "current settings" — the resume.sh
#     pattern, works on Broadcom hci0/hci1.
#   - `hciconfig <hci>` succeeds AND prints a BD Address — the fallback,
#     observed to be the actual reliable signal on the Realtek 5.3 dongle
#     (hci2 on host3) where `btmgmt --index 2 info` was returning
#     no usable output even after MGMT was clearly up (manual btmgmt run
#     in another terminal worked fine). We're not interested in which
#     specific MGMT primitive btmgmt is failing on — what we need is to
#     know the chip is reachable.
#
# Bounded at 30s (60 × 0.5s). If both signals stay silent we log the
# actual btmgmt output and CONTINUE — the `timeout 5 ...`
# backstop on the btmgmt block below catches any real wedge. Hard-
# failing here would just turn a chip-vendor-specific quirk into a
# script-wide outage.
echo "== Waiting for MGMT to enumerate $ADAPTER_HCI (controller bring-up) =="
mgmt_ready=0
info_out=""
for i in $(seq 1 60); do
    # Capture stdout AND stderr — some btmgmt builds write the info
    # block to stderr; throwing it away with `2>/dev/null` (the
    # original resume.sh pattern) hid the real output in the Realtek
    # case and the loop spun forever even though MGMT was up.
    info_out=$(timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>&1 || true)
    if echo "$info_out" | grep -qE 'current settings|Primary controller'; then
        mgmt_ready=1
        echo "  MGMT enumerated via btmgmt after $((i * 5 / 10))s"
        break
    fi
    if hciconfig "$ADAPTER_HCI" 2>/dev/null | grep -qE 'BD Address:'; then
        mgmt_ready=1
        echo "  MGMT enumerated via hciconfig fallback after $((i * 5 / 10))s"
        break
    fi
    # Surface what btmgmt is actually saying every 4 iterations (2s).
    # Without this the operator sees the same `+ timeout 5 btmgmt …`
    # xtrace line repeated forever with no clue WHY grep doesn't match.
    if (( i % 4 == 0 )); then
        first_line=$(echo "$info_out" | head -1 | tr -d '\r' | cut -c1-160)
        echo "  iter=$i still waiting; btmgmt said: ${first_line:-(no output)}"
    fi
    sleep 0.5
done
if [[ $mgmt_ready -eq 0 ]]; then
    echo "  WARNING: MGMT enumeration wait exhausted after 30s — continuing anyway" >&2
    echo "  last btmgmt --index $ADAPTER_INDEX info output:" >&2
    echo "$info_out" | sed 's/^/    /' >&2
fi

# Remove bonded peers from THIS adapter only (§6.7.22-followup-12).
# The previous loop ran `bluetoothctl devices Paired` which lists peers
# across EVERY adapter on the host — start.sh on hci2 was nuking
# hci1's STB bond (AA:BB:CC:DD:EE:01), reproducible 2026-05-29 in
# /tmp/ble-start-hci2.log → `removing AA:BB:CC:DD:EE:01` line. That's
# exactly the "second pair breaks the first" symptom the user reported.
#
# Fix: walk the D-Bus tree filtered by `/org/bluez/${ADAPTER_HCI}/dev_*`
# and call Adapter1.RemoveDevice with an explicit adapter object path.
# Each call is unambiguous about which adapter the bond belongs to —
# bluetoothctl `remove <MAC>` is not (it picks a controller implicitly).
adapter_obj="/org/bluez/$ADAPTER_HCI"
for dev_path in $(busctl --no-pager call org.bluez / \
        org.freedesktop.DBus.ObjectManager GetManagedObjects 2>/dev/null \
        | grep -oE "${adapter_obj}/dev_[A-F0-9_]{17}" \
        | sort -u); do
    dev_mac="$(basename "$dev_path" | sed 's/^dev_//;s/_/:/g')"
    echo "  removing $dev_mac from $ADAPTER_HCI"
    timeout 5 busctl --no-pager call org.bluez "$dev_path" \
        org.bluez.Device1 Disconnect >/dev/null 2>&1 || true
    timeout 5 busctl --no-pager call org.bluez "$adapter_obj" \
        org.bluez.Adapter1 RemoveDevice "o" "$dev_path" >/dev/null 2>&1 || true
done

echo "== Wiping BlueZ on-disk cache =="
# Scope the wipe to this adapter's bond dirs (current factory MAC AND
# any prior spoofed MACs under our SPOOF_MAC_PREFIX). The previous
# unconditional "wipe every controller's bonds" was the third leg of
# the multi-adapter trampling problem — when hci1 and hci2 ran
# start.sh in parallel, whichever wiped second nuked the other's
# fresh bond directory along with the controller-level state.
# What we wipe:
#   1. Every prior spoof-MAC dir under SPOOF_MAC_PREFIX that ISN'T
#      currently in use by a sibling adapter on this host. Multi-adapter
#      hosts (host3: hci1 + hci2 both Broadcom) share the spoof
#      prefix, so a blanket wipe of every `…1F:*` dir would also delete
#      the sibling's bond — which is the multi-pair regression we hit
#      2026-05-29: pairing hci2 killed hci1's pairing and vice versa.
#      Solution: before wiping, query every other hciN on the host for
#      its current `addr` and exclude those dirs from the rm.
#   2. The current adapter's factory-MAC dir's cache/ and bond
#      subdirs (Realtek can't accept public-addr spoofing, so its
#      adapter dir IS the factory MAC).
# What we leave alone: every other controller's directory, so a
# concurrent run on the sibling adapter keeps its in-flight state,
# AND every sibling's currently-assigned spoof MAC dir so its bond
# survives this run.

# Discover sibling adapters' current addresses (the dir names that
# represent the OTHER adapters' active bonds).
declare -A SIBLING_MACS=()
for sysdir in /sys/class/bluetooth/hci*; do
    [[ -d "$sysdir" ]] || continue
    other_hci="$(basename "$sysdir")"
    # Skip kernel connection sub-devices like `hci1:64` — same reason
    # as the USED_BYTES loop above (top of script).
    [[ "$other_hci" =~ ^hci[0-9]+$ ]] || continue
    [[ "$other_hci" == "$ADAPTER_HCI" ]] && continue
    other_idx="${other_hci#hci}"
    other_addr=$(timeout 5 btmgmt --index "$other_idx" info 2>&1 \
        | grep -oE 'addr [0-9A-F:]{17}' | head -1 | awk '{print $2}')
    if [[ -n "$other_addr" ]]; then
        SIBLING_MACS["${other_addr^^}"]=1
        echo "  preserving sibling $other_hci bond dir: $other_addr"
    fi
done

# Also preserve via the PERSISTED bindings — not just live btmgmt. A sibling
# that is momentarily wedged out of MGMT (HCI up but `btmgmt --index` empty —
# the §6.7.25-followup wedge) returns no address above, so without this its
# bond dir would be deleted on the next re-pair of THIS adapter: the
# "pairing one removes the other" failure. adapter-hciN.mac is stable on disk,
# so add every OTHER adapter's assigned MAC to the preserve set unconditionally.
# See BLUETOOTH.md §6.7.26-followup.
for macfile in /var/lib/vpt-ble/adapter-hci*.mac; do
    [[ -f "$macfile" ]] || continue
    [[ "$macfile" == "/var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac" ]] && continue
    sib_mac="$(tr -d '[:space:]' < "$macfile" 2>/dev/null || true)"
    if [[ "$sib_mac" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:[0-9A-Fa-f]{2}$ ]]; then
        SIBLING_MACS["${sib_mac^^}"]=1
        echo "  preserving sibling bond dir via persisted binding: $sib_mac"
    fi
done

shopt -s nullglob
for ctrl in /var/lib/bluetooth/${SPOOF_MAC_PREFIX}:*; do
    [[ -d "$ctrl" ]] || continue
    base="$(basename "$ctrl")"
    if [[ -n "${SIBLING_MACS[${base^^}]:-}" ]]; then
        echo "  skipping $ctrl (currently owned by sibling adapter)"
        continue
    fi
    echo "  clearing $ctrl (prior spoof MAC, no sibling owner)"
    rm -rf "$ctrl" 2>/dev/null || true
done
shopt -u nullglob
# Also clean the current adapter's factory-MAC dir if we have one.
# Parsed from the `addr <MAC>` line of the `btmgmt info` read above
# (mfr_out); empty if the chip was wedged when we read it, in which case
# we simply skip this best-effort cleanup.
ADAPTER_FACTORY_MAC=$(echo "$mfr_out" | grep -oE 'addr [0-9A-F:]{17}' | head -1 | awk '{print $2}')
if [[ -n "$ADAPTER_FACTORY_MAC" \
      && -d "/var/lib/bluetooth/$ADAPTER_FACTORY_MAC" \
      && -z "${SIBLING_MACS[${ADAPTER_FACTORY_MAC^^}]:-}" ]]; then
    echo "  clearing /var/lib/bluetooth/$ADAPTER_FACTORY_MAC (this adapter's factory MAC)"
    rm -rf "/var/lib/bluetooth/$ADAPTER_FACTORY_MAC"/cache/* 2>/dev/null || true
    find "/var/lib/bluetooth/$ADAPTER_FACTORY_MAC" -mindepth 1 -maxdepth 1 -type d ! -name cache -exec rm -rf {} + 2>/dev/null || true
fi

echo "== Reapplying adapter settings ($ADAPTER_HCI, LE-only, spoofed MAC, pairable) =="
# BCM4345C0 quirk: btmgmt connectable/advertising and bluetoothctl
# discoverable all jam the Broadcom HCI advertising engine (status 0x0C).
# We still need these MGMT-level flags for bluetoothd to accept incoming
# connections, so we set them here — then override the chip's advertising
# state via raw HCI at the end (disable → set data → enable), which
# always works regardless of MGMT state divergence.
#
# Every btmgmt call is bounded with `timeout 5`:
#   - `timeout 5` prevents a single wedged MGMT round-trip (observed when
#     this script runs from gunicorn vs a login shell) from eating the
#     controller's 60s subprocess budget. 124 exit code is absorbed by
#     `|| true`. Worst case: the chip state diverges and the raw-HCI
#     advertising block at the end of the script paper-overs the MGMT
#     no-ops, which is exactly what the BCM4345C0 quirk comment above
#     already accounts for.
# Note: do NOT add `</dev/null` to btmgmt calls. We tried it during the
# 2026-05-29 multi-adapter session as a defence against gunicorn's
# stdin pipe, but on this btmgmt build (`bluetoothd 5.82`) redirecting
# stdin from /dev/null makes every `btmgmt` invocation produce ZERO
# output and rc=124 (it blocks until killed). The `exec < <(:)` at the
# top of this script already forces fd0 to an empty closed pipe, which
# is the correct fix (§6.7.23-followup); leave stdin inherited here.
# Helper: run a btmgmt command, capture output, log a one-line summary
# when it fails. Without this every `btmgmt … || true` was silently
# swallowing failures — the trace showed `+ true` after each call with
# no indication WHY the chip never came up (observed on the Realtek 5.3
# dongle: every btmgmt call returned non-zero because the chip was DOWN
# at the HCI layer, but the |-true chain made the script look healthy
# while every operation was a no-op).
btmgmt_step() {
    local desc="$1"; shift
    local out rc
    # Capture rc separately — `|| true` would mask the non-zero exit,
    # leaving us with empty output AND rc=0, which printed ✓ even when
    # btmgmt failed silently (observed on the Realtek dongle when the
    # chip was DOWN: every btmgmt power on returned non-zero with empty
    # output, and the trace cheerfully printed `✓ power on` 8 times in
    # a row while nothing was happening).
    out=$(timeout 5 btmgmt --index "$ADAPTER_INDEX" "$@" 2>&1)
    rc=$?
    local first
    first=$(echo "$out" | head -1 | tr -d '\r' | cut -c1-200)
    if [[ $rc -ne 0 ]] \
            || echo "$out" | grep -qiE 'fail|error|status 0x[0-9a-f]+'; then
        echo "  ⚠ $desc — btmgmt $* (rc=$rc): ${first:-(no output)}" >&2
        return 0   # never propagate failure — the post-config state
                   # dump below is what surfaces a broken chip
    fi
    echo "  ✓ $desc"
}

# Force the HCI layer up first. bluetoothd's AutoEnable should bring
# the chip up via MGMT on `systemctl start bluetooth`, but it can race
# (or be disabled in main.conf) — observed on Realtek where the chip
# stayed DOWN through the entire btmgmt block and every command
# silently failed. `hciconfig up` is the lowest-level bring-up
# primitive; if it fails, the chip is unreachable at the kernel level
# (firmware load, USB enum, etc.) and no amount of btmgmt will help.
echo "  -> hciconfig $ADAPTER_HCI up"
if hciconfig_out=$(hciconfig "$ADAPTER_HCI" up 2>&1); then
    echo "  ✓ HCI layer up"
else
    echo "  ⚠ hciconfig $ADAPTER_HCI up FAILED: ${hciconfig_out:-(no output)}" >&2
    echo "  Chip is unreachable at the HCI layer. Diagnose with:" >&2
    echo "    sudo dmesg | grep -i 'hci0\\|BCM4345'  # firmware load / UART bring-up" >&2
    echo "    btmgmt info                            # MGMT index present? (§6.7.12 wedge if absent)" >&2
    echo "  Common fixes:" >&2
    echo "    • UART firmware reload: unbind/rebind serial0-0 on hci_uart_bcm (§6.7.12)" >&2
    echo "    • USB Belkin dongle: physically unplug + replug" >&2
    echo "    • a host reboot re-attaches the onboard radio cleanly" >&2
    # Don't exit — let the rest of the script run so the post-config
    # state dump captures whatever btmgmt thinks of the chip; the
    # operator sees the whole picture, not just the first failure.
fi
sleep 0.5

btmgmt_step "power off"      power off
sleep 1
btmgmt_step "public-addr"    public-addr "$ADAPTER_MAC"
sleep 1
# Explicitly enable LE host support BEFORE attempting `bredr off`. On
# legacy dual-mode chips like the Belkin BCM20702A1, `bredr off` is
# rejected with MGMT status 0x0B (Rejected) — observed 2026-05-29 on
# host3 hci1. The old script relied on `bredr off` to implicitly
# enable LE-only mode; when it failed, `le` never appeared in
# `current_settings`, bluetoothd refused to route LE GATT/SMP traffic,
# and the STB silently couldn't pair even though raw-HCI advertising
# was clearly going out (Status 00). Setting `le on` explicitly
# guarantees LE host support is on regardless of whether bredr off
# succeeds — the chip then operates in dual mode but with LE fully
# functional, which is all we need for the peripheral.
btmgmt_step "le on"          le on
sleep 1
btmgmt_step "bredr off"      bredr off
sleep 1
btmgmt_step "power on"       power on
sleep 1
# After power on, force-up at HCI layer again in case btmgmt power on
# didn't actually flip the chip (it didn't on Realtek — `current settings`
# came back without `powered`). If hciconfig up succeeded, the chip is
# UP regardless of what the MGMT layer thinks, and the connectable/discov
# flags below will land on a real working radio.
hciconfig "$ADAPTER_HCI" up 2>/dev/null || true
sleep 0.5

btmgmt_step "connectable on" connectable on
sleep 0.5
btmgmt_step "bondable on"    bondable on
sleep 0.5
btmgmt_step "discov on"      discov on
sleep 0.5
btmgmt_step "io-cap 3"       io-cap 3

# Final visibility check: dump the post-config state so the operator
# can see at a glance whether `powered` and the spoofed MAC are now set.
echo "== Post-config adapter state =="
hciconfig "$ADAPTER_HCI" 2>&1 | head -3 | sed 's/^/  /'
timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>&1 | grep -E 'addr|current settings' | sed 's/^/  /' || true

# HID_REMOTE_SKIP_ADV=1 makes hid_remote.py skip D-Bus
# RegisterAdvertisement and rely on the raw-HCI advertising block at the
# end of this script. The BCM4345C0 jams its HCI advertising engine on
# MGMT/D-Bus-driven advertising (§6.7.13), so raw HCI is the only path
# that makes it advertise correctly. Unconditional — every adapter is a
# BCM4345C0.
echo "== Launching $HID_AGENT_UNIT + $HID_REMOTE_UNIT (persistent template units) =="
# Persistent template units replace the old transient `systemd-run
# --property=Restart=always` launch. Restart=always is still set (in the
# unit files) for the §6.7.22-followup-11 reason — the daemon can exit
# between here and the STB's first GATT subscription and must self-heal —
# but a persistent unit file is never deleted, so the stop+relaunch every
# re-pair performs is an atomic `systemctl restart` instead of a race that
# storms systemd with "Failed to open /run/systemd/transient/...".
# Per-adapter runtime env goes in the EnvironmentFile the template reads;
# HID_REMOTE_SKIP_ADV=1 keeps the Broadcom raw-HCI advertising path (§6.7.13).

# Self-bootstrap the template units into /etc/systemd/system so a plain code
# deploy needs no separate install step (the install_service.sh path prefixes
# `vpt-`, which wouldn't match the bare `hid-remote@`/`hid-agent@` names the
# scripts and controller use). Idempotent: only rewrites + daemon-reloads when
# the rendered repo copy differs from what's installed. See §6.7.25.
PROJECT_ROOT_DIR="$(cd "$DIR/../../../../.." && pwd)"
_need_reload=0
for _u in hid-remote hid-agent; do
    _src="$DIR/../../../../config/services/linux/${_u}@.service"
    _dst="/etc/systemd/system/${_u}@.service"
    [[ -f "$_src" ]] || continue
    _tmp="$(mktemp)"
    sed "s|%PROJECT_ROOT%|${PROJECT_ROOT_DIR}|g" "$_src" > "$_tmp"
    if ! cmp -s "$_tmp" "$_dst" 2>/dev/null; then
        cp "$_tmp" "$_dst"; _need_reload=1
    fi
    rm -f "$_tmp"
done
[[ $_need_reload -eq 1 ]] && systemctl daemon-reload

mkdir -p /run/vpt-ble 2>/dev/null || true
cat > "/run/vpt-ble/hid-remote-${ADAPTER_HCI}.env" <<EOF
PYTHONUNBUFFERED=1
HID_REMOTE_ADAPTER=${ADAPTER_HCI}
HID_REMOTE_KEYMAP=${DIR}/ble_conf/${BLE_TYPE}.json
HID_REMOTE_SKIP_ADV=1
EOF
systemctl restart "$HID_AGENT_UNIT"
systemctl restart "$HID_REMOTE_UNIT"

sleep 3

# Raw HCI advertising override (§6.7.13).
#
# The BCM4345C0 jams its HCI advertising engine with status 0x0C when
# MGMT-level connectable/discov on is used; the raw-HCI sequence below
# (disable → set data → set scan rsp → set params → enable) bypasses that
# quirk and is the only way to make the chip advertise correctly.
# Unconditional — every adapter in the fleet is a BCM4345C0.
echo "== Enabling advertising via raw HCI (BCM4345C0, §6.7.13) =="
# 1. Disable (may return 0C if not active — that's fine)
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 00 >/dev/null 2>&1
# §6.7.31: fresh pair — the accept list from the previous bond must not
# block the new STB (policy is 0x00 below, but keep the list clean).
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0010 >/dev/null 2>&1
sleep 0.2

# 2. Advertising data (22 bytes):
#    Flags(3) + 16-bit UUIDs HID+Battery(6) + Appearance(4)
#    + ManufacturerData UEI 0x0093(6) + TxPower(3)
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0008 \
  16 02 01 06 05 03 12 18 0F 18 03 19 80 01 05 FF 93 00 00 80 02 0A 00 \
  00 00 00 00 00 00 00 00 00 >/dev/null 2>&1

# 3. Scan response: Complete Local Name "RemoteUnit"
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0009 \
  0C 0B 09 52 65 6D 6F 74 65 55 6E 69 74 \
  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 >/dev/null 2>&1

# 4. Advertising parameters: ADV_IND (connectable undirected), 20-40ms
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0006 \
  20 00 40 00 00 00 00 00 00 00 00 00 00 07 00 >/dev/null 2>&1

# 5. Enable
ADV_RAW=$(hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 01 2>/dev/null)
ADV_STATUS=$(echo "$ADV_RAW" | grep -v "^[<>]" | tail -1 | awk '{print $NF}')
if [[ "$ADV_STATUS" != "00" ]]; then
    echo "ERROR: LE Set Advertise Enable failed (HCI status 0x$ADV_STATUS)." >&2
    echo "Adapter $ADAPTER_HCI did not accept raw HCI advertising. A host reboot or a different adapter may be needed (try ADAPTER_HCI=hci1)." >&2
    exit 3
fi

echo
echo "== State after reset =="
hciconfig "$ADAPTER_HCI" | head -3
echo
timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>/dev/null | grep -E 'addr|current settings' || true
echo
echo "Paired:    $(bluetoothctl devices Paired | wc -l)"
echo "Connected: $(bluetoothctl devices Connected | wc -l)"
echo
echo "Logs:  sudo journalctl -fu $HID_REMOTE_UNIT"
echo "Now forget the remote on the STB and start a new pairing flow."
