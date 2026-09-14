# VirtualPyTest VM Software Overview

## VM Architecture Summary
7 dedicated Debian 13 VMs, each with specific role. All VMs share code via NFS from Storage VM.

## VM Software Requirements & Users

### 0. Proxmox Host (192.168.x.1)
**Role**: Physical host providing network infrastructure and gateway
**Software**: Proxmox VE with NAT, DNS forwarding, and network routing
**Network**: Gateway at 192.168.x.1, provides internet access to all VMs

---

### 1. Storage VM (192.168.x.100)
**Role**: Complete storage solution and NFS server for all VMs
**Software Installed**:
- NFS Server (multi-tier access control: rw/ro permissions)
- MinIO (S3-compatible storage)
- Redis (caching)
- Backup tools (rsync, borgbackup)

**Storage Setup**: Two-phase process - see [`vm-storage-overview.md`](vm-storage-overview.md) for complete storage architecture, drive configuration, and setup workflow.

**Users**:
- `vpt_user`: Runs storage services
- Team users: SSH access for management

**Network**: Internal access only (192.168.x.0/24)

---

### 2. Reverse Proxy VM (192.168.x.107)
**Role**: Traffic router and SSL termination
**Software Installed**:
- Nginx (web server + load balancer)
- Certbot (SSL certificates)
- HAProxy (advanced routing)

**Users**:
- `vpt_user`: Runs proxy services
- Team users: SSH access for config

**Network**:
- External: Ports 80/443 (public access)
- Internal: Routes to other VMs

---

### 3. Database VM (192.168.x.102)
**Role**: Data storage and authentication
**Software Installed**:
- **Docker (auto-installed)** - Required for Supabase
- **PostgreSQL client (auto-installed)** - psql for running migrations
- **Supabase** - PostgreSQL + Auth + Storage + API in Docker

> ⚠️ **Docker Required**: Supabase runs all services in Docker containers (PostgreSQL, Auth, Storage, Studio). No separate PostgreSQL installation.

**Architecture Note**: Supabase manages PostgreSQL in Docker. All database services are containerized and managed by Supabase CLI.

**Services Exposed**:
- PostgreSQL: Port 5432 (internal only)
- Supabase API: Port 54321 (internal only)
- Supabase Studio: Port 54323 (accessible via reverse proxy at /supabase/)

**RAM Requirements**: 16GB total VM RAM required since Supabase uses ~8GB RAM. This is normal for a full local/self-hosted stack.

**Why Supabase uses 8GB RAM:**
- PostgreSQL (main consumer — shared buffers, caches)
- Realtime, PostgREST, Auth, Storage, Analytics, Kong, Studio, Edge Runtime
- Each service runs in its own container, so memory adds up
- Docker also uses memory for networking and filesystem caching

**Typical ranges:**
- Idle Supabase stack: ~4–6 GB
- Active workload / analytics enabled: ~6–10 GB+

**Users**:
- `vpt_user`: Runs database services
- postgres: Database system user
- Team users: SSH access for management

**Network**: Internal access only (192.168.x.0/24)

---

### 4. Backend Server VM (192.168.x.103)
**Role**: Main application API
**Software Installed**:
- Python 3.9+ (Flask API)
- Gunicorn (application server)
- PostgreSQL client libraries

**Users**:
- `vpt_user`: Runs Flask API service
- Team users: SSH access for deployment

**Network**: Internal access only (192.168.x.0/24)

---

### 5. Backend Host VMs (192.168.x.140+)
**Role**: Device control and test execution
**Software Installed**:
- Python 3.9+ (automation)
- XFCE4 desktop environment
- VNC/noVNC (remote access)
- Firefox/Chromium browsers
- FFmpeg (video processing)

**Users**:
- `vpt_user`: Runs test services
- Team users: SSH access for management

**Network**:
- Internal: API access (192.168.x.0/24)
- External: VNC access (5901, 6080)

---

### 6. Frontend VM (192.168.x.105)
**Role**: Web interface
**Software Installed**:
- Node.js 20+ (React app)
- Build tools (Vite, etc.)
- Production: Serves built static files (no nginx needed)

**Users**:
- `vpt_user`: Runs web server
- Team users: SSH access for deployment

**Network**: Internal access only (192.168.x.0/24)
**Note**: Reverse proxy VM handles SSL and routing - frontend serves static files directly

---

### 7. Monitoring VM (192.168.x.106)
**Role**: Dashboards and metrics
**Software Installed**:
- Grafana (visualization)
- Docker (required for image renderer)
- Grafana Image Renderer (Docker container on port 8081 — renders dashboards as PNG for alerts/reports)
- InfluxDB (time-series data)
- Telegraf (metrics collection)

**Users**:
- `vpt_user`: Runs monitoring services
- Team users: SSH access for management

**Network**: Internal access only (192.168.x.0/24)

## User Security Model

### vpt_user (Service Account)
- **Purpose**: Runs application services with minimal privileges
- **Access**: No SSH login, no password, systemd-only
- **Security**: If compromised, limited damage scope
- **Consistency**: Same user across all VMs for services

### Team Users (Human Access)
- **Purpose**: SSH access for development and management
- **Access**: Full SSH + sudo for system operations
- **Examples**: member1, member2, member3
- **Security**: Can restart services but not run as root

## Network Security Model

### Internal Network (192.168.x.0/24)
- **Trust Level**: High (VM-to-VM communication)
- **Access**: All VMs can talk to each other
- **Firewall**: Open required ports between VMs
- **Example**: Database VM serves Backend Server VM

### External Access (via Reverse Proxy)
- **Trust Level**: Low (internet-facing)
- **Access**: Only through Reverse Proxy VM (192.168.x.107)
- **Firewall**: Strict rules, only ports 80/443 open
- **Example**: Users access https://your-domain.com → routed internally

### Key Network Flows
```
Internet → Reverse Proxy (80/443) → Internal VMs
                                       ↓
Internal VMs ←→ Database, Storage, Monitoring
```

## Installation Order
1. **Proxmox Host first** (network infrastructure and NAT setup)
2. **Storage VM** (NFS server, MinIO, Redis)
3. **All other VMs parallel** (inherit NFS mount from template, install services)
4. **Configure networking** (internal communication)
5. **Test access** (verify all services running)

## Hardware Requirements Summary
| VM | CPU | RAM | Storage | Purpose |
|----|-----|-----|---------|---------|
| Reverse Proxy | 1-2 | 2GB | 20GB | Traffic routing |
| Database | 8 | 16GB | 200GB+ | Data storage |
| Backend Server | 2 | 4GB | 50GB | API services |
| Host VMs | 4 | 8GB | 100GB | Test execution |
| Frontend | 2 | 4GB | 50GB | Web interface |
| Monitoring | 4 | 16GB | 50GB | Dashboards + Image Renderer |
| Storage | 2 | 4GB | 3 drives: 100GB SSD + 2TB+ HDD + 200GB SSD | Multi-tier storage & NFS |

---
**Total**: 1 Proxmox Host + 7 VMs | **Shared Codebase**: Yes (NFS) | **Security**: Defense-in-depth