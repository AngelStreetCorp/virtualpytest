#!/bin/bash

# VirtualPyTest - Create and Mount Data Disk for Backend Host VM
# Prepares a dedicated disk for the Backend Host VM and mounts it at /data
# (for recordings, screenshots, logs, artifacts).
#
# Disk selection (in order):
#   1. Positional arg:        sudo ./create_disk_partition.sh /dev/nvme1n1
#   2. /data already mounted: partition phase is skipped (dirs only)
#   3. Auto-detect:           largest non-root block device with no mounted
#                             partitions (handles sdb, nvme1n1, vdb, mmcblk1)
#
# Run as: sudo ./create_disk_partition.sh [device]

set -e

DEVICE_OVERRIDE="${1:-}"

echo "💽 VirtualPyTest - Preparing Data Disk for Backend Host VM"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "This script will:"
echo "   • Pick or use the supplied data disk"
echo "   • Create a partition + ext4 filesystem (if not already there)"
echo "   • Mount it to /data + add /etc/fstab entry"
echo "   • Create host data directories"
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

# Partition device naming differs between legacy SCSI/SATA (sdb → sdb1) and
# NVMe/loop/mmc (nvme1n1 → nvme1n1p1). Single helper so the rest of the script
# stays disk-family agnostic.
partition_name_for() {
    local dev="$1"
    case "$dev" in
        /dev/nvme*|/dev/loop*|/dev/mmcblk*) echo "${dev}p1" ;;
        *)                                   echo "${dev}1" ;;
    esac
}

# Walk the LVM/dm symlinks up to the underlying physical block device that
# backs the OS root, so auto-detection never proposes wiping the OS disk.
root_block_device() {
    local root_src pk
    root_src=$(findmnt -no SOURCE / 2>/dev/null || true)
    [ -z "$root_src" ] && return 0
    pk=$(lsblk -no PKNAME "$root_src" 2>/dev/null | head -1)
    [ -n "$pk" ] && echo "/dev/$pk"
}

# Auto-detect: pick the largest non-root disk whose partitions are all
# unmounted. Returns empty if no candidate found.
auto_detect_data_disk() {
    local root_dev candidate best_size best_dev
    root_dev=$(root_block_device)
    best_size=0
    best_dev=""
    while read -r name size type; do
        [ "$type" = "disk" ] || continue
        candidate="/dev/$name"
        [ "$candidate" = "$root_dev" ] && continue
        # Skip disk if any of its partitions are currently mounted
        if lsblk -no MOUNTPOINT "$candidate" 2>/dev/null | grep -qv '^$'; then
            continue
        fi
        if [ "$size" -gt "$best_size" ]; then
            best_size=$size
            best_dev=$candidate
        fi
    done < <(lsblk -dnb -o NAME,SIZE,TYPE)
    [ -n "$best_dev" ] && echo "$best_dev"
}

# Function to setup disk partition
setup_disk_partition() {
    local device=$1
    local partition
    partition=$(partition_name_for "$device")
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
# Pick + setup the /data disk
# ============================================================================
echo ""

if mountpoint -q /data 2>/dev/null; then
    DATA_SOURCE=$(findmnt -no SOURCE /data 2>/dev/null || echo "?")
    echo "✅ /data is already mounted ($DATA_SOURCE) — skipping partition phase"
    echo "   Continuing with host data directory creation only."
elif [ -n "$DEVICE_OVERRIDE" ]; then
    echo "📦 Using disk supplied on command line: $DEVICE_OVERRIDE"
    if ! setup_disk_partition "$DEVICE_OVERRIDE" "/data" "hostdata"; then
        echo "⚠️  Failed to setup /data disk on $DEVICE_OVERRIDE"
        echo "   Continue anyway? (y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    DATA_DISK=$(auto_detect_data_disk)
    if [ -z "$DATA_DISK" ]; then
        echo "⚠️  No candidate data disk found (no unmounted secondary disk)."
        echo "   • If you have a data disk, pass it explicitly:"
        echo "       sudo $0 /dev/sdb        (or /dev/nvme1n1, /dev/vdb, ...)"
        echo "   • If this host has no dedicated data disk, the installer will"
        echo "     fall back to the OS partition automatically."
        echo "   Continue anyway? (y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "🔍 Auto-detected candidate data disk: $DATA_DISK"
        lsblk "$DATA_DISK" || true
        echo ""
        if ! setup_disk_partition "$DATA_DISK" "/data" "hostdata"; then
            echo "⚠️  Failed to setup /data disk on $DATA_DISK"
            echo "   Continue anyway? (y/N)"
            read -r response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
fi

# ============================================================================
# Create Host Data Directories
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📁 Creating Host Data Directories"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create subdirectories for host data
echo "📋 Creating data directories..."
mkdir -p /data/recordings
mkdir -p /data/screenshots
mkdir -p /data/logs
mkdir -p /data/temp
mkdir -p /data/artifacts

# Set permissions
echo ""
echo "🔐 Setting directory permissions..."
chmod 755 /data
chmod 755 /data/recordings
chmod 755 /data/screenshots
chmod 755 /data/logs
chmod 755 /data/temp
chmod 755 /data/artifacts

echo "   • /data: rwxr-xr-x (read-write for host services)"
echo "   • Subdirectories: rwxr-xr-x (accessible to host processes)"

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Disk Preparation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Current mount status:"
df -h | grep -E "Filesystem|/data"
echo ""
echo "📝 /etc/fstab entries:"
grep -E "/data" /etc/fstab || echo "   (none found)"
echo ""
echo "📁 Host data directories:"
ls -la /data | grep -E "^d" | head -10
echo ""
echo "✅ Next step: Install host services"
echo "   cd ~/virtualpytest/setup/local/linux/host"
echo "   sudo ./install_host.sh"
echo ""
echo "   Then test host services:"
echo "   cd ~/virtualpytest/setup/local/linux/host"
echo "   ./test_host.sh"
echo ""