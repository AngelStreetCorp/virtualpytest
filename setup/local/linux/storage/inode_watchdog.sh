#!/bin/bash
# inode_watchdog.sh — warn before MinIO's drive runs out of INODES.
#
# Why this exists (BUG-0109): /data is default-formatted ext4 (1 inode per 16 KB), so the
# 32 GB volume caps at ~2.1 M files. MinIO single-drive mode stores each object as a
# directory with xl.meta (~2 inodes/object), so with ~1 KB objects the inode ceiling
# arrives at roughly 8 GB of 32 GB used. When it hits 100% every PutObject fails with
# XMinioStorageFull — which says "minimum free drive threshold" and sends you to df -h,
# where everything looks fine. The heatmap silently stopped publishing for ~8 hours.
#
# This logs to syslog (tag: vpt-inode-watchdog) so it is visible via:
#   journalctl -t vpt-inode-watchdog --since today
#
# Install (on storage / .101):
#   sudo install -m 755 inode_watchdog.sh /usr/local/bin/vpt-inode-watchdog
#   printf '*/15 * * * * root /usr/local/bin/vpt-inode-watchdog\n' \
#     | sudo tee /etc/cron.d/vpt-inode-watchdog >/dev/null
#
# Exit codes: 0 ok, 1 warn, 2 critical (so it can gate other tooling).

set -uo pipefail

WARN_PCT=${WARN_PCT:-75}
CRIT_PCT=${CRIT_PCT:-90}
MOUNTS=${MOUNTS:-"/data /shared"}
TAG=vpt-inode-watchdog
MINIO_ROOT=${MINIO_ROOT:-/data/minio/virtualpytest}

log() { logger -t "$TAG" -p "$1" -- "$2"; }

rc=0
for m in $MOUNTS; do
  mountpoint -q "$m" 2>/dev/null || continue

  # Inodes are the real limit; bytes are reported alongside for context.
  # NB: no -i here — it is mutually exclusive with --output, and the i* fields already
  # select inode columns.
  read -r i_used i_free i_pct <<<"$(df --output=iused,iavail,ipcent "$m" | tail -1 | tr -d '%')"
  b_pct=$(df -h --output=pcent "$m" | tail -1 | tr -d ' %')

  msg="$m inodes ${i_pct}% used (${i_used} used, ${i_free} free) | disk ${b_pct}% used"

  if   [ "$i_pct" -ge "$CRIT_PCT" ]; then
    # Deliberately no find(1) here: walking the MinIO tree to name the biggest prefix
    # means ~1M stat calls, which is far too slow for a cron job (and slowest exactly
    # when the box is already struggling). Name the command instead of running it.
    log crit "CRITICAL: $msg — MinIO writes will fail with XMinioStorageFull. Find the offender with: for d in $MINIO_ROOT/*/; do echo -n \"\$d \"; find \"\$d\" -xdev | wc -l; done | sort -k2 -rn | head. Delete objects, THEN adjust ILM (setting a rule is itself a write and fails on a full drive)."
    rc=2
  elif [ "$i_pct" -ge "$WARN_PCT" ]; then
    log warning "WARN: $msg — check 'mc ilm rule ls local/virtualpytest' retention against the current write rate."
    [ "$rc" -lt 1 ] && rc=1
  else
    log info "OK: $msg"
  fi
done

exit "$rc"
