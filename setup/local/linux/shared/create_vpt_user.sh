#!/bin/bash

# VirtualPyTest - Create Service Account (vpt_user) - Must be run as root
# This script creates the dedicated service account for running VirtualPyTest services
# You need to be root su -
set -e

echo "👤 Creating VirtualPyTest service account (vpt_user)..."

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges"
   echo "Usage: sudo ./create_vpt_user.sh"
   exit 1
fi

# Check if vpt_user already exists
if id "vpt_user" &>/dev/null; then
    echo "✅ vpt_user already exists"
    echo "📁 Checking VirtualPyTest directory..."

    # Check if directory exists and has correct ownership
    if [ -d "/opt/virtualpytest" ]; then
        owner=$(stat -c %U /opt/virtualpytest 2>/dev/null || echo "unknown")
        if [ "$owner" = "vpt_user" ]; then
            echo "✅ VirtualPyTest directory exists with correct ownership"
        else
            echo "🔧 Fixing VirtualPyTest directory ownership..."
            chown -R vpt_user:vpt_user /opt/virtualpytest
            echo "✅ Ownership fixed"
        fi
    else
        echo "📁 Creating VirtualPyTest directory..."
        mkdir -p /opt/virtualpytest
        chown -R vpt_user:vpt_user /opt/virtualpytest
        chmod 775 /opt/virtualpytest
        echo "✅ Directory created"
    fi

    # Setup /tmp permissions for all VirtualPyTest operations
    echo "🔧 Configuring /tmp permissions..."
    # Ensure /tmp has standard sticky bit permissions (everyone can write, only owner can delete)
    chmod 1777 /tmp 2>/dev/null || true
    
    # Create VirtualPyTest subdirectories with full access
    mkdir -p /tmp/kpi_queue /tmp/virtualpytest
    chmod -R 777 /tmp/kpi_queue /tmp/virtualpytest 2>/dev/null || true
    
    echo "✅ /tmp permissions configured for vpt_user"

    # Allow vpt_user to read the systemd journal (journalctl -u ...) so the
    # Status page log viewer works. Services run as vpt_user; without this
    # group `journalctl -u vpt-*` returns no entries (not an error).
    if getent group systemd-journal >/dev/null 2>&1; then
        usermod -aG systemd-journal vpt_user
        echo "✅ vpt_user added to systemd-journal group"
    fi

    echo "✅ Service account and directory are ready"
    exit 0
fi

# Create system user for VirtualPyTest services
# vpt_user gets --shell /bin/false on purpose: it is a system service account
# and must not have an interactive login shell. Trade-off: the XFCE4 terminal
# in the VNC take-control session opens then instantly closes (it spawns this
# login shell, which exits immediately). To intentionally enable an interactive
# terminal on a debug/take-control host:
#     sudo usermod -s /bin/bash vpt_user
# This does NOT affect the systemd services (they use explicit ExecStart /
# `sudo -u vpt_user bash -c`, never the login shell). Revert with --shell /bin/false.
echo "🔧 Creating vpt_user system account..."
useradd --system \
        --shell /bin/false \
        --home /var/lib/vpt_user \
        --create-home \
        --comment "VirtualPyTest Service Account" \
        vpt_user

# Create standard VirtualPyTest installation directory
echo "📁 Creating VirtualPyTest directory structure..."
mkdir -p /opt/virtualpytest
chown -R vpt_user:vpt_user /opt/virtualpytest
chmod 775 /opt/virtualpytest

# Setup /tmp permissions for VirtualPyTest operations
echo "🔧 Configuring /tmp permissions for VirtualPyTest..."
# Ensure /tmp has standard sticky bit permissions (everyone can write, only owner can delete)
chmod 1777 /tmp 2>/dev/null || true

# Create VirtualPyTest subdirectories with full access
echo "📁 Creating VirtualPyTest temp directories..."
mkdir -p /tmp/kpi_queue /tmp/virtualpytest
chmod -R 777 /tmp/kpi_queue /tmp/virtualpytest 2>/dev/null || true

echo "✅ /tmp permissions configured for vpt_user"

# Allow vpt_user to read the systemd journal (journalctl -u ...) so the
# Status page log viewer works. Services run as vpt_user; without this
# group `journalctl -u vpt-*` returns no entries (not an error).
if getent group systemd-journal >/dev/null 2>&1; then
    usermod -aG systemd-journal vpt_user
    echo "✅ vpt_user added to systemd-journal group"
fi

# Verify creation
echo "✅ vpt_user created successfully"
echo "   • User: $(id vpt_user)"
echo "   • Home: $(eval echo ~vpt_user)"
echo "   • VirtualPyTest Directory: /opt/virtualpytest"
echo ""