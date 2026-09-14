# Backend Host macOS Installation

## Overview
This script installs and configures the VirtualPyTest Backend Host on macOS for device capture and control, including browser automation tools, device detection, and VNC/remote access capabilities using macOS built-in services.

**Architecture**: The installation uses a modular structure with shared utilities across platforms:
- `setup/local/shared/` - Cross-platform logging and device parsing utilities
- `setup/local/macos/backend_host/` - macOS-specific installation scripts
- `backend_host/config/services/mac/` - launchd plist templates

## Prerequisites
- macOS 10.15 (Catalina) or later
- Homebrew package manager (installed automatically if missing)
- Administrator access (sudo) for system installation
- Hardware access for device capture (USB, cameras, etc.)
- Screen Recording and Camera permissions in System Settings

## File Structure
```
setup/local/
├── shared/                      # Cross-platform utilities
│   ├── logging.sh              # Shared logging functions
│   └── parse_devices.sh        # Device parsing from .env
└── macos/backend_host/
    ├── common_vars.sh          # macOS-specific variables + launchd helpers
    ├── install_host_macos.sh   # Main installation script
    └── install_service.sh      # Generic service installer (uses plist templates)

backend_host/
├── scripts/
│   ├── run_ffmpeg_macos.sh     # FFmpeg capture script
│   └── setup_ramdisk_macos.sh  # RAM disk creation script (runs at boot)
└── config/services/mac/
    ├── ramdisk.plist           # Boot-time RAM disk service template
    ├── flask.plist             # Flask API service template
    ├── stream.plist            # FFmpeg stream service template
    └── ...                     # Other service templates
```

## Usage
```bash
# Install host components and services (requires sudo)
sudo ./setup/local/macos/backend_host/install_host_macos.sh

# User-level installation (no sudo, limited features)
./setup/local/macos/backend_host/install_host_macos.sh --user-install

# Uninstall
sudo ./setup/local/macos/backend_host/install_host_macos.sh --uninstall
```

## Installation Steps
The `install_host_macos.sh` script performs these steps:

1. **Check macOS Version**
   - Verifies macOS 10.15+ (Catalina or later)

2. **Fix /tmp Permissions**
   - Ensures /tmp is writable for all users

3. **Create vpt_user Service Account**
   - Creates dedicated service account for running services
   - Services requiring GUI access run as logged-in user

4. **Install Homebrew**
   - Installs Homebrew if not present
   - Updates existing Homebrew installation

5. **Install Dependencies**
   - Python 3 (if not available)
   - wget, FFmpeg via Homebrew

6. **Setup Python Environment**
   - Creates virtual environment at `venv/`
   - Installs backend_host requirements
   - Installs macOS-specific packages (websockify, pyobjc)
   - Installs Playwright browsers

7. **Setup Storage**
   - Parses devices from `.env` file
   - Creates directory structure: `/var/www/html/stream/{device}/{captures,thumbnails,segments,metadata,audio}/{0-23}/`
   - Creates RAM disks (128MB per device) for hot storage
   - Symlinks hot storage at `{device}/hot/`

8. **Setup Environment**
   - Creates `.env` from template if not exists

9. **Setup noVNC**
   - Clones noVNC to `/tmp/noVNC`
   - Installs custom `vnc_lite.html` with auto-path detection for nginx routing
   - Template: `backend_host/config/services/mac/vnc.lite.example`
   - Auto-sets username to current user

10. **Install Services**
    - Installs `ramdisk` service first (creates RAM disks at boot)
    - Uses `install_service.sh` for all services (template-based)
    - Templates from `backend_host/config/services/mac/`

11. **Setup Permissions**
    - Displays required macOS permissions (Screen Recording, Camera, Accessibility)

12. **Test Installation**
    - Verifies Python environment, FFmpeg, services, directories

## Services Installed
All services use the naming convention `com.virtualpytest.{service}`:

| Service | Description | Port | Type |
|---------|-------------|------|------|
| `com.virtualpytest.ramdisk` | RAM Disk Setup (runs at boot) | - | LaunchDaemon |
| `com.virtualpytest.flask` | Flask API Server | 6109 | LaunchDaemon |
| `com.virtualpytest.stream` | FFmpeg Capture Service | - | LaunchDaemon |
| `com.virtualpytest.monitor` | Capture Monitor | - | LaunchDaemon |
| `com.virtualpytest.archiver` | Hot/Cold Archiver | - | LaunchDaemon |
| `com.virtualpytest.transcript` | Audio Transcript | - | LaunchDaemon |
| `com.virtualpytest.vnc` | macOS Screen Sharing | 5900 | LaunchAgent |
| `com.virtualpytest.websockify` | noVNC WebSocket Proxy | 6080 | LaunchDaemon |

