#!/bin/bash

# Usage: ./run_ffmpeg.sh [device_id] [quality]
# Examples:
#   ./run_ffmpeg.sh              # Start all devices (systemd mode)
#   ./run_ffmpeg.sh device1 hd   # Restart device1 with HD
#   ./run_ffmpeg.sh host sd      # Restart host with SD

# Enable debugging
#set -x  # Print commands as they execute
# set -e  # Exit on error (commented out for debugging)

# Set umask to allow world read/write for shared temp files
umask 0000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BACKEND_HOST_DIR/src/.env"

echo "🔍 DEBUG: Running as user: $(whoami)"
echo "🔍 DEBUG: SCRIPT_DIR: $SCRIPT_DIR"
echo "🔍 DEBUG: ENV_FILE: $ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

if [ ! -r "$ENV_FILE" ]; then
    echo "ERROR: .env file not readable by $(whoami)"
    ls -la "$ENV_FILE"
    exit 1
fi

echo "✅ .env file found and readable"

# Fix Windows line endings in .env file (common issue when editing on Windows)
echo "🔧 Fixing any Windows line endings in .env file..."
sed -i 's/\r$//' "$ENV_FILE"

# Parse arguments
TARGET_DEVICE="${1:-all}"
TARGET_QUALITY="${2:-sd}"
SINGLE_DEVICE_MODE=false

echo "🔍 DEBUG: Script called with arguments:"
echo "  \$1 (TARGET_DEVICE): '$TARGET_DEVICE'"
echo "  \$2 (TARGET_QUALITY): '$TARGET_QUALITY'"
echo "  All args: $@"

if [ "$TARGET_DEVICE" != "all" ]; then
    SINGLE_DEVICE_MODE=true
    echo "🎯 Restarting $TARGET_DEVICE with quality: $TARGET_QUALITY"
fi

# Load .env
echo "🔍 DEBUG: Loading .env file..."
# Fix Windows line endings in .env file before sourcing
sed -i 's/\r$//' "$ENV_FILE"
set -a
source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep -v '^x')
set +a
echo "✅ .env loaded successfully"

declare -A GRABBERS=()
declare -A RUNNING_QUALITY=()  # Track what quality each device is actually running
declare -A FAIL_COUNT=()       # Watchdog: consecutive failed restarts per device
declare -A LAST_RESTART_TS=()  # Watchdog: unix-ts of last restart attempt per device
declare -A DORMANT=()          # Watchdog: "1" when retry cap exhausted; auto-exits on device reappear
declare -A RESTART_HISTORY=()  # Watchdog: space-separated unix-ts of recent restarts (flap detector)
declare -A FLAP_UNTIL=()       # Watchdog: unix-ts until which a flapping device is left idle (0 = not flapping)

# Build GRABBERS array (filtered by target device if in single mode)
if [ -n "$HOST_VIDEO_SOURCE" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "host" ]; }; then
    # Strip carriage returns from Windows line endings
    clean_capture_path=$(echo "${HOST_VIDEO_CAPTURE_PATH}" | tr -d '\r')
    # HOST_VIDEO_FPS default is 5, not 2: VNC captures are pinned to fps=5 (freeze
    # detection), so a <5 input upsamples them (duplicate frames -> false freeze). See
    # docs/agent/devices/STREAM.md §4.
    GRABBERS["host"]="$HOST_VIDEO_SOURCE|${HOST_VIDEO_AUDIO:-null}|${clean_capture_path}|${HOST_VIDEO_FPS:-5}"
fi

for i in {1..10}; do
    video_var="DEVICE${i}_VIDEO"
    audio_var="DEVICE${i}_VIDEO_AUDIO"
    capture_var="DEVICE${i}_VIDEO_CAPTURE_PATH"
    fps_var="DEVICE${i}_VIDEO_FPS"

    video_source="${!video_var}"
    audio_device="${!audio_var}"
    capture_path="${!capture_var}"
    fps="${!fps_var}"

    # ADB/scrcpy device (takes priority over VIDEO if both set)
    adb_var="DEVICE${i}_ADB_SERIAL"
    if [ -n "${!adb_var}" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "device$i" ]; }; then
        clean_capture_path=$(echo "${capture_path}" | tr -d '\r')
        GRABBERS["device$i"]="ADB|${!adb_var}|${clean_capture_path}|${fps:-5}"
    elif [ -n "$video_source" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "device$i" ]; }; then
        # Strip carriage returns from Windows line endings
        clean_capture_path=$(echo "${capture_path}" | tr -d '\r')
        GRABBERS["device$i"]="$video_source|${audio_device:-null}|${clean_capture_path}|${fps:-10}"
    fi
done

