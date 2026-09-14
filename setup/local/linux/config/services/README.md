# VirtualPyTest Service Configuration Files

This directory contains systemd service configuration files used by VirtualPyTest installation scripts.

## Service Files

### Storage Services

#### `redis-server.service`
- **Purpose**: Systemd service for Redis server
- **Deployed to**: `/etc/systemd/system/redis-server.service`
- **Used by**: `setup/local/linux/storage/install_redis.sh`
- **Description**: Configures Redis for VirtualPyTest caching and message queuing with proper security and performance settings

#### `minio.service`
- **Purpose**: Systemd service for MinIO (S3-compatible object storage)
- **Deployed to**: `/etc/systemd/system/minio.service`
- **Used by**: `setup/local/linux/storage/install_minio.sh`
- **Description**: Configures MinIO for VirtualPyTest object storage (screenshots, videos, logs, test results)

### Other Services

#### `grafana-server.service`
- **Purpose**: Systemd service for Grafana monitoring
- **Deployed to**: `/etc/systemd/system/grafana-server.service`
- **Description**: Configures Grafana for VirtualPyTest monitoring and metrics visualization

#### `supabase.service`
- **Purpose**: Systemd service for Supabase
- **Deployed to**: `/etc/systemd/system/supabase.service`
- **Used by**: `setup/local/linux/database/install_supabase.sh`
- **Description**: Configures Supabase backend services with PostgreSQL, Auth, Storage, and API

#### `vpt_server_host.service`
- **Purpose**: Systemd service for combined server+host deployment (single machine, e.g. Raspberry Pi)
- **Deployed to**: `/etc/systemd/system/vpt-server-host.service`
- **Description**: Runs both backend server and host on the same machine

## Benefits of Separated Service Files

1. **Better Visibility**: Service configurations are easy to find, review, and compare
2. **Version Control**: Service definitions are tracked separately from installation logic
3. **Reusability**: Service files can be referenced by multiple scripts or documentation
4. **Maintainability**: Easier to update service configurations without touching installation scripts
5. **Consistency**: Follows the same pattern as other VirtualPyTest components (backend_server, backend_host, frontend)

## Usage Pattern

Installation scripts locate these files using:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/services"
sudo cp "${CONFIG_DIR}/service-name.service" /etc/systemd/system/service-name.service
```

## Modifying Service Files

To modify a service configuration:

1. Edit the service file in this directory
2. Re-run the appropriate installation script to deploy the changes
3. Reload systemd: `sudo systemctl daemon-reload`
4. Restart the service: `sudo systemctl restart <service-name>`
