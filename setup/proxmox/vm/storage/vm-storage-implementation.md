# VM Storage Implementation

## Overview

VirtualPyTest Storage VM provides NFS-shared storage with MinIO S3-compatible object storage and Redis caching. Setup occurs in three phases using dedicated scripts.

## Infrastructure Setup

### Proxmox VM Configuration
- **IP**: 192.168.x.100 (Storage VM)
- **Disks**: 3 virtual disks (100GB system + 2TB data + 200GB shared)
- **Network**: Internal network (192.168.x.0/24)

### Disk Mapping
| Proxmox Disk | VM Disk | VM Partition | Size | Purpose | NFS Access |
|-------------|---------|--------------|------|---------|------------|
| **scsi0** | **sda** | **sda1** | 100GB | System (OS) | Local only |
| **scsi1** | **sdb** | **sdb1** | 2TB+ | Data (rw) | Backend Server + Host VMs |
| **scsi2** | **sdc** | **sdc1** | 200GB | Shared (ro) | All VMs |

## Phase-by-Phase Installation

### Phase 1: Disk Partitioning (Proxmox Admin)
**Script**: `storage_create_disks_partitions.sh`
- Creates `sdb1` (ext4, label: data) → mounts to `/data`
- Creates `sdc1` (ext4, label: shared) → mounts to `/shared`
- Adds entries to `/etc/fstab` for persistence
- Sets permissions: `chown nobody:nogroup`
- Creates directory structure:
  - `/data/{images,videos,logs,results,minio,redis}`
  - `/shared/{code,scripts,utils,configs,docs}`

### Phase 2: NFS Server Setup (VM User)
**Script**: `storage_setup_nfs_server.sh`
- Installs: `nfs-kernel-server rpcbind`
- Copies VirtualPyTest repository to `/shared/code/` (via `scp` instead of `git clone`)
- Configures tiered NFS exports in `/etc/exports`:
  ```
  /data 192.168.x.103(rw,sync,no_subtree_check,no_root_squash)      # Backend Server only
  /data 192.168.x.140/28(rw,sync,no_subtree_check,no_root_squash)   # Backend Host range only
  /shared 192.168.x.0/24(ro,sync,no_subtree_check,no_root_squash)   # All VMs: read-only
  ```
- Enables services: `nfs-kernel-server rpcbind`
- Exports filesystem: `exportfs -ra`

### Phase 3: Storage Services Installation (VM User)
**Script**: `install_storage.sh` (calls `install_minio.sh` + `install_redis.sh`)

#### Redis Setup
- Installs Redis server with network access
- Configures password: `virtualpytest_redis_password`
- Port: 6379 (internal network only)

#### MinIO Setup
- Installs MinIO server + client (`mc`)
- Data stored on `/data` disk (not system disk)
- Credentials: `virtualpytest` / `<generated per install>`
- Creates bucket: `virtualpytest`
- Ports: 9000 (API), 9001 (Console)
- Configures systemd service for auto-start

## Storage Architecture

### Directory Structure
```
/ (System - sda1, local only)
├── OS and system files
└── No NFS sharing

/data (Data Partition - sdb1, 2TB+)
├── images/          # Test screenshots, captures
├── videos/          # Test recordings
├── logs/            # Application logs
├── results/         # Test execution results
├── minio/           # S3 storage data (bucket)
└── redis/           # Cache data (if moved from system disk)
→ NFS: rw for Backend Server + Backend Host VMs only

/shared (Shared Partition - sdc1, 200GB)
├── code/            # Source code repositories (scp'd VirtualPyTest)
├── scripts/         # Automation scripts
├── utils/           # System utilities
├── configs/         # Shared configurations
└── docs/            # Documentation
→ NFS: ro for ALL VMs
```

### VM Access Permissions
| VM Type | /data Access | /shared Access | Network Access |
|---------|-------------|----------------|----------------|
| **Storage VM** | Local rw | Local rw | - |
| **Backend Server** | NFS rw | NFS ro | 192.168.x.103 |
| **Backend Host VMs** | NFS rw | NFS ro | 192.168.x.140/28 |
| **Frontend** | No access | NFS ro | 192.168.x.105 |
| **Monitoring** | No access | NFS ro | 192.168.x.106 |
| **Database** | No access | NFS ro | 192.168.x.102 |
| **Reverse Proxy** | No access | NFS ro | 192.168.x.107 |

### VM Mount Configuration

**Backend Server & Host VMs:**
```bash
# Mount both directories
sudo ./setup/proxmox/vm/scripts/mount_nfs_data_shared.sh
# Result: /mnt/data (rw), /mnt/shared (ro)
```

**Frontend, Monitoring, Database, Reverse Proxy:**
```bash
# Mount shared only
sudo ./setup/proxmox/vm/scripts/mount_nfs_shared.sh
# Result: /mnt/shared (ro), no /mnt/data access
```

## Services Configuration

### MinIO (S3-Compatible Storage)
- **Console**: http://192.168.x.100:9001
- **API**: http://192.168.x.100:9000
- **Credentials**: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`
- **Bucket**: virtualpytest
- **Data Path**: /data/minio

### Redis (Caching)
- **Host**: 192.168.x.100:6379
- **Password**: virtualpytest_redis_password
- **Network**: Internal network only

## Configuration Reference

Add these to VirtualPyTest project configuration:

```bash
# MinIO S3-Compatible Storage
MINIO_ENDPOINT=http://192.168.x.100:9000
MINIO_ACCESS_KEY=virtualpytest
MINIO_SECRET_KEY=<generated per install>
MINIO_BUCKET=virtualpytest
MINIO_CONSOLE_URL=http://192.168.x.100:9001

# Redis Caching
REDIS_HOST=192.168.x.100
REDIS_PORT=6379
REDIS_PASSWORD=virtualpytest_redis_password
REDIS_DB=0

# Additional Paths
STORAGE_BASE_PATH=/data/minio
RCLONE_CONFIG_LOCAL=virtualpytest-local
```