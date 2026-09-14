# VirtualPyTest macOS Installation Guide

macOS runs the **host role only** (a device controller with its own screen/camera capture,
joining a server that runs on Linux or in Docker). The server, frontend and database are not
offered natively on macOS — use Docker Desktop (`docs/get-started/docker.md`). Overview:
`docs/get-started/local-dev.md#macos`.

## Prerequisites

### System Requirements
- macOS 10.15 (Catalina) or later (11.0 Big Sur recommended)
- At least 8GB RAM (16GB recommended for RAM disk)
- 20GB free disk space
- Administrator privileges (for some setup steps)
- Internet connection for downloading dependencies

### Required Permissions
VirtualPyTest on macOS requires these system permissions:
- **Screen Recording** (for screen capture)
- **Camera** (for camera access)
- **Accessibility** (for UI automation, optional)

## Installation

### 1. Prepare Your System

1. **Open Terminal**
   ```bash
   # Terminal is in Applications > Utilities > Terminal
   ```

2. **Navigate to Project Directory**
   ```bash
   cd /path/to/virtualpytest
   ```

3. **Run Installation Script**
   ```bash
   # Basic installation with VNC
   ./setup/local/macos/backend_host/install_host_macos.sh

   # Installation without VNC
   ./setup/local/macos/backend_host/install_host_macos.sh --no-vnc
   ```

### 2. Grant System Permissions

After installation, you must grant permissions in System Settings:

1. **Screen Recording Permission**:
   - Go to **System Settings** → **Privacy & Security** → **Screen Recording**
   - Check the box for **Terminal** (or your preferred terminal app)
   - You may need to restart Terminal

2. **Camera Permission**:
   - Go to **System Settings** → **Privacy & Security** → **Camera**
   - Check the box for **Terminal** (or your preferred terminal app)

3. **Allow Launch Agents**:
   - Go to **System Settings** → **General** → **Login Items & Extensions**
   - Allow the VirtualPyTest launchd services

### 3. Configure Environment

Edit the generated `.env` file — it must carry `SERVER_URL`, `API_KEY` and the Supabase /
storage values of the server this host joins (`backend_host/src/.env.example` documents them):
```bash
nano backend_host/src/.env
```

## Configuration

### Environment Variables

The installer creates macOS launchd environment variables:
- `VIRTUALPYTEST_ROOT` - Project root directory
- `VIRTUALPYTEST_HOST` - Backend host directory
- `VIRTUALPYTEST_LOGS` - Log files directory
- `PYTHONPATH` - Python module paths
- `DISPLAY` - X11 display number
- `LC_CTYPE=UTF-8` - UTF-8 character encoding

### Device Configuration

Configure video capture devices in `backend_host/src/.env`:

```bash
# Host screen capture (macOS)
HOST_VIDEO_SOURCE=1:0
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=/usr/local/virtualpytest/cold/host
HOST_VIDEO_FPS=2

# Camera capture (macOS device index)
DEVICE1_VIDEO=0
DEVICE1_VIDEO_AUDIO=null
DEVICE1_VIDEO_CAPTURE_PATH=/usr/local/virtualpytest/cold/device1
DEVICE1_VIDEO_FPS=10

# Second camera
DEVICE2_VIDEO=1
DEVICE2_VIDEO_AUDIO=null
DEVICE2_VIDEO_CAPTURE_PATH=/usr/local/virtualpytest/cold/device2
DEVICE1_VIDEO_FPS=15
```

### Finding Camera Device Indices

To find available cameras on macOS:

```bash
# List all cameras with system_profiler
system_profiler SPCameraDataType

# Example output:
# FaceTime HD Camera:
#   Model: FaceTime HD Camera
#   Unique ID: 8C3D6F8E-9E3D-4F1D-8F3E-2D4E5F6A7B8C
#
# USB Camera:
#   Model: Logitech Webcam C920
#   Unique ID: 1A2B3C4D-5E6F-7A8B-9C0D-1E2F3A4B5C6D

# Camera indices start from 0
# FaceTime HD Camera = index 0
# USB Camera = index 1
```

## Services Overview

The installation creates macOS launchd services in `~/Library/LaunchAgents/`:

| Service Label | Description | Port |
|---------------|-------------|------|
| `com.virtualpytest.flask` | REST API server | 6109 |
| `com.virtualpytest.stream` | FFmpeg video capture | N/A |
| `com.virtualpytest.monitor` | Capture monitoring | N/A |
| `com.virtualpytest.archiver` | Hot/cold storage archiver | N/A |
| `com.virtualpytest.transcript` | Audio transcription | N/A |
| `com.virtualpytest.vnc` | Built-in VNC server | 5900 |
| `com.virtualpytest.websockify` | WebSocket proxy for VNC | 6080 |

