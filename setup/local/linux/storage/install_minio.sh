#!/bin/bash

# VirtualPyTest - Install MinIO Server
# This script sets up MinIO (S3-compatible object storage) for VirtualPyTest

set -e

echo "💾 VirtualPyTest - Installing MinIO Server (S3-compatible)"
echo "📦 Installing MinIO Server (S3-compatible)..."

# dl.min.io stopped serving the binaries (HTTP 410 Gone, 2025), the GitHub releases carry no
# assets and Docker Hub denies the minio/* repositories: the binaries are taken out of the
# pinned images on quay.io (MinIO's own registry) that the Docker stack uses
# (setup/docker/docker-compose.yml). Docker is present on every VM the installer targets
# (the database role needs it); a container is created, never run.
MINIO_IMAGE="quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z"
MC_IMAGE="quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z"
SUDO=""; [ "$EUID" -ne 0 ] && SUDO="sudo"
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ docker is required to obtain the MinIO binaries (dl.min.io no longer serves them)"
    exit 1
fi
fetch_from_image() {  # fetch_from_image <image> <path-in-image> <destination>
    local cid
    cid=$($SUDO docker create "$1") || return 1
    $SUDO docker cp "$cid:$2" "$3" || { $SUDO docker rm "$cid" >/dev/null 2>&1; return 1; }
    $SUDO docker rm "$cid" >/dev/null 2>&1
    $SUDO chmod +x "$3"
}
echo "📦 Installing MinIO Server (binary from $MINIO_IMAGE)..."
if ! command -v minio >/dev/null 2>&1; then
    fetch_from_image "$MINIO_IMAGE" /usr/bin/minio /tmp/minio
    $SUDO mv /tmp/minio /usr/local/bin/minio
fi

echo "📦 Installing MinIO Client (mc, from $MC_IMAGE)..."
if ! command -v mc >/dev/null 2>&1; then
    fetch_from_image "$MC_IMAGE" /usr/bin/mc /tmp/mc
    $SUDO mv /tmp/mc /usr/local/bin/mc
fi

# Create MinIO user and directories
echo "📁 Setting up MinIO directories and user..."
echo "   • MinIO data will be stored on /data disk (2TB+) instead of system disk (100GB)"

# Check if /data directory exists (data disk should be mounted)
if [ ! -d "/data" ]; then
    echo "⚠️  Warning: /data directory not found. Creating /data/minio on system disk instead."
    echo "   Please ensure your data disk is mounted at /data for proper storage capacity."
    sudo mkdir -p /data
fi

# Create minio-user if it doesn't exist
if ! id -u minio-user > /dev/null 2>&1; then
    sudo useradd -r minio-user -s /sbin/nologin
    echo "   ✅ Created minio-user"
else
    echo "   ℹ️  minio-user already exists, continuing..."
fi

sudo mkdir -p /usr/local/share/minio
sudo mkdir -p /etc/minio
sudo mkdir -p /data/minio  # Use data disk (sdb1) for all images/videos/logs/results storage

# Set proper permissions
sudo chown -R minio-user:minio-user /usr/local/share/minio
sudo chown -R minio-user:minio-user /etc/minio
sudo chown -R minio-user:minio-user /data/minio  # Update ownership for data disk

# Create MinIO configuration
echo "⚙️ Creating MinIO configuration..."
sudo tee /etc/default/minio > /dev/null << 'EOF'
# MinIO configuration file
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=admin1234
MINIO_OPTS="--address :9000 --console-address :9001"
MINIO_CONFIG_DIR=/etc/minio
MINIO_CACHE_DRIVES=""
MINIO_DRIVES="/data/minio"
EOF

# Get the script's directory to locate config files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/services"

# Install MinIO systemd service
echo "🚀 Installing MinIO systemd service..."
sudo cp "${CONFIG_DIR}/minio.service" /etc/systemd/system/minio.service
echo "   ✅ MinIO service installed from ${CONFIG_DIR}/minio.service"

# Enable and start MinIO service
echo "🚀 Enabling and starting MinIO service..."
sudo systemctl daemon-reload
sudo systemctl enable minio

# Stop any existing MinIO service
if sudo systemctl is-active --quiet minio; then
    echo "   ℹ️  Stopping existing MinIO service..."
    sudo systemctl stop minio
fi

# Try to start MinIO and check if it succeeds
echo "   🚀 Starting MinIO service..."
if sudo systemctl start minio; then
    echo "   ✅ MinIO service started successfully"