**Notes**:
- **ramdisk** runs once at boot to create RAM disks before other services start
- **VNC** runs as LaunchAgent (user context) because it requires GUI access

## Configuration
### Environment File
Settings in `backend_host/src/.env`:
```bash
# Host video configuration (macOS screen capture)
HOST_VIDEO_SOURCE=1:0          # AVFoundation display index
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/host
HOST_VIDEO_FPS=2

# Camera configurations
DEVICE1_VIDEO=0                # Camera device index
DEVICE1_VIDEO_AUDIO=null
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/device1
DEVICE1_VIDEO_FPS=10

# Flask API
HOST_PORT=6109
```

### VNC/noVNC Authentication
macOS Screen Sharing requires username+password authentication.

**Username is auto-set** during installation to your current macOS user. Set your password:

```bash
# Edit /tmp/noVNC/vnc_lite.html and replace 'mac_pwd' with your macOS password:
sed -i '' "s/mac_pwd/YOUR_MACOS_PASSWORD/g" /tmp/noVNC/vnc_lite.html

# Or access via URL with password parameter:
http://localhost:6080/vnc_lite.html?password=YOUR_PASS
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
> 1. Edit `/Library/LaunchDaemons/com.virtualpytest.websockify.plist`
> 2. Add `<string>--cert=/usr/local/etc/ssl/certs/websockify.pem</string>` to the ProgramArguments array
> 3. Generate certificate: `sudo openssl req -x509 -newkey rsa:2048 -keyout /usr/local/etc/ssl/certs/websockify.pem -out /usr/local/etc/ssl/certs/websockify.pem -days 365 -nodes -subj "/CN=localhost"`
> 4. Reload: `sudo launchctl unload /Library/LaunchDaemons/com.virtualpytest.websockify.plist && sudo launchctl load /Library/LaunchDaemons/com.virtualpytest.websockify.plist`

## Access Points
| Service | URL/Address |
|---------|-------------|
| Flask API | `http://localhost:6109` |
| VNC Desktop | `vnc://localhost:5900` (macOS credentials) |
| noVNC Web (direct) | `http://localhost:6080/vnc_lite.html` |
| noVNC Web (via nginx) | `https://your-server/host/{hostname}/vnc_lite.html` |

## Ports Used
| Port | Service | Protocol |
|------|---------|----------|
| 5900 | macOS Screen Sharing | TCP |
| 6080 | noVNC/WebSockify | TCP |
| 6109 | Flask API | TCP |

## Required Permissions
Grant these in **System Settings > Privacy & Security**:

| Permission | Required For |
|------------|--------------|
| Screen Recording | Desktop/screen capture |
| Camera | Camera access |
| Accessibility | Desktop automation (optional) |

## Service Management
```bash
# List all VirtualPyTest services
launchctl list | grep virtualpytest

# Check service status
launchctl list com.virtualpytest.ramdisk
launchctl list com.virtualpytest.flask
launchctl list com.virtualpytest.stream
launchctl list com.virtualpytest.vnc

# Start/Stop services
launchctl start com.virtualpytest.flask
launchctl stop com.virtualpytest.stream

# Restart service
launchctl kickstart -k system/com.virtualpytest.flask

# Manually trigger RAM disk creation (runs once, not a long-running service)
sudo launchctl kickstart system/com.virtualpytest.ramdisk

# View logs
tail -f /usr/local/virtualpytest/logs/flask.log
tail -f /usr/local/virtualpytest/logs/stream.log
tail -f /usr/local/virtualpytest/logs/ramdisk.log

# Reload service after plist changes
sudo launchctl unload /Library/LaunchDaemons/com.virtualpytest.flask.plist
sudo launchctl load /Library/LaunchDaemons/com.virtualpytest.flask.plist
```

## Device Detection
```bash
# List available AVFoundation devices (cameras, screens)
ffmpeg -f avfoundation -list_devices true -i ""

# List cameras
system_profiler SPCameraDataType

# List USB devices
system_profiler SPUSBDataType

# List audio devices
system_profiler SPAudioDataType

# Test screen capture
ffmpeg -f avfoundation -i "1:0" -frames:v 1 test.jpg

# Test camera capture
ffmpeg -f avfoundation -pixel_format uyvy422 -i "0:none" -frames:v 1 test.jpg
```

## Storage Architecture
- **Hot storage**: RAM disk per device (128MB each)
  - Mounted at `/Volumes/VirtualPyTest_{device}_Hot`
  - Symlinked to `/var/www/html/stream/{device}/hot/`
- **Cold storage**: Local SSD at `/var/www/html/stream/{device}/`
- **Dynamic allocation**: RAM disks only created for devices in `.env`
- **Automatic cleanup**: Unused RAM disks removed on reinstall

