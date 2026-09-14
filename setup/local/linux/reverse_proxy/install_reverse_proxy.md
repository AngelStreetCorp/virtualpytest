# Reverse Proxy VM Installation

## Overview
This script installs and configures the VirtualPyTest Reverse Proxy VM with Nginx load balancer, SSL termination, and routing to all backend services.

## Prerequisites
- Debian/Ubuntu Linux
- sudo access for system service configuration
- DNS configuration pointing to this VM (192.168.x.107)
- Firewall configuration handled at Proxmox level

## Usage
```bash
# Install reverse proxy
./setup/local/install_reverse_proxy.sh
```

## What It Does
1. **Nginx Installation & Configuration**
   - Installs Nginx web server
   - Configures as reverse proxy and load balancer
   - Sets up SSL/TLS termination (if certificates available)

2. **Service Routing Configuration**
   - Routes `/` → Frontend VM (192.168.x.105:5073)
   - Routes `/server/` → Backend Server VM (192.168.x.103:5109)
   - Routes `/host/{name}/api/` → Backend Host Flask API (map → :6109)
   - Routes `/host/{name}/stream/` → Backend Host Flask stream serving (map → :6109)
   - Routes `/host/{name}/vnc_lite.html` → Backend Host websockify (map → :6080)
   - Routes `/grafana/` → Monitoring VM (192.168.x.106:3000)

3. **Load Balancing Setup**
   - Configures upstream servers for backend hosts
   - Sets up round-robin load balancing
   - Configures health checks and failover

4. **SSL/TLS Configuration**
   - Generates self-signed certificates for HTTPS configs (development)
   - Sets up Let's Encrypt certificates (production recommended)
   - Configures automatic HTTP to HTTPS redirection
   - Implements security headers and HSTS

5. **Security Hardening**
   - Configures rate limiting
   - Sets up fail2ban for SSH protection
   - Implements basic DDoS protection

## Services Installed
- **Nginx Reverse Proxy** (`nginx.service`)
  - Load balancer and reverse proxy
  - SSL termination and routing
  - Auto-starts on boot

- **Fail2Ban** (`fail2ban.service`) - optional
  - SSH brute force protection
  - Auto-bans malicious IPs

## Routing Configuration
```
/                              → proxy_pass → Frontend VM (192.168.x.105:5073)
/server/                       → proxy_pass → Backend Server VM (192.168.x.103:5109)
/host/{name}/api/              → proxy_pass → Backend Host Flask (:6109, via map)
/host/{name}/stream/{path}     → proxy_pass → Backend Host Flask (:6109, via map)
/host/{name}/vnc_lite.html     → proxy_pass → Backend Host websockify (:6080, via map)
/host/{name}/websockify        → proxy_pass → Backend Host websockify (:6080, via map)
/grafana/                      → proxy_pass → Monitoring VM (192.168.x.106:3000)
```

All `/host/{name}/` routes use nginx `map` blocks to resolve the backend host IP from the host identifier. Stream content (HLS segments, captures, thumbnails, archive manifests) is served by Flask on the backend host — no local file mounts needed on the proxy VM.

## Access Points
- **Main Application**: http://192.168.x.107/ (or https:// if SSL configured)
- **API Endpoints**: http://192.168.x.107/server/ (or https://)
- **Host Control**: http://192.168.x.107/host/ (or https://)
- **Monitoring**: http://192.168.x.107/grafana/ (or https://)
- **VNC Access**: http://192.168.x.107/vnc/ (or https://)

**Note**: HTTPS URLs are automatically shown when using SSL-enabled configurations.

## Configuration Files
- Nginx config: `/etc/nginx/sites-available/virtualpytest`
- SSL certificates: `/etc/ssl/virtualpytest/` (auto-generated for HTTPS configs)
- Upstream config: `/etc/nginx/conf.d/upstreams.conf`

## SSL Certificates

The installation script automatically generates self-signed SSL certificates when using HTTPS-enabled nginx configurations (like `proxmox.local.https.conf`). This allows immediate HTTPS testing without domain setup.

### Auto-Generated Certificates
- **Location**: `/etc/ssl/virtualpytest/`
- **Certificate**: `virtualpytest.crt`
- **Private Key**: `virtualpytest.key`
- **Validity**: 365 days
- **Subject**: `CN=virtualpytest.local`
- **Alt Names**: `virtualpytest.local`, `localhost`, `127.0.0.1`

### Browser Warning
Self-signed certificates will show a security warning in browsers. To proceed:
1. Click "Advanced" or "Show Details"
2. Click "Proceed to [site] (unsafe)" or "Accept the Risk"

### Production SSL Setup
For production environments, replace self-signed certificates with Let's Encrypt certificates:

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Generate certificate (requires domain pointing to server)
sudo certbot --nginx -d yourdomain.com

# The script will automatically detect and use Let's Encrypt certificates
```

### Custom SSL Certificates
To use your own SSL certificates:

1. Place your certificate files in `/etc/ssl/virtualpytest/`
2. Update the nginx config to point to your certificate files:
   ```nginx
   ssl_certificate /etc/ssl/virtualpytest/your-cert.pem;
   ssl_certificate_key /etc/ssl/virtualpytest/your-key.key;
   ```

The script detects HTTPS configurations automatically and generates certificates as needed.

### Customizing Service IPs

Edit the **SERVICE CONFIGURATION** section at the top of your nginx config file:

```nginx
# =============================================================================
# SERVICE CONFIGURATION - Edit IPs here only
# =============================================================================

# Reverse Proxy IP (nginx server ip - used for access URL display)
# REVERSE_PROXY_IP: 192.168.x.100

# Frontend (React app)
upstream frontend {
    server 192.168.x.105:5073;
}

# Backend Server (Flask API)
upstream backend_server {
    server 192.168.x.103:5109;
}

# Grafana Monitoring
upstream grafana {
    server 192.168.x.106:3000;
}
```

**Note**: The `REVERSE_PROXY_IP` is a comment used by the install script to display actual access URLs. Update this to match your nginx server's IP address.

## Required Ports (Configure in Proxmox)
- **HTTP**: 80 TCP (external access, auto-redirects to HTTPS if SSL enabled)
- **HTTPS**: 443 TCP (automatic if using HTTPS config, external access)
- **SSH**: 22 TCP (management access from trusted networks only)

## Next Steps
1. Configure DNS to point to 192.168.x.107
2. Test all service routes (accept browser SSL warnings for self-signed certs)
3. Set up production SSL certificates with Let's Encrypt (optional)
4. Configure additional security headers
5. Set up monitoring for proxy performance

## Service Management
```bash
# Check Nginx status
sudo systemctl status nginx

# Reload Nginx configuration
sudo systemctl reload nginx

# View access logs
sudo tail -f /var/log/nginx/access.log

# View error logs
sudo tail -f /var/log/nginx/error.log

# Test configuration
sudo nginx -t

# Check fail2ban status
sudo systemctl status fail2ban
sudo fail2ban-client status sshd
```

## Proxy Smoke Test

```bash
./setup/local/linux/reverse_proxy/test_proxy.sh
```