else
    echo "   ❌ MinIO service failed to start. Checking status..."
    sudo systemctl status minio.service --no-pager -l
    echo ""
    echo "   📋 Checking journal logs:"
    sudo journalctl -u minio.service -n 50 --no-pager
    exit 1
fi

# Wait for MinIO to start and verify it's listening
echo "⏳ Waiting for MinIO to start..."
RETRY_COUNT=0
MAX_RETRIES=30

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if sudo netstat -tlnp 2>/dev/null | grep -q ":9000"; then
        echo "   ✅ MinIO is listening on port 9000"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ MinIO failed to start listening on port 9000 after 30 seconds"
        echo "   📋 Service status:"
        sudo systemctl status minio.service --no-pager -l
        echo ""
        echo "   📋 Recent logs:"
        sudo journalctl -u minio.service -n 50 --no-pager
        exit 1
    fi
    sleep 1
done

# Configure MinIO client and create bucket
echo "⚙️ Configuring MinIO client and creating bucket..."

# Wait a bit more to ensure MinIO is fully ready
sleep 3

# Configure mc alias with retry logic
RETRY_COUNT=0
MAX_RETRIES=10

echo "   Configuring MinIO client alias..."
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    MC_OUTPUT=$(mc alias set local http://localhost:9000 admin admin1234 2>&1)
    MC_EXIT=$?
    
    if [ $MC_EXIT -eq 0 ]; then
        echo "   ✅ MinIO client configured successfully"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ Failed to configure MinIO client after $MAX_RETRIES attempts"
        echo "   Error output: $MC_OUTPUT"
        echo ""
        echo "   📋 Checking MinIO service status:"
        sudo systemctl status minio.service --no-pager -l
        echo ""
        echo "   📋 Checking MinIO logs:"
        sudo journalctl -u minio.service -n 20 --no-pager
        echo ""
        echo "   You can configure it manually later with:"
        echo "   mc alias set local http://localhost:9000 admin admin1234"
        echo "   mc mb local/virtualpytest"
        exit 1
    fi
    echo "   Retry $RETRY_COUNT/$MAX_RETRIES (waiting for MinIO to be fully ready)..."
    sleep 3
done

# Check if bucket already exists
echo "   Checking if bucket 'virtualpytest' already exists..."
if mc ls local/ 2>/dev/null | grep -q "virtualpytest"; then
    echo "   ℹ️  Bucket 'virtualpytest' already exists, skipping creation"
else
    # Create bucket with retry logic
    echo "   Creating bucket 'virtualpytest'..."
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        BUCKET_OUTPUT=$(mc mb local/virtualpytest 2>&1)
        BUCKET_EXIT=$?
        
        if [ $BUCKET_EXIT -eq 0 ]; then
            echo "   ✅ Bucket 'virtualpytest' created successfully"
            break
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
            echo "   ❌ Failed to create bucket after $MAX_RETRIES attempts"
            echo "   Error output: $BUCKET_OUTPUT"
            echo ""
            echo "   📋 Checking MinIO service status:"
            sudo systemctl status minio.service --no-pager -l
            echo ""
            echo "   You can create it manually later with:"
            echo "   mc mb local/virtualpytest"
            exit 1
        fi
        echo "   Retry $RETRY_COUNT/$MAX_RETRIES..."
        sleep 2
    done
fi

# Verify bucket was created/exists
echo "   Verifying bucket..."
if mc ls local/ 2>/dev/null | grep -q "virtualpytest"; then
    echo "   ✅ Bucket 'virtualpytest' verified and ready"
else
    echo "   ⚠️  WARNING: Bucket verification failed!"
    echo "   📋 Listing all buckets:"
    mc ls local/ 2>&1 || echo "   Failed to list buckets"
    echo ""
    echo "   You may need to create the bucket manually with:"
    echo "   mc alias set local http://localhost:9000 admin admin1234"
    echo "   mc mb local/virtualpytest"
    exit 1
fi

# Configure lifecycle (ILM) rules — auto-expire ephemeral run artifacts so
# local /data/minio doesn't grow unbounded. Prefixes match the upload paths
# in shared/src/lib/utils/cloudflare_utils.py. Every artifact prefix gets 14
# days.
# navigation/ and reference-images/ are DELIBERATELY EXCLUDED — those are the
# permanent nav-tree screenshot and reference-image libraries, not run
# artifacts. An expiry rule on them would silently delete production data.
# See install_storage.md for how to change these per-prefix.
#
# Every prefix cloudflare_utils.py writes to must be listed here. A missing one
# never expires: on the Awesomation instance script-screenshots/ (5.1G) and
# reports/ had no rule and grew until MinIO hit its free-space threshold and
# started refusing every upload with XMinioStorageFull (2026-09-14).
echo "⏳ Configuring bucket lifecycle (auto-expiry) rules..."

add_ilm_rule() {
    local prefix="$1" days="$2"
    if mc ilm rule ls "local/virtualpytest" 2>/dev/null | grep -q "$prefix"; then
        echo "   ℹ️  ILM rule for '${prefix}' already exists, skipping"
        return
    fi
    if mc ilm rule add --expire-days "$days" "local/virtualpytest" --prefix "$prefix" >/dev/null 2>&1; then
        echo "   ✅ ILM rule added: ${prefix} -> expires after ${days}d"
    else
        echo "   ⚠️  Failed to add ILM rule for '${prefix}' (non-fatal, continuing)"
    fi
}

# Every ephemeral artifact prefix: 14 days
add_ilm_rule "script-reports/" 14
add_ilm_rule "restart-reports/" 14
add_ilm_rule "zap-reports/" 14
add_ilm_rule "kpi_measurement/" 14
add_ilm_rule "heatmaps/" 14
add_ilm_rule "script-logs/" 14
add_ilm_rule "alerts/" 14
add_ilm_rule "audio-analysis/" 14
add_ilm_rule "script-screenshots/" 14
add_ilm_rule "reports/" 14
add_ilm_rule "fleet-health/" 14

echo "   Verifying lifecycle rules:"
mc ilm rule ls local/virtualpytest 2>&1 || echo "   ⚠️  Could not list ILM rules"

# Install rclone for additional cloud storage compatibility
echo "📦 Installing rclone for cloud storage compatibility..."
sudo apt update
sudo apt install -y rclone

# Configure rclone for local MinIO (S3-compatible)
echo "⚙️ Configuring rclone for local MinIO..."
mkdir -p ~/.config/rclone
cat > ~/.config/rclone/rclone.conf << 'EOF'
[virtualpytest-local]
type = s3
provider = MinIO
env_auth = false
access_key_id = virtualpytest
secret_access_key = admin1234
endpoint = http://localhost:9000
acl = private
server_side_encryption =
sse_kms_key_id =
signature_version2 = false
region = us-east-1
EOF

# Install traditional storage tools for compatibility
echo "📦 Installing traditional storage tools..."
sudo apt install -y rsync borgbackup quota p7zip-full pigz

echo "✅ MinIO installation completed!"
echo ""

# Final verification
echo "🔍 Verifying MinIO installation..."
echo ""
echo "📊 Service Status:"
sudo systemctl status minio.service --no-pager | head -10
echo ""
echo "🌐 Network Status:"
echo "   Port 9000 (API):"
sudo netstat -tlnp 2>/dev/null | grep ":9000" || echo "   ⚠️  Not listening on port 9000"
echo "   Port 9001 (Console):"
sudo netstat -tlnp 2>/dev/null | grep ":9001" || echo "   ⚠️  Not listening on port 9001"
echo ""
echo "📦 MinIO Process:"
ps aux | grep -v grep | grep minio || echo "   ⚠️  MinIO process not found"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 MinIO Console (S3 Interface): http://localhost:9001"
echo "🔑 Login: virtualpytest / admin1234"
echo "📊 MinIO API: http://localhost:9000"
echo "🪣 Bucket: virtualpytest"
echo ""
echo "🔧 Management Commands:"
echo "   • Check status: sudo systemctl status minio"
echo "   • View logs: sudo journalctl -u minio.service -f"
echo "   • Restart: sudo systemctl restart minio"
echo "   • MinIO client: mc admin info local"
echo "   • Rclone: rclone lsd virtualpytest-local:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⚠️  REVERSE PROXY CONFIGURATION (Required for nginx subpath access)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "If accessing MinIO Console via nginx reverse proxy (e.g., /minio-console/),"
echo "you MUST configure the redirect URL for the console to work properly."
echo ""
echo "Edit /etc/default/minio and add:"
echo "   MINIO_BROWSER_REDIRECT_URL=https://<YOUR_PROXY_IP>/minio-console/"
echo ""
echo "Example:"
echo "   echo 'MINIO_BROWSER_REDIRECT_URL=https://192.168.0.107/minio-console/' | sudo tee -a /etc/default/minio"
echo "   sudo systemctl restart minio"
echo ""
echo "Without this, the console will load assets from root path (/) instead of /minio-console/."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ MinIO is ready for VirtualPyTest S3-compatible storage!"
