#!/bin/bash
# Ensure RAM-disk hot-storage mounts match .env on every vpt-stream start.
#
# This is the lifecycle companion to setup_ram_hot_storage.sh (which runs
# once at install time). It is invoked by vpt-stream.service as:
#
#   ExecStartPre=-+/opt/virtualpytest/setup/local/linux/backend_host/ensure_hot_mounts.sh
#
# The `-` prefix tells systemd to ignore a non-zero exit, and this script
# additionally always exits 0 — a host without tmpfs support must still be
# able to start vpt-stream in cold-only SD mode. run_ffmpeg.sh detects the
# missing tmpfs via `mount | grep` and takes its existing SD fallback.
#
# What it does:
#   1. Parse DEVICE{N}_VIDEO_CAPTURE_PATH entries from .env.
#   2. For each active device, make sure /hot is a tmpfs mount. If a stale
#      non-tmpfs /hot directory exists, rename it to hot.stale.<timestamp>
#      so future mounts never overlay it and Python helpers see a clean
#      state.
#   3. Write/update the /etc/fstab entry so the mount survives reboot.
#   4. Clean up orphan /hot tmpfs mounts whose device was removed from .env.
#
# No `set -e` — every failure is logged and ignored.

PROJECT_ROOT="/opt/virtualpytest"
ENV_FILE="$PROJECT_ROOT/backend_host/src/.env"
BASE_PATH="/var/www/html/stream"
MOUNT_SIZE="200M"
VPT_USER="vpt_user"
DRY_RUN="${DRY_RUN:-0}"

log_info() { echo "INFO: $*"; }
log_warn() { echo "WARN: $*"; }

trap 'exit 0' EXIT

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "       [dry-run] $*"
    return 0
  fi
  "$@"
}

if [ ! -f "$ENV_FILE" ]; then
  log_warn ".env not found at $ENV_FILE — skipping hot-mount provisioning"
  exit 0
fi

# Resolve vpt_user uid/gid — without this we can't build a correct tmpfs
# mount line. If the user doesn't exist, bail out cleanly.
VPT_UID=$(id -u "$VPT_USER" 2>/dev/null)
VPT_GID=$(id -g "$VPT_USER" 2>/dev/null)
if [ -z "$VPT_UID" ] || [ -z "$VPT_GID" ]; then
  log_warn "vpt_user not found — skipping hot-mount provisioning"
  exit 0
fi

# Parse DEVICE{N}_VIDEO_CAPTURE_PATH (same extractor as setup_ram_hot_storage.sh).
DEVICES=()
ACTIVE_HOT_PATHS=()

HOST_CAPTURE_PATH=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
if [ -n "$HOST_CAPTURE_PATH" ]; then
  DEVICES+=("$(basename "$HOST_CAPTURE_PATH")")
fi

