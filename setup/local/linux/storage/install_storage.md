# Storage VM Installation

## Overview

The Storage VM provides data storage services for the VirtualPyTest architecture:
- **MinIO** - S3-compatible object storage
- **Redis** - Caching and session storage

## Prerequisites

- Debian/Ubuntu Linux
- sudo access for system service configuration
- `/data` directory mounted and available (disk mounting handled at infrastructure level)
- `/shared` directory mounted and available (disk mounting handled at infrastructure level)

## Quick Start

```bash
# Clone the repository
git clone <repo> ~/virtualpytest

# Run the installer
cd ~/virtualpytest
sudo ./setup/local/linux/storage/install_storage.sh
```

The installer will:
- Create service user (`vpt_user`)
- Install Redis server
- Install Redis Commander (Redis Web GUI via Node.js/npm)
- Install MinIO server
- Configure systemd services
- Create default bucket

## Directory Structure

```
/data/
├── minio/              # MinIO object storage data
└── redis/              # Redis persistence data

/opt/
└── virtualpytest/      # Local copy for service configuration
```

## Services Installed

### Redis Server (`redis-server.service`)
- **Purpose**: Network-accessible caching and session storage
- **Port**: 6379
- **Password**: generated per install (`.env`)
- **Data location**: `/data/redis`

### Redis Commander (`redis-commander.service`)
- **Purpose**: Web GUI for Redis management (like Upstash)
- **Port**: 8081
- **Local URL**: http://localhost:8081
- **Proxied URL**: https://your-domain/redis/
- **Web Login**: admin / the password in `.env`
- **Requires**: Node.js and npm (installed automatically)

### MinIO Server (`minio.service`)
- **Purpose**: S3-compatible object storage
- **Console**: Port 9001
- **API**: Port 9000
- **Data location**: `/data/minio`
- **Credentials**: 
  - Access Key: `virtualpytest`
  - Secret Key: `MINIO_SECRET_KEY` from `.env`
- **Default Bucket**: `virtualpytest`

## Service Management

### Check Status

```bash
# All storage services
sudo systemctl status redis-server redis-commander minio

# Individual services
sudo systemctl status minio
sudo systemctl status redis-server
sudo systemctl status redis-commander
```

### View Logs

```bash
# MinIO logs
sudo journalctl -u minio -f

# Redis logs
sudo journalctl -u redis-server -f

# Redis Commander logs
sudo journalctl -u redis-commander -f
```

### Restart Services

```bash
# Restart MinIO
sudo systemctl restart minio

# Restart Redis
sudo systemctl restart redis-server

# Restart Redis Commander
sudo systemctl restart redis-commander
```

## Service Testing

### Test Redis

```bash
# Test connection
redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping
# Expected output: PONG

# Test operations
redis-cli -a "$REDIS_PASSWORD" --no-auth-warning set test_key "test_value"
redis-cli -a "$REDIS_PASSWORD" --no-auth-warning get test_key
redis-cli -a "$REDIS_PASSWORD" --no-auth-warning del test_key
```

### Test MinIO

```bash
# Configure MinIO client
mc alias set local http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"

# List buckets
mc ls local/

# Test bucket access
mc ls local/virtualpytest

# Upload test file
echo "test" > /tmp/test.txt
mc cp /tmp/test.txt local/virtualpytest/test.txt

# Download test file
mc cp local/virtualpytest/test.txt /tmp/test_download.txt

# Delete test file
mc rm local/virtualpytest/test.txt
rm /tmp/test.txt /tmp/test_download.txt
```

## Configuration

### Object Lifecycle / Retention (ILM)

`install_minio.sh` sets default auto-expiry rules on the `virtualpytest` bucket so
uploaded run artifacts don't grow the disk forever. Rules are per-prefix and match
the upload paths in `shared/src/lib/utils/cloudflare_utils.py`:

