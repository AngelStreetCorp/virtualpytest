# VirtualPyTest Windows Installation Guide

Windows runs the **host role only** (a device controller with desktop capture, joining a
server that runs on Linux or in Docker). Server, frontend and database on Windows are not
offered; a single Windows box can run the full stack in Docker Desktop (WSL2) instead —
`docs/get-started/docker.md`. Overview: `docs/get-started/local-dev.md#windows`.

## Prerequisites

### System Requirements
- Windows 10/11 (64-bit)
- Administrator privileges
- At least 8GB RAM (16GB recommended for RAM disk)
- 20GB free disk space
- Internet connection for downloading dependencies

### Required Software
The installation script will automatically install:
- Chocolatey (package manager)
- FFmpeg (video processing)
- Python 3.11+ (runtime)
- NSSM (Non-Sucking Service Manager)
- TightVNC (VNC server)
- VcXsrv (X11 compatibility)
- IIS (web server)

## Installation

### 1. Prepare Your System

1. **Run PowerShell as Administrator**
   ```powershell
   # Right-click PowerShell → Run as Administrator
   ```

2. **Enable Execution Policy**
   ```powershell
   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

3. **Navigate to Project Directory**
   ```powershell
   cd C:\path\to\virtualpytest
   ```

### 2. Run Installation Script

```powershell
.\setup\local\windows\backend_host\install_host_windows.ps1

# The installer will copy the repo to the standard install root:
#   C:\virtualpytest\virtualpytest
# and then run from there so Windows services reference stable paths.
```

### 3. Configure Environment

Edit the generated `.env` file — it must carry `SERVER_URL`, `API_KEY` and the Supabase /
storage values of the server this host joins (`backend_host\src\.env.example` documents them):
```powershell
notepad backend_host\src\.env
```

## Configuration

### Environment Variables

The installer creates these Windows environment variables:
- `VIRTUALPYTEST_ROOT` - Project root directory
- `VIRTUALPYTEST_HOST` - Backend host directory
- `VIRTUALPYTEST_LOGS` - Log files directory
- `PYTHONPATH` - Python module paths
- `DISPLAY` - X11 display number (for compatibility)

### Device Configuration

Configure video capture devices in `backend_host\src\.env`:

```bash
# Host VNC display capture
HOST_VIDEO_SOURCE=:1
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=C:\virtualpytest\cold\host
HOST_VIDEO_FPS=2

# Hardware camera capture (Windows DirectShow)
DEVICE1_VIDEO=USB Camera
DEVICE1_VIDEO_AUDIO=null
DEVICE1_VIDEO_CAPTURE_PATH=C:\virtualpytest\cold\device1
DEVICE1_VIDEO_FPS=10

# Screen capture
DEVICE2_VIDEO=desktop
DEVICE2_VIDEO_AUDIO=null
DEVICE2_VIDEO_CAPTURE_PATH=C:\virtualpytest\cold\device2
DEVICE2_VIDEO_FPS=5
```

### Finding Camera Names

To find available camera devices on Windows:

```powershell
# List DirectShow devices
ffmpeg -list_devices true -f dshow -i dummy

# Or use PowerShell
Get-PnpDevice | Where-Object { $_.Class -eq "Camera" -or $_.Class -eq "Image" } | Select Name
```

## Services Overview

The installation creates these components:

| Name | Type | Description | Port |
|------|------|-------------|------|
| vpt-host | Service (NSSM) | REST API server | 6109 |
| vpt-monitor | Service (NSSM) | Capture monitoring | N/A |
| vpt-archiver | Service (NSSM) | Hot/cold storage archiver | N/A |
| vpt-transcript | Service (NSSM) | Audio transcription | N/A |
| vpt-vnc | Service (NSSM) | VNC server | 5900 |
| vpt-websockify | Service (NSSM) | WebSocket proxy for VNC | 6080 |
| vpt-stream | Scheduled Task | FFmpeg desktop capture (interactive session required) | N/A |

Why is `vpt-stream` a task on Windows? `ffmpeg -f gdigrab -i desktop` must run in the interactive console session (Session 1). It cannot capture the desktop from Session 0 (services/SSH).

## Service Management

### Using PowerShell

```powershell
# Check service status
Get-Service vpt-*

