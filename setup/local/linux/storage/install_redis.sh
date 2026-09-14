#!/bin/bash

# VirtualPyTest - Install Redis Server
# This script sets up Redis for caching and message queuing

set -e

echo "🔴 VirtualPyTest - Installing Redis Server"
echo "📦 Installing Redis server..."

# Install Redis server
echo "📦 Installing Redis Server..."
sudo apt update
sudo apt install -y redis-server

# Create Redis user and directories (use /data for storage)
echo "📁 Setting up Redis directories and permissions..."
sudo mkdir -p /data/redis  # Use data disk for Redis persistence
sudo mkdir -p /etc/redis
sudo chown -R redis:redis /data/redis
sudo chown -R redis:redis /etc/redis

# Configure Redis
echo "⚙️ Configuring Redis server..."
sudo tee /etc/redis/redis.conf > /dev/null << 'EOF'
# Redis configuration for VirtualPyTest
bind 0.0.0.0
port 6379
timeout 0
tcp-keepalive 300
daemonize no
supervised systemd
loglevel notice
logfile /var/log/redis/redis-server.log

# Security
requirepass admin1234

# Memory management
maxmemory 256mb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000

# Append only file
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec

# Disable dangerous commands in production
# rename-command FLUSHDB ""
# rename-command FLUSHALL ""
# rename-command DEBUG ""
# rename-command CONFIG ""

# Enable AOF
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Disable RDB persistence if not needed
# save ""

dir /data/redis
EOF

# Get the script's directory to locate config files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/services"

# Install Redis systemd service
echo "🚀 Installing Redis systemd service..."
sudo cp "${CONFIG_DIR}/redis-server.service" /etc/systemd/system/redis-server.service
echo "   ✅ Redis service installed from ${CONFIG_DIR}/redis-server.service"

# Enable and start Redis service
echo "🚀 Enabling and starting Redis service..."
sudo systemctl daemon-reload
sudo systemctl enable redis-server

# Stop any existing Redis service
if sudo systemctl is-active --quiet redis-server; then
    echo "   ℹ️  Stopping existing Redis service..."
    sudo systemctl stop redis-server
fi

# Start Redis service
echo "   🚀 Starting Redis service..."
if sudo systemctl start redis-server; then
    echo "   ✅ Redis service started successfully"
else
    echo "   ❌ Redis service failed to start. Checking status..."
    sudo systemctl status redis-server.service --no-pager -l
    echo ""
    echo "   📋 Checking journal logs:"
    sudo journalctl -u redis-server.service -n 50 --no-pager
    exit 1
fi

# Wait for Redis to start and verify it's listening
echo "⏳ Waiting for Redis to start..."
RETRY_COUNT=0
MAX_RETRIES=30

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if sudo netstat -tlnp 2>/dev/null | grep -q ":6379"; then
        echo "   ✅ Redis is listening on port 6379"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ Redis failed to start listening on port 6379 after 30 seconds"
        echo "   📋 Service status:"
        sudo systemctl status redis-server.service --no-pager -l
        echo ""
        echo "   📋 Recent logs:"
        sudo journalctl -u redis-server.service -n 50 --no-pager
        exit 1
    fi
    sleep 1
done

# Test Redis connection
echo "🧪 Testing Redis connection..."
if redis-cli -a admin1234 ping | grep -q "PONG"; then
    echo "   ✅ Redis is running and responding to commands"
else
    echo "   ❌ Redis is not responding to ping command"
    exit 1
fi

# Install Redis Commander (Simple Redis Web GUI)
echo ""
echo "🔴 Installing Redis Commander (Redis Web GUI)..."
echo "📦 Installing Redis Commander..."

