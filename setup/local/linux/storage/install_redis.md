# Redis Configuration Guide

## Overview

VirtualPyTest uses Redis for:
- **AI Agent Queues**: Background task processing for AI agents (Sherlock, Nightwatch)
- **Queue Management**: Priority queues (P1: alerts, P2: scripts, P3: reserved)
- **Session Storage**: User session data and temporary state
- **Caching**: Application data caching for performance
- **Rate Limiting**: Alert filtering and rate limiting

Redis can be deployed in two modes:
1. **Local Redis** - Self-hosted TCP server (development/on-premise)
2. **Cloud Redis (Upstash)** - Managed REST API service (production/cloud)

**All components** (AI agents, task queues, caching) use the **same unified Redis configuration** via the shared `RedisQueueProcessor`.

## Unified Configuration

VirtualPyTest uses a **unified configuration approach** that auto-detects the connection type based on the `REDIS_URL` format:

### Environment Variables

**Required:**
- `REDIS_URL` - Connection URL (format determines connection type)

**Optional:**
- `REDIS_TOKEN` - Bearer token (required for Upstash/HTTPS URLs)
- `REDIS_PASSWORD` - Password (optional for local redis:// URLs)

### Configuration Examples

#### Local Redis (Default - Self-Hosted)

```bash
# No password required
REDIS_URL=redis://localhost:6379/0
```

**Features:**
- ✅ No internet required
- ✅ No authentication needed
- ✅ Full control
- ❌ Requires local maintenance

#### Remote Redis (Separate VM)

```bash
# With password authentication (replace with actual IP)
REDIS_URL=redis://:admin1234@192.168.x.101:6379/0
```

**Features:**
- ✅ Centralized Redis service
- ✅ Authentication enabled
- ✅ Network accessible
- ❌ Network dependency

#### Cloud Redis (Upstash)

```bash
# REST API over HTTPS
REDIS_URL=https://learning-cobra-12345.upstash.io
REDIS_TOKEN=AabBcc...xyz  # Bearer token from Upstash dashboard
```

**Features:**
- ✅ Managed service (no maintenance)
- ✅ REST API over HTTPS
- ✅ Global distribution
- ✅ Auto-scaling
- ❌ Requires internet connectivity

**Features:**
- ✅ Full control
- ✅ Lower latency
- ✅ No internet required
- ✅ No external costs
- ❌ Requires maintenance

## Local Redis Installation

### Quick Install

```bash
# Run the Redis installer
cd ~/virtualpytest
sudo ./setup/local/linux/storage/install_redis.sh
```

### What Gets Installed

1. **Redis Server** (`redis-server` package)
2. **Node.js & npm** (runtime for Redis Commander)
3. **Redis Commander** (`redis-commander` npm package) - Web GUI for Redis
4. **Systemd Services** (`redis-server.service`, `redis-commander.service`)
5. **Configuration** (`/etc/redis/redis.conf`)
6. **Data Directory** (`/data/redis`)
7. **Working Directory** (`/var/lib/redis-commander`)
8. **Redis CLI** (`redis-cli` command)

### Configuration Details

**Service File**: `/etc/systemd/system/redis-server.service.d/override.conf`

```ini
[Service]
ExecStart=/usr/bin/redis-server /etc/redis/redis.conf
Restart=always
User=redis
Group=redis
```

**Redis Config**: `/etc/redis/redis.conf`

```ini
# Network
bind 0.0.0.0                    # Listen on all interfaces
port 6379                        # Standard Redis port

# Security
requirepass admin1234            # Password authentication enabled

# Memory
maxmemory 256mb                  # Memory limit
maxmemory-policy allkeys-lru     # Eviction policy

# Persistence
appendonly yes                   # Enable AOF
appendfsync everysec            # Sync every second
save 900 1                      # Save after 900s if 1+ keys changed
save 300 10                     # Save after 300s if 10+ keys changed
save 60 10000                   # Save after 60s if 10000+ keys changed

# Data directory
dir /data/redis                  # Persistence location
```

### Redis Commander Web GUI

**Service File**: `/etc/systemd/system/redis-commander.service`

```ini
[Unit]
Description=Redis Commander
Documentation=https://github.com/joeferner/redis-commander
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=vpt_user
Group=vpt_user
Environment=HOME=/var/lib/redis-commander
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=NODE_PATH=/usr/local/lib/node_modules
WorkingDirectory=/var/lib/redis-commander
ExecStart=/usr/local/bin/redis-commander --redis-host 127.0.0.1 --redis-port 6379 --redis-password admin1234 --http-auth admin:admin1234
Restart=always

# Security
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
```

### Redis Commander Access

**Local Access**: `http://localhost:8081`
**Proxied Access**: `https://your-domain/redis/`
**Web Login**: `admin` / `admin1234`

Redis Commander automatically connects to Redis using:
- **Host**: `127.0.0.1`
- **Port**: `6379`
- **Password**: `admin1234`

No manual configuration needed - just open the web interface and start managing queues!

### Service Management

#### Redis Server
```bash
# Check status
sudo systemctl status redis-server

# Start service
sudo systemctl start redis-server

# Stop service
sudo systemctl stop redis-server

# Restart service
sudo systemctl restart redis-server

# Enable on boot
sudo systemctl enable redis-server

# View logs
sudo journalctl -u redis-server -f
```

#### Redis Commander Web GUI
```bash
# Check status
sudo systemctl status redis-commander

# Start service
sudo systemctl start redis-commander

# Stop service
sudo systemctl stop redis-commander

# Restart service
sudo systemctl restart redis-commander

# Enable on boot
sudo systemctl enable redis-commander

# View logs
sudo journalctl -u redis-commander -f
```

### Testing Local Redis

```bash
# Test connection (no password)
redis-cli ping
# Expected: PONG

# Test connection (with password)
redis-cli -a your_password ping
# Expected: PONG

# Set and get a value
redis-cli set test_key "hello world"
redis-cli get test_key
redis-cli del test_key

# Check server info
redis-cli info server

# Monitor commands in real-time
redis-cli monitor
```

### Configuration for VirtualPyTest

Add to your `.env` file:

```bash
# Local Redis (no password)
REDIS_URL=redis://localhost:6379

# Local Redis (with password)
REDIS_URL=redis://:your_password@localhost:6379
REDIS_PASSWORD=your_password
```

## Cloud Redis (Upstash) Setup

### 1. Create Upstash Account

1. Go to [upstash.com](https://upstash.com)
2. Sign up for a free account
3. Create a new Redis database

### 2. Get Credentials

From the Upstash dashboard:

1. Click on your database
2. Copy the **REST URL** (starts with `https://`)
3. Copy the **REST Token** (long alphanumeric string)

### 3. Configure VirtualPyTest

Add to your `.env` file:

```bash
# Upstash Redis (REST API)
REDIS_URL=https://learning-cobra-12345.upstash.io
REDIS_TOKEN=AabBcc...xyz
```

### 4. Verify Connection

```bash
# Using curl
curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://your-database.upstash.io/ping
# Expected: {"result":"PONG"}

# Using the application
# Start your server and check logs for:
# [@redis_queue] Upstash Redis REST API: https://...
```

## Queue System

VirtualPyTest uses Redis for a **priority queue system**:

### Queue Types

1. **P1 Queue** (`p1_alerts`) - Highest Priority
   - Alert notifications
   - Critical system events
   - Immediate processing required

2. **P2 Queue** (`p2_scripts`) - Medium Priority
   - Script execution results
   - Background task results
   - Deferred processing

3. **P3 Queue** (`p3_reserved`) - Low Priority
   - Reserved for future use
   - Batch processing
   - Non-urgent tasks

### Queue Operations

The `RedisQueueProcessor` handles all queue operations:

```python
from shared.src.lib.utils.redis_queue import get_queue_processor

# Get queue processor instance
queue = get_queue_processor()

# Add items to queues
queue.add_alert_to_queue(alert_id, alert_data)
queue.add_script_to_queue(script_id, script_data)

# Check queue lengths
lengths = queue.get_all_queue_lengths()
# Returns: {'p1_alerts': 5, 'p2_scripts': 12, 'p3_reserved': 0}

# Peek at queue items (without removing)
items = queue.peek_queue('p2_scripts', limit=10)

# Clear a queue
queue.clear_queue('p2_scripts')

# Health check
is_healthy = queue.health_check()
```

### Monitoring Queues

```bash
# Using Redis CLI (local)
redis-cli LLEN p1_alerts
redis-cli LLEN p2_scripts
redis-cli LLEN p3_reserved

# View queue items
redis-cli LRANGE p2_scripts 0 10

# Using the application API
curl http://localhost:5109/api/health
# Returns queue lengths in response
```

## Auto-Detection Logic

The system automatically detects Redis connection type:

```python
# In shared/src/lib/utils/redis_queue.py

if redis_url.startswith('https://'):
    # Use Upstash REST API
    # Requires REDIS_TOKEN
    mode = 'upstash'
    
elif redis_url.startswith('redis://'):
    # Use local TCP connection
    # Optional REDIS_PASSWORD
    mode = 'local'
```

### Unified Redis Usage

All VirtualPyTest components now use the **same shared Redis configuration**:

**Backend Server** (`backend_server/src/agent/core/manager.py`):
```python
from shared.src.lib.utils.redis_queue import get_queue_processor

# AI agents use shared queue processor
redis_processor = get_queue_processor()

# Check health
if redis_processor.health_check():
    print(f"Connected via {redis_processor.redis_mode}")
```

**API Routes** (`backend_server/src/routes/server_ai_queue_routes.py`):
```python
from shared.src.lib.utils.redis_queue import get_queue_processor

# Same processor for queue monitoring
queue_processor = get_queue_processor()
lengths = queue_processor.get_all_queue_lengths()
```

**Benefits of Unified Setup**:
- ✅ Single Redis instance for all components
- ✅ Consistent configuration across codebase  
- ✅ Works with both local and cloud Redis
- ✅ Automatic mode detection
- ✅ No duplicate Redis implementations

## Troubleshooting

### Local Redis Not Starting

```bash
# Check service status
sudo systemctl status redis-server

# Check logs
sudo journalctl -u redis-server -n 50

# Verify port is listening
sudo netstat -tlnp | grep 6379

# Test connection
redis-cli ping

# Check Redis process
ps aux | grep redis-server

# Verify data directory permissions
ls -la /data/redis
sudo chown -R redis:redis /data/redis
```

### Upstash Connection Failed

**Error**: `Name or service not known`

**Cause**: REDIS_URL is set to Upstash but:
- Network connectivity issue
- Invalid URL
- Missing REDIS_TOKEN

**Fix**:
```bash
# Verify environment variables
echo $REDIS_URL
echo $REDIS_TOKEN

# Test with curl
curl -H "Authorization: Bearer $REDIS_TOKEN" $REDIS_URL/ping

# Switch to local Redis for testing
export REDIS_URL=redis://localhost:6379
unset REDIS_TOKEN
```

### Wrong Redis Mode Detected

**Error**: Trying to use Upstash in local environment

**Cause**: `REDIS_URL` is set to `https://...` but you want local

**Fix**:
```bash
# Use redis:// URL for local
export REDIS_URL=redis://localhost:6379

# Remove Upstash token
unset REDIS_TOKEN
```

### Queue Operations Failing

```bash
# Check Redis connection
redis-cli ping

# Check queue lengths
redis-cli LLEN p1_alerts
redis-cli LLEN p2_scripts

# Clear stuck queues
redis-cli DEL p1_alerts
redis-cli DEL p2_scripts

# Verify memory
redis-cli INFO memory

# Check if Redis is full
redis-cli CONFIG GET maxmemory
```

### Permission Denied

```bash
# Check Redis is running
sudo systemctl status redis-server

# Verify data directory
sudo chown -R redis:redis /data/redis
sudo chmod 755 /data/redis

# Restart service
sudo systemctl restart redis-server
```

## Performance Tuning

### Memory Management

```bash
# Check memory usage
redis-cli INFO memory

# Set memory limit (in redis.conf)
maxmemory 256mb
maxmemory-policy allkeys-lru

# Or at runtime
redis-cli CONFIG SET maxmemory 256mb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

### Persistence Options

**AOF (Append Only File)** - More durable:
```ini
appendonly yes
appendfsync everysec  # Balance between performance and durability
```

**RDB (Snapshot)** - Faster, less durable:
```ini
save 900 1
save 300 10
save 60 10000
```

**Disable Persistence** (fastest, no durability):
```ini
save ""
appendonly no
```

### Connection Pooling

VirtualPyTest automatically uses connection pooling:

```python
# For local Redis (redis-py)
redis.Redis(
    host=host,
    port=port,
    socket_timeout=5,
    socket_connect_timeout=5,
    decode_responses=True
)

# Connection pool is managed automatically
```

## Security Best Practices

### Local Redis

1. **Enable Authentication**:
   ```ini
   # In /etc/redis/redis.conf
   requirepass your_strong_password_here
   ```

2. **Bind to Specific Interface**:
   ```ini
   # Only allow localhost
   bind 127.0.0.1
   
   # Allow specific network
   bind 127.0.0.1 192.168.x.102
   ```

3. **Disable Dangerous Commands**:
   ```ini
   rename-command FLUSHDB ""
   rename-command FLUSHALL ""
   rename-command CONFIG ""
   ```

4. **Use Firewall**:
   ```bash
   # Only allow from specific IPs
   sudo ufw allow from 192.168.x.0/24 to any port 6379
   ```

### Upstash (Cloud)

1. **Protect REST Token**: Never commit to git
2. **Use Environment Variables**: Store in `.env` file
3. **Rotate Tokens**: Regularly rotate credentials
4. **Monitor Access**: Check Upstash dashboard for unusual activity

## Migration Guide

### From Upstash to Local

```bash
# 1. Install local Redis
sudo ./setup/local/linux/storage/install_redis.sh

# 2. Update .env
REDIS_URL=redis://localhost:6379
# Remove: REDIS_TOKEN

# 3. Restart application
sudo systemctl restart vpt-server-host
```

### From Local to Upstash

```bash
# 1. Create Upstash database
# (via upstash.com dashboard)

# 2. Update .env
REDIS_URL=https://your-database.upstash.io
REDIS_TOKEN=your_token_here

# 3. Restart application
sudo systemctl restart vpt-server-host
```

## Monitoring

### Key Metrics

```bash
# Connected clients
redis-cli INFO clients

# Memory usage
redis-cli INFO memory

# Stats
redis-cli INFO stats

# Queue lengths
redis-cli LLEN p1_alerts
redis-cli LLEN p2_scripts
redis-cli LLEN p3_reserved

# Slow operations
redis-cli SLOWLOG GET 10
```

### Health Check Endpoint

```bash
# Check application health (includes Redis status)
curl http://localhost:5109/api/health

# Returns:
# {
#   "redis": {
#     "status": "healthy",
#     "queues": {
#       "p1_alerts": 0,
#       "p2_scripts": 5,
#       "p3_reserved": 0
#     }
#   }
# }
```

## References

- **Redis Documentation**: [redis.io/documentation](https://redis.io/documentation)
- **Upstash Documentation**: [upstash.com/docs/redis](https://upstash.com/docs/redis)
- **redis-py Library**: [github.com/redis/redis-py](https://github.com/redis/redis-py)
- **VirtualPyTest Queue Processor**: `shared/src/lib/utils/redis_queue.py`

---

**Version**: 6.2 (Redis Commander Web GUI via Node.js/npm)
**Last Updated**: January 2026
