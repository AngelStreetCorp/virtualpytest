# Database Installation - Supabase (Docker)

## Overview
Installs **Supabase with PostgreSQL in Docker** as a complete database solution.

**Architecture**: Supabase manages PostgreSQL + Auth + Storage + API services in Docker containers.

**What gets installed**:
- Docker (auto-installed if missing)
- Supabase CLI
- Supabase services in Docker (PostgreSQL + Auth + Storage + API)
- VirtualPyTest database schema
- Library visibility schema for hiding scripts, test cases, and campaigns per team
- Systemd service for auto-startup

## Prerequisites
- Debian/Ubuntu Linux
- sudo access
- **Recommended: 16GB+ RAM** for the full Supabase stack
- 10GB+ disk space for Docker images
- Internet connection

**RAM Requirements**:
- Full Supabase stack can use **multiple GB** (often ~4–10GB depending on services and workload).
- VirtualPyTest runs Supabase in **minimal mode by default** to reduce RAM usage by disabling services that commonly spawn large `beam.smp` processes (Erlang/Elixir), such as **Realtime** and **Analytics/Logflare**.

Minimal mode is applied during install and on each `supabase.service` start via `ExecStartPre`.

**Why Supabase uses 8GB RAM:**
- PostgreSQL (main consumer — shared buffers, caches)
- Realtime, PostgREST, Auth, Storage, Analytics, Kong, Studio, Edge Runtime
- Each service runs in its own container, so memory adds up
- Docker also uses memory for networking and filesystem caching

**Typical ranges:**
- Idle Supabase stack: ~4–6 GB
- Active workload / analytics enabled: ~6–10 GB+

## Quick Start
```bash
# Install complete database stack
./setup/local/linux/database/install_db.sh
```

**Result**: Fully configured Supabase instance with VirtualPyTest schema ready.

## What It Does

1. **Environment Setup**
   - Creates `vpt_user` with Docker access
   - Copies project to `/opt/virtualpytest`

2. **Supabase Installation**
   - Installs Docker + Docker Compose
   - Downloads Supabase CLI
   - Initializes Supabase project in `/data/supabase`

3. **Services Startup**
   - Starts Supabase services in Docker
   - Auto-generates database schema from migrations
   - Includes `library_visibility` for team-scoped hide/show controls
   - Extracts API keys and credentials

4. **Configuration**
   - Updates `/opt/virtualpytest/.env` with real values
   - Installs systemd service for auto-startup
   - Provides connection details

## Services Running (All in Docker)

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 54322 | Database (internal) |
| Supabase API | 54321 | REST/GraphQL API |
| Supabase Studio | 54323 | Web interface |
| Auth | Internal | Authentication |
| Storage | Internal | File storage |
| Realtime | Internal | Real-time subscriptions |

## Connection Details

**Database (internal access):**
- Host: `127.0.0.1`
- Port: `54322`
- Database: `postgres`
- User: `postgres`
- Password: `postgres`
- URI: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`

**External API access:**
- API URL: `http://localhost:54321`
- Studio URL: `http://localhost:54323`

## Configuration Files
- **Main config**: `/opt/virtualpytest/.env` (auto-updated)
- **Database config**: `/opt/virtualpytest/config/database/local.env`
- **Supabase project**: `/data/supabase/` (managed by Supabase CLI)

## Required Ports
- **54321**: Supabase API (REST/GraphQL)
- **54323**: Supabase Studio (web interface)
- **54322**: PostgreSQL (internal Docker access only)

## Management Commands
```bash
# Check status
sudo systemctl status supabase

# View logs
sudo journalctl -u supabase -f

# Restart service
sudo systemctl restart supabase

# Connect to database (from database VM only)
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres

# Stop service
sudo systemctl stop supabase
```

## Minimal Mode Toggle

To keep the full Supabase stack (including Realtime/Analytics), edit the systemd unit and set:

```bash
sudo systemctl edit supabase
```

Add:
```ini
[Service]
Environment=VPT_SUPABASE_MINIMAL=0
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart supabase
```

## Next Steps
1. **Access Supabase Studio**: `http://database-vm:54323`
2. **Use API**: `http://database-vm:54321`
3. **Configure other VMs**: Update their `.env` files with Supabase URLs/keys
4. **Test connections**: Verify API connectivity from other VMs
