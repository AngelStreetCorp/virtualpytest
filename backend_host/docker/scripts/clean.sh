#!/bin/bash
# Clean backend_host Docker resources

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🧹 Cleaning backend_host Docker resources..."

cd "$DOCKER_DIR"

# Stop and remove containers
docker-compose down --volumes --remove-orphans

# Remove image
echo "Removing image virtualpytest-backend-host:latest..."
docker rmi virtualpytest-backend-host:latest 2>/dev/null || echo "Image not found (already cleaned)"

echo "✅ Cleanup complete!"

