# Frontend VM Installation

## Overview
This script installs and configures the VirtualPyTest Frontend VM with React web application, Node.js environment, and Nginx web server.

## Prerequisites
- Debian/Ubuntu Linux
- sudo access for system service configuration
- At least 50GB storage space available
- Firewall configuration handled at Proxmox level

## Usage
```bash
# Install frontend
./setup/local/install_frontend.sh
```

## What It Does
1. **Node.js Environment Setup**
   - Installs Node.js 18.x LTS and npm
   - Configures npm registry and global packages
   - Sets up Node.js environment variables

2. **React Application Installation**
   - Installs frontend dependencies from `package.json`
   - Builds production React application
   - Configures build optimization

3. **Nginx Web Server**
   - Installs and configures Nginx
   - Sets up virtual host for frontend
   - Configures SSL/TLS (if certificates available)
   - Sets up static file serving

4. **Environment Configuration**
   - Creates `.env` file from template
   - Configures API endpoints and backend URLs
   - Sets up frontend-specific settings

5. **Static Asset Optimization**
   - Configures gzip compression
   - Sets up browser caching headers
   - Optimizes static file serving

## Services Installed
- **Nginx Web Server** (`nginx.service`)
  - Serves React application on ports 80/443
  - Auto-starts on boot
  - Handles static asset serving

## Access Points
- **Frontend Web App**: http://192.168.x.105/
- **HTTPS** (if configured): https://192.168.x.105/
- **Admin Interface**: Available through web UI
- **API Proxy**: Routes to backend server

## Configuration Files
- Frontend config: `frontend/.env`
- Nginx config: `/etc/nginx/sites-available/virtualpytest-frontend`
- Build config: `frontend/vite.config.ts`

## Required Ports (Configure in Proxmox)
- **HTTP**: 80 TCP (may be restricted to reverse proxy)
- **HTTPS**: 443 TCP (if SSL configured)
- **Frontend Production**: 5073 TCP (internal network only)

## Next Steps
1. Configure API endpoints in `frontend/.env`
2. Set up SSL certificates if needed
3. Test web interface: http://192.168.x.105/
4. Configure reverse proxy routing (from reverse proxy VM)
5. Set up monitoring and logging

## Service Management
```bash
# Check Nginx status
sudo systemctl status nginx

# Reload Nginx configuration
sudo systemctl reload nginx

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Rebuild frontend (after code changes)
cd frontend
npm run build
sudo systemctl reload nginx

# Check Node.js processes
ps aux | grep node
```