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

## 🗂 Timeline sprite cache (TASK-94)

The Timeline page loads thumbnail sprites (`/host/<name>/stream/<capture>/thumbnails/<hour>/timeline_*.jpg|json`, built by the host's `vpt-timeline` service) from the hosts, often over a home uplink. The proxy can keep them: a read-through `proxy_cache` for **only** those files, so the first viewer pulls a file from the host and everyone after is served by the proxy.

- **What:** `config/example/timeline-cache.conf` holds the two pieces: a `proxy_cache_path` at http level (top of `sites-enabled/virtualpytest`) and two regex locations (`vpt-pi*/vpt-nipogi/vpt-mf1` via `rpitest_origin`, and every other host via `$backend_host_ip`) placed **before** the generic `# Stream auth gate` locations in each server block that has them (virtualpytest and virtualpytest-demo). Same `auth_request` gate as the stream locations: the cache sits behind it, a cached file is never served to a caller the gate refuses. The key is `$uri$is_args$args` (the path contains the host name, the query is the page's `?v=<chunk end time>`), so hosts do not mix and a recycled hour folder (the hosts keep a 24 h ring) is a new key, never yesterday's picture.
- **Size:** `max_size=3g`, `inactive=26h`, `keys_zone=10m` (about 80,000 keys; a device-day is about 430 files). A viewed device-day costs about 29 MB (heaviest about 70 MB), so 3 GB covers about 40-100 devices. The proxy VM (2026-10-14) has one 32 GB disk `/` with 27 GB free, no `/data`, 1.9 GB RAM, so the cache lives in `/var/cache/nginx/vpt-timeline` on `/`; nginx creates the directory on reload and evicts the oldest entries itself when it is full.
- **Only 200 is cached** (`proxy_cache_valid 200 26h`): a 404 before the host built the chunk is not. `proxy_cache_lock on` makes concurrent first viewers share one upstream fetch; `proxy_cache_use_stale` serves a cached file when the host is down or slow. The host's `Cache-Control` is replaced by `expires 1d` so browsers keep versioned files too. `add_header` is deliberately not used in these locations (it would replace the server-level security headers).
- **Apply:** `bash infra/proxy/nginx/apply_timeline_cache.sh --dry-run` shows the diff; without `--dry-run` it backs up, patches, runs `nginx -t` (restores the backup if it fails) and reloads. By hand: (the vhost file is `jndoye`-writable, no root needed; `sudo nginx -t` and `sudo systemctl reload nginx` are allowed): copy `~/nginx-backup/virtualpytest.<ts>` first, insert piece 1 before `upstream rpitest_origin {` and piece 2 before each `# Stream auth gate (BUG-0107 step 2, generalized)` comment, `sudo nginx -t`, `sudo systemctl reload nginx`. Rollback: copy the backup back, `nginx -t`, reload (the cache directory can stay or be deleted).
- **Check:** `du -sh /var/cache/nginx/vpt-timeline` grows as people open the Timeline page; opening the same device again does not hit the host (watch the host's nginx access log for `timeline_`). An unauthenticated request to one of these URLs must still answer 401.
- **Status 2026-10-14:** **applied on the proxy VM at 09:29** with `apply_timeline_cache.sh` (`nginx -t` ok, reloaded; backup `~/nginx-backup/virtualpytest.20261014-092934.pre-timeline-cache`; `/var/cache/nginx/vpt-timeline` created; unauthenticated requests to `timeline_*` and to other stream files both still answer 401; the site answers 200). Cache hits are not yet observed: no host runs `vpt-timeline`, so there are no `timeline_*` files. Level 3 of the precache plan (the host pushing the files into the MinIO/R2 bucket as a 24 h ring like the heatmap) is separate and not built: [TASK-94 §19](../../../docs/tasks/TASK-94-timeline-page.md).

## 📡 Remote Pi live-stream cache

**In plain words.** A device's live video is not one continuous stream: its host writes the video as small files of
0.4 s each (`segments/segment_<N>.ts`) plus a list of the newest ones (`output.m3u8`, the playlist). The browser's
player loops: download the list, download the newest file, again, 2-3 times a second. Every one of those downloads goes
browser → Cloudflare → **proxy** → host and back. For hosts on the lab LAN the proxy → host leg is ~1.5 ms. For the
**remote Pis** (`vpt-pi*`, `vpt-nipogi`, `vpt-mf1`, reached through `rpitest_origin`) it crosses the Pi's home internet:
~160 ms per request, and every byte is **uploaded by the Pi's home connection**.

```
without cache, 3 viewers:  Pi uploads every file 3 times ─► proxy ─► 3 browsers
with cache,    3 viewers:  Pi uploads every file once    ─► proxy keeps a copy (2 min) ─► 3 browsers
```

- **Where:** on the **proxy** (this nginx), nothing on the hosts.
- **What it fixes:** with N viewers of the same Pi device (a wall display + an operator, two people), the Pi uploads each
  video file once instead of N times, and viewers 2..N get it in ~6 ms from the proxy instead of ~80-300 ms from the Pi.
  That matters most for a Pi on a weak link (`vpt-mf1` is on 2.4 GHz Wi-Fi), where several viewers can saturate the
  uplink and make the stream stutter for everyone.
- **What it does not fix:** a single viewer (nothing changes), LAN hosts (already fast), or a stream that stutters
  because the Pi itself is slow (CPU, capture, Wi-Fi with one viewer).
- **Only the video files are cached, not the playlist.** nginx cache lifetimes are whole seconds; a "1 s" playlist cache
  lived 1-2 s (measured: the same last segment for 2 s while the Pi wrote 5 new ones), which would put *every* viewer up
  to 2 s behind live. Playlists therefore go through the normal Pi location, uncached. A segment name is never reused
  (the 9-digit counter continues across ffmpeg restarts, `next_start_number` in `run_ffmpeg.sh`), so a cached file is
  never wrong.
- **Not done, host side:** the Pi's own nginx (the `rpitest_origin` box) sends the playlist **uncompressed**, 28 KB per
  request, about as much upload as the video itself (~12 KB per 0.4 s). Gzip on `application/vnd.apple.mpegurl` there
  would cut it to ~2.4 KB for every viewer, including a single one. The proxy already gzips it towards the browser.

**How.** `config/example/pi-stream-cache.conf` holds the two pieces: a `proxy_cache_path` (`vpt_pistream`,
`/var/cache/nginx/vpt-pistream`, `max_size=1g`, `inactive=10m`) at http level before `upstream rpitest_origin {`, and one
regex location for `…/segments/segment_<N>.ts` on the Pi hosts, placed before each `# Stream auth gate` comment
(virtualpytest and virtualpytest-demo server blocks). Same `auth_request` gate as every stream location: a cached file
is never served to a caller the gate refuses. Only 200 is cached (2 min); `proxy_cache_lock` makes simultaneous first
viewers share one fetch from the Pi. The key is `$http_origin|$uri` because the host echoes the caller's Origin in
`Access-Control-Allow-Origin` (`Vary: Origin`). The host's `no-cache` headers are ignored for this cache only and still
reach the browser.

- **Apply:** `bash infra/proxy/nginx/apply_pi_stream_cache.sh --dry-run` shows the diff; without `--dry-run` it backs up
  (`~/nginx-backup/virtualpytest.<stamp>.pre-pi-stream-cache`), patches, runs `nginx -t` (restores the backup if it
  fails) and reloads. Idempotent. Rollback: copy the backup back, `sudo nginx -t`, `sudo systemctl reload nginx`.
- **Check (on the proxy, with a `vpt_host_session` cookie for the Pi):** fetch the same segment three times through
  `https://127.0.0.1/host/vpt-pi1/stream/capture1/segments/segment_<N>.ts` with `Host: virtualpytest.angelstreet.io`:
  the first is ~80 ms (from the Pi), the next ones ~6 ms (cache). The playlist must still advance every ~0.4-0.5 s.
  Without the cookie the same URL answers 401.
- **Status 2026-10-19:** applied on the proxy VM (backup `~/nginx-backup/virtualpytest.20261019-084542.pre-pi-stream-cache`).
  Measured on vpt-pi1: segment 75 ms first, 7.6 / 6.2 ms after; playlist advancing every 0.5 s; 401 without a session;
  site 200.

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
