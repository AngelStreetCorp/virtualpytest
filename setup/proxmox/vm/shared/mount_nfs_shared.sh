#!/bin/bash

# VirtualPyTest - Mount NFS Shared Directory (Read-Only)
# Mounts /shared directory from Storage VM for VMs that only need code access
# Must be run as root on Frontend, Monitoring, Database, Reverse Proxy VMs

set -e

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the VM"
   echo "Usage: sudo ./mount_nfs_shared.sh"
   exit 1
fi

echo "🔗 VirtualPyTest - Mounting Shared Storage (Read-Only)"

# Create mount point and mount shared directory (read-only)
sudo mkdir -p /mnt/shared
sudo mount "192.168.0.100:/shared" /mnt/shared

# Add to fstab for persistence (read-only)
echo "192.168.0.100:/shared /mnt/shared nfs ro,defaults 0 0" >> /etc/fstab

echo "✅ Shared storage mount complete!"
echo "📂 Codebase available at: /mnt/shared (read-only)"