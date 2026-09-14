#!/bin/bash

# VirtualPyTest - Test Backend Server
# This script tests if the backend server and services are running properly

set -e

echo "🧪 Testing VirtualPyTest Backend Server..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test backend server health endpoint
echo "🌐 Testing backend server health endpoint (localhost:5109/health)..."
if curl -f -s --max-time 10 http://localhost:5109/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Backend server is responding on port 5109${NC}"
else
    echo -e "${RED}❌ Backend server is not responding on port 5109${NC}"
    echo -e "${YELLOW}   Make sure the server is running: sudo systemctl start vpt-server${NC}"
    exit 1
fi

echo ""

# Test vpt-server service status
echo "🔧 Checking vpt-server service status..."
if systemctl is-active --quiet vpt-server; then
    echo -e "${GREEN}✅ vpt-server service is running${NC}"
else
    echo -e "${RED}❌ vpt-server service is not running${NC}"
    echo -e "${YELLOW}   Start service: sudo systemctl start vpt-server${NC}"
    echo -e "${YELLOW}   Check status: sudo systemctl status vpt-server${NC}"
    exit 1
fi

echo ""

# Test vpt-heatmap service status
echo "🔥 Checking vpt-heatmap service status..."
if systemctl is-active --quiet vpt-heatmap; then
    echo -e "${GREEN}✅ vpt-heatmap service is running${NC}"
else
    echo -e "${RED}❌ vpt-heatmap service is not running${NC}"
    echo -e "${YELLOW}   Start service: sudo systemctl start vpt-heatmap${NC}"
    echo -e "${YELLOW}   Check status: sudo systemctl status vpt-heatmap${NC}"
    exit 1
fi

echo ""
# Test discard services status
echo "🧠 Checking discard services status..."
if systemctl is-active --quiet vpt-discard-scripts; then
    echo -e "${GREEN}✅ vpt-discard-scripts service is running${NC}"
else
    echo -e "${YELLOW}ℹ️ vpt-discard-scripts service is not running (optional by default)${NC}"
    echo -e "${YELLOW}   Start service if needed: sudo systemctl start vpt-discard-scripts${NC}"
    echo -e "${YELLOW}   Enable on boot (expert): sudo systemctl enable vpt-discard-scripts${NC}"
fi

if systemctl is-active --quiet vpt-discard-incidents; then
    echo -e "${GREEN}✅ vpt-discard-incidents service is running${NC}"
else
    echo -e "${YELLOW}ℹ️ vpt-discard-incidents service is not running (optional by default)${NC}"
    echo -e "${YELLOW}   Start service if needed: sudo systemctl start vpt-discard-incidents${NC}"
    echo -e "${YELLOW}   Enable on boot (expert): sudo systemctl enable vpt-discard-incidents${NC}"
fi

echo ""
echo -e "${GREEN}🎉 All services are running properly!${NC}"
echo ""
echo "📊 Service Status Summary:"
echo "   • Backend Server: Running on port 5109"
echo "   • vpt-server service: Active"
echo "   • vpt-heatmap service: Active"
if systemctl is-active --quiet vpt-discard-scripts; then
    echo "   • vpt-discard-scripts service: Active"
else
    echo "   • vpt-discard-scripts service: Optional/Inactive"
fi
if systemctl is-active --quiet vpt-discard-incidents; then
    echo "   • vpt-discard-incidents service: Active"
else
    echo "   • vpt-discard-incidents service: Optional/Inactive"
fi
