#!/bin/bash

# VirtualPyTest - Install Backend Server (Autonomous)
# This script installs backend_server dependencies and configuration
# This installer is autonomous and will set up the complete environment

set -e

echo "🖥️ Installing VirtualPyTest Backend Server (Autonomous)..."

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="/opt/virtualpytest"
COMPONENT_DIR="$PROJECT_ROOT/backend_server"
TMP_DIR="${TMPDIR:-/tmp}"

# Load shared bootstrap functions
if [ -f "$SCRIPT_DIR/../shared/bootstrap.sh" ]; then
    source "$SCRIPT_DIR/../shared/bootstrap.sh"
else
    echo "❌ Bootstrap script not found"
    exit 1
fi

# Setup for code-dependent installer (creates user, directory, copies project)
setup_for_code_installer "$SOURCE_ROOT"

# Change to project root
cd "$PROJECT_ROOT"

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d "backend_server" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Expected: $PROJECT_ROOT"
    exit 1
fi

# Install system dependencies (base requirements for all Debian/Ubuntu systems)
echo "📦 Installing system dependencies..."
if [ -f "$SCRIPT_DIR/../shared/install_requirements.sh" ]; then
    bash "$SCRIPT_DIR/../shared/install_requirements.sh"
else
    echo "⚠️ Shared requirements script not found, installing basic packages..."
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv python3-dev build-essential gunicorn libpq-dev postgresql-client
fi
echo "✅ System dependencies installed"

# Ensure OpenCV runtime libs are present for optional analyzer workers.
# This prevents runtime import errors like: libGL.so.1 missing.
echo "📦 Installing backend runtime libraries (OpenCV)..."
sudo apt-get install -y libgl1 libglib2.0-0
echo "✅ Backend runtime libraries installed"

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
else
    echo "✅ Virtual environment already exists at $PROJECT_ROOT/venv"
fi

install_backend_server_dependencies() {
    sudo -u vpt_user bash -c "
        cd '$PROJECT_ROOT'
        source venv/bin/activate
        python -m pip install --upgrade pip setuptools wheel
        cd backend_server
        pip install -r requirements.txt
    "
}

# Install backend_server dependencies as vpt_user
echo "📦 Installing backend_server dependencies as vpt_user into $PROJECT_ROOT/venv..."
if install_backend_server_dependencies; then
    echo "✅ Dependencies installed in $PROJECT_ROOT/venv"
else
    echo "⚠️ backend_server dependency install failed. Recreating venv and retrying once..."
    sudo rm -rf "$PROJECT_ROOT/venv"
    sudo -u vpt_user python3 -m venv "$PROJECT_ROOT/venv"
    install_backend_server_dependencies
    echo "✅ Dependencies installed in $PROJECT_ROOT/venv after venv reset"
fi

# Create .env file in project root if it doesn't exist
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        echo "📝 Creating .env file from .env.example..."
        sudo -u vpt_user cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        echo "✅ Created .env file at $PROJECT_ROOT/.env - please configure it with your settings"
    else
        echo "⚠️ No .env.example found - please create .env manually at $PROJECT_ROOT/.env"
    fi
else
    echo "✅ .env file already exists at $PROJECT_ROOT/.env"
fi

# Note: Firewall configuration is handled at the Proxmox level
# Required port for backend server: 5109 TCP (configure in Proxmox)

# Install VirtualPyTest Server Service
echo "🔧 Installing VirtualPyTest Server Service..."
VPT_SERVER_SERVICE_FILE="$PROJECT_ROOT/backend_server/config/services/linux/server.service"

