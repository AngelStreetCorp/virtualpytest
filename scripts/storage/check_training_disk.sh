#!/bin/bash
# check_training_disk.sh — watch the dedicated TASK-27 training data disk.
#
# Runs on the storage VM (node1 VM 101, 192.168.0.101), where the 50 GB disk for
# vpt-training is mounted at /mnt/minio-training. Logs to the journal (tag:
# vpt-training-disk) so it is visible via:
#   journalctl -t vpt-training-disk --since today
#
# This does NOT walk the "whatever already watches MinIO's disk" list wired up
# elsewhere (setup/local/linux/storage/inode_watchdog.sh watches /data and /shared via
# cron.d, a different mount) — /mnt/minio-training is new and separate, so this is a
# standalone daily systemd timer per TASK-27 Step 1 task 4.
#
# Install (on VM 101, as root or via sudo):
#   sudo install -m 755 check_training_disk.sh /usr/local/bin/vpt-training-disk-check
#   sudo cp check_training_disk.service check_training_disk.timer /etc/systemd/system/
#   (or pass --install to generate + install the unit files directly, see below)
#
# Exit codes: 0 ok, 1 warn/critical (>= 80% used) — non-zero as the card requires.

set -uo pipefail

MOUNT="${TRAINING_DISK_MOUNT:-/mnt/minio-training}"
WARN_PCT="${WARN_PCT:-80}"
TAG=vpt-training-disk

log() { logger -t "$TAG" -p "$1" -- "$2"; }

install_units() {
    local self_path
    self_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
    local bin=/usr/local/bin/vpt-training-disk-check
    sudo install -m 755 "$self_path" "$bin"
    sudo tee /etc/systemd/system/vpt-training-disk-check.service > /dev/null << EOF
[Unit]
Description=Check free space on the TASK-27 training data disk ($MOUNT)

[Service]
Type=oneshot
ExecStart=$bin
EOF
    sudo tee /etc/systemd/system/vpt-training-disk-check.timer > /dev/null << 'EOF'
[Unit]
Description=Daily check of the TASK-27 training data disk

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now vpt-training-disk-check.timer
    echo "Installed and enabled vpt-training-disk-check.timer (daily 04:00)."
    systemctl list-timers vpt-training-disk-check.timer --no-pager
    exit 0
}

[ "${1:-}" = "--install" ] && install_units

if ! mountpoint -q "$MOUNT"; then
    log err "CRITICAL: $MOUNT is not mounted"
    exit 1
fi

pct="$(df -h --output=pcent "$MOUNT" | tail -1 | tr -d ' %')"
line="$MOUNT disk ${pct}% used"

if [ "$pct" -ge "$WARN_PCT" ]; then
    log warning "WARN: $line (>= ${WARN_PCT}%) — check 'mc quota info training/vpt-training' and 'du -sh $MOUNT/data/*' before it fills."
    exit 1
else
    log info "OK: $line"
    exit 0
fi
