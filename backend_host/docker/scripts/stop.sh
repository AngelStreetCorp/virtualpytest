#!/bin/bash
# Stop backend_host containers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🛑 Stopping backend_host..."

cd "$DOCKER_DIR"
docker-compose down

echo "✅ backend_host stopped!"

