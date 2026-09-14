# Proxmox VM User & Service Configuration

> **Note**: For VM architecture overview and specifications, see:
> - [Main Architecture](../README.md) - VM specifications and network setup
> - [Software Requirements](../scripts/README.md) - Installation scripts and prerequisites

## Network Configuration (Static IPs)

### VM IP Assignments (192.168.x.0/24 subnet)
```
192.168.x.100   - Storage VM (NFS + MinIO S3 + Redis caching)
192.168.x.107   - Reverse Proxy VM (Nginx, SSL termination)
192.168.x.102   - Database VM (Supabase/PostgreSQL + Auth + API)
192.168.x.103   - Backend Server VM (Flask API)
192.168.x.140+ - Backend Host Server VM (Device control + desktop, incremental)
192.168.x.105   - Frontend VM (React web interface)
192.168.x.106   - Monitoring VM (Grafana + dashboards)
```

### Proxmox Network Setup
- **Subnet**: 192.168.x.0/24
- **Gateway**: 192.168.x.1 (Proxmox host)
- **DNS**: Configure each VM with static IPs above
- **Firewall**: Allow inter-VM communication on required ports

## VM Specifications

| VM | vCPU | RAM | Storage | Purpose |
|----|------|-----|---------|---------|
| Reverse Proxy | 1-2 | 2GB | 20GB SSD | Traffic routing |
| Database | 8 | 16GB | 200GB+ SSD | PostgreSQL + APIs |
| Backend Server | 2 | 4GB | 50GB SSD | Flask API |
| Host | 4 | 8GB | 100GB SSD | Test execution |
| Frontend | 2 | 4GB | 50GB SSD | React UI |
| Monitoring | 2 | 4GB | 100GB SSD | Grafana + metrics |
| Storage | 2 | 4GB | 2TB+ | NFS + MinIO + Redis |

## User Accounts to Create

### Human Users (Team Members)
- **Purpose**: SSH access for development, deployment, and administration
- **Accounts**: `member1`, `member2`, `member3` (one per team member)
- **Access**: SSH with sudo privileges for system management
- **Example**: `ssh member1@vpt-server` to deploy code

### Service Account (Application Owner)
- **Purpose**: Dedicated account for running VirtualPyTest services
- **Account**: `vpt_user` (single account across all VMs)
- **Access**: No SSH login, no password, used only by systemd services
- **Permissions**: Minimal privileges to run Flask/Gunicorn processes
- **Consistency**: All services configured to run as vpt_user, never as human users

## Service Running Configuration

### Services Running as vpt_user
The following VirtualPyTest application services run as the dedicated `vpt_user` account for security:

- **vpt-server** (Backend Server VM): Flask API service
- **vpt-host** (Host Server VM): Device control and automation service
- **vpt-frontend** (Frontend VM): React web interface service

Infrastructure services (database, monitoring, storage) run as their respective system/service accounts.

### VM Service Inventory

#### Backend Server VM Services (192.168.x.103)
- **vpt-server**: Main Flask API service
- **heatmap-processor**: Heatmap processing and analysis service

#### Backend Host Server VM Services (192.168.x.140+)
- **vpt-host**: Main VirtualPyTest host service (device control)
- **hot-cold-archiver**: RAM+SD storage management service
- **kpi-executor**: KPI measurement and analysis service
- **monitor**: Capture monitoring service
- **novnc**: Web-based VNC access service
- **stream**: FFmpeg capture and streaming service
- **subtitle-stream**: Subtitle transcription service
- **transcript-stream**: Audio detection and transcription service
- **vncserver**: TigerVNC server for display control

#### Frontend VM Services (192.168.x.105)
- **vpt-frontend**: React web interface service

#### Database VM Services (192.168.x.102)
- **supabase-postgres**: PostgreSQL database service
- **supabase-auth**: Authentication service
- **supabase-api**: REST API service
- **supabase-storage**: File storage service

#### Monitoring VM Services (192.168.x.106)
- **grafana**: Visualization dashboard service
- **influxdb**: Time-series database service
- **telegraf**: Metrics collection service

#### Storage VM Services (192.168.x.100)
- **nfs-server**: Network File System server
- **minio**: S3-compatible object storage
- **redis**: Caching and session storage service

### Systemd Services
```ini
[Service]
User=vpt_user
Group=vpt_user
ExecStart=/path/to/venv/bin/gunicorn --bind 0.0.0.0:5109 app:app
```

### Sudo Configuration for Human Users
```bash
# Allow service management without full sudo
member1 ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart vpt-server
member2 ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload vpt-server
```

## Shared Codebase Setup (NFS)

### Overview
Instead of cloning the repository on every VM, use NFS to share a single codebase from the Proxmox Host to all VMs. The NFS server runs on the Proxmox Host for better stability and performance.

### NFS Client Setup (VMs)
```bash
# On each VM - Mount shared VirtualPyTest codebase (NFS server pre-configured on Storage VM)
sudo ./setup/proxmox/vm/scripts/mount_nfs_shared.sh
```

### NFS Client Setup (VM Template)
```bash
# On VM Template (first VM) - Configure NFS mount BEFORE cloning
sudo ./setup/proxmox/vm/scripts/mount_nfs_shared.sh

# Convert to template - all clones inherit the NFS mount automatically
```

