# Launch Core - VirtualPyTest Core Services

## Overview

Unified launcher script that starts the three core VirtualPyTest services (frontend, backend_host, backend_server) with real-time unified logging.

**Note**: This does NOT launch supporting services like Grafana, storage (MinIO), or database. Those are managed separately.

## Services Launched

1. **backend_server** (port 5109) - Core API server
2. **backend_host** (port 6109) - Host management service  
3. **frontend** (port 5073) - Web UI

## Prerequisites

- Python virtual environment (`venv/`) installed
- Frontend dependencies (`frontend/node_modules/`) installed

Run installation if needed:
```bash
./setup/local/linux/install_all.sh
```

## Usage

```bash
cd /path/to/virtualpytest
./setup/local/linux/launch_core.sh
```

## Features

- **Unified logging**: All service logs appear in one terminal with colored prefixes
- **Auto port cleanup**: Kills any processes blocking required ports
- **Graceful shutdown**: Press `Ctrl+C` to stop all services
- **Real-time output**: Unbuffered logging for immediate visibility

## Log Prefixes

- `[SERVER]` - backend_server logs (blue)
- `[HOST]` - backend_host logs (green)
- `[FRONTEND]` - frontend logs (yellow)

## Access URLs

After successful launch:
- Frontend: http://localhost:5073
- backend_server: http://localhost:5109
- backend_host: http://localhost:6109

### Local Network Test Endpoints (Current Setup)

Use these when testing from another machine on the same LAN:

- Frontend UI: `http://<frontend-machine>:5073`
- backend_server API: `http://<server-machine>:5109`

Quick checks:

```bash
curl -I http://<frontend-machine>:5073
curl -I http://<server-machine>:5109/server/system/getAllHosts
```

Dashboard/API validation:

```bash
# Full host + system stats payload used by Dashboard
curl "http://<server-machine>:5109/server/system/getAllHosts?include_actions=false&include_system_stats=true"
```

## Troubleshooting

### Missing Dependencies
Script will check and report missing components with fix commands.

### Port Conflicts
Script automatically clears ports 5109, 6109, and 5073 before launch.

### Process Management
All PIDs tracked and cleaned up on exit. PID files removed from `/tmp/`.
