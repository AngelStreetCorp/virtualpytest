# Backend Host Linux Installation

## Overview
This script installs and configures the VirtualPyTest Backend Host on Linux for device capture and control, including browser automation tools, device detection, and VNC/remote access capabilities.

**Architecture**: The installation uses a modular structure with shared utilities across platforms:
- `setup/local/shared/` - Cross-platform logging and device parsing utilities
- `setup/local/linux/backend_host/` - Linux-specific installation scripts
- `backend_host/config/services/linux/` - systemd service templates

## Prerequisites
- Debian/Ubuntu Linux (tested on Raspberry Pi OS, Ubuntu 22.04+, Debian 13)
- sudo access for system service configuration
- Hardware access for device capture (USB, cameras, IR blasters, etc.)
- Firewall configuration handled at Proxmox level (if using VMs) — see **Firewall / Egress Requirements** below

## Firewall / Egress Requirements

The installer pulls packages from several external hosts. On VMs behind a restrictive egress firewall, allow outbound **TCP 443** (HTTPS) and **TCP 80** (HTTP, for some apt mirrors) to the hosts below. If any are blocked, the listed step will fail or stall — most are now non-fatal in the installer (it logs a warning and continues), but the corresponding feature won't work until the host is reachable.

### Required (installer will not complete cleanly without these)