## Service Management

### Using launchctl

```bash
# List VirtualPyTest services
launchctl list | grep virtualpytest

# Start a service
launchctl start com.virtualpytest.flask

# Stop a service
launchctl stop com.virtualpytest.flask

# View service logs
tail -f /usr/local/virtualpytest/logs/flask.log

# Unload a service
launchctl unload ~/Library/LaunchAgents/com.virtualpytest.flask.plist

# Reload a service (after editing plist)
launchctl unload ~/Library/LaunchAgents/com.virtualpytest.flask.plist
launchctl load ~/Library/LaunchAgents/com.virtualpytest.flask.plist
```

### Using Activity Monitor

1. Open **Activity Monitor** (Applications → Utilities)
2. Search for "python" or "ffmpeg"
3. Select process and click X to quit

### Service Startup

Services are configured to start automatically on login. To manage:

```bash
# Disable auto-start for a service
launchctl unload -w ~/Library/LaunchAgents/com.virtualpytest.stream.plist

# Re-enable auto-start
launchctl load -w ~/Library/LaunchAgents/com.virtualpytest.stream.plist
```

## Storage Architecture

### Directory Structure

```
/usr/local/virtualpytest/
├── cold/           # Persistent storage (disk)
│   ├── host/       # Host device captures
│   │   ├── captures/
│   │   ├── thumbnails/
│   │   ├── segments/
│   │   ├── metadata/
│   │   └── audio/
│   └── device1/    # Device captures
└── logs/           # Log files
    ├── flask.log
    ├── stream.log
    └── *.log
```

### RAM Disk (Optional)

macOS supports RAM disk for hot storage:

- **Location**: `/Volumes/VirtualPyTest_Hot/`
- **Size**: 512MB (configurable in script)
- **Purpose**: Reduces SSD writes by 99%
- **Created**: Automatically by installation script

## Access Points

After installation, VirtualPyTest is accessible at:

- **REST API**: http://localhost:6109
- **Built-in VNC**: vnc://localhost:5900
- **noVNC Web Interface**: http://localhost:6080
- **nginx Web Server**: http://localhost (if configured)

## Logging

### Log Locations

- **Installation**: `/usr/local/virtualpytest/logs/install.log`
- **FFmpeg**: `/usr/local/virtualpytest/logs/stream.log`
- **Services**: `/usr/local/virtualpytest/logs/*.log`
- **System**: Console.app (Applications → Utilities → Console)

### Viewing Logs

```bash
# View all service logs
tail -f /usr/local/virtualpytest/logs/*.log

# View specific service log
tail -f /usr/local/virtualpytest/logs/flask.log

# View FFmpeg logs
tail -f /usr/local/virtualpytest/logs/stream.log

# View system logs for VirtualPyTest
log show --predicate 'process == "python" OR process == "ffmpeg"' --last 1h
```

## Troubleshooting

### Common Issues

#### 1. Services Won't Start

```bash
# Check service status
launchctl list com.virtualpytest.flask

# Check service plist syntax
plutil ~/Library/LaunchAgents/com.virtualpytest.flask.plist

# View service logs
tail -f /usr/local/virtualpytest/logs/flask.log
```

#### 2. FFmpeg Capture Fails

```bash
# Test camera access
ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | head -20

# Test screen capture
ffmpeg -f avfoundation -list_devices true -i "1" 2>&1 | head -20

# Check permissions
system_profiler SPCameraDataType
```

#### 3. Permission Issues

**Screen Recording Permission**:
```bash
# Check if screen recording is enabled
tccutil query ScreenCapture
# Reset permissions if needed
tccutil reset ScreenCapture
```

**Camera Permission**:
```bash
# Check camera permissions
tccutil query Camera
# Reset if needed
tccutil reset Camera
```

#### 4. RAM Disk Issues

```bash
# Check if RAM disk exists
df -h | grep VirtualPyTest

# Remount RAM disk
sudo umount /Volumes/VirtualPyTest_Hot 2>/dev/null || true
RAM_SECTORS=$((512 * 1024 * 1024 / 512))
RAM_DEVICE=$(hdiutil attach -nomount ram://$RAM_SECTORS)
newfs_hfs -v "VirtualPyTest_Hot" $RAM_DEVICE
mkdir -p /Volumes/VirtualPyTest_Hot
mount -t hfs $RAM_DEVICE /Volumes/VirtualPyTest_Hot
```

### Performance Tuning

#### FFmpeg Optimization

Edit `backend_host/scripts/run_ffmpeg_macos.sh`:

