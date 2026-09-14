# Network setup

> **Purpose**: Network architecture and connectivity for VirtualPyTest  
> **Audience**: Network Engineers, DevOps, System Administrators

---

## Overview

VirtualPyTest requires network connectivity for:
- Service communication (Frontend ↔ Server ↔ Host)
- Device control (ADB, IR, Smart devices)
- Cloud services (Database, Storage, AI)
- Remote access (Web UI, VNC)

### Port Summary

| Service | Port | Protocol | Direction |
|---------|------|----------|-----------|
| Frontend | 3000 | HTTP/S | Inbound |
| Backend Server | 5109 | HTTP/WS | Inbound |
| Backend Host | 6109+ | HTTP/WS | Inbound |
| Grafana | 3001 | HTTP | Inbound |
| NoVNC | 6080 | HTTP/WS | Inbound |
| VNC (raw) | 5900 | TCP | Inbound |
| PostgreSQL | 5432 | TCP | Outbound |
| HTTPS (Cloud) | 443 | HTTPS | Outbound |

---

## Part A: Standalone Network

### Topology

```
┌──────────────────────────────────────────────────────────────┐
│                    HOME/OFFICE LAN                           │
│                    192.168.1.0/24                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│     ┌─────────┐                                              │
│     │ Router  │◄────────────────► Internet                   │
│     │  DHCP   │                                              │
│     └────┬────┘                                              │
│          │                                                   │
│          │ LAN                                               │
│          │                                                   │
│     ┌────┴─────────────────────────────────────────┐         │
│     │                                              │         │
│  ┌──▼──────────────────┐    ┌──────────┐    ┌──────▼─────┐   │
│  │ VirtualPyTest Host  │    │   STB    │    │  Mobile    │   │
│  │ 192.168.1.100       │    │ .101     │    │  (DHCP)    │   │
│  │                     │    └──────────┘    └────────────┘   │
│  │ ├─ :3000  Frontend  │          │                │        │
│  │ ├─ :5109  Server    │◄─────────┘ HDMI           │        │
│  │ ├─ :6109  Host      │◄──────────────────────────┘ USB    │
│  │ ├─ :6080  NoVNC     │                                    │
│  │ └─ :3001  Grafana   │                                    │
│  └─────────────────────┘                                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Port Requirements

| Port | Service | Access | Notes |
|------|---------|--------|-------|
| 3000 | Frontend | LAN | Web interface |
| 5109 | Backend Server | LAN | API + WebSocket |
| 6109 | Backend Host | LAN | Device control |
| 6080 | NoVNC | LAN | Web-based VNC |
| 5900 | VNC | LAN | Raw VNC (optional) |
| 3001 | Grafana | LAN | Monitoring |

### Firewall Rules (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH (if remote)
sudo ufw allow 22/tcp

# VirtualPyTest services
sudo ufw allow 3000/tcp    # Frontend
sudo ufw allow 5109/tcp    # Backend Server
sudo ufw allow 6109/tcp    # Backend Host
sudo ufw allow 6080/tcp    # NoVNC
sudo ufw allow 3001/tcp    # Grafana (optional)

# Verify
sudo ufw status
```

### Static IP Configuration

**Recommended:** Assign static IP to host for consistent access.

**/etc/netplan/01-netcfg.yaml** (Ubuntu):
```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses:
        - 192.168.1.100/24
      gateway4: 192.168.1.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
```

Apply: `sudo netplan apply`

### Router Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| DHCP Reservation | Host MAC → 192.168.1.100 | Consistent IP |
| Port Forward (optional) | 443 → 192.168.1.100:5109 | External access |
| DNS (optional) | virtualpytest.local → 192.168.1.100 | Friendly name |

---

## Part B: Production Network

### Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRODUCTION NETWORK                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                              ┌─────────────┐                                │
│           Internet ◄─────────┤  Firewall   │                                │
│                              │  (pfSense)  │                                │
│                              └──────┬──────┘                                │
│                                     │                                       │
│                              ┌──────▼──────┐                                │
│                              │ Core Switch │                                │
│                              │ Arista 10GbE│                                │
│                              │ (L3 Routing)│                                │
│                              └──────┬──────┘                                │
│                                     │                                       │
│          ┌──────────────────────────┼──────────────────────────┐            │
│          │                          │                          │            │
│   ┌──────▼──────┐           ┌───────▼──────┐           ┌───────▼──────┐     │
│   │  VLAN 10    │           │   VLAN 20    │           │   VLAN 30    │     │
│   │  COMPUTE    │           │   DEVICES    │           │  MANAGEMENT  │     │
│   │ 10.0.1.0/24 │           │ 10.0.2.0/24  │           │ 10.0.3.0/24  │     │
│   │             │           │              │           │              │     │
│   │ • Servers   │◄─────────►│ • STBs       │           │ • IPMI/BMC   │     │
│   │ • Capture   │   10GbE   │ • Mobiles    │           │ • Switch Mgmt│     │
│   │ • IR Ctrl   │           │ • Smart TVs  │           │ • PDU Mgmt   │     │
│   │             │           │              │           │              │     │
│   │ Server 1:   │           │ Devices:     │           │ IPMI:        │     │
│   │  10.0.1.11  │           │  10.0.2.1-80 │           │  10.0.3.11-15│     │
│   │ Server 2:   │           │              │           │ Switch:      │     │
│   │  10.0.1.12  │           │              │           │  10.0.3.1    │     │
│   │ ...         │           │              │           │              │     │
│   └─────────────┘           └──────────────┘           └──────────────┘     │
│                                                                             │
│   RACK A (Compute)          RACK B (Devices)                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### VLAN Configuration

| VLAN | ID | Subnet | Purpose | Gateway |
|------|-----|--------|---------|---------|
| Compute | 10 | 10.0.1.0/24 | Servers, capture cards | 10.0.1.1 |
| Devices | 20 | 10.0.2.0/24 | Test devices (STB, mobile) | 10.0.2.1 |
| Management | 30 | 10.0.3.0/24 | IPMI, switch mgmt, PDU | 10.0.3.1 |

### Core Switch Configuration (Arista)

```bash
! VLAN definitions
vlan 10
   name COMPUTE
vlan 20
   name DEVICES
vlan 30
   name MANAGEMENT

! Server ports (10GbE trunk)
interface Ethernet1-5
   description Server1-5
   switchport mode trunk
   switchport trunk allowed vlan 10,20,30

! Device uplinks (1GbE access)
interface Ethernet10-48
   description Device-Ports
   switchport mode access
   switchport access vlan 20

! Inter-VLAN routing
interface Vlan10
   ip address 10.0.1.1/24
interface Vlan20
   ip address 10.0.2.1/24
interface Vlan30
   ip address 10.0.3.1/24

! Enable routing
ip routing
```

### Port Matrix by Service

| Service | Source | Destination | Port | Protocol |
|---------|--------|-------------|------|----------|
| Frontend → Server | Any | 10.0.1.x | 5109 | HTTPS/WSS |
| Server → Host | 10.0.1.x | 10.0.1.x | 6109-6119 | HTTP |
| Host → Devices | 10.0.1.x | 10.0.2.x | Various | ADB/HTTP |
| IR Controller | 10.0.1.x | 10.0.1.x | 4998 | TCP |
| IPMI Access | 10.0.3.x | 10.0.3.x | 443/623 | HTTPS/IPMI |

### Firewall Rules (Production)

**Inbound (Internet → DMZ):**
```
# HTTPS to reverse proxy
ALLOW TCP 443 → 10.0.1.10 (Nginx)

# Block all other inbound
DENY ALL
```

**Inter-VLAN:**
```
# Compute → Devices (device control)
ALLOW VLAN10 → VLAN20 (ADB: 5555, HTTP: 80/443)

# Devices → Compute (responses only)
ALLOW VLAN20 → VLAN10 ESTABLISHED

# Management → All (admin access)
ALLOW VLAN30 → VLAN10,20 (SSH: 22, HTTPS: 443)

# Block device-to-device
DENY VLAN20 → VLAN20
```

**Outbound (Internal → Internet):**
```
# Cloud services
ALLOW 10.0.1.0/24 → ANY:443 (HTTPS)
ALLOW 10.0.1.0/24 → ANY:54321-54324 (Supabase services)

# Block devices from internet
DENY 10.0.2.0/24 → ANY
```

### Inter-Rack Connectivity

