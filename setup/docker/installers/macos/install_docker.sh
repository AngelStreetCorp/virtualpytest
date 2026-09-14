#!/bin/bash
# setup/docker/installers/macos/install_docker.sh
# macOS Docker Desktop installer using Homebrew

set -e

echo "🐳 Installing Docker Desktop for macOS"
echo ""

# Check if Docker is already installed
if command -v docker &> /dev/null && docker --version &> /dev/null; then
    echo "✅ Docker is already installed"
    docker --version
    exit 0
fi

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "📦 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Add Homebrew to PATH for this session
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi

    echo "✅ Homebrew installed successfully"
else
    echo "✅ Homebrew is already installed"
fi

# Install Docker Desktop via Homebrew Cask
echo "📦 Installing Docker Desktop..."
brew install --cask docker

echo ""
echo "🎉 Docker Desktop installation completed!"
echo ""
echo "🚀 Next steps:"
echo "   1. Start Docker Desktop from your Applications folder"
echo "   2. Wait for Docker to finish initializing"
echo "   3. Run: docker --version"
echo ""
echo "📋 Useful commands:"
echo "   Start Docker:  docker --version"
echo "   Launch app:   cd setup/docker/standalone_server_host && ./launch.sh"