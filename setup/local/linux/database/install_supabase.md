# Supabase Installation

## Overview
Installs Supabase (PostgreSQL + Auth + Storage + API) in Docker containers with VirtualPyTest schema.

**Architecture**: All services run in Docker, managed by Supabase CLI. Includes automatic schema setup and credential extraction.

## Prerequisites
- Linux (Debian/Ubuntu)
- sudo access
- 10GB+ disk space
- Internet connection

## Quick Installation
```bash
# Install Supabase with VirtualPyTest schema
./setup/local/linux/database/install_supabase.sh [DATA_DIR]

# DATA_DIR defaults to /data/supabase
```

**Result**: Complete Supabase instance with database schema, API keys extracted, and systemd service configured.

## What It Does

1. **Environment Setup**
   - Installs Docker + Docker Compose
   - Installs Supabase CLI
   - Creates Supabase project structure

2. **Database Schema**
   - Combines VirtualPyTest migrations into `seed.sql`
   - Supabase handles schema creation automatically

3. **Service Startup**
   - Starts all Supabase services in Docker
   - Waits for database readiness
   - Extracts API keys and credentials

4. **Configuration**
   - Updates `.env` files with real values
   - Installs systemd service for auto-startup
   - Provides access URLs and credentials

## Services Running

| Service | Port | Access |
|---------|------|--------|
| Supabase API | 54321 | `http://localhost:54321` |
| Supabase Studio | 54323 | `http://localhost:54323` |
| PostgreSQL | 54322 | Internal Docker only |

## Docker network interfaces summary (Supabase VM)

This VM runs **12 Supabase containers**. Docker automatically creates virtual networking to isolate services and allow internal communication.

| Interface Type         | Example                                       | Purpose                                                                            |
| ---------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------- |
| Physical NIC           | `ens18`, `ens19`, `ens20`                     | Real VM network interfaces connected to the infrastructure network                 |
| Docker default bridge  | `docker0`                                     | Default Docker network (not used by Supabase here)                                 |
| Docker custom bridge   | `br-8dbc84d3eea8`                             | Private virtual switch used by all Supabase containers                             |
| Virtual ethernet pairs | `veth69e935f`, `veth9a580f0`, etc. (12 total) | One per container — connects each container's internal `eth0` to the Docker bridge |

**In short:**
Each Supabase container gets its own virtual network interface (`veth`) connected to a private Docker bridge. This provides isolation, security, and controlled service-to-service communication. This setup is normal and expected for container platforms.

## Auto-Configured Environment Variables

After installation, these are set in `/opt/virtualpytest/.env`:

```bash
SUPABASE_URL=http://localhost:54321
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
SUPABASE_JWT_SECRET=your-secure-jwt-secret
SUPABASE_DB_URI=postgresql://postgres:postgres@127.0.0.1:54322/postgres
```

## Access URLs

- **Supabase Studio**: `http://localhost:54323` (web interface)
- **Supabase API**: `http://localhost:54321` (REST/GraphQL)
- **Database**: Internal Docker access only (port 54322)

## Service Management

```bash
# Check status
sudo systemctl status supabase

# View logs
sudo journalctl -u supabase -f

# Restart
sudo systemctl restart supabase

# Stop
sudo systemctl stop supabase
```

## Manual Commands

```bash
# Go to Supabase directory
cd /data/supabase

# Check Supabase status
supabase status

# View logs
supabase logs
```

## Files Created

- `/opt/virtualpytest/.env` - Environment variables (auto-updated)
- `/data/supabase/config.toml` - Supabase configuration
- `/data/supabase/seed.sql` - Combined database schema

## Summary

✅ **Supabase installed in Docker** with VirtualPyTest schema  
✅ **API keys auto-extracted** and configured  
✅ **Systemd service** for auto-startup  
✅ **Ready for development** - access Studio at `http://localhost:54323`