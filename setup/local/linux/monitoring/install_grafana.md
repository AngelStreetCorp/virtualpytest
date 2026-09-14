# Grafana Monitoring Installation

## Overview
This script installs and configures Grafana for VirtualPyTest local development with pre-configured dashboards and data sources. It works with any PostgreSQL database and includes comprehensive testing capabilities.

## Prerequisites
- Debian/Ubuntu (11+) or RHEL/CentOS/Fedora Linux
- sudo access for system service configuration
- PostgreSQL database (optional, for metrics storage)
- .env file with database credentials
- Modern GPG support (available in Debian 11+, Ubuntu 18.04+)

## Usage
```bash
# Install Grafana for local development
sudo bash ./setup/local/linux/monitoring/install_grafana.sh

# Start Grafana using the created launch script
./setup/local/linux/monitoring/launch_grafana.sh

# Test the installation
./setup/local/linux/monitoring/test_monitoring.sh
```

## What It Does
1. **Grafana Installation**
   - Installs Grafana server from official repositories
   - Installs PostgreSQL client for database connectivity testing
   - Uses modern GPG key management for repository setup
   - Configures admin user, password, and secret key from .env
   - Sets up local development security settings

2. **SQLite Database Setup**
   - Uses built-in SQLite for Grafana's internal storage
   - No external database required for local development
   - Fast, reliable, and self-contained

3. **Configuration & Dashboards**
   - Copies pre-configured grafana.ini
   - Imports Grafana database with all dashboards
   - Sets up data source provisioning

4. **Launch Script Creation**
   - Creates `setup/local/linux/monitoring/launch_grafana.sh` for easy startup
   - Includes proper configuration paths and options
   - Makes script executable for direct execution

5. **Database Connectivity Testing**
   - Tests connections to configured databases
   - Parses SUPABASE_DB_URI for connection details
   - Provides detailed error messages for troubleshooting

6. **Data Sources**
   - VirtualPyTest application database (when available)
   - Any external databases you configure
   - Connect via Grafana UI or provisioning

## Services Installed
- **Grafana Server** (`grafana-server.service`)
  - Web interface on port 3000
  - Pre-configured dashboards loaded
  - Auto-starts on boot

## Packages Installed
- **Grafana Server** - Visualization platform
- **PostgreSQL Client** (`psql`) - Database connectivity testing

## Access Points
- **Grafana Web UI**: http://localhost:3000
  - Admin user: `$GRAFANA_ADMIN_USER` (default: admin)
  - Admin password: `$GRAFANA_ADMIN_PASSWORD` (default: admin)

## Pre-configured Dashboards
- System Performance Dashboard
- Database Metrics Dashboard
- API Response Times Dashboard
- Device Capture Statistics
- Network Monitoring Dashboard
- Custom VirtualPyTest dashboards

## Required Ports
- **Grafana Web UI**: 3000 TCP

## Environment Configuration
Configure these variables in your `.env` file:
```bash
# Grafana Admin Credentials
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
GRAFANA_SECRET_KEY=your-secret-key-here

# Database Connections (optional)
VIRTUALPYTEST_DB_USER=virtualpytest_user
VIRTUALPYTEST_DB_PASSWORD=your-db-password
GRAFANA_DB_USER=grafana_user
GRAFANA_DB_PASSWORD=grafana-password
```

## Next Steps
1. Start Grafana: `./setup/local/linux/monitoring/launch_grafana.sh`
2. Access Grafana: http://localhost:3000
3. Login with configured admin credentials
4. Review pre-configured dashboards
5. Configure additional data sources as needed
5. Set up alerting rules if required

## Service Management
```bash
# Check Grafana service
sudo systemctl status grafana-server
sudo systemctl start grafana-server
sudo systemctl stop grafana-server
sudo systemctl restart grafana-server

# View logs
sudo journalctl -u grafana-server -f
sudo journalctl -u grafana-server -n 50

# Test installation
./setup/local/linux/monitoring/test_monitoring.sh
```

## Testing
Run the comprehensive test script to verify everything is working:
```bash
./setup/local/linux/monitoring/test_monitoring.sh
```

This will check:
- Grafana package installation
- PostgreSQL client availability
- Service status
- Web interface accessibility
- Database connectivity (using SUPABASE_DB_URI or VirtualPyTest DB)
- Configuration file integrity