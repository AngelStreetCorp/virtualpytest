# Common variables for macOS service installation
# This file is sourced by all macOS backend_host installation scripts

# Script directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
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

# Installation paths
INSTALL_PATH="${VIRTUALPYTEST_INSTALL_PATH:-/var/www/html/stream}"
LOGS_PATH="/usr/local/virtualpytest/logs"

# Environment file
ENV_FILE="$BACKEND_HOST_PATH/src/.env"

# Service configuration
SERVICE_DOMAIN="com.virtualpytest"
SERVICE_TEMPLATES_DIR="$BACKEND_HOST_PATH/config/services/mac"

# noVNC directory
NOVNC_DIR="/tmp/noVNC"

# Websockify SSL certificate (for HTTPS/WSS support)
WEBSOCKIFY_CERT_DIR="/usr/local/etc/ssl/certs"
WEBSOCKIFY_CERT="$WEBSOCKIFY_CERT_DIR/websockify.pem"

# Stream script (existing script, not generated)
STREAM_SCRIPT="$SCRIPTS_PATH/run_ffmpeg_macos.sh"

# RAM disk setup script (boot service)
RAMDISK_SCRIPT="$SCRIPTS_PATH/setup_ramdisk_macos.sh"

# Load a launchd service plist properly (handles already-loaded services)
# Usage: load_launchd_service <plist_path> <service_label>
load_launchd_service() {
    local plist_path="$1"
    local service_label="$2"
    
    # Check if service is already loaded
    if launchctl list "$service_label" &>/dev/null; then
        # Service already loaded - unload first to apply any plist changes
        launchctl bootout system "$plist_path" &>/dev/null || \
        launchctl unload "$plist_path" &>/dev/null || true
        sleep 0.5
    fi
    
    # Try bootstrap first (modern method), fallback to load (legacy)
    if launchctl bootstrap system "$plist_path" &>/dev/null; then
        return 0
    elif launchctl load "$plist_path" &>/dev/null; then
        return 0
    else
        # Final check: service might have loaded despite error
        if launchctl list "$service_label" &>/dev/null; then
            return 0
        fi
        return 1
    fi
}

# Load a user launch agent (for VNC which needs GUI access)
# Usage: load_launchd_user_agent <plist_path> <service_label>
load_launchd_user_agent() {
    local plist_path="$1"
    local service_label="$2"

    # Check if service is already loaded
    if launchctl list "$service_label" &>/dev/null; then
        # Service already loaded - unload first to apply any plist changes
        launchctl bootout gui/$(id -u) "$plist_path" &>/dev/null || \
        launchctl unload "$plist_path" &>/dev/null || true
        sleep 0.5
    fi

    # Load as user agent
    if launchctl load "$plist_path" &>/dev/null; then
        return 0
    else
        # Final check: service might have loaded despite error
        if launchctl list "$service_label" &>/dev/null; then
            return 0
        fi
        return 1
    fi
}
