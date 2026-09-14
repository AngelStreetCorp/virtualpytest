#!/bin/bash

# VirtualPyTest - Core Installation
# Installs only core components: frontend, backend_server, backend_host

set -e

echo "🔥 VirtualPyTest Core Installation"
echo "📦 Installing core components: frontend, backend_server, backend_host"
echo ""

# Get to project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STANDARD_ROOT="/opt/virtualpytest"

# Load shared bootstrap functions (needed for setup functions)
source "$SCRIPT_DIR/shared/bootstrap.sh"

# Setup for code-dependent installer (creates user, directory, copies project)
# This handles everything: user creation, /opt/virtualpytest, and copying code
setup_for_code_installer "$CURRENT_ROOT"

# If we're running from a different location, re-execute from standard location
if [ "$CURRENT_ROOT" != "$STANDARD_ROOT" ]; then
    echo "📁 Installation prepared from: $CURRENT_ROOT"
    echo "🎯 Project copied to: $STANDARD_ROOT"
    echo "🔄 Re-executing installation from standard location..."
    echo ""
    
    # Re-execute this script from the standard location
    exec "$STANDARD_ROOT/setup/local/linux/install_core.sh" "$@"
fi

# We're now in the standard location
PROJECT_ROOT="$STANDARD_ROOT"
cd "$PROJECT_ROOT"

# Final verification
if [ ! -f "README.md" ] || [ ! -d "shared" ]; then
    echo "❌ Could not find virtualpytest project in standard location: $PROJECT_ROOT"
    exit 1
fi

echo "✅ Running from standard VirtualPyTest location: $PROJECT_ROOT"

# Local installation - Linux only
VPT_OS="linux"
VPT_INSTALL_SERVER_SCRIPT="linux/backend_server/install_server.sh"
VPT_INSTALL_HOST_SCRIPT="linux/backend_host/install_host.sh"
VPT_INSTALL_FRONTEND_SCRIPT="linux/frontend/install_frontend.sh"

# Make scripts executable
if command -v find >/dev/null 2>&1; then
    if [ -w ./setup/local/linux ]; then
        find ./setup/local/linux -type f -name "install*.sh" -exec chmod +x {} +
    elif command -v sudo >/dev/null 2>&1; then
        sudo find ./setup/local/linux -type f -name "install*.sh" -exec chmod +x {} +
    else
        echo "⚠️ Warning: Cannot chmod install scripts (no write access and sudo unavailable)."
    fi
else
    chmod +x ./setup/local/linux/*/install*.sh 2>/dev/null || true
fi

# Install system requirements
echo "0️⃣ Installing system requirements..."
if [ -f "./setup/local/linux/shared/install_requirements.sh" ]; then
    ./setup/local/linux/shared/install_requirements.sh
else
    echo "⚠️ Warning: setup/local/linux/shared/install_requirements.sh not found"
fi

# Set up permissions
echo ""
echo "🔐 Setting up system permissions..."
if command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then
        sudo ./setup/local/linux/backend_host/setup_permissions.sh --user "$(whoami)"
    else
        echo "⚠️ Permission setup requires sudo. Run manually if needed:"
        echo "   sudo ./setup/local/linux/backend_host/setup_permissions.sh --user $(whoami)"
    fi
else
    echo "⚠️ sudo not available. Skipping permission setup."
fi

# Set up environment files
echo ""
echo "📄 Setting up environment files..."
copy_env_if_missing() {
    local src="$1"
    local dst="$2"

    [ -f "$src" ] || return 0
    [ ! -f "$dst" ] || return 0

    if [ -w "$(dirname "$dst")" ]; then
        cp "$src" "$dst"
    elif command -v sudo >/dev/null 2>&1; then
        sudo cp "$src" "$dst"
        sudo chown vpt_user:vpt_user "$dst" 2>/dev/null || true
    else
        echo "⚠️ Could not create $dst (no write access and sudo unavailable)"
    fi
}

copy_env_if_missing ".env.example" ".env"
copy_env_if_missing "backend_host/src/.env.example" "backend_host/src/.env"
copy_env_if_missing "frontend/.env.example" "frontend/.env"
# Fill URLs, API_KEY and (when a local Supabase exists) its keys. No database on this
# machine? set SUPABASE_* in .env by hand afterwards — the script says so.
./setup/local/linux/shared/write_env.sh

# Install core components
echo ""
echo "1️⃣ Installing shared library..."
./setup/local/linux/shared/install_shared.sh

echo ""
echo "2️⃣ Installing backend_server..."
./setup/local/"$VPT_INSTALL_SERVER_SCRIPT"

echo ""
echo "3️⃣ Installing backend_host..."
./setup/local/"$VPT_INSTALL_HOST_SCRIPT"

echo ""
echo "4️⃣ Installing frontend..."
./setup/local/"$VPT_INSTALL_FRONTEND_SCRIPT"

echo ""
echo "🎉 Core VirtualPyTest installation completed!"
echo ""
echo "🚀 Launch with: ./scripts/launch_virtualpytest.sh"
echo "🔧 Individual services: ./setup/local/launch_server.sh, ./setup/local/launch_host.sh, ./setup/local/launch_frontend.sh"
