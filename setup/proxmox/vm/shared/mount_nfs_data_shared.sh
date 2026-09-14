#!/bin/bash

# VirtualPyTest - Mount NFS Data + Shared Directories
# Mounts both /data (rw) and /shared (ro) directories from Storage VM
# Must be run as root on Backend Server and Backend Host VMs

set -e

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the VM"
   echo "Usage: sudo ./mount_nfs_data_shared.sh"
   exit 1
fi

echo "🔗 VirtualPyTest - Mounting Full Storage Access"

# Create mount points
sudo mkdir -p /mnt/data /mnt/shared

# Mount data directory (read-write)
echo "📁 Mounting data directory (read-write)..."
sudo mount "192.168.0.100:/data" /mnt/data

# Mount shared directory (read-only)
echo "📁 Mounting shared directory (read-only)..."
sudo mount "192.168.0.100:/shared" /mnt/shared

# Add to fstab for persistence
echo "192.168.0.100:/data /mnt/data nfs defaults 0 0" >> /etc/fstab
echo "192.168.0.100:/shared /mnt/shared nfs ro,defaults 0 0" >> /etc/fstab

echo "✅ Full storage mount complete!"
echo "📂 Data (rw): /mnt/data"
echo "📂 Shared (ro): /mnt/shared"