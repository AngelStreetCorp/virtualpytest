# Backend Host Windows Installation

## Overview
This script installs and configures the VirtualPyTest Backend Host on Windows for device capture and control, including browser automation tools, device detection, and VNC/remote access capabilities.

**Architecture**: The installation uses a modular structure with shared utilities across platforms:
- `setup/local/shared/` - Cross-platform logging and device parsing utilities
- `setup/local/windows/backend_host/` - Windows-specific installation scripts
- `backend_host/config/services/windows/` - (Reserved for future Windows service templates)

## Prerequisites
- Windows 10/11 (64-bit)
- Administrator privileges (required for service installation and system configuration)
- PowerShell 5.1 or later (included with Windows)
- Internet connection for package downloads
- Python 3.x (installed automatically via Chocolatey if not present)
- Hardware access for device capture (USB, cameras, etc.)

## File Structure
```
setup/local/
├── shared/                      # Cross-platform utilities
│   ├── logging.sh              # Shared logging functions
│   └── parse_devices.sh        # Device parsing from .env
└── windows/backend_host/
    ├── install_host_windows.ps1 # Main installation script (services + interactive tasks)
    ├── common_vars.ps1          # Windows-specific variables
    └── README.md                # Additional documentation
```

## Usage
```powershell
# Update host code to debug branch before install
cd C:\virtualpytest\virtualpytest
git pull --rebase origin debug

# Install everything (dependencies + services) in one command (run as Administrator)
.\setup\local\windows\backend_host\install_host_windows.ps1

# Install with custom options
.\setup\local\windows\backend_host\install_host_windows.ps1 -NoVNC -InstallPath "D:\vpt"
```

## Installation Steps
The `install_host_windows.ps1` script performs these steps:

1. **Administrator Check**
   - Verifies script is running with administrator privileges
   - Required for service installation and system configuration

2. **Install Chocolatey**
   - Installs Chocolatey package manager if not present
   - Used for installing system dependencies

3. **Install System Dependencies**
   - Python 3, pip, virtual environment tools
   - Chromium, Firefox (for browser automation)
   - FFmpeg (for video capture and processing)
   - Git (for repository management)
   - NSSM (Non-Sucking Service Manager for Windows services)
   - Microsoft Teams Network Assessment Tool (auto-detected; winget install attempted when missing)

4. **Setup Python Environment**
   - Checks if Python 3 is installed, installs via Chocolatey if not found
   - Creates virtual environment at `venv/`
   - Upgrades pip to latest version
   - Installs backend_host requirements from `requirements.txt` (includes psutil, flask, etc.)
   - Installs Playwright browsers (chromium, firefox, webkit)

5. **Setup Environment**
   - Creates `.env` from template if not exists
   - Creates Windows-specific environment configuration

6. **Setup Storage**
   - Creates storage directories with hourly folders (flat layout — no hot/cold split on Windows)
   - Directory structure: `C:\virtualpytest\stream\{device}\{captures,thumbnails,segments,metadata,audio}\`
   - Hour folders (0-23) for segments, metadata, and audio

7. **Install Services**
   - Uses NSSM to create Windows services
   - Background components run under Local System account
   - `vpt-host` and `vpt-stream` run as interactive Scheduled Tasks
   - Automatic service recovery and restart configuration

8. **Configure VNC** (unless -NoVNC specified)
   - Sets up TightVNC or similar VNC server
   - Configures default password and settings
   - Downloads noVNC static files to `C:\virtualpytest\novnc`
   - Configures `vpt-websockify` to serve `vnc_lite.html` via `--web` (port 6080)

9. **Configure Permissions**
   - Sets up Windows service permissions
   - Configures FFmpeg process control permissions

10. **Configure Firewall**
    - Opens required ports in Windows Firewall
    - Configures service access rules
    - Opens browser CDP ports `9222` and `9223` for web automation debugging

## Services Installed
Most components run as Windows services managed by NSSM.

**Important (Windows host + stream):** browser automation and `ffmpeg` desktop capture (`gdigrab`) must run in an interactive user session (console Session 1). They cannot run reliably from Session 0 (services/SSH). For this reason, **`vpt-host` and `vpt-stream` are installed as Scheduled Tasks**, not Windows Services.

- **Desktop requirements:** Desktop Window Manager (`dwm.exe`) must be installed and running (start the `Desktop Window Manager Session Manager (UxSms)` service if it is disabled). After a reboot you must sign back into the console session (or add automatic logon) before the scheduled tasks will be able to run—`vpt-host` and `vpt-stream` use logon triggers and cannot start while no user is signed in.

| Name | Type | Description | Port |
|------|------|-------------|------|
| `vpt-host` | Scheduled Task | Host API Server (interactive) | 6109 |
| `vpt-monitor` | Service (NSSM) | Capture Monitor | - |
| `vpt-archiver` | Service (NSSM) | Hot/Cold Archiver | - |
| `vpt-transcript` | Service (NSSM) | Audio Transcript | - |
| `vpt-vnc` | Service (NSSM) | VNC Server | 5900 |
| `vpt-websockify` | Service (NSSM) | noVNC WebSocket Proxy | 6080 |
| `vpt-stream` | Scheduled Task | FFmpeg capture (interactive session) | - |

## Configuration
### Environment File
Each Backend Host gets settings in `backend_host\src\.env`:
```powershell
# Host video configuration
HOST_VIDEO_SOURCE=0  # DirectShow device index on Windows
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=C:\virtualpytest\stream\host
HOST_VIDEO_FPS=2

