#!/bin/bash

# VirtualPyTest - Proxmox Host Prerequisites Setup
# This script sets up the Proxmox host with base tools and networking
# Must be run as root on the Proxmox host
# Note: NFS server has been moved to Storage VM

set -e

echo "🏠 VirtualPyTest - Installing Proxmox Host Prerequisites"
echo "   • System updates and base tools"
echo "   • Network configuration and tools"
echo "   • SSH key setup for VM access"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the Proxmox host"
   echo "Usage: sudo ./install_prerequisites_host.sh"
   exit 1
fi

# Fix IPv6 issues by preferring IPv4 for apt
echo "🔧 Configuring apt to prefer IPv4 over IPv6..."
echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# System update (with IPv4 preference)
echo "📦 Updating system packages..."
apt update
if [ $? -ne 0 ]; then
    echo "⚠️ apt update failed, trying with IPv4-only..."
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
    apt update
fi
apt upgrade -y

# Install base tools
echo "📦 Installing base tools..."
apt install -y curl wget nano htop net-tools git dnsutils lsof sudo

# Configure PATH
export PATH=$PATH:/usr/sbin:/sbin

# Setup SSH key for VM access
echo "🔑 Setting up SSH key for VM access..."

# Create .ssh directory if it doesn't exist
mkdir -p /root/.ssh
chmod 700 /root/.ssh

# Generate SSH key if it doesn't exist
if [ ! -f /root/.ssh/id_ed25519 ]; then
    ssh-keygen -t ed25519 -C "proxmox@virtualpytest" -f /root/.ssh/id_ed25519 -N ""
    echo "✅ Generated SSH key: /root/.ssh/id_ed25519"
else
    echo "✅ SSH key already exists"
fi

# Display public key for copying to VMs
echo ""
echo "📋 SSH Public Key (copy this to VMs for passwordless access):"
echo "--------------------------------------------------------------------------------"
cat /root/.ssh/id_ed25519.pub
echo "--------------------------------------------------------------------------------"

echo ""
echo "🎉 Proxmox Host prerequisites setup complete!"
echo ""
echo "🔑 SSH Access Details:"
echo "   • Private key: /root/.ssh/id_ed25519"
echo "   • Public key: /root/.ssh/id_ed25519.pub"
echo "   • Use this key to setup passwordless SSH to VMs"
echo ""
echo "📋 Next Steps:"
echo "   1. Setup Storage VM FIRST (see vm-storage-overview.md):"
echo "      - sudo ./setup/proxmox/vm/scripts/storage_create_disks_partitions.sh"
echo "      - sudo ./setup/proxmox/vm/scripts/storage_setup_nfs_server.sh"
echo "   2. Create other VMs and run: ./setup/proxmox/vm/scripts/install_prerequisites_proxmox_vm.sh"
echo "   3. Configure NFS mounts: ./setup/proxmox/vm/scripts/mount_nfs_shared.sh"
echo "   4. Clone VM as template for other services"