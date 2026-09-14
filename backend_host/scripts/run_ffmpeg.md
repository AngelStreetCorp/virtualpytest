# run_ffmpeg.sh — Multi-Device FFmpeg Capture Service

## Overview

`run_ffmpeg.sh` is the main capture service that reads device configuration from `.env`, starts one FFmpeg process per device, and monitors them with quality-change and stall-detection watchdogs.

**Systemd service:** `vpt-stream.service` (runs as `vpt_user`)

## Architecture

```
vpt-stream.service
  └── run_ffmpeg.sh (main loop — stays alive for systemd)
       ├── start_grabber("device1") → FFmpeg PID 1234 → capture1/captures/
       ├── start_grabber("device2") → FFmpeg PID 1235 → capture2/captures/
       └── main loop (every 1s):
            ├── check_quality_changes()   ← reads active_captures.conf
            └── check_stalled_devices()   ← detects frozen ffmpeg
```

## Device Configuration (.env)

Each device is configured in `backend_host/src/.env`:

```bash
# Host VNC capture (display :1)
HOST_VIDEO_SOURCE=:1
HOST_VIDEO_AUDIO=default
HOST_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture
HOST_VIDEO_FPS=2

# Android emulator (ADB or image-file pipe)
DEVICE1_VIDEO=/var/www/html/stream/emulator_frames/latest.png
DEVICE1_VIDEO_AUDIO=null
DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
DEVICE1_VIDEO_FPS=5
DEVICE1_ADB_SERIAL=emulator-5554      # If set, uses scrcpy→ffmpeg pipe

# Disable a device: prefix with 'x'
xDEVICE2_VIDEO=/dev/video2
```

## Source Types

| Type | Detection | Input method | Example |
|------|-----------|-------------|---------|
| `v4l2` | `/dev/videoN` | `-f v4l2` hardware capture | HDMI capture card |
| `x11grab` | `:N` display | `-f x11grab` screen grab | VNC display |
| `imagefile` | `.png`/`.jpg` extension | `cat` loop piped to `-f image2pipe` | Emulator screenshot |
| `ADB` | `DEVICE*_ADB_SERIAL` set | `scrcpy --record` piped to ffmpeg | Android device/emulator |

## Storage Modes

### RAM mode (hot storage)
When tmpfs is mounted at `$capture_dir/hot`, FFmpeg writes to RAM:
```
$capture_dir/hot/captures/capture_000001.jpg    ← FFmpeg output
$capture_dir/hot/segments/output.m3u8           ← HLS stream
$capture_dir/hot/thumbnails/capture_000001_thumbnail.jpg
```
The `hot_cold_archiver` moves files from RAM to SD periodically.

### SD mode (no tmpfs)
When no tmpfs mount exists, FFmpeg writes directly to disk:
```
$capture_dir/captures/capture_000001.jpg
$capture_dir/segments/output.m3u8
$capture_dir/thumbnails/capture_000001_thumbnail.jpg
```

**Important:** The kill/grep patterns in `kill_all_ffmpeg_for_device()` use
`$capture_dir/captures` which matches both modes (SD path directly, RAM path
via the `/hot/captures` substring).

## Quality Tiers

| Quality | Stream scale | Bitrate | When used |
|---------|-------------|---------|-----------|
| `low` | 320x180 (or 180x320 portrait) | 120-150k | Default — multi-device preview |
| `sd` | 640x360 (or 360x640 portrait) | 350k | Modal opened — single device focus |
| `hd` | 1280x720 (or 720x1280 portrait) | 1000-1500k | User clicks HD button |

Captures are always 1280x720 regardless of stream quality (for detection accuracy).

Quality is managed via `active_captures.conf` (CSV: `capture_dir,pid,quality`).
The VPT host API writes to this file; the main loop detects changes and restarts
ffmpeg with the new quality.

## Process Lifecycle

### Startup (systemd `ExecStart`)
1. Load `.env` → build `GRABBERS` array (one entry per device)
2. For each device: `start_grabber()` → detect source type → build FFmpeg command → `eval ... &`
3. Record PID in `active_captures.conf`
4. Enter main loop

### Main loop (every 1s)
1. **`check_quality_changes()`** — compare `active_captures.conf` quality vs `RUNNING_QUALITY[$device]`. If different: kill old ffmpeg → start new with new quality.
2. **`check_stalled_devices()`** — for each device, check capture file age. If stale beyond timeout: kill → restart.

### Stall detection thresholds
| Check | Timeout | Env var |
|-------|---------|---------|
| Capture file age | 20s | `FFMPEG_STALL_TIMEOUT_SECONDS` |
| Metadata file age | 40s | `FFMPEG_STALL_METADATA_TIMEOUT_SECONDS` |
| Hard capture timeout | 60s | `FFMPEG_STALL_HARD_CAPTURE_TIMEOUT_SECONDS` |
| Restart cooldown | 30s | `FFMPEG_STALL_RESTART_COOLDOWN_SECONDS` |

### Kill logic (`kill_all_ffmpeg_for_device`)
```
1. pgrep -f "$capture_dir/captures" → count matching processes
2. pkill -9 -f "$capture_dir/captures" → kill them
3. Verify count drops to 0
4. If still alive: broader pkill -f "$capture_dir"
```

**Device isolation:** Each device has a unique `$capture_dir` (e.g., `/stream/capture1`,
`/stream/capture2`), so the kill pattern only matches that device's ffmpeg — never
other devices on the same host.

### Shutdown (SIGTERM from systemd)
`cleanup_all()` → `pkill -9 -f '/usr/bin/ffmpeg'` (kills all ffmpegs on this host)

## Single Device Restart

```bash
# Restart just device1 with HD quality (from VPT host API or manually)
sudo -u vpt_user bash /opt/virtualpytest/backend_host/scripts/run_ffmpeg.sh device1 hd
```

In single-device mode: kills only that device's ffmpeg → starts new one → exits immediately (no main loop).

## Troubleshooting

### Duplicate FFmpeg processes
**Symptom:** Two ffmpegs writing to same capture dir, vpt-monitor queue overloaded.

**Cause:** `kill_all_ffmpeg_for_device` pattern didn't match (historically used
`$capture_dir/hot/captures` which fails in SD mode). Fixed to use `$capture_dir/captures`.

**Fix:** `sudo systemctl restart vpt-stream.service`

### FFmpeg stuck in D state
**Symptom:** `ps` shows ffmpeg in `DLl` state, high CPU but no new captures.

**Cause:** Image pipe input blocked (emulator not producing frames, or `cat` loop stuck).

**Fix:** The stall watchdog should auto-restart after 20-60s. If not: `sudo systemctl restart vpt-stream.service`

### No captures produced
```bash
# Check if ffmpeg is running
ps aux | grep ffmpeg | grep -v grep

# Check source availability
ls -la /var/www/html/stream/emulator_frames/latest.png  # imagefile source
adb devices                                               # ADB source
DISPLAY=:1 xdpyinfo                                      # x11grab source

# Check ffmpeg logs
cat /tmp/ffmpeg_output_device1.log
```

### Quality not changing
```bash
# Check active_captures.conf
cat /var/www/html/stream/active_captures.conf
# Format: capture_dir,pid,quality

# Verify the main loop is running (look for the parent bash)
ps -ef --forest | grep run_ffmpeg
```
