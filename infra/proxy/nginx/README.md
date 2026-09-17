# VirtualPyTest Nginx Configurations

This directory contains self-contained nginx configuration files for different deployment scenarios.

## 📁 Configuration Files

```
nginx/
├── config/
│   ├── docker.conf                # Docker Compose deployment
│   ├── local-http.conf            # Localhost development (HTTP)
│   ├── proxmox.local.conf         # Proxmox VM deployment (HTTP)
│   ├── proxmox.local.https.conf   # Proxmox VM deployment (HTTPS)
│   ├── proxmox.https.conf         # Proxmox public (HTTPS)
│   └── production-https.conf      # Production with SSL (HTTPS)
├── docker-compose.yml             # Docker orchestration
├── docker-compose.env.example     # Environment template
└── DOCKER-COMPOSE-README.md       # Docker quick start
```

## 🚀 Quick Start

### Docker Compose (Recommended)

```bash
cd nginx/
cp docker-compose.env.example .env
nano .env  # Add your database credentials
docker-compose up -d
```

Access: `http://localhost/`

### Local Development

```bash
# Copy config to nginx
sudo cp nginx/config/local-http.conf /etc/nginx/sites-available/virtualpytest

# Enable site
sudo ln -sf /etc/nginx/sites-available/virtualpytest /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t && sudo systemctl reload nginx
```

Access: `http://localhost/`

### Production (HTTPS)

```bash
# Get SSL certificates first
sudo certbot certonly --nginx -d yourdomain.com

# Copy and edit config
sudo cp nginx/config/production-https.conf /etc/nginx/sites-available/virtualpytest
sudo nano /etc/nginx/sites-available/virtualpytest
# Edit: SERVICE CONFIGURATION section with your IPs
# Edit: SSL certificate paths if needed

# Enable and reload
sudo ln -sf /etc/nginx/sites-available/virtualpytest /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Using Custom Configs

```bash
# Method 1: Command line argument
./install_nginx.sh path/to/your/custom-config.conf

# Method 2: Environment variable
VIRTUALPYTEST_CONFIG="path/to/your/custom-config.conf" ./install_nginx.sh

# Example: Proxmox deployment
./install_nginx.sh ../../../proxmox/vm/proxy/config/nginx.local.conf
```

## 📋 Configuration Details

All config files follow the same **upstream + map** pattern:

```nginx
# SERVICE CONFIGURATION (edit IPs here only)

# Reverse Proxy IP (nginx server ip - used for access URL display)
# REVERSE_PROXY_IP: 192.168.x.100

upstream frontend { server 192.168.x.105:5073; }
upstream backend_server { server 192.168.x.103:5109; }
upstream grafana { server 192.168.x.106:3000; }
upstream minio { server 192.168.x.101:9000; }

# Host routing maps (for /host/{name}/ endpoints)
map $host_identifier $backend_host_ip {
    default "192.168.x.200";
    "host1" "192.168.x.200";
    "host2" "192.168.x.201";
}

# Server block uses upstream names
location / {
    proxy_pass http://frontend;  # Uses upstream
}
location /server/ {
    proxy_pass http://backend_server;  # Uses upstream
}
location ~ ^/host/([^/]+)/api/ {
    proxy_pass http://$backend_host_ip:$backend_host_port/;  # Uses map
}
location ~ ^/host/([^/]+)/stream/(.+)$ {
    proxy_pass http://$backend_host_ip:$backend_host_port/stream/$2;  # Uses map
}
```

### Stream Routing Architecture

Stream content (HLS segments, captures, thumbnails, archive manifests) is served by Flask on the backend host. The proxy uses `proxy_pass` to forward `/host/{name}/stream/...` requests to the backend host's Flask app (port 6109), which serves files from `/var/www/html/stream/` with hot/cold storage support.

This `proxy_pass` approach works regardless of whether the proxy is colocated with the backend host or on a separate machine — no NFS mounts or local file copies required.

### Reverse Proxy IP Configuration

Each config file includes a `REVERSE_PROXY_IP` comment that specifies the nginx server's IP address. This is used by the installation script to display actual access URLs instead of placeholders.

```nginx
# REVERSE_PROXY_IP: 192.168.x.100
```

**Note**: This is a comment (not an nginx directive) and is only used by the install script to show helpful URLs. Nginx itself doesn't need to know its own external IP.

### `config/docker.conf`

**For**: Docker Compose deployments  
**Protocol**: HTTP  
**Services**: Uses Docker service names

```nginx
# SERVICE CONFIGURATION
# REVERSE_PROXY_IP: localhost

upstream frontend { server frontend:5073; }
upstream backend_server { server backend_server:5109; }
upstream grafana { server grafana:3000; }
upstream minio { server minio:9000; }

map $host_identifier $backend_host_ip {
    default "backend_host";
    "localhost" "backend_host";
}
```

### `config/local-http.conf`

**For**: Localhost development  
**Protocol**: HTTP  
**Services**: All on 127.0.0.1

```nginx
# SERVICE CONFIGURATION
# REVERSE_PROXY_IP: 127.0.0.1

upstream frontend { server 127.0.0.1:5073; }
upstream backend_server { server 127.0.0.1:5109; }
upstream grafana { server 127.0.0.1:3000; }
upstream minio { server 127.0.0.1:9000; }