for i in {1..14}; do
  VIDEO_CAPTURE_PATH=$(grep "^DEVICE${i}_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
  if [ -n "$VIDEO_CAPTURE_PATH" ]; then
    DEVICES+=("$(basename "$VIDEO_CAPTURE_PATH")")
  fi
done

if [ ${#DEVICES[@]} -eq 0 ]; then
  log_warn ".env has no DEVICE{N}_VIDEO_CAPTURE_PATH entries — nothing to provision"
  exit 0
fi

log_info "parsing .env, found ${#DEVICES[@]} active device(s): ${DEVICES[*]}"

MOUNT_OPTS="size=$MOUNT_SIZE,noexec,nodev,nosuid,uid=$VPT_UID,gid=$VPT_GID,mode=755"

for DEVICE in "${DEVICES[@]}"; do
  DEVICE_DIR="$BASE_PATH/$DEVICE"
  HOT_PATH="$DEVICE_DIR/hot"

  run mkdir -p "$DEVICE_DIR" 2>/dev/null
  run chown "$VPT_USER:$VPT_USER" "$DEVICE_DIR" 2>/dev/null || true

  # Fast path: already a tmpfs mount.
  if mountpoint -q "$HOT_PATH" 2>/dev/null; then
    log_info "$DEVICE — already mounted as tmpfs, skip"
    ACTIVE_HOT_PATHS+=("$(realpath "$HOT_PATH" 2>/dev/null || echo "$HOT_PATH")")
    continue
  fi

  # Stale-dir fix: /hot exists but is NOT a tmpfs mount. Preserve it out of
  # the way so future mounts never overlay it. This is the root cause of the
  # capture4-on-host3 false-stuck bug.
  if [ -d "$HOT_PATH" ]; then
    STALE_NAME="hot.stale.$(date +%Y%m%d-%H%M%S)"
    log_warn "$DEVICE — /hot exists but is not a tmpfs mount (stale dir)"
    log_info "       renaming $HOT_PATH -> $DEVICE_DIR/$STALE_NAME"
    run mv "$HOT_PATH" "$DEVICE_DIR/$STALE_NAME" 2>/dev/null || \
      log_warn "$DEVICE — could not rename stale /hot (permission?); continuing"
  fi

  run mkdir -p "$HOT_PATH" 2>/dev/null

  # Try to mount tmpfs. Any failure (no tmpfs support, OOM, read-only /etc)
  # is logged and ignored — run_ffmpeg.sh will fall back to SD mode.
  if [ "$DRY_RUN" = "1" ]; then
    echo "       [dry-run] would mount -t tmpfs -o $MOUNT_OPTS tmpfs $HOT_PATH"
  elif mount -t tmpfs -o "$MOUNT_OPTS" tmpfs "$HOT_PATH" 2>/dev/null; then
    log_info "$DEVICE — mounted tmpfs ($MOUNT_SIZE) at $HOT_PATH"
    mkdir -p "$HOT_PATH/captures" "$HOT_PATH/segments" "$HOT_PATH/thumbnails" "$HOT_PATH/metadata" 2>/dev/null
    chown -R "$VPT_USER:$VPT_USER" "$HOT_PATH" 2>/dev/null || true
    chmod 755 "$HOT_PATH" "$HOT_PATH/captures" "$HOT_PATH/segments" "$HOT_PATH/thumbnails" "$HOT_PATH/metadata" 2>/dev/null || true
    ACTIVE_HOT_PATHS+=("$(realpath "$HOT_PATH" 2>/dev/null || echo "$HOT_PATH")")
  else
    log_warn "$DEVICE — could not mount tmpfs at $HOT_PATH; ffmpeg will fall back to SD mode"
    continue
  fi

  # Best-effort fstab upsert (only if we successfully mounted).
  REAL_HOT_PATH="$(realpath "$HOT_PATH" 2>/dev/null || echo "$HOT_PATH")"
  FSTAB_LINE="tmpfs $REAL_HOT_PATH tmpfs $MOUNT_OPTS 0 0"
  if [ -w /etc/fstab ] || [ "$(id -u)" = "0" ]; then
    if grep -Fq "$REAL_HOT_PATH" /etc/fstab 2>/dev/null; then
      existing=$(grep -F "$REAL_HOT_PATH" /etc/fstab)
      if [ "$existing" != "$FSTAB_LINE" ]; then
        if [ "$DRY_RUN" = "1" ]; then
          echo "       [dry-run] would update /etc/fstab entry for $REAL_HOT_PATH"
        else
          grep -Fv "$REAL_HOT_PATH" /etc/fstab > /etc/fstab.tmp 2>/dev/null && \
            echo "$FSTAB_LINE" >> /etc/fstab.tmp && \
            mv /etc/fstab.tmp /etc/fstab && \
            log_info "$DEVICE — updated /etc/fstab entry" || \
            log_warn "$DEVICE — could not update /etc/fstab"
        fi
      fi
    else
      if [ "$DRY_RUN" = "1" ]; then
        echo "       [dry-run] would add /etc/fstab entry for $REAL_HOT_PATH"
      else
        echo "$FSTAB_LINE" >> /etc/fstab 2>/dev/null && \
          log_info "$DEVICE — added to /etc/fstab" || \
          log_warn "$DEVICE — could not append to /etc/fstab"
      fi
    fi
  else
    log_warn "$DEVICE — /etc/fstab not writable (need root?); mount will not survive reboot"
  fi
done

# Cleanup: unmount /hot tmpfs mounts whose device is no longer in .env.
log_info "cleanup pass — checking for orphan tmpfs hot mounts"
CLEANUP_COUNT=0
MOUNTED_HOT_PATHS=$(mount | awk '$1 == "tmpfs" && $3 ~ /\/hot$/ { print $3 }')
for MOUNTED_PATH in $MOUNTED_HOT_PATHS; do
  FOUND=0
  for ACTIVE_PATH in "${ACTIVE_HOT_PATHS[@]}"; do
    if [ "$MOUNTED_PATH" = "$ACTIVE_PATH" ]; then
      FOUND=1
      break
    fi
  done
  if [ $FOUND -eq 0 ]; then
    log_info "unmounting orphan $MOUNTED_PATH"
    if [ "$DRY_RUN" = "1" ]; then
      echo "       [dry-run] would umount $MOUNTED_PATH and strip fstab entry"
      continue
    fi
    umount "$MOUNTED_PATH" 2>/dev/null && CLEANUP_COUNT=$((CLEANUP_COUNT + 1)) || \
      log_warn "could not unmount $MOUNTED_PATH (in use?); leaving it alone"
    grep -Fv "$MOUNTED_PATH" /etc/fstab > /etc/fstab.tmp 2>/dev/null && \
      mv /etc/fstab.tmp /etc/fstab 2>/dev/null || true
  fi
done

if [ $CLEANUP_COUNT -eq 0 ]; then
  log_info "cleanup pass — no orphan mounts found"
fi

exit 0
