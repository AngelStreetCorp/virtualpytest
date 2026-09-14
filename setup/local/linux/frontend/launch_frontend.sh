#!/bin/bash

# VirtualPyTest - Launch Frontend with Real-time Logs
echo "⚛️ Starting VirtualPyTest Frontend with Real-time Logs..."

set -e

# Use standardized VirtualPyTest directory
PROJECT_ROOT="/opt/virtualpytest"

# Ensure the directory exists
if [ ! -d "$PROJECT_ROOT" ]; then
    echo "❌ VirtualPyTest directory not found at $PROJECT_ROOT"
    echo "Please run: sudo ./setup/local/linux/shared/create_vpt_user.sh"
    echo "Then copy/clone VirtualPyTest to $PROJECT_ROOT"
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d "frontend" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Expected: $PROJECT_ROOT"
    exit 1
fi

# Check if node_modules exists
if [ ! -d "frontend/node_modules" ]; then
    echo "❌ Frontend dependencies not installed. Please run: ./setup/local/install_frontend.sh"
    exit 1
fi

# Source port checking functions
source "$PROJECT_ROOT/setup/local/linux/shared/check_and_open_port.sh"

# Get FRONTEND_PORT from frontend .env file (Vite uses PORT env var)
FRONTEND_ENV_FILE="$PROJECT_ROOT/frontend/.env"
FRONTEND_PORT=$(get_port_from_env "$FRONTEND_ENV_FILE" "PORT" "3000")

echo "📋 Frontend Configuration:"
echo "   Port: $FRONTEND_PORT (from $FRONTEND_ENV_FILE)"
echo "   Service: frontend (Vite dev server)"

# Check port availability and kill conflicting processes
check_port_availability "$FRONTEND_PORT" "frontend"

# Colors for output
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Cleanup function
cleanup() {
    echo -e "\n${RED}🛑 Shutting down frontend...${NC}"
    if [ -f /tmp/frontend.pid ]; then
        PID=$(cat /tmp/frontend.pid)
        if kill -0 "$PID" 2>/dev/null; then
            kill -TERM "$PID" 2>/dev/null
            sleep 2
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null
            fi
        fi
        rm -f /tmp/frontend.pid
    fi
    echo -e "${RED}✅ Frontend stopped${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "📺 Starting frontend with real-time logging..."
echo "💡 Press Ctrl+C to stop"
echo "=================================================================================="

# Start frontend with real-time output
cd frontend
echo -e "${YELLOW}🟡 Starting Frontend...${NC}"

# Start the process and capture PID
env FORCE_COLOR=1 npm run dev 2>&1 | {
    while IFS= read -r line; do
        printf "${YELLOW}[FRONTEND]${NC} %s\n" "$line"
    done
} &

FRONTEND_PID=$!
echo $FRONTEND_PID > /tmp/frontend.pid

echo "Started Frontend with PID: $FRONTEND_PID"
echo "🌐 Frontend: http://localhost:$FRONTEND_PORT"
echo "💡 Logs will appear with [FRONTEND] prefix below"
echo "=================================================================================="

# Wait for the process
wait $FRONTEND_PID