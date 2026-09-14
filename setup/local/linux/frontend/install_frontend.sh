#!/bin/bash

# VirtualPyTest - Install Frontend (Autonomous)
# This script installs frontend dependencies
# This installer is autonomous and will set up the complete environment

set -e

echo "⚛️ Installing VirtualPyTest Frontend (Autonomous)..."

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="/opt/virtualpytest"
TMP_DIR="${TMPDIR:-/tmp}"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
VENV_BIN_DIR="$PROJECT_ROOT/venv/bin"

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
if [ ! -f "README.md" ] || [ ! -d "frontend" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Expected: $PROJECT_ROOT"
    exit 1
fi

# Install system dependencies (base requirements for all Debian/Ubuntu systems)
echo "📦 Installing system dependencies..."
sudo apt update
sudo apt install -y build-essential xsel python3 python3-pip
echo "✅ System dependencies installed"

# Install Node.js and npm if not present
# NOTE: This script requires Node.js 22+
# If you have Node.js older than 22, update it by running:
#   sudo apt-get remove -y nodejs npm
#   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
#   sudo apt-get install -y nodejs
echo "📦 Checking Node.js installation..."
NODE_MAJOR=22
if ! command -v node &> /dev/null; then
    echo "🔧 Installing Node.js ${NODE_MAJOR}..."
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash -
    sudo apt-get install -y nodejs
    echo "✅ Node.js installed successfully"
else
    CURRENT_NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [ "$CURRENT_NODE_MAJOR" -lt "$NODE_MAJOR" ]; then
        echo "🔧 Upgrading Node.js to ${NODE_MAJOR} (current: $(node --version))..."
        sudo apt-get remove -y nodejs npm
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash -
        sudo apt-get install -y nodejs
        echo "✅ Node.js upgraded successfully"
    else
        echo "✅ Node.js is already installed ($(node --version))"
    fi
fi

# Verify npm is available
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not available after Node.js installation"
    exit 1
fi

# Install frontend dependencies as vpt_user (service runs as vpt_user)
echo "📦 Installing frontend dependencies..."
cd frontend
sudo -u vpt_user npm install

# Ensure serve runtime config exists for production static docs behavior
if [ ! -f "serve.json" ]; then
    echo "📝 Creating frontend/serve.json (disable cleanUrls redirects)..."
    cat > serve.json << 'EOF'
{
  "cleanUrls": false
}
EOF
else
    echo "✅ frontend/serve.json already exists"
fi

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "📝 Creating .env file from .env.example..."
        cp .env.example .env
        echo "✅ Created .env file - please configure it with your settings"
    else
        echo "⚠️ No .env.example found - please create .env manually"
    fi
else
    echo "✅ .env file already exists"
fi

cd ..

# Install Bandit for security docs generation (used by frontend prebuild)
echo "📦 Ensuring Bandit is installed for vpt_user..."
if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

if sudo -u vpt_user "$VENV_BIN_DIR/bandit" --version >/dev/null 2>&1; then
    echo "✅ Bandit already installed in project venv"
else
    sudo -u vpt_user "$VENV_PYTHON" -m pip install bandit
    echo "✅ Bandit installed in project venv"
fi

# Note: Firewall configuration is handled at the Proxmox level
# Required port for frontend service: 5073 TCP (configure in Proxmox)

# Install VirtualPyTest Frontend Service
install_frontend_service() {
    echo "🔧 Installing VirtualPyTest Frontend Service..."

    VPT_FRONTEND_SERVICE_FILE="$PROJECT_ROOT/frontend/config/services/linux/frontend_prod.service"
    SERVICE_NAME="vpt-frontend-prod"

    # Persistent doc-build cache (survives deploys; prebuild.sh skips the slow
    # doc/security pipeline when sources are unchanged). MUST live outside the
    # deploy target and be writable by the service user.
    DOCS_CACHE_DIR="${VPT_DOCS_CACHE_DIR:-/opt/vpt-cache/docs}"
    echo "📦 Provisioning doc-build cache at $DOCS_CACHE_DIR"
    sudo mkdir -p "$DOCS_CACHE_DIR"
    sudo chown -R vpt_user:vpt_user "$(dirname "$DOCS_CACHE_DIR")"

    if [ ! -f "$VPT_FRONTEND_SERVICE_FILE" ]; then
        echo "⚠️  Frontend service file not found: $VPT_FRONTEND_SERVICE_FILE"
        echo "   Creating service file..."
        
        mkdir -p "$PROJECT_ROOT/frontend/config/services/linux"
        
        cat > "$VPT_FRONTEND_SERVICE_FILE" << 'EOFSERVICE'
[Unit]
Description=VirtualPyTest Frontend Service (Production)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%USER%
WorkingDirectory=%PROJECT_ROOT%/frontend
Environment="PATH=%PROJECT_ROOT%/venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin"
Environment="NODE_ENV=production"

# Build (conditional install) and start frontend
ExecStartPre=/usr/bin/npm run build
ExecStart=/usr/bin/npm run start

# Restart policy
Restart=on-failure
RestartSec=10

# Resource limits
TimeoutStartSec=60
TimeoutStopSec=30

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=vpt-frontend-prod

[Install]
WantedBy=multi-user.target
EOFSERVICE
    fi
    
    # Stop existing service if running
    sudo systemctl stop vpt-frontend 2>/dev/null || true
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true

    # Process the service template and copy to systemd directory
    echo "📝 Processing Frontend service template..."
    echo "   User: vpt_user"
    echo "   Project Root: $PROJECT_ROOT"

    local_frontend_tmp="$TMP_DIR/vpt-frontend.service.tmp"
    if sed -e "s|%PROJECT_ROOT%|$PROJECT_ROOT|g" \
           "$VPT_FRONTEND_SERVICE_FILE" > "$local_frontend_tmp" 2>/dev/null; then
        echo "✅ Service file processed successfully"
    else
        echo "❌ Failed to process service file"
        return 1
    fi
    
    # Copy to systemd directory
    sudo cp "$local_frontend_tmp" /etc/systemd/system/"$SERVICE_NAME".service
    rm -f "$local_frontend_tmp"
    
    # Reload systemd daemon
    sudo systemctl daemon-reload
    
    # Enable service for auto-start
    sudo systemctl enable "$SERVICE_NAME"
    
    echo "✅ VirtualPyTest Frontend service installed and enabled"
    echo "   • Service will start automatically on boot"
    echo "   • Runs production build via npm run build/start"
    
    # Start the service now
    echo ""
    echo "🚀 Starting Frontend service..."
    # The unit's ExecStartPre runs the production build (10-20 min on a small machine).
    # Queue the start and let it build in the background rather than blocking the whole
    # installation on it — the URL table at the end says where to check.
    if sudo systemctl start --no-block "$SERVICE_NAME"; then
        echo "✅ Frontend service start queued — it builds the production bundle first"
        echo "   (first build: 10-20 min; follow with: sudo journalctl -u ${SERVICE_NAME} -f)"
    else
        echo "⚠️  Could not queue the Frontend service start"
        echo "   Check logs: sudo journalctl -u ${SERVICE_NAME} -f"
    fi
    
    echo ""
    echo "📋 Service Management Commands:"
    echo "   • Check status: sudo systemctl status $SERVICE_NAME"
    echo "   • View logs: sudo journalctl -u $SERVICE_NAME -f"
    echo "   • Stop: sudo systemctl stop $SERVICE_NAME"
    echo "   • Restart: sudo systemctl restart $SERVICE_NAME"
    echo "   • Disable auto-start: sudo systemctl disable $SERVICE_NAME"
}

echo ""
echo "🔧 Installing Frontend auto-start service..."
install_frontend_service

echo ""
echo "✅ Frontend installation completed!"
echo ""
echo "🚀 Service Details:"
echo "   • Frontend service: vpt-frontend-prod.service"
echo "   • Will start automatically on boot"
echo "   • Runs production build on configured port"
echo "   • View logs: sudo journalctl -u vpt-frontend-prod -f"
echo ""
echo "🌐 Access Frontend:"
FE_HOST="$(grep -E '^VITE_SERVER_URL=' "$PROJECT_ROOT/frontend/.env" 2>/dev/null | head -1 | sed -E 's|.*://([^:/]+).*|\1|')"
echo "   • Local:   http://localhost:5073"
echo "   • Network: http://${FE_HOST:-<this machine>}:5073"