| Prefix                 | Default expiry | Content                                  |
|------------------------|----------------|-------------------------------------------|
| `script-reports/`      | 14 days        | Script test reports (HTML, video, images) |
| `restart-reports/`     | 14 days        | Restart video reports                     |
| `zap-reports/`         | 14 days        | Zap reports                               |
| `kpi_measurement/`     | 14 days        | KPI measurement thumbnails + reports      |
| `heatmaps/`            | 14 days        | Heatmap mosaic HTML                       |
| `script-logs/`         | 14 days        | Execution logs, verification review, metadata |
| `alerts/`              | 14 days        | Alert artifacts                           |
| `audio-analysis/`      | 14 days        | Audio analysis clips                      |
| `script-screenshots/`  | 14 days        | Per-step screenshots                      |
| `reports/`             | 14 days        | Validation / exploration reports          |
| `fleet-health/`        | 14 days        | Daily fleet-health report artifacts       |

**Every prefix `cloudflare_utils.py` writes to must appear in this table.** A prefix
with no rule never expires. On the Awesomation instance `script-screenshots/` (5.1G)
and `reports/` had no rule, `/data` reached 95%, and MinIO began refusing *every*
upload with `XMinioStorageFull` — script runs then record `success=false` purely
because their report could not be stored (2026-09-14). Check with
`mc ilm rule ls` after adding any new upload path.

**Never set an expiry rule on `navigation/` or `reference-images/`.** Those are the
permanent navigation-tree screenshot and reference-image libraries the product reads
from on every run, not per-execution artifacts — an expiry rule on them silently
deletes production data, not cleanup.