| Connection | Cable Type | Speed | Distance |
|------------|-----------|-------|----------|
| Rack A ↔ Core Switch | DAC/SFP+ | 10GbE | <5m |
| Rack A ↔ Rack B | Cat6a | 10GbE | 5m |
| Server ↔ Server | DAC | 10GbE | <3m |

---

## Part C: External Connectivity

### Cloud Services

```
┌─────────────────────────────────────────────────────────────────┐
│                     EXTERNAL SERVICES                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   VirtualPyTest                                                 │
│        │                                                        │
│        ├───────► Supabase (Database)                            │
│        │         └─ db.xxxx.supabase.co:5432                    │
│        │         └─ Protocol: PostgreSQL (TCP)                  │
│        │         └─ Auth: Connection string                     │
│        │                                                        │
│        ├───────► Cloudflare R2 (Storage)                        │
│        │         └─ xxxx.r2.cloudflarestorage.com:443           │
│        │         └─ Protocol: S3-compatible (HTTPS)             │
│        │         └─ Auth: Access Key + Secret                   │
│        │                                                        │
│        ├───────► OpenRouter (AI/LLM)                            │
│        │         └─ openrouter.ai:443                           │
│        │         └─ Protocol: REST API (HTTPS)                  │
│        │         └─ Auth: API Key                               │
│        │                                                        │
│        └───────► Vercel (Frontend CDN)                          │
│                  └─ virtualpytest.vercel.app:443                │
│                  └─ Protocol: HTTPS                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Outbound Requirements

| Service | Domain | Port | Protocol | Required |
|---------|--------|------|----------|----------|
| Supabase | *.supabase.co | 5432 | TCP | Yes |
| Cloudflare R2 | *.r2.cloudflarestorage.com | 443 | HTTPS | Yes |
| OpenRouter | openrouter.ai | 443 | HTTPS | Optional |
| npm/pip | registry.npmjs.org, pypi.org | 443 | HTTPS | Build only |
| Docker Hub | docker.io, registry-1.docker.io | 443 | HTTPS | Build only |

### SSL/TLS Configuration

**Let's Encrypt Setup:**
```bash
# Install certbot
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.yourdomain.com \
    --non-interactive \
    --agree-tos \
    --email admin@yourdomain.com

# Auto-renewal (already configured)
sudo systemctl status certbot.timer