# Start/stop core services (stream is a Scheduled Task on Windows)
Start-Service vpt-host, vpt-monitor, vpt-archiver, vpt-transcript, vpt-vnc, vpt-websockify
Stop-Service  vpt-host, vpt-monitor, vpt-archiver, vpt-transcript, vpt-vnc, vpt-websockify

# Restart specific service
Restart-Service vpt-host
```

### Stream Task (vpt-stream)

```powershell
# Task status
Get-ScheduledTask vpt-stream | Select TaskName, State
Get-ScheduledTaskInfo vpt-stream | Select LastRunTime, LastTaskResult

# Start/stop
Start-ScheduledTask vpt-stream
Stop-ScheduledTask vpt-stream
```

### Desktop requirements for stream capture

- The stream task captures the interactive console desktop, so **Desktop Window Manager (dwm.exe)** must be enabled and running. On Server SKUs, verify the `Desktop Window Manager Session Manager (UxSms)` service is started and not disabled via Group Policy.
- After you reboot the host, log back into the **console session** (or configure automatic logon) before the `vpt-stream` task runs—the task uses a Logon trigger and cannot capture from Session 0. While the desktop is locked or no user is signed in, ffmpeg’s `gdigrab` source cannot access the screen and `websockify` drops the connection.
### Using Services MMC

1. Press `Win + R`, type `services.msc`
2. Look for services starting with "vpt-"
3. Right-click → Start/Stop/Restart

### Using NSSM

```cmd
# Open command prompt as Administrator
nssm status vpt-host
nssm start vpt-host
nssm stop vpt-host
nssm restart vpt-host
```

## Access Points

After installation, VirtualPyTest is accessible at:

- **REST API**: http://localhost:6109
- **VNC Server**: localhost:5900 (no VNC authentication; firewall rule limited to the local subnet)
- **noVNC Web Interface**: http://localhost:6080/vnc_lite.html
- **IIS Web Server**: http://localhost (if configured)

## Storage Architecture

### Directory Structure

```
C:\virtualpytest\
├── cold\           # Persistent storage (disk)
│   ├── host\       # Host device captures
│   ├── device1\    # Device 1 captures
│   └── ...
├── hot\            # RAM disk mount (optional)
│   ├── segments\   # HLS video segments
│   ├── captures\   # JPEG captures
│   └── thumbnails\ # Thumbnail images
└── logs\           # Log files
    ├── install.log
    ├── ffmpeg_stream.log
    └── *.log
```

### RAM Disk (Optional)

If enabled, a RAM disk provides high-performance hot storage:

- **Size**: 512MB (configurable)
- **Drive Letter**: R:
- **Purpose**: Reduces SD card writes by 99%
- **Fallback**: Uses disk storage if RAM disk fails

## Firewall Configuration

The installer automatically creates Windows Firewall rules:

- **VirtualPyTest Host API** (TCP 6109)
- **VirtualPyTest VNC** (TCP 5900)
- **VirtualPyTest noVNC** (TCP 6080)

Ensure any external firewall or router also allows inbound TCP ports **22** (for remote administration/SSH access if you rely on it), **5900** (TightVNC), and **6080** (noVNC). Port **6109** should stay open for the API as well.

## Logging

### Log Locations

- **Installation**: `C:\virtualpytest\logs\install.log`
- **FFmpeg**: `C:\virtualpytest\logs\ffmpeg_stream.log`
- **Services**: Windows Event Viewer → Windows Logs → Application

### Viewing Logs

```powershell
# View installation log
Get-Content C:\virtualpytest\logs\install.log -Tail 50

# View FFmpeg log
Get-Content C:\virtualpytest\logs\ffmpeg_stream.log -Tail 20 -Wait

# View Windows Event Logs
Get-EventLog -LogName Application -Source vpt-* -Newest 10
```

## Troubleshooting

### Common Issues

#### 1. Services Won't Start

```powershell
# Check service status
Get-Service vpt-* | Select Name, Status, StartType

# Check service dependencies
nssm dump vpt-host
```

#### 2. FFmpeg Capture Fails

```powershell
# Test camera access
ffmpeg -f dshow -list_options true -i video="USB Camera"