NODE_MAJOR=22
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    CURRENT_NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [ "$CURRENT_NODE_MAJOR" -lt "$NODE_MAJOR" ]; then
        echo "   🔧 Upgrading Node.js to ${NODE_MAJOR} (current: $(node --version))..."
        sudo apt-get remove -y nodejs npm
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash -
        sudo apt-get install -y nodejs
    fi
    echo "   📦 Installing Redis Commander via npm..."
    if sudo npm install -g redis-commander; then
        echo "   ✅ Redis Commander installed via npm"
        # Ensure the binary is executable and update service path
        REDIS_COMMANDER_BIN=""
        if [ -f /usr/local/bin/redis-commander ]; then
            REDIS_COMMANDER_BIN="/usr/local/bin/redis-commander"
        elif [ -f /usr/bin/redis-commander ]; then
            REDIS_COMMANDER_BIN="/usr/bin/redis-commander"
        elif [ -f /usr/lib/node_modules/redis-commander/bin/redis-commander.js ]; then
            REDIS_COMMANDER_BIN="/usr/bin/node /usr/lib/node_modules/redis-commander/bin/redis-commander.js"
        fi

        if [ -n "$REDIS_COMMANDER_BIN" ]; then
            echo "   ✅ Redis Commander found at: $REDIS_COMMANDER_BIN"
            # Store the binary path for later use when updating the service file
            export REDIS_COMMANDER_PATH="$REDIS_COMMANDER_BIN"
        else
            echo "   ❌ Redis Commander binary not found in any expected location"
            find /usr -name "*redis-commander*" 2>/dev/null || echo "   ❌ No redis-commander files found"
            return 1
        fi
    else
        echo "   ❌ Redis Commander npm installation failed"
        return 1
    fi
elif command -v apt >/dev/null 2>&1; then
    echo "   📦 Installing Node.js and npm first..."
    sudo apt update
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash -
    if sudo apt install -y nodejs npm; then
        echo "   📦 Installing Redis Commander via npm..."
        if sudo npm install -g redis-commander; then
            echo "   ✅ Redis Commander installed via npm"
        else
            echo "   ❌ Redis Commander npm installation failed"
            return 1
        fi
    else
        echo "   ❌ Failed to install Node.js/npm"
        return 1
    fi
else
    echo "   ❌ Neither Node.js nor apt available for Redis Commander installation"
    echo "   ℹ️  Install manually: sudo apt install nodejs npm && sudo npm install -g redis-commander"
    return 0
fi

# Create vpt_user if it doesn't exist
if ! id -u vpt_user >/dev/null 2>&1; then
    echo "👤 Creating vpt_user system user..."
    sudo useradd -r -s /usr/sbin/nologin -d /var/lib/vpt_user -m vpt_user
    echo "   ✅ vpt_user created"
else
    echo "   ✅ vpt_user already exists"
fi

# Create Redis Commander working directory with proper permissions
echo "📁 Setting up Redis Commander directories..."
sudo mkdir -p /var/lib/redis-commander
sudo chown vpt_user:vpt_user /var/lib/redis-commander
sudo chmod 755 /var/lib/redis-commander
echo "   ✅ Directory /var/lib/redis-commander created with vpt_user ownership"

# Install Redis Commander systemd service
echo "🚀 Installing Redis Commander systemd service..."
sudo cp "${CONFIG_DIR}/redis-commander.service" /etc/systemd/system/redis-commander.service

# Update ExecStart with the correct binary path if it was detected
if [ -n "$REDIS_COMMANDER_PATH" ]; then
    sudo sed -i "s|ExecStart=.*redis-commander.*|ExecStart=$REDIS_COMMANDER_PATH --redis-host 127.0.0.1 --redis-port 6379 --redis-password admin1234 --http-auth admin:admin1234|" /etc/systemd/system/redis-commander.service
    echo "   ✅ Service file updated with binary path: $REDIS_COMMANDER_PATH"
fi

echo "   ✅ Redis Commander service installed from ${CONFIG_DIR}/redis-commander.service"

# Enable and start Redis Commander service
echo "🚀 Enabling and starting Redis Commander service..."
sudo systemctl daemon-reload
sudo systemctl enable redis-commander

# Stop any existing Redis Commander service
if sudo systemctl is-active --quiet redis-commander; then
    echo "   ℹ️  Stopping existing Redis Commander service..."
    sudo systemctl stop redis-commander
fi

# Start Redis Commander service
echo "   🚀 Starting Redis Commander service..."
if sudo systemctl start redis-commander; then
    echo "   ✅ Redis Commander service started successfully"