# Test renewal
sudo certbot renew --dry-run
```

### Reverse Proxy (Nginx)

**/etc/nginx/sites-available/virtualpytest:**
```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    # SSL (managed by certbot)
    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Increase buffer sizes
    client_max_body_size 100M;
    proxy_buffer_size 128k;
    proxy_buffers 4 256k;

    # Backend Server API
    location /server/ {
        proxy_pass http://127.0.0.1:5109/server/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:5109/server/health;
    }

    # Grafana (optional)
    location /grafana/ {
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
    }

    # Backend Host 1
    location /host1/ {
        rewrite ^/host1/(.*)$ /host/$1 break;
        proxy_pass http://127.0.0.1:6109;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    # Backend Host 2
    location /host2/ {
        rewrite ^/host2/(.*)$ /host/$1 break;
        proxy_pass http://127.0.0.1:6110;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    # Default
    location / {
        proxy_pass http://127.0.0.1:5109;
    }
}
```

**Enable and test:**
```bash
sudo ln -sf /etc/nginx/sites-available/virtualpytest \
            /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Part D: Remote Access Options

### Comparison

| Method | Public IP | Setup | Security | Latency | Best For |
|--------|-----------|-------|----------|---------|----------|
| **Direct** | Required | Easy | Medium | Low | Simple, static IP |
| **Cloudflare Tunnel** | No | Medium | High | Low | Production |
| **Tailscale** | No | Easy | High | Low | Teams |
| **WireGuard** | No | Hard | High | Low | Self-hosted |
| **ngrok** | No | Easy | Medium | Medium | Development |

### Option 1: Direct (Public IP)

**Requirements:**
- Static public IP or Dynamic DNS
- Port forwarding on router
- SSL certificate

**Router Port Forward:**
| External | Internal | Service |
|----------|----------|---------|
| 443 | 192.168.1.100:443 | Nginx (HTTPS) |

### Option 2: Cloudflare Tunnel (Recommended)

**Zero Trust access without public IP.**

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create virtualpytest

# Configure tunnel
cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.yourdomain.com
    service: http://localhost:5109
  - hostname: vnc.yourdomain.com
    service: http://localhost:6080
  - service: http_status:404
EOF

# Run as service
cloudflared service install
systemctl start cloudflared
```

### Option 3: Tailscale

**Mesh VPN with zero configuration.**

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh

# Authenticate
sudo tailscale up

# Get Tailscale IP
tailscale ip -4
# Example: 100.x.y.z

# Access from any Tailscale device
# http://100.x.y.z:5109
```

### Option 4: WireGuard

**Self-hosted VPN.**

```bash
# Install
sudo apt install wireguard

# Generate keys
wg genkey | tee privatekey | wg pubkey > publickey

# Server config (/etc/wireguard/wg0.conf)
[Interface]
Address = 10.200.200.1/24
PrivateKey = <SERVER_PRIVATE_KEY>
ListenPort = 51820

[Peer]
PublicKey = <CLIENT_PUBLIC_KEY>
AllowedIPs = 10.200.200.2/32

# Start
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

### Option 5: ngrok (Development)

**Quick tunnels for testing.**

```bash
# Install
snap install ngrok

# Authenticate
ngrok config add-authtoken <YOUR_TOKEN>

# Tunnel to Backend Server
ngrok http 5109

# Output: https://xxxx.ngrok.io → localhost:5109
```

---

## Appendix

### A. Complete Port Reference

| Port | Service | Protocol | Direction | Required | Notes |
|------|---------|----------|-----------|----------|-------|
| 22 | SSH | TCP | Inbound | Optional | Admin access |
| 80 | HTTP | TCP | Inbound | Yes | Redirect to HTTPS |
| 443 | HTTPS | TCP | Inbound | Yes | Main entry point |
| 3000 | Frontend | HTTP | Inbound | Dev only | Direct access |
| 3001 | Grafana | HTTP | Inbound | Optional | Monitoring |
| 5109 | Backend Server | HTTP/WS | Internal | Yes | API |
| 54321-54324 | Supabase | TCP | Outbound | Yes | API, Database, Studio, Mailpit |
| 5900 | VNC | TCP | Internal | Optional | Raw VNC |
| 6080 | NoVNC | HTTP/WS | Internal | Yes | Web VNC |
| 6109-6119 | Backend Hosts | HTTP | Internal | Yes | Device control |
| 6379 | Redis | TCP | Internal | Yes | Caching & Queuing |
| 51820 | WireGuard | UDP | Inbound | Optional | VPN |

### B. Troubleshooting

**Connection Issues:**

```bash
# Check if port is listening
netstat -tlnp | grep 5109
ss -tlnp | grep 5109

# Test local connectivity
curl http://localhost:5109/server/health

# Test from another machine
curl http://192.168.1.100:5109/server/health

# Check firewall
sudo ufw status verbose

# Check Docker networking
docker network ls
docker network inspect virtualpytest-standalone-network
```

**DNS Issues:**

```bash
# Check DNS resolution
nslookup api.yourdomain.com
dig api.yourdomain.com

# Test with IP directly
curl -H "Host: api.yourdomain.com" http://<IP>/health
```

**SSL Issues:**

```bash
# Check certificate
openssl s_client -connect api.yourdomain.com:443

# Check certificate expiry
certbot certificates

# Force renewal
sudo certbot renew --force-renewal
```

### C. Network Security Checklist

**Standalone:**
- [ ] Static IP configured
- [ ] UFW enabled with required ports only
- [ ] SSH key authentication (disable password)
- [ ] Services bound to LAN interface only

**Production:**
- [ ] VLANs configured and isolated
- [ ] Inter-VLAN firewall rules
- [ ] Management VLAN restricted
- [ ] SSL/TLS on all external endpoints
- [ ] API keys rotated regularly
- [ ] No direct internet access for devices (VLAN 20)
- [ ] IPMI on isolated management network
- [ ] Intrusion detection (optional)
- [ ] Network monitoring (optional)

### D. DNS Records

| Type | Name | Value | TTL | Purpose |
|------|------|-------|-----|---------|
| A | api | <Server IP> | 300 | Backend Server |
| A | vnc | <Server IP> | 300 | NoVNC access |
| CNAME | www | virtualpytest.vercel.app | 300 | Frontend |

---

**Next:** [Install with Docker](docker.md)
