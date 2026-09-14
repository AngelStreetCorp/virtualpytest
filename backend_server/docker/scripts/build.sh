#!/bin/bash
set -e

echo "🔨 Building backend_server Docker image..."

# Navigate to backend_server directory
cd "$(dirname "$0")/../.."

# Build image
echo "📦 Building Docker image..."
docker build -f Dockerfile -t virtualpytest/backend_server:latest ..

echo ""
echo "✅ Build complete!"
echo "📦 Image: virtualpytest/backend_server:latest"
echo ""
echo "Next steps:"
echo "  ./scripts/docker-run.sh    # Start with docker-compose"

