#!/bin/bash
# VirtualPyTest - Launch Services (DEVELOPMENT MODE)
# Starts containers with source code mounted for rapid iteration
# Edit code locally → Changes reflect immediately → Just restart container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 VirtualPyTest - Launch Services (DEV MODE)"
echo "========================================="

# Check if setup was run
if [ ! -f "setup/docker/hetzner_custom/docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found"
    echo ""
    echo "Run setup first:"
    echo "  cd setup/docker/hetzner_custom"
    echo "  ./setup.sh"
    exit 1
fi

# Check if dev compose exists
if [ ! -f "setup/docker/hetzner_custom/docker-compose.dev.yml" ]; then
    echo "❌ Error: docker-compose.dev.yml not found"
    echo ""
    echo "Run setup first:"
    echo "  cd setup/docker/hetzner_custom"
    echo "  ./setup.sh"
    exit 1
fi

# Check if main .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found in project root"
    echo ""
    echo "Create .env file with your configuration:"
    echo "  cp setup/docker/hetzner_custom/env.example .env"
    echo "  nano .env"
    exit 1
fi

echo ""
echo "📦 DEV MODE: Source code will be mounted from host"
echo "   → Edit files locally"
echo "   → Changes reflect immediately" 
echo "   → Just restart containers to pick up changes"
echo ""

# Build base image ONLY (one-time, or when Dockerfile changes)
# Note: This builds the base image that backend_host_1-N use
# Dev mode will mount source code into the running containers
echo "🐳 Building base image (if needed)..."
docker-compose --env-file .env \
    -f setup/docker/hetzner_custom/docker-compose.yml \
    -f setup/docker/hetzner_custom/docker-compose.dev.yml \
    build backend_host_base

echo ""
echo "🚀 Starting Docker containers with dev overrides..."
docker-compose --env-file .env \
    -f setup/docker/hetzner_custom/docker-compose.yml \
    -f setup/docker/hetzner_custom/docker-compose.dev.yml \
    up -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 5

# Show status
echo ""
docker-compose --env-file .env \
    -f setup/docker/hetzner_custom/docker-compose.yml \
    -f setup/docker/hetzner_custom/docker-compose.dev.yml \
    ps

echo ""
echo "========================================="
echo "✅ Services Started (DEV MODE)!"
echo ""
echo "📦 Source Code Mounted (live editing enabled):"
echo "   • shared/ → All containers"
echo "   • backend_server/src/ → backend_server"
echo "   • backend_host/src/ → backend_host_1 through backend_host_N (running containers)"
echo "   Note: backend_host_base is just the base image, not a running container"
echo ""
echo "💡 Quick Restart After Code Changes:"
echo "   docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml -f setup/docker/hetzner_custom/docker-compose.dev.yml restart backend_host_1"
echo "   docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml -f setup/docker/hetzner_custom/docker-compose.dev.yml restart backend_server"
echo ""
echo "📋 Local Access:"
echo "   Backend Server:  http://localhost:5109"
echo "   Grafana:         http://localhost:3000"
echo "   Langfuse:        http://localhost:3001 (if installed)"

# Show host ports dynamically
if [ -f "setup/docker/hetzner_custom/config.env" ]; then
    source setup/docker/hetzner_custom/config.env
    for i in $(seq 1 $HOST_MAX); do
        PORT=$((HOST_START_PORT + i - 1))
        echo "   Backend Host ${i}:   http://localhost:${PORT}"
    done
fi

echo ""
echo "🌐 Public Access (if nginx configured):"
if [ -f "setup/docker/hetzner_custom/config.env" ]; then
    source setup/docker/hetzner_custom/config.env
    echo "   API: https://${DOMAIN}"
    for i in $(seq 1 $HOST_MAX); do
        echo "   VNC Host ${i}: https://${DOMAIN}/host${i}/vnc/vnc_lite.html"
    done
    if [ "${ENABLE_LANGFUSE}" = "true" ]; then
        echo "   Langfuse: https://${DOMAIN}/langfuse"
    fi
fi

echo ""
echo "📊 View logs:"
echo "   docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml -f setup/docker/hetzner_custom/docker-compose.dev.yml logs -f [service]"
echo ""
echo "🛑 Stop:"
echo "   docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml -f setup/docker/hetzner_custom/docker-compose.dev.yml down"
echo ""

