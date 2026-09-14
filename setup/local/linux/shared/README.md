# VirtualPyTest Installation Directory Structure

## Overview

All VirtualPyTest installation scripts now follow a consistent directory structure that keeps installation artifacts separate from the project source code. This ensures that:

- Setup scripts never write to the project directory
- Installation artifacts are properly organized by type
- Multiple installations can coexist without conflicts
- User permissions are respected (no sudo required for user directories)

## Directory Structure

### Standardized Installation (All VMs)

All VirtualPyTest installations use the **exact same directory structure** for consistency and predictability:

```bash
/opt/virtualpytest/          # ← Standard installation directory
├── README.md               # Project documentation
├── shared/                 # Shared libraries and utilities
├── backend_server/        # Backend API server
├── backend_host/          # Hardware interface services
├── frontend/              # React web application
├── venv/                  # Python virtual environment
├── config/                # Configuration files (.env files)
├── scripts/               # Launch and utility scripts
├── setup/                 # Installation scripts
└── infra/                 # Infrastructure services
    ├── monitoring/grafana/ # Monitoring dashboards
    ├── proxy/nginx/        # Reverse proxy configs
    ├── database/supabase/  # Supabase project files
    └── storage/            # MinIO + Redis
```

### User and Permissions

```bash
vpt_user (system account):
├── Home: /var/lib/vpt_user (standard system user home)
├── Shell: /bin/false (no login for security)
├── Owns: /opt/virtualpytest (full ownership)
└── Services run as: vpt_user
```

## Installation Scripts

All installation scripts use the **standardized `/opt/virtualpytest` location**:

- `install_core.sh` - Complete VirtualPyTest installation
- `install_db.sh` - Database/Supabase installation
- `install_server.sh` - Backend server installation
- `install_frontend.sh` - Frontend installation

## Key Features

### Standardized Architecture
- **Fixed Location**: Every installation uses `/opt/virtualpytest`
- **Same Structure**: Identical directory layout on every VM
- **User Isolation**: Each VM has complete, independent copy
- **Predictable Paths**: Support and documentation are consistent

### Bootstrap Installation
- **Smart Detection**: Scripts detect if running from standard location
- **Automatic Setup**: Creates user and directory if needed
- **Copy & Continue**: Copies code to standard location automatically
- **User-Friendly**: Users don't need to know the convention

## Installation Process

### For New Users:
```bash
# 1. Clone repository (anywhere)
git clone <repo> ~/virtualpytest

# 2. Run installation script
cd ~/virtualpytest
./setup/local/linux/install_core.sh

# Script automatically:
# - Creates vpt_user and /opt/virtualpytest
# - Copies code to /opt/virtualpytest
# - Installs all components
# - Configures services
```

### For Existing VMs:
```bash
# If /opt/virtualpytest doesn't exist:
sudo ./setup/local/linux/shared/linux/create_vpt_user.sh
sudo cp -r /path/to/cloned/repo /opt/virtualpytest
sudo chown -R vpt_user:vpt_user /opt/virtualpytest

# Then run installation from standard location:
cd /opt/virtualpytest
./setup/local/linux/install_core.sh
```

## Benefits

- **Consistent Architecture**: Every VirtualPyTest installation is identical
- **Proxmox Safe**: No shared folder conflicts (each VM has its own copy)
- **Predictable Support**: Know exactly where everything is located
- **Clean Isolation**: Each VM's venv, config, and logs are separate
- **Simple Maintenance**: Clear upgrade and backup procedures
