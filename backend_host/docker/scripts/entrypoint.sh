#!/bin/bash
# Docker entrypoint script for backend_host
# Starts supervisord with backend_host services
# NOTE: This script runs on EVERY container start to ensure RAM storage is initialized

set -e

echo "🚀 Starting VirtualPyTest Backend Host..."
echo "   Container: $(hostname)"
echo "   Timestamp: $(date)"

# Initialize storage directories from .env
ENV_FILE="/app/backend_host/src/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

echo ""
echo "📁 Initializing storage directories..."

# Parse devices from .env file (same logic as RAM setup script).
# env_value KEY: the value with quotes, an inline "# comment" and surrounding whitespace
# removed — the template writes `HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture    # …`
# and taking the raw text created a directory named "capture    # Capture output directory".
env_value() { grep "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d "'" | sed 's/[[:space:]]*#.*$//' | xargs; }
CAPTURE_PATHS=()

# Check for HOST device first
HOST_CAPTURE_PATH=$(env_value HOST_VIDEO_CAPTURE_PATH)
if [ -n "$HOST_CAPTURE_PATH" ]; then
    CAPTURE_PATHS+=("$HOST_CAPTURE_PATH")
    echo "   ✓ Found host: HOST -> $HOST_CAPTURE_PATH"
fi

# Check for regular devices (dynamically detect up to 14)
for i in {1..14}; do
    DEVICE_CAPTURE_PATH=$(env_value "DEVICE${i}_VIDEO_CAPTURE_PATH")

    if [ -n "$DEVICE_CAPTURE_PATH" ]; then
        CAPTURE_PATHS+=("$DEVICE_CAPTURE_PATH")
        DEVICE_NAME=$(env_value "DEVICE${i}_NAME")
        echo "   ✓ Found device$i: ${DEVICE_NAME:-Device$i} -> $DEVICE_CAPTURE_PATH"
    elif [ $i -gt 20 ] && [ ${#CAPTURE_PATHS[@]} -gt 0 ]; then
        # Stop scanning after 20 consecutive empty slots beyond configured devices
        break
    fi
done

if [ ${#CAPTURE_PATHS[@]} -eq 0 ]; then
    echo "   ❌ ERROR: No capture paths found in .env file"
    exit 1
fi

echo "   📊 Initializing ${#CAPTURE_PATHS[@]} device(s)..."

# Process each capture path
for CAPTURE_PATH in "${CAPTURE_PATHS[@]}"; do
    echo ""
    echo "   🔧 Processing: $CAPTURE_PATH"

    # Verify tmpfs mount exists (should be mounted by docker-compose.yml)
    if mountpoint -q "$CAPTURE_PATH/hot" 2>/dev/null; then
        HOT_SIZE=$(df -h "$CAPTURE_PATH/hot" 2>/dev/null | tail -1 | awk '{print $2}')
        echo "      ✅ tmpfs mounted at $CAPTURE_PATH/hot (size: $HOT_SIZE)"
    else
        echo "      ⚠️  WARNING: $CAPTURE_PATH/hot is NOT mounted as tmpfs!"
        echo "      This may cause performance issues. Check docker-compose.yml"
    fi

    # Create HOT subdirectories (tmpfs loses all data on container restart)
    echo "      📁 Creating HOT directories (RAM)..."
    mkdir -p "$CAPTURE_PATH/hot/captures"
    mkdir -p "$CAPTURE_PATH/hot/thumbnails"
    mkdir -p "$CAPTURE_PATH/hot/segments"
    mkdir -p "$CAPTURE_PATH/hot/metadata"

    # Create COLD subdirectories (persistent disk)
    echo "      💾 Creating COLD directories (disk)..."
    mkdir -p "$CAPTURE_PATH/captures"
    mkdir -p "$CAPTURE_PATH/segments"
    mkdir -p "$CAPTURE_PATH/metadata"
    mkdir -p "$CAPTURE_PATH/audio"
    mkdir -p "$CAPTURE_PATH/thumbnails"

    # Create hour folders (0-23) for rolling 24h storage
    for hour in {0..23}; do
        mkdir -p "$CAPTURE_PATH/segments/$hour"
        mkdir -p "$CAPTURE_PATH/metadata/$hour"
        mkdir -p "$CAPTURE_PATH/audio/$hour"
    done

    # Create temp directories
    mkdir -p "$CAPTURE_PATH/segments/temp"
    mkdir -p "$CAPTURE_PATH/metadata/temp"

    # Set all permissions to 777 for cross-service access
    chmod -R 777 "$CAPTURE_PATH"

    echo "      ✅ $CAPTURE_PATH initialized"
done

echo ""
echo "   🎉 All storage directories initialized successfully"
echo ""
echo "📊 Storage summary:"
echo "   Devices configured: ${#CAPTURE_PATHS[@]}"
for CAPTURE_PATH in "${CAPTURE_PATHS[@]}"; do
    CAPTURE_DIR=$(basename "$CAPTURE_PATH")
    echo "   📁 $CAPTURE_DIR:"
    echo "      HOT (RAM):  $CAPTURE_PATH/hot/{captures,thumbnails,segments,metadata}"
    echo "      COLD (disk): $CAPTURE_PATH/{captures,segments,metadata,audio}"
done
echo "   ⏰ Hour folders: 0-23 in segments/metadata/audio (all devices)"
echo "   🔧 Temp dirs: segments/temp, metadata/temp (all devices)"
echo ""

echo "🔧 Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf -n

