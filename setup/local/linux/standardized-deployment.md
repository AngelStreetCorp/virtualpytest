# 🏗️ Standardized VirtualPyTest Deployment Architecture

## 🎯 Overview

VirtualPyTest uses a **simple, consistent deployment architecture** that ensures every VM follows the exact same pattern, whether you're deploying on a single development machine, multiple Proxmox VMs, or any other environment.

**Key Principle**:
> **Every VM gets the full project at `/opt/virtualpytest`**

This provides:
- ✅ **Simplicity** - One pattern, no exceptions
- ✅ **Consistency** - Same structure everywhere
- ✅ **Reliability** - No broken dependencies
- ✅ **Debuggability** - Source always available

## 📁 Standard Directory Structure

**Every VM has the exact same structure:**

```
/opt/virtualpytest/          # ← Standard installation directory
├── README.md               # Project documentation
├── .version                # Installation version tracking
├── shared/                 # Shared libraries and utilities
├── backend_server/        # Backend API server
├── backend_host/           # Hardware interface services
├── frontend/               # React web application
├── setup/                  # Installation scripts (always available!)
│   ├── local/
│   │   └── linux/
│   │       ├── shared/
│   │       │   └── bootstrap.sh  # Bootstrap functions
│   │       ├── storage/
│   │       ├── database/
│   │       └── ...
│   └── db/                 # Database migrations
├── infra/                  # Infrastructure services
│   ├── monitoring/grafana/  # Monitoring dashboards
│   ├── proxy/nginx/         # Nginx configs
│   ├── database/supabase/   # Supabase project files
│   └── storage/             # MinIO + Redis
├── venv/                   # Python virtual environment (if created)
├── config/                 # Configuration files (.env files)
└── scripts/                # Launch and utility scripts
```

**No exceptions. Every VM. Same structure.**

## 🔧 All Installers Use Same Pattern

VirtualPyTest installers all follow **one standard approach**:

### All Installers

| Installer | Command | What It Installs |
|-----------|---------|------------------|
| Core | `./setup/local/linux/install_core.sh` | Frontend + Backend Server + Backend Host |
| Frontend | `./setup/local/linux/frontend/install_frontend.sh` | React + Node.js + npm packages |
| Backend Server | `./setup/local/linux/backend_server/install_server.sh` | Python + Flask + API dependencies |
| Backend Host | `./setup/local/linux/backend_host/install_host.sh` | Appium + ADB + device controllers |
| Storage | `./setup/local/linux/storage/install_storage.sh` | MinIO + Redis |
| Database | `./setup/local/linux/database/install_db.sh` | Supabase + PostgreSQL |
| Nginx | `./setup/local/linux/reverse_proxy/install_nginx.sh` | Nginx reverse proxy |
| Grafana | `./setup/local/linux/monitoring/install_grafana.sh` | Grafana monitoring |
| Shared | `./setup/local/linux/shared/install_shared.sh` | Shared Python library |

**Every installer does the same setup:**
1. ✅ Creates `vpt_user` service account
2. ✅ Creates `/opt/virtualpytest` directory
3. ✅ Copies **entire project** to `/opt/virtualpytest`
4. ✅ Installs its specific components

**No special cases. Always consistent.**

## 👤 User Management

### Service Account
```bash
vpt_user (system account):
├── Home: /var/lib/vpt_user (standard system user home)
├── Shell: /bin/false (no login for security)
├── Owns: /opt/virtualpytest (if exists)
└── Services run as: vpt_user
```

### Automatic Creation
```bash
# You don't need to create the user manually!
# Every installer automatically creates vpt_user if needed

# Example: Storage installer
sudo ./setup/local/linux/storage/install_storage.sh
# ✅ Automatically creates vpt_user
# ✅ Installs MinIO + Redis
# ❌ Does NOT copy project code
```

## 🚀 Bootstrap Installation Process

### How Autonomous Installers Work

Each installer is **completely autonomous** and handles its own setup:

```bash
# 1. User clones repo anywhere
git clone <repo> ~/any/location/virtualpytest
cd ~/any/location/virtualpytest

# 2. User runs ANY installer directly
./setup/local/linux/storage/install_storage.sh

# 3. Installer automatically:
#    → Detects it's running from ~/any/location/virtualpytest
#    → Creates vpt_user (if needed)
#    → Creates /opt/virtualpytest (only if installer needs it)
#    → Copies project code (only if installer needs it)
#    → Installs its specific components

# Result: Perfect installation for that component!
```

### Standard Bootstrap Flow

**Every installer follows the same flow:**

```
User runs any installer
      ↓
Installer calls: setup_for_code_installer()
      ↓
  1. Create vpt_user
  2. Create /opt/virtualpytest
  3. Copy entire project
  4. Save version info
      ↓
cd /opt/virtualpytest
      ↓
Install component-specific services
```