map $host_identifier $backend_host_ip {
    default "127.0.0.1";
    "localhost" "127.0.0.1";
}
```

### `config/proxmox.local.conf`

**For**: Proxmox VM deployment  
**Protocol**: HTTP  
**Services**: Pre-configured with Proxmox VM IPs

```nginx
# SERVICE CONFIGURATION
# REVERSE_PROXY_IP: 192.168.x.100

upstream frontend { server 192.168.x.105:5073; }
upstream backend_server { server 192.168.x.103:5109; }
upstream grafana { server 192.168.x.106:3000; }
upstream minio { server 192.168.x.101:9000; }

map $host_identifier $backend_host_ip {
    default "192.168.x.200";
    "localhost" "192.168.x.200";
    "host1" "192.168.x.200";
}
```

### `config/production-https.conf`

**For**: Production servers with SSL  
**Protocol**: HTTPS with HTTP redirect  
**Services**: Edit the upstream blocks

```nginx
# SERVICE CONFIGURATION - Edit IPs here
# REVERSE_PROXY_IP: your-domain.com

upstream frontend { server 127.0.0.1:5073; }
upstream backend_server { server 127.0.0.1:5109; }
upstream grafana { server 127.0.0.1:3000; }
upstream minio { server 127.0.0.1:9000; }

map $host_identifier $backend_host_ip {
    default         "127.0.0.1";
    # Proxmox example:
    # "pi1"         "192.168.x.140";
    # "pi2"         "192.168.x.141";
}
```

## 🔧 Customization

Each config file is **self-contained**. To customize:

1. **Copy the appropriate config** to `/etc/nginx/sites-available/`
2. **Edit the SERVICE CONFIGURATION section** at the top
3. **Test and reload**: `sudo nginx -t && sudo systemctl reload nginx`

### Adding Backend Hosts

Edit the `map` block in your config:

```nginx
map $host_identifier $backend_host_ip {
    default         "192.168.x.200";
    "localhost"     "192.168.x.200";
    "pi1"           "192.168.x.140";  # Add your hosts
    "pi2"           "192.168.x.141";
    "pi3"           "192.168.x.142";
}
```

Then reload nginx: `sudo nginx -s reload`

## 🌐 URL Patterns

All configs support these routes:

| Service | URL | Routing | Description |
|---------|-----|---------|-------------|
| Frontend | `/` | `proxy_pass` → upstream | React web app |
| Backend API | `/server/` | `proxy_pass` → upstream | REST API |
| Host API | `/host/{name}/api/` | `proxy_pass` → map | Backend host control (Flask :6109) |
| Streams | `/host/{name}/stream/{path}` | `proxy_pass` → map | HLS segments, captures, archives (Flask :6109) |
| VNC | `/host/{name}/vnc_lite.html` | `proxy_pass` → map | Web VNC access (websockify :6080) |
| WebSocket | `/host/{name}/websockify` | `proxy_pass` → map | VNC WebSocket tunnel (:6080) |
| Phone link | `/host/{name}/phone/socket.io/` | `proxy_pass` → map | Mobile-app phone WebSocket (Socket.IO `/phone` ns, Flask :6109, TASK-17) |
| Grafana | `/grafana/` | `proxy_pass` → upstream | Monitoring dashboard |
| Health | `/health` | local | Health check |

### MinIO Storage

The `/minio/` prefix proxies to the MinIO object store, so it needs a lightweight streaming configuration instead of the defaults used for the frontend/backend routes. Every config now includes the following block:

```nginx
location /minio/ {
    proxy_pass http://minio/;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
}
```

Keeping the upstream connection alive (`proxy_http_version 1.1` + `proxy_set_header Connection ""`) and disabling buffering prevents the intermittent delays/504s that can happen when the proxy waits for MinIO to stream large objects.

## 🧪 Testing

### Test Proxy Endpoints
```bash
# Test with localhost
./nginx/test_proxy.sh

# Test with specific IP
./nginx/test_proxy.sh 192.168.x.107
```

### Test Configuration
```bash
sudo nginx -t
```

### View Logs
```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

### Check Service Status
```bash
sudo systemctl status nginx
```

### Common Issues

**502 Bad Gateway**: Backend service not running
```bash
# Check if services are running
curl http://127.0.0.1:5073  # Frontend
curl http://127.0.0.1:5109  # Backend server
curl http://127.0.0.1:6109  # Backend host
```

**Host not found**: Missing from map block
```bash
# Add host to the map $host_identifier block in your config
sudo nano /etc/nginx/sites-available/virtualpytest
sudo nginx -s reload
```

## 📊 Deployment Matrix

| Environment | Config File | Protocol | Service Config |
|------------|-------------|----------|----------------|
| Docker | `docker.conf` | HTTP | Docker service names |
| Local Dev | `local-http.conf` | HTTP | 127.0.0.1 IPs |
| Proxmox VM (HTTP) | `proxmox.local.conf` | HTTP | 192.168.0.x IPs |
| Proxmox VM (HTTPS) | `proxmox.local.https.conf` | HTTPS | 192.168.0.x IPs |
| Proxmox Public | `proxmox.https.conf` | HTTPS | 192.168.0.x IPs |
| Production | `production-https.conf` | HTTPS | Custom IPs |

## 🔗 Related Documentation

- [Docker Compose README](./DOCKER-COMPOSE-README.md)
- [Nginx Documentation](https://nginx.org/en/docs/)
- [Let's Encrypt](https://letsencrypt.org/)
