#!/bin/bash

# VirtualPyTest - Permission Setup Script
# All storage owned by vpt_user. Nginx only needs read access (755/644 suffices).
# Usage: ./setup_permissions.sh [--user USERNAME]

set -e

# Parse command line arguments
# Default to vpt_user (VirtualPyTest service user)
TARGET_USER="vpt_user"

while [[ $# -gt 0 ]]; do
    case $1 in
        --user=*)
            TARGET_USER="${1#*=}"
            shift
            ;;
        --user)
            TARGET_USER="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--user USERNAME]"
            echo "  --user USERNAME   Set up permissions for specific user (default: vpt_user)"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            echo "❌ Unknown parameter: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "🔐 Setting up VirtualPyTest permissions for user: $TARGET_USER"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run with sudo privileges"
    echo "Usage: sudo $0 [--user $TARGET_USER]"
    exit 1
fi

# Validate target user exists
if ! id "$TARGET_USER" &>/dev/null; then
    echo "❌ User '$TARGET_USER' does not exist"
    exit 1
fi

echo "👤 Setting up permissions for user: $TARGET_USER"

# =============================================================================
# SYSTEM USER GROUPS AND PERMISSIONS
# =============================================================================

echo "📝 Adding user to required system groups..."

# Add user to video, audio, and render groups for hardware access
usermod -aG video,audio,render "$TARGET_USER"
echo "✅ Added $TARGET_USER to video, audio, render groups"

# =============================================================================
# DISPLAY AND X11 PERMISSIONS
# =============================================================================

echo "🖥️ Setting up display permissions..."

# Set up X11 permissions for vpt_user (if DISPLAY is set)
if [ -n "$DISPLAY" ]; then
    echo "Setting X11 permissions for display: $DISPLAY"
    sudo -u "$TARGET_USER" DISPLAY="$DISPLAY" xhost +local:"$TARGET_USER" 2>/dev/null || echo "⚠️ Warning: Could not set X11 permissions (display may not be available)"
    echo "✅ X11 permissions configured for $TARGET_USER"
else
    echo "⚠️ No DISPLAY variable set, skipping X11 permissions"
fi

# =============================================================================
# DIRECTORY STRUCTURE CREATION
# =============================================================================

echo "📁 Creating directory structure..."

# Create main www directories
mkdir -p /var/www/html/stream
mkdir -p /var/www/.config/pulse
mkdir -p /tmp/virtualpytest