### RAM Disk Boot Persistence (macOS vs Linux)

| Platform | RAM Disk Mechanism | Boot Behavior |
|----------|-------------------|---------------|
| **Linux** | `tmpfs` in `/etc/fstab` | Kernel auto-creates at boot |
| **macOS** | `hdiutil attach ram://` | Must be recreated each boot |

**macOS RAM disks are volatile** - they exist only in RAM and are cleared on every reboot. Unlike Linux where `/etc/fstab` with `tmpfs` entries are automatically mounted by the kernel, macOS requires explicit recreation using `hdiutil`.

The `com.virtualpytest.ramdisk` launchd service handles this:
1. Runs **once at boot** (before other VirtualPyTest services)
2. Reads device configuration from `.env`
3. Creates RAM disk for each device using `hdiutil attach -nomount ram://`
4. Formats as HFS+ and mounts at `/Volumes/VirtualPyTest_{device}_Hot`
5. Creates directory structure (segments, captures, thumbnails, metadata)
6. Creates symlink from `{device}/hot/` to the RAM disk

**Data in hot storage is always lost on reboot** - this is by design. The archiver service moves important data to cold storage.

## Troubleshooting

### Service Won't Start
```bash
# Check service status
launchctl list com.virtualpytest.flask

# Check logs
tail -f /usr/local/virtualpytest/logs/flask_error.log

# Check if port is in use
lsof -i :6109

# Verify Python environment
source venv/bin/activate
python -c "import flask"
```

### VNC Issues
```bash
# Check if Screen Sharing is enabled
sudo systemsetup -getremotelogin

# Enable Screen Sharing
sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart -activate -configure -access -on -users $USER -privs -all -restart -agent

# Test local VNC
open vnc://localhost:5900
```

### noVNC Issues
```bash
# Check noVNC files
ls -la /tmp/noVNC/vnc_lite.html

# Test WebSockify
curl -I http://localhost:6080/vnc_lite.html

# Check websockify process
ps aux | grep websockify
```

### Permission Issues
```bash
# Reset Screen Recording permissions
tccutil reset ScreenCapture

# Reset Camera permissions
tccutil reset Camera

# Force camera permission prompt
ffmpeg -f avfoundation -video_device_index 0 -i "" -t 1 -f null -
```

### RAM Disk Issues
```bash
# Check if RAM disk is mounted
mount | grep VirtualPyTest

# Check hot storage symlink
ls -la /var/www/html/stream/*/hot

# Verify symlink target exists
readlink /var/www/html/stream/capture2/hot

# Manually run RAM disk setup (if ramdisk service not running)
sudo /path/to/virtualpytest/backend_host/scripts/setup_ramdisk_macos.sh

# Manually create RAM disk (128MB)
RAM_DEVICE=$(hdiutil attach -nomount ram://$((128 * 1024 * 1024 / 512)))
diskutil eraseVolume HFS+ "VirtualPyTest_device1_Hot" $RAM_DEVICE

# Fix broken symlink (if RAM disk exists but symlink is wrong)
sudo rm /var/www/html/stream/device1/hot
sudo ln -sf /Volumes/VirtualPyTest_device1_Hot /var/www/html/stream/device1/hot

# List all disk devices
diskutil list

# Check ramdisk service status
launchctl list com.virtualpytest.ramdisk

# View ramdisk service logs
tail -f /usr/local/virtualpytest/logs/ramdisk.log
```

## Comparison with Linux
| Feature | macOS | Linux |
|---------|-------|-------|
| Service Manager | launchd (plist) | systemd (unit files) |
| VNC Server | macOS Screen Sharing | TigerVNC |
| Video Capture | AVFoundation | V4L2 |
| RAM Disk | hdiutil + HFS+ | tmpfs |
| RAM Disk Boot | launchd service recreates | /etc/fstab (kernel mounts) |
| Service Templates | `config/services/mac/` | `config/services/linux/` |
| Main Script | `install_host_macos.sh` | `install_host.sh` |

Both platforms share:
- `setup/local/shared/logging.sh` - Logging functions
- `setup/local/shared/parse_devices.sh` - Device parsing
- Same directory structure (`/var/www/html/stream/`)
- Same `.env` configuration format
- Same API port (6109)

## Next Steps
1. Edit `backend_host/src/.env` to configure your devices
2. Grant required permissions in System Settings
3. Set VNC password in `/tmp/noVNC/vnc_lite.html` (replace `mac_pwd` with your macOS password)
4. Test noVNC locally: `http://localhost:6080/vnc_lite.html`
5. Test noVNC via nginx: `https://your-server/host/{hostname}/vnc_lite.html`
6. Test API: `curl http://localhost:6109/health`
7. Verify device detection: `ffmpeg -f avfoundation -list_devices true -i ""`
