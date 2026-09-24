# Proxmox Database VM - Infrastructure Setup

## Overview

This directory handles **ONLY infrastructure** (disk mount for database storage).
Database installation (PostgreSQL/Supabase) uses the standard local installer.

## ⚠️ Single Supabase Instance — Database VM Only

There is **one** Supabase instance in the entire infrastructure, running on **this VM (192.168.x.102)**.

| What | Where |
|------|-------|
| Supabase Studio | `https://<origin-ip>:54323` → proxied to `192.168.x.102:54323` |
| Supabase API (PostgREST) | `http://192.168.x.102:54321` |
| PostgreSQL direct | `postgresql://<user>:<password>@<host>:<port>/<db>` (see `local install_supabase.sh` for the actual values) |
| App data (testcases, nav trees, scripts, etc.) | This database |
| Monitoring metrics (system_metrics, system_device_metrics) | Also this database — Grafana reads directly via `54322` |

The storage VM (192.168.x.101) runs **MinIO + Redis only**. Do not install Supabase there.

```
Proxmox Level (Infrastructure):
├── create_disk_partition.sh  → Creates/mounts /dev/sdb to /data
└── test_database.sh          → Tests infrastructure only

Local Level (Services):
├── install_db.sh             → Installs Supabase (PostgreSQL) + InfluxDB
└── test_db.sh                → Tests database services
```

## Quick Start

### On Proxmox Database VM

```bash
# Step 1: Setup disk infrastructure (Proxmox-specific)
cd ~/virtualpytest/setup/proxmox/vm/database
sudo bash create_disk_partition.sh
./test_database.sh

# Step 2: Mount shared code repository (NFS from Storage VM)
cd ~/virtualpytest/setup/proxmox/vm/shared
sudo bash mount_nfs_shared.sh

# Step 3: Install database services (same as standalone)
cd /shared/code/virtualpytest/setup/local/linux/database
sudo ./install_db.sh
./test_db.sh
```

## Disk Configuration

### Recommended: Dedicated Database Partitions (sda1 + sdb1)
**Best Practice**: Create 2 dedicated partitions for database storage on both system and database disks.

**Advantages:**
- Better performance (RAID-0 like striping across disks)
- Improved I/O distribution
- Separate database partitions from OS
- Easier backup and maintenance

```
`/dev/sda1 + /dev/sdb1 → /databases (combined storage)
           ├── postgresql/   (PostgreSQL/Supabase data)
           ├── influxdb/     (InfluxDB time-series data)
           └── docker/       (Docker volumes)
               └── volumes/
```

**Partition sizes:**
- `/dev/sda1`: 50GB (from system disk)
- `/dev/sdb1`: 450GB+ (from database disk)
- **Total**: 500GB+ for development, 2TB+ for production

### Alternative: Single Database Disk (sdb)
```
/dev/sdb → /data (500GB+ recommended)
           ├── postgresql/   (PostgreSQL/Supabase data)
           ├── influxdb/     (InfluxDB time-series data)
           └── docker/       (Docker volumes)
               └── volumes/
```

**Recommended size**: 500GB for development, 2TB+ for production

## Scripts

### 1. `create_disk_partition.sh` (Proxmox Only)

**Purpose**: Prepare dedicated disk for database storage

**What it does:**
- Checks for `/dev/sdb`
- Creates partition (if not exist)
- Formats as ext4
- Mounts to `/data`
- Adds to `/etc/fstab` for persistence
- Creates subdirectories for PostgreSQL, InfluxDB, Docker

**Run:**
```bash
sudo bash create_disk_partition.sh
```

### 2. `test_database.sh` (Proxmox Only)

**Purpose**: Test infrastructure setup

**Tests:**
- ✅ Disk mount (`/data`)
- ✅ `/etc/fstab` entry
- ✅ Database directories (postgresql, influxdb, docker)
- ✅ NFS shared code mount (optional)
- ✅ Disk space

**Run:**
```bash
./test_database.sh
```

### 3. Install Database Services (Uses Local Installer)

After infrastructure is ready, install services using the **standard local installer**:

```bash
cd /shared/code/virtualpytest/setup/local/linux/database
sudo ./install_db.sh
```

This installs:
- Supabase (includes PostgreSQL, Auth, Storage, API via Docker)
- InfluxDB (time-series database)

The installer automatically detects that `/data` is mounted and configures databases to use it.

## Proxmox VM Setup

### 1. Create VM in Proxmox

**Recommended specs:**
- OS: Debian 12
- RAM: 16GB (databases are memory-intensive)
- CPU: 8 cores (required for Supabase performance)
- Disks:
  - System: 100GB (sda)
  - Database: 500GB-2TB (sdb)

### 2. Attach Database Disk

In Proxmox UI:
1. Select VM → **Hardware**
2. Click **Add → Hard Disk**
   - Size: 500GB-2TB → becomes `/dev/sdb`

### 3. Run Infrastructure Setup

```bash
cd ~/virtualpytest/setup/proxmox/vm/database

