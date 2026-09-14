#!/bin/bash
# setup/docker/installers/linux/install_docker.sh
# Universal Linux Docker installer (works on Ubuntu, Debian, Fedora, CentOS, RHEL, Raspberry Pi, etc.)

set -e

echo "🐳 Installing Docker for Linux (Universal)"

# Check if Docker is already installed
if command -v docker &> /dev/null && docker --version &> /dev/null; then
    echo "✅ Docker is already installed"
    docker --version
    exit 0
fi

# Detect if running as root
if [ "$EUID" -eq 0 ]; then
    echo "ℹ️  Running as root user"
    SUDO=""
    DOCKER_USER="root"
else
    echo "ℹ️  Running as non-root user (will use sudo)"
    SUDO="sudo"
    DOCKER_USER="$USER"
fi

# Install Docker using official installation script (handles all Linux distributions)
echo "📦 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
$SUDO sh get-docker.sh
rm get-docker.sh

# Install Docker Compose plugin (works on most Linux distros)
echo "🔧 Installing Docker Compose..."
$SUDO apt update && $SUDO apt install -y docker-compose-plugin

# Also install standalone docker-compose for compatibility
echo "🔧 Installing standalone Docker Compose..."
$SUDO curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
$SUDO chmod +x /usr/local/bin/docker-compose

# Add current user to docker group (if not root)
if [ "$EUID" -ne 0 ]; then
    echo "👤 Adding user to docker group..."
    $SUDO usermod -aG docker $USER
fi

# Start and enable Docker service
echo "🔧 Starting Docker service..."
$SUDO systemctl enable docker
$SUDO systemctl start docker

# Verify installation
echo "✅ Verifying installation..."
docker --version
docker compose version
docker-compose --version

echo ""
echo "🎉 Docker installation completed successfully!"
echo ""
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Note: You may need to log out and back in, or run 'newgrp docker'"
    echo "         for docker group changes to take effect"
fi