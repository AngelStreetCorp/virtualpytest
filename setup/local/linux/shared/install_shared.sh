#!/bin/bash

# VirtualPyTest - Install Shared Library Dependencies
# This script installs the shared library dependencies (no longer a pip package)

set -e

echo "📚 Installing VirtualPyTest Shared Library Dependencies..."

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

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d "shared" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Create virtual environment if it doesn't exist or is incomplete
if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "⚠️ Found incomplete venv directory, removing..."
        sudo rm -rf venv
    fi
    
    echo "🐍 Creating Python virtual environment as vpt_user at $PROJECT_ROOT/venv..."
    sudo -u vpt_user python3 -m venv venv
    
    # Verify venv was created successfully
    if [ ! -f "venv/bin/activate" ]; then
        echo "❌ Failed to create virtual environment at $PROJECT_ROOT/venv"
        echo "Please check that python3-venv is installed: sudo apt install python3-venv"
        exit 1
    fi
    echo "✅ Virtual environment created at $PROJECT_ROOT/venv"
fi

echo "📦 Installing shared library dependencies as vpt_user into $PROJECT_ROOT/venv..."
sudo -u vpt_user bash -c "
    cd '$PROJECT_ROOT'
    source venv/bin/activate
    cd shared
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt
    elif [ -f pyproject.toml ] || [ -f setup.py ]; then
        # Fallback to editable install when a package manifest exists
        pip install -e .
    else
        echo '⚠️ No requirements.txt, setup.py, or pyproject.toml found in shared/. Skipping shared dependency install.'
    fi
"

echo "✅ Shared library dependencies installation completed!"
echo "📁 Installation location: $PROJECT_ROOT"
echo "📁 Virtual environment: $PROJECT_ROOT/venv"
echo "📁 Shared modules are available at: $PROJECT_ROOT/shared" 