if [ ${#GRABBERS[@]} -eq 0 ]; then
    echo "ERROR: No devices configured"
    exit 1
fi

echo "🔍 DEBUG: Found ${#GRABBERS[@]} device(s) configured"
for device in "${!GRABBERS[@]}"; do
    echo "  - $device"
done

# Clean up any stale temp files from previous runs
echo "🔍 DEBUG: Cleaning stale temp files..."
rm -f /var/www/html/stream/active_captures.conf.tmp* 2>/dev/null || true

# Single device restart: kill ALL FFmpeg processes for this device
if [ "$SINGLE_DEVICE_MODE" = true ]; then
    echo "🔍 DEBUG: Killing ALL processes for $TARGET_DEVICE..."
    for index in "${!GRABBERS[@]}"; do
        if [ "$index" = "$TARGET_DEVICE" ]; then
            IFS='|' read -r _ _ capture_dir _ <<< "${GRABBERS[$index]}"
            kill_all_ffmpeg_for_device "$capture_dir" "$index"
            break
        fi
    done
    sleep 2  # Extra wait to ensure processes are fully cleaned up
fi

# Note: For "all devices" mode, systemd ExecStartPre handles cleanup

reset_log_if_large() {
  local logfile="$1" max_size_mb=30
  if [ -f "$logfile" ]; then
    local size_mb=$(du -m "$logfile" | cut -f1)
    if [ "$size_mb" -ge "$max_size_mb" ]; then
      > "$logfile"
    fi
  fi
}

get_device_info() {
  local capture_dir="$1"
  local field="$2"  # 'pid' or 'quality'
  local conf_file="/var/www/html/stream/active_captures.conf"
  
  if [ ! -f "$conf_file" ]; then
    echo ""
    return
  fi
  
  local line=$(grep "^${capture_dir}," "$conf_file")
  if [ -n "$line" ]; then
    IFS=',' read -r _ pid quality <<< "$line"
    if [ "$field" = "pid" ]; then
      echo "$pid"
    elif [ "$field" = "quality" ]; then
      echo "$quality"
    fi
  fi
}

get_device_quality() {
  local capture_dir="$1"
  if [ "$SINGLE_DEVICE_MODE" = true ]; then
    echo "$TARGET_QUALITY"
  else
    local quality=$(get_device_info "$capture_dir" "quality")
    if [ -z "$quality" ]; then
      echo "low"  # Default to LOW quality (320:180) for preview/monitoring
    else
      echo "$quality"
    fi
  fi
}

# Function to detect source type (hardware video device or VNC display)
detect_source_type() {
  local source="$1"
  if [[ "$source" =~ ^:[0-9]+$ ]]; then
    echo "x11grab"
  elif [[ "$source" =~ \.(png|jpg|jpeg)$ ]]; then
    echo "imagefile"
  elif [[ "$source" == /dev/* ]]; then
    # Any /dev path: /dev/videoN, port-pinned symlinks like /dev/stb1
    # (see docs/agent/devices/PERSISTENT_DEVICES.md), /dev/v4l/by-path/..., etc.
    echo "v4l2"
  else
    echo "unknown"
  fi
}

# VAAPI hardware-encode detection.
#
# On Intel/AMD hosts (e.g. the Minisforum boxes) the iGPU can encode H.264 in
# hardware, offloading the HLS stream encode off the CPU — important now that
# the stream runs at native fps instead of a hard 5. On the Pi 5 fleet the
# VideoCore VII has NO H.264 encoder, so detection finds no encode entrypoint
# and we transparently fall back to software libx264.
#
# VAAPI_RENDER_NODE holds the render node (e.g. /dev/dri/renderD128) when a
# usable H.264 encode entrypoint exists, else stays empty. Result is cached in
# /tmp (cleared on reboot) so the frequent single-device quality-switch
# restarts don't re-run vainfo every time. We do NOT force LIBVA_DRIVER_NAME:
# modern libva auto-selects iHD (Intel) / radeonsi (AMD) from the PCI id, so
# leaving it unset keeps this portable across both vendors.
VAAPI_RENDER_NODE=""
VAAPI_CACHE="/tmp/vpt_vaapi_render_node"
detect_vaapi() {
  if [ -f "$VAAPI_CACHE" ]; then
    VAAPI_RENDER_NODE="$(cat "$VAAPI_CACHE" 2>/dev/null)"
    [ -n "$VAAPI_RENDER_NODE" ] && echo "✅ VAAPI H.264 encode (cached): $VAAPI_RENDER_NODE"
    return
  fi
  local dev="/dev/dri/renderD128"
  if [ -e "$dev" ] && command -v vainfo >/dev/null 2>&1 \
     && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_vaapi \
     && vainfo --display drm --device "$dev" 2>/dev/null | grep -qE 'VAProfileH264.*VAEntrypointEncSlice'; then
    VAAPI_RENDER_NODE="$dev"
    echo "✅ VAAPI H.264 encode available on $dev — offloading HLS stream encode off CPU"
  else
    echo "ℹ️  No VAAPI H.264 encode entrypoint — using software libx264"
  fi
  echo "$VAAPI_RENDER_NODE" > "$VAAPI_CACHE" 2>/dev/null || true
}

# Function to get VNC display resolution
get_vnc_resolution() {
  local display="$1"
  local resolution=$(xdpyinfo -display "$display" 2>/dev/null | grep dimensions | awk '{print $2}')
  if [ -z "$resolution" ]; then
    resolution="1280x720"
  fi
  echo "$resolution"
}

# Function to reset video device before capture
reset_video_device() {
  local device="$1"
  fuser -k "$device" 2>/dev/null || true
  sleep 1
}

# Kill ALL FFmpeg processes for a specific device (prevents process accumulation)
kill_all_ffmpeg_for_device() {
  local capture_dir="$1"
  local index="$2"
  local capture_pattern="$capture_dir/captures"
  local hot_capture_pattern="$capture_dir/hot/captures"
  
  echo "🔪 Killing FFmpeg for $index..."
  
  # Count processes BEFORE kill (for logging)
  local before_count=$(( $(pgrep -f "$capture_pattern" 2>/dev/null | wc -l) + $(pgrep -f "$hot_capture_pattern" 2>/dev/null | wc -l) ))
  
  if [ "$before_count" -eq 0 ]; then
    echo "✅ No FFmpeg processes found for $index"
    return 0
  fi
  
  echo "   Found $before_count process(es) to kill"
  
  # Kill ONLY this device's FFmpeg processes in either SD mode or RAM hot mode.
  pkill -9 -f "$capture_pattern" 2>/dev/null || true
  pkill -9 -f "$hot_capture_pattern" 2>/dev/null || true
  
  # Wait for cleanup
  sleep 1
  
  # Verify kill succeeded
  local after_count=$(( $(pgrep -f "$capture_pattern" 2>/dev/null | wc -l) + $(pgrep -f "$hot_capture_pattern" 2>/dev/null | wc -l) ))
  
  if [ "$after_count" -eq 0 ]; then
    echo "✅ Successfully killed $before_count FFmpeg process(es) for $index"
  else
    echo "❌ ERROR: $after_count process(es) still alive for $index after kill!"
    echo "   Stuck PIDs:"
    pgrep -f "$capture_pattern" 2>/dev/null || true
    pgrep -f "$hot_capture_pattern" 2>/dev/null || true
    
    # Try one more time with broader match
    pkill -9 -f "$capture_dir" 2>/dev/null || true
    sleep 1
    
    # Final check
    local final_count=$(( $(pgrep -f "$capture_pattern" 2>/dev/null | wc -l) + $(pgrep -f "$hot_capture_pattern" 2>/dev/null | wc -l) ))
    if [ "$final_count" -gt 0 ]; then
      echo "❌ CRITICAL: Could not kill all processes! Manual intervention needed."
    fi
  fi
}

# Clean up playlist files for a specific capture directory
clean_playlist_files() {
  local capture_dir=$1
  echo "Cleaning playlist files in hot storage..."
  # Clean playlists in hot storage (RAM)
  rm -f "$capture_dir/hot/segments/output.m3u8" 2>/dev/null || true
  rm -f "$capture_dir/hot/segments/archive.m3u8" 2>/dev/null || true
}

# Continuous numbering across restarts.
#
# FFmpeg's HLS segment counter and image2 capture counter both reset to 0 on
# every (re)start. A restart therefore rewinds the HLS media sequence and the
# capture filename counter. Consequences observed in production:
#   - browser HLS.js 404s the now-missing high-numbered segments and declares
#     "FFmpeg appears stuck" / shows "Loading stream" until manual refresh;
#   - capture_monitor's LIFO backlog guard mis-reads the jpg rewind as a huge
#     backlog and never closes the freeze incident (fake multi-hour freeze).
#
# Resuming each counter from max(existing index)+1 keeps both monotonic, so a
# real restart is a forward jump the player and monitor both tolerate.
#
# Fail-safe: no files / any unparseable name -> echo 0, i.e. exactly the old
# reset-to-zero behaviour. Never worse than today. Globbing a ~150-file tmpfs
# dir runs once per (re)start, not per frame — cost is negligible.
next_start_number() {
  local dir="$1" prefix="$2" suffix="$3"
  local f base max=-1
  for f in "$dir/${prefix}"*"${suffix}"; do
    base="${f##*/}"; base="${base#"$prefix"}"; base="${base%"$suffix"}"
    [[ "$base" =~ ^[0-9]+$ ]] || continue   # also rejects the literal glob when dir empty
    base=$((10#$base))                        # force base-10 (leading zeros are not octal)
    (( base > max )) && max=$base
  done
  if (( max >= 0 )); then echo $((max + 1)); else echo 0; fi
}


# Setup capture directory structure and detect storage mode
setup_capture_directories() {
  local capture_dir=$1
  
  # Check if hot storage is mounted (RAM mode)
  # Resolve symlinks since mount output uses real paths
  local real_hot_path=$(realpath "$capture_dir/hot" 2>/dev/null || echo "$capture_dir/hot")
  if mount | grep -q "$real_hot_path"; then
    echo "✓ RAM hot storage detected at $capture_dir/hot"
    # Create subdirectories in RAM hot storage
    mkdir -p "$capture_dir/hot/segments"
    mkdir -p "$capture_dir/hot/captures"
    mkdir -p "$capture_dir/hot/thumbnails"
    mkdir -p "$capture_dir/hot/metadata"
    echo "✓ Using RAM mode (99% SD write reduction)"
    return 0  # RAM mode
  else
    echo "⚠️  No RAM hot storage found at $capture_dir/hot"
    echo "   Run: setup_ram_hot_storage.sh to enable RAM mode"
    # Create directories on SD card
    mkdir -p "$capture_dir/segments"
    mkdir -p "$capture_dir/captures"
    mkdir -p "$capture_dir/thumbnails"
    mkdir -p "$capture_dir/metadata"
    echo "✓ Using SD card mode (direct write)"
    return 1  # SD mode
  fi
}

# Shutdown is handled by a single cleanup_all() trap installed before any
# grabber starts (see below). The old per-grabber cleanup() trap was removed:
# it did not exit, and start_grabber re-installed it on every device recycle,
# clobbering cleanup_all — so `systemctl stop` hung until SIGKILL, leaving
# the unit `failed` and (Restart=always ignores explicit stop) stuck down.

# Detect stalled ffmpeg (e.g. MS2109 USB dongle silent URB stall: process alive, holds
# /dev/videoN + ALSA fd, but kernel stops delivering frames — no USB disconnect, no error).
# Signal: /tmp/ffmpeg_output_${index}.log mtime — ffmpeg writes a progress line ~1/s while
# reading input; mtime stops advancing the instant frames stop arriving.
# Action: kill the stale ffmpeg and restart via start_grabber. Reopening the device
# forces VIDIOC_STREAMON from scratch and recovers most MS2109 stalls.
#
# Retry policy:
#  - At most MAX_RESTART_ATTEMPTS restarts, spaced RESTART_SPACING_SEC apart.
#  - Counter resets to 0 when log mtime becomes fresh again (successful recovery).
#  - When cap is reached: device enters DORMANT state — no more restart spam. We keep
#    probing whether /dev/videoN reappeared (cheap `test -c`); on reappearance we clear
#    DORMANT and resume normal restart behavior. Manual resolution: systemctl restart
#    vpt-stream.
STALE_SEC=30
RESTART_SPACING_SEC=60
MAX_RESTART_ATTEMPTS=10
# Runaway-log guard: a grabber fed corrupt input spews decode errors and can
# balloon /tmp/ffmpeg_output_${index}.log to tens of GB, pegging a CPU core and
# filling the SD rootfs (full-disk outage of every service). Healthy logs are a
# few MB over hours, so anything this large means the input is broken.
LOG_RUNAWAY_MB=100
# Flap back-off. An MS2109 grabber on a marginal USB link (long/extension cable,
# over-subscribed controller) streams fine for a few seconds, then browns out
# under capture load and drops off the bus — the kernel re-enumerates it and the
# /dev/videoN minor changes. ffmpeg dies, the log goes stale, and the stale path
# below restarts it ~every RESTART_SPACING_SEC — which reloads the port and
# browns it out again: an endless ~65s re-enumerate loop that also shreds the
# /dev/video* numbering. The plain FAIL_COUNT/DORMANT cap never catches this,
# because the few seconds of successful streaming after each re-enumeration reset
# FAIL_COUNT to 0 so the cap is never reached. Instead we detect the PATTERN:
# FLAP_THRESHOLD restarts inside FLAP_WINDOW_SEC → kill the grabber and leave the
# port IDLE for FLAP_BACKOFF_SEC. An idle MS2109 is low-power and stable, so the
# flap stops; we then attempt ONE clean restart. Root cause is physical — see
# docs/agent/devices/USB_GRABBER_FLAPPING.md.
FLAP_WINDOW_SEC=300
FLAP_THRESHOLD=4
FLAP_BACKOFF_SEC=600

# Cheap presence check for the device source. For v4l2 and imagefile the source is a
# filesystem path so we check the node directly. For ADB (USB serial), x11grab (:0) and
# unknown we return success — watchdog will just attempt restart, which is the right
# behavior when we have no cheap presence signal.
device_present() {
  local source="$1"
  if [[ "$source" == /dev/* ]]; then
    # -c follows symlinks, so /dev/stb1 → /dev/video0 still resolves correctly
    [ -c "$source" ]
  elif [[ "$source" =~ \.(png|jpg|jpeg)$ ]]; then
    [ -r "$source" ]
  else
    return 0
  fi
}

# Flap detector: append `now` to this device's restart history, prune entries
# older than FLAP_WINDOW_SEC, and return the surviving count via $REPLY.
record_restart() {
  local index="$1" now="$2" cutoff=$(( $2 - FLAP_WINDOW_SEC ))
  local ts kept="" count=0
  for ts in ${RESTART_HISTORY[$index]:-} "$now"; do
    if [ "$ts" -gt "$cutoff" ]; then
      kept="$kept $ts"
      count=$((count + 1))
    fi
  done
  RESTART_HISTORY[$index]="${kept# }"
  REPLY=$count
}

# Record a restart attempt; if the device has restarted FLAP_THRESHOLD+ times
# inside FLAP_WINDOW_SEC it's flapping (physical USB fault, not a stall). Kill it
# and arm a FLAP_BACKOFF_SEC idle window instead of restarting. Returns 0 when it
# handled the situation (caller MUST skip its normal restart), 1 otherwise.
maybe_backoff() {
  local index="$1" capture_dir="$2" now="$3"
  record_restart "$index" "$now"
  [ "$REPLY" -lt "$FLAP_THRESHOLD" ] && return 1
  echo "🌀 $index: $REPLY restarts within ${FLAP_WINDOW_SEC}s → USB flapping (re-enumeration under load, not a stall). Killing grabber and backing off ${FLAP_BACKOFF_SEC}s so the port can sit idle and settle. Physical root cause — see docs/agent/devices/USB_GRABBER_FLAPPING.md"
  kill_all_ffmpeg_for_device "$capture_dir" "$index"
  FLAP_UNTIL[$index]=$(( now + FLAP_BACKOFF_SEC ))
  LAST_RESTART_TS[$index]=$now
  return 0
}

check_grabber_health() {
  local now=$(date +%s)
  for index in "${!GRABBERS[@]}"; do
    local log="/tmp/ffmpeg_output_${index}.log"
    [ -f "$log" ] || continue

    IFS='|' read -r source audio_device capture_dir fps <<< "${GRABBERS[$index]}"
    local mtime=$(stat -c %Y "$log" 2>/dev/null || echo 0)
    local age=$(( now - mtime ))
    local fails=${FAIL_COUNT[$index]:-0}

    # Dormant: we exhausted retries. Only wake up if the device node reappears.
    if [ "${DORMANT[$index]:-0}" = "1" ]; then
      if device_present "$source"; then
        echo "✅ $index: $source reappeared — exiting dormant state, resuming restarts"
        FAIL_COUNT[$index]=0
        DORMANT[$index]=0
      else
        continue
      fi
    fi

    # Flap back-off: device is re-enumerating under load; we've killed it and are
    # letting the USB port sit idle to settle. Do nothing until the timer elapses,
    # then reset watchdog state and fall through so it gets ONE clean restart.
    if [ "${FLAP_UNTIL[$index]:-0}" -gt 0 ]; then
      if [ "$now" -lt "${FLAP_UNTIL[$index]}" ]; then
        continue
      fi
      echo "↩️  $index: flap back-off elapsed (${FLAP_BACKOFF_SEC}s idle) — resetting counters, attempting one clean restart"
      FLAP_UNTIL[$index]=0
      RESTART_HISTORY[$index]=""
      FAIL_COUNT[$index]=0
      fails=0
    fi

    # Runaway-log guard. Checked BEFORE the mtime logic on purpose: a spewing
    # ffmpeg writes constantly, so its log mtime stays fresh and the staleness
    # path below would never fire. An oversized log is a critical fault — the
    # input is producing a per-frame error flood. Restart the grabber (re-opens
    # the v4l2 device and truncates the log via reset_log_if_large in
    # start_grabber), reusing the same rate-limit + dormant cap as staleness so
    # a permanently-bad dongle can't restart-loop.
    local size_mb=0
    [ -f "$log" ] && size_mb=$(du -m "$log" 2>/dev/null | cut -f1)
    if [ "${size_mb:-0}" -ge "$LOG_RUNAWAY_MB" ]; then
      local since_last=$(( now - ${LAST_RESTART_TS[$index]:-0} ))
      if [ "$since_last" -ge "$RESTART_SPACING_SEC" ]; then
        if [ "$fails" -ge "$MAX_RESTART_ATTEMPTS" ]; then
          echo "🛑 $index: log runaway (${size_mb}MB) but exhausted $MAX_RESTART_ATTEMPTS restarts — entering dormant; manual fix: check $source capture dongle, then systemctl restart vpt-stream"
          DORMANT[$index]=1
        elif maybe_backoff "$index" "$capture_dir" "$now"; then
          :  # flapping — backed off; skip restart this tick
        else
          local quality=$(get_device_quality "$capture_dir")
          echo "🚨 $index: ffmpeg log runaway ${size_mb}MB ≥ ${LOG_RUNAWAY_MB}MB (corrupt input?) — restarting grabber attempt=$((fails + 1))/$MAX_RESTART_ATTEMPTS (quality=$quality)"
          kill_all_ffmpeg_for_device "$capture_dir" "$index"
          start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$fps" "$quality"
          FAIL_COUNT[$index]=$((fails + 1))
          LAST_RESTART_TS[$index]=$now
        fi
      fi
      continue
    fi

    # Healthy again: reset counter if we had failures and the log is now fresh.
    if [ "$age" -le "$STALE_SEC" ] && [ "$fails" -gt 0 ]; then
      echo "✅ $index recovered (log_age=${age}s) — resetting failure counter (was $fails)"
      FAIL_COUNT[$index]=0
      continue
    fi

    # Stale — consider restarting.
    if [ "$age" -gt "$STALE_SEC" ]; then
      local since_last=$(( now - ${LAST_RESTART_TS[$index]:-0} ))

      # Rate limit: don't restart more than once every RESTART_SPACING_SEC.
      if [ "$since_last" -lt "$RESTART_SPACING_SEC" ]; then
        continue
      fi

      # Cap: after MAX_RESTART_ATTEMPTS failures, go dormant.
      if [ "$fails" -ge "$MAX_RESTART_ATTEMPTS" ]; then
        echo "🛑 $index: exhausted $MAX_RESTART_ATTEMPTS restart attempts — entering dormant state; will auto-resume when $source reappears"
        DORMANT[$index]=1
        continue
      fi

      # Flap guard: convert the Nth rapid restart into an idle back-off instead.
      if maybe_backoff "$index" "$capture_dir" "$now"; then
        continue
      fi

      local quality=$(get_device_quality "$capture_dir")
      echo "⚠️  Stale ffmpeg: $index log_age=${age}s attempt=$((fails + 1))/$MAX_RESTART_ATTEMPTS — restarting (quality=$quality)"
      kill_all_ffmpeg_for_device "$capture_dir" "$index"
      start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$fps" "$quality"
      FAIL_COUNT[$index]=$((fails + 1))
      LAST_RESTART_TS[$index]=$now
    fi
  done
}

# Check if any device needs quality change (called from main loop)
check_quality_changes() {
  local conf_file="/var/www/html/stream/active_captures.conf"
  [ -f "$conf_file" ] || return
  
  # Read config and compare with what's actually running
  while IFS=',' read -r capture_dir pid config_quality; do
    [ -z "$capture_dir" ] && continue
    
    # Find device_id
    local device_id=""
    for index in "${!GRABBERS[@]}"; do
      IFS='|' read -r _ _ dev_capture_dir _ <<< "${GRABBERS[$index]}"
      [ "$dev_capture_dir" = "$capture_dir" ] && device_id="$index" && break
    done
    [ -z "$device_id" ] && continue
    
    # Compare config quality vs running quality
    local running_quality="${RUNNING_QUALITY[$device_id]}"
    
    if [ "$config_quality" != "$running_quality" ]; then
      echo "🔄 Quality change detected: $device_id ($running_quality → $config_quality)"

      # Kill ALL FFmpeg processes for this device (not just the PID from config)
      kill_all_ffmpeg_for_device "$capture_dir" "$device_id"

      # Also kill any ffmpeg matching capture_dir that kill_all_ffmpeg_for_device may have missed
      local remaining=$(pgrep -f "$capture_dir" 2>/dev/null | xargs -I{} sh -c 'ps -p {} -o comm= 2>/dev/null | grep -q ffmpeg && echo {}' || true)
      if [ -n "$remaining" ]; then
        echo "⚠️  Found leftover ffmpeg for $device_id after kill, cleaning up..."
        echo "$remaining" | xargs -r kill -9 2>/dev/null || true
      fi

      sleep 2  # Ensure cleanup complete before restart

      # Restart with new quality
      IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$device_id]}"
      start_grabber "$source" "$audio_device" "$capture_dir" "$device_id" "$input_fps" "$config_quality"
    fi
  done < "$conf_file"
}

start_grabber() {
  local source=$1 audio_device=$2 capture_dir=$3 index=$4 input_fps=$5
  local target_quality=$6  # Optional: if provided, use this quality instead of get_device_quality
  
  # Use target_quality if provided, otherwise fallback to get_device_quality
  local quality=${target_quality:-$(get_device_quality "$capture_dir")}
  local source_type=$(detect_source_type "$source")

  if [ "$source_type" = "unknown" ]; then
    echo "ERROR: Unknown source type for $source"
    return 1
  fi

  # Resolve the HD+ VAAPI gate FIRST, before anything keys off $quality (notably
  # captures_per_segment below, which must match the final segment duration). HD+ is
  # a VAAPI-only tier: on software-only hosts (Pi 5, no H.264 encoder) fall back to
  # HD so libx264 is never asked to do a high-bitrate 720p encode in realtime, and so
  # the capture-counter math doesn't size for 2s segments that won't be produced.
  if [ "$quality" = "hd_plus" ] && [ -z "$VAAPI_RENDER_NODE" ]; then
    echo "ℹ️  hd_plus requested but no VAAPI encoder — falling back to hd"
    quality="hd"
  fi

  if setup_capture_directories "$capture_dir"; then
    local storage_base="$capture_dir/hot"
  else
    local storage_base="$capture_dir"
  fi
  
  local output_segments="$storage_base/segments"
  local output_captures="$storage_base/captures"
  local output_thumbnails="$storage_base/thumbnails"

  clean_playlist_files "$capture_dir"

  # Continuous numbering across restarts, with the SEGMENT counter as the
  # single source of truth and the capture/thumbnail counters DERIVED from it.
  #
  # The getSegmentCapture API maps a segment to its still frame arithmetically:
  #     capture_number = segment_number * captures_per_segment
  # That only holds if the two counters stay locked at exactly that ratio. The
  # old code resumed each counter independently from its own directory's
  # max+1, so the instant one branch lost its files while the other survived
  # (e.g. an encoder crash wiped captures but segments persisted) the counters
  # offset permanently and EVERY getSegmentCapture returned 500. Deriving
  # cap/thumb starts from seg_start makes the invariant true by construction —
  # it cannot desync regardless of what's in the captures dir.
  #
  # captures_per_segment = capture_fps * hls_segment_seconds, per source type:
  #   v4l2:      5 fps captures, 0.4s segments -> 2
  #   x11grab:   5 fps captures, 1s segments   -> 5
  #   ADB/image: input_fps captures, 1s segs   -> input_fps
  # NOTE (v4l2): segments are 0.4s (not 1s) to cut live HLS latency. Captures stay at
  # 5 fps (200ms granularity, required by freeze detection) — they are decoupled from
  # segment duration. The only constraint is captures_per_segment must be an integer,
  # so segment_seconds must be a multiple of 0.2 (5 * 0.4 = 2 ✓; 5 * 0.5 = 2.5 ✗).
  local seg_start cap_start thumb_start captures_per_segment
  case "$source_type" in
    v4l2)          captures_per_segment=2 ;;
    x11grab)       captures_per_segment=5 ;;
    ADB|imagefile) captures_per_segment=$input_fps ;;
    *)             captures_per_segment=5 ;;
  esac
  # HD+ streams in 2s segments (vs the 0.4s live default — see the v4l2 quality block).
  # Captures are UNCHANGED at 5 fps, so the ratio becomes 5*2=10. This is required, not
  # cosmetic: with 2s segments the segment counter advances 5x slower than the 5fps
  # capture counter, so the default ratio 2 would make cap_start REWIND on each restart
  # → capture_monitor reads a fake multi-hour backlog/freeze. 10 keeps it monotonic.
  if [ "$source_type" = "v4l2" ] && [ "$quality" = "hd_plus" ]; then
    captures_per_segment=10
  fi
  seg_start=$(next_start_number "$output_segments" "segment_" ".ts")
  cap_start=$(( seg_start * captures_per_segment ))
  thumb_start=$cap_start
  if [ "$seg_start" -gt 0 ]; then
    echo "↻ Continuous numbering: segments@${seg_start} captures@${cap_start} thumbs@${thumb_start} (captures_per_segment=${captures_per_segment})"
  fi
  # Always prune the prior run's files: with a high -start_number FFmpeg
  # neither overwrites the old files nor (for HLS) tracks them under
  # delete_segments, so without this the RAM tmpfs would leak one run's worth
  # of segments/captures every restart. Pruning unconditionally (cheap no-op
  # on empty dirs) also clears stray captures when segments reset to 0, forcing
  # a clean resync of both counters from zero.
  find "$output_segments"   -maxdepth 1 -name 'segment_*.ts'           -delete 2>/dev/null || true
  find "$output_captures"   -maxdepth 1 -name 'capture_*.jpg'          -delete 2>/dev/null || true
  find "$output_thumbnails" -maxdepth 1 -name 'capture_*_thumbnail.jpg' -delete 2>/dev/null || true


  # ADB/scrcpy path for Android emulators and real devices
  if [ "$source_type" = "ADB" ]; then
    local serial="$source"
    echo "📱 Starting scrcpy→FFmpeg for ADB device: $serial"
    adb connect "$serial" 2>/dev/null || true
    scrcpy --serial "$serial" --no-audio --video-bit-rate 2M --record - --record-format mkv 2>/dev/null \
    | /usr/bin/ffmpeg -y -i pipe:0 \
        -filter_complex "[0:v]fps=$input_fps,split=3[str][cap][thm];[str]scale=320:180:flags=fast_bilinear[streamout];[cap]scale=1280:720:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]scale=320:180:flags=neighbor[thumbout]" \
        -map "[captureout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 -start_number $cap_start "$output_captures/capture_%09d.jpg" \
        -map "[thumbout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 -start_number $thumb_start "$output_thumbnails/capture_%09d_thumbnail.jpg" \
        -map "[streamout]" -c:v libx264 -preset ultrafast -tune zerolatency -b:v 150k -maxrate 200k -bufsize 400k -pix_fmt yuv420p \
        -f hls -hls_time 1 -hls_list_size 150 -hls_flags delete_segments+omit_endlist+split_by_time -lhls 1 \
        -start_number $seg_start -hls_segment_filename "$output_segments/segment_%09d.ts" "$output_segments/output.m3u8" &
    local ffmpeg_pid=$!
    echo "✅ scrcpy→FFmpeg started (PID: $ffmpeg_pid) for $serial"
    return 0
  fi

  if [ "$source_type" = "v4l2" ]; then
    reset_video_device "$source"
  fi

  if [ "$source_type" = "v4l2" ]; then
    # HD+ VAAPI gate already resolved at the top of start_grabber (before
    # captures_per_segment, which must match the final segment duration).
    # 4-tier quality system: LOW (preview) → SD (modal) → HD (user clicks HD) → HD+ (VAAPI watch)
    # Captures always stay at 1280:720 for high-quality detection (zap, freeze, etc)
    if [ "$quality" = "hd_plus" ]; then
      # HD+: VAAPI-only, quality over latency (dedicated fullscreen watch player).
      # Bitrate is sized for 30 fps: bits are per-SECOND, so 30 fps needs ~3x the
      # bitrate of 10 fps to keep the same per-frame clarity (else motion blocks up).
      local stream_scale="1280:720"
      local stream_bitrate="12000k"
      local stream_maxrate="16000k"
      local stream_bufsize="32000k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    elif [ "$quality" = "hd" ]; then
      # HD: Full quality stream for single device focus
      local stream_scale="1280:720"
      local stream_bitrate="1500k"
      local stream_maxrate="1800k"
      local stream_bufsize="3600k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    elif [ "$quality" = "sd" ]; then
      # SD: Medium quality when modal opened (single device)
      local stream_scale="640:360"
      local stream_bitrate="350k"
      local stream_maxrate="400k"
      local stream_bufsize="800k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    else
      # LOW (default): Minimal quality for preview/monitoring (multiple devices)
      local stream_scale="320:180"
      local stream_bitrate="150k"
      local stream_maxrate="200k"
      local stream_bufsize="400k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    fi
    # Stream frame rate + GOP. Default: device capture fps (input_fps) with a 0.4s
    # GOP (fps*0.4 → 4 at 10 fps) so each 0.4s HLS segment starts on a keyframe.
    # HD+ captures at 30 fps for SMOOTH motion — bitrate sets per-frame clarity,
    # frame rate sets fluidity, and the upstream 10 fps was the real ceiling. The
    # [cap]/[thm] detection branches stay pinned to fps=5, so freeze/zap detection
    # is unchanged; idle CPU/GPU headroom on VAAPI hosts makes the extra fps ~free.
    local stream_fps="$input_fps"
    local stream_gop=4
    local stream_tqs=512        # v4l2 input thread queue
    local lhls_flag="-lhls 1"   # low-latency HLS partial segments (live preview)
    local stream_hls_time=0.4   # live tiers: 0.4s segments for low latency
    local stream_hls_list=150   # 150 * 0.4s = 60s DVR window
    # split_by_time cuts segments at an exact wall-clock boundary even mid-GOP, so a
    # segment can start on a P-frame → MSE decode glitch at that boundary (the live
    # tiers accept this for latency). HD+ omits it so HLS splits ON keyframes.
    local stream_hls_flags="delete_segments+omit_endlist+split_by_time"
    if [ "$quality" = "hd_plus" ]; then
      # HD+ is a BUFFERED WATCH stream (player sits ~18s behind live), so latency is
      # irrelevant and we optimize for smooth, efficient, proxy-friendly playback:
      #   2s segments + GOP 60 (= 2s * 30 fps) → one keyframe per segment, 5x fewer
      #   keyframes than the 0.4s/GOP-12 live profile. Big quality-per-bit win (P-frames
      #   instead of constant I-frames), 5x fewer proxy requests, 5x fewer MSE appends.
      # Requires captures_per_segment=10 (set above) to keep the capture counter aligned.
      stream_fps=30
      stream_gop=60     # 2s segment * 30 fps = 60 frames → one keyframe per segment
      stream_hls_time=2 # 2s segments (vs 0.4s live)
      stream_hls_list=30 # 30 * 2s = 60s DVR window (matches the live window)
      stream_tqs=2048   # 3x the frames need a bigger input queue, else frames back up
                        # and audio (alsa, tqs=2048) drifts ahead → A/V desync
      # LHLS partial segments add .tmp-and-rename churn + partial reads that reverse
      # proxies (e.g. a customer CDN edge) serve poorly → freezes. Drop it so the player
      # only ever fetches complete segments. (Player already runs lowLatencyMode:false.)
      lhls_flag=""
      stream_hls_flags="delete_segments+omit_endlist"  # split on keyframes (see above)
    fi
    # Pi5-optimized FFmpeg configuration (real-time streaming priority)
    # Test if audio device is available. Retry: on a restart the previous
    # ffmpeg's USB-audio handle (MS2109) is released slowly, so a single 2s
    # probe can lose the race and doom the device to video-only for the whole
    # process lifetime. Probe up to 3 times (1s apart) before giving up.
    local audio_available=false
    local audio_input_flags=""
    local audio_map_flags=""
    local audio_codec_flags=""
    if [ "$audio_device" != "null" ] && [ -n "$audio_device" ]; then
      local audio_try
      for audio_try in 1 2 3; do
        if timeout 2 arecord -D "$audio_device" -d 1 -f cd /dev/null >/dev/null 2>&1; then
          audio_available=true
          audio_input_flags="-f alsa -thread_queue_size 2048 -async 1 -err_detect ignore_err -i \"$audio_device\""
          audio_map_flags="-map 1:a?"
          audio_codec_flags="-c:a aac -b:a 32k -ar 48000 -ac 2"
          echo "✅ Audio device $audio_device available (probe attempt ${audio_try})"
          break
        fi
        echo "⏳ Audio device $audio_device busy (attempt ${audio_try}/3)"
        [ "$audio_try" -lt 3 ] && sleep 1
      done
      [ "$audio_available" = false ] && echo "⚠️  Audio device $audio_device not available after 3 probes — starting video-only"
    fi

    # Stream-encode path: hardware VAAPI when a render node with an H.264 encode
    # entrypoint was detected (Intel/AMD hosts), else software libx264 (Pi 5).
    # Only the [str] (HLS) branch is offloaded — the [cap]/[thm] mjpeg branches
    # stay on CPU (image2 needs software frames). The VAAPI branch uploads the
    # already-scaled small frame to the GPU (format=nv12,hwupload) and encodes
    # there; -pix_fmt/-preset/-tune/-x264opts are x264-only and must be omitted.
    local vaapi_dev_flag="" stream_filter stream_codec
    if [ -n "$VAAPI_RENDER_NODE" ]; then
      vaapi_dev_flag="-vaapi_device $VAAPI_RENDER_NODE"
      # fps=${stream_fps} FIRST forces constant frame rate: the v4l2 input uses
      # -use_wallclock_as_timestamps, so frames arrive at jittery wall-clock times
      # (VFR). Unevenly-spaced 30 fps reads as stutter even with drop=0; resampling
      # to an even grid here is what makes motion actually smooth. (At 10 fps the
      # jitter is within the 100ms slot and invisible, so this is a no-op there.)
      stream_filter="[str]fps=${stream_fps},scale=${stream_scale}:flags=fast_bilinear,format=nv12,hwupload[streamout]"
      # NOTE: iHD chokes on constrained_baseline encode (VAAPI "internal
      # encoding error 24"). Use the default High profile + default rc, which
      # is what the validated standalone test used. -g keeps a ~0.4s GOP (stream_gop
      # = fps*0.4) so every 0.4s HLS segment starts on a keyframe: 4 at 10 fps, 12 at
      # HD+'s 30 fps. HD+ levers are higher bitrate (scaling block) + higher fps
      # (stream_fps), both at 720p — a large, zero-risk visible quality jump.
      # Deliberately no -bf/-rc_mode here: B-frames and ICQ support vary by driver
      # (iHD vs radeonsi) and tripped the error above.
      stream_codec="-c:v h264_vaapi -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize -g $stream_gop"
    else
      stream_filter="[str]fps=${stream_fps},scale=${stream_scale}:flags=fast_bilinear[streamout]"
      stream_codec="-c:v libx264 -preset ultrafast -tune zerolatency -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize -x264opts keyint=4:min-keyint=4:no-scenecut:bframes=0 -pix_fmt yuv420p -profile:v baseline -level 3.0"
    fi

    # -loglevel error: drop the per-frame info/decoder chatter (a corrupt-input
    # grabber floods it). -stats: keep the ~1/s progress line so the log mtime
    # still advances — check_grabber_health uses that as the liveness signal.
    FFMPEG_CMD="/usr/bin/ffmpeg -loglevel error -stats -y \
      $vaapi_dev_flag \
      -fflags +nobuffer+genpts+flush_packets \
      -use_wallclock_as_timestamps 1 \
      -thread_queue_size $stream_tqs \
      -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate $stream_fps -i $source \
      $audio_input_flags \
      -filter_complex \"[0:v]split=3[str][cap][thm]; \
        $stream_filter; \
        [cap]fps=5,scale=${capture_scale}:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor[thumbout]\" \
      -map \"[streamout]\" $audio_map_flags \
      $stream_codec \
      $audio_codec_flags \
      -f hls -hls_time $stream_hls_time -hls_list_size $stream_hls_list -hls_flags $stream_hls_flags $lhls_flag \
      -start_number $seg_start \
      -hls_segment_filename $output_segments/segment_%09d.ts \
      $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg"

  elif [ "$source_type" = "imagefile" ]; then
    # Image file source (e.g., Android emulator PNG frames updated by vpt-emulator-fifo)
    # IMPORTANT: Do NOT use -stream_loop — ffmpeg caches the file and never re-reads.
    # Instead, pipe `cat` of the source file repeatedly into ffmpeg -f image2pipe.

    # Detect orientation from source image (wait for valid source to avoid boot race)
    local img_dims=""
    local wait_count=0
    while [ -z "$img_dims" ] || [ "$img_dims" = " " ] || [ "$img_dims" = "0 0" ]; do
      img_dims=$(identify -format "%w %h" "$source" 2>/dev/null || echo "")
      if [ -z "$img_dims" ] || [ "$img_dims" = " " ] || [ "$img_dims" = "0 0" ]; then
        wait_count=$((wait_count + 1))
        if [ $wait_count -le 60 ]; then
          echo "Waiting for valid source image ($source)... attempt $wait_count/60"
          sleep 2
        else
          echo "WARNING: Source image not available after 120s, defaulting to landscape"
          img_dims="1920 1080"
          break
        fi
      fi
    done
    local img_w=$(echo "$img_dims" | awk '{print $1}')
    local img_h=$(echo "$img_dims" | awk '{print $2}')
    local orientation="landscape"
    if [ "$img_h" -gt "$img_w" ] 2>/dev/null; then
      orientation="portrait"
    fi
    echo "Detected orientation: $orientation (source: ${img_w}x${img_h})"

    # Quality-based scaling (read from active_captures.conf)
    local thumb_scale="320:180"
    if [ "$orientation" = "portrait" ]; then
      thumb_scale="180:320"
      if [ "$quality" = "hd" ]; then
        local stream_scale="720:1280"; local stream_bitrate="1500k"
      elif [ "$quality" = "sd" ]; then
        local stream_scale="360:640"; local stream_bitrate="350k"
      else
        local stream_scale="180:320"; local stream_bitrate="120k"
      fi
    else
      if [ "$quality" = "hd" ]; then
        local stream_scale="1280:720"; local stream_bitrate="1500k"
      elif [ "$quality" = "sd" ]; then
        local stream_scale="640:360"; local stream_bitrate="350k"
      else
        local stream_scale="320:180"; local stream_bitrate="120k"
      fi
    fi

    echo "Starting ffmpeg: quality=$quality orient=$orientation scale=$stream_scale thumb=$thumb_scale bitrate=$stream_bitrate"

    # Use piped cat loop — re-reads source file each frame
    # The outer while-true loop in run_one_grabber will restart on quality change
    FFMPEG_CMD="(while true; do cat \"$source\" 2>/dev/null || break; sleep 0.2; done) | \
      /usr/bin/ffmpeg -loglevel error -stats -f image2pipe -framerate $input_fps -i - \
      -filter_complex \"[0:v]split=3[str][cap][thm]; \
        [str]scale=${stream_scale}[streamout]; \
        [cap]setpts=PTS-STARTPTS[captureout]; \
        [thm]scale=${thumb_scale}[thumbout]\" \
      -map \"[streamout]\" -c:v libx264 -preset ultrafast -tune zerolatency \
        -g $input_fps -keyint_min $input_fps \
        -b:v ${stream_bitrate} -maxrate ${stream_bitrate} -bufsize $((${stream_bitrate%k} * 2))k \
        -pix_fmt yuv420p \
        -f hls -hls_time 1 -hls_list_size 30 -hls_flags delete_segments \
        -start_number $seg_start \
        -hls_segment_filename $output_segments/segment_%09d.ts \
        $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
        -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
        -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg"

  elif [ "$source_type" = "x11grab" ]; then
    # 3-tier quality system: LOW (preview) → SD (modal opened) → HD (user clicks HD)
    # Captures always stay at 1280:720 for high-quality VNC detection (aligned with v4l2)
    if [ "$quality" = "hd" ]; then
      # HD: Full quality stream for single device focus
      local stream_scale="1280:720"
      local stream_bitrate="1000k"
      local stream_maxrate="1200k"
      local stream_bufsize="2400k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    elif [ "$quality" = "sd" ]; then
      # SD: Medium quality when modal opened (single device)
      local stream_scale="640:360"
      local stream_bitrate="350k"
      local stream_maxrate="400k"
      local stream_bufsize="800k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    else
      # LOW (default): Minimal quality for preview/monitoring (multiple devices)
      local stream_scale="320:180"
      local stream_bitrate="120k"
      local stream_maxrate="150k"
      local stream_bufsize="300k"
      local capture_scale="1280:720"    # Captures at HD for best detection quality
    fi
    
    # X11 access is configured by vncserver.service ExecStartPost
    export DISPLAY="$source"

    # Self-heal PulseAudio (x11grab/VNC desktop only). By design pulse is started
    # by the VNC session's xstartup (install_host.sh), NOT by vpt-stream — so on a
    # fresh VM boot, if the VNC session came up without it (or pulse died), the
    # grabber fails with "Error opening input file default". Only relevant when
    # audio is routed through pulse (default/pulse); ALSA/null sources skip this.
    # `pulseaudio --start` is idempotent: a no-op if a daemon for this user already
    # runs, so this strictly self-heals the missing case (it does NOT replace the
    # VNC-coupled daemon when one is present).
    if { [ "$audio_device" = "default" ] || [ "$audio_device" = "pulse" ]; } \
         && ! pactl info >/dev/null 2>&1; then
      echo "⚠️  PulseAudio not reachable — starting user daemon" >&2
      pulseaudio --start --exit-idle-time=-1 >/dev/null 2>&1 || true
      for _ in 1 2 3 4 5; do pactl info >/dev/null 2>&1 && break; sleep 0.3; done
    fi

    # Find PulseAudio socket for this user session
    local pulse_socket=""
    # Prefer the active server from pactl (most reliable when multiple pulse daemons exist)
    local pactl_server=$(pactl info 2>/dev/null | awk -F': ' '/Server String/ {print $2}' | head -1)
    if [ -n "$pactl_server" ]; then
      if [[ "$pactl_server" == unix:* ]]; then
        pulse_socket="${pactl_server#unix:}"
      elif [[ "$pactl_server" == /* ]]; then
        pulse_socket="$pactl_server"
      fi
    fi
    # Fallback: choose only user-owned socket to avoid selecting root's pulse socket
    if [ -z "$pulse_socket" ]; then
      pulse_socket=$(find /tmp/pulse-* -name "native" -user "$(id -u)" 2>/dev/null | head -1)
    fi
    if [ -n "$pulse_socket" ]; then
      export PULSE_SERVER="unix:${pulse_socket}"
    fi
    
    local resolution=$(get_vnc_resolution "$source")

    # Pi5-optimized X11grab configuration (real-time streaming priority)
    # Build audio input if audio is enabled (not null and not empty)
    # For VNC with PulseAudio: use "default" or "pulse" to connect to PulseAudio server
    local audio_input=""
    local audio_codec=""
    local audio_map=""
    if [ "$audio_device" != "null" ] && [ -n "$audio_device" ]; then
      # If audio_device is "default" or "pulse", use PulseAudio
      if [ "$audio_device" = "default" ] || [ "$audio_device" = "pulse" ]; then
        # Use PulseAudio default source/sink monitor. "pulse" as input name is invalid on some hosts.
        audio_input="-f pulse -thread_queue_size 2048 -i default"
      else
        # Otherwise use as ALSA device
        audio_input="-f alsa -thread_queue_size 2048 -i \"$audio_device\""
      fi
      audio_codec="-c:a aac -b:a 64k -ar 44100 -ac 2"
      audio_map="-map 1:a?"
    fi

    FFMPEG_CMD="DISPLAY=\"$source\" /usr/bin/ffmpeg -loglevel error -stats -y \
      -probesize 32M -analyzeduration 0 \
      -draw_mouse 0 -show_region 0 \
      -f x11grab -video_size $resolution -framerate $input_fps -i $source \
      $audio_input \
      -filter_complex \"[0:v]split=3[str][cap][thm]; \
        [str]scale=${stream_scale}:flags=neighbor[streamout]; \
        [cap]fps=5,scale=${capture_scale}:flags=neighbor,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor[thumbout]\" \
      -map \"[streamout]\" $audio_map \
      -c:v libx264 -preset ultrafast -tune zerolatency \
      -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize \
      $audio_codec \
      -pix_fmt yuv420p -profile:v baseline -level 3.0 \
      -x264opts keyint=${input_fps}:min-keyint=${input_fps}:no-scenecut:bframes=0:ref=1:me=dia:subme=0 \
      -f hls -hls_time 1 -hls_list_size 150 -hls_flags delete_segments+omit_endlist+split_by_time -lhls 1 \
      -start_number $seg_start \
      -hls_segment_filename $output_segments/segment_%09d.ts \
      $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 10 -f image2 -atomic_writing 1 \
      -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 10 -f image2 -atomic_writing 1 \
      -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg"
  else
    echo "ERROR: Unsupported source type: $source_type"
    return 1
  fi

  local FFMPEG_LOG="/tmp/ffmpeg_output_${index}.log"
  > "$FFMPEG_LOG"
  reset_log_if_large "$FFMPEG_LOG"

  # Filter known noise out of FFmpeg stderr without affecting process PID.
  # "failed to delete old segment" fires every time the archiver deletes a .ts
  # segment before FFmpeg's own HLS rotation does — harmless race, but it spams
  # ~50 lines/min per device and masks real issues during log review. See
  # docs/agent/devices/FFMPEG_TROUBLESHOOT.md "Known noise".
  # Using process substitution keeps $! = FFmpeg's PID (grep runs in a sub-shell).
  #
  # ⚠️  The `tr '\r' '\n'` is LOAD-BEARING — do not remove it. With
  # `-loglevel error -stats`, a *healthy* FFmpeg writes nothing but the
  # `-stats` progress line, which is carriage-return-terminated (`\r`, no
  # newline). `grep` is line-oriented: it never emits a `\r`-only "line", so
  # without the `tr` the log stays 0 bytes and its mtime never advances on a
  # healthy stream. check_grabber_health uses that mtime as its liveness
  # signal (STALE_SEC), so it would (and did) declare every healthy grabber
  # "Stale" and kill+restart it every ~30-70s in an endless round-robin —
  # which in turn rewinds the HLS segment + capture-jpg counters and produces
  # the "FFmpeg appears stuck" frontend 404s and fake multi-hour freezes.
  # Converting `\r`→`\n` turns each stats refresh into a real line so the log
  # mtime advances ~1/s exactly as the watchdog assumes. stdbuf -oL keeps tr
  # from block-buffering its pipe to grep.
  eval $FFMPEG_CMD > "$FFMPEG_LOG" 2> >(stdbuf -oL tr '\r' '\n' | grep -v --line-buffered "failed to delete old segment" >> "$FFMPEG_LOG") &
  local FFMPEG_PID=$!
  
  # Update active_captures.conf with CSV format
  update_active_captures "$capture_dir" "$FFMPEG_PID" "$quality"
  
  # Track running quality in memory
  RUNNING_QUALITY[$index]="$quality"
  
  echo "✅ Started $index PID:$FFMPEG_PID quality:$quality"
  # NOTE: do NOT install a SIGTERM trap here. start_grabber runs in the main
  # shell (not a subshell) and is re-invoked from the steady-state loop to
  # recycle a device; a trap set here would clobber the global cleanup_all
  # handler with one that never exits. Shutdown is owned by cleanup_all only.
}

update_active_captures() {
  local capture_dir="$1"
  local pid="$2"
  local quality="$3"
  
  echo "🔍 DEBUG: update_active_captures called with:"
  echo "  capture_dir: $capture_dir"
  echo "  pid: $pid"
  echo "  quality: $quality"
  
  local conf_file="/var/www/html/stream/active_captures.conf"
  local temp_file="${conf_file}.tmp.$$"
  
  # Simple atomic update - no locking needed
  # Create temp file (umask 0000 ensures 666 permissions)
  > "$temp_file"
  
  if [ -f "$conf_file" ]; then
    # Remove old entry for this capture_dir
    grep -v "^${capture_dir}," "$conf_file" > "$temp_file" 2>/dev/null || true
  fi
  
  # Add new entry
  echo "${capture_dir},${pid},${quality}" >> "$temp_file"
  
  # Atomic move with explicit permissions
  mv "$temp_file" "$conf_file"
  chmod 666 "$conf_file"
  
  echo "🔍 DEBUG: Updated active_captures.conf:"
  cat "$conf_file"
}

# Initialize active captures file - ALWAYS clean start for proper permissions
ACTIVE_CAPTURES_CONF="/var/www/html/stream/active_captures.conf"

if [ "$SINGLE_DEVICE_MODE" = false ]; then
  # Remove old file completely to avoid permission conflicts
  rm -f "$ACTIVE_CAPTURES_CONF" 2>/dev/null || true
  
  # Create fresh file with explicit 666 permissions (world read/write for all services)
  > "$ACTIVE_CAPTURES_CONF"
  chmod 666 "$ACTIVE_CAPTURES_CONF"
  
  echo "✅ Created fresh active_captures.conf at $ACTIVE_CAPTURES_CONF with 666 permissions"
  echo "Starting ${#GRABBERS[@]} devices"
else
  # Single device mode: ensure file exists with correct permissions
  if [ ! -f "$ACTIVE_CAPTURES_CONF" ]; then
    > "$ACTIVE_CAPTURES_CONF"
    chmod 666 "$ACTIVE_CAPTURES_CONF"
  fi
fi

# Kill stale ffmpeg processes from previous runs before starting new ones
echo "🧹 Checking for stale ffmpeg processes..."
stale_count=0
for index in "${!GRABBERS[@]}"; do
  IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$index]}"
  if [ -n "$capture_dir" ]; then
    local_pids=$(pgrep -f "$capture_dir" 2>/dev/null | xargs -I{} sh -c 'ps -p {} -o comm= 2>/dev/null | grep -q ffmpeg && echo {}' || true)
    if [ -n "$local_pids" ]; then
      local_count=$(echo "$local_pids" | wc -l | tr -d ' ')
      echo "🔪 Found $local_count stale ffmpeg process(es) for $index ($capture_dir)"
      echo "$local_pids" | xargs -r kill -9 2>/dev/null || true
      stale_count=$((stale_count + local_count))
    fi
  fi
done
if [ "$stale_count" -gt 0 ]; then
  echo "🧹 Killed $stale_count stale ffmpeg process(es). Waiting for cleanup..."
  sleep 2
else
  echo "✅ No stale ffmpeg processes found"
fi

# Graceful shutdown handler for systemd stop/restart. Installed BEFORE any
# grabber starts so SIGTERM during startup or a steady-state device recycle
# is always handled by a fast, exiting handler — keeping `systemctl stop`
# well within TimeoutStopSec (no SIGKILL, no `failed`, no stuck-down unit).
cleanup_all() {
  echo "🛑 Received shutdown signal - cleaning up..."
  pkill -9 -f '/usr/bin/ffmpeg' 2>/dev/null || true
  # Clean up temp files (no sudo needed with umask 0000)
  rm -f /var/www/html/stream/active_captures.conf.tmp* 2>/dev/null || true
  echo "✅ Cleanup complete - exiting"
  exit 0
}
trap cleanup_all SIGTERM SIGINT

# arecord (alsa-utils) is what each grabber uses to probe whether its audio
# device is live before adding the -f alsa input. If it's missing, EVERY probe
# fails and all devices silently start video-only — a confusing failure that
# looks like an audio-device problem. Warn loudly once at startup instead.
if ! command -v arecord >/dev/null 2>&1; then
  echo "⚠️  arecord not found (install 'alsa-utils') — audio probe will fail for all devices; grabbers will start VIDEO-ONLY"
fi

# Detect hardware video encode once before starting any grabber (result cached).
detect_vaapi

# Start grabbers (serially to avoid race condition in active_captures.conf)
echo "🔍 DEBUG: Starting grabbers..."
for index in "${!GRABBERS[@]}"; do
  IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$index]}"
  echo "🔍 DEBUG: Starting grabber for $index (source: $source)"
  start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$input_fps"
  # Note: Starts serially (no &), takes ~1-2s total for 4 devices
  # FFmpeg processes themselves run in background inside start_grabber
done

echo "✅ All grabbers started"

if [ "$SINGLE_DEVICE_MODE" = true ]; then
  echo "🔍 DEBUG: Single device mode - exiting"
  exit 0
fi

# cleanup_all + trap already installed above (before grabbers started).

# Keep script running for systemd (Type=simple with Restart=always)
# The script must stay alive or systemd will restart it continuously
echo "🔍 DEBUG: Keeping service alive (systemd Type=simple)"
echo "Press Ctrl+C or send SIGTERM to stop gracefully"

HEALTH_INTERVAL=30  # run check_grabber_health every N iterations of the 1s sleep
tick=0
while true; do
  # Check if any device quality changed or died
  check_quality_changes

  tick=$((tick + 1))
  if [ $((tick % HEALTH_INTERVAL)) -eq 0 ]; then
    check_grabber_health
  fi

  sleep 1  # Check every second
done
