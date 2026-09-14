#!/bin/bash

# VirtualPyTest - Force Stop All Processes (Enhanced)
# This script aggressively stops ALL VirtualPyTest processes and clears ports
# Use this when the regular stop_all_local.sh doesn't work completely

set -e

echo "🛑 Force Stopping ALL VirtualPyTest Processes..."
echo "⚠️  This will aggressively terminate all related processes"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to kill processes by pattern with confirmation
kill_by_pattern() {
    local pattern="$1"
    local description="$2"
    
    echo -e "\n${YELLOW}🔍 Checking for $description...${NC}"
    
    # Find processes matching the pattern
    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    
    if [ -n "$pids" ]; then
        echo -e "${RED}Found processes: $pids${NC}"
        echo "Killing $description..."
        
        # Try graceful termination first
        echo "$pids" | xargs -r kill -TERM 2>/dev/null || true
        sleep 2
        
        # Force kill any remaining
        local remaining=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$remaining" ]; then
            echo "Force killing remaining processes: $remaining"
            echo "$remaining" | xargs -r kill -9 2>/dev/null || true
        fi
        
        echo -e "${GREEN}✅ $description stopped${NC}"
    else
        echo -e "${GREEN}ℹ️  No $description processes found${NC}"
    fi
}

# Function to kill processes on specific ports
kill_port_processes() {
    local port="$1"
    local service="$2"
    
    echo -e "\n${YELLOW}🔍 Checking port $port ($service)...${NC}"
    
    if lsof -ti:$port > /dev/null 2>&1; then
        echo -e "${RED}🛑 Killing processes on port $port...${NC}"
        lsof -ti:$port | xargs kill -9 2>/dev/null || true
        sleep 1
        
        # Verify port is clear
        if lsof -ti:$port > /dev/null 2>&1; then
            echo -e "${RED}⚠️  Port $port still in use after cleanup${NC}"
        else
            echo -e "${GREEN}✅ Port $port is now available${NC}"
        fi
    else
        echo -e "${GREEN}ℹ️  Port $port is available${NC}"
    fi
}

echo "=================================================================================="
echo "🎯 PHASE 1: Kill VirtualPyTest processes by pattern"
echo "=================================================================================="

# Kill all VirtualPyTest Python processes
kill_by_pattern "python.*app\.py" "Python app processes"
kill_by_pattern "python.*backend_server" "Backend server processes"
kill_by_pattern "python.*backend_host" "Backend host processes"
kill_by_pattern "python.*capture_monitor\.py" "Capture monitor processes"

# Kill all VirtualPyTest Node/npm processes
kill_by_pattern "npm.*run.*dev" "NPM dev processes"
kill_by_pattern "node.*vite" "Vite dev server processes"
kill_by_pattern "node.*esbuild" "ESBuild processes"

# Kill launch scripts
kill_by_pattern "bash.*launch_all\.sh" "Launch script processes"
kill_by_pattern "bash.*launch_.*\.sh" "Individual launch scripts"

echo ""
echo "=================================================================================="
echo "🎯 PHASE 2: Clear VirtualPyTest ports"
echo "=================================================================================="

# Clear all VirtualPyTest ports
kill_port_processes "5109" "backend_server"
kill_port_processes "6109" "backend_host"  
kill_port_processes "3000" "frontend"
kill_port_processes "3001" "grafana"

echo ""
echo "=================================================================================="
echo "🎯 PHASE 3: Clean up PID files and background jobs"
echo "=================================================================================="

echo -e "${YELLOW}🧹 Cleaning up PID files...${NC}"
rm -f /tmp/backend_server.pid /tmp/backend_host.pid /tmp/frontend.pid
echo -e "${GREEN}✅ PID files cleaned${NC}"

echo -e "${YELLOW}🧹 Killing any remaining background jobs...${NC}"
jobs -p | xargs -r kill -9 2>/dev/null || true
echo -e "${GREEN}✅ Background jobs cleaned${NC}"

echo ""
echo "=================================================================================="
echo "🎯 PHASE 4: Final verification"
echo "=================================================================================="

echo -e "${YELLOW}📊 Final Process Status Check:${NC}"

# Check for any remaining VirtualPyTest processes
remaining_processes=$(ps aux | grep -E "(python.*app\.py|npm.*run.*dev|node.*vite|virtualpytest|capture_monitor)" | grep -v grep | wc -l)

if [ "$remaining_processes" -gt 0 ]; then
    echo -e "${RED}⚠️  Warning: $remaining_processes VirtualPyTest processes may still be running:${NC}"
    ps aux | grep -E "(python.*app\.py|npm.*run.*dev|node.*vite|virtualpytest|capture_monitor)" | grep -v grep
    echo ""
    echo -e "${YELLOW}💡 You may need to manually kill these processes or reboot the system${NC}"
else
    echo -e "${GREEN}✅ No VirtualPyTest processes found${NC}"
fi

# Check port status
echo -e "\n${YELLOW}📊 Port Status:${NC}"
for port in 5109 6109 3000 3001; do
    if lsof -ti:$port > /dev/null 2>&1; then
        echo -e "${RED}❌ Port $port: still in use${NC}"
    else
        echo -e "${GREEN}✅ Port $port: available${NC}"
    fi
done

echo ""
echo "=================================================================================="
echo -e "${GREEN}🎉 Force cleanup completed!${NC}"
echo -e "${GREEN}You can now safely launch VirtualPyTest${NC}"
echo "=================================================================================="
