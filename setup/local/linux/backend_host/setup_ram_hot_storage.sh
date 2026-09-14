#!/bin/bash
# Setup RAM-based hot storage - DYNAMIC FROM .ENV
# Auto-configures /etc/fstab for automatic remount on reboot
# Reads device configuration from backend_host/src/.env

set -e

MOUNT_SIZE="200M"
BASE_PATH="/var/www/html/stream"
FSTAB_BACKUP="/etc/fstab.backup.$(date +%Y%m%d_%H%M%S)"

# This script assumes it's running from /opt/virtualpytest (installed location)
# It should be called by install_host.sh after changing to the project root
PROJECT_ROOT="/opt/virtualpytest"
ENV_FILE="$PROJECT_ROOT/backend_host/src/.env"

echo "================================"
echo "RAM Hot Storage Setup (Dynamic)"
echo "================================"

# Debug paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Debug info:"
echo "  Script location: $SCRIPT_DIR"
echo "  Project root: $PROJECT_ROOT"
echo "  Looking for .env at: $ENV_FILE"
echo ""

# Check if .env file exists (should have been created by install_host.sh)
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: .env file not found at $ENV_FILE"
    echo "   Please run install_host.sh first to create the .env file"
    exit 1
fi

echo "✅ Found .env file at $ENV_FILE"

echo "Reading device configuration from: $ENV_FILE"
echo ""

# Parse devices from .env file (look for HOST_VIDEO_CAPTURE_PATH and DEVICE{N}_VIDEO_CAPTURE_PATH)
DEVICES=()
REAL_HOT_PATHS=()  # Resolved mount paths (populated during mount loop)

# Check for HOST device first
HOST_CAPTURE_PATH=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
if [ -n "$HOST_CAPTURE_PATH" ]; then
    CAPTURE_FOLDER=$(basename "$HOST_CAPTURE_PATH")
    DEVICES+=("$CAPTURE_FOLDER")
    echo "✓ Found host: HOST -> $CAPTURE_FOLDER"
fi