| Host | Purpose | Step that fails if blocked |
|---|---|---|
| `deb.debian.org` (or your configured mirror, e.g. `debian.ethz.ch`) | Debian base packages: ffmpeg, tesseract, xfce4, novnc, lirc, tigervnc, … | STEP 2 — `apt-get install` (HARD FAIL) |
| `security.debian.org` | Debian security updates | STEP 2 — `apt-get update` (warning if missing) |
| `pypi.org` | Python package index metadata | STEP 3 — `pip install -r requirements.txt` (HARD FAIL) |
| `files.pythonhosted.org` | Python wheel/tarball downloads (PyPI's CDN) | STEP 3 — `pip install …` (HARD FAIL — pip metadata resolves on `pypi.org` then fetches actual files here) |

### Optional (failure is non-fatal — installer continues with `⚠️` warning)

| Host | Purpose | What you lose |
|---|---|---|
| `packagecloud.io` + `*.packagecloud.io` | Ookla Speedtest CLI apt repo. The actual `.deb` is served from a Fastly/S3 CDN domain fronted by packagecloud — if your firewall does strict per-FQDN allowlisting and `.deb` downloads fail after the repo file is added, allow `*.packagecloud.io` (wildcard) too. | Network speed-test feature uses a fallback; manual install possible later via [install.speedtest.net](https://www.speedtest.net/apps/cli) |
| `install.speedtest.net` | Manual speedtest tarball mirror (workaround for blocked packagecloud) | Manual install path also blocked |
| `playwright.azureedge.net` | Playwright browser binary downloads | Headless browser automation broken until binaries fetched manually |
| `cdn.playwright.dev` | Playwright fallback CDN | Same as above |
| `github.com` + `objects.githubusercontent.com` | Patched `bluetoothd` source, BLE remote service files | BLE remote control may not work; can be installed manually later |

### How to validate egress from a fresh VM

Run this before `install_host.sh` to confirm every required host is reachable:

```bash
for host in deb.debian.org security.debian.org pypi.org files.pythonhosted.org \
            packagecloud.io install.speedtest.net playwright.azureedge.net; do
    printf '%-50s ' "$host"
    if curl -fsSI -4 --connect-timeout 5 "https://$host/" >/dev/null 2>&1; then
        echo "✅ reachable"
    else
        echo "❌ blocked or unreachable"
    fi
done
```

Required-tier failures must be fixed before installing; optional-tier failures will produce `⚠️` warnings during install and degraded (but not broken) functionality after.

### Notes on specific failures we've hit

- **`packagecloud.io` blocked** — symptom: `📥 Adding Ookla packagecloud repo (20s connect cap)...` followed by `⚠️ Packagecloud repo script failed (rc=124)`. The `rc=124` is `timeout(1)` killing the curl wrapper after 30s. Speedtest CLI is skipped, install continues.
- **`pypi.org` or `files.pythonhosted.org` blocked** — symptom: STEP 3 hangs on `pip install` then aborts with `ReadTimeoutError` or `ConnectionError`. This IS fatal; the host service can't start without its Python deps. Fix the firewall or run pip behind a proxy (`pip install --proxy http://corp-proxy:8080 …`).
- **IPv6 enabled but no IPv6 route** — symptom: every curl says `Network is unreachable` for the IPv6 attempt, then retries IPv4. Not fatal, but adds latency. Either disable IPv6 on the VM (`sysctl -w net.ipv6.conf.all.disable_ipv6=1`) or fix the IPv6 route.

## File Structure
```
setup/local/
├── shared/                      # Cross-platform utilities
│   ├── logging.sh              # Shared logging functions
│   └── parse_devices.sh        # Device parsing from .env
└── linux/backend_host/
    ├── common_vars.sh          # Linux-specific variables
    ├── install_host.sh         # Main installation script
    ├── install_service.sh      # Generic service installer
    ├── install_requirements.sh # System dependencies
    └── launch_host.sh          # Manual launch script
```

## Usage
```bash
# Install everything (dependencies + services) in one command
./setup/local/linux/backend_host/install_host.sh [DATA_DIR]

# DATA_DIR: Optional path for host data storage (default: /var/www/html/stream)
#          If specified, creates symlink from /var/www/html/stream to custom location

# Examples:
./setup/local/linux/backend_host/install_host.sh                    # Default location
./setup/local/linux/backend_host/install_host.sh /data/stream      # Custom location

# Or install individual components:
./setup/local/linux/backend_host/install_requirements.sh  # System deps only
./setup/local/linux/backend_host/install_service.sh vpt-host # Single service
```

## Installation Steps
The `install_host.sh` script performs these steps:

1. **Create vpt_user Service Account**
   - Creates dedicated service account for running services
   - Follows security best practices (minimal privileges)

2. **Install System Dependencies**
   - Python 3, pip, venv, dev tools
   - Chromium, Firefox ESR (for browser automation)
   - LIRC (IR remote control), v4l-utils
   - TigerVNC (server + tools), noVNC, websockify
   - XFCE4 desktop environment, BlueZ (`bluetoothd` / `bluetooth.service`)
   - dbus-x11 (required for XFCE4 session)
   - python3-dbus (required by BLE HID remote services launched via system Python)
   - locales package (en_US.UTF-8)

3. **Setup Python Environment**
   - Creates virtual environment at `venv/`
   - Installs backend_host requirements
   - Installs Playwright browsers

4. **Configure LIRC**
   - Sets up IR remote control support
   - Configures `/etc/lirc/lirc_options.conf`

5. **Setup Environment**
   - Creates `.env` from template if not exists at `backend_host/src/.env`

6. **Setup Storage**
   - Creates RAM hot storage (tmpfs) for high-speed capture
   - Creates cold storage directories with hourly folders
   - Directory structure: `{DATA_DIR}/{device}/{captures,thumbnails,segments,metadata}/{0-23}/`
   - If custom DATA_DIR specified, creates symlink: `/var/www/html/stream → {DATA_DIR}`

7. **Install Services**
   - Uses `install_service.sh` for all services (template-based)
   - Templates from `backend_host/config/services/linux/`

8. **Configure VNC**
   - Sets up TigerVNC with XFCE4 desktop
   - Default password: `admin1234`
   - Installs custom `vnc_lite.html` with auto-path detection for nginx routing
   - Template: `backend_host/config/services/linux/vnc.lite.example`

9. **Configure Permissions**
   - Sets up sudo permissions for service management
   - Configures FFmpeg process control

10. **Configure XFCE4**
    - Sets up `.xinitrc` for desktop session

11. **Configure PulseAudio for VNC Audio**
    - Installs PulseAudio, pulseaudio-utils, and pavucontrol (for audio control GUI)
    - Configures PulseAudio to accept anonymous TCP connections (port 4713)
    - Adds `PULSE_SERVER` environment variable to VNC xstartup for audio forwarding
    - VNC clients can stream audio through PulseAudio server

## Services Installed
All services use the naming convention `vpt-{service}.service`:

| Service | Description | Port |
|---------|-------------|------|
| `vpt-host.service` | Host API Server | 6109 |
| `vpt-stream.service` | FFmpeg Capture Service | - |
| `vpt-monitor.service` | Capture Monitor | - |
| `vpt-archiver.service` | Hot/Cold Archiver | - |
| `vpt-transcript.service` | Audio Transcript | - |
| `vpt-vnc.service` | TigerVNC Server | 5901 |
| `vpt-websockify.service` | noVNC WebSocket Proxy | 6080 |

## Configuration

### Data Directory
The host data directory can be customized during installation:

- **Default**: `/var/www/html/stream` (no symlink created)
- **Custom**: Any path (e.g., `/data/stream`, `/mnt/host-data`)
- **Environment Variable**: `VIRTUALPYTEST_INSTALL_PATH` is set for scripts that support it

**Benefits of Custom Data Directory:**
- Store data on dedicated disks/partitions
- Better performance with SSD/RAID storage
- Easier backup and maintenance
- Separation of OS and data

### Environment File
Each Backend Host gets settings in `backend_host/src/.env`:
```bash
# Host video configuration
HOST_VIDEO_SOURCE=/dev/video0
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/host
HOST_VIDEO_FPS=2

# Device configurations
DEVICE1_VIDEO=/dev/video1
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/device1
DEVICE1_VIDEO_FPS=10

# Flask API
HOST_PORT=6109
```

## Websockify Configuration

**Default**: Websockify runs **without SSL** - nginx handles SSL termination and proxies to websockify over plain HTTP/WebSocket.

- Access via nginx: `https://your-server/host/{hostname}/vnc_lite.html`
- Direct local access: `http://localhost:6080/vnc_lite.html`

### vnc_lite.html Auto-Path Detection
The custom `vnc_lite.html` automatically detects the correct WebSocket path based on its URL location:
- Page at `/host/myhost/vnc_lite.html` → WebSocket connects to `/host/myhost/websockify`
- No manual `?path=` parameter needed

> **💡 Optional SSL**: To enable SSL directly on websockify (for direct access without nginx):
> 1. Edit `/etc/systemd/system/vpt-websockify.service`
> 2. Add `--cert=/etc/ssl/certs/websockify.pem` to the `ExecStart` line
> 3. Generate certificate: `sudo openssl req -x509 -newkey rsa:2048 -keyout /etc/ssl/certs/websockify.pem -out /etc/ssl/certs/websockify.pem -days 365 -nodes -subj "/CN=localhost"`
> 4. Reload: `sudo systemctl daemon-reload && sudo systemctl restart vpt-websockify`

## Access Points
| Service | URL/Address |
|---------|-------------|
| Flask API | `http://localhost:6109` |
| VNC Desktop | `vnc://localhost:5901` (password: admin1234) |
| noVNC Web (direct) | `http://localhost:6080/vnc_lite.html` |
| noVNC Web (via nginx) | `https://your-server/host/{hostname}/vnc_lite.html` |

## Ports Used
| Port | Service | Protocol |
|------|---------|----------|
| 5901 | TigerVNC Server | TCP |
| 6080 | noVNC/WebSockify | TCP |
| 6109 | Flask API | TCP |

## Service Management
```bash
# List all VirtualPyTest services
sudo systemctl list-units --type=service | grep virtualpytest

# Check service status
sudo systemctl status vpt-host
sudo systemctl status vpt-stream
sudo systemctl status vpt-vnc

# Start/Stop/Restart services
sudo systemctl start vpt-host
sudo systemctl stop vpt-stream
sudo systemctl restart vpt-vnc

# Enable/Disable auto-start
sudo systemctl enable vpt-host
sudo systemctl disable vpt-stream

# View service logs
sudo journalctl -u vpt-host -f
tail -f /tmp/ffmpeg_service.log

# Start all services
sudo systemctl start vpt-{host,stream,monitor,archiver,transcript}

# Stop all services
sudo systemctl stop vpt-{host,stream,monitor,archiver,transcript}
```

## Device Detection
```bash
# List USB devices
lsusb

# List video devices
v4l2-ctl --list-devices

# List audio devices
arecord -l

# Test video capture
ffmpeg -f v4l2 -list_formats all -i /dev/video0
```

## Manual Launch (Development)
```bash
# Launch without systemd services
./setup/local/linux/backend_host/launch_host.sh
```

## Troubleshooting

### Service Won't Start
```bash
# Check service status and logs
sudo systemctl status vpt-host
sudo journalctl -u vpt-host -n 50

# Check if port is in use
sudo lsof -i :6109

# Verify Python environment
source venv/bin/activate
python -c "import flask"
```

### VNC Issues
```bash
# Check VNC process
ps aux | grep Xvnc

# Kill stale VNC sessions
tigervncserver -kill :1

# Clean up lock files
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# Restart VNC service
sudo systemctl restart vpt-vnc
```

### Video Capture Issues
```bash
# Check device permissions
ls -la /dev/video*

# Add user to video group
sudo usermod -aG video vpt_user

# Test capture
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 test.jpg
```

## Next Steps
1. Edit `backend_host/src/.env` to configure your devices
2. Test VNC connectivity: `vncviewer localhost:5901` (password: admin1234)
3. Test noVNC web locally: `http://localhost:6080/vnc_lite.html`
4. Test noVNC via nginx: `https://your-server/host/{hostname}/vnc_lite.html`
5. Verify device detection with `v4l2-ctl --list-devices`
6. Test API: `curl http://localhost:6109/health`

## Firewall / Egress Requirements

The VM needs outbound internet to install. Please open **outbound TCP 443** (HTTPS) to the hostnames below. No incoming ports need to be opened.

```
deb.debian.org
security.debian.org
pypi.org
files.pythonhosted.org
```

- The first two = Debian operating-system packages.
- The last two = Python libraries (the app is written in Python).

```
packagecloud.io
d3fo0g5hm7lbuv.cloudfront.net
playwright.azureedge.net
cdn.playwright.dev
github.com
objects.githubusercontent.com
raw.githubusercontent.com
codeload.github.com
```

- `packagecloud.io` + `d3fo0g5hm7lbuv.cloudfront.net` = Speedtest CLI. The `.io` host returns the install script and repo metadata; the CloudFront host serves the GPG key and `.deb` package downloads via 302 redirect. Both must be reachable, or the GPG key ends up 0 bytes and `apt-get install speedtest` returns "Unable to locate package".
- `playwright.*` = headless browser used for web tests.
- `github.com` = Bluetooth remote-control patches.
