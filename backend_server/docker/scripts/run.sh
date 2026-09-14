#!/bin/bash
set -e

echo "🚀 Starting backend_server with Docker Compose..."

# Navigate to docker directory
cd "$(dirname "$0")/.."

# Check if .env exists in project root
if [ ! -f "../../.env" ]; then
    echo "❌ .env file not found in project root!"
    echo "📝 Copy .env.example and configure it:"
    echo ""
    echo "  cp docker/.env.example ../../.env"
    echo "  nano ../../.env"
    echo ""
    exit 1
fi

echo "✅ .env file found"
echo ""

# Start services
echo "🐳 Starting Docker Compose services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to start (40 seconds)..."
sleep 40

echo ""
echo "✅ Services started!"
echo ""
echo "🌐 Access points:"
echo "  Flask API:  http://localhost:5109"
echo "  Health:     http://localhost:5109/health"
echo "  Grafana:    http://localhost:3000"
echo ""
echo "📋 Useful commands:"
echo "  docker-compose logs -f              # View all logs"
echo "  docker-compose logs -f backend_server  # View server logs only"
echo "  docker-compose ps                   # Check service status"
echo "  docker-compose exec backend_server supervisorctl status  # Check processes"
echo "  docker-compose down                 # Stop services"
echo "  docker-compose restart              # Restart services"
echo ""

# Test health endpoint
echo "🔍 Testing health endpoint..."
if curl -s -f http://localhost:5109/health > /dev/null 2>&1; then
    echo "✅ Health check passed!"
    curl -s http://localhost:5109/health | python3 -m json.tool 2>/dev/null || echo "API is responding"
else
    echo "⚠️  Health check not ready yet. Check logs:"
    echo "  docker-compose logs -f backend_server"
fi

