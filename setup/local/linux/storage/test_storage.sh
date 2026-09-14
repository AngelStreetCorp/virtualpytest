#!/bin/bash

# VirtualPyTest - Test Storage VM Components
# Tests directory structure, MinIO (S3), and Redis functionality

echo "🧪 VirtualPyTest - Testing Storage VM Services"
echo "   • MinIO (S3-compatible object storage)"
echo "   • Redis (caching and sessions)"
echo "   • Directory structure and permissions"
echo ""

# Configuration from install_storage.sh
MINIO_ENDPOINT="http://localhost:9000"
MINIO_ACCESS_KEY="admin"
MINIO_SECRET_KEY="admin1234"
MINIO_BUCKET="virtualpytest"
REDIS_PASSWORD="admin1234"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

success() { echo -e "${GREEN}✅ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "   ℹ️  $1"; }

# Test counter
PASSED=0
FAILED=0

# ============================================================================
# Test 1: Service User
# ============================================================================
echo "🔍 Testing Service User..."

# Test vpt_user exists
if id vpt_user &>/dev/null; then
    success "vpt_user exists"
    ((PASSED++))
    
    # Check user details
    VPT_HOME=$(getent passwd vpt_user | cut -d: -f6)
    VPT_SHELL=$(getent passwd vpt_user | cut -d: -f7)
    info "Home: $VPT_HOME"
    info "Shell: $VPT_SHELL"
    
    # Check if user can access /opt/virtualpytest
    if [ -d "/opt/virtualpytest" ]; then
        # Get owner (try Linux format first, then macOS)
        if command -v stat &>/dev/null; then
            OPT_OWNER=$(stat -c '%U' /opt/virtualpytest 2>/dev/null)
            if [ -z "$OPT_OWNER" ]; then
                OPT_OWNER=$(stat -f '%Su' /opt/virtualpytest 2>/dev/null)
            fi
        else
            OPT_OWNER=$(ls -ld /opt/virtualpytest | awk '{print $3}')
        fi
        
        if [ "$OPT_OWNER" = "vpt_user" ]; then
            success "/opt/virtualpytest owned by vpt_user"
            ((PASSED++))
        else
            error "/opt/virtualpytest NOT owned by vpt_user (owner: $OPT_OWNER)"
            ((FAILED++))
        fi
    fi
else
    error "vpt_user does NOT exist"
    ((FAILED++))
fi

echo ""

# ============================================================================
# Test 2: Directory Structure
# ============================================================================
echo "🔍 Testing Directory Structure..."

# Test /data directory
if [ -d "/data" ]; then
    success "/data directory exists"
    ((PASSED++))
    
    # Check if it's a mount point
    if mountpoint -q /data; then
        info "✓ /data is mounted (dedicated disk detected)"
    else
        info "✓ /data is a local directory (no dedicated disk)"
    fi
else
    error "/data directory NOT found"
    ((FAILED++))
fi

# Test /data/minio directory
if [ -d "/data/minio" ]; then
    success "/data/minio directory exists"
    ((PASSED++))
    
    # Check permissions
    if command -v stat &>/dev/null; then
        MINIO_OWNER=$(stat -c '%U' /data/minio 2>/dev/null)
        if [ -z "$MINIO_OWNER" ]; then
            MINIO_OWNER=$(stat -f '%Su' /data/minio 2>/dev/null)
        fi
    else
        MINIO_OWNER=$(ls -ld /data/minio | awk '{print $3}')
    fi
    info "Owner: $MINIO_OWNER"
else
    error "/data/minio directory NOT found"
    ((FAILED++))
fi

# Test /data/redis directory
if [ -d "/data/redis" ]; then
    success "/data/redis directory exists"
    ((PASSED++))
    
    # Check if Redis is using it
    if [ -f "/data/redis/appendonly.aof" ] || [ -f "/data/redis/dump.rdb" ]; then
        info "Redis data files found in /data/redis"
    fi
else
    error "/data/redis directory NOT found"
    ((FAILED++))
fi

# Test /opt/virtualpytest directory (local copy)
if [ -d "/opt/virtualpytest" ]; then
    success "/opt/virtualpytest exists (local execution copy)"
    ((PASSED++))
    
    # Check if .version file exists
    if [ -f "/opt/virtualpytest/.version" ]; then
        info "✓ Version tracking file found"
        INSTALL_DATE=$(grep "INSTALL_DATE=" /opt/virtualpytest/.version | cut -d'=' -f2 || echo "unknown")
        info "Installed: $INSTALL_DATE"
    fi
else
    error "/opt/virtualpytest NOT found"
    ((FAILED++))
fi

echo ""

# ============================================================================
# Test 3: Service Status
# ============================================================================
echo "🔍 Testing Service Status..."

# Test MinIO service
if systemctl is-active --quiet minio; then
    success "MinIO service is RUNNING"
    ((PASSED++))
    
    # Check MinIO data directory config
    if grep -q "MINIO_DRIVES=\"/data/minio\"" /etc/default/minio 2>/dev/null; then
        info "✓ MinIO configured to use /data/minio"
    fi
else
    error "MinIO service is NOT running"
    ((FAILED++))
fi

# Test Redis service
if systemctl is-active --quiet redis-server; then
    success "Redis service is RUNNING"
    ((PASSED++))
    
    # Check Redis data directory config
    if grep -q "dir /data/redis" /etc/redis/redis.conf 2>/dev/null; then
        info "✓ Redis configured to use /data/redis"
    fi
else
    error "Redis service is NOT running"
    ((FAILED++))
fi

echo ""

# ============================================================================
# Test 4: Redis Functionality
# ============================================================================
echo "🔍 Testing Redis Functionality..."

if redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q "PONG"; then
    success "Redis connection successful"
    ((PASSED++))

    # Test Redis list operations
    info "Testing Redis operations..."
    redis-cli -a "$REDIS_PASSWORD" lpush test_list "item1" "item2" "item3" > /dev/null 2>&1
    COUNT=$(redis-cli -a "$REDIS_PASSWORD" llen test_list 2>/dev/null)
    if [ "$COUNT" -eq 3 ]; then
        success "Redis LPUSH/LLEN operations successful"
        ((PASSED++))
    else
        error "Redis LPUSH/LLEN operations failed"
        ((FAILED++))
    fi

    POPPED=$(redis-cli -a "$REDIS_PASSWORD" rpop test_list 2>/dev/null)
    if [ "$POPPED" = "item1" ]; then
        success "Redis RPOP operation successful"
        ((PASSED++))
    else
        error "Redis RPOP operation failed"
        ((FAILED++))
    fi

    # Clean up
    redis-cli -a "$REDIS_PASSWORD" del test_list > /dev/null 2>&1
else
    error "Redis connection failed"
    ((FAILED++))
fi

echo ""

# ============================================================================
# Test 5: MinIO Functionality
# ============================================================================
echo "🔍 Testing MinIO Functionality..."

# Configure mc alias for testing (may already be configured, but ensure it's set)
mc alias set local http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" > /dev/null 2>&1

# Test bucket existence
if mc ls local/ 2>/dev/null | grep -q "$MINIO_BUCKET"; then
    success "MinIO bucket '$MINIO_BUCKET' exists"
    ((PASSED++))
else
    error "MinIO bucket '$MINIO_BUCKET' does NOT exist"
    info "Attempting to create bucket..."
    if mc mb local/"$MINIO_BUCKET" --ignore-existing 2>/dev/null; then
        success "MinIO bucket '$MINIO_BUCKET' created"
        ((PASSED++))
    else
        error "Failed to create MinIO bucket '$MINIO_BUCKET'"
        ((FAILED++))
        info "Skipping file operations tests"
        echo ""
        
        # Skip to next test
        # ============================================================================
        # Test 6: Disk Space
        # ============================================================================
        echo "🔍 Testing Disk Space..."

        # Check /data disk space
        DATA_USAGE=$(df -h /data | awk 'NR==2 {print $5}' | sed 's/%//')
        DATA_AVAIL=$(df -h /data | awk 'NR==2 {print $4}')
        if [ "$DATA_USAGE" -lt 90 ]; then
            success "/data has sufficient space (${DATA_USAGE}% used, ${DATA_AVAIL} available)"
            ((PASSED++))
        else
            warning "/data is running low on space (${DATA_USAGE}% used)"
        fi

        # Check /shared disk space (if different from /data)
        if ! df /data | grep -q "$(df /shared | awk 'NR==2 {print $1}')"; then
            SHARED_USAGE=$(df -h /shared | awk 'NR==2 {print $5}' | sed 's/%//')
            SHARED_AVAIL=$(df -h /shared | awk 'NR==2 {print $4}')
            if [ "$SHARED_USAGE" -lt 90 ]; then
                success "/shared has sufficient space (${SHARED_USAGE}% used, ${SHARED_AVAIL} available)"
                ((PASSED++))
            else
                warning "/shared is running low on space (${SHARED_USAGE}% used)"
            fi
        fi

        echo ""

        # Jump to summary
        # ============================================================================
        # Summary
        # ============================================================================
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📊 Test Summary"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""

        if [ $FAILED -eq 0 ]; then
            success "🎉 ALL TESTS PASSED! ($PASSED/$PASSED)"
            echo ""
            echo "✅ Storage VM Architecture:"
            echo "   • Directory structure: CORRECT"
            echo "   • MinIO (S3 storage): WORKING"
            echo "   • Redis (caching): WORKING"
            echo "   • Data directories: CONFIGURED"
            echo ""
            echo "💾 VirtualPyTest Storage VM is fully operational!"
            echo ""
            exit 0
        else
            error "SOME TESTS FAILED! (Passed: $PASSED, Failed: $FAILED)"
            echo ""
            echo "⚠️  Please check the errors above and:"
            echo "   1. Verify services are running: sudo systemctl status minio redis-server"
            echo "   2. Check logs: sudo journalctl -u minio -n 50"
            echo "   3. Verify disk mounts: df -h | grep -E '/data|/shared'"
            echo "   4. Re-run installer if needed: sudo ./setup/local/linux/storage/install_storage.sh"
            echo ""
            exit 1
        fi
    fi
fi

# Create test file
echo "VirtualPyTest MinIO Test File - $(date)" > /tmp/test_file.txt

# Upload file
info "Testing file upload..."
if mc cp /tmp/test_file.txt local/"$MINIO_BUCKET"/test_file.txt > /dev/null 2>&1; then
    success "MinIO file upload successful"
    ((PASSED++))
else
    error "MinIO file upload failed"
    ((FAILED++))
fi

# Download and verify file
info "Testing file download..."
if mc cp local/"$MINIO_BUCKET"/test_file.txt /tmp/downloaded_file.txt > /dev/null 2>&1; then
    if cmp -s /tmp/test_file.txt /tmp/downloaded_file.txt; then
        success "MinIO file download and verification successful"
        ((PASSED++))
    else
        error "MinIO file verification failed (content mismatch)"
        ((FAILED++))
    fi
else
    error "MinIO file download failed"
    ((FAILED++))
fi

# List files in bucket
info "Testing bucket listing..."
if mc ls local/"$MINIO_BUCKET"/ 2>/dev/null | grep -q "test_file.txt"; then
    success "MinIO bucket listing successful"
    ((PASSED++))
else
    error "MinIO bucket listing failed"
    ((FAILED++))
fi

# Delete file
info "Testing file deletion..."
if mc rm local/"$MINIO_BUCKET"/test_file.txt > /dev/null 2>&1; then
    success "MinIO file deletion successful"
    ((PASSED++))
else
    error "MinIO file deletion failed"
    ((FAILED++))
fi

# Clean up local test files
rm -f /tmp/test_file.txt /tmp/downloaded_file.txt

echo ""

# ============================================================================
# Test 6: Disk Space
# ============================================================================
echo "🔍 Testing Disk Space..."

# Check /data disk space
DATA_USAGE=$(df -h /data | awk 'NR==2 {print $5}' | sed 's/%//')
DATA_AVAIL=$(df -h /data | awk 'NR==2 {print $4}')
if [ "$DATA_USAGE" -lt 90 ]; then
    success "/data has sufficient space (${DATA_USAGE}% used, ${DATA_AVAIL} available)"
    ((PASSED++))
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
    success "🎉 ALL TESTS PASSED! ($PASSED/$PASSED)"
    echo ""
    echo "✅ Storage VM Architecture:"
    echo "   • Directory structure: CORRECT"
    echo "   • MinIO (S3 storage): WORKING"
    echo "   • Redis (caching): WORKING"
    echo "   • Data directories: CONFIGURED"
    echo ""
    echo "💾 VirtualPyTest Storage VM is fully operational!"
    echo ""
    exit 0
else
    error "SOME TESTS FAILED! (Passed: $PASSED, Failed: $FAILED)"
    echo ""
    echo "⚠️  Please check the errors above and:"
    echo "   1. Verify services are running: sudo systemctl status minio redis-server"
    echo "   2. Check logs: sudo journalctl -u minio -n 50"
    echo "   3. Verify disk mount: df -h /data"
    echo "   4. Re-run installer if needed: sudo ./setup/local/linux/storage/install_storage.sh"
    echo ""
    exit 1
fi