if [ -f "$VPT_SERVER_SERVICE_FILE" ]; then
    # Stop existing service if running
    sudo systemctl stop vpt-server 2>/dev/null || true

    # Process the service template and copy to systemd directory
    # Replace placeholders with actual values
    echo "📝 Processing service template..."
    local_server_tmp="$TMP_DIR/vpt-server.service.tmp"
    if sed -e "s|%PROJECT_ROOT%|$PROJECT_ROOT|g" \
           "$VPT_SERVER_SERVICE_FILE" > "$local_server_tmp" 2>/dev/null; then
        echo "✅ Service file processed successfully"
    else
        echo "❌ Failed to process service file - checking paths..."
        echo "   Service file: $VPT_SERVER_SERVICE_FILE"
        echo "   Project root: $PROJECT_ROOT"
        echo "   Current dir: $(pwd)"
        ls -la "$VPT_SERVER_SERVICE_FILE" 2>/dev/null || echo "   Service file not found"
        exit 1
    fi

    sudo cp "$local_server_tmp" /etc/systemd/system/vpt-server.service
    rm -f "$local_server_tmp"

    # Reload systemd daemon
    sudo systemctl daemon-reload

    # Enable service for auto-start
    sudo systemctl enable vpt-server

    echo "✅ VirtualPyTest Server service installed and enabled"
    echo "   • Service will start automatically on boot"
    echo "   • Runs VirtualPyTest backend server on port 5109"
    echo "   • To start now: sudo systemctl start vpt-server"
    echo "   • To check status: sudo systemctl status vpt-server"
    echo "   • To view logs: sudo journalctl -u vpt-server -f"
else
    echo "⚠️ VPT Server service file not found: $VPT_SERVER_SERVICE_FILE"
fi

# Install Heatmap Processor Service
echo "🔧 Installing Heatmap Processor Service..."
HEATMAP_SERVICE_FILE="$PROJECT_ROOT/backend_server/config/services/linux/vpt-heatmap.service"

if [ -f "$HEATMAP_SERVICE_FILE" ]; then
    # Stop existing service if running
    sudo systemctl stop vpt-heatmap 2>/dev/null || true

    # Process the service template and copy to systemd directory
    # Replace placeholders with actual values
    echo "📝 Processing heatmap service template..."
    local_heatmap_tmp="$TMP_DIR/vpt-heatmap.service.tmp"
    sed -e "s|%PROJECT_ROOT%|$PROJECT_ROOT|g" \
        "$HEATMAP_SERVICE_FILE" > "$local_heatmap_tmp"

    sudo cp "$local_heatmap_tmp" /etc/systemd/system/vpt-heatmap.service
    rm -f "$local_heatmap_tmp"

    # Reload systemd daemon
    sudo systemctl daemon-reload

    # Enable service for auto-start
    sudo systemctl enable vpt-heatmap

    echo "✅ Heatmap Processor service installed and enabled"
    echo "   • Service will start automatically on boot"
    echo "   • Generates 24h circular heatmap buffer every minute"
    echo "   • To start now: sudo systemctl start vpt-heatmap"
    echo "   • To check status: sudo systemctl status vpt-heatmap"
    echo "   • To view logs: sudo journalctl -u vpt-heatmap -f"
else
    echo "⚠️ Heatmap service file not found: $HEATMAP_SERVICE_FILE"
fi

# Install Analyzer Discard Worker Services (both disabled by default)
echo "🔧 Installing Analyzer Discard Worker Services..."
DISCARD_SCRIPT_SERVICE_FILE="$PROJECT_ROOT/backend_server/config/services/linux/vpt-discard-scripts.service"
DISCARD_INCIDENT_SERVICE_FILE="$PROJECT_ROOT/backend_server/config/services/linux/vpt-discard-incidents.service"

# Remove legacy service if present
sudo systemctl stop vpt-discard 2>/dev/null || true
sudo systemctl disable vpt-discard 2>/dev/null || true
sudo rm -f /etc/systemd/system/vpt-discard.service

install_discard_service() {
    local service_name="$1"
    local service_file="$2"

    if [ ! -f "$service_file" ]; then
        echo "⚠️ Discard worker service file not found: $service_file"
        return 0
    fi

    sudo systemctl stop "$service_name" 2>/dev/null || true
    sudo systemctl disable "$service_name" 2>/dev/null || true

    echo "📝 Processing $service_name template..."
    local_discard_tmp="$TMP_DIR/${service_name}.service.tmp"
    sed -e "s|%PROJECT_ROOT%|$PROJECT_ROOT|g" \
        "$service_file" > "$local_discard_tmp"

    sudo cp "$local_discard_tmp" "/etc/systemd/system/${service_name}.service"
    rm -f "$local_discard_tmp"

    echo "✅ $service_name installed (disabled by default)"
}

