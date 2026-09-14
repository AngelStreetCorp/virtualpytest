#!/bin/bash

# VirtualPyTest - Launch Frontend Production Server
echo "Building and serving VirtualPyTest Frontend (Production)..."

set -e

# Use standardized VirtualPyTest directory
PROJECT_ROOT="/opt/virtualpytest"

# Ensure the directory exists
if [ ! -d "$PROJECT_ROOT" ]; then
    echo "VirtualPyTest directory not found at $PROJECT_ROOT"
    echo "Please run: sudo ./setup/local/linux/shared/create_vpt_user.sh"
    echo "Then copy/clone VirtualPyTest to $PROJECT_ROOT"
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d "frontend" ]; then
    echo "Could not find virtualpytest project root directory"
    echo "Expected: $PROJECT_ROOT"
    exit 1
fi

# Check if node_modules exists
if [ ! -d "frontend/node_modules" ]; then
    echo "Frontend dependencies not installed. Please run: ./setup/local/linux/frontend/install_frontend.sh"
    exit 1
fi

# Source port checking functions
source "$PROJECT_ROOT/setup/local/linux/shared/check_and_open_port.sh"

# Port 5073 (same as dev to prevent conflicts)
FRONTEND_PORT=5073

echo "Frontend Configuration:"
echo "   Port: $FRONTEND_PORT"
echo "   Mode: Production (serve)"

# Check port availability and kill conflicting processes
check_port_availability "$FRONTEND_PORT" "frontend"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Cleanup function
cleanup() {
    echo -e "\n${RED}Shutting down frontend...${NC}"
    if [ -f /tmp/frontend_prod.pid ]; then
        PID=$(cat /tmp/frontend_prod.pid)
        if kill -0 "$PID" 2>/dev/null; then
            kill -TERM "$PID" 2>/dev/null
            sleep 2
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null
            fi
        fi
        rm -f /tmp/frontend_prod.pid
    fi
    echo -e "${RED}Frontend stopped${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

cd frontend

# Build if dist doesn't exist or --build flag passed
if [ ! -d "dist" ] || [ "$1" == "--build" ]; then
    echo "Building frontend..."
    npm run build
    echo "Build complete."
fi

echo "=================================================================================="
echo -e "${GREEN}Starting frontend production server...${NC}"
echo "Press Ctrl+C to stop"
echo "=================================================================================="

# Start serve with real-time output
npm run start 2>&1 | {
    while IFS= read -r line; do
        printf "${GREEN}[FRONTEND-PROD]${NC} %s\n" "$line"
    done
} &

FRONTEND_PID=$!
echo $FRONTEND_PID > /tmp/frontend_prod.pid

echo "Started Frontend with PID: $FRONTEND_PID"
echo "Frontend: http://localhost:$FRONTEND_PORT"
echo "=================================================================================="

# Wait for the process
wait $FRONTEND_PID
