#!/usr/bin/env bash
# Non-destructive resume of the BLE HID remote peripheral.
#
# Reapplies the MAC spoof, LE-only + pairable adapter settings, and
# relaunches hid-agent + hid-remote as transient systemd units — WITHOUT
# wiping existing bonds.
#
# Usage:  sudo ~/ble-remote/resume.sh
#
# Adapter selection (ADAPTER_HCI env, default hci0):
#   - Pi (host1, host3):   ADAPTER_HCI=hci0   (onboard BCM4345C0, UART)
#   - Minisforum (host3) Belkin dongle:   ADAPTER_HCI=hci1   (Broadcom, USB)
# Stuck-state recovery auto-detects UART vs USB transport from
# /sys/class/bluetooth/$ADAPTER_HCI/device.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"

ADAPTER_HCI="${ADAPTER_HCI:-hci0}"
# Derive MGMT numeric index from the hciN string. The old code defaulted
# to 0 unconditionally, which meant resume.sh always pointed at hci0
# even when ADAPTER_HCI=hci2 — every `btmgmt --index $ADAPTER_INDEX`
# call hit the wrong adapter. start.sh has always derived it correctly;
# this brings resume.sh in line (required for the multi-instance
# vpt-ble-remote@hciN.service template, §6.7.22-followup-6).
ADAPTER_INDEX="${ADAPTER_HCI#hci}"
BLE_TYPE="${BLE_TYPE:-arris}"

# Mirror all stdout+stderr to a per-adapter file so the run is tailable in
# real time even when this script is launched via subprocess.run with
# capture_output=True (which buffers output until exit, hiding progress).
# Per-adapter naming because multi-device hosts can run several resume.sh
# instances in parallel (one per BLE controller); a shared file would
# interleave them illegibly. Tail with: `tail -f /tmp/ble-resume-hciN.log`
exec > >(tee -a "/tmp/ble-resume-${ADAPTER_HCI}.log") 2>&1
# Force our own stdin to an empty, already-closed pipe — NEVER /dev/null.
# On bluetoothd 5.82 (Debian 13) every `btmgmt` call WEDGES (rc=124) when its
# stdin is /dev/null but returns immediately when it's a pipe. resume.sh is
# launched by the boot unit ble-remote@.service (StandardInput=null = /dev/null)
# and by Flask's Resume button (gunicorn stdin = /dev/null) — so without this
# override every btmgmt here (MAC spoof, le on, power on) silently timed out,
# the bond never loaded, and the frontend showed "No Bluetooth pairing found".
# This was the real cause of "can't resume on multi-adapter hosts", NOT the
# Cccs/CCCD persistence. Do NOT change to `< /dev/null`. See BLUETOOTH.md §6.7.23.
exec < <(:)
echo "===== resume.sh begin $(date -Is) (pid=$$ adapter=${ADAPTER_HCI}) ====="

SPOOF_MAC_PREFIX="20:21:41:00:1F"