install_discard_service "vpt-discard-scripts" "$DISCARD_SCRIPT_SERVICE_FILE"
install_discard_service "vpt-discard-incidents" "$DISCARD_INCIDENT_SERVICE_FILE"
sudo systemctl daemon-reload

echo "✅ Analyzer discard services installed (both disabled by default)"
echo "   • Services are NOT auto-started on boot"
echo "   • To enable on boot: sudo systemctl enable vpt-discard-scripts vpt-discard-incidents"
echo "   • To start now: sudo systemctl start vpt-discard-scripts vpt-discard-incidents"
echo "   • To check status: sudo systemctl status vpt-discard-scripts vpt-discard-incidents"
echo "   • To view logs: sudo journalctl -u vpt-discard-scripts -u vpt-discard-incidents -f"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 Configuring sudo permissions..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Server-side counterpart to install_host.sh's sudoers. The backend runs as
# vpt_user and needs these for restart-vpt-server-service, reboot-server and
# the frontend redeploy. Journal access for the log viewer is intentionally
# NOT granted here — it comes from the systemd-journal group added in
# shared/create_vpt_user.sh (single source of truth, no duplication).
sudo tee /etc/sudoers.d/virtualpytest > /dev/null << 'EOF'
# Dashboard restart-server-service + reboot-server + frontend redeploy:
# start/stop/restart any vpt-* unit (vpt-server/frontend/heatmap/discard-*/...).
vpt_user ALL=(root) NOPASSWD: /bin/systemctl start vpt-*, /usr/bin/systemctl start vpt-*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl stop vpt-*, /usr/bin/systemctl stop vpt-*
vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*
vpt_user ALL=(root) NOPASSWD: /sbin/reboot, /usr/sbin/reboot
EOF
sudo chmod 440 /etc/sudoers.d/virtualpytest
if sudo visudo -cf /etc/sudoers.d/virtualpytest >/dev/null 2>&1; then
    echo "✅ sudo permissions configured"
else
    echo "⚠️  sudoers syntax check failed — review /etc/sudoers.d/virtualpytest"
fi

echo ""
echo "✅ Backend Server installation completed!"
echo ""
echo "📋 Installation Location: $PROJECT_ROOT"
echo ""
echo "📋 Next steps:"
echo "1. Configure your Supabase URI in $PROJECT_ROOT/.env"
echo "2. Run: $PROJECT_ROOT/setup/local/launch_server.sh"
echo ""
echo "🔧 Services Installed:"
echo "   • VirtualPyTest Server Service: vpt-server.service"
echo "   • Runs VirtualPyTest backend server on port 5109"
echo "   • Working Directory: $PROJECT_ROOT"
echo "   • Virtual Environment: $PROJECT_ROOT/venv"
echo "   • To start now: sudo systemctl start vpt-server"
echo "   • To check status: sudo systemctl status vpt-server"
echo "   • To view logs: sudo journalctl -u vpt-server -f"
echo ""
echo "   • Heatmap Processor Service: vpt-heatmap.service"
echo "   • Generates 24h circular heatmap buffer every minute"
echo "   • Working Directory: $PROJECT_ROOT"
echo "   • To start now: sudo systemctl start vpt-heatmap"
echo "   • To check status: sudo systemctl status vpt-heatmap"
echo "   • To view logs: sudo journalctl -u vpt-heatmap -f" 
echo ""
echo "   • Analyzer Discard Worker Service: vpt-discard-scripts.service"
echo "   • Analyzer Discard Worker Service: vpt-discard-incidents.service"
echo "   • Processes AI discard analysis queues (scripts/incidents)"
echo "   • Disabled by default"
echo "   • Working Directory: $PROJECT_ROOT/backend_server"
echo "   • To enable on boot: sudo systemctl enable vpt-discard-scripts vpt-discard-incidents"
echo "   • To start now: sudo systemctl start vpt-discard-scripts vpt-discard-incidents"
echo "   • To check status: sudo systemctl status vpt-discard-scripts vpt-discard-incidents"
echo "   • To view logs: sudo journalctl -u vpt-discard-scripts -u vpt-discard-incidents -f"
