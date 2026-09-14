#!/bin/bash
# VirtualPyTest - Cross-Platform Docker Installation
# Automatically detects platform and installs appropriate Docker version

set -e

echo "🐳 Installing Docker for VirtualPyTest"

# Detect platform (uname is enough here; the per-OS installers do the fine-grained work)
case "$(uname -s)" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    MINGW*|MSYS*|CYGWIN*) PLATFORM=windows ;;
    *) PLATFORM="unknown ($(uname -s))" ;;
esac

case $PLATFORM in
    "linux")
        echo "📦 Installing Docker for Linux..."
        $(dirname "$0")/installers/linux/install_docker.sh
        ;;
    "windows")
        echo "📦 Installing Docker Desktop for Windows..."
        powershell -ExecutionPolicy Bypass -File $(dirname "$0")/installers/windows/install_docker.ps1
        ;;
    "macos")
        echo "📦 Installing Docker Desktop for macOS..."
        $(dirname "$0")/installers/macos/install_docker.sh
        ;;
    *)
        echo "❌ Unsupported platform: $PLATFORM"
        echo "Supported platforms: linux, windows, macos"
        echo ""
        echo "For manual installation:"
        echo "  Linux: https://docs.docker.com/engine/install/"
        echo "  Windows: Install Docker Desktop manually"
        echo "  macOS: Install Docker Desktop manually"
        exit 1
        ;;
esac

echo "🎉 Docker installation completed!"
echo ""
echo "🚀 Next steps:"
echo "   ./setup/docker/launch.sh"