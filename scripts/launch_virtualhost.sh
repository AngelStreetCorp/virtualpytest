#!/bin/bash

# VirtualPyTest Host Launch Script - Delegates to setup/local/launch_host.sh
echo "🔧 Starting VirtualPyTest Host Client..."

# Get the script directory and navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "$PROJECT_ROOT/README.md" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    exit 1
fi

# Check if launch_host.sh exists
LAUNCH_HOST_SCRIPT="$PROJECT_ROOT/setup/local/launch_host.sh"
if [ ! -f "$LAUNCH_HOST_SCRIPT" ]; then
    echo "❌ Host launch script not found: $LAUNCH_HOST_SCRIPT"
    exit 1
fi

# Make sure the script is executable
chmod +x "$LAUNCH_HOST_SCRIPT"

# Delegate to launch_host.sh
echo "🔄 Delegating to setup/local/launch_host.sh..."
exec "$LAUNCH_HOST_SCRIPT"