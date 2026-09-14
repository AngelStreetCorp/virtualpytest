#!/bin/bash

# VirtualPyTest - Test Proxmox Backend Host Infrastructure
# Tests ONLY infrastructure setup (disk mount, directories)
# Does NOT test services - use local test for that

echo "🧪 VirtualPyTest - Testing Proxmox Backend Host Infrastructure"
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
# Test 1: Disk Mount (from create_disk_partition.sh)
# ============================================================================
echo "📦 Test 1: Disk Partition & Mount"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check /data mount
if mountpoint -q /data 2>/dev/null; then
    success "/data is mounted"
    DISK_INFO=$(df -h /data | awk 'NR==2 {print $1, $2, $5}')
    info "$DISK_INFO"
else
    error "/data is NOT mounted"
    info "Run: sudo ./create_disk_partition.sh"
fi

# Check fstab entry
if grep -q "/data" /etc/fstab 2>/dev/null; then
    success "/data is in /etc/fstab (persistent)"
else
    warning "/data not in /etc/fstab (won't persist on reboot)"
fi

echo ""

# ============================================================================
# Test 2: Host Data Directories (from create_disk_partition.sh)
# ============================================================================
echo "📦 Test 2: Host Data Directories"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

HOST_DIRS=("/data/recordings" "/data/screenshots" "/data/logs" "/data/temp" "/data/artifacts")

for dir in "${HOST_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        success "$dir exists"

        # Check permissions (should be 755)
        PERMS=$(stat -c '%a' "$dir" 2>/dev/null || stat -f '%Lp' "$dir" 2>/dev/null)
        if [ "$PERMS" = "755" ]; then
            success "$dir permissions: $PERMS (rwxr-xr-x)"
        else
            warning "$dir permissions: $PERMS (expected 755)"
        fi
    else
        error "$dir NOT found"
        info "Run: sudo ./create_disk_partition.sh"
    fi
done

echo ""

# ============================================================================
# Test 3: Disk Space
# ============================================================================
echo "📦 Test 3: Disk Space & Usage"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if mountpoint -q /data 2>/dev/null; then
    # Get disk usage info
    DISK_TOTAL=$(df -BG /data | awk 'NR==2 {print $2}' | sed 's/G//')
    DISK_USED=$(df -BG /data | awk 'NR==2 {print $3}' | sed 's/G//')
    DISK_AVAIL=$(df -BG /data | awk 'NR==2 {print $4}' | sed 's/G//')
    DISK_PERCENT=$(df -h /data | awk 'NR==2 {print $5}' | sed 's/%//')

    # Check minimum size (50GB+)
    if [ "$DISK_TOTAL" -ge 50 ]; then
        success "Disk size: ${DISK_TOTAL}GB (minimum 50GB)"
    else
        warning "Disk size: ${DISK_TOTAL}GB (recommended 100GB+)"
    fi

    # Check usage (should be low after fresh setup)
    if [ "$DISK_PERCENT" -lt 10 ]; then
        success "Disk usage: ${DISK_USED}GB used (${DISK_PERCENT}%)"
    else
        warning "Disk usage: ${DISK_USED}GB used (${DISK_PERCENT}%) - high for fresh setup"
    fi

    info "Available: ${DISK_AVAIL}GB"
else
    error "Cannot check disk space - /data not mounted"
fi

echo ""

# ============================================================================
# Test 4: Write Test
# ============================================================================
echo "📦 Test 4: Disk Write Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if mountpoint -q /data 2>/dev/null; then
    TEST_FILE="/data/.infrastructure_test"

    # Try to write a test file
    if echo "VirtualPyTest infrastructure test - $(date)" > "$TEST_FILE" 2>/dev/null; then
        success "Write test passed"
        rm -f "$TEST_FILE"
    else
        error "Write test failed - cannot write to /data"
    fi
else
    error "Cannot test write access - /data not mounted"
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
    echo "✅ Proxmox Backend Host Infrastructure:"
    echo "   • Disk mount: READY"
    echo "   • Host directories: READY"
    echo "   • Disk space: ADEQUATE"
    echo "   • Write access: CONFIRMED"
    echo ""
    echo "📋 Next Steps:"
    echo "   1. Install host services: cd ~/virtualpytest/setup/local/linux/host && sudo ./install_host.sh"
    echo "   2. Test host services: cd ~/virtualpytest/setup/local/linux/host && ./test_host.sh"
    echo ""
    exit 0
else
    error "SOME TESTS FAILED! (Passed: $PASSED, Failed: $FAILED)"
    echo ""
    echo "⚠️  Please check the errors above and run the appropriate script:"
    echo "   • For disk setup: sudo ./create_disk_partition.sh"
    echo ""
    exit 1
fi