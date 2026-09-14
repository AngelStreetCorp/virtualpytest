#!/bin/bash

# VirtualPyTest Launch Script - Server + Frontend
echo "🚀 Starting VirtualPyTest Server + Frontend..."

# Get the script directory and navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "$PROJECT_ROOT/README.md" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    exit 1
fi

# Check if required launch scripts exist
LAUNCH_SERVER_SCRIPT="$PROJECT_ROOT/setup/local/launch_server.sh"
LAUNCH_FRONTEND_SCRIPT="$PROJECT_ROOT/setup/local/launch_frontend.sh"

if [ ! -f "$LAUNCH_SERVER_SCRIPT" ]; then
    echo "❌ Server launch script not found: $LAUNCH_SERVER_SCRIPT"
    exit 1
fi

if [ ! -f "$LAUNCH_FRONTEND_SCRIPT" ]; then
    echo "❌ Frontend launch script not found: $LAUNCH_FRONTEND_SCRIPT"
    exit 1
fi

# Make sure the scripts are executable
chmod +x "$LAUNCH_SERVER_SCRIPT"
chmod +x "$LAUNCH_FRONTEND_SCRIPT"

# Colors for output
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Check if Redis is running (required for agent Event Bus)
echo -e "${BLUE}🔍 Checking Redis status...${NC}"
if command -v redis-cli &> /dev/null; then
    if ! redis-cli ping &> /dev/null; then
        echo -e "${YELLOW}⚠️  Redis is not running. The agent system requires Redis for the Event Bus.${NC}"
        echo -e "${BLUE}🚀 Starting Redis...${NC}"
        
        # Try to start Redis based on OS
        if command -v systemctl &> /dev/null; then
            # Linux with systemd
            echo -e "${BLUE}Using systemctl to start Redis...${NC}"
            sudo systemctl start redis-server 2>/dev/null || sudo systemctl start redis 2>/dev/null
            sleep 2
            if redis-cli ping &> /dev/null; then
                echo -e "${GREEN}✅ Redis started successfully${NC}"
                # Enable to start on boot
                sudo systemctl enable redis-server 2>/dev/null || sudo systemctl enable redis 2>/dev/null
            else
                echo -e "${RED}❌ Failed to start Redis via systemctl${NC}"
                exit 1
            fi
        elif command -v service &> /dev/null; then
            # Linux with service command
            echo -e "${BLUE}Using service command to start Redis...${NC}"
            sudo service redis-server start 2>/dev/null || sudo service redis start 2>/dev/null
            sleep 2
            if redis-cli ping &> /dev/null; then
                echo -e "${GREEN}✅ Redis started successfully${NC}"
            else
                echo -e "${RED}❌ Failed to start Redis via service${NC}"
                exit 1
            fi
        elif command -v redis-server &> /dev/null; then
            # Start Redis directly in background
            redis-server --daemonize yes
            sleep 2
            if redis-cli ping &> /dev/null; then
                echo -e "${GREEN}✅ Redis started successfully${NC}"
            else
                echo -e "${RED}❌ Failed to start Redis${NC}"
                exit 1
            fi
        else
            echo -e "${RED}❌ Could not start Redis. Please start it manually:${NC}"
            echo -e "${RED}   sudo systemctl start redis-server${NC}"
            echo -e "${RED}   OR: redis-server --daemonize yes${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✅ Redis is running${NC}"
    fi
else
    echo -e "${RED}❌ Redis is not installed. The agent system requires Redis.${NC}"
    echo -e "${RED}   Install with:${NC}"
    echo -e "${RED}   - Ubuntu/Debian: sudo apt-get install redis-server${NC}"
    echo -e "${RED}   - RHEL/CentOS:   sudo yum install redis${NC}"
    echo -e "${RED}   - Fedora:        sudo dnf install redis${NC}"
    echo -e "${RED}   Then start with: sudo systemctl start redis-server${NC}"
    exit 1
fi
echo ""

# Array to store background process PIDs
declare -a PIDS=()

# Enhanced cleanup function
cleanup() {
    echo -e "\n${RED}🛑 Shutting down all services...${NC}"
    
    # Kill all background processes gracefully first
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping process $pid..."
            kill -TERM "$pid" 2>/dev/null
        fi
    done
    
    # Wait a moment for graceful shutdown
    sleep 3
    
    # Force kill any remaining processes
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Force killing process $pid..."
            kill -9 "$pid" 2>/dev/null
        fi
    done
    
    # Kill any remaining background jobs
    jobs -p | xargs -r kill -9 2>/dev/null
    
    echo -e "${RED}✅ All services stopped${NC}"
    echo -e "${YELLOW}💡 Note: Redis is still running (may be used by other services)${NC}"
    echo -e "${YELLOW}   To stop Redis: sudo systemctl stop redis-server${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "📺 Starting services with real-time unified logging..."
echo "💡 Press Ctrl+C to stop all services"
echo "💡 Logs will appear with colored prefixes: [SERVER], [FRONTEND]"
echo "=================================================================================="

# Start server in background
echo -e "${BLUE}🔵 Starting Backend Server...${NC}"
"$LAUNCH_SERVER_SCRIPT" &
SERVER_PID=$!
PIDS+=($SERVER_PID)
echo "Started Server with PID: $SERVER_PID"
sleep 3

# Start frontend in background
echo -e "${YELLOW}🟡 Starting Frontend...${NC}"
"$LAUNCH_FRONTEND_SCRIPT" &
FRONTEND_PID=$!
PIDS+=($FRONTEND_PID)
echo "Started Frontend with PID: $FRONTEND_PID"

echo "=================================================================================="
echo -e "${NC}✅ All services started! Watching for logs...${NC}"
echo -e "${NC}💡 You should see logs with colored prefixes appearing above${NC}"
echo -e "${NC}🌐 URLs:${NC}"
echo -e "${NC}   Frontend: http://localhost:5073${NC}"
echo -e "${NC}   backend_server: http://localhost:5109${NC}"
echo "=================================================================================="

# Wait for all background jobs
wait