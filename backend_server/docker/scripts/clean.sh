#!/bin/bash
set -e

echo "🧹 Stopping and cleaning up backend_server Docker environment..."
echo ""

# Navigate to docker directory
cd "$(dirname "$0")/.."

# Stop services
echo "🛑 Stopping services..."
docker-compose down

# Optional: Remove volumes
read -p "Remove volumes (database data will be lost)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker-compose down -v
    echo "✅ Volumes removed"
fi

# Optional: Clean up images
read -p "Remove Docker images? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker rmi virtualpytest/backend_server:latest 2>/dev/null || echo "Image not found"
    echo "✅ Images removed"
fi

echo ""
echo "✅ Cleanup complete!"

