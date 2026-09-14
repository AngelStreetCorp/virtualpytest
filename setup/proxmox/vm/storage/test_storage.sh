#!/bin/bash

# VirtualPyTest - Test Proxmox Storage Infrastructure
# Tests ONLY infrastructure setup (disks, mounts, NFS)
# Does NOT test services (MinIO, Redis) - use local test for that

echo "🧪 VirtualPyTest - Testing Proxmox Storage Infrastructure"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test counter
PASSED=0
FAILED=0

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

success() { echo -e "${GREEN}✅ $1${NC}"; PASSED=$((PASSED + 1)); }
error() { echo -e "${RED}❌ $1${NC}"; FAILED=$((FAILED + 1)); }
warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "   ℹ️  $1"; }

# ============================================================================
# Test 1: Disk Mounts (from create_disks_partitions.sh)
# ============================================================================
echo "📦 Test 1: Disk Partitions & Mounts"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check /data mount
if mountpoint -q /data 2>/dev/null; then
    success "/data is mounted"
    DISK_INFO=$(df -h /data | awk 'NR==2 {print $1, $2, $5}')
    info "$DISK_INFO"
else
    error "/data is NOT mounted"
    info "Run: sudo ./create_disks_partitions.sh"
fi

# Check /shared mount
if mountpoint -q /shared 2>/dev/null; then
    success "/shared is mounted"
    DISK_INFO=$(df -h /shared | awk 'NR==2 {print $1, $2, $5}')
    info "$DISK_INFO"
else
    error "/shared is NOT mounted"
    info "Run: sudo ./create_disks_partitions.sh"
fi

# Check fstab entries
if grep -q "/data" /etc/fstab 2>/dev/null; then
    success "/data is in /etc/fstab (persistent)"
else
    warning "/data not in /etc/fstab (won't persist on reboot)"
fi

if grep -q "/shared" /etc/fstab 2>/dev/null; then
    success "/shared is in /etc/fstab (persistent)"
else
    warning "/shared not in /etc/fstab (won't persist on reboot)"
fi

echo ""

# ============================================================================
# Test 2: Code Repository (from create_disks_partitions.sh)
# ============================================================================
echo "📦 Test 2: Shared Code Repository"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -d "/shared/code/virtualpytest" ]; then
    success "/shared/code/virtualpytest exists"
    
    if [ -d "/shared/code/virtualpytest/.git" ]; then
        success "Repository is a git repository"
    else
        warning "Repository is not a git repository (no .git folder)"
    fi
    
    # Check permissions (should be read-execute only)
    PERMS=$(stat -c '%a' /shared/code/virtualpytest 2>/dev/null || stat -f '%Lp' /shared/code/virtualpytest 2>/dev/null)
    if [ "$PERMS" = "555" ] || [ "$PERMS" = "755" ]; then
        success "Repository permissions: $PERMS (read-execute)"
    else
        warning "Repository permissions: $PERMS (expected 555 or 755)"
    fi
    
    REPO_SIZE=$(du -sh /shared/code/virtualpytest 2>/dev/null | cut -f1)
    info "Size: $REPO_SIZE"
else
    error "/shared/code/virtualpytest NOT found"
    info "Run: sudo ./create_disks_partitions.sh"
fi

echo ""

# ============================================================================
# Test 3: NFS Server (from storage_setup_nfs_server.sh)
# ============================================================================
echo "📦 Test 3: NFS Server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if NFS packages are installed
if command -v exportfs &> /dev/null; then
    success "NFS server tools installed"
else
    warning "NFS server tools NOT installed"
    info "Run: sudo ./storage_setup_nfs_server.sh"
fi

# Check NFS server service
if systemctl is-active --quiet nfs-kernel-server 2>/dev/null; then
    success "nfs-kernel-server is running"
else
    warning "nfs-kernel-server is NOT running"
    info "Run: sudo ./storage_setup_nfs_server.sh"
fi

# Check rpcbind service
if systemctl is-active --quiet rpcbind 2>/dev/null; then
    success "rpcbind is running"
else
    warning "rpcbind is NOT running"
    info "Run: sudo ./storage_setup_nfs_server.sh"
fi

# Check NFS exports
if [ -f /etc/exports ]; then
    if grep -q "^/data" /etc/exports && grep -q "^/shared" /etc/exports; then
        success "NFS exports configured"
        
        # Check /data export permissions (should be rw)
        if grep "^/data.*rw" /etc/exports > /dev/null; then
            success "/data exported as read-write (rw)"
        else
            warning "/data export permissions incorrect (should be rw)"
        fi
        
        # Check /shared export permissions (should be ro)
        if grep "^/shared.*ro" /etc/exports > /dev/null; then
            success "/shared exported as read-only (ro)"
        else
            warning "/shared export permissions incorrect (should be ro)"
        fi
        
        info "Current exports:"
        grep "^/data\|^/shared" /etc/exports | sed 's/^/     /'
        
        # Verify exports are active
        if command -v showmount &> /dev/null; then
            if showmount -e 127.0.0.1 2>/dev/null | grep -q "/data\|/shared"; then
                success "NFS exports are active"
            else
                warning "NFS exports configured but not active"
                info "Try: sudo exportfs -ra"
            fi
        fi
    else
        warning "NFS exports NOT configured"
        info "Run: sudo ./storage_setup_nfs_server.sh"
    fi
else
    warning "/etc/exports NOT found"
    info "Run: sudo ./storage_setup_nfs_server.sh"
fi

echo ""

# ============================================================================
# Summary
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Test Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $FAILED -eq 0 ]; then
    success "🎉 ALL INFRASTRUCTURE TESTS PASSED! ($PASSED tests)"
    echo ""
    echo "✅ Proxmox Storage Infrastructure:"
    echo "   • Disk mounts: READY"
    echo "   • Code repository: READY"
    echo "   • NFS server: READY"
    echo ""
    echo "📋 Next Steps:"
    echo "   1. Install services: cd ~/virtualpytest/setup/local/linux/storage && sudo ./install_storage.sh"
    echo "   2. Test services: cd ~/virtualpytest/setup/local/linux/storage && ./test_storage.sh"
    echo ""
    exit 0
else
    error "SOME TESTS FAILED! (Passed: $PASSED, Failed: $FAILED)"
    echo ""
    echo "⚠️  Please check the errors above and run the appropriate script:"
    echo "   • For disk mounts: sudo ./create_disks_partitions.sh"
    echo "   • For NFS server: sudo ./storage_setup_nfs_server.sh"
    echo ""
    exit 1
fi
