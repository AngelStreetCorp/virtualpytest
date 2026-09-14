#!/bin/bash

# VirtualPyTest - Launch Grafana Locally
# This script starts Grafana for local development

set -e

echo "📊 Starting Grafana for VirtualPyTest local development..."

# Get to project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Change to project root
cd "$PROJECT_ROOT"

# Load credentials from .env if it exists
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Check if Grafana is installed
if ! command -v grafana-server &> /dev/null; then
    echo "❌ Grafana is not installed"
    echo "Please run: ./setup/local/linux/monitoring/install_grafana.sh"
    exit 1
fi

# Check if Grafana is configured (Linux only)
GRAFANA_CONF="/etc/grafana/grafana.ini"

if [ ! -f "$GRAFANA_CONF" ]; then
    echo "❌ Grafana configuration not found at $GRAFANA_CONF"
    echo "Please run: ./setup/local/linux/monitoring/install_grafana.sh"
    exit 1
fi

# Check if PostgreSQL is running (for metrics storage)
if ! pg_isready &> /dev/null; then
    echo "🐘 Starting PostgreSQL..."
    sudo systemctl start postgresql
    sleep 3
fi

# Kill any existing Grafana processes on port 3000
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "🛑 Stopping existing Grafana process..."
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "🚀 Starting Grafana server..."
echo "📊 Grafana will be available at: http://localhost:3000"
echo "🔑 Login: ${GRAFANA_ADMIN_USER:-admin} / (password set during installation)"
echo "💡 Press Ctrl+C to stop"

# Start Grafana server using system configuration (Linux)
grafana-server \
    --config="$GRAFANA_CONF" \
    --homepath="/usr/share/grafana" \
    web