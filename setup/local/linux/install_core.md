# Core Installation Script

## Overview
This script performs a **core installation** of VirtualPyTest, installing only the essential components needed to run the basic system: frontend, backend_server, and backend_host.

**Use Case**: When you want to install just the core VirtualPyTest components without database, monitoring, or storage services.

## Prerequisites
- Debian/Ubuntu Linux
- sudo access for system configuration
- At least 10GB free disk space
- Internet connection for package downloads

## Usage
```bash
# Install only core components
./setup/local/linux/install_core.sh
```

## What It Does

### System Setup
1. **System Requirements**
   - Installs system packages and dependencies
   - Sets up required libraries and tools

2. **Permissions Setup**
   - Configures www-data user permissions
   - Sets up directory ownership and access rights
   - Requires sudo access

3. **Environment Configuration**
   - Creates `.env` files from templates
   - Sets up backend_host, frontend, and main configuration

### Core Components Installation
1. **Shared Library** (`shared/`)
   - Installs common Python packages and utilities
   - Smart update mode (preserves existing installations)

2. **Backend Server** (`backend_server/`)
   - Installs Python dependencies
   - Configures server environment
   - Smart update mode

3. **Backend Host** (`backend_host/`)
   - Installs hardware control services
   - Sets up VNC, ADB, and device management
   - Fresh installation mode (cleans existing services)

4. **Frontend** (`frontend/`)
   - Installs Node.js dependencies
   - Builds React application
   - Smart update mode

## Components Installed
- ✅ **Frontend** - Web interface (React)
- ✅ **Backend Server** - API and business logic (Python)
- ✅ **Backend Host** - Hardware control and services (Python)
- ❌ **Database** - Not included (use install_all.sh for full setup)
- ❌ **Grafana** - Not included (use install_all.sh for monitoring)
- ❌ **Storage** - Not included (use install_all.sh for file storage)

## Configuration Files Created
- `.env` - Main application configuration
- `backend_host/src/.env` - Hardware/device settings
- `frontend/.env` - Web interface settings

## Next Steps
1. **Edit Configuration**
   ```bash
   # Configure main settings
   nano .env

   # Configure hardware settings
   nano backend_host/src/.env

   # Configure web interface
   nano frontend/.env
   ```

2. **Launch System**
   ```bash
   # Start all core services
   ./scripts/launch_virtualpytest.sh
   ```

3. **Individual Service Control**
   ```bash
   # Start backend server only
   ./setup/local/launch_server.sh

   # Start backend host only
   ./setup/local/launch_host.sh

   # Start frontend only
   ./setup/local/launch_frontend.sh
   ```

## When to Use
- **Development**: Quick setup for development/testing
- **Minimal Installation**: When you don't need database/monitoring
- **CI/CD**: Faster builds without full infrastructure
- **Resource Limited**: Systems with limited storage/network

## Differences from Full Installation
| Component | install_core.sh | install_all.sh |
|-----------|----------------|----------------|
| Database | ❌ | ✅ Supabase + PostgreSQL |
| Grafana | ❌ | ✅ Monitoring |
| Storage | ❌ | ✅ MinIO S3 |
| Shared Lib | ✅ | ✅ |
| Backend Server | ✅ | ✅ |
| Backend Host | ✅ | ✅ |
| Frontend | ✅ | ✅ |

## Troubleshooting
- **Permission Issues**: Run with sudo or ensure user has proper permissions
- **Missing Dependencies**: Check that `shared/install_requirements.sh` exists
- **Environment Files**: Ensure `.env.example` templates are present

## Related Scripts
- `install_all.sh` - Full system installation with all components
- `launch_core.sh` - Launch script for core components only