**Simple. Consistent. Predictable.**

### For Updates/Re-runs:
```bash
# From any clone location, run install script again
cd ~/any/clone/location/virtualpytest
./setup/local/linux/install_core.sh

# Script automatically:
# - Detects existing /opt/virtualpytest installation
# - Compares versions (git commit)
# - If update needed: updates code
# - Saves new version information
# - Re-runs installation process
```

### Version Tracking:
```bash
# Version information saved in:
/opt/virtualpytest/.version    # For code-dependent installers

# Contains:
# - INSTALL_DATE: When installed/updated
# - GIT_COMMIT: Current git commit hash
# - GIT_BRANCH: Current git branch
# - GIT_REMOTE: Git remote URL
# - SOURCE_DIR: Where code was copied from
# - TARGET_DIR: Installation directory (/opt/virtualpytest)
```

## 🐧 Proxmox VM Deployment

### Perfect Architecture for Distributed VMs

**Key Insight**: Consistency > Micro-optimization

Every VM gets the full project. Why?

✅ **Simple** - One pattern, no exceptions  
✅ **Debuggable** - Source code always available  
✅ **Maintainable** - Can reference any script/doc  
✅ **Reliable** - No broken dependencies  
✅ **Cost** - ~500MB disk (negligible)

```
Proxmox Host
├── Core VM
│   ├── /opt/virtualpytest/     # ← Full project
│   ├── Frontend (React + Node)
│   ├── Backend Server (Python API)
│   └── Backend Host (Appium + ADB)
│
├── Storage VM
│   ├── /opt/virtualpytest/     # ← Full project (same!)
│   ├── MinIO (S3 storage)
│   └── Redis (caching)
│
├── Database VM
│   ├── /opt/virtualpytest/     # ← Full project (same!)
│   └── Supabase (PostgreSQL)
│
├── Nginx VM
│   ├── /opt/virtualpytest/     # ← Full project (same!)
│   └── Nginx (reverse proxy)
│
└── Monitoring VM
    ├── /opt/virtualpytest/     # ← Full project (same!)
    └── Grafana (monitoring)
```

**Every VM: Identical structure. No special cases.**

### Proxmox Deployment Steps

#### Option 1: Each VM Downloads Code Independently
```bash
# On each VM, clone and run appropriate installer
git clone <repo> ~/virtualpytest
cd ~/virtualpytest

# Core VM
sudo ./setup/local/linux/install_core.sh

# Storage VM
sudo ./setup/local/linux/storage/install_storage.sh

# Database VM
sudo ./setup/local/linux/database/install_db.sh

# Nginx VM
sudo ./setup/local/linux/reverse_proxy/install_nginx.sh

# Monitoring VM
sudo ./setup/local/linux/monitoring/install_grafana.sh
```

#### Option 2: Share Clone via NFS (Read-Only)
```bash
# 1. On Proxmox host, share code via NFS
mkdir -p /mnt/shared/virtualpytest
git clone <repo> /mnt/shared/virtualpytest

# 2. Mount on each VM (read-only)
sudo mount -t nfs proxmox-host:/mnt/shared/virtualpytest /mnt/source

# 3. On each VM, run installer from shared mount
cd /mnt/source
sudo ./setup/local/linux/<appropriate-installer>.sh

# Installer copies only what it needs to local disk!
```

## 🔧 Technical Implementation

### Modular Bootstrap Functions

All installers use shared bootstrap functions from `setup/local/linux/shared/bootstrap.sh`:

#### Level 1: User Management
```bash
ensure_vpt_user()
# Creates vpt_user service account only
```

#### Level 2: Directory Management
```bash
ensure_opt_directory()
# Creates /opt/virtualpytest directory (empty)
```

#### Level 3: Project Management
```bash
ensure_project_copied()
# Copies entire project to /opt/virtualpytest

copy_selective_files("path/to/files")
# Copies only specific files
```

#### Convenience Functions
```bash
setup_for_service_installer()
# Level 1 only: Creates user, no directory, no project

setup_for_code_installer()
# All levels: Creates user, directory, copies full project

setup_for_hybrid_installer("path")
# Levels 1-2 + selective copy: Creates user, directory, copies specific files
```

### Service Template Standards

**All service files use absolute paths:**
```bash
# Systemd service example
[Service]
User=vpt_user
Group=vpt_user
WorkingDirectory=/opt/virtualpytest/backend_server
ExecStart=/opt/virtualpytest/venv/bin/python app.py
```

**No dynamic path resolution** - everything is standardized.

## ✅ Benefits Achieved

### 1. **Autonomous Installations**
- Each installer runs independently
- No need to run core installer first
- Minimal dependencies between components

### 2. **Efficient Resource Usage**
- Storage VM: NO project code (saves disk space)
- Database VM: Only SQL files (minimal overhead)
- Core VM: Full project (only where needed)

