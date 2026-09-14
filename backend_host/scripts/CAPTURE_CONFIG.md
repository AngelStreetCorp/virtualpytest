# Centralized Capture Directory Configuration

## Overview

All capture directory configuration is **centralized** in a single `.env` file to avoid duplication and synchronization issues.

## Single Source of Truth

**File:** `backend_host/src/.env`

**Why .env?**
- ✅ Already used by backend API
- ✅ Standard environment variable format
- ✅ Easy to template and version control
- ✅ Works with heatmap_processor.py automatically
- ✅ Single edit point for all services

**Required Variables Per Device:**

```bash
# Host VNC Capture
HOST_VIDEO_SOURCE=:1                    # VNC display or video device
HOST_VIDEO_AUDIO=null                   # Audio device (null for no audio)
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
HOST_VIDEO_FPS=2                        # Input FPS

# Hardware Device
DEVICE1_VIDEO=/dev/video0               # Video capture device
DEVICE1_VIDEO_AUDIO=plughw:2,0          # ALSA audio device
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture2
DEVICE1_VIDEO_FPS=10                    # Input FPS
```

## How It Works

1. **Master Config:** Edit only `backend_host/src/.env` file
2. **FFmpeg Script:** `run_ffmpeg.sh` reads `.env` and builds GRABBERS dynamically
3. **Export:** Writes active capture directories to `/var/www/html/stream/active_captures.conf`
4. **Consumers:** All scripts (capture_monitor.py, clean_captures.sh, backend API, heatmap_processor.py) use same config

## Files That Read Configuration

| File | Purpose | Configuration Source |
|------|---------|---------------------|
| `backend_host/src/.env` | **MASTER CONFIG** | Edit here only |
| `run_ffmpeg.sh` | FFmpeg capture processes | Reads `.env` → builds GRABBERS |
| `capture_monitor.py` | Incident monitoring | `/var/www/html/stream/active_captures.conf` |
| `clean_captures.sh` | Cleanup old files | `/var/www/html/stream/active_captures.conf` |
| Backend API | Device management | Reads `.env` directly |
| `heatmap_processor.py` | Heatmap generation | Via API (reads `.env`) |

## Adding New Capture Directory

**You only need to edit ONE file:**

1. Open `backend_host/src/.env`
2. Add new device configuration:
   ```bash
   # Device 3 - New Device
   DEVICE3_NAME=NewDevice
   DEVICE3_MODEL=android_mobile
   DEVICE3_VIDEO=/dev/video2              # Hardware capture device
   DEVICE3_VIDEO_AUDIO=plughw:3,0         # ALSA audio device
   DEVICE3_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture4
   DEVICE3_VIDEO_STREAM_PATH=/host/stream/capture4
   DEVICE3_VIDEO_FPS=10                   # Input FPS
   ```

3. Restart the FFmpeg service:
   ```bash
   sudo systemctl restart ffmpeg_capture
   ```

**That's it!** All services will automatically use the new configuration:
- ✅ FFmpeg script creates capture
- ✅ capture_monitor.py monitors it
- ✅ clean_captures.sh cleans it
- ✅ Backend API recognizes it
- ✅ heatmap_processor.py includes it

## Disabling Devices

To temporarily disable a device **without deleting** its configuration:

**Option 1: Prefix with 'x'**
```bash
# Disabled - FFmpeg script will skip this
xDEVICE3_VIDEO=/dev/video2
xDEVICE3_VIDEO_AUDIO=plughw:3,0
xDEVICE3_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture4
xDEVICE3_VIDEO_FPS=10
```

**Option 2: Comment out with '#'**
```bash
# Disabled - FFmpeg script will skip this
#DEVICE3_VIDEO=/dev/video2
#DEVICE3_VIDEO_AUDIO=plughw:3,0
#DEVICE3_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture4
#DEVICE3_VIDEO_FPS=10
```

## Fallback Behavior

If `/var/www/html/stream/active_captures.conf` doesn't exist (e.g., FFmpeg service not running), monitoring scripts fall back to default directories:
- `capture1`
- `capture2`

This ensures monitoring continues to work even if the FFmpeg service is stopped.

## Configuration File Format

### .env Format (MASTER)
```bash
# Host VNC (always use HOST_VIDEO_SOURCE for host capture)
HOST_VIDEO_SOURCE=:1                    # VNC display :1 or video device
HOST_VIDEO_AUDIO=null                   # null or ALSA device
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
HOST_VIDEO_FPS=2                        # Input FPS (2 for VNC, 10 for hardware)

# Hardware Devices (use DEVICE1-10 numbering)
DEVICE1_VIDEO=/dev/video0               # Required: Video device
DEVICE1_VIDEO_AUDIO=plughw:2,0          # Required: Audio device or null
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture2  # Required
DEVICE1_VIDEO_FPS=10                    # Required: Input FPS
```

### /var/www/html/stream/active_captures.conf Format (AUTO-GENERATED)
CSV Format with capture directory, PID, and quality:
```
/var/www/html/stream/capture1,PID,quality
/var/www/html/stream/capture2,PID,quality
/var/www/html/stream/capture3,PID,quality
```

**Note:** The base directory is stored (without `/captures` suffix). Consumer scripts add `/captures` as needed.

## Benefits

✅ **Single edit point** - No more syncing 3+ files  
✅ **Automatic propagation** - Changes apply to all services  
✅ **No duplication** - Reduced risk of configuration drift  
✅ **Graceful fallback** - Works even if config file missing  
✅ **Clear ownership** - FFmpeg script is master config  

## Migration Notes

**Before:** Had to edit capture directories in multiple places:
- `run_ffmpeg.sh` (GRABBERS array)
- `capture_monitor.py` (hardcoded list)
- `clean_captures.sh` (hardcoded array)
- `backend_host/src/.env` (for API)

**After:** Edit only `backend_host/src/.env` file

## Complete .env Example

```bash
# =====================================================
# HOST DEVICE CONFIGURATION (VNC Capture)
# =====================================================
HOST_VIDEO_SOURCE=:1
HOST_VIDEO_AUDIO=null
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
HOST_VIDEO_FPS=2

# =====================================================
# DEVICE 1 - Android Phone
# =====================================================
DEVICE1_NAME=S21x
DEVICE1_MODEL=android_mobile
DEVICE1_VIDEO=/dev/video0
DEVICE1_VIDEO_AUDIO=plughw:2,0
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture2
DEVICE1_VIDEO_FPS=10

# =====================================================
# DEVICE 2 - iPad (Disabled)
# =====================================================
xDEVICE2_NAME=iPad
xDEVICE2_MODEL=ios_mobile
xDEVICE2_VIDEO=/dev/video2
xDEVICE2_VIDEO_AUDIO=plughw:3,0
xDEVICE2_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture3
xDEVICE2_VIDEO_FPS=10
```
