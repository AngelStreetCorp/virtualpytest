#!/bin/bash

# VirtualPyTest - Create and Mount Storage Disks for Proxmox VMs
# This script prepares dedicated disks for the Storage VM:
#   - /dev/sdb → /data (for MinIO and Redis data)
#   - /dev/sdc → /shared (for shared code repository)
#
# Usage: Run this BEFORE install_storage.sh on Proxmox Storage VM
# Run as: sudo ./create_disks_partitions.sh

set -e

echo "💽 VirtualPyTest - Preparing Storage Disks for Proxmox VM"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "This script will:"
echo "   • Create partition on /dev/sdb → mount to /data"
echo "   • Create partition on /dev/sdc → mount to /shared"
echo "   • Format partitions as ext4"
echo "   • Add entries to /etc/fstab for persistent mounting"
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

# Function to setup disk partition
setup_disk_partition() {
    local device=$1
    local partition="${device}1"
    local mount_point=$2
    local label=$3
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📦 Setting up $device → $mount_point"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Check if device exists
    if [ ! -b "$device" ]; then
        echo "❌ Device $device not found!"
        echo "   Please ensure the disk is attached in Proxmox:"
        echo "   1. Go to VM → Hardware"
        echo "   2. Add → Hard Disk"
        echo "   3. Attach disk as $device"
        return 1
    fi
    
    echo "✅ Found $device"
    
    # Show disk info
    echo "📊 Disk information:"
    lsblk "$device" || true
    echo ""
    
    # Check if partition already exists
    if [ -b "$partition" ]; then
        echo "✅ Partition $partition already exists"
    else
        echo "📦 Creating partition on $device..."
        echo "   This will:"
        echo "   • Create a single partition using entire disk"
        echo "   • Set partition type to Linux LVM (8e)"
        
        # Create partition non-interactively
        # n = new partition
        # p = primary
        # 1 = partition number
        # (default) = first sector
        # (default) = last sector
        # t = change partition type
        # 8e = Linux LVM
        # w = write changes
        echo -e "n\np\n1\n\n\nt\n8e\nw" | fdisk "$device" || true
        
        # Inform kernel of partition table changes
        partprobe "$device" 2>/dev/null || blockdev --rereadpt "$device" 2>/dev/null || true
        sleep 2
        
        echo "🔧 Formatting $partition as ext4..."
        mkfs.ext4 -L "$label" "$partition"
        
        echo "✅ Partition created and formatted"
    fi
    
    # Create mount point
    mkdir -p "$mount_point"
    
    # Check if already mounted
    if mountpoint -q "$mount_point"; then
        echo "✅ $mount_point is already mounted"
    else
        echo "📁 Mounting $partition to $mount_point..."
        mount "$partition" "$mount_point"
        systemctl daemon-reload 2>/dev/null || true
        echo "✅ Mounted successfully"
    fi
    
    # Add to fstab if not already present
    if grep -q "$partition.*$mount_point" /etc/fstab; then
        echo "✅ $partition already in /etc/fstab"
    else
        echo "📝 Adding $partition to /etc/fstab for persistent mounting..."
        echo "$partition $mount_point ext4 defaults 0 2" >> /etc/fstab
        echo "✅ Added to /etc/fstab"
    fi
    
    # Verify mount
    echo ""
    echo "✅ Verification:"
    df -h "$mount_point"
    echo ""
    
    return 0
}

# ============================================================================
# Setup /data disk (sdb)
# ============================================================================
echo ""
if ! setup_disk_partition "/dev/sdb" "/data" "data"; then
    echo "⚠️  Failed to setup /data disk"
    echo "   Continue anyway? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ============================================================================
# Setup /shared disk (sdc)
# ============================================================================
echo ""
if ! setup_disk_partition "/dev/sdc" "/shared" "shared"; then
    echo "⚠️  Failed to setup /shared disk"
    echo "   Continue anyway? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ============================================================================
# Setup Shared Code Repository
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Setting Up Shared Code Repository"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get script directory and source root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Check if code already exists in /shared/code/virtualpytest
if [ -d "/shared/code/virtualpytest" ]; then
    echo "✅ Code repository already exists at /shared/code/virtualpytest"
else
    echo "📋 Copying code to /shared/code/virtualpytest (source of truth)..."
    mkdir -p /shared/code
    
    # Copy from current location to shared
    cp -r "$SOURCE_ROOT" /shared/code/virtualpytest
    
    # Set ownership for NFS sharing
    chown -R nobody:nogroup /shared/code
    
    # Set read-execute only permissions (no write)
    # This prevents VMs from accidentally modifying the source code
    chmod -R 555 /shared/code
    
    echo "✅ Code repository created at /shared/code/virtualpytest"
    echo "   This becomes the source of truth for all VMs"
    echo "   Permissions: read-execute only (no write)"
fi

# Set /data permissions for read-write
echo ""
echo "🔐 Setting directory permissions..."
chmod 755 /data
echo "   • /data: rwxr-xr-x (read-write for services)"
echo "   • /shared/code: r-xr-xr-x (read-execute only)"

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Disk Preparation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Current mount status:"
df -h | grep -E "Filesystem|/data|/shared"
echo ""
echo "📝 /etc/fstab entries:"
grep -E "/data|/shared" /etc/fstab || echo "   (none found)"
echo ""
echo "📦 Shared code repository:"
if [ -d "/shared/code/virtualpytest" ]; then
    echo "   ✅ /shared/code/virtualpytest (source of truth)"
    du -sh /shared/code/virtualpytest 2>/dev/null || echo "   Size: (calculating...)"
else
    echo "   ⚠️  Not found"
fi
echo ""
echo "✅ Next step: Setup NFS server"
echo "   cd ~/virtualpytest/setup/proxmox/vm/storage"
echo "   sudo bash storage_setup_nfs_server.sh"
echo ""
echo "   Then install storage services:"
echo "   cd ~/virtualpytest/setup/local/linux/storage"
echo "   sudo ./install_storage.sh"
echo ""
