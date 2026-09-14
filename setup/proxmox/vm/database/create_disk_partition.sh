#!/bin/bash

# VirtualPyTest - Create and Mount Database Disk for Proxmox VM
# This script prepares dedicated disk for the Database VM:
#   - /dev/sdb → /data (for PostgreSQL, InfluxDB, and Docker volumes)
#
# Usage: Run this BEFORE install_db.sh on Proxmox Database VM
# Run as: sudo bash create_disk_partition.sh

echo "💽 VirtualPyTest - Preparing Database Disk for Proxmox VM"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "This script will:"
echo "   • Create partition on /dev/sdb → mount to /data"
echo "   • Format partition as ext4"
echo "   • Add entry to /etc/fstab for persistent mounting"
echo "   • Setup directories for PostgreSQL, InfluxDB, and Docker"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (use sudo)"
    exit 1
fi

# Install parted if partprobe is not available
if ! command -v partprobe &> /dev/null; then
    echo "📦 Installing parted (for partprobe)..."
    apt-get update -qq
    apt-get install -y parted
    echo ""
fi

# ============================================================================
# Setup Database Disk (sdb)
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Setting up /dev/sdb → /data"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

DEVICE="/dev/sdb"
PARTITION="${DEVICE}1"
MOUNT_POINT="/data"
LABEL="database"

# Check if device exists
if [ ! -b "$DEVICE" ]; then
    echo "❌ Device $DEVICE not found!"
    echo "   Please ensure the disk is attached in Proxmox:"
    echo "   1. Go to VM → Hardware"
    echo "   2. Add → Hard Disk"
    echo "   3. Attach disk as $DEVICE"
    echo "   Recommended size: 500GB+ for production databases"
    exit 1
fi

echo "✅ Found $DEVICE"

# Show disk info
echo "📊 Disk information:"
lsblk "$DEVICE" || true
echo ""

# Check if partition already exists
if [ -b "$PARTITION" ]; then
    echo "✅ Partition $PARTITION already exists"
else
    echo "📦 Creating partition on $DEVICE..."
    echo "   This will:"
    echo "   • Create a single partition using entire disk"
    echo "   • Set partition type to Linux (83)"
    
    # Create partition non-interactively
    echo -e "n\np\n1\n\n\nw" | fdisk "$DEVICE" || true
    
    # Inform kernel of partition table changes
    partprobe "$DEVICE" 2>/dev/null || blockdev --rereadpt "$DEVICE" 2>/dev/null || true
    sleep 2
    
    echo "🔧 Formatting $PARTITION as ext4..."
    mkfs.ext4 -L "$LABEL" "$PARTITION"
    
    echo "✅ Partition created and formatted"
fi

# Create mount point
mkdir -p "$MOUNT_POINT"

# Check if already mounted
if mountpoint -q "$MOUNT_POINT"; then
    echo "✅ $MOUNT_POINT is already mounted"
else
    echo "📁 Mounting $PARTITION to $MOUNT_POINT..."
    mount "$PARTITION" "$MOUNT_POINT"
    systemctl daemon-reload 2>/dev/null || true
    echo "✅ Mounted successfully"
fi

# Add to fstab if not already present
if grep -q "$PARTITION.*$MOUNT_POINT" /etc/fstab; then
    echo "✅ $PARTITION already in /etc/fstab"
else
    echo "📝 Adding $PARTITION to /etc/fstab for persistent mounting..."
    echo "$PARTITION $MOUNT_POINT ext4 defaults 0 2" >> /etc/fstab
    echo "✅ Added to /etc/fstab"
fi

# Verify mount
echo ""
echo "✅ Verification:"
df -h "$MOUNT_POINT"
echo ""

# ============================================================================
# Setup Database Directories
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Setting Up Database Directories"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create directory structure for databases
echo "📁 Creating database directories..."
mkdir -p /data/{postgresql,influxdb,docker}
mkdir -p /data/docker/volumes

# Set initial permissions (will be updated by services during installation)
chmod 755 /data
chmod 755 /data/{postgresql,influxdb,docker}

echo "✅ Database directories created:"
echo "   • /data/postgresql  → PostgreSQL/Supabase data"
echo "   • /data/influxdb    → InfluxDB time-series data"
echo "   • /data/docker      → Docker volumes and containers"

echo ""

# ============================================================================
# Summary
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Database Disk Preparation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Current mount status:"
df -h | grep -E "Filesystem|/data"
echo ""
echo "📝 /etc/fstab entry:"
grep "/data" /etc/fstab || echo "   (none found)"
echo ""
echo "📦 Database directories:"
ls -la /data/ 2>/dev/null | grep -E "postgresql|influxdb|docker" || echo "   Creating..."
echo ""
echo "✅ Next steps:"
echo "   1. Mount shared code repository (NFS from Storage VM):"
echo "      cd ~/virtualpytest/setup/proxmox/vm/shared"
echo "      sudo bash mount_nfs_shared.sh"
echo ""
echo "   2. Install database services:"
echo "      cd /shared/code/virtualpytest/setup/local/linux/database"
echo "      sudo ./install_db.sh"
echo ""