```bash
# Adjust quality settings
quality="hd"  # Options: low, sd, hd

# Adjust FPS
input_fps=5   # Lower = less CPU usage

# Adjust buffer sizes
hls_time=2    # Shorter segments for lower latency
```

#### RAM Disk Size

Modify RAM disk size in the installation script:
```bash
# Change this line in install_host_macos.sh
RAM_DISK_SIZE_MB=1024  # 1GB instead of 512MB
```

### System Resources

Monitor resource usage:

```bash
# CPU and memory usage
top -pid $(pgrep -f "ffmpeg\|python")

# Disk I/O
iostat -w 5

# Network usage
nettop -p $(pgrep -f "python")
```

## Advanced Configuration

### Custom Service Configuration

Edit launchd plist files in `~/Library/LaunchAgents/`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.virtualpytest.flask</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/project/venv/bin/python</string>
        <string>/path/to/project/backend_host/src/app.py</string>
    </array>
    <!-- Add custom environment variables -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>CUSTOM_VAR</key>
        <string>custom_value</string>
    </dict>
</dict>
</plist>
```

### Multiple Displays

For multi-display setups:

```bash
# List available displays
ffmpeg -f avfoundation -list_devices true -i "1" 2>&1

# Configure in .env
HOST_VIDEO_SOURCE=1:0    # Display 1, Screen 0
DEVICE1_VIDEO=1:1       # Display 1, Screen 1
```

### Network Configuration

For remote access:

1. **Configure Firewall**:
   ```bash
   # Allow incoming connections
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/python
   ```

2. **Port Forwarding**:
   - Configure router to forward ports 6109, 5900, 6080
   - Use dynamic DNS for remote access

3. **SSL/TLS**:
   - Configure nginx with SSL certificates
   - Use self-signed certificates for testing

## Uninstallation

To completely remove VirtualPyTest:

```bash
# Run uninstaller
./setup/local/macos/backend_host/install_host_macos.sh --uninstall

# Or manual removal
launchctl list | grep virtualpytest | awk '{print $3}' | xargs launchctl unload

# Remove plist files
rm ~/Library/LaunchAgents/com.virtualpytest.*.plist

# Remove installation directory
sudo rm -rf /usr/local/virtualpytest

# Remove RAM disk
sudo umount /Volumes/VirtualPyTest_Hot 2>/dev/null || true
rmdir /Volumes/VirtualPyTest_Hot 2>/dev/null || true
```

## Security Considerations

### macOS Security Features

1. **System Integrity Protection (SIP)**:
   - Prevents modification of system files
   - VirtualPyTest installs to user directories only

2. **Gatekeeper**:
   - Validates downloaded applications
   - Python and FFmpeg are installed via Homebrew (trusted)

3. **Privacy Controls**:
   - Screen Recording and Camera permissions required
   - User must explicitly grant access

### Best Practices

1. **Keep macOS Updated**:
   ```bash
   softwareupdate --all --install --force
   ```

2. **Use Strong Passwords**:
   - Change default VNC password
   - Use complex API authentication

3. **Regular Backups**:
   - Backup configuration files
   - Backup captured data

4. **Monitor Logs**:
   - Regularly check log files for errors
   - Set up log rotation

## Support

### Getting Help

1. **Check Logs First**:
   ```bash
   # View recent errors
   grep -r "ERROR" /usr/local/virtualpytest/logs/
   ```

2. **Verify Configuration**:
   ```bash
   # Check .env file
   cat backend_host/src/.env | grep -v '^#'
   ```

3. **Test Services Individually**:
   ```bash
   # Test Flask API
   curl http://localhost:6109/host/system/health

   # Test FFmpeg
   ffmpeg -f avfoundation -list_devices true -i ""
   ```

4. **System Diagnostics**:
   ```bash
   # System information
   system_profiler SPSoftwareDataType SPHardwareDataType

   # Check permissions
   tccutil query ScreenCapture
   tccutil query Camera
   ```

### Performance Monitoring

```bash
# Monitor VirtualPyTest processes
ps aux | grep -E "(python|ffmpeg)" | grep -v grep

# CPU usage
iostat -c 5

# Memory usage
vm_stat 5

# Network connections
lsof -i :6109,5900,6080
```

---

## Quick Start Checklist

- [ ] Run installation script as administrator
- [ ] Grant Screen Recording permission in System Settings
- [ ] Grant Camera permission in System Settings
- [ ] Allow launchd services in Login Items & Extensions
- [ ] Edit `.env` file to configure devices
- [ ] Start services: `launchctl start com.virtualpytest.flask`
- [ ] Test API access at http://localhost:6109
- [ ] Test VNC access at vnc://localhost:5900
- [ ] Check logs for any errors

For additional help, refer to the main VirtualPyTest documentation or create an issue in the project repository.