# Auto-detect: find the most recently modified adapter directory that
# matches our spoof prefix AND contains a bonded device. This is the
# MAC that start.sh picked for the last successful pair.  Falls back
# to the newest matching adapter dir even without a bond (handles
# "start.sh ran but STB hasn't paired yet").
if [[ -z "${ADAPTER_MAC:-}" ]]; then
    ADAPTER_MAC=""
    # Pass 0 (preferred): the hci -> MAC binding start.sh persisted for THIS
    # adapter. Deterministic across reboot and immune to the multi-adapter
    # collision where hci1 and hci2 share the ${SPOOF_MAC_PREFIX}:* prefix and
    # the dir-glob passes below let one adapter pick the other's bond. See
    # BLUETOOTH.md §6.7.23-followup.
    bind_file="/var/lib/vpt-ble/adapter-${ADAPTER_HCI}.mac"
    if [[ -f "$bind_file" ]]; then
        cand="$(tr -d '[:space:]' < "$bind_file" 2>/dev/null || true)"
        if [[ "$cand" =~ ^${SPOOF_MAC_PREFIX//:/\\:}:[0-9A-Fa-f]{2}$ ]]; then
            # Trust the persisted binding ONLY if its adapter dir actually holds a
            # bond. A stale/premature bind file strands the real bond otherwise:
            # start.sh persists the binding EARLY (line ~160) from an auto-picked
            # byte, but its 60s controller timeout can kill the run before the pair
            # completes — leaving adapter-hciN.mac pointing at a bondless MAC (the
            # lowest free byte, typically 1F:01) while the good bond sits untouched
            # under a different 1F:xx dir. Blindly spoofing the bind-file MAC then
            # reports "no bonded peer" forever ("No Bluetooth pairing found" in the
            # UI) even though the bond is intact. When the bind-file MAC has no
            # bond, fall through to the Pass-1 scan below, which finds the dir that
            # actually contains a bond. See BLUETOOTH.md §6.7.26-followup-4.
            if ls "/var/lib/bluetooth/$cand/" 2>/dev/null | grep -qE '^[0-9A-F]{2}:'; then
                ADAPTER_MAC="$cand"
                echo "== Using persisted adapter binding: ${ADAPTER_HCI} -> $ADAPTER_MAC =="
            else
                echo "== Ignoring persisted binding ${ADAPTER_HCI} -> $cand: no bond under that MAC. Scanning for the real bond dir. ==" >&2
            fi
        fi
    fi
    # First pass (fallback): adapter dir with a bond subdirectory
    if [[ -z "$ADAPTER_MAC" ]]; then
        for d in $(ls -td /var/lib/bluetooth/${SPOOF_MAC_PREFIX}:* 2>/dev/null); do
            if ls "$d" 2>/dev/null | grep -qE '^[0-9A-F]{2}:'; then
                ADAPTER_MAC="$(basename "$d")"
                break
            fi
        done
    fi
    # Second pass (fallback): newest adapter dir (no bond yet)
    if [[ -z "$ADAPTER_MAC" ]]; then
        newest=$(ls -td /var/lib/bluetooth/${SPOOF_MAC_PREFIX}:* 2>/dev/null | head -1)
        if [[ -n "$newest" ]]; then
            ADAPTER_MAC="$(basename "$newest")"
        fi
    fi
    if [[ -z "$ADAPTER_MAC" ]]; then
        echo "ERROR: no adapter directory matching $SPOOF_MAC_PREFIX:* in /var/lib/bluetooth/" >&2
        echo "Run start.sh first to create one." >&2
        exit 2
    fi
    echo "== Auto-detected adapter MAC: $ADAPTER_MAC =="
fi

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo)." >&2
    exit 1
fi

# Wait for the bare HCI device node first (it appears within ~1s).
for _ in $(seq 1 40); do
    hciconfig "$ADAPTER_HCI" >/dev/null 2>&1 && break
    sleep 0.25
done
if ! hciconfig "$ADAPTER_HCI" >/dev/null 2>&1; then
    echo "$ADAPTER_HCI did not appear within 10s, aborting" >&2
    exit 1
fi

# Then — crucially — wait for the kernel to register the controller into
# the MGMT subsystem (`btmgmt info` showing it). The bare hciX node
# appears almost immediately, but the BCM4345C0 takes much longer to
# finish firmware load + hci_register_dev. resume.sh runs ~5s after boot
# (ordered only After=bluetooth.service), so a plain hciconfig wait
# returns while MGMT is still absent — NOT because the radio is wedged
# but because it isn't up yet. Acting then (UART unbind/rebind) races the
# kernel's own in-progress bring-up: that is exactly the "done too
# hastily" failure §6.7.12 warns about — firmware reloads fine but the
# controller never re-registers into MGMT and the adapter is left stuck
# on its factory MAC, bond unloaded, frontend "No Bluetooth pairing
# found". Wait up to 120s; the common cold-boot path resolves here with
# no firmware reload at all.
# See start.sh for the full rationale on positive-signal selection and
# the diagnostic logging. Same pattern here: accept either btmgmt's
# `current settings`/`Primary controller` line OR hciconfig's BD Address
# as proof the controller is reachable; log every 4 iterations so a
# stuck loop names what btmgmt is actually returning; continue on
# exhaustion rather than hard-fail — the bounded btmgmt calls downstream
# are already the real wedge defence.
echo "== Waiting for MGMT to enumerate $ADAPTER_HCI (controller bring-up) =="
mgmt_ready=0
info_out=""
for i in $(seq 1 60); do
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

# Per-adapter daemon unit names — multi-instance support (mirrors start.sh).
# Persistent template units (hid-remote@/hid-agent@), replacing the old
# transient hid-remote-${ADAPTER_HCI}.service. See BLUETOOTH.md §6.7.25.
HID_REMOTE_UNIT="hid-remote@${ADAPTER_HCI}.service"
HID_AGENT_UNIT="hid-agent@${ADAPTER_HCI}.service"

# Detect a sibling adapter's active pairing run or live peripheral, so the
# firmware-reset paths below never restart the SHARED bluetoothd out from under
# it (§6.7.22-followup-10 / §6.7.26-followup-3). An ISOLATED per-USB-device
# reset is still allowed when a sibling is active — only the bluetoothd restart
# is gated. Mirrors start.sh's OTHER_RUN_ACTIVE detection.
OTHER_RUN_ACTIVE=0
for f in /tmp/ble-remote-pairing-hci*.lock; do
    [[ -f "$f" ]] || continue
    [[ "$f" == "/tmp/ble-remote-pairing-${ADAPTER_HCI}.lock" ]] && continue
    other_age=$(( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ))
    if (( other_age < 60 )); then
        OTHER_RUN_ACTIVE=1
        echo "== Concurrent start.sh detected ($(basename "$f"), age ${other_age}s) — bluetoothd restart will be skipped =="
        break
    fi
done
if (( OTHER_RUN_ACTIVE == 0 )); then
    while IFS= read -r unit; do
        [[ -z "$unit" ]] && continue
        [[ "$unit" == "$HID_REMOTE_UNIT" ]] && continue
        OTHER_RUN_ACTIVE=1
        echo "== Active sibling daemon detected ($unit) — bluetoothd restart will be skipped =="
        break
    done < <(systemctl list-units --no-legend --type=service --state=active \
                'hid-remote@hci*.service' 2>/dev/null | awk '{print $1}')
fi

# Isolated per-USB-device firmware reset: unbind+rebind ONLY this dongle's btusb
# interface. Does NOT restart the shared bluetoothd and does NOT touch any
# sibling adapter (a different USB interface), so it is safe to call even while a
# sibling hid-remote daemon is serving another STB. No-op (returns 1) for
# non-USB transports — UART hosts are single-adapter and reset via the Variant A
# block below. See BLUETOOTH.md §6.7.26-followup-3.
isolated_usb_reset() {
    local dev_link dev_path usb_drv iface cur b
    dev_link="/sys/class/bluetooth/$ADAPTER_HCI/device"
    [[ -L "$dev_link" ]] || { echo "  isolated_usb_reset: no device link for $ADAPTER_HCI"; return 1; }
    dev_path="$(readlink -f "$dev_link")"
    usb_drv="/sys/bus/usb/drivers/btusb"
    [[ "$dev_path" == *"/usb"* && -d "$usb_drv" ]] \
        || { echo "  isolated_usb_reset: $ADAPTER_HCI is not USB — skipping"; return 1; }
    iface=""
    cur="$dev_path"
    while [[ "$cur" != "/" && "$cur" != "/sys" ]]; do
        b="$(basename "$cur")"
        if [[ "$b" =~ ^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$ ]]; then iface="$b"; break; fi
        cur="$(dirname "$cur")"
    done
    [[ -n "$iface" ]] || { echo "  isolated_usb_reset: could not derive btusb iface ($dev_path)"; return 1; }
    echo "  isolated btusb reset: unbind/rebind $iface (this dongle only, bluetoothd untouched)"
    hciconfig "$ADAPTER_HCI" down 2>/dev/null || true
    echo "$iface" > "$usb_drv/unbind" 2>/dev/null || true
    sleep 2
    echo "$iface" > "$usb_drv/bind" 2>/dev/null || true
    for _ in $(seq 1 20); do hciconfig "$ADAPTER_HCI" >/dev/null 2>&1 && break; sleep 0.25; done
    sleep 1
    return 0
}

# One bounded pass of (power off → spoof MAC → le on → bredr off → power on),
# returning 0 as soon as hciconfig reports the spoofed MAC. Factored out so the
# post-loop wedge recovery below can re-run it after an isolated reset.
apply_spoof_mac() {
    local iters="$1" _
    for _ in $(seq 1 "$iters"); do
        timeout 5 btmgmt --index "$ADAPTER_INDEX" power off                  >/dev/null 2>&1 || true
        sleep 1
        timeout 5 btmgmt --index "$ADAPTER_INDEX" public-addr "$ADAPTER_MAC" >/dev/null 2>&1 || true
        sleep 1
        timeout 5 btmgmt --index "$ADAPTER_INDEX" le on                      >/dev/null 2>&1 || true
        sleep 1
        timeout 5 btmgmt --index "$ADAPTER_INDEX" bredr off                  >/dev/null 2>&1 || true
        sleep 1
        timeout 5 btmgmt --index "$ADAPTER_INDEX" power on                   >/dev/null 2>&1 || true
        sleep 1
        if hciconfig "$ADAPTER_HCI" 2>/dev/null | grep -qi "BD Address: ${ADAPTER_MAC}"; then
            return 0
        fi
        sleep 2
    done
    return 1
}

echo "== Stopping any running peripheral units ($HID_REMOTE_UNIT, $HID_AGENT_UNIT) =="
systemctl stop "$HID_REMOTE_UNIT" "$HID_AGENT_UNIT" 2>/dev/null || true
systemctl reset-failed "$HID_REMOTE_UNIT" "$HID_AGENT_UNIT" 2>/dev/null || true

# Self-heal the §6.7.25 unit rename (mirrors start.sh): stop pre-rename leftover
# daemons for THIS adapter (old transient hid-remote-<hci>/hid-agent-<hci> + the
# old global hid-remote/hid-agent singletons). On an in-place upgrade without a
# reboot those run ALONGSIDE the new @ units — two hid_remote.py on one chip
# stomp each other's raw-HCI advertising so the standby wake never lands
# (§6.7.26-followup-2). Per-adapter so a sibling's canonical @ daemon is safe.
systemctl stop "hid-remote-${ADAPTER_HCI}.service" "hid-agent-${ADAPTER_HCI}.service" \
               hid-remote.service hid-agent.service 2>/dev/null || true
systemctl reset-failed "hid-remote-${ADAPTER_HCI}.service" "hid-agent-${ADAPTER_HCI}.service" \
                       hid-remote.service hid-agent.service 2>/dev/null || true

echo "== Detecting stuck radio state =="
STUCK=0
STUCK_REASON=""

# Every adapter in the fleet is a Broadcom BCM4345C0 — onboard UART on the
# Raspberry Pis (host1/host3, enumerates as Cypress mfr 305) and the
# Belkin USB dongle on the Minisforum (mfr 15). So there is no vendor gate:
# the §6.7.12 firmware reset is always the right recovery, and we pick UART
# vs USB purely by transport below. (We used to gate this on mfr==15, which
# silently excluded the Cypress-branded onboard chip — the exact reason a
# reboot left it wedged on its factory MAC with "No Bluetooth pairing
# found"; and during the wedge btmgmt returns nothing so the mfr was
# unreadable anyway.)

# Variant A — MGMT layer lost the controller entirely. If `btmgmt info`
# shows no controller while hciconfig still has the HCI up, the radio is
# genuinely wedged (HCI up, MGMT permanently detached) — bluetoothd never
# creates /org/bluez/hciX, so GattManager1 is absent (hid_remote.py exits +
# Restart=always loops) and every `btmgmt public-addr/power` below silently
# no-ops. A UART/USB firmware reload is the only recovery.
if ! timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>/dev/null | grep -qE 'current settings'; then
    STUCK=1
    STUCK_REASON="MGMT index $ADAPTER_INDEX absent (controller wedged — HCI up, MGMT detached)"
fi

# Variant B — advertising enable/disable returns 0x0C (Command Disallowed).
# This is NO LONGER treated as "stuck". On the Belkin BCM20702 dongles a 0x0C
# here just means advertising isn't configured yet (benign) — the raw-HCI
# advertising block at the END of this script programs the params and enables
# it. The old behaviour (set STUCK=1 → btusb unbind/rebind) was a FALSE-
# POSITIVE recovery that repeatedly knocked the dongle out of MGMT (HCI up but
# `btmgmt --index` empty → daemon can't bind it, falls back to the wrong hci,
# bond-wipe of a "wedged" sibling, etc.). We now ONLY rebind for Variant A
# (MGMT genuinely absent — the real wedge). A genuine advertising-engine jam
# still surfaces: the raw-HCI enable at the end fails and the script exits 3.
# See BLUETOOTH.md §6.7.26-followup.
if [[ $STUCK -eq 0 ]]; then
    ADV_DIS=$(hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 00 2>/dev/null \
        | grep -v "^[<>]" | tail -1 | awk '{print $NF}')
    ADV_EN=$(hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 01 2>/dev/null \
        | grep -v "^[<>]" | tail -1 | awk '{print $NF}')
    if [[ "$ADV_DIS" == "0C" && "$ADV_EN" == "0C" ]]; then
        echo "  note: advertising enable/disable returned 0x0C (benign on Belkin —"
        echo "        raw-HCI block below will configure + enable it; NOT rebinding)"
    fi
fi

if [[ $STUCK -eq 1 ]]; then
    echo "  Broadcom radio stuck — $STUCK_REASON"
    if (( OTHER_RUN_ACTIVE == 0 )); then
        systemctl stop bluetooth 2>/dev/null || true
    else
        echo "  sibling daemon active — NOT restarting shared bluetoothd (isolated reset only)"
    fi
    hciconfig "$ADAPTER_HCI" down 2>/dev/null || true

    # Transport-aware firmware reset (mirrors start.sh):
    #   - Pi onboard BCM4345C0 → UART (hci_uart_bcm) unbind/rebind
    #   - USB BT dongle (Belkin Broadcom, etc.) → btusb unbind/rebind
    DEV_LINK="/sys/class/bluetooth/$ADAPTER_HCI/device"
    DEV_PATH=""
    [[ -L "$DEV_LINK" ]] && DEV_PATH="$(readlink -f "$DEV_LINK")"

    UART_DRV="/sys/bus/serial/drivers/hci_uart_bcm"
    UART_DEV="serial0-0"
    USB_DRV="/sys/bus/usb/drivers/btusb"

    if [[ "$DEV_PATH" == *"/usb"* && -d "$USB_DRV" ]]; then
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
            echo "  USB transport: btusb unbind/rebind $USB_IFACE"
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
        echo "  UART transport: hci_uart_bcm unbind/rebind $UART_DEV"
        echo "$UART_DEV" > "$UART_DRV/unbind" 2>/dev/null || true
        sleep 3
        echo "$UART_DEV" > "$UART_DRV/bind" 2>/dev/null || true
        for _ in $(seq 1 20); do
            hciconfig "$ADAPTER_HCI" >/dev/null 2>&1 && break
            sleep 0.25
        done
        sleep 1
    else
        echo "  $ADAPTER_HCI: no recognised transport — skipping firmware reset" >&2
    fi

    if (( OTHER_RUN_ACTIVE == 0 )); then
        systemctl start bluetooth
        sleep 2
    fi
fi

# Apply the spoofed MAC by VERIFICATION, not by timing. Post-firmware-
# reload MGMT re-enumeration on the BCM4345C0 is long and wildly
# variable (measured 70s to >240s across host3 reboots) — no fixed wait
# can bound it, and a fire-and-forget `btmgmt public-addr` silently
# no-ops while MGMT is still absent, leaving the adapter on its factory
# MAC, the bond dir unloaded, and the frontend showing "No Bluetooth
# pairing found". So loop the (power off → public-addr → bredr off →
# power on) sequence and re-attempt until `hciconfig` actually reports
# the spoofed address. This is deterministic regardless of how long
# MGMT takes: every no-op iteration is harmless, and the first iteration
# after MGMT comes up makes the spoof stick and the verify pass. Bounded
# at ~7 min (worst observed re-enum + margin); on a clean run where MGMT
# is already up it succeeds on the first iteration in a few seconds.
# Apply by VERIFICATION, not timing (see apply_spoof_mac + the long rationale
# that used to live here): post-firmware-reload MGMT re-enumeration on the
# BCM4345C0 is long and variable (70s–>240s), so loop power off → public-addr →
# le on → bredr off → power on until hciconfig actually reports the spoofed
# address. Every no-op iteration is harmless; the first after MGMT is up makes
# the spoof stick. Bounded ~7min; a clean run succeeds in seconds.
echo "== Applying spoofed MAC $ADAPTER_MAC (retry until $ADAPTER_HCI reports it) =="
spoof_applied=0
if apply_spoof_mac 70; then
    spoof_applied=1
    echo "  spoofed MAC confirmed on $ADAPTER_HCI"
else
    # The MAC never stuck across the full retry window. On the BCM4345C0 USB
    # dongle this is the firmware-WEDGE signature: every btmgmt no-ops because
    # the MGMT/firmware engine is jammed (public-addr → 0x0b Rejected, power on
    # → 0x05 Authentication Failed, raw-adv enable → 0x0C; observed on
    # host3 hci1, BLUETOOTH.md §6.7.26-followup-3). The adapter is up at
    # the HCI layer but cannot be configured — and if the STB connects to it in
    # this state it lands in the battery-only trap (§6.7.9).
    #
    # Escalate to an ISOLATED per-USB-device reset (safe even with the sibling
    # hci2 daemon running — it never restarts the shared bluetoothd) and retry
    # ONCE. This is what lets Resume recover a wedge NON-DESTRUCTIVELY, instead
    # of leaving the operator to hit Start Pairing — which wipes the good bond
    # onto the still-wedged adapter and is what actually creates the persistent
    # battery-only state.
    echo "  ⚠ spoofed MAC never applied — $ADAPTER_HCI appears firmware-wedged" >&2
    if isolated_usb_reset; then
        echo "  retrying MAC apply after isolated reset..."
        if apply_spoof_mac 30; then
            spoof_applied=1
            echo "  spoofed MAC confirmed after isolated reset"
        fi
    fi
    if [[ $spoof_applied -eq 0 ]]; then
        echo "  ERROR: $ADAPTER_HCI still will not accept $ADAPTER_MAC after a firmware reset." >&2
        echo "  The dongle is hard-wedged — physically replug it or reboot the host." >&2
        echo "  Do NOT click Start Pairing: it will wipe the good bond onto the wedged" >&2
        echo "  adapter and burn the MAC battery-only. See BLUETOOTH.md §6.7.26-followup-3." >&2
    fi
fi

echo "== Reapplying remaining adapter flags (pairable, discoverable) =="
timeout 5 btmgmt --index "$ADAPTER_INDEX" connectable on || true
sleep 0.5
# §6.7.29: only open the pairing window when this adapter has no bond yet.
# This block used to force bondable+discov on unconditionally on every
# resume; combined with the NoInputNoOutput auto-accept agent that meant
# ANY device could silently bond at ANY time. That is exactly how the
# 2026-07-24 host2 duplicate-bond incident happened: the STB
# re-paired itself mid-Resume (no start.sh had run for two days), leaving
# a stale battery-only bond next to the fresh one, and wake-on-press
# chased the wrong MAC. A bonded reconnect (LTK re-encryption + directed
# adv) needs neither bondable nor discoverable, so once a bond exists we
# CLOSE the window; only start.sh (a deliberate fresh pair) opens it.
# Consequence to know: after an STB-side factory reset the STB can no
# longer silently re-pair on its own — the operator must click Pair
# (start.sh), which is the clean flow anyway (wipes the old bond first).
BOND_COUNT=0
for _bd in "/var/lib/bluetooth/$ADAPTER_MAC"/*:*:*:*:*:*; do
    [[ -d "$_bd" ]] && BOND_COUNT=$((BOND_COUNT + 1))
done
if [[ "$BOND_COUNT" -gt 1 ]]; then
    echo "  ⚠ $BOND_COUNT bonds under $ADAPTER_MAC — one is stale (§6.7.20/§6.7.29)." >&2
    echo "  ⚠ Remove the non-HID one: sudo bluetoothctl → select $ADAPTER_MAC → remove <stale-mac>" >&2
    ls "/var/lib/bluetooth/$ADAPTER_MAC" 2>/dev/null | grep -E '^([0-9A-F]{2}:){5}[0-9A-F]{2}$' | sed 's/^/      /' >&2 || true
fi
if [[ "$BOND_COUNT" -gt 0 ]]; then
    echo "  bond present ($BOND_COUNT peer) — closing pairing window (bondable/discov off, §6.7.29)"
    timeout 5 btmgmt --index "$ADAPTER_INDEX" bondable off || true
    sleep 0.5
    timeout 5 btmgmt --index "$ADAPTER_INDEX" discov off   || true
else
    echo "  no bond yet — leaving pairing window open (bondable/discov on)"
    timeout 5 btmgmt --index "$ADAPTER_INDEX" bondable on  || true
    sleep 0.5
    timeout 5 btmgmt --index "$ADAPTER_INDEX" discov on    || true
fi
sleep 0.5
timeout 5 btmgmt --index "$ADAPTER_INDEX" io-cap 3       || true

# The BCM4345C0 jams its HCI advertising engine on D-Bus
# RegisterAdvertisement (§6.7.13), so hid_remote.py must skip it and we
# drive advertising via raw HCI below. Every adapter in the fleet is a
# BCM4345C0, so this is unconditional.
echo "== Launching $HID_AGENT_UNIT + $HID_REMOTE_UNIT (persistent template units) =="
# Persistent template units replace the old transient `systemd-run` launch
# so the stop+relaunch is an atomic `systemctl restart`, not a transient-
# unit restart storm (§6.7.25). Per-adapter env (incl. HID_REMOTE_SKIP_ADV=1
# for the Broadcom raw-HCI advertising path) goes in the EnvironmentFile the
# template reads.

# Self-bootstrap the template units into /etc/systemd/system (mirrors
# start.sh) so a plain code deploy needs no separate install step. Idempotent.
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

# Raw HCI advertising override — the BCM4345C0 jams MGMT/D-Bus-driven
# advertising (§6.7.13), so we bypass MGMT and program the chip directly.
# Unconditional: every adapter in the fleet is a BCM4345C0.
echo "== Enabling advertising via raw HCI (BCM4345C0, §6.7.13) =="
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 00 >/dev/null 2>&1
sleep 0.2

hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0008 \
  16 02 01 06 05 03 12 18 0F 18 03 19 80 01 05 FF 93 00 00 80 02 0A 00 \
  00 00 00 00 00 00 00 00 00 >/dev/null 2>&1

hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0009 \
  0C 0B 09 52 65 6D 6F 74 65 55 6E 69 74 \
  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 >/dev/null 2>&1

# §6.7.31: with a bond, only the bonded STB may CONNECT to this advert.
# Load the controller's LE filter accept list with every bonded peer
# (public addresses, little-endian) while advertising is disabled, then
# advertise with filter policy 0x02 (scan from any, connect from list only).
# No bond (fresh pair pending) -> policy 0x00, list cleared.
ADV_FILTER_POLICY=00
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0010 >/dev/null 2>&1      # LE Clear Filter Accept List
if [[ "${BOND_COUNT:-0}" -gt 0 ]]; then
    for _bd in "/var/lib/bluetooth/$ADAPTER_MAC"/*:*:*:*:*:*; do
        [[ -d "$_bd" ]] || continue
        _mac="$(basename "$_bd")"
        _le="$(echo "$_mac" | awk -F: '{printf "%s %s %s %s %s %s", $6,$5,$4,$3,$2,$1}')"
        # shellcheck disable=SC2086
        if hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0011 00 $_le 2>/dev/null | grep -v '^[<>]' | tail -1 | grep -q ' 00 *$'; then
            echo "  accept list += $_mac"
            ADV_FILTER_POLICY=02
        else
            echo "  ! accept list add $_mac FAILED — advert stays open" >&2
        fi
    done
fi
echo "  advertising filter policy: 0x$ADV_FILTER_POLICY ($([[ "$ADV_FILTER_POLICY" == 02 ]] && echo 'connect from bonded STB only' || echo 'open — no bond'))"
hcitool -i "$ADAPTER_HCI" cmd 0x08 0x0006 \
  20 00 40 00 00 00 00 00 00 00 00 00 00 07 $ADV_FILTER_POLICY >/dev/null 2>&1

hcitool -i "$ADAPTER_HCI" cmd 0x08 0x000a 01 >/dev/null 2>&1

echo
echo "== State after resume =="
hciconfig "$ADAPTER_HCI" | head -3
timeout 5 btmgmt --index "$ADAPTER_INDEX" info 2>/dev/null | grep -E 'addr|current settings' || true
echo "Bonds under $ADAPTER_MAC:"
ls -1 "/var/lib/bluetooth/$ADAPTER_MAC/" 2>/dev/null | grep -E '^[0-9A-F]{2}:' || echo "  (none)"
echo
echo "Logs:  sudo journalctl -fu $HID_REMOTE_UNIT"
