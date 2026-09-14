#!/bin/bash

# VirtualPyTest - Setup NFS Server for Storage VM
# This script sets up NFS server and configures exports
# Must be run as root on the Storage VM (192.168.0.100)
# 
# Prerequisites:
#   1. Disk partitions created: ./create_disks_partitions.sh
#   2. Storage services installed: ~/virtualpytest/setup/local/linux/storage/install_storage.sh

set -e

echo "🔗 VirtualPyTest - Setting up NFS Server"
echo "   • Install and configure NFS server"
echo "   • Setup tiered access permissions"
echo "   • Configure and export NFS shares"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the Storage VM"
   echo "Usage: sudo ./storage_setup_nfs_server.sh"
   exit 1
fi

# Verify prerequisites
echo "🔍 Verifying prerequisites..."

# Check if /data exists (mounted or directory)
if [ ! -d "/data" ]; then
    echo "❌ /data directory not found!"
    echo "   Please run disk setup first: sudo ./create_disks_partitions.sh"
    exit 1
fi

# Check if /shared exists (mounted or directory)
if [ ! -d "/shared" ]; then
    echo "❌ /shared directory not found!"
    echo "   Please run disk setup first: sudo ./create_disks_partitions.sh"
    exit 1
fi

# Check if code repository exists
if [ ! -d "/shared/code/virtualpytest" ]; then
    echo "❌ /shared/code/virtualpytest not found!"
    echo "   Please run storage installer first:"
    echo "   cd ~/virtualpytest/setup/local/linux/storage"
    echo "   sudo ./install_storage.sh"
    exit 1
fi

echo "✅ Prerequisites verified"
echo "   • /data: $(df -h /data | awk 'NR==2 {print $2}' || echo 'exists')"
echo "   • /shared: $(df -h /shared | awk 'NR==2 {print $2}' || echo 'exists')"
echo "   • Code repository: /shared/code/virtualpytest"
echo ""

# Install NFS server components if not already installed
echo "📦 Installing NFS server components..."
apt update
apt install -y nfs-kernel-server rpcbind

# Configure NFS exports with tiered permissions
echo "⚙️ Configuring NFS exports with tiered permissions..."

# Clean up any existing VirtualPyTest exports (old format)
sed -i '/\/srv\/shared\/virtualpytest/d' /etc/exports
sed -i '/\/data/d' /etc/exports
sed -i '/\/shared/d' /etc/exports

# Add new tiered exports with proper permissions
echo "/data 192.168.0.103(rw,sync,no_subtree_check,no_root_squash)" >> /etc/exports      # Backend Server only
echo "/data 192.168.0.140/28(rw,sync,no_subtree_check,no_root_squash)" >> /etc/exports  # Backend Host range only
echo "/shared 192.168.0.0/24(ro,sync,no_subtree_check,no_root_squash)" >> /etc/exports  # All VMs: read-only
echo "✅ Added tiered NFS exports to /etc/exports"

# Configure permissions for shared code directory
echo "🔒 Setting up permissions for /shared/code..."
sudo chmod 755 /shared/code
# → drwxr-xr-x   (owner full, group/other: read + execute)

# 2. Apply recursively to all subfolders (same permissions)
sudo find /shared/code -type d -exec chmod 755 {} +

# 3. Make files readable + executable by everyone
#    (safest for shared tools/code — everyone can run what's there)
sudo find /shared/code -type f -exec chmod 755 {} +
echo "✅ Permissions configured for /shared/code"

# Export the filesystem
echo "🚀 Exporting NFS filesystem..."
exportfs -ra

# Enable and start NFS services
echo "🚀 Enabling and starting NFS services..."
systemctl enable --now nfs-kernel-server rpcbind 

# Wait a moment for services to start
sleep 2

# Verify NFS server is running
echo "🔍 Verifying NFS server..."
if systemctl is-active --quiet nfs-kernel-server; then
    echo "✅ NFS server is running"
else
    echo "❌ NFS server failed to start"
    echo "   Check: sudo systemctl status nfs-kernel-server"
    exit 1
fi

# Test NFS export
echo "🔍 Testing NFS export..."
if showmount -e 127.0.0.1 | grep -q "/data\|/shared"; then
    echo "✅ NFS exports are available:"
    showmount -e 127.0.0.1
else
    echo "❌ NFS exports not found"
    echo "   Check exports: sudo showmount -e 127.0.0.1"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ NFS Server Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 NFS Share Details:"
echo "   • /data (192.168.0.103, 192.168.0.140/28): read-write"
echo "     → MinIO data, Redis data"
echo "   • /shared (192.168.0.0/24): read-only"
echo "     → Shared code repository at /shared/code/virtualpytest"
echo ""
echo "📊 Available Resources:"
echo "   • Code repository: /shared/code/virtualpytest"
echo "   • MinIO data: /data/minio"
echo "   • Redis data: /data/redis"
echo ""
echo "📋 Next Steps:"
echo "   1. Install storage services on this VM:"
echo "      cd ~/virtualpytest/setup/local/linux/storage"
echo "      sudo ./install_storage.sh"
echo ""
echo "   2. Mount NFS shares on other VMs:"
echo "      • Backend Server/Host: sudo ./mount_nfs_data_shared.sh"
echo "      • Other VMs: sudo ./mount_nfs_shared.sh"
echo ""
echo "🔧 Management Commands:"
echo "   • View exports: sudo showmount -e 127.0.0.1"
echo "   • Reload exports: sudo exportfs -ra"
echo "   • Check mounted: sudo exportfs -v"
echo "   • NFS status: sudo systemctl status nfs-kernel-server"
echo ""