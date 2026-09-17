# VirtualPyTest Storage VM - Overview

## Disk Mapping

| Proxmox Disk | VM Disk | VM Partition | Size | Purpose | NFS Access |
|-------------|---------|--------------|------|---------|------------|
| **scsi0** | **sda** | **sda1** | 100GB | System (OS) | Local only |
| **scsi1** | **sdb** | **sdb1** | 2TB+ | Data (rw) | Backend Server + Host VMs |
| **scsi2** | **sdc** | **sdc1** | 100-200GB | Shared (ro) | All VMs |

## Storage Setup Workflow

### Step 1: Disk Partitioning (Proxmox Only)
```bash
# Run on Storage VM
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./create_disks_partitions.sh
```
**What it does:**
- Creates partitions sdb1 → /data, sdc1 → /shared
- Formats as ext4
- Mounts to /data, /shared
- Adds to /etc/fstab for persistence

**Note:** Skip this step for standalone Linux (installer creates directories instead)

### Step 2: Install Storage Services
```bash
# Run on Storage VM (same as standalone Linux)
cd ~/virtualpytest/setup/local/linux/storage
sudo ./install_storage.sh
```
**What it does:**
- Ensures /data and /shared exist (uses mounts if available, creates directories otherwise)
- Copies code to /shared/code/virtualpytest (source of truth)
- Creates /opt/virtualpytest (local execution copy)
- Installs MinIO → /data/minio
- Installs Redis → /data/redis
- Creates service accounts (minio-user, vpt_user)
- Starts all services

### Step 3: Setup NFS Server (Multi-VM Only)
```bash
# Run on Storage VM (optional, for multi-VM deployments)
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./storage_setup_nfs_server.sh
```
**What it does:**
- Installs NFS server components
- Exports /data (rw) to Backend Server + Hosts
- Exports /shared (ro) to all VMs
- Starts NFS services

**Note:** Skip this step for single-machine deployments

### Test Installation
```bash
# Verify everything works
cd ~/virtualpytest/setup/local/linux/storage
./test_storage.sh
```

## Storage VM Folder Structure

```
/ (System - sda1, 100GB, local only)
├── /opt/virtualpytest/           # Local execution copy
│   ├── backend_host/             # Backend host code
│   ├── backend_server/           # Backend server code
│   ├── frontend/                 # Frontend code
│   └── shared/                   # Shared libraries
├── /etc/systemd/system/          # Service files
│   ├── minio.service
│   └── redis-server.service
└── /var/lib/                     # Service accounts
    ├── vpt_user/                 # VirtualPyTest service user
    └── minio-user/               # MinIO service user

/data (Data Partition - sdb1, 2TB+)
├── minio/                        # MinIO S3-compatible storage
│   ├── .minio.sys/               # MinIO system data
│   └── virtualpytest/            # Bucket: test images, videos, logs, results
└── redis/                        # Redis cache data
    ├── appendonly.aof            # Redis persistence
    └── dump.rdb                  # Redis snapshot
→ NFS Export: rw for Backend Server (192.168.x.103) + Backend Hosts (192.168.x.140/28)
→ Services: MinIO (port 9000), Redis (port 6379)

/shared (Shared Partition - sdc1, 100-200GB)
└── code/
    └── virtualpytest/            # **SOURCE OF TRUTH** - Main repository
        ├── backend_host/         # Backend host code
        ├── backend_server/       # Backend server code
        ├── frontend/             # Frontend React app
        ├── shared/               # Shared Python libraries
        ├── setup/                # Installation scripts
        ├── infra/                # Infrastructure services
        │   ├── monitoring/grafana/ # Monitoring dashboards
        │   ├── proxy/nginx/        # Reverse proxy configs
        │   ├── database/supabase/  # Supabase project files
        │   └── storage/            # MinIO + Redis
        ├── docs/                 # Documentation
        └── .git/                 # Git repository (if copied from git clone)
→ NFS Export: ro for ALL VMs (192.168.x.0/24)
→ Purpose: Central code repository, read-only access for all VMs
```

### Key Directories Explained

#### `/opt/virtualpytest` (Local Execution Copy)
- **Location**: System disk (sda)
- **Purpose**: Local copy for running services on Storage VM
- **Owner**: `vpt_user`
- **Created by**: `install_storage.sh`
- **Why**: Each VM has its own `/opt/virtualpytest` for local execution