**Free space immediately** (ILM only acts when MinIO's scanner next runs):
```bash
mc rm --recursive --force --older-than 14d local/virtualpytest/<prefix>/
```
Add `--dry-run` first. Never run this against `navigation/` or `reference-images/`.

**Verify current rules:**
```bash
mc ilm rule ls local/virtualpytest
```

**Change a rule's retention** (e.g. bump `script-logs/` to 30 days) — remove and re-add,
`mc ilm` has no in-place edit:
```bash
mc ilm rule ls local/virtualpytest   # find the rule ID for the prefix
mc ilm rule rm local/virtualpytest --id <RULE_ID>
mc ilm rule add --expire-days 30 local/virtualpytest --prefix "script-logs/"
```

**Add a rule for a new prefix** not in the table above:
```bash
mc ilm rule add --expire-days 14 local/virtualpytest --prefix "new-prefix/"
```

MinIO only deletes the *object*, not the local disk copy — this bounds bucket growth,
it does not clean up `/data/stream/*` on backend_host machines. That's a separate,
mostly-unimplemented concern (see `backend_host/scripts/hot_cold_archiver.py` for the
one local cleanup job that exists, covering `captures/verification_results/` only).

### MinIO Configuration

**Location**: `/etc/default/minio`

```bash
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=<MINIO_SECRET_KEY from .env>
MINIO_OPTS="--address :9000 --console-address :9001"
MINIO_DRIVES="/data/minio"
```

### MinIO Reverse Proxy Configuration (Required for nginx)

When accessing MinIO Console through an nginx reverse proxy with a subpath (e.g., `/minio-console/`), you **must** configure `MINIO_BROWSER_REDIRECT_URL`. Without this, the console will try to load assets from the root path instead of the subpath.

**Add to** `/etc/default/minio`:

```bash
MINIO_BROWSER_REDIRECT_URL=https://<REVERSE_PROXY_IP>/minio-console/
```

**Example** (replace with your actual proxy IP):

```bash
# Add the redirect URL
echo 'MINIO_BROWSER_REDIRECT_URL=https://192.168.x.107/minio-console/' | sudo tee -a /etc/default/minio

# Restart MinIO to apply
sudo systemctl restart minio
```

**Why is this needed?**
- MinIO Console is a React SPA that generates root-relative URLs (`/static/js/...`)
- Without the redirect URL, browser requests go to `https://proxy/static/...` instead of `https://proxy/minio-console/static/...`
- The nginx proxy only handles `/minio-console/` paths, so root requests fail with 404

### Redis Configuration

**Location**: `/etc/redis/redis.conf`

Key settings:
```bash
# Data directory
dir /data/redis

# Password
requirepass <REDIS_PASSWORD from .env>

# Persistence
appendonly yes
```

### Application Environment Variables

Add these to your application's configuration:

```bash
# MinIO S3-Compatible Storage
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=<generated per install>
MINIO_BUCKET=virtualpytest
MINIO_CONSOLE_URL=http://localhost:9001
# Proxied access through nginx:
# MINIO_CONSOLE_URL=https://your-domain/minio-console/

# Redis Caching
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=<generated per install>
REDIS_DB=0

# Redis Commander (Web GUI)
REDIS_COMMANDER_URL=http://localhost:8081
# Proxied access through nginx:
# REDIS_COMMANDER_URL=https://your-domain/redis/
```

## Access Points

### MinIO Console (Web Interface)
- **Local URL**: http://localhost:9001
- **Proxied URL**: https://your-domain/minio-console/
- **Login**: virtualpytest
- **Password**: generated per install (`.env`)

### MinIO API
- **URL**: http://localhost:9000

### Redis Server
- **Host**: localhost
- **Port**: 6379
- **Password**: generated per install (`.env`)

### Redis Commander (Web GUI)
- **Local URL**: http://localhost:8081
- **Proxied URL**: https://your-domain/redis/
- **Web Login**: admin / the password in `.env`
- **Redis auto-connected**: 127.0.0.1:6379 with password

## Verification

### Check Data Directories

```bash
# Verify data directories exist and have correct ownership
ls -la /data/minio
ls -la /data/redis

# Check disk space
df -h /data
```

### Verify Services are Running

```bash
# Check if services are active
systemctl is-active minio
systemctl is-active redis-server
systemctl is-active redis-commander

# Check if ports are listening
sudo netstat -tlnp | grep -E ':(9000|9001|6379|8081)'
```

### Run Automated Tests

```bash
# Run the test suite
cd ~/virtualpytest/setup/local/linux/storage
./test_storage.sh
```

The test script verifies:
- Service user configuration
- Directory structure
- Service status
- Redis functionality (connection, operations)
- MinIO functionality (bucket access, file operations)
- Disk space availability

## Troubleshooting

### Services Not Starting

```bash
# Check service status
sudo systemctl status minio
sudo systemctl status redis-server

# View detailed logs
sudo journalctl -u minio -n 50
sudo journalctl -u redis-server -n 50

# Verify data directory permissions
ls -la /data/minio
ls -la /data/redis
```

### MinIO Bucket Not Accessible

```bash
# Verify MinIO service is running
sudo systemctl status minio

# Check if bucket exists
mc alias set local http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc ls local/

# Create bucket manually if needed
mc mb local/virtualpytest
```

### Redis Connection Issues

```bash
# Test local connection
redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping

# Check Redis configuration
grep -E "requirepass|bind" /etc/redis/redis.conf

# Verify Redis is listening
sudo netstat -tlnp | grep 6379
```

### Redis Commander Issues

```bash
# Check service status
sudo systemctl status redis-commander

# Check if port 8081 is listening
sudo netstat -tlnp | grep 8081

# View logs for errors
sudo journalctl -u redis-commander -n 50

# Verify working directory exists
ls -la /var/lib/redis-commander

# Test manually as vpt_user
sudo -u vpt_user redis-commander --redis-host 127.0.0.1 --redis-port 6379 --redis-password "$REDIS_PASSWORD" --http-auth admin:"$REDIS_PASSWORD"
```

### Permission Errors

```bash
# Verify ownership
sudo chown -R minio-user:minio-user /data/minio
sudo chown -R redis:redis /data/redis

# Restart services
sudo systemctl restart minio redis-server
```

## Update Procedure

To update the storage services:

```bash
# Pull latest code
cd ~/virtualpytest
git pull

# Re-run installer
sudo ./setup/local/linux/storage/install_storage.sh

# Verify services restarted correctly
sudo systemctl status minio redis-server
```

The installer is idempotent and can be safely run multiple times.

## Additional Tools

The installer also includes:

- **rclone**: Cloud storage compatibility and migration
- **rsync**: Efficient file synchronization
- **borgbackup**: Backup and restore functionality
- **p7zip-full**: Archive compression
- **pigz**: Parallel gzip compression

---

**Version**: 5.1 (Added Redis Commander Web GUI)  
**Last Updated**: January 2026
