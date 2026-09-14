# Common variables for Linux service installation
# This file is sourced by all Linux backend_host installation scripts

# Use standardized VirtualPyTest directory
PROJECT_ROOT="/opt/virtualpytest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST_PATH="$PROJECT_ROOT/backend_host"
SCRIPTS_PATH="$BACKEND_HOST_PATH/scripts"
SHARED_PATH="$PROJECT_ROOT/shared"

# Source shared utilities (logging, device parsing)
SHARED_SCRIPTS_DIR="$SCRIPT_DIR/../../shared"
if [[ -f "$SHARED_SCRIPTS_DIR/logging.sh" ]]; then
    source "$SHARED_SCRIPTS_DIR/logging.sh"
fi
if [[ -f "$SHARED_SCRIPTS_DIR/parse_devices.sh" ]]; then
    source "$SHARED_SCRIPTS_DIR/parse_devices.sh"
fi

# Python environment
VENV_PATH="$PROJECT_ROOT/venv"
PYTHON_EXE="$VENV_PATH/bin/python"
PIP_EXE="$VENV_PATH/bin/pip"

# Installation paths (configurable via environment variable or symlink)
# VIRTUALPYTEST_INSTALL_PATH can be set to redirect data to custom location
# Default: /var/www/html/stream (can be symlinked to custom location)
INSTALL_PATH="${VIRTUALPYTEST_INSTALL_PATH:-/var/www/html/stream}"
LOGS_PATH="/tmp"

# Environment file
ENV_FILE="$BACKEND_HOST_PATH/src/.env"

# User and paths
PROJECT_ROOT_ESCAPED=$(printf '%s\n' "$PROJECT_ROOT" | sed 's/[[\.*^$()+?{|]/\\&/g')

# Service templates directory
SERVICE_TEMPLATES_DIR="$BACKEND_HOST_PATH/config/services/linux"

# Websockify SSL certificate (for HTTPS/WSS support)
WEBSOCKIFY_CERT_DIR="/etc/ssl/certs"
WEBSOCKIFY_CERT="$WEBSOCKIFY_CERT_DIR/websockify.pem"
