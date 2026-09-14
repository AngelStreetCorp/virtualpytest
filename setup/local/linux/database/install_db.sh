#!/bin/bash

# VirtualPyTest Database Installation (Autonomous)
# Installs Supabase (includes PostgreSQL + Auth + Storage + API)
# Standard approach: Creates user, copies project to /opt, installs from there
#
# Usage: ./install_db.sh [DATA_DIR]
#   DATA_DIR: Optional path for Supabase data (default: /data/supabase)

set -e

echo "🐧 Installing VirtualPyTest Database (Supabase with PostgreSQL)"
echo "   Architecture: Supabase manages PostgreSQL in Docker containers"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="/opt/virtualpytest"

# Parse arguments
SUPABASE_DATA_DIR="${1:-/data/supabase}"

echo "📁 Configuration:"
echo "   • Project code: $PROJECT_ROOT"
echo "   • Supabase data: $SUPABASE_DATA_DIR"
echo ""

# Load shared bootstrap functions
if [ -f "$SCRIPT_DIR/../shared/bootstrap.sh" ]; then
    source "$SCRIPT_DIR/../shared/bootstrap.sh"
else
    echo "❌ Bootstrap script not found"
    exit 1
fi

# Setup standard environment (user + directory + full project copy)
setup_for_code_installer "$SOURCE_ROOT"

# Change to project root
cd "$PROJECT_ROOT"

# Install Supabase (includes PostgreSQL, Auth, Storage, API)
if [[ -f "$SCRIPT_DIR/install_supabase.sh" ]]; then
    echo "🔗 Installing Supabase (PostgreSQL + Auth + Storage + API)..."
    "$SCRIPT_DIR/install_supabase.sh" "$SUPABASE_DATA_DIR"
    if [ $? -eq 0 ]; then
        echo "✅ Supabase installation completed"
    else
        echo "❌ Supabase installation failed"
        exit 1
    fi
else
    echo "❌ install_supabase.sh not found in $SCRIPT_DIR"
    exit 1
fi

echo ""
echo "🎉 Complete VirtualPyTest Database Setup Finished!"
echo "   ✅ Supabase installed with PostgreSQL, Auth, Storage, and API"
echo "   ✅ Database migrations applied"
echo "   ✅ All database components are operational"
echo ""
echo "📁 Installation Summary:"
echo "   • Project code: $PROJECT_ROOT"
echo "   • Supabase data: $SUPABASE_DATA_DIR"
echo "   • Systemd service: supabase.service (auto-starts on boot)"