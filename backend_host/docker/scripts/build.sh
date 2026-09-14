#!/bin/bash
# Build backend_host Docker image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🐳 Building backend_host Docker image..."
echo "   Project root: $PROJECT_ROOT"
echo "   Docker context: $PROJECT_ROOT"
echo "   Dockerfile: backend_host/docker/Dockerfile"

cd "$PROJECT_ROOT"

docker build \
  -f backend_host/docker/Dockerfile \
  -t virtualpytest-backend-host:latest \
  .

echo "✅ Build complete!"
echo ""
echo "Next steps:"
echo "  • Run locally:  cd backend_host/docker && ./scripts/run.sh"
echo "  • View logs:    cd backend_host/docker && ./scripts/logs.sh"
echo "  • Stop:         cd backend_host/docker && ./scripts/stop.sh"

