#!/bin/bash
set -e

echo "🧪 Testing backend_server Docker setup..."
echo ""

# Navigate to docker directory
cd "$(dirname "$0")/.."

# Check if docker-compose is running
if docker-compose ps | grep -q "backend_server"; then
    echo "✅ backend_server container is running"
    echo ""
    
    # Test Flask API health
    echo "🔍 Testing Flask API health endpoint..."
    if curl -s -f http://localhost:5109/health > /dev/null 2>&1; then
        echo "✅ Flask health check passed!"
        echo ""
        echo "Response:"
        curl -s http://localhost:5109/health | python3 -m json.tool || curl -s http://localhost:5109/health
        echo ""
    else
        echo "❌ Flask health check failed"
        echo ""
    fi
    
    # Test Grafana
    echo "🔍 Testing Grafana..."
    if curl -s -f http://localhost:3000/api/health > /dev/null 2>&1; then
        echo "✅ Grafana is accessible"
        echo ""
    else
        echo "⚠️  Grafana not ready yet (may still be starting)"
        echo ""
    fi
    
    # Check supervisor status
    echo "🔍 Checking supervisor processes..."
    docker-compose exec -T backend_server supervisorctl status || echo "Could not check supervisor status"
    echo ""
    
    # Show recent logs
    echo "📋 Recent logs (last 20 lines):"
    docker-compose logs --tail=20 backend_server
    echo ""
    
else
    echo "❌ backend_server container is not running"
    echo ""
    echo "Start with: ./scripts/docker-run.sh"
    exit 1
fi