### 3. **Proxmox Optimized**
- Each VM completely isolated
- No shared folder conflicts
- Independent virtual environments
- Separate configurations per VM

### 4. **Predictability**
- Known locations for components that need them
- Standardized service configurations
- Consistent upgrade procedures

### 5. **User Experience**
- Bootstrap handles complexity automatically
- Users don't need to understand the architecture
- Works from any clone location
- Clear error messages

## 🔄 Migration & Upgrades

### Idempotent Installation (Safe Re-runs)
All installation scripts are **idempotent** - they can be run multiple times safely:

- **User Check**: `vpt_user` creation skipped if exists
- **Directory Check**: `/opt/virtualpytest` creation skipped if exists
- **Version Check**: Updates only when source has changed
- **Service Safety**: Services stopped before updates, restarted after

### Updating an Existing Installation

```bash
# Same process for ALL VMs:

# 1. Pull latest code to any clone location
cd ~/virtualpytest
git pull

# 2. Re-run the installer
sudo ./setup/local/linux/<installer-name>.sh

# Installer will:
# - Detect existing /opt/virtualpytest
# - Compare versions (git commit)
# - Update if changed
# - Restart services

# Examples:
sudo ./setup/local/linux/install_core.sh
sudo ./setup/local/linux/storage/install_storage.sh
sudo ./setup/local/linux/database/install_db.sh
```

## 📋 Configuration Files

### Standard Configuration Locations

Every VM uses the same pattern:

#### Application Configs (in /opt/virtualpytest)
```
/opt/virtualpytest/
├── .env                      # Main configuration
├── .env                       # Backend server config (shared)
├── backend_host/.env        # Host config
├── frontend/.env            # Frontend config
└── infra/monitoring/grafana/config/          # Grafana dashboards
```

#### System Service Configs (system locations)
```
/etc/redis/redis.conf         # Redis configuration
/etc/nginx/nginx.conf         # Nginx configuration
/etc/default/minio            # MinIO configuration
/etc/grafana/grafana.ini      # Grafana system config
```

**Pattern**: Project configs in `/opt/virtualpytest`, system configs in `/etc`

## 🚀 Access Points

After installation, services are available at standard ports:

### Core VM
- **Frontend**: http://vm-ip:5073
- **Backend Server**: http://vm-ip:5109
- **Backend Host**: http://vm-ip:6109

### Storage VM
- **MinIO Console**: http://vm-ip:9001
- **MinIO API**: http://vm-ip:9000
- **Redis**: vm-ip:6379

### Database VM
- **Supabase Studio**: http://vm-ip:8000
- **PostgreSQL**: vm-ip:5432

### Nginx VM
- **HTTP**: http://vm-ip:80
- **HTTPS**: https://vm-ip:443

### Monitoring VM
- **Grafana**: http://vm-ip:3000

## 🛠️ Troubleshooting

### Verify Standard Installation

```bash
# Check project exists (should on ALL VMs)
ls -la /opt/virtualpytest

# Should show full project structure:
# - README.md
# - setup/
# - shared/
# - backend_server/
# - frontend/
# - etc.
```

### Check User Creation
```bash
# Verify vpt_user exists
id vpt_user

# Should show:
# uid=XXX(vpt_user) gid=XXX(vpt_user) groups=XXX(vpt_user)
```

### Verify Services
```bash
# Core VM
sudo systemctl status vpt-server vpt-frontend vpt-host

# Storage VM
sudo systemctl status minio redis-server

# Database VM
docker ps | grep supabase

# Nginx VM
sudo systemctl status nginx

# Monitoring VM
sudo systemctl status grafana-server
```

### Permission Issues
```bash
# Fix ownership (same on all VMs)
sudo chown -R vpt_user:vpt_user /opt/virtualpytest

# Restart services
sudo systemctl restart <service-name>
```

### Re-run Installer
```bash
# Safe to re-run any installer
cd ~/virtualpytest
sudo ./setup/local/linux/<installer-name>.sh

# The installer is idempotent and will:
# - Skip what's already done
# - Update what needs updating
# - Fix any issues automatically
```

## 📚 Additional Documentation

For detailed architecture information, see:
- **`/setup/local/linux/shared/bootstrap.sh`** - Bootstrap function documentation

---

## 🎯 Summary

The standardized architecture provides:

✅ **Simple** - One pattern, no exceptions  
✅ **Consistent** - Same structure on every VM  
✅ **Reliable** - No broken dependencies  
✅ **Debuggable** - Source always available  
✅ **Maintainable** - Easy to understand and support  
✅ **Autonomous** - Each installer runs independently  
✅ **Proxmox Ready** - Perfect for distributed deployments  

**The Rule:** Every VM gets full project at `/opt/virtualpytest`

**Why it works:** Simplicity and consistency beat micro-optimization.
