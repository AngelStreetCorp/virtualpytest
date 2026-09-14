#!/bin/bash

# VirtualPyTest Nginx Proxy Test Script
# Simple endpoint testing to verify nginx proxy is working

set -e

# Default nginx server IP (change this to your nginx server IP)
NGINX_IP="${1:-localhost}"

echo "🧪 Testing VirtualPyTest Nginx Proxy"
echo "🌐 Nginx server: $NGINX_IP"
echo ""

# Test main application
echo "📱 Testing main application..."
if curl -s -f "http://$NGINX_IP/" > /dev/null; then
    echo "✅ Main application: OK"
else
    echo "❌ Main application: FAILED"
fi

# Test API health
echo "🔧 Testing API health..."
if curl -s -f "http://$NGINX_IP/server/health" > /dev/null; then
    echo "✅ API health: OK"
else
    echo "❌ API health: FAILED"
fi

# Test nginx health
echo "⚙️ Testing nginx health..."
if curl -s -f "http://$NGINX_IP/health" > /dev/null; then
    echo "✅ Nginx health: OK"
else
    echo "❌ Nginx health: FAILED"
fi

echo ""
echo "🎉 Proxy testing complete!"
echo ""
echo "📋 Tested URLs:"
echo "   • http://$NGINX_IP/"
echo "   • http://$NGINX_IP/server/health"
echo "   • http://$NGINX_IP/health"
echo ""
echo "💡 If tests fail, check nginx config and backend services"