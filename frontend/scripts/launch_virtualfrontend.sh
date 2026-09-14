#!/bin/bash

# VirtualPyTest Frontend Launch Script - Delegates to setup/local/launch_frontend.sh
echo "⚛️ Starting VirtualPyTest Frontend..."

# Get the script directory and navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "$PROJECT_ROOT/README.md" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    exit 1
fi

# Check if launch_frontend.sh exists
LAUNCH_FRONTEND_SCRIPT="$PROJECT_ROOT/setup/local/launch_frontend.sh"
if [ ! -f "$LAUNCH_FRONTEND_SCRIPT" ]; then
    echo "❌ Frontend launch script not found: $LAUNCH_FRONTEND_SCRIPT"
    exit 1
fi

# Make sure the script is executable
chmod +x "$LAUNCH_FRONTEND_SCRIPT"

# Delegate to launch_frontend.sh
echo "🔄 Delegating to setup/local/launch_frontend.sh..."
exec "$LAUNCH_FRONTEND_SCRIPT" 