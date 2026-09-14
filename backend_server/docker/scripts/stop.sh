#!/bin/bash
# Stop Docker services (but keep containers for quick restart)
set -e

cd "$(dirname "$0")/.."

echo "🛑 Stopping backend_server services..."
docker-compose stop

echo ""
echo "✅ Services stopped!"
echo ""
echo "To start again: ./scripts/run.sh"
echo "To remove completely: ./scripts/clean.sh"

