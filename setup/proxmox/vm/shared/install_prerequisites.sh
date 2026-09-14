#!/bin/bash

# VirtualPyTest - Proxmox VM Prerequisites Setup
# This script sets up Debian VMs with VirtualPyTest prerequisites
# Must be run as root on each VM

set -e

echo "🖥️ VirtualPyTest - Installing Proxmox VM Prerequisites"
echo "   • System updates and base tools"
echo "   • VirtualPyTest service account (vpt_user)"
echo "   • Development tools"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges on the VM"
   echo "Usage: sudo ./install_prerequisites_proxmox_vm.sh"
   exit 1
fi

# Fix IPv6 issues by preferring IPv4 for apt
#echo "🔧 Configuring apt to prefer IPv4 over IPv6..."
#echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# System update (with IPv4 preference)
echo "📦 Updating system packages..."
apt update
if [ $? -ne 0 ]; then
    echo "⚠️ apt update failed, trying with IPv4-only..."
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
    apt update
fi
apt upgrade -y

# Install sudo if not present
echo "🔧 Installing sudo..."
apt install -y sudo

# Install base tools with error handling
echo "📦 Installing base tools..."
if ! apt install -y curl wget nano htop net-tools git dnsutils lsof nfs-common rsync; then
    echo "⚠️ First attempt failed, retrying with IPv4 preference..."
    echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4
    apt update
    apt install -y curl wget nano htop net-tools git dnsutils lsof nfs-common rsync
fi

# Configure PATH
    export PATH=$PATH:/usr/sbin:/sbin

# Create VirtualPyTest service account (vpt_user)
echo "👤 Creating VirtualPyTest service account..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/create_vpt_user.sh" ]; then
    bash "$SCRIPT_DIR/create_vpt_user.sh"
else
    echo "❌ create_vpt_user.sh script not found in $SCRIPT_DIR"
    exit 1
fi

echo ""
echo "🎉 VM prerequisites setup complete!"
echo ""
echo "📋 Next Steps:"
echo "   1. Mount NFS share: ./setup/proxmox/vm/scripts/mount_nfs_shared.sh"
echo "   2. Install service-specific software (e.g., ./setup/local/install_server.sh)"
echo ""
echo "🔧 VM is ready for VirtualPyTest service installation!"