# Check FFmpeg logs
Get-Content C:\virtualpytest\logs\ffmpeg_stream.log -Tail 50
```

#### 3. VNC Connection Issues

```powershell
# Test VNC server
Test-NetConnection localhost -Port 5900

# Check VNC service logs
Get-EventLog -LogName Application -Source tvnserver -Newest 5
```

#### 4. RAM Disk Issues

```powershell
# Check if RAM disk exists
Get-PSDrive -Name R -ErrorAction SilentlyContinue

# Recreate RAM disk manually
imdisk -a -s 512M -m R: -p "/fs:ntfs /q /y"
```

### Performance Tuning

#### FFmpeg Optimization

Edit `backend_host\scripts\run_ffmpeg.ps1`:

```powershell
# Adjust buffer sizes and quality settings
$streamBitrate = "500k"  # Reduce for slower systems
$hlsTime = "2"          # Shorter segments for lower latency
```

#### RAM Disk Size

Modify RAM disk size in the installation script:
```powershell
imdisk -a -s 1G -m R: -p "/fs:ntfs /q /y"  # 1GB instead of 512MB
```

## Uninstallation

To completely remove VirtualPyTest:

```powershell
# Run uninstaller
.\setup\local\windows\backend_host\install_host_windows.ps1 -Uninstall

# Or manual removal
Get-Service vpt-* | Stop-Service
nssm remove vpt-host confirm
# ... remove other services

# Remove stream scheduled task
Unregister-ScheduledTask -TaskName vpt-stream -Confirm:$false

# Remove directories
Remove-Item C:\virtualpytest -Recurse -Force

# Remove environment variables
[Environment]::SetEnvironmentVariable("VIRTUALPYTEST_ROOT", $null, "Machine")
[Environment]::SetEnvironmentVariable("VIRTUALPYTEST_HOST", $null, "Machine")
# ... remove other variables
```

## Advanced Configuration

### Custom Service Accounts

Create a dedicated service account:

```powershell
# Create service user
$password = ConvertTo-SecureString "ComplexPassword123!" -AsPlainText -Force
New-LocalUser -Name "VirtualPyTestSvc" -Password $password -FullName "VirtualPyTest Service Account" -Description "Account for VirtualPyTest services"

# Configure NSSM to use service account
nssm set vpt-host ObjectName ".\VirtualPyTestSvc" "ComplexPassword123!"
```

### IIS Configuration

For advanced web server setup:

```powershell
# Import IIS module
Import-Module WebAdministration

# Configure custom bindings
Set-WebBinding -Name "VirtualPyTest" -BindingInformation "*:80:" -PropertyName Port -Value 8080
Set-WebBinding -Name "VirtualPyTest" -BindingInformation "*:443:ssl" -PropertyName Port -Value 8443
```

### Network Configuration

For multi-machine setups:

1. **Change default ports** in `.env` file
2. **Configure Windows Firewall** for remote access
3. **Set up SSL certificates** for HTTPS
4. **Configure load balancing** if needed

## Support

### Getting Help

1. **Check logs** first (see Logging section)
2. **Verify configuration** in `.env` file
3. **Test services individually**
4. **Check Windows Event Viewer**

### Common Log Locations

- `C:\virtualpytest\logs\*.log`
- Windows Event Viewer → Application logs
- IIS logs: `C:\inetpub\logs\LogFiles\`

### Performance Monitoring

```powershell
# Monitor service CPU/memory usage
Get-Process | Where-Object { $_.Name -like "*ffmpeg*" -or $_.Name -like "*python*" } | Select Name, CPU, WorkingSet

# Check disk I/O
Get-Counter '\PhysicalDisk(*)\% Disk Time'

# Monitor RAM disk usage
Get-PSDrive -Name R | Select Used, Free
```

---

## Quick Start Checklist

- [ ] Run PowerShell as Administrator
- [ ] Execute installation script
- [ ] Configure devices in `.env` file
- [ ] Start services
- [ ] Test API access at http://localhost:6109
- [ ] Test VNC access at localhost:5900
- [ ] Check logs for any errors

For additional help, refer to the main VirtualPyTest documentation or create an issue in the project repository.