else
    echo "   ❌ Redis Commander service failed to start. Checking status..."
    sudo systemctl status redis-commander.service --no-pager -l
    echo ""
    echo "   📋 Checking journal logs:"
    sudo journalctl -u redis-commander.service -n 50 --no-pager
    exit 1
fi

# Wait for Redis Commander to start and verify it's listening
echo "⏳ Waiting for Redis Commander to start..."
RETRY_COUNT=0
MAX_RETRIES=30

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if sudo netstat -tlnp 2>/dev/null | grep -q ":8081"; then
        echo "   ✅ Redis Commander is listening on port 8081"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo "   ❌ Redis Commander failed to start listening on port 8081 after 30 seconds"
        echo "   📋 Service status:"
        sudo systemctl status redis-commander.service --no-pager -l
        echo ""
        echo "   📋 Recent logs:"
        sudo journalctl -u redis-commander.service -n 50 --no-pager
        exit 1
    fi
    sleep 1
done

echo ""
echo "✅ Redis installation completed!"
echo ""

# Final verification
echo "🔍 Verifying Redis and Redis Commander installation..."
echo ""
echo "📊 Redis Service Status:"
sudo systemctl status redis-server.service --no-pager | head -10
echo ""
echo "📊 Redis Commander Service Status:"
sudo systemctl status redis-commander.service --no-pager | head -10
echo ""
echo "🌐 Network Status:"
echo "   Redis Port 6379:"
sudo netstat -tlnp 2>/dev/null | grep ":6379" || echo "   ⚠️  Not listening on port 6379"
echo "   Redis Commander Port 8081:"
sudo netstat -tlnp 2>/dev/null | grep ":8081" || echo "   ⚠️  Not listening on port 8081"
echo ""
echo "📦 Redis Process:"
ps aux | grep -v grep | grep redis-server || echo "   ⚠️  Redis process not found"
echo ""
echo "📦 Redis Commander Process:"
ps aux | grep -v grep | grep redis-commander || echo "   ⚠️  Redis Commander process not found"
echo ""
echo "📊 Redis Server Info:"
redis-cli info server | head -10
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔴 Redis Server Status:"
echo "   • Port: 6379"
echo "   • Status: $(sudo systemctl is-active redis-server)"
echo ""
echo "🔴 Redis Commander Web GUI Status:"
echo "   • Port: 8081"
echo "   • Status: $(sudo systemctl is-active redis-commander)"
echo "   • Local URL: http://localhost:8081"
echo "   • Proxied URL: https://your-domain/redis/"
echo "   • Web login: admin / admin1234"
echo ""
echo "🔧 Management Commands:"
echo "   Redis Server:"
echo "   • Check status: sudo systemctl status redis-server"
echo "   • View logs: sudo journalctl -u redis-server -f"
echo "   • Restart: sudo systemctl restart redis-server"
echo "   • Redis CLI: redis-cli"
echo "   • Test connection: redis-cli ping"
echo "   • Monitor: redis-cli monitor"
echo ""
echo "   Redis Commander:"
echo "   • Check status: sudo systemctl status redis-commander"
echo "   • View logs: sudo journalctl -u redis-commander -f"
echo "   • Restart: sudo systemctl restart redis-commander"
echo ""
echo "📝 Configuration Values for VirtualPyTest:"
echo ""
echo "   Redis Server:"
echo "   • Local Redis (with password):"
echo "     REDIS_URL=redis://:admin1234@localhost:6379/0"
echo "   • Remote Redis (with password):"
echo "     REDIS_URL=redis://:admin1234@192.168.0.101:6379/0"
echo ""
echo "   Redis Commander Web GUI:"
echo "   • Local URL: http://localhost:8081"
echo "   • Proxied URL: https://your-domain/redis/"
echo "   • Web login: admin / admin1234"
echo "   • Redis connection: 127.0.0.1:6379 with password 'admin1234' (auto-configured)"
echo ""
echo "   Test script available: test_redis.py (supports password auth)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Redis and Redis Commander are ready for VirtualPyTest!"
echo "   • Redis server: Port 6379 (caching and queuing)"
echo "   • Redis Commander GUI: Port 8081 (web interface)"
