#!/bin/bash

# VirtualPyTest - Install System Requirements (Ubuntu/Linux)
# This script installs system-level dependencies NOT covered by other install_*.sh scripts
# Usage: ./install_requirements.sh

set -e

echo "🔧 Installing VirtualPyTest System Requirements for Ubuntu/Linux..."

# Check if running on Ubuntu/Debian
if ! command -v apt-get &> /dev/null; then
    echo "❌ This script is designed for Ubuntu/Debian systems with apt-get"
    echo "For other Linux distributions, please install packages manually:"
    echo "See REQUIREMENTS.md for the complete package list"
    exit 1
fi

echo "🖥️ Detected Ubuntu/Debian system"


# Function to install packages
install_packages() {
    local packages=("$@")
    
    echo "📦 Updating package list..."
    # A dead Ookla repo from an earlier run (no build for this release) breaks apt entirely
    if [ -f /etc/apt/sources.list.d/ookla_speedtest-cli.list ] && ! command -v speedtest &> /dev/null; then
        sudo rm -f /etc/apt/sources.list.d/ookla_speedtest-cli.list
    fi
    sudo apt-get update
    echo "📦 Installing packages: ${packages[*]}"
    sudo apt-get install -y "${packages[@]}"
}

# Function to install development tools
install_dev_tools() {
    echo "🔧 Installing development tools..."
    install_packages build-essential git curl wget python3 python3-pip python3-venv python3-dev rsync
}

# Function to install database tools
install_database_tools() {
    echo "🗃️ Installing database tools..."
    install_packages libpq-dev postgresql-client
}

# Function to install system monitoring tools
install_system_tools() {
    echo "🔍 Installing system monitoring tools..."
    install_packages lsof net-tools psmisc inotify-tools
}

# Function to install ADB (Android Debug Bridge)
install_adb() {
    # Check if ADB is already available
    if command -v adb &> /dev/null; then
        echo "ℹ️ ADB already installed: $(adb version 2>&1 | head -n1)"
        return 0
    fi

    # Try installing from Ubuntu repository first (easiest method)
    echo "📦 Attempting to install ADB from Ubuntu repository..."
    if sudo apt-get install -y android-tools-adb android-tools-fastboot 2>/dev/null; then
        echo "✅ ADB installed from Ubuntu repository"
        return 0
    fi

    echo "⚠️ Ubuntu repository installation failed, installing Android SDK Platform Tools..."

    # Create Android SDK directory
    local android_home="$HOME/android-sdk"
    local platform_tools_dir="$android_home/platform-tools"

    mkdir -p "$android_home"

    # Download Android SDK Platform Tools
    echo "📥 Downloading Android SDK Platform Tools..."
    local platform_tools_url="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    local temp_zip="/tmp/platform-tools.zip"

    if ! wget -O "$temp_zip" "$platform_tools_url"; then
        echo "❌ Failed to download Android SDK Platform Tools"
        return 1
    fi

    # Extract platform tools
    echo "📂 Extracting Android SDK Platform Tools..."
    if ! unzip -q "$temp_zip" -d "$android_home"; then
        echo "❌ Failed to extract Android SDK Platform Tools"
        rm -f "$temp_zip"
        return 1
    fi

    rm -f "$temp_zip"

    # Add to PATH in multiple shell profiles
    echo "🔧 Configuring PATH for ADB..."

    local path_export="export PATH=\"$platform_tools_dir:\$PATH\""
    local android_home_export="export ANDROID_HOME=\"$android_home\""

    # Add to .bashrc
    if [ -f "$HOME/.bashrc" ]; then
        if ! grep -q "android-sdk/platform-tools" "$HOME/.bashrc"; then
            echo "" >> "$HOME/.bashrc"
            echo "# Android SDK Platform Tools" >> "$HOME/.bashrc"
            echo "$android_home_export" >> "$HOME/.bashrc"
            echo "$path_export" >> "$HOME/.bashrc"
        fi
    fi

    # Add to .profile (for login shells)
    if [ -f "$HOME/.profile" ]; then
        if ! grep -q "android-sdk/platform-tools" "$HOME/.profile"; then
            echo "" >> "$HOME/.profile"
            echo "# Android SDK Platform Tools" >> "$HOME/.profile"
            echo "$android_home_export" >> "$HOME/.profile"
            echo "$path_export" >> "$HOME/.profile"
        fi
    fi

    # Add to .zshrc if it exists (for zsh users)
    if [ -f "$HOME/.zshrc" ]; then
        if ! grep -q "android-sdk/platform-tools" "$HOME/.zshrc"; then
            echo "" >> "$HOME/.zshrc"
            echo "# Android SDK Platform Tools" >> "$HOME/.zshrc"
            echo "$android_home_export" >> "$HOME/.zshrc"
            echo "$path_export" >> "$HOME/.zshrc"
        fi
    fi

    # Export for current session
    export ANDROID_HOME="$android_home"
    export PATH="$platform_tools_dir:$PATH"

    # Verify installation
    if command -v adb &> /dev/null; then
        echo "✅ ADB installed successfully: $(adb version 2>&1 | head -n1)"
        echo "📍 Location: $platform_tools_dir/adb"
        echo "🔄 Note: You may need to restart your terminal or run 'source ~/.bashrc' to use ADB"
        return 0
    else
        echo "❌ ADB installation verification failed"
        return 1
    fi
}