#### `/data/minio` (MinIO S3 Storage)
- **Location**: Data disk (sdb) or local directory
- **Purpose**: S3-compatible object storage
- **Owner**: `minio-user`
- **API Endpoint**: http://localhost:9000
- **Web Console**: http://localhost:9001
- **Credentials**: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`
- **Bucket**: `virtualpytest`
- **Stores**: Test screenshots, videos, logs, results, artifacts

#### `/data/redis` (Redis Cache)
- **Location**: Data disk (sdb) or local directory
- **Purpose**: Caching and session storage
- **Owner**: `redis`
- **Port**: 6379
- **Password**: virtualpytest_redis_password
- **Stores**: Session data, temporary cache, queue data

#### `/shared/code/virtualpytest` (Source of Truth)
- **Location**: Shared disk (sdc) or local directory
- **Purpose**: Central code repository for all VMs
- **Owner**: `nobody:nogroup` (for NFS sharing)
- **Created by**: `install_storage.sh` (copies from current location)
- **Access**: 
  - Storage VM: Local read-write (can update code)
  - Other VMs: NFS read-only mount (cannot modify code)
- **Why**: Single source of truth, prevents code drift across VMs

## VM Access Permissions

| VM Type | /data Access | /shared Access | Network Access |
|---------|-------------|----------------|----------------|
| **Storage VM** (192.168.x.100) | Local rw | Local rw | - |
| **Backend Server** (192.168.x.103) | NFS rw | NFS ro | 192.168.x.103 |
| **Backend Host VMs** (192.168.x.140+) | NFS rw | NFS ro | 192.168.x.140/28 |
| **Frontend** (192.168.x.105) | No access | NFS ro | 192.168.x.105 |
| **Monitoring** (192.168.x.106) | No access | NFS ro | 192.168.x.106 |
| **Database** (192.168.x.102) | No access | NFS ro | 192.168.x.102 |
| **Reverse Proxy** (192.168.x.107) | No access | NFS ro | 192.168.x.107 |

## NFS Export Configuration

```bash
# /etc/exports on Storage VM (created by storage_setup_nfs_server.sh)
/data 192.168.x.103(rw,sync,no_subtree_check,no_root_squash)         # Backend Server only
/data 192.168.x.140/28(rw,sync,no_subtree_check,no_root_squash)      # Backend Host range
/shared 192.168.x.0/24(ro,sync,no_subtree_check,no_root_squash)      # All VMs: read-only
```

## VM Mount Configuration

### Backend Server & Host VMs

**Requirement:** Both /data and /shared access

```bash
# Mount both data (rw) + shared (ro)
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_data_shared.sh
```

**Mounted paths:**
- `/mnt/data` (rw) → Storage VM's `/data`
  - MinIO S3 storage
  - Redis cache data
- `/mnt/shared` (ro) → Storage VM's `/shared`
  - Code at `/mnt/shared/code/virtualpytest`

**Use cases:**
- Backend Server: Write test results to MinIO via S3 API
- Backend Host: Store screenshots/videos to MinIO bucket
- Both: Access shared code from `/mnt/shared/code/virtualpytest`
- Both: Copy code to local `/opt/virtualpytest` for execution

### Frontend, Monitoring, Database, Reverse Proxy

**Requirement:** Only /shared access (no data access for security)

```bash
# Mount only shared (ro)
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_shared.sh
```

**Mounted paths:**
- `/mnt/shared` (ro) → Storage VM's `/shared`
  - Code at `/mnt/shared/code/virtualpytest`
- No `/mnt/data` mount (data isolation)

**Use cases:**
- Frontend: `/mnt/shared/code/virtualpytest/frontend/`
- Monitoring: `/mnt/shared/code/virtualpytest/infra/monitoring/grafana/`
- Database: `/mnt/shared/code/virtualpytest/setup/db/`
- Reverse Proxy: `/mnt/shared/code/virtualpytest/infra/proxy/nginx/`

## Specific VM Examples

### Frontend VM (192.168.x.105)
```bash
# Mount shared code
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_shared.sh

# Copy to local for execution
cd ~/virtualpytest/setup/local/linux/frontend
sudo ./install_frontend.sh