# Parse DEVICE{N}_VIDEO_CAPTURE_PATH from .env so we operate on exactly the
# devices the host is configured for. This replaces the old hardcoded
# `for i in {1..4}` loops that silently ignored device 5+.
ENV_FILE="/opt/virtualpytest/backend_host/src/.env"
DEVICE_FOLDERS=()
if [ -f "$ENV_FILE" ]; then
    HOST_CAPTURE_PATH=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
    if [ -n "$HOST_CAPTURE_PATH" ]; then
        DEVICE_FOLDERS+=("$(basename "$HOST_CAPTURE_PATH")")
    fi
    for i in {1..30}; do
        VIDEO_CAPTURE_PATH=$(grep "^DEVICE${i}_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs)
        if [ -n "$VIDEO_CAPTURE_PATH" ]; then
            DEVICE_FOLDERS+=("$(basename "$VIDEO_CAPTURE_PATH")")
        fi
    done
fi
# Fallback: if .env is missing or empty (fresh install, permission script
# running before .env is seeded), provision the classic capture1-4 set so
# the installer bootstrap still has something to chown.
if [ ${#DEVICE_FOLDERS[@]} -eq 0 ]; then
    DEVICE_FOLDERS=(capture1 capture2 capture3 capture4)
fi

echo "📋 Devices from .env: ${DEVICE_FOLDERS[*]}"

for folder in "${DEVICE_FOLDERS[@]}"; do
    mkdir -p "/var/www/html/stream/$folder"
    mkdir -p "/var/www/html/stream/$folder/captures"
done

# Create additional directories
mkdir -p /var/www/html/camera/captures
mkdir -p /var/www/html/vnc/stream

echo "✅ Directory structure created"

# =============================================================================
# HOT STORAGE RESET
# =============================================================================

echo "🧹 Clearing hot stream storage..."

# Hot stream data is disposable runtime output, but the tmpfs mount itself must
# survive. Clear capture contents without unmounting hot RAM storage so later
# services continue writing to /hot instead of silently falling back to SD.
for folder in "${DEVICE_FOLDERS[@]}"; do
    capture_dir="/var/www/html/stream/$folder"
    hot_dir="$capture_dir/hot"

    mkdir -p "$capture_dir"
    mkdir -p "$hot_dir"

    # Clear cold/runtime content while preserving the hot mountpoint.
    find "$capture_dir" -mindepth 1 -maxdepth 1 ! -name hot -exec rm -rf {} + 2>/dev/null || true

    if mountpoint -q "$hot_dir" 2>/dev/null; then
        find "$hot_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    else
        rm -rf "$hot_dir" 2>/dev/null || true
        mkdir -p "$hot_dir"
    fi
done

find /var/www/html/stream -mindepth 1 -maxdepth 1 ! -name 'capture*' ! -name 'capture' -exec rm -rf {} + 2>/dev/null || true

echo "✅ Hot stream storage cleared"

# Recreate expected hot storage directories after cleanup
for folder in "${DEVICE_FOLDERS[@]}"; do
    mkdir -p "/var/www/html/stream/$folder"
    mkdir -p "/var/www/html/stream/$folder/captures"
    mkdir -p "/var/www/html/stream/$folder/hot"
done

mkdir -p "/var/www/html/stream/capture"

# =============================================================================
# OWNERSHIP AND PERMISSIONS
# =============================================================================

echo "🔐 Setting ownership and permissions..."

# Set ownership of directories after hot storage reset
chown vpt_user:vpt_user /var/www/html/stream
chown -R vpt_user:vpt_user /var/www/.config/pulse
chown -R "$TARGET_USER:$TARGET_USER" /tmp/virtualpytest

# Set permissions (755: owner rwx, others rx - nginx reads as "other")
chmod 755 /var/www/html/stream
chmod -R 755 /var/www/.config/pulse

# Setup /tmp directories with proper permissions
echo "🔧 Configuring /tmp directories..."
chmod 1777 /tmp 2>/dev/null || true
chmod -R 755 /tmp/virtualpytest /tmp/kpi_queue 2>/dev/null || true
echo "✅ /tmp permissions configured"

# Set specific permissions for capture directories (need write access)
for folder in "${DEVICE_FOLDERS[@]}"; do
    chown -R vpt_user:vpt_user "/var/www/html/stream/$folder"
    chmod -R 755 "/var/www/html/stream/$folder"
done

# Set permissions for HOST capture directory (same as device directories)
mkdir -p "/var/www/html/stream/capture"
chown -R vpt_user:vpt_user "/var/www/html/stream/capture"
chmod -R 755 "/var/www/html/stream/capture"

# Set permissions for camera and vnc directories
chown -R vpt_user:vpt_user /var/www/html/camera
chmod -R 755 /var/www/html/camera

if [ -d "/var/www/html/vnc" ]; then
    chown -R vpt_user:vpt_user /var/www/html/vnc
    chmod -R 755 /var/www/html/vnc
fi

# Normalize IR device access for the service user. LIRC character devices are
# typically owned by root:video, and vpt_user is added to the video group above.
for lirc_dev in /dev/lirc*; do
    if [ -e "$lirc_dev" ]; then
        chgrp video "$lirc_dev" 2>/dev/null || true
        chmod 660 "$lirc_dev" 2>/dev/null || true
    fi
done

echo "✅ Ownership and permissions set"

# =============================================================================
# BINARY PERMISSIONS (if they exist)
# =============================================================================

echo "🔧 Setting binary permissions..."

# Set permissions for analysis scripts if they exist
if [ -f "/usr/local/bin/analyze_frame.py" ]; then
    chown -R "$TARGET_USER:$TARGET_USER" /usr/local/bin/analyze_frame.py
    chmod +x /usr/local/bin/analyze_frame.py
    echo "✅ analyze_frame.py permissions set"
fi

if [ -f "/usr/local/bin/analyze_audio.py" ]; then
    chown -R "$TARGET_USER:$TARGET_USER" /usr/local/bin/analyze_audio.py
    chmod +x /usr/local/bin/analyze_audio.py
    echo "✅ analyze_audio.py permissions set"
fi

# =============================================================================
# PULSE AUDIO CONFIGURATION
# =============================================================================

echo "🔊 Setting up PulseAudio permissions..."

# Create PulseAudio config directory
mkdir -p /var/www/.config/pulse
chown -R vpt_user:vpt_user /var/www/.config/pulse
chmod -R 755 /var/www/.config/pulse

echo "✅ PulseAudio permissions configured"

# =============================================================================
# VERIFICATION AND SUMMARY
# =============================================================================

echo ""
echo "🎉 Permission setup completed successfully!"
echo ""
echo "📋 Summary of changes:"
echo "   👤 User groups:"
echo "      - $TARGET_USER: added to video, audio, render"
echo ""
echo "   📁 Directories created:"
echo "      - /var/www/html/stream/capture{1..4}/"
echo "      - /var/www/html/camera/captures/"
echo "      - /var/www/.config/pulse/"
echo "      - /tmp/virtualpytest/"
echo ""
echo "   🔐 Permissions set:"
echo "      - /var/www/html/stream/: vpt_user:vpt_user, 755"
echo "      - /var/www/.config/pulse/: vpt_user:vpt_user, 755"
echo "      - /tmp/: 1777 (sticky bit, world-writable)"
echo "      - /tmp/virtualpytest/: 777 (recursive)"
echo ""
echo "   🖥️ Display access:"
echo "      - X11 permissions granted to $TARGET_USER (if display available)"
echo ""
echo "⚠️ IMPORTANT NOTES:"
echo "   - You may need to log out and back in for group changes to take effect"
echo "   - If using systemd services, restart them after permission changes"
echo "   - For Docker deployments, ensure proper volume mounts are configured"
echo ""
echo "🔄 To verify permissions are working:"
echo "   sudo -u vpt_user touch /var/www/html/stream/capture1/test.txt"
echo "   ls -la /var/www/html/stream/capture1/test.txt"
echo "   sudo rm /var/www/html/stream/capture1/test.txt"