# Function to install Ookla Speedtest CLI — NON-CRITICAL.
# Packagecloud builds lag behind Debian releases and some VMs have no egress
# to packagecloud.io at all. Every failure mode here is logged and ignored
# (function always returns 0) so the parent installer keeps going. Network
# speed checks fall back gracefully when the CLI is missing.
install_ookla_speedtest() {
    echo "🌐 Installing Ookla Speedtest CLI (non-critical)..."

    if command -v speedtest &> /dev/null; then
        echo "✅ Ookla Speedtest CLI already installed: $(speedtest --version 2>&1 | head -n1)"
        return 0
    fi

    set +e
    echo "📥 Adding Ookla packagecloud repo (20s connect cap)..."
    # Hard caps so VMs with no egress to packagecloud.io don't stall for minutes:
    #   --connect-timeout 10  : give up per-IP after 10s (curl tries each A record)
    #   --max-time 20         : total curl budget 20s incl. body download
    #   timeout 30 …          : wraps curl+bash so the downloaded script can't
    #                           itself hang on its own apt-get update either
    timeout 30 bash -c "curl -fsSL --connect-timeout 10 --max-time 20 https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash" >/dev/null 2>&1
    REPO_RC=$?
    if [ $REPO_RC -ne 0 ]; then
        echo "⚠️  Packagecloud repo script failed (rc=$REPO_RC) — unreachable or no build for $(lsb_release -cs 2>/dev/null || echo this OS)"
    fi

    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y speedtest >/dev/null 2>&1
    INSTALL_RC=$?
    set -e

    if command -v speedtest &> /dev/null; then
        echo "✅ Ookla Speedtest CLI installed: $(speedtest --version 2>&1 | head -n1)"
    else
        # No build for this release (e.g. Ubuntu 24.04): drop the repo the script added,
        # otherwise every later `apt-get update` on this machine fails with
        # "does not have a Release file" and the next install run dies at its first step.
        sudo rm -f /etc/apt/sources.list.d/ookla_speedtest-cli.list
        echo "⚠️  Skipping Ookla Speedtest CLI (apt rc=$INSTALL_RC) — continuing install"
        echo "    Network speed checks will use a fallback (this is non-critical)."
        echo "    To install manually later: https://www.speedtest.net/apps/cli"
    fi
    return 0
}

# Function to verify installations
verify_installation() {
    echo "🔍 Verifying installations..."

    # Always check these
    echo -n "Git: "
    if command -v git &> /dev/null; then
        echo "✅ $(git --version)"
    else
        echo "❌ Not found"
    fi

    echo -n "Curl: "
    if command -v curl &> /dev/null; then
        echo "✅ Available"
    else
        echo "❌ Not found"
    fi

    echo -n "Ookla Speedtest: "
    if command -v speedtest &> /dev/null; then
        echo "✅ $(speedtest --version 2>&1 | head -n1)"
    else
        echo "❌ Not found"
    fi

    echo "UFW (Firewall): Not needed (handled at Proxmox level)"
}

# Main installation process
main() {
    
    echo "📋 Installation plan:"
    echo "  - Development tools (git, curl, build tools)"
    echo "  - Database tools (PostgreSQL client)"
    echo "  - System monitoring tools"
    echo "  - Network testing tools (Ookla Speedtest CLI)"
    echo ""

    # Install components
    install_dev_tools
    install_database_tools
    install_system_tools
    install_adb
    install_ookla_speedtest

    echo ""
    echo "✅ System requirements installation completed!"
    echo ""
    
    verify_installation
    
    echo ""
    echo "📋 Next steps:"
    echo "1. Run VirtualPyTest installation:"
    echo "   ./setup/local/install_all.sh"
    echo ""
    echo "2. Launch VirtualPyTest:"
    echo "   ./scripts/launch_virtualpytest.sh"
    echo ""
    echo "💡 Note: Some packages may require logging out and back in to work properly"
}

# Execute main function
main