# Result:
# - /mnt/shared/code/virtualpytest → source of truth (ro)
# - /opt/virtualpytest → local copy for execution (rw)
# - Frontend runs from /opt/virtualpytest/frontend/
```

### Backend Server VM (192.168.x.103)
```bash
# Mount both data and shared
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_data_shared.sh

# Install backend server
cd ~/virtualpytest/setup/local/linux/backend_server
sudo ./install_server.sh

# Result:
# - /mnt/data → MinIO S3, Redis (rw)
# - /mnt/shared/code/virtualpytest → source (ro)
# - /opt/virtualpytest → local copy (rw)
# - Can write to MinIO S3 storage
# - Can write to Redis cache
```

### Backend Host VM (192.168.x.141)
```bash
# Mount both data and shared
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_data_shared.sh

# Install backend host
cd ~/virtualpytest/setup/local/linux/backend_host
sudo ./install_host.sh

# Result:
# - /mnt/data → MinIO S3, Redis (rw)
# - /mnt/shared/code/virtualpytest → source (ro)
# - /opt/virtualpytest → local copy (rw)
# - Can capture screenshots to MinIO
# - Can store test videos to MinIO
```

### Monitoring VM (192.168.x.106)
```bash
# Mount shared code only
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo ./mount_nfs_shared.sh

# Install Grafana
cd ~/virtualpytest/setup/local/linux/monitoring
sudo ./install_grafana.sh

# Result:
# - /mnt/shared/code/virtualpytest → source (ro)
# - /opt/virtualpytest → local copy (rw)
# - Grafana dashboards from /opt/virtualpytest/infra/monitoring/grafana/
```

## Architecture Benefits

### Centralized Storage
✅ **Single Source of Truth**: `/shared/code/virtualpytest` on Storage VM
✅ **No Code Drift**: All VMs mount the same code repository
✅ **Easy Updates**: Update code once on Storage VM, all VMs see changes

### Data Isolation
✅ **Minimal Access**: VMs only access what they need
✅ **Read-Only Code**: Prevents accidental code changes in production
✅ **Isolated Data**: Sensitive test data only accessible to Backend VMs

### Performance
✅ **Local Execution**: Each VM runs from `/opt/virtualpytest` (fast)
✅ **Shared Storage**: MinIO/Redis on dedicated disks (optimized I/O)
✅ **Network Efficiency**: NFS used only for code sync, not execution

### Security
✅ **Network Segregation**: IP-based NFS access control
✅ **Service Isolation**: Separate service accounts (minio-user, vpt_user)
✅ **Permission Layers**: Storage VM (rw) vs Other VMs (ro)

## Backup Strategy

### Option A: Storage VM Level
```bash
# Backup /data and /shared
/data/backups/
├── daily/           # Automated daily backups
├── weekly/          # Weekly full backups
└── snapshots/       # Point-in-time snapshots
```

### Option B: Proxmox Level
```bash
# Proxmox VM snapshots
# Backup entire VM including disks
# Restore full VM state if needed
```

### Option C: Service Level
```bash
# MinIO: Built-in replication
# Redis: AOF + RDB persistence
# Git: Push to remote repository
```

## Troubleshooting

### Check NFS Exports
```bash
# On Storage VM
sudo showmount -e 127.0.0.1
```

### Check NFS Mounts
```bash
# On other VMs
df -h | grep mnt
mount | grep nfs
```

### Verify Services
```bash
# On Storage VM
sudo systemctl status minio redis-server nfs-kernel-server
```

### Test Storage
```bash
# On Storage VM
cd ~/virtualpytest/setup/local/linux/storage
./test_storage.sh
```

### Access MinIO Console
```
# From your browser
http://192.168.x.100:9001

# Login:
Username: virtualpytest
Password: generated per install (`.env`)
```

### Test Redis
```bash
# On Storage VM
redis-cli -a virtualpytest_redis_password ping
# Should return: PONG
```

## Related Documentation

- **Disk Partitioning**: `create_disks_partitions.sh` (Proxmox setup)
- **Storage Installation**: `~/virtualpytest/setup/local/linux/storage/install_storage.sh`
- **NFS Setup**: `storage_setup_nfs_server.sh` (multi-VM)
- **Storage Architecture**: `README.md` (detailed setup guide)
- **Testing**: `test_storage.sh` (comprehensive tests)
