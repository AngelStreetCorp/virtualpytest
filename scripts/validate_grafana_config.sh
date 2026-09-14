#!/bin/bash

# Grafana Configuration Validation Script
echo "🔍 Validating Grafana configuration..."

# Check if separate Grafana folder exists
if [ -d "infra/monitoring/grafana/config" ]; then
    echo "✅ Separate infra/monitoring/grafana/config directory exists"
else
    echo "❌ Missing infra/monitoring/grafana/config directory"
    exit 1
fi

# Check if grafana.ini exists
if [ -f "infra/monitoring/grafana/config/grafana.ini" ]; then
    echo "✅ grafana.ini found in separate folder"
else
    echo "❌ Missing infra/monitoring/grafana/config/grafana.ini"
    exit 1
fi

# Check if grafana data directory exists
if [ -d "infra/monitoring/grafana/data" ]; then
    echo "✅ Separate infra/monitoring/grafana/data directory exists"
else
    echo "❌ Missing infra/monitoring/grafana/data directory"
    exit 1
fi

echo ""
echo "🎉 All Grafana configuration checks passed!"
echo ""
echo "📋 Summary:"
echo "   • Grafana config: infra/monitoring/grafana/config/grafana.ini (separate folder)"
echo "   • Grafana data: infra/monitoring/grafana/data/ (separate folder)"
echo "   • Docker setup uses Grafana files via setup/docker/ and install scripts"
echo ""
echo "🚀 Ready to build and run!"
