#!/bin/bash
# VirtualPyTest - Launch Services
# Starts all Docker containers (server + all hosts)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 VirtualPyTest - Launch Services"
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

# Check if main .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found in project root"
    echo ""
    echo "Create .env file with your configuration:"
    echo "  cp setup/docker/hetzner_custom/env.example .env"
    echo "  nano .env"
    exit 1
fi

# Launch
echo "🐳 Building shared backend_host image (used by all hosts)..."
docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml build backend_host_base

echo ""
echo "🚀 Starting Docker containers..."
docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml up -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 5

# Show status
echo ""
docker-compose --env-file .env -f setup/docker/hetzner_custom/docker-compose.yml ps

echo ""
echo "========================================="
echo "✅ Services Started!"
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
echo "📊 View logs:    docker-compose -f setup/docker/hetzner_custom/docker-compose.yml logs -f"
echo "🛑 Stop:         docker-compose -f setup/docker/hetzner_custom/docker-compose.yml down"
echo ""
