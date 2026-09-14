#!/usr/bin/env bash
set -euo pipefail

# host_golden_sysprep.sh — strip machine-specific identity from a backend_host
# box (minisforum/Debian) BEFORE its SSD is imaged as a "golden" source for
# cloning to other units.
#
# Run this LOCALLY on the source host as root, once, right before you pull
# the SSD image. After it runs, power the box off and image the disk — do
# NOT reboot it back into service on this identity (machine-id/SSH host keys
# are gone; that's the point).
#
# What it does:
#   - stops bluetooth.service + hid-remote@*/hid-agent@*/ble-remote@* units
#   - wipes /var/lib/bluetooth (bonds are keyed to THIS box's adapter MACs —
#     meaningless, actively misleading, on a clone with different dongles)
#   - deletes /etc/ssh/ssh_host_* (every clone sharing one host key is a
#     real security problem, not just tidiness)
#   - empties /etc/machine-id (systemd/dbus regenerate on next boot)
#   - clears apt cache, logs, tmp, shell history
#   - resets hostname/hosts to a placeholder
#
# What it deliberately does NOT do:
#   - does NOT rename the LVM volume group (root fs is on LVM — the VG name
#     is likely referenced in fstab/crypttab/grub.cfg/initramfs; renaming it
#     wrong breaks boot). See --rename-vg-warning for details instead.
#   - does NOT touch LVM/PV UUIDs (fine for standalone boxes; only matters if
#     two clones' disks are ever attached to one running kernel at once).
#
# Usage:
#   sudo bash host_golden_sysprep.sh --check     # report only, changes nothing
#   sudo bash host_golden_sysprep.sh --yes        # actually run it
#
# Pair with: scripts/host_postclone_configure.sh (run on each clone after imaging).

log() { echo "[sysprep] $*"; }
warn() { echo "[sysprep] WARNING: $*" >&2; }

if [[ "${1:-}" == "--rename-vg-warning" ]]; then
  cat <<'EOF'
VG rename is NOT handled by this script. If you want to fix the leftover
"host3--vg" naming, do it as its own careful, reviewed change:
  1. grep -rn "<old-vg-name>" /etc/fstab /etc/crypttab /boot/grub/grub.cfg
  2. vgrename <old-vg-name> <new-vg-name>
  3. update every reference found in step 1 to the new name
  4. update-initramfs -u -k all
  5. update-grub
  6. reboot and confirm it comes up BEFORE touching anything else
Skip this entirely unless someone is going to sit at the console for the
reboot in step 6.
EOF
  exit 0
fi

CHECK_ONLY=0
CONFIRM=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --yes) CONFIRM=1 ;;
    -h|--help) sed -n '3,33p' "$0"; exit 0 ;;
    *) echo "[sysprep] unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[sysprep] must run as root (sudo)" >&2
  exit 1
fi

log "host: $(hostname)   date: $(date)"

# --- Pre-flight readiness checks (informational — this script only strips
# identity, it does NOT verify BLE/IR are functionally healthy) ---
BT_ADAPTERS=$(ls /sys/class/bluetooth 2>/dev/null | grep -cE '^hci[0-9]+$' || true)
log "Bluetooth adapters present: ${BT_ADAPTERS:-0}"
if command -v lsusb >/dev/null; then
  BELKIN_COUNT=$(lsusb | grep -ic belkin || true)
  log "Belkin USB dongles seen by lsusb: ${BELKIN_COUNT:-0}"
fi
systemctl list-units --all --no-pager --no-legend 'hid-remote*' 'hid-agent*' 'ble-remote*' 2>/dev/null | sed 's/^/[sysprep]   unit: /' || true

cat <<'EOF'

[sysprep] Before proceeding, confirm OUTSIDE this script:
[sysprep]   - all expected Bluetooth dongles are present (lsusb) and none wedged
[sysprep]   - hid_remote.py is the current build, not a stale/pre-fix version
[sysprep]   - diagnose_ble.sh has been run and comes back clean
[sysprep] This script does not check any of that — it only strips identity.

EOF

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  log "--check only, no changes made. Re-run with --yes to actually sysprep."
  exit 0
fi

if [[ "$CONFIRM" -ne 1 ]]; then
  echo "[sysprep] this is destructive (deletes SSH host keys, machine-id, BLE bonds)." >&2
  echo "[sysprep] re-run with --yes to proceed." >&2
  exit 2
fi

log "stopping bluetooth + hid-remote/hid-agent/ble-remote units"
systemctl stop bluetooth.service 2>/dev/null || true
for unit in $(systemctl list-units --all --no-legend --plain 'hid-remote*' 'hid-agent*' 'ble-remote*' 2>/dev/null | awk '{print $1}'); do
  systemctl stop "$unit" 2>/dev/null || true
done

log "wiping /var/lib/bluetooth (bonds are per-adapter-MAC, meaningless on a clone)"
rm -rf /var/lib/bluetooth/*

log "deleting SSH host keys"
rm -f /etc/ssh/ssh_host_*

log "emptying machine-id"
truncate -s 0 /etc/machine-id
if [[ -e /var/lib/dbus/machine-id && ! -L /var/lib/dbus/machine-id ]]; then
  rm -f /var/lib/dbus/machine-id
  ln -s /etc/machine-id /var/lib/dbus/machine-id
fi

log "resetting hostname to placeholder"
echo "golden-template" > /etc/hostname
hostnamectl set-hostname golden-template 2>/dev/null || true
sed -i '/^127\.0\.1\.1[[:space:]]/d' /etc/hosts
echo "127.0.1.1	golden-template" >> /etc/hosts

log "clearing apt cache, logs, tmp, shell history"
apt-get clean
find /var/log -type f -exec truncate -s 0 {} \; 2>/dev/null || true
journalctl --rotate 2>/dev/null || true
journalctl --vacuum-time=1s 2>/dev/null || true
rm -rf /tmp/* /tmp/.[!.]* 2>/dev/null || true
rm -f /root/.bash_history
for h in /home/*/.bash_history; do rm -f "$h"; done

log "done. Power off now and image the SSD — do NOT reboot this box back into service on this state."
log "Reminder: VG is still named for the old host ('host3--vg' style). Run:"
log "  bash $0 --rename-vg-warning"
log "if you want the (manual, reviewed) fix for that."
