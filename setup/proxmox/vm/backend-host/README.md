# Proxmox Backend Host VM - Infrastructure Setup

## Autonomous Architecture

This directory handles **ONLY infrastructure** (disk mount for host data storage).
Service installation (device control, automation) uses the standard local installer.

```
Proxmox Level (Infrastructure):
└── create_disk_partition.sh  → Creates/mounts disk for /data

Local Level (Services):
├── install_host.sh           → Installs backend host services
└── test_host.sh              → Tests services only
```

## Quick Start (Autonomous)

### On Proxmox Backend Host VM

```bash
# Step 1: Setup infrastructure (Proxmox-specific)
cd ~/virtualpytest/setup/proxmox/vm/backend-host
sudo bash create_disk_partition.sh
./test_host.sh

# Step 2: Install services (same as standalone)
cd ~/virtualpytest/setup/local/linux/host
sudo ./install_host.sh [DATA_DIR]
./test_host.sh
```

**DATA_DIR**: Optional path for host data (default: `/var/www/html/stream`)
- Use `/data/stream` to store data on the dedicated disk partition

**Examples:**
```bash
sudo ./install_host.sh              # Default: /var/www/html/stream
sudo ./install_host.sh /data/stream # Custom: /data/stream (with symlink)
```

That's it! The infrastructure script handles Proxmox-specific setup, then the local installer works exactly like on standalone systems.

## What Each Script Does

### 1. `create_disk_partition.sh` (Proxmox Only)

**Purpose**: Prepare dedicated disk for host data storage

**What it does:**
- Checks for `/dev/sdb`
- Creates partition (if not exist)
- Formats as ext4
- Mounts to `/data`
- Adds to `/etc/fstab` for persistence
- Creates subdirectories for host data

**Disk configuration:**
```
/dev/sdb → /data    (100GB+ recommended)
           ├── recordings/     (video captures)
           ├── screenshots/    (test screenshots)
           ├── logs/          (host service logs)
           ├── temp/          (temporary files)
           └── artifacts/     (test artifacts)
```

**Run:**
```bash
sudo bash create_disk_partition.sh
```

### 2. Test Script (Infrastructure Only)

**Purpose**: Test infrastructure setup

**Tests:**
- ✅ Disk mount (`/data`)
- ✅ `/etc/fstab` entry
- ✅ Host data directories
- ✅ Disk space

**Run:**
```bash
./test_host.sh
```

### 3. Install Host Services (Uses Local Installer)

After infrastructure is ready, install services using the **standard local installer**:

```bash
cd ~/virtualpytest/setup/local/linux/host
sudo ./install_host.sh
```

This installs:
- Backend host services (device control, automation)
- VNC server for remote access
- FFmpeg for video processing
- Test execution environment

The installer automatically detects that `/data` is mounted and configures services to use it.

## Proxmox VM Setup

### 1. Create VM in Proxmox

**Recommended specs:**
- OS: Debian 12
- RAM: 8GB
- CPU: 4 cores
- Disks:
  - System: 50GB (sda)
  - Data: 100GB+ (sdb)

### 2. Attach Data Disk

In Proxmox UI:
1. Select VM → **Hardware**
2. Click **Add → Hard Disk**
   - Size: 100GB+ → becomes `/dev/sdb`

### 3. Run Infrastructure Setup

```bash
cd ~/virtualpytest/setup/proxmox/vm/backend-host

# Setup disk
sudo bash create_disk_partition.sh

# Test infrastructure
./test_host.sh
```

### 4. Install Host Services

```bash
cd ~/virtualpytest/setup/local/linux/host

# Install host services
sudo ./install_host.sh

# Test services
./test_host.sh
```

## Directory Structure

### After Infrastructure Setup
```
/data/
├── recordings/     # Empty, ready for video captures
├── screenshots/    # Empty, ready for test screenshots
├── logs/          # Empty, ready for service logs
├── temp/          # Empty, ready for temporary files
└── artifacts/     # Empty, ready for test artifacts
```

### After Host Installation
```
/data/
├── recordings/
│   └── [video files from tests]
├── screenshots/
│   └── [screenshot files from tests]
├── logs/
│   └── [backend-host service logs]
├── temp/
│   └── [temporary processing files]
└── artifacts/
    └── [test result files]
```

## Verification

### Check Infrastructure

```bash
# Disk mount
df -h | grep /data

# Host data directories
ls -la /data/

# Test infrastructure
cd ~/virtualpytest/setup/proxmox/vm/backend-host
./test_host.sh
```

### Check Host Services

```bash
# Service status
sudo systemctl status backend-host

# Test services
cd ~/virtualpytest/setup/local/linux/host
./test_host.sh
```

## Standalone vs Proxmox

### Standalone Linux

```bash
# ONLY run local installer (no Proxmox scripts)
cd ~/virtualpytest/setup/local/linux/host
sudo ./install_host.sh
./test_host.sh
```

The installer creates `/data` as a directory on the system disk.

### Proxmox with Dedicated Disk

```bash
# First: Proxmox infrastructure script
cd ~/virtualpytest/setup/proxmox/vm/backend-host
sudo bash create_disk_partition.sh
./test_host.sh

# Then: Same local installer as standalone
cd ~/virtualpytest/setup/local/linux/host
sudo ./install_host.sh
./test_host.sh
```

The installer detects that `/data` is already mounted and uses it.

## Architecture Comparison

### Standalone
```
/data/              # Directory on system disk
  ├── recordings/
  ├── screenshots/
  └── logs/
```

### Proxmox
```
/dev/sdb1 → /data/  # Dedicated disk for host data
  ├── recordings/
  ├── screenshots/
  └── logs/
```

**Key Point**: The local installer (`install_host.sh`) works the same in both cases!

## Data Directory Configuration

### Symlink Mechanism
When you specify a custom `DATA_DIR` during installation:

1. **Data is stored** in your custom location (e.g., `/data/stream`)
2. **Symlink is created**: `/var/www/html/stream → /data/stream`
3. **All scripts work unchanged** - they still reference `/var/www/html/stream`
4. **Environment variable set**: `VIRTUALPYTEST_INSTALL_PATH=/data/stream`

### Benefits
- ✅ **Zero script modifications** required
- ✅ **Transparent operation** - existing scripts work unchanged
- ✅ **Flexible storage** - data can be on any disk/mount point
- ✅ **Easy migration** - change location without touching code

### Example with Dedicated Disk
```bash
# Infrastructure creates /data partition on sdb1
sudo bash create_disk_partition.sh

# Installation uses /data/stream with symlink
sudo ./install_host.sh /data/stream

# Result: /var/www/html/stream → /data/stream
# All scripts work normally, data stored on dedicated disk
```

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

## Next Steps

After successful setup:

1. **Configure VNC access** for remote device control
2. **Setup device connections** (USB, HDMI, IR)
3. **Configure test campaigns** and automation scripts
4. **Setup monitoring** and log aggregation

## Files in This Directory

- `create_disk_partition.sh` - Create and mount data disk
- `test_host.sh` - Test infrastructure
- `README.md` - This file

**Note**: For service installation and testing, use `setup/local/linux/host/`

---

**Version**: 1.0 (Autonomous Infrastructure)
**Last Updated**: January 2026