# Grafana Image Renderer Setup

Enables Grafana to render dashboards and panels as PNG images (used for alerts, reports, sharing via the "Export as image" feature).

## Prerequisites

- Grafana running (systemd `grafana-server.service`) on the monitoring VM
- Docker installed on the monitoring VM (`apt-get install docker.io`)
- Port 8081 available on the monitoring VM
- Grafana `domain` and `root_url` must point to the external proxy URL (not `localhost`) — otherwise the browser fetches render images from `http://localhost:3000` which fails

## Install

### 1. Install Docker (if not already installed)

```bash
sudo apt-get update && sudo apt-get install -y docker.io
sudo systemctl enable docker && sudo systemctl start docker
```

### 2. Pull and run the renderer container

```bash
sudo docker run -d \
  --name=grafana-image-renderer \
  --restart=unless-stopped \
  --network=host \
  -e HTTP_PORT=8081 \
  -e ENABLE_METRICS=true \
  -e LOG_LEVEL=info \
  -e AUTH_TOKEN=<token> \
  grafana/grafana-image-renderer:latest
```

- `--network=host` — Grafana runs as a systemd service (not Docker), so the renderer needs direct access to `localhost:3000`
- `AUTH_TOKEN=<token>` — must match `renderer_token` in grafana.ini (the Go-based renderer enforces auth token matching; without this, render requests return 401). Use a random value, e.g. `openssl rand -hex 16`: Grafana 11+ refuses to start with the default `-`.

### 3. Remove old local plugin (if present)

If a local `grafana-image-renderer` plugin was previously installed, it will conflict with the remote renderer and produce signature validation errors in logs:

```bash
# Check for old plugin
ls /var/lib/grafana/plugins/grafana-image-renderer

# Remove if present
sudo rm -rf /var/lib/grafana/plugins/grafana-image-renderer
```

### 4. Configure Grafana

In `/etc/grafana/grafana.ini` (source: `infra/monitoring/grafana/config/grafana.ini`):

**[server] section** — set external domain (required for render URLs):
```ini
[server]
domain = virtualpytest.angelstreet.io
root_url = https://%(domain)s/grafana/
serve_from_sub_path = true
```

If `domain = localhost`, Grafana generates render URLs like `http://localhost:3000/grafana/render/...` which the browser can't reach. The domain must match the external proxy URL.

**[rendering] section** — enable the remote renderer:
```ini
[rendering]
server_url = http://localhost:8081/render
callback_url = http://localhost:3000/
renderer_token = <same token as AUTH_TOKEN>
concurrent_render_request_limit = 10
```

- `server_url` — where Grafana sends render requests (the Docker container)
- `callback_url` — where the renderer calls back to fetch dashboard data (stays `localhost` since renderer is on the same VM). Must match `root_url`: add `/grafana/` only when Grafana is served under that sub-path behind a reverse proxy
- `renderer_token` — must match the `AUTH_TOKEN` env var on the container (a random value, never the default `-`)
- `concurrent_render_request_limit` — set to 10 (lower than default 30) to avoid overloading the VM

### 5. Configure Nginx reverse proxy

The proxy VM needs a dedicated location block for `/grafana/render/` with extended timeouts and relaxed CORS headers. Without this, the browser's `fetch()` fails due to `Cross-Origin-Resource-Policy: same-origin` set globally.

Add this **before** the existing `location /grafana/` block in `/etc/nginx/sites-enabled/virtualpytest`:

```nginx
location /grafana/render/ {
    # Override security headers that block Grafana JS fetch for rendered images
    proxy_hide_header Cross-Origin-Resource-Policy;
    proxy_hide_header Cross-Origin-Opener-Policy;
    add_header Cross-Origin-Resource-Policy "cross-origin" always;
    proxy_pass http://grafana/grafana/render/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Script-Name /grafana;
    proxy_redirect off;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
    proxy_buffering off;
}
```

Then test and reload:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 6. Restart Grafana

```bash
sudo systemctl restart grafana-server
```

## Verify

```bash
# Check renderer container is running and healthy
sudo docker ps --filter name=grafana-image-renderer

# Check renderer health endpoint
curl -s http://localhost:8081

# Test render locally (should return a PNG)
curl -s -o /tmp/render_test.png \
  'http://localhost:3000/grafana/render/d-solo/<dashboard-uid>?orgId=1&panelId=1&width=800&height=400' \
  -u "admin:$GRAFANA_ADMIN_PASSWORD"
file /tmp/render_test.png  # Should say "PNG image data"

# Check Grafana logs for rendering errors
sudo journalctl -u grafana-server -n 50 --no-pager | grep -i render
```

In the Grafana UI: open any dashboard > Share > Export as image > Generate image > Download image.

## Manage

```bash
# View renderer logs
sudo docker logs grafana-image-renderer

# Restart renderer
sudo docker restart grafana-image-renderer

# Update renderer
sudo docker pull grafana/grafana-image-renderer:latest
sudo docker stop grafana-image-renderer && sudo docker rm grafana-image-renderer
# Then re-run the docker run command from step 2
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Renderer returns 401 | `AUTH_TOKEN` / `renderer_token` mismatch | Set both to the same random token |
| Browser shows "Failed to fetch" | `domain = localhost` in grafana.ini | Set `domain` to external proxy hostname |
| Browser shows "Failed to fetch" | `Cross-Origin-Resource-Policy: same-origin` header | Add dedicated Nginx render location block (step 5) |
| Plugin signature validation error in logs | Old local `grafana-image-renderer` plugin installed | Remove from `/var/lib/grafana/plugins/` (step 3) |
| Render timeout | VM resources too low or Nginx timeout too short | Increase `proxy_read_timeout` in Nginx, or increase VM CPU/RAM |

## Resource Notes

Grafana docs recommend 16GB RAM + 4 CPU cores for the renderer under heavy load. The monitoring VM can run it with less for occasional rendering but may be slow under concurrent requests. The `concurrent_render_request_limit = 10` setting helps prevent overload. Increase VM resources if rendering is frequently used.
