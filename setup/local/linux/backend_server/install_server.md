# Backend Server Installation

## Overview
This script installs and configures the VirtualPyTest Backend Server, including dependencies, environment setup, and system services.

## Prerequisites
- Python 3.x
- sudo access for systemd service configuration
- Firewall configuration handled at Proxmox level

## Usage
```bash
./setup/local/install_server.sh
```

## What It Does
1. **Environment Setup**
   - Creates Python virtual environment in project root
   - Installs backend_server dependencies from `requirements.txt`

2. **Configuration**
   - Creates `.env` file from `.env.example` (if exists)
   - Configures backend server environment variables

3. **Services**
   - Installs Heatmap Processor systemd service
   - Installs Analyzer Discard Scripts + Incidents systemd services
   - Keeps discard services disabled by default
   - Services generate heatmaps and process AI discard queue

## Services Installed
- **Heatmap Processor Service** (`vpt-heatmap.service`)
  - Generates heatmap data every minute
  - Auto-starts on system boot
- **Analyzer Discard Scripts Worker** (`vpt-discard-scripts.service`)
  - Consumes `p2_scripts` Redis queue
  - Runs Sherlock false-positive/discard analysis
  - Disabled by default
- **Analyzer Discard Incidents Worker** (`vpt-discard-incidents.service`)
  - Consumes incident analysis queue
  - Runs Sherlock false-positive/discard analysis
  - Disabled by default

## Next Steps
1. Configure Supabase URI in `/opt/virtualpytest/.env` (project root)
2. Configure `OPENROUTER_API_KEY` in `/opt/virtualpytest/.env` for analyzer
2. Run `./setup/local/launch_server.sh` to start the server
3. Start services:
   - `sudo systemctl start vpt-heatmap`
   - `sudo systemctl start vpt-discard-scripts`
   - `sudo systemctl start vpt-discard-incidents`


## Service Management
```bash
# Start heatmap processor
sudo systemctl start vpt-heatmap
# Start analyzer discard workers
sudo systemctl start vpt-discard-scripts
sudo systemctl start vpt-discard-incidents

# Check status
sudo systemctl status vpt-heatmap
sudo systemctl status vpt-discard-scripts
sudo systemctl status vpt-discard-incidents

# View logs
sudo journalctl -u vpt-heatmap -f
sudo journalctl -u vpt-discard-scripts -f
sudo journalctl -u vpt-discard-incidents -f
```
