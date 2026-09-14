#!/bin/bash

# VirtualPyTest Launch Script - Delegates to setup/local/linux/launch_core.sh
# Usage: ./launch_virtualpytest.sh
# Launches the core components of the VirtualPyTest system
# (backend_server, backend_host, frontend)

# Get the script directory and navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "$PROJECT_ROOT/README.md" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    exit 1
fi

# Check if launch_core.sh exists
LAUNCH_CORE_SCRIPT="$PROJECT_ROOT/setup/local/linux/launch_core.sh"
if [ ! -f "$LAUNCH_CORE_SCRIPT" ]; then
    echo "❌ Launch script not found: $LAUNCH_CORE_SCRIPT"
    exit 1
fi

# Make sure the script is executable
chmod +x "$LAUNCH_CORE_SCRIPT"
exec "$LAUNCH_CORE_SCRIPT"
