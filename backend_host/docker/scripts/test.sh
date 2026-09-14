#!/bin/bash
# Test backend_host health

set -e

echo "🩺 Testing backend_host health..."
echo ""

# Test Flask API
echo "Testing Flask API (http://localhost:6109/host/system/health)..."
if curl -f -s http://localhost:6109/host/system/health > /dev/null; then
    echo "✅ Flask API is healthy"
    echo ""
    echo "Response:"
    curl -s http://localhost:6109/host/system/health | python3 -m json.tool
else
    echo "❌ Flask API is not responding"
    exit 1
fi

echo ""
echo "Testing NoVNC (http://localhost:6080)..."
if curl -f -s http://localhost:6080 > /dev/null; then
    echo "✅ NoVNC is accessible"
else
    echo "❌ NoVNC is not responding"
    exit 1
fi

echo ""
echo "✅ All services are healthy!"

