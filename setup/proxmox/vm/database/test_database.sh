#!/bin/bash

# VirtualPyTest - Test Database VM Infrastructure
# Tests ONLY infrastructure setup (disk, mount, directories)
# Does NOT test database services (PostgreSQL, InfluxDB) - use local test for that

echo "🧪 VirtualPyTest - Testing Database VM Infrastructure"
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
# Test 1: Database Disk Mount
# ============================================================================
echo "📦 Test 1: Database Disk & Mount"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check /data mount
if mountpoint -q /data 2>/dev/null; then
    success "/data is mounted"
    DISK_INFO=$(df -h /data | awk 'NR==2 {print $1, $2, $5}')
    info "$DISK_INFO"
else
    error "/data is NOT mounted"
    info "Run: sudo bash create_disk_partition.sh"
fi

# Check fstab entry
if grep -q "/data" /etc/fstab 2>/dev/null; then
    success "/data is in /etc/fstab (persistent)"
else
    warning "/data not in /etc/fstab (won't persist on reboot)"
fi

echo ""

# ============================================================================
# Test 2: Database Directories
# ============================================================================
echo "📦 Test 2: Database Directories"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check PostgreSQL directory
if [ -d "/data/postgresql" ]; then
    success "/data/postgresql exists"
else
    error "/data/postgresql NOT found"
    info "Run: sudo bash create_disk_partition.sh"
fi

# Check InfluxDB directory
if [ -d "/data/influxdb" ]; then
    success "/data/influxdb exists"
else
    error "/data/influxdb NOT found"
    info "Run: sudo bash create_disk_partition.sh"
fi

# Check Docker directory
if [ -d "/data/docker" ]; then
    success "/data/docker exists"
    if [ -d "/data/docker/volumes" ]; then
        success "/data/docker/volumes exists"
    else
        warning "/data/docker/volumes NOT found"
    fi
else
    error "/data/docker NOT found"
    info "Run: sudo bash create_disk_partition.sh"
fi

echo ""

# ============================================================================
# Test 3: NFS Shared Code Mount (Optional)
# ============================================================================
echo "📦 Test 3: Shared Code Repository (NFS)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if mountpoint -q /shared 2>/dev/null; then
    success "/shared is mounted (NFS from Storage VM)"
    
    if [ -d "/shared/code/virtualpytest" ]; then
        success "/shared/code/virtualpytest accessible"
        
        if [ -f "/shared/code/virtualpytest/setup/local/linux/database/install_db.sh" ]; then
            success "Database installer found"
        else
            warning "Database installer not found in shared code"
        fi
    else
        warning "/shared/code/virtualpytest not found"
    fi
else
    warning "/shared is NOT mounted"
    info "Optional: Mount NFS share from Storage VM"
    info "Run: cd ~/virtualpytest/setup/proxmox/vm/shared && sudo bash mount_nfs_shared.sh"
fi

echo ""

# ============================================================================
# Test 4: Disk Space
# ============================================================================
echo "📦 Test 4: Disk Space"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

DATA_USAGE=$(df -h /data | awk 'NR==2 {print $5}' | sed 's/%//')
DATA_AVAIL=$(df -h /data | awk 'NR==2 {print $4}')
DATA_SIZE=$(df -h /data | awk 'NR==2 {print $2}')

if [ "$DATA_USAGE" -lt 90 ]; then
    success "/data has sufficient space (${DATA_USAGE}% used, ${DATA_AVAIL} available)"
    info "Total size: $DATA_SIZE"
else
    warning "/data is running low on space (${DATA_USAGE}% used)"
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
    echo "✅ Database VM Infrastructure:"
    echo "   • Disk mount: READY"
    echo "   • Database directories: READY"
    echo "   • Shared code: $(mountpoint -q /shared && echo "READY" || echo "Optional")"
    echo ""
    echo "📋 Next Steps:"
    if ! mountpoint -q /shared 2>/dev/null; then
        echo "   1. Mount shared code (optional):"
        echo "      cd ~/virtualpytest/setup/proxmox/vm/shared"
        echo "      sudo bash mount_nfs_shared.sh"
        echo ""
    fi
    echo "   2. Install database services:"
    echo "      cd /shared/code/virtualpytest/setup/local/linux/database"
    echo "      sudo ./install_db.sh"
    echo ""
    echo "   3. Test services:"
    echo "      cd /shared/code/virtualpytest/setup/local/linux/database"
    echo "      ./test_db.sh"
    echo ""
    exit 0
else
    error "SOME TESTS FAILED! (Passed: $PASSED, Failed: $FAILED)"
    echo ""
    echo "⚠️  Please check the errors above and run the appropriate script:"
    echo "   • For disk mount: sudo bash create_disk_partition.sh"
    echo "   • For shared code: cd ~/virtualpytest/setup/proxmox/vm/shared && sudo bash mount_nfs_shared.sh"
    echo ""
    exit 1
fi
