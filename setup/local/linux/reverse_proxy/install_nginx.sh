#!/bin/bash

# VirtualPyTest - Reverse Proxy Installation Script
# Installs nginx with a single self-contained configuration file

set -e

echo "🌐 VirtualPyTest Reverse Proxy Installation"
echo ""

# Show available configs first
echo "📁 Available configs:"
echo "   • infra/proxy/nginx/config/local-http.conf      (localhost development)"
echo "   • infra/proxy/nginx/config/production-https.conf (production with SSL)"
echo "   • infra/proxy/nginx/config/docker.conf          (Docker deployment)"
echo "   • Or specify any config file path as argument"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Load shared bootstrap functions
if [ -f "$SCRIPT_DIR/../shared/bootstrap.sh" ]; then
    source "$SCRIPT_DIR/../shared/bootstrap.sh"
else
    echo "❌ Bootstrap script not found"
    exit 1
fi

# Setup standard environment (user + directory + full project copy)
setup_for_code_installer "$SOURCE_ROOT"

# Change to project root for consistency
cd /opt/virtualpytest

# Install requirements
echo "📦 Installing Nginx..."
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx openssl

# Determine which config to use
echo "⚙️ Setting up nginx configuration..."

DEFAULT_CONFIG="$SOURCE_ROOT/infra/proxy/nginx/config/local-http.conf"

