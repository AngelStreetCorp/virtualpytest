# Proxmox Storage VM - Infrastructure Setup

## Autonomous Architecture

This directory handles **ONLY infrastructure** (disks, mounts, NFS).
Service installation (MinIO, Redis) uses the standard local installer.

```
Proxmox Level (Infrastructure):
├── create_disks_partitions.sh  → Creates/mounts disks
├── storage_setup_nfs_server.sh → Sets up NFS exports
└── test_storage.sh             → Tests infrastructure only

Local Level (Services):
├── install_storage.sh          → Installs MinIO + Redis
└── test_storage.sh             → Tests services only
```

## ⚠️ What Runs on This VM — and What Does NOT

| Service | Runs here? | Notes |
|---------|-----------|-------|
| MinIO (S3) | ✅ Yes | Port 9000 (API), 9001 (console) |
| Redis | ✅ Yes | Port 6379 |
| NFS server | ✅ Yes | Exports /data (rw) and /shared (ro) |
| **Supabase / PostgreSQL** | ❌ **NO** | Lives on the **database VM (192.168.x.102)** |

**Do NOT run `install_supabase.sh` or `install_db.sh` on the storage VM.**
In March 2026 this was done by mistake, creating an orphaned Supabase instance that caused the nginx proxy to serve the wrong database to the Studio UI. The fix required redirecting the nginx proxy to 192.168.x.102 and removing the accidental containers.

## Quick Start (Autonomous)

### On Proxmox Storage VM

```bash
# Step 1: Setup infrastructure (Proxmox-specific)
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo bash create_disks_partitions.sh
sudo bash storage_setup_nfs_server.sh
./test_storage.sh

# Step 2: Install services (same as standalone)
cd ~/virtualpytest/setup/local/linux/storage
sudo ./install_storage.sh
./test_storage.sh
```

That's it! The infrastructure scripts handle Proxmox-specific setup, then the local installer works exactly like on standalone systems.

## What Each Script Does

### 1. `create_disks_partitions.sh` (Proxmox Only)

**Purpose**: Prepare dedicated disks for storage

**What it does:**
- Checks for `/dev/sdb` and `/dev/sdc`
- Creates partitions (if not exist)
- Formats as ext4
- Mounts to `/data` and `/shared`
- Adds to `/etc/fstab` for persistence
- Copies code to `/shared/code/virtualpytest`

**Disk configuration:**
```
/dev/sdb → /data    (2TB+ recommended)
           ├── minio/  (created by install_storage.sh)
           └── redis/  (created by install_storage.sh)

/dev/sdc → /shared  (100GB recommended)
           └── code/
               └── virtualpytest/  (git repository)
```

**Run:**
```bash
sudo bash create_disks_partitions.sh
```

### 2. `storage_setup_nfs_server.sh` (Proxmox Only)

**Purpose**: Share storage with other VMs via NFS

**What it does:**
- Installs NFS server packages
- Configures exports in `/etc/exports`
- Sets tiered permissions:
  - `/data`: RW for Backend Server (192.168.x.103) & Backend Hosts (192.168.x.140/28)
  - `/shared`: RO for all VMs (192.168.x.0/24)
- Starts NFS services

**Run:**
```bash
sudo bash storage_setup_nfs_server.sh
```

### 3. `test_storage.sh` (Proxmox Only)

**Purpose**: Test infrastructure setup

**Tests:**
- ✅ Disk mounts (`/data`, `/shared`)
- ✅ `/etc/fstab` entries
- ✅ Code repository
- ✅ NFS server status
- ✅ NFS exports configuration

**Run:**
```bash
./test_storage.sh
```

### 4. Install Services (Uses Local Installer)

After infrastructure is ready, install services using the **standard local installer**:

```bash
cd ~/virtualpytest/setup/local/linux/storage
sudo ./install_storage.sh
```

This installs:
- MinIO (S3-compatible storage)
- Redis (caching)

The installer automatically detects that `/data` is mounted and uses it.

### 5. Test Services (Uses Local Test)

```bash
cd ~/virtualpytest/setup/local/linux/storage
./test_storage.sh
```

This tests:
- ✅ MinIO functionality
- ✅ Redis functionality
- ✅ Service status
- ✅ File operations

## Proxmox VM Setup

### 1. Create VM in Proxmox

**Recommended specs:**
- OS: Debian 12
- RAM: 8GB
- CPU: 4 cores
- Disks:
  - System: 100GB (sda)
  - Data: 2TB (sdb)
  - Shared: 100GB (sdc)

### 2. Attach Disks

In Proxmox UI:
1. Select VM → **Hardware**
2. Click **Add → Hard Disk**
   - First: 2TB → becomes `/dev/sdb`
   - Second: 100GB → becomes `/dev/sdc`

### 3. Run Infrastructure Setup

```bash
cd ~/virtualpytest/setup/proxmox/vm/storage

# Setup disks
sudo bash create_disks_partitions.sh

# Setup NFS
sudo bash storage_setup_nfs_server.sh

# Test infrastructure
./test_storage.sh
```

### 4. Install Services

```bash
cd ~/virtualpytest/setup/local/linux/storage

# Install MinIO + Redis
sudo ./install_storage.sh

# Test services
./test_storage.sh
```

## Verification

### Check Infrastructure

```bash
# Disk mounts
df -h | grep -E "/data|/shared"

# NFS exports
sudo showmount -e 127.0.0.1

# Test infrastructure
cd ~/virtualpytest/setup/proxmox/vm/storage
./test_infrastructure.sh
```

### Check Services

```bash
# Service status
sudo systemctl status minio redis-server

# Test services
cd ~/virtualpytest/setup/local/linux/storage
./test_storage.sh
```

## Standalone vs Proxmox

### Standalone Linux

```bash
# ONLY run local installer (no Proxmox scripts)
cd ~/virtualpytest/setup/local/linux/storage
sudo ./install_storage.sh
./test_storage.sh
```

The installer creates `/data` and `/shared` as directories on the system disk.

### Proxmox with Dedicated Disks

```bash
# First: Proxmox infrastructure scripts
cd ~/virtualpytest/setup/proxmox/vm/storage
sudo bash create_disks_partitions.sh
sudo bash storage_setup_nfs_server.sh
./test_infrastructure.sh

# Then: Same local installer as standalone
cd ~/virtualpytest/setup/local/linux/storage
sudo ./install_storage.sh
./test_storage.sh
```

The installer detects that `/data` and `/shared` are already mounted and uses them.

## Architecture Comparison

### Standalone
```
/data/              # Directory on system disk
  ├── minio/
  └── redis/
```

### Proxmox
```
/dev/sdb1 → /data/  # Dedicated 2TB disk
  ├── minio/
  └── redis/

/dev/sdc1 → /shared/  # Dedicated 100GB disk
  └── code/
      └── virtualpytest/
```

**Key Point**: The local installer (`install_storage.sh`) works the same in both cases!

## Troubleshooting

### Disks Not Found

```bash
# List all disks
lsblk

# Check if attached in Proxmox
# Proxmox UI → VM → Hardware
```

### Partprobe Not Found

The script auto-installs `parted` if needed. If you see this error, it's handled automatically.

### NFS Not Starting

```bash
# Check service status
sudo systemctl status nfs-kernel-server

# Check logs
sudo journalctl -u nfs-kernel-server -n 50

# Restart
sudo systemctl restart nfs-kernel-server
```

### Mount Failed

```bash
# Check if already mounted
mount | grep -E "sdb|sdc"

# Check fstab
cat /etc/fstab | grep -E "/data|/shared"

# Reload systemd
sudo systemctl daemon-reload
```

## Next Steps

After successful setup:

1. **Mount NFS on other VMs** (if multi-VM deployment)
2. **Configure firewall** for NFS ports (2049)
3. **Setup backups** for `/data` and `/shared`

## Files in This Directory

- `create_disks_partitions.sh` - Create and mount disks
- `storage_setup_nfs_server.sh` - Setup NFS server
- `test_storage.sh` - Test infrastructure
- `README.md` - This file

**Note**: For service installation and testing, use `setup/local/linux/storage/`

---

**Version**: 1.0 (Autonomous Infrastructure)  
**Last Updated**: January 2026