# Check for regular devices (dynamically detect up to 100)
for i in {1..14}; do
    DEVICE_NAME=$(grep "^DEVICE${i}_NAME=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
    VIDEO_CAPTURE_PATH=$(grep "^DEVICE${i}_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
    
    if [ -n "$VIDEO_CAPTURE_PATH" ]; then
        CAPTURE_FOLDER=$(basename "$VIDEO_CAPTURE_PATH")
        DEVICES+=("$CAPTURE_FOLDER")
        echo "✓ Found device$i: $DEVICE_NAME -> $CAPTURE_FOLDER"
    elif [ $i -gt 20 ] && [ ${#DEVICES[@]} -gt 0 ]; then
        # Stop scanning after 20 consecutive empty slots beyond configured devices
        break
    fi
done

if [ ${#DEVICES[@]} -eq 0 ]; then
    echo "⚠️  No devices found in .env file"
    echo "   Please configure DEVICE1_VIDEO_CAPTURE_PATH, etc. in $ENV_FILE"
    exit 1
fi

echo ""
echo "Configuring RAM storage for ${#DEVICES[@]} device(s): ${DEVICES[*]}"
echo ""

# Check if we have sudo access
if ! sudo -n true 2>/dev/null; then
    echo "⚠️  This script requires sudo access"
    exit 1
fi

# All storage owned by vpt_user (the single service user for all VPT services).
# Nginx only needs read access to serve HLS segments - standard 755/644 perms suffice.
VPT_USER="vpt_user"
VPT_UID=$(id -u "$VPT_USER" 2>/dev/null || { echo "❌ $VPT_USER user not found"; exit 1; })
VPT_GID=$(id -g "$VPT_USER" 2>/dev/null || { echo "❌ $VPT_USER group not found"; exit 1; })

echo "Mount ownership: $VPT_USER (uid=$VPT_UID, gid=$VPT_GID)"
echo ""

# Ensure base stream directory is owned by vpt_user (active_captures.conf lives here)
sudo mkdir -p "$BASE_PATH"
sudo chown "$VPT_USER:$VPT_USER" "$BASE_PATH"
echo "🔍 Permission check: $BASE_PATH -> $(ls -ld "$BASE_PATH")"

for DEVICE in "${DEVICES[@]}"; do
  HOT_PATH="$BASE_PATH/$DEVICE/hot"

  # Create device directory and mount point
  DEVICE_DIR="$BASE_PATH/$DEVICE"
  echo "Creating device directory: $DEVICE_DIR"
  sudo mkdir -p "$HOT_PATH"
  sudo chown "$VPT_USER:$VPT_USER" "$DEVICE_DIR"
  echo "🔍 Permission check: $DEVICE_DIR -> $(ls -ld "$DEVICE_DIR")"

  # Resolve symlinks to get the real filesystem path for mount/fstab operations.
  # Cold storage (captures, segments, etc.) can live on any partition via symlinks,
  # but hot storage must always be tmpfs in RAM. mount/fstab require real paths.
  REAL_HOT_PATH=$(realpath "$HOT_PATH")
  if [ "$REAL_HOT_PATH" != "$HOT_PATH" ]; then
    echo "  Symlink resolved: $HOT_PATH -> $REAL_HOT_PATH"
  fi

  # Track resolved paths for cleanup section
  REAL_HOT_PATHS+=("$REAL_HOT_PATH")

  DESIRED_MOUNT_OPTS="size=$MOUNT_SIZE,noexec,nodev,nosuid,uid=$VPT_UID,gid=$VPT_GID,mode=755"

  # Check if already mounted (use real path since mount resolves symlinks)
  if mountpoint -q "$REAL_HOT_PATH" 2>/dev/null; then
    echo "↻ Remounting tmpfs at $REAL_HOT_PATH with current ownership/options"
    sudo mount -o "remount,$DESIRED_MOUNT_OPTS" "$REAL_HOT_PATH"
    echo "✓ Remounted (owner: $VPT_USER, mode: 755)"
  else
    echo "Mounting tmpfs ($MOUNT_SIZE) at $REAL_HOT_PATH"
    sudo mount -t tmpfs -o "$DESIRED_MOUNT_OPTS" tmpfs "$REAL_HOT_PATH"
    echo "✓ Mounted (owner: $VPT_USER, mode: 755)"
  fi

  # Create subdirectories in RAM (instant, no SD card I/O)
  # Note: Audio extracted directly to COLD storage - no hot/audio needed
  sudo mkdir -p "$HOT_PATH/captures"
  sudo mkdir -p "$HOT_PATH/thumbnails"
  sudo mkdir -p "$HOT_PATH/segments"
  sudo mkdir -p "$HOT_PATH/metadata"

  # Ownership: vpt_user (all VPT services run as this user)
  # Permissions: 755 (owner rwx, others rx - nginx reads as "other")
  sudo chown -R "$VPT_USER:$VPT_USER" "$REAL_HOT_PATH"
  sudo chmod 755 "$HOT_PATH"
  sudo chmod 755 "$HOT_PATH/captures"
  sudo chmod 755 "$HOT_PATH/thumbnails"
  sudo chmod 755 "$HOT_PATH/segments"
  sudo chmod 755 "$HOT_PATH/metadata"
  
  echo "✓ $DEVICE hot storage ready (captures, thumbnails, segments, metadata)"
  
  # Create ALL cold storage directories (on disk partition)
  # Audio stored directly to COLD (extracted from MP4 chunks)
  # thumbnails needed as fallback when hot storage detection fails in run_ffmpeg.sh
  for subdir in captures thumbnails segments metadata audio; do
    COLD_DIR="$BASE_PATH/$DEVICE/$subdir"
    if [ ! -d "$COLD_DIR" ]; then
      sudo mkdir -p "$COLD_DIR"
    fi
    sudo chown "$VPT_USER:$VPT_USER" "$COLD_DIR"
    sudo chmod 755 "$COLD_DIR"
  done

  # Create hour folders (0-23) for rolling 24h storage
  for hour in {0..23}; do
    for subdir in segments metadata audio; do
      HOUR_DIR="$BASE_PATH/$DEVICE/$subdir/$hour"
      if [ ! -d "$HOUR_DIR" ]; then
        sudo mkdir -p "$HOUR_DIR"
      fi
      sudo chown "$VPT_USER:$VPT_USER" "$HOUR_DIR"
      sudo chmod 755 "$HOUR_DIR"
    done
  done

  # Create temp directory for progressive MP4 merging
  TEMP_DIR="$BASE_PATH/$DEVICE/segments/temp"
  if [ ! -d "$TEMP_DIR" ]; then
    sudo mkdir -p "$TEMP_DIR"
  fi
  sudo chown "$VPT_USER:$VPT_USER" "$TEMP_DIR"
  sudo chmod 755 "$TEMP_DIR"

  # Create temp directory for metadata merging
  METADATA_TEMP_DIR="$BASE_PATH/$DEVICE/metadata/temp"
  if [ ! -d "$METADATA_TEMP_DIR" ]; then
    sudo mkdir -p "$METADATA_TEMP_DIR"
  fi
  sudo chown "$VPT_USER:$VPT_USER" "$METADATA_TEMP_DIR"
  sudo chmod 755 "$METADATA_TEMP_DIR"
  
  echo "✓ Cold storage ready (hour folders 0-23, temp dirs)"

  # Final permission verification for this device
  echo "🔍 Permission verification for $DEVICE:"
  echo "   $(ls -ld "$BASE_PATH")"
  echo "   $(ls -ld "$DEVICE_DIR")"
  echo "   $(ls -ld "$HOT_PATH")"
  for subdir in captures thumbnails segments metadata audio; do
    echo "   $(ls -ld "$DEVICE_DIR/$subdir" 2>/dev/null || echo "   MISSING: $DEVICE_DIR/$subdir")"
  done

  # Write test: verify vpt_user can actually write
  if sudo -u "$VPT_USER" touch "$BASE_PATH/.perm_test" 2>/dev/null; then
    sudo -u "$VPT_USER" rm -f "$BASE_PATH/.perm_test"
    echo "   ✅ vpt_user can write to $BASE_PATH"
  else
    echo "   ❌ vpt_user CANNOT write to $BASE_PATH"
  fi
  if sudo -u "$VPT_USER" touch "$DEVICE_DIR/.perm_test" 2>/dev/null; then
    sudo -u "$VPT_USER" rm -f "$DEVICE_DIR/.perm_test"
    echo "   ✅ vpt_user can write to $DEVICE_DIR"
  else
    echo "   ❌ vpt_user CANNOT write to $DEVICE_DIR"
  fi
  if sudo -u "$VPT_USER" touch "$HOT_PATH/.perm_test" 2>/dev/null; then
    sudo -u "$VPT_USER" rm -f "$HOT_PATH/.perm_test"
    echo "   ✅ vpt_user can write to $HOT_PATH"
  else
    echo "   ❌ vpt_user CANNOT write to $HOT_PATH"
  fi
  echo ""
done

# Configure /etc/fstab for auto-mount on reboot
echo "================================"
echo "Configuring /etc/fstab for auto-mount on reboot..."
echo "================================"

# Backup fstab
sudo cp /etc/fstab "$FSTAB_BACKUP"
echo "✓ Backed up /etc/fstab to $FSTAB_BACKUP"

ENTRIES_ADDED=0
ENTRIES_UPDATED=0

for idx in "${!DEVICES[@]}"; do
  DEVICE="${DEVICES[$idx]}"
  HOT_PATH="$BASE_PATH/$DEVICE/hot"
  REAL_HOT_PATH="${REAL_HOT_PATHS[$idx]}"
  FSTAB_LINE="tmpfs $REAL_HOT_PATH tmpfs size=$MOUNT_SIZE,noexec,nodev,nosuid,uid=$VPT_UID,gid=$VPT_GID,mode=755 0 0"

  # Normalize existing entries so stale uid/gid or old path variants are repaired.
  if grep -Fq "$REAL_HOT_PATH" /etc/fstab || grep -Fq "$HOT_PATH" /etc/fstab; then
    existing_entry=$(grep -F "$REAL_HOT_PATH" /etc/fstab || grep -F "$HOT_PATH" /etc/fstab || true)
    if [ "$existing_entry" != "$FSTAB_LINE" ]; then
      echo "Updating /etc/fstab entry for $REAL_HOT_PATH..."
      sudo awk -v real="$REAL_HOT_PATH" -v logical="$HOT_PATH" 'index($0, real) == 0 && index($0, logical) == 0 { print }' /etc/fstab | sudo tee /etc/fstab.tmp > /dev/null
      echo "$FSTAB_LINE" | sudo tee -a /etc/fstab.tmp > /dev/null
      sudo mv /etc/fstab.tmp /etc/fstab
      echo "✓ Updated ($VPT_USER:$VPT_USER, mode: 755)"
      ENTRIES_UPDATED=$((ENTRIES_UPDATED + 1))
    else
      echo "✓ $REAL_HOT_PATH already in /etc/fstab"
    fi
  else
    echo "Adding $REAL_HOT_PATH to /etc/fstab..."
    echo "$FSTAB_LINE" | sudo tee -a /etc/fstab > /dev/null
    echo "✓ Added ($VPT_USER:$VPT_USER, mode: 755)"
    ENTRIES_ADDED=$((ENTRIES_ADDED + 1))
  fi
done

if [ $ENTRIES_ADDED -gt 0 ] || [ $ENTRIES_UPDATED -gt 0 ]; then
  echo ""
  echo "Testing /etc/fstab configuration..."
  if sudo mount -a; then
    echo "✅ /etc/fstab test successful - mounts will auto-mount on reboot"
  else
    echo "❌ /etc/fstab test failed - restoring backup"
    sudo cp "$FSTAB_BACKUP" /etc/fstab
    exit 1
  fi
fi

# Clean up: Unmount and remove from fstab any devices NOT in .env
echo ""
echo "================================"
echo "Cleaning up unused devices..."
echo "================================"

# Find all mounted tmpfs hot storage paths (mount always shows real paths)
MOUNTED_HOT_PATHS=$(mount | grep "tmpfs.*hot" | awk '{print $3}')
CLEANUP_COUNT=0

for MOUNTED_PATH in $MOUNTED_HOT_PATHS; do
  # Check if this mounted path is in our active resolved paths list
  FOUND=0
  for ACTIVE_PATH in "${REAL_HOT_PATHS[@]}"; do
    if [ "$MOUNTED_PATH" = "$ACTIVE_PATH" ]; then
      FOUND=1
      break
    fi
  done

  if [ $FOUND -eq 0 ]; then
    echo "Unmounting unused hot storage: $MOUNTED_PATH"
    sudo umount "$MOUNTED_PATH" 2>/dev/null && CLEANUP_COUNT=$((CLEANUP_COUNT + 1)) || echo "  ⚠️  Could not unmount $MOUNTED_PATH"
  fi
done

# Also check fstab for entries not in active list
FSTAB_HOT_PATHS=$(grep "tmpfs.*hot" /etc/fstab 2>/dev/null | awk '{print $2}')
for FSTAB_PATH in $FSTAB_HOT_PATHS; do
  FOUND=0
  for ACTIVE_PATH in "${REAL_HOT_PATHS[@]}"; do
    if [ "$FSTAB_PATH" = "$ACTIVE_PATH" ]; then
      FOUND=1
      break
    fi
  done

  if [ $FOUND -eq 0 ]; then
    echo "Removing $FSTAB_PATH from /etc/fstab..."
    sudo cp /etc/fstab "$FSTAB_BACKUP.cleanup"
    sudo grep -v "$FSTAB_PATH" /etc/fstab | sudo tee /etc/fstab.tmp > /dev/null
    sudo mv /etc/fstab.tmp /etc/fstab
    echo "  ✓ Removed from /etc/fstab"
    CLEANUP_COUNT=$((CLEANUP_COUNT + 1))
  fi
done

if [ $CLEANUP_COUNT -eq 0 ]; then
  echo "✓ No unused devices found"
fi

# Show mounted RAM disks
echo ""
echo "================================"
echo "Mounted RAM disks:"
df -h | grep -E "tmpfs.*/hot|Filesystem"
echo "================================"

echo ""
# Ensure active_captures.conf has correct permissions in new location
ACTIVE_CAPTURES_CONF="/var/www/html/stream/active_captures.conf"
if [ -f "$ACTIVE_CAPTURES_CONF" ]; then
  sudo chmod 666 "$ACTIVE_CAPTURES_CONF"
  echo "✓ Fixed $ACTIVE_CAPTURES_CONF permissions (666)"
fi

echo "✅ RAM hot storage setup complete!"
echo "   • Devices configured: ${#DEVICES[@]} (${DEVICES[*]})"
echo "   • Each device mounted in RAM ($MOUNT_SIZE)"
echo "   • HOT directories: captures, thumbnails, segments, metadata"
echo "   • COLD directories: captures, segments, metadata, audio (with hour folders 0-23)"
echo "   • COLD temp directories: segments/temp, metadata/temp"
echo "   • Owner: $VPT_USER:$VPT_USER"
echo "   • All directories: 755 (owner rwx, nginx reads as other)"
echo "   • Auto-mount configured in /etc/fstab"
echo "   • Will automatically remount on reboot"
echo ""
echo "💡 To add/remove devices:"
echo "   1. Edit $ENV_FILE"
echo "   2. Add/remove HOST_VIDEO_CAPTURE_PATH or DEVICE{N}_VIDEO_CAPTURE_PATH"
echo "   3. Re-run this script to apply changes"
echo ""
