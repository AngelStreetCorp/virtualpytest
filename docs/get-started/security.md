# Security setup

> **Going live?** Start with the [production hardening checklist](production-checklist.md): the
> defaults the installers ship (MinIO, Redis, VNC, Postgres, open mode) and what to close first.

> **Purpose**: Security configuration and best practices for VirtualPyTest  
> **Audience**: Security Engineers, DevOps, System Administrators

---

## Overview

### Security Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SECURITY ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      LAYER 1: TRANSPORT                             │   │
│   │   • TLS 1.3 encryption (Let's Encrypt)                              │   │
│   │   • HTTPS enforcement                                               │   │
│   │   • WSS for WebSockets                                              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      LAYER 2: NETWORK                               │   │
│   │   • Firewall (UFW/iptables)                                         │   │
│   │   • VLAN isolation (Production)                                     │   │
│   │   • VPN for remote access                                           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      LAYER 3: APPLICATION                           │   │
│   │   • API Key authentication                                          │   │
│   │   • CORS whitelist                                                  │   │
│   │   • Input validation                                                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      LAYER 4: DATA                                  │   │
│   │   • Secrets in .env (git-ignored)                                   │   │
│   │   • Database RLS (Supabase)                                         │   │
│   │   • Encrypted storage                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Threat Model Summary

| Threat | Mitigation | Priority |
|--------|------------|----------|
| Man-in-the-middle | TLS/HTTPS | Critical |
| Unauthorized API access | API Keys + CORS | Critical |
| Network intrusion | Firewall + VLAN | High |
| Secret exposure | .env + git-ignore | Critical |
| Container escape | Non-root + limits | Medium |
| Database breach | RLS + encryption | High |

---

## Part A: Transport Security

### SSL/TLS Configuration

**Nginx SSL Settings (recommended):**

```nginx
# /etc/nginx/snippets/ssl-params.conf

ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers on;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_ecdh_curve secp384r1;

ssl_session_timeout 1d;
ssl_session_cache shared:SSL:50m;
ssl_session_tickets off;

ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;

add_header Strict-Transport-Security "max-age=63072000" always;
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
```

### Certificate Management (Let's Encrypt)

**Initial Setup:**
```bash
# Install certbot
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.yourdomain.com \
    --non-interactive \
    --agree-tos \
    --email admin@yourdomain.com \
    --redirect

# Verify auto-renewal
sudo systemctl status certbot.timer
```

**Manual Renewal:**
```bash
# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check expiry
sudo certbot certificates
```

**Auto-Renewal Cron (backup):**
```bash
# /etc/cron.d/certbot-renew
0 3 * * * root certbot renew --quiet --post-hook "systemctl reload nginx"
```

### HTTPS Enforcement

**Nginx Redirect:**
```nginx
server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

**HSTS Header:**
```nginx
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
```

---

## Part B: Authentication & Authorization

### API Keys (Server ↔ Host)

**Purpose:** Authenticate communication between Backend Server and Backend Hosts.

**Generate Strong Key:**
```bash
# Generate 32-byte random key
openssl rand -hex 32
# Example: a1b2c3d4e5f6...

# Or use Python
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Configuration:**

`.env` (project root):
```bash
API_KEY=your_api_key_here
```

`backend_host_N/.env`:
```bash
API_KEY=your_api_key_here
```

**Validation (Backend Server):**
```python
from functools import wraps
from flask import request, jsonify
import os

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.getenv('API_KEY'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated
```

### Supabase Auth (Optional)

**Row Level Security (RLS):**
```sql
-- Enable RLS on table
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their team's devices
CREATE POLICY "Users can view own team devices"
ON devices FOR SELECT
USING (team_id = auth.jwt() ->> 'team_id');

-- Policy: Users can only modify their team's devices
CREATE POLICY "Users can modify own team devices"
ON devices FOR ALL
USING (team_id = auth.jwt() ->> 'team_id');
```

**Service Role Key (Server-side only):**
```bash
# NEVER expose in frontend
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
```

### CORS Configuration

`shared/src/lib/utils/app_utils.py` calls `CORS(app, origins=..., supports_credentials=True)` for
both `backend_server` and `backend_host` — it is wired up, and it is the **only** origin-based
access control in front of `/server/*` and `/host/*`. nginx does not restrict either location by
IP (verified against every shipped template) — CORS is it. Since 2026-09-15 (BUG-0092) the
allowed origins come from `CORS_ALLOWED_ORIGINS` (comma-separated; unset = the vendor's own
known frontend domains, see `.env.example`) — there is **no `*` fallback**.

> **If you deployed before 2026-09-15**, your server was almost certainly running
> `origins="*", supports_credentials=True`, which Flask-CORS turns into "reflect whichever
> `Origin` header the caller sends, and allow credentials for it" — any web page, anywhere,
> could make a fully-credentialed cross-origin call to your API and read the response. Redeploy
> the current code to pick up the fix; see the [production checklist](production-checklist.md).

Set it only if your frontend is served from a **different origin** than this server — e.g. a
Vercel-hosted frontend calling a Render-hosted server (see
[Cloud Setup, Step 4.1](cloud-setup.md#41-cors-only-needed-if-the-frontend-calls-render-directly)),
or one frontend switching between several backend servers. A same-origin deployment (frontend
and `/server/` behind the same nginx host — the default in the Proxmox and Docker install paths)
needs no CORS configuration at all: same-origin requests never trigger the browser's CORS checks
in the first place.

```bash
# .env
CORS_ALLOWED_ORIGINS=https://virtualpytest.vercel.app,https://yourdomain.com
```

---

## Part C: Network Security

### Firewall Rules (UFW)

> Port 6109 (the host API) is now restricted to the LAN automatically by
> `setup/local/linux/backend_host/install_host.sh` (STEP 11) — it auto-detects the host's own
> subnet, without touching any other port or UFW's own default policy. Set `VPT_HOST_LAN_CIDR`
> before running the installer if your server/proxy sit on a different subnet than the host.
> The manual commands below are for everything the installer doesn't cover, or for adjusting
> port 6109's rule by hand.

**Standalone Setup:**
```bash
# Enable UFW
sudo ufw enable

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (restrict to your IP if possible)
sudo ufw allow from 192.168.1.0/24 to any port 22

# VirtualPyTest services (LAN only)
sudo ufw allow from 192.168.1.0/24 to any port 3000  # Frontend
sudo ufw allow from 192.168.1.0/24 to any port 5109  # Server
sudo ufw allow from 192.168.1.0/24 to any port 6109  # Host
sudo ufw allow from 192.168.1.0/24 to any port 6080  # NoVNC

# Verify
sudo ufw status verbose
```

**Production Setup:**
```bash
# Enable UFW
sudo ufw enable

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (from management network only)
sudo ufw allow from 10.0.3.0/24 to any port 22

# HTTPS only (public)
sudo ufw allow 443/tcp

# HTTP for Let's Encrypt challenges
sudo ufw allow 80/tcp

# Block direct access to internal services
# (Nginx proxies all traffic)

# Verify
sudo ufw status verbose
```

### VLAN Isolation (Production)

**Network Segmentation:**

| VLAN | Subnet | Access Policy |
|------|--------|---------------|
| 10 (Compute) | 10.0.1.0/24 | Can reach Devices, Internet |
| 20 (Devices) | 10.0.2.0/24 | No Internet, Compute only |
| 30 (Management) | 10.0.3.0/24 | Can reach all VLANs |

**Inter-VLAN Firewall:**
```
# Compute → Devices (device control)
ALLOW 10.0.1.0/24 → 10.0.2.0/24 : TCP 5555 (ADB)
ALLOW 10.0.1.0/24 → 10.0.2.0/24 : TCP 80,443 (HTTP)

# Devices → Internet (BLOCKED)
DENY 10.0.2.0/24 → ANY

# Devices → Compute (responses only)
ALLOW 10.0.2.0/24 → 10.0.1.0/24 : ESTABLISHED

# Management → All
ALLOW 10.0.3.0/24 → ANY
```

### VPN Options

**WireGuard (Self-hosted):**
```bash
# Server config (/etc/wireguard/wg0.conf)
[Interface]
Address = 10.200.200.1/24
PrivateKey = <SERVER_PRIVATE_KEY>
ListenPort = 51820
PostUp = ufw allow 51820/udp
PostDown = ufw delete allow 51820/udp

[Peer]
PublicKey = <CLIENT_PUBLIC_KEY>
AllowedIPs = 10.200.200.2/32
```

**Tailscale (Managed):**
```bash
# Install and join network
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=tskey-xxx

# Access via Tailscale IP
# http://100.x.y.z:5109
```

---

## Part D: Secrets Management

### Environment Files (.env)

**File Hierarchy:**
```
virtualpytest/
├── .env                      # Main secrets (git-ignored)
├── .env.example              # Template (committed)
├── backend_host_1/.env       # Host 1 secrets (git-ignored)
├── backend_host_2/.env       # Host 2 secrets (git-ignored)
└── setup/docker/hetzner_custom/
    ├── config.env            # Deployment config (git-ignored)
    └── config.env.example    # Template (committed)
```

**Required in .gitignore:**
```gitignore
# Environment files with secrets
.env
*.env
!*.env.example
!*.env.template

# Host-specific configs
backend_host_*/.env

# Deployment configs
setup/docker/hetzner_custom/config.env
```

### Secret Categories

| Secret | Location | Rotation |
|--------|----------|----------|
| `API_KEY` | .env, host .env | Quarterly |
| `SUPABASE_SERVICE_ROLE_KEY` | .env | On compromise |
| `CLOUDFLARE_R2_SECRET_ACCESS_KEY` | .env | Annually |
| `OPENROUTER_API_KEY` | .env | Annually |
| `GRAFANA_ADMIN_PASSWORD` | .env | On first login |

### Secret Rotation

**API Key Rotation:**
```bash
# 1. Generate new key
NEW_KEY=$(openssl rand -hex 32)

# 2. Update server .env
sed -i "s/API_KEY=.*/API_KEY=$NEW_KEY/" .env

# 3. Update all host .env files
for i in 1 2 3 4; do
    sed -i "s/API_KEY=.*/API_KEY=$NEW_KEY/" backend_host_$i/.env
done

# 4. Restart services
docker-compose -f docker-compose.yml restart
```

**Database Credentials (Supabase):**
```bash
# 1. Generate new password in Supabase dashboard
# 2. Update connection string
# 3. Restart services
# 4. Revoke old password in Supabase
```

---

## Part E: Container Security

### Non-Root Users

**Dockerfile Best Practice:**
```dockerfile
# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set ownership
RUN chown -R appuser:appuser /app

# Switch to non-root
USER appuser

# Run application
CMD ["gunicorn", "app:app"]
```

### Privileged Mode (Hardware Access)

**When Required:**
- USB device access (`/dev/ttyUSB*`)
- HDMI capture (`/dev/video*`)
- GPIO control

**Minimal Privileges (preferred):**
```yaml
# docker-compose.yml
backend_host:
  devices:
    - /dev/video0:/dev/video0
    - /dev/ttyUSB0:/dev/ttyUSB0
  group_add:
    - video
    - dialout
```

**Full Privileged (if needed):**
```yaml
backend_host:
  privileged: true
  volumes:
    - /dev:/dev
```

### Image Security

**Base Image:**
```dockerfile
# Use specific version, not 'latest'
FROM python:3.11-slim-bookworm

# Update and install security patches
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
```

**Scan for Vulnerabilities:**
```bash
# Using Trivy
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy image virtualpytest-backend-server:latest

# Using Docker Scout
docker scout cves virtualpytest-backend-server:latest
```

---

## Part F: External Services Security

### Supabase

**Security Checklist:**
- [ ] Enable Row Level Security (RLS) on all tables
- [ ] Use service role key only server-side
- [ ] Use anon key for frontend (limited permissions)
- [ ] Enable email confirmation for auth
- [ ] Set up database backups
- [ ] Monitor auth logs

**API Key Permissions:**
```
anon key:      Read public data only
service role:  Full access (server-side only)
```

### Cloudflare R2

**Security Checklist:**
- [ ] Create dedicated API token (not global)
- [ ] Limit token to specific bucket
- [ ] Enable bucket encryption
- [ ] Set CORS policy on bucket
- [ ] Use signed URLs for sensitive files

**CORS Policy:**
```json
[
  {
    "AllowedOrigins": ["https://yourdomain.com"],
    "AllowedMethods": ["GET", "PUT"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3600
  }
]
```

### OpenRouter

**Security Checklist:**
- [ ] Set spending limits
- [ ] Monitor usage dashboard
- [ ] Use environment variable (never hardcode)
- [ ] Rotate key if exposed

**Rate Limiting:**
```python
# Implement client-side rate limiting
from ratelimit import limits, sleep_and_retry

@sleep_and_retry
@limits(calls=10, period=60)  # 10 calls per minute
def call_openrouter(prompt):
    # API call
    pass
```

### Grafana

**Security Checklist:**
- [ ] Change default admin password immediately
- [ ] Disable anonymous access
- [ ] Use HTTPS (proxied through Nginx)
- [ ] Restrict dashboard editing
- [ ] Enable audit logging

**Configuration:**
```ini
# /etc/grafana/grafana.ini

[security]
admin_user = admin
admin_password = <strong-password>
disable_gravatar = true
cookie_secure = true
cookie_samesite = strict

[auth.anonymous]
enabled = false

[users]
allow_sign_up = false
allow_org_create = false
```

**Environment Variables:**
```bash
GRAFANA_ADMIN_PASSWORD=<strong-password>
GF_SECURITY_ADMIN_PASSWORD=<strong-password>
GF_AUTH_ANONYMOUS_ENABLED=false
GF_USERS_ALLOW_SIGN_UP=false
```

---

## Appendix

### A. Security Checklist (Standalone)

**Transport:**
- [ ] HTTPS enabled (even for local, use self-signed)
- [ ] Strong TLS configuration

**Network:**
- [ ] UFW enabled
- [ ] Services bound to LAN only
- [ ] SSH key authentication

**Application:**
- [ ] API_KEY configured
- [ ] CORS restricted to localhost

**Secrets:**
- [ ] .env file created (not committed)
- [ ] Strong passwords for all services
- [ ] Grafana admin password changed

**Container:**
- [ ] Docker group limited to trusted users
- [ ] Regular image updates

### B. Security Checklist (Production)

**Transport:**
- [ ] Let's Encrypt certificate installed
- [ ] Auto-renewal configured
- [ ] HSTS enabled
- [ ] TLS 1.2+ only

**Network:**
- [ ] UFW enabled with minimal rules
- [ ] VLAN isolation configured
- [ ] No direct Internet for device VLAN
- [ ] VPN for remote admin access
- [ ] Management network isolated

**Application:**
- [ ] Strong API_KEY (32+ bytes)
- [ ] CORS restricted to production domains
- [ ] Rate limiting enabled
- [ ] Input validation on all endpoints

**Secrets:**
- [ ] All .env files git-ignored
- [ ] Secrets rotated on schedule
- [ ] No secrets in logs
- [ ] No secrets in Docker images

**Database:**
- [ ] Supabase RLS enabled
- [ ] Service role key protected
- [ ] Database backups enabled
- [ ] Connection over SSL

**External Services:**
- [ ] R2 bucket access restricted
- [ ] OpenRouter spending limits set
- [ ] Grafana anonymous access disabled
- [ ] All API keys unique per service

**Container:**
- [ ] Non-root users where possible
- [ ] Minimal privileged containers
- [ ] Regular vulnerability scans
- [ ] Image pinning (no :latest)

**Monitoring:**
- [ ] Failed auth attempts logged
- [ ] Anomaly detection enabled
- [ ] Alert on security events

### C. Incident Response

**If API Key Compromised:**
```bash
# 1. Generate new key immediately
NEW_KEY=$(openssl rand -hex 32)

# 2. Update all configs
sed -i "s/API_KEY=.*/API_KEY=$NEW_KEY/" .env
for f in backend_host_*/.env; do
    sed -i "s/API_KEY=.*/API_KEY=$NEW_KEY/" "$f"
done

# 3. Restart all services
docker-compose down && docker-compose up -d

# 4. Review access logs for abuse
docker logs virtualpytest-backend-server | grep -i "unauthorized\|401"

# 5. Document incident
```

**If Database Credentials Compromised:**
```bash
# 1. Rotate password in Supabase dashboard
# 2. Update SUPABASE_DB_URI in .env
# 3. Restart services
# 4. Review database audit logs
# 5. Check for unauthorized data access
```

**If Server Compromised:**
```bash
# 1. Isolate server (disconnect network)
# 2. Preserve logs for forensics
# 3. Rotate ALL credentials
# 4. Rebuild from clean image
# 5. Restore data from backup
# 6. Review and patch vulnerability
```

### D. Security Contacts

| Issue | Contact |
|-------|---------|
| VirtualPyTest vulnerabilities | GitHub Issues (private) |
| Supabase issues | support@supabase.io |
| Cloudflare issues | Cloudflare Dashboard |
| Infrastructure issues | Your security team |

---

**Back to:** [Documentation Index](README.md)