# Check for command line argument first, then environment variable
if [ $# -eq 1 ]; then
    CUSTOM_CONFIG="$1"
    echo "📋 Using config: $CUSTOM_CONFIG"
elif [ -n "$VIRTUALPYTEST_CONFIG" ]; then
    CUSTOM_CONFIG="$VIRTUALPYTEST_CONFIG"
    echo "📋 Using config: $CUSTOM_CONFIG"
else
    CUSTOM_CONFIG=""
fi

if [ -n "$CUSTOM_CONFIG" ] && [ -f "$CUSTOM_CONFIG" ]; then
    CONFIG_FILE="$CUSTOM_CONFIG"
    CONFIG_TYPE="custom"
else
    CONFIG_FILE="$DEFAULT_CONFIG"
    CONFIG_TYPE="default"
    echo "📋 Using default config: $DEFAULT_CONFIG"
fi

# Copy config to nginx sites
sudo cp "$CONFIG_FILE" "/etc/nginx/sites-available/virtualpytest"

# Enable the VirtualPyTest site
sudo ln -sf /etc/nginx/sites-available/virtualpytest /etc/nginx/sites-enabled/

# Remove default nginx site if it exists
sudo rm -f /etc/nginx/sites-enabled/default

# Generate self-signed SSL certificate if HTTPS config detected
if grep -q "listen.*443.*ssl" "$CONFIG_FILE"; then
    echo "🔐 HTTPS configuration detected - generating self-signed SSL certificate..."

    SSL_DIR="/etc/ssl/virtualpytest"
    CERT_FILE="$SSL_DIR/virtualpytest.crt"
    KEY_FILE="$SSL_DIR/virtualpytest.key"

    # Create SSL directory if it doesn't exist
    sudo mkdir -p "$SSL_DIR"

    # Generate self-signed certificate (valid for 365 days)
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/C=US/ST=State/L=City/O=VirtualPyTest/CN=virtualpytest.local" \
        -addext "subjectAltName=DNS:virtualpytest.local,DNS:localhost,IP:127.0.0.1"

    # Set proper permissions
    sudo chmod 600 "$KEY_FILE"
    sudo chmod 644 "$CERT_FILE"
    sudo chown root:root "$SSL_DIR"/*

    echo "✅ Self-signed certificate generated:"
    echo "   • Certificate: $CERT_FILE"
    echo "   • Private key: $KEY_FILE"
    echo "   • Valid for: 365 days"
    echo "   ⚠️  Browser will show security warning - click 'Advanced' → 'Proceed'"
fi

# Test nginx configuration
echo "🧪 Testing Nginx configuration..."
if sudo nginx -t; then
    echo "✅ Nginx configuration is valid"
else
    echo "❌ Nginx configuration has errors"
    exit 1
fi

# Reload nginx to apply configuration
echo "🔄 Reloading Nginx..."
sudo systemctl reload nginx

echo ""
echo "✅ Reverse proxy installation completed!"
echo ""
echo "📋 Configuration:"
echo "   • Config file: $CONFIG_FILE"
echo "   • Nginx config: /etc/nginx/sites-available/virtualpytest"

# Extract and show configured IPs from the config file
echo ""
echo "📋 Configured services:"

# Extract upstream servers with IP:port
if grep -q "upstream frontend" "$CONFIG_FILE"; then
    FRONTEND_IP_PORT=$(grep -A1 "upstream frontend" "$CONFIG_FILE" | grep "server" | sed 's/.*server \([0-9.]*:[0-9]*\).*/\1/')
    echo "   • Frontend: $FRONTEND_IP_PORT"
fi

if grep -q "upstream backend_server" "$CONFIG_FILE"; then
    BACKEND_IP_PORT=$(grep -A1 "upstream backend_server" "$CONFIG_FILE" | grep -E "^\s*server " | sed 's/.*server \([0-9.]*:[0-9]*\).*/\1/')
    echo "   • Backend API: $BACKEND_IP_PORT"
fi

if grep -q "upstream grafana" "$CONFIG_FILE"; then
    GRAFANA_IP_PORT=$(grep -A1 "upstream grafana" "$CONFIG_FILE" | grep "server" | sed 's/.*server \([0-9.]*:[0-9]*\).*/\1/')
    echo "   • Grafana: $GRAFANA_IP_PORT"
fi

if grep -q "upstream minio" "$CONFIG_FILE"; then
    MINIO_IP_PORT=$(grep -A1 "upstream minio" "$CONFIG_FILE" | grep "server" | sed 's/.*server \([0-9.]*:[0-9]*\).*/\1/')
    echo "   • MinIO: $MINIO_IP_PORT"
fi

# Extract host mappings
if grep -q "map.*backend_host_ip" "$CONFIG_FILE"; then
    echo "   • Host mappings:"
    grep -A10 "map.*backend_host_ip" "$CONFIG_FILE" | grep -E '^\s*"[a-zA-Z0-9_-]+"\s*"' | head -5 | sed 's/^\s*"/     • /' | sed 's/"\s*"/: /' | sed 's/";/,/' | sed 's/,$//'
fi

# Extract reverse proxy IP
REVERSE_PROXY_IP="[nginx-server-ip]"
if grep -q "REVERSE_PROXY_IP:" "$CONFIG_FILE"; then
    EXTRACTED_IP=$(grep "REVERSE_PROXY_IP:" "$CONFIG_FILE" | sed 's/.*REVERSE_PROXY_IP:\s*\([0-9.]*\).*/\1/')
    if [ -n "$EXTRACTED_IP" ]; then
        REVERSE_PROXY_IP="$EXTRACTED_IP"
    fi
fi

echo ""
echo "🌐 Access URLs:"
if grep -q "listen.*443.*ssl" "$CONFIG_FILE"; then
    PROTOCOL="https"
    echo "   🔒 HTTPS enabled (self-signed certificate)"
else
    PROTOCOL="http"
fi
echo "   • Main application: $PROTOCOL://$REVERSE_PROXY_IP/"
echo "   • API endpoints: $PROTOCOL://$REVERSE_PROXY_IP/server/"
echo "   • Host control: $PROTOCOL://$REVERSE_PROXY_IP/host/"
echo "   • Monitoring: $PROTOCOL://$REVERSE_PROXY_IP/grafana/"

echo ""
echo "📋 Next steps:"
echo "1. Edit /etc/nginx/sites-available/virtualpytest to customize IPs"
if grep -q "listen.*443.*ssl" "$CONFIG_FILE"; then
    echo "2. Accept self-signed certificate in browser for HTTPS access"
    echo "3. For production SSL, use: infra/proxy/nginx/config/production-https.conf with Let's Encrypt"
else
    echo "2. For HTTPS, use: infra/proxy/nginx/config/proxmox.local.https.conf"
fi