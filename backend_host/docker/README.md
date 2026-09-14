# 🐳 backend_host Docker Setup

**Note:** This directory contains the core Docker files for the backend_host container. For complete cross-platform deployment with automatic device configuration, use the setup in `setup/` directory.

---

## 📋 Overview

The backend_host provides hardware control and device management services for VirtualPyTest.

### Core Files:
- **`Dockerfile`** - Container image definition
- **`supervisord.conf`** - Process manager configuration

### Cross-Platform Deployment:
For complete deployment with automatic device detection and RAM storage configuration, use:

```bash
cd setup/
./launch.sh    # Linux/macOS
.\launch.bat   # Windows
```

---

## 🗂️ Structure

```
backend_host/
└── docker/
    ├── Dockerfile              # Container image
    ├── supervisord.conf        # Process manager config
    ├── setup/                  # Cross-platform deployment
    │   ├── launch.sh          # Linux/macOS launcher
    │   ├── launch.bat         # Windows launcher
    │   ├── generate_tmpfs_config.sh
    │   └── README.md           # Deployment guide
    └── README.md               # This file
```

---

## 🚀 Deployment

For complete deployment instructions, see `setup/README.md`.

The core files in this directory are used by the deployment scripts in `setup/`.

---

## 📚 Related Documentation

- [Setup Guide](setup/README.md) - Complete deployment instructions
- [Project Root README](../../README.md)
- [Deployment Guide](../../docs/DEPLOYMENT_SYSTEM.md)

---

