#!/bin/bash
# Run backend_host using docker-compose

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting backend_host with docker-compose..."

cd "$DOCKER_DIR"

# Check if .env exists in project root
if [ ! -f "../../.env" ]; then
    echo "⚠️  Warning: ../../.env not found"
    echo "   Create .env file with required variables:"
    echo "   HOST_NAME, HOST_PORT, HOST_URL, SERVER_URL"
    echo ""
fi

docker-compose up -d

echo "✅ backend_host started!"
echo ""
echo "Services running:"
echo "  • Flask API:  http://localhost:6109/host/health"
echo "  • NoVNC:      http://localhost:6080"
echo ""
echo "Next steps:"
echo "  • View logs:  ./scripts/logs.sh"
echo "  • Stop:       ./scripts/stop.sh"
echo "  • Restart:    ./scripts/restart.sh"