# Device configurations
DEVICE1_VIDEO=1  # Second camera
DEVICE1_VIDEO_CAPTURE_PATH=C:\virtualpytest\stream\device1
DEVICE1_VIDEO_FPS=10

# Flask API
HOST_PORT=6109
```

### Windows-Specific Configuration
- Device paths use DirectShow indices instead of `/dev/video*`
- Storage paths use Windows-style paths (`C:\...`)
- Firewall rules are configured automatically

## NSSM Service Management

**NSSM (Non-Sucking Service Manager)** is used instead of Windows built-in service management:

```powershell
# List NSSM services
nssm list

# Check host task status
Get-ScheduledTask vpt-host | Select TaskName, State
Get-ScheduledTaskInfo vpt-host | Select LastRunTime, LastTaskResult
```

## Stream Task Management (Windows)
```powershell
# Task status
Get-ScheduledTask vpt-stream | Select TaskName, State
Get-ScheduledTaskInfo vpt-stream | Select LastRunTime, LastTaskResult

# Start/stop
Start-ScheduledTask vpt-stream
Stop-ScheduledTask vpt-stream

# Disable/enable
Disable-ScheduledTask vpt-stream
Enable-ScheduledTask vpt-stream
```

## Access Points
| Service | URL/Address |
|---------|-------------|
| Flask API | `http://localhost:6109` |
| VNC Desktop | `vnc://localhost:5900` (password: admin1234) |
| noVNC Web | `http://localhost:6080/vnc_lite.html` |

## Ports Used
|  connexion closed 1011  | Service | Protocol |
|------|---------|----------|
| 5900 | VNC Server | TCP |
| 6080 | noVNC/WebSockify | TCP |
| 6109 | Flask API | TCP |

## Service Management
```powershell
# List all VirtualPyTest services
Get-Service vpt-*

# Check host task status
Get-ScheduledTask vpt-host | Select TaskName, State

# Start/Stop task
Start-ScheduledTask vpt-host
Stop-ScheduledTask vpt-host
Restart-Service vpt-vnc

# View host task logs (capped at 30 MB/file by host_wrapper.ps1; older
# content rolls to <name>.1 — check .log first, then .log.1 for history)
Get-Content C:\virtualpytest\logs\host.log -Tail 100
Get-Content C:\virtualpytest\logs\host_error.log -Tail 100

# Start background services + interactive tasks
Start-Service vpt-monitor, vpt-archiver, vpt-transcript
Start-ScheduledTask vpt-host
Start-ScheduledTask vpt-stream

# Stop background services + interactive tasks
Stop-ScheduledTask vpt-host
Stop-ScheduledTask vpt-stream
Stop-Service vpt-monitor, vpt-archiver, vpt-transcript
```

## Device Detection
```powershell
# List video devices (DirectShow)
ffmpeg -list_devices true -f dshow -i dummy

# List audio devices
ffmpeg -list_devices true -f dshow -i dummy

# Test video capture (device index 0)
ffmpeg -f dshow -i video="Integrated Camera" -frames:v 1 test.jpg
```

