# VirtualPyTest Backend Host Services

This directory contains system service configurations for running VirtualPyTest backend host components as background services. The backend host handles device capture, processing, and analysis.

## Linux Services (`linux/`)

### Core Infrastructure Services

#### `vpt-host.service`
**Purpose**: Main Host API server for hardware interface
- **Executes**: `app.py` - Flask application server on port 6109
- **Function**: Provides REST API for device control, monitoring, and data access
- **Dependencies**: Network connectivity, git auto-update

#### `vnc.service`
**Purpose**: Virtual display server for headless operation
- **Executes**: TigerVNC server on display :1 (port 5901)
- **Function**: Provides virtual X11 display for applications requiring GUI
- **Resolution**: 1280x720, accessible from network

#### `websockify.service`
**Purpose**: WebSocket proxy for VNC access
- **Executes**: noVNC websockify on port 6080
- **Function**: Enables browser-based VNC access through WebSocket proxy
- **Dependencies**: Runs after `vnc.service`

### Capture & Monitoring Services

#### `stream.service`
**Purpose**: Screen capture using FFmpeg
- **Executes**: `run_ffmpeg.sh` - FFmpeg screen recording
- **Function**: Continuous screen capture to video files
- **Output**: Streams to `/tmp/ffmpeg_service.log`

#### `monitor.service`
**Purpose**: Capture process monitoring
- **Executes**: `capture_monitor.py` - Monitors capture health
- **Function**: Watches FFmpeg processes, detects failures, manages capture lifecycle

### Analysis & Processing Services

#### `kpi.service`
**Purpose**: KPI measurement execution
- **Executes**: `kpi_executor.py` - Performance metrics collection
- **Function**: Measures network latency, response times, system performance
- **Delay**: 5-second startup delay to allow system stabilization

#### `transcript.service`
**Purpose**: Audio transcription and detection
- **Executes**: `transcript_accumulator.py` - Audio processing
- **Function**: Processes audio streams for incident detection (silence, audio loss)
- **Default**: Audio detection only (transcription disabled)
- **Optional**: Enable Whisper transcription with `--transcript true`
- **Tuning**: `TRANSCRIPTION_WORKERS` and `MAX_INFLIGHT_PER_DEVICE`
- **Delay**: 10-second startup delay

#### `subtitle.service`
**Purpose**: Subtitle generation (24h circular buffer)
- **Executes**: `subtitle_accumulator.py` - Text subtitle creation
- **Function**: Generates subtitle files from audio/video content
- **Delay**: 10-second startup delay

#### `archiver.service`
**Purpose**: Hot/cold data archiving
- **Executes**: `hot_cold_archiver.py` - Data lifecycle management
- **Function**: Manages data retention, moves old captures to cold storage

## macOS Services (`mac/`)

### Platform-Specific Services

#### `ramdisk.plist`
**Purpose**: RAM disk setup (macOS only)
- **Executes**: RAM disk creation script (runs as root)
- **Function**: Creates high-performance RAM-based storage for capture data
- **Lifecycle**: One-shot service that runs at boot, doesn't restart

### Cross-Platform Services
All other macOS services mirror their Linux counterparts with `.plist` extensions:
- `vpt-host.plist` - Main API server
- `vnc.plist` - Virtual display
- `websockify.plist` - WebSocket proxy
- `stream.plist` - FFmpeg capture
- `monitor.plist` - Capture monitoring
- `kpi.plist` - KPI measurements
- `transcript.plist` - Audio processing
- `subtitle.plist` - Subtitle generation
- `archiver.plist` - Data archiving

## Service Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   vpt-host.service │    │  stream.service  │    │ monitor.service │
│   (API Server)  │◄──►│ (FFmpeg Capture) │◄──►│ (Process Watch) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ websockify.svc  │    │  vnc.service     │    │ kpi.service     │
│ (Web Access)    │    │ (Virtual Display)│    │ (Performance)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ transcript.svc  │    │ subtitle.service │    │ archiver.svc    │
│ (Audio Detect)  │    │ (Text Subs)      │    │ (Data Mgmt)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Service Management

### Linux (systemd)
```bash
# Start all services
sudo systemctl start vpt-host vnc websockify stream monitor kpi transcript subtitle archiver

# Check status
sudo systemctl status vpt-host.service

# View logs
sudo journalctl -u vpt-host.service -f

# Enable auto-start
sudo systemctl enable vpt-host.service
```

### macOS (launchd)
```bash
# Load all services
sudo launchctl load /Library/LaunchDaemons/com.virtualpytest.*.plist

# Start service
sudo launchctl start com.virtualpytest.vpt-host

# Check status
sudo launchctl list | grep virtualpytest
```

## Notes
- Template files use placeholders (`%USER%`, `%PROJECT_ROOT%`, etc.) replaced by setup scripts
- Services run under dedicated `vpt_user` account with security restrictions
- Startup delays prevent race conditions during boot
- All services include automatic restart policies
- macOS `ramdisk.plist` requires root privileges for disk mounting