### Benefits
- **Single codebase**: No duplicate storage across VMs - files exist physically only once on Proxmox Host
- **Central updates**: Deploy once, available everywhere instantly via NFS mounts
- **Version consistency**: All VMs use identical code from shared `/mnt/virtualpytest/` mount
- **Reduced complexity**: No git operations needed on individual VMs

## Simple Communication Pairs

**Server talks to:**
- Database (5432 TCP - PostgreSQL)
- Redis (443 TCP - HTTPS REST API)
- Hosts (6109 TCP - HTTP)
- MinIO (9000 TCP - HTTP API)

**Hosts talk to:**
- Database (5432 TCP - PostgreSQL)
- Server (5109 TCP - HTTP callbacks)
- MinIO (9000 TCP - HTTP file uploads)

**Monitoring talks to:**
- Database (5432 TCP - PostgreSQL, 8086 TCP - InfluxDB)

**All VMs talk to:**
- Storage (2049 TCP/UDP - NFS, 111 TCP/UDP - Portmapper)

**Reverse Proxy talks to:**
- Server (5109 TCP - HTTP)
- Hosts (6109-6xxx TCP - HTTP, external ports)
- Frontend (3000 TCP - HTTP)
- Monitoring (3000 TCP - HTTP)
- MinIO (9001 TCP - HTTP console)




### Prerequisites
- **Storage VM IP**: Known and reachable by all VMs (e.g., 192.168.x.100)
- **Network**: All VMs on same subnet (192.168.x.0/24)
- **Firewall**: Configure above rules for secure communication
- **DNS/Internal Resolution**: VMs can resolve each other by IP or hostname

### Basic Firewall Setup

**For Reverse Proxy Configuration:**
- Allow external access to ports 80/443 on reverse proxy VM
- Internal VMs should only accept connections from reverse proxy (192.168.x.141)
- Database should only accept connections from server (192.168.x.103) and hosts (192.168.x.140+)
- Storage NFS should be accessible from all VMs in subnet

## Shared Codebase Solution

### Physical Location
**Files physically exist ONLY on Proxmox Host disk**

```
PHYSICAL STORAGE:
Proxmox Host Disk ───┐
                     ├── /srv/shared/virtualpytest/backend_server/
                     ├── /srv/shared/virtualpytest/frontend/
                     └── /srv/shared/virtualpytest/setup/

LOGICAL ACCESS:
Server VM    ──────┼──→ /mnt/virtualpytest/ (NFS mount)
Host VM      ──────┼──→ /mnt/virtualpytest/ (NFS mount)
Frontend VM  ──────┼──→ /mnt/virtualpytest/ (NFS mount)
Grafana VM   ──────┼──→ /mnt/virtualpytest/ (NFS mount)
```

**Same path, same files, but only one physical copy on Proxmox Host.**

## Complete Proxmox Setup Workflow (Empty System)

> **Note**: This detailed workflow focuses on user accounts, security configuration, and service setup. For basic VM provisioning and network setup, see [Main Architecture](../README.md#installation).

### Phase 1: Proxmox Host Setup
```bash
# On Proxmox Host (192.168.x.1) - BEFORE creating any VMs:
# Manual setup (basic system preparation):
apt update && apt upgrade -y
apt install -y curl wget git htop openssh-server
# Configure networking and NAT (see proxmox-setup-guide.md)
# Generate SSH key for VM access: ssh-keygen -t ed25519 -C "proxmox@virtualpytest"
```

### Phase 1.5: Storage VM NFS Setup
```bash
# On Storage VM (192.168.x.100) - BEFORE creating other VMs:
sudo ./setup/proxmox/vm/scripts/storage_create_disks_partitions.sh
sudo ./setup/proxmox/vm/scripts/storage_setup_nfs_server.sh
# (sets up NFS server for shared codebase)
```

### Phase 2: VM Provisioning & Template Setup
```bash
# Create template VM with Debian 13
# Configure network and install prerequisites
# Setup NFS mount to /mnt/virtualpytest from Proxmox host
# Convert to template
```

### Phase 3: Clone VMs with Specific Hardware
```bash
# Clone template for each service VM
# Specs per VM in main README.md
# Configure static IPs per network mapping above
# NFS mount inherited automatically from template
```

### Phase 4: Service Installation (Parallel)
```bash
# Storage VM (192.168.x.100) - MinIO + Redis only:
./setup/local/install_storage.sh

# All other VMs (NFS mount already configured):
./setup/local/install_db.sh          # Database VM: Supabase + PostgreSQL
./setup/local/install_server.sh     # Backend VM: Flask API
./setup/local/install_frontend.sh    # Frontend VM: React UI
./setup/local/install_grafana.sh     # Monitoring VM: Grafana + InfluxDB
./setup/local/install_host.sh        # Host VMs: device control
./setup/local/install_host_services.sh
./setup/local/install_reverse_proxy.sh  # Reverse Proxy VM: last
```

### Phase 5: Service Launch & Verification
```bash
# Configure .env files and service credentials
# Launch all services: ./setup/local/launch_all.sh
# Verify cluster health: check all VMs have running services
```