# Setup disk
sudo bash create_disk_partition.sh

# Test infrastructure
./test_database.sh
```

### 4. Mount Shared Code (NFS)

```bash
cd ~/virtualpytest/setup/proxmox/vm/shared
sudo bash mount_nfs_shared.sh
```

This mounts `/shared` from the Storage VM, giving access to the code repository.

### 5. Install Database Services

```bash
cd /shared/code/virtualpytest/setup/local/linux/database

# Install databases
sudo ./install_db.sh

# Test services
./test_db.sh
```

## Directory Structure

### After Infrastructure Setup
```
/data/
├── postgresql/   # Empty, ready for PostgreSQL data
├── influxdb/     # Empty, ready for InfluxDB data
└── docker/       # Empty, ready for Docker volumes
    └── volumes/

/shared/          # NFS mount from Storage VM
└── code/
    └── virtualpytest/  # Code repository
```

### After Database Installation
```
/data/
├── postgresql/
│   └── [PostgreSQL database files]
├── influxdb/
│   └── [InfluxDB data]
└── docker/
    └── volumes/
        └── [Supabase Docker volumes]
```

## Verification

### Check Infrastructure

```bash
# Disk mount
df -h | grep /data

# Database directories
ls -la /data/

# NFS shared code
df -h | grep /shared

# Test infrastructure
cd ~/virtualpytest/setup/proxmox/vm/database
./test_database.sh
```

### Check Database Services

```bash
# Docker containers (Supabase)
docker ps

# PostgreSQL connection
docker exec -it supabase-db psql -U postgres

# Test services
cd /shared/code/virtualpytest/setup/local/linux/database
./test_db.sh
```

## Standalone vs Proxmox

### Standalone Linux

```bash
# ONLY run local installer (no Proxmox scripts)
cd ~/virtualpytest/setup/local/linux/database
sudo ./install_db.sh
./test_db.sh
```

The installer creates `/data` as a directory on the system disk.

### Proxmox with Dedicated Disk

```bash
# First: Proxmox infrastructure script
cd ~/virtualpytest/setup/proxmox/vm/database
sudo bash create_disk_partition.sh
./test_database.sh

# Then: Mount shared code
cd ~/virtualpytest/setup/proxmox/vm/shared
sudo bash mount_nfs_shared.sh

# Finally: Same local installer as standalone
cd /shared/code/virtualpytest/setup/local/linux/database
sudo ./install_db.sh
./test_db.sh
```

The installer detects that `/data` is already mounted and uses it.

## Troubleshooting

### Disk Not Found

```bash
# List all disks
lsblk

# Check if attached in Proxmox
# Proxmox UI → VM → Hardware
```

### Mount Failed

```bash
# Check if already mounted
mount | grep sdb

# Check fstab
cat /etc/fstab | grep /data

# Reload systemd
sudo systemctl daemon-reload
```

### NFS Mount Failed

```bash
# Check network connectivity to Storage VM
ping 192.168.x.100

# Verify NFS exports on Storage VM
showmount -e 192.168.x.100

# Manual mount test
sudo mount -t nfs 192.168.x.100:/shared /shared
```

### Database Storage Issues

```bash
# Check disk space
df -h /data

# Check permissions
ls -la /data/

# Check Docker volumes
docker volume ls
docker volume inspect supabase_db
```

## Files in This Directory

- `create_disk_partition.sh` - Create and mount database disk
- `test_database.sh` - Test infrastructure
- `README.md` - This file

**Note**: For database service installation and testing, use `setup/local/linux/database/`

---

**Version**: 1.0 (Autonomous Infrastructure)  
**Last Updated**: January 2026