## Manual Launch (Development)
```powershell
# Launch without Windows services
.\setup\local\windows\backend_host\launch_host.ps1
```

## Troubleshooting

### Teams Network Assessment Tool
```powershell
# Expected executable path
Test-Path "C:\Program Files (x86)\Microsoft Teams Network Assessment Tool\NetworkAssessmentTool.exe"

# Run a quick test
& "C:\Program Files (x86)\Microsoft Teams Network Assessment Tool\NetworkAssessmentTool.exe" /?
```

### Service Won't Start
```powershell
# Check host task status
Get-ScheduledTask vpt-host | Select TaskName, State
Get-ScheduledTaskInfo vpt-host | Select LastRunTime, LastTaskResult

# Check task logs. All vpt-* logs are capped at 30 MB:
#  - host/stream wrappers roll to <name>.log.1
#  - NSSM services (monitor/archiver/transcript/kpi/websockify) roll to
#    timestamped <name>-YYYYMMDD.log via NSSM online rotation
Get-Content C:\virtualpytest\logs\host.log -Tail 100
Get-Content C:\virtualpytest\logs\host_error.log -Tail 100

# Check if port is in use
netstat -ano | findstr :6109

# Verify Python environment
& "C:\virtualpytest\venv\Scripts\python.exe" -c "import flask"
```

### VNC Issues
```powershell
# Check VNC process
Get-Process -Name "*vnc*"

# Kill stale VNC sessions
Stop-Process -Name "*vnc*" -Force

# Restart VNC service
Restart-Service vpt-vnc
```

### VNC Mouse Cursor Disappears on Take Control
Windows VNC servers (TightVNC) don't send cursor shape updates via the RFB protocol like Linux TigerVNC does. This causes the mouse cursor to disappear in the noVNC web interface when taking control.

**Fix:** Edit `C:\virtualpytest\novnc\vnc_lite.html` and add `rfb.showDotCursor = true;` after the existing RFB settings:
```javascript
rfb.viewOnly = readQueryVariable('view_only', false);
rfb.scaleViewport = readQueryVariable('scale', false);
rfb.showDotCursor = true; // Show dot cursor when server doesn't send cursor shape
```
Then refresh the noVNC page (no service restart needed).

The template source is `backend_host/config/services/linux/vnc.lite.example` — re-running the install script will also apply this fix.

### Video Capture Issues
```powershell
# Check device permissions (run as Administrator)
# Windows usually grants access to video devices automatically

# Test capture with different device names
ffmpeg -f dshow -i video="USB Camera" -frames:v 1 test.jpg

# List available devices
ffmpeg -list_devices true -f dshow -i dummy
```

### NSSM Issues
```powershell
# Check NSSM installation
Get-Command nssm

# Reinstall NSSM if corrupted
choco install nssm -y
```

### Firewall Issues
```powershell
# Check firewall rules
Get-NetFirewallRule -DisplayName "*VirtualPyTest*"

# Open port manually if needed
New-NetFirewallRule -DisplayName "VirtualPyTest API" -Direction Inbound -Protocol TCP -LocalPort 6109 -Action Allow
New-NetFirewallRule -DisplayName "VirtualPyTest Browser CDP 9223" -Direction Inbound -Protocol TCP -LocalPort 9223 -Action Allow
```

## Windows-Specific Considerations
- **Administrator Privileges**: Required for service installation and system configuration
- **DirectShow**: Windows uses DirectShow for video/audio device access instead of V4L2
- **Paths**: Use Windows-style paths (`C:\...`) instead of Unix paths (`/dev/...`)
- **Services**: NSSM provides systemd-like service management on Windows
- **Firewall**: Windows Firewall rules are configured automatically

## Next Steps
1. Edit `backend_host\src\.env` to configure your devices
2. Test VNC connectivity: Use VNC Viewer to connect to `localhost:5900`
3. Test noVNC web: Open `http://localhost:6080/vnc_lite.html` in browser
4. Verify device detection with `ffmpeg -list_devices true -f dshow -i dummy`
5. Test API: Open `http://localhost:6109/health` in browser
6. Configure device-specific capture parameters in `.env` file
