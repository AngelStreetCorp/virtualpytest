#!/bin/bash

# VirtualPyTest Server Launch Script
# Launches only the backend_server component

echo "🚀 Starting VirtualPyTest Server..."

set -e

# Get to project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "README.md" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    exit 1
fi

# Check dependencies
if [ ! -d "venv" ]; then
    echo "❌ Missing Python virtual environment (venv/)"
    echo "   → Fix: ./setup/local/install_python_deps.sh"
    exit 1
fi

# Detect Python executable
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ No Python executable found!"
    exit 1
fi

echo "🐍 Using Python: $PYTHON_CMD"

# Activate virtual environment
source venv/bin/activate

# Set up environment variables
export PYTHONPATH="$PROJECT_ROOT/shared/lib"

# Colors
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Function to run command with colored prefix
run_with_prefix() {
    local prefix="$1"
    local color="$2"
    local directory="$3"
    shift 3

    cd "$directory"

    # Run command with real-time output
    {
        exec $PYTHON_CMD -u "${@:2}" 2>&1
    } | {
        while IFS= read -r line; do
            printf "${color}[${prefix}]${NC} %s\n" "$line"
        done
    } &

    local pid=$!
    echo "Started server with PID: $pid"

    cd "$PROJECT_ROOT"
}

# Cleanup function
cleanup() {
    echo -e "\n${RED}🛑 Shutting down server...${NC}"
    jobs -p | xargs -r kill -9 2>/dev/null || true
    echo -e "${RED}✅ Server stopped${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Check and clear port 5109
if lsof -ti:5109 > /dev/null 2>&1; then
    echo "🛑 Killing processes on port 5109..."
    lsof -ti:5109 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

echo "✅ Port 5109 is available"

# Check vpt-heatmap service
if systemctl is-active --quiet vpt-heatmap 2>/dev/null; then
    echo "✅ Heatmap processor service is running"
else
    echo "🔄 Starting heatmap processor service..."
    sudo systemctl start vpt-heatmap 2>/dev/null || echo "⚠️ Could not start heatmap processor service"
fi

# Discard workers are optional and disabled by default
if systemctl is-active --quiet vpt-discard-scripts 2>/dev/null; then
    echo "✅ Analyzer discard scripts service is running"
else
    echo "ℹ️ Analyzer discard scripts service is disabled/off (expected by default)"
fi

if systemctl is-active --quiet vpt-discard-incidents 2>/dev/null; then
    echo "✅ Analyzer discard incidents service is running"
else
    echo "ℹ️ Analyzer discard incidents service is disabled/off (expected by default)"
fi

echo "📺 Starting server..."
echo "💡 Press Ctrl+C to stop"
echo "=================================================================================="

# Start backend_server
echo -e "${BLUE}🔵 Starting backend_server...${NC}"
run_with_prefix "SERVER" "$BLUE" "$PROJECT_ROOT/backend_server" python src/app.py
sleep 3

echo "=================================================================================="
echo -e "${NC}✅ Server started! Watching for logs...${NC}"
echo -e "${NC}🌐 URL: http://localhost:5109${NC}"
echo "=================================================================================="

# Wait for background job
wait
