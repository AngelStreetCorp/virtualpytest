#!/bin/sh
# Windows Docker Desktop compatible entrypoint script for backend_host
# This version avoids bash-specific features that may not work in Windows containers

# Initialize storage directories from .env
ENV_FILE="/app/backend_host/src/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

echo ""
echo "Initializing storage directories..."

# Simple device detection (HOST only for Windows compatibility)
HOST_CAPTURE_PATH=$(grep "^HOST_VIDEO_CAPTURE_PATH=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | tr -d '"' | tr -d "'")
if [ -n "$HOST_CAPTURE_PATH" ]; then
    echo "Found host: HOST -> $HOST_CAPTURE_PATH"
    echo "Windows mode: Directory creation delegated to ffmpeg script (no tmpfs support)"
    echo "Directories will be created dynamically when capture starts"
fi

echo ""
echo "Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf -n