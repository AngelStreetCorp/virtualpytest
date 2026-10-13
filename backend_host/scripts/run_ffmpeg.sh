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
# Read KEY=VALUE literally instead of `source`-ing the file. To bash,
# `DEVICE3_NAME=Sauce S23 FE` is an assignment followed by a COMMAND, so sourcing
# both left the variable EMPTY and ran `S23 FE` ("S23: command not found" in the
# journal). Every device whose name contains a space was affected — DEVICE2_NAME
# on an ordinary phone slot was empty here too. A value is data: it is never
# expanded and never executed.
_load_env_file() {
  local _line _k _v
  while IFS= read -r _line; do
    [[ "$_line" != *=* ]] && continue
    _k="${_line%%=*}"; _v="${_line#*=}"
    [[ "$_k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    _v="${_v%%[[:space:]]#*}"                 # drop a ' # inline comment', as source did
    _v="${_v%"${_v##*[![:space:]]}"}"         # trim trailing whitespace
    if [[ ${#_v} -ge 2 && ( ( "${_v:0:1}" == '"' && "${_v: -1}" == '"' ) \
                         || ( "${_v:0:1}" == "'" && "${_v: -1}" == "'" ) ) ]]; then
      _v="${_v:1:${#_v}-2}"                   # strip surrounding quotes, as source did
    fi
    export "$_k=$_v"
  done < <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep -v '^x')
}
_load_env_file
echo "✅ .env loaded successfully"

# TASK-31: helpers the GRABBERS loop calls at parse time. They MUST stay above that
# loop: bash resolves a call when it runs, so a definition further down is
# "command not found" at startup and every override / YouTube slot is skipped.

# TASK-31 follow-up: runtime URL override for the new RTSPController / videofile controller.
# Reads active_rtsp_url.conf for the given capture_dir. CSV format: <capture>,<url>[,<yt>].
# Returns the URL on stdout (or the YouTube watch URL when $2 = yt), or empty if no
# override. Empty means "use the env / DEVICE*_VIDEO".
get_rtsp_url_state() {
  local capture_dir="$1"
  local conf_file="/var/www/html/stream/active_rtsp_url.conf"
  # An unset DEVICE{i}_VIDEO_CAPTURE_PATH must not match: grep -F "," hits the first
  # line, which made every unconfigured slot 5..30 a phantom grabber with capture_dir
  # "" whose kill_all_ffmpeg_for_device (pkill -f "/captures") killed EVERY device's
  # ffmpeg on each source switch (BUG-0285).
  if [ -z "$capture_dir" ] || [ ! -f "$conf_file" ]; then
    return
  fi
  local line=$(grep -F "${capture_dir}," "$conf_file" 2>/dev/null | head -1)
  [ -z "$line" ] && return
  IFS=',' read -r _ url yt <<< "$line"
  if [ "$2" = "yt" ]; then echo "$yt"; else echo "$url"; fi
}

# TASK-31 follow-up: runtime file-path override for VideoFileStreamController.
# Reads active_video_path.conf. CSV format: <capture>,<local_path>[,<restart token>].
# Returns the path on stdout (or, with "restart" as $2, the token), empty if none.
# The token (TASK-50) is any string: changing it restarts the device's ffmpeg on the
# same file, so the film plays again from second 0.
get_video_path_state() {
  local capture_dir="$1"
  local conf_file="/var/www/html/stream/active_video_path.conf"
  if [ -z "$capture_dir" ] || [ ! -f "$conf_file" ]; then  # see get_rtsp_url_state
    return
  fi
  local line=$(grep -F "${capture_dir}," "$conf_file" 2>/dev/null | head -1)
  [ -z "$line" ] && return
  IFS=',' read -r _ path token <<< "$line"
  if [ "$2" = "restart" ]; then echo "$token"; else echo "$path"; fi
}

# YouTube source (TASK-31): DEVICE{i}_YOUTUBE_URL, or field 3 of active_rtsp_url.conf.
# The link is a video (watch?v=ID, youtu.be/ID) or a playlist (any URL with list=ID).
# The link is stable; what ffmpeg plays is the signed googlevideo URL yt-dlp resolves it
# to, and that URL dies ~6 h later (expire= in it). So the YouTube state is kept per device
# and re-resolved by the main loop, through the same kill + start_grabber as a source switch:
#   - YOUTUBE_REFRESH_MARGIN_SEC (default 600) before expire=, resume at the current
#     position (-ss) with a fresh URL: one ~3-4 s capture gap every ~6 h.
#   - ffmpeg exits (restart_ended_hls): near the end of the video = it ended, play the next
#     playlist entry (wrap to the first = loop), or the same video again; earlier = it died
#     (403, network), resume at the position with a fresh URL.
#   - the watchdog restarts a stalled YouTube device with a fresh URL too.
# Steady-state cost: integer compares per YouTube device per tick, no fork.
# yt-dlp needs to be installed (pip install yt-dlp); DRM streams fail to resolve.
YOUTUBE_REFRESH_MARGIN_SEC=${YOUTUBE_REFRESH_MARGIN_SEC:-600}
YOUTUBE_END_SLACK_SEC=15        # exit within this of the video's duration = it ended
declare -A YT_SRC=()       # device -> YouTube link as configured (video or playlist)
declare -A YT_DIR=()       # device -> capture_dir (now-playing file)
declare -A YT_IDS=()       # device -> playlist video ids, space-separated; empty = one video
declare -A YT_POS=()       # device -> index in YT_IDS of the entry playing
declare -A YT_VIDEO=()     # device -> watch URL of the video playing
declare -A YT_EXPIRE=()    # device -> unix-ts the resolved URL expires (0 = unknown)
declare -A YT_DURATION=()  # device -> duration of the video playing in s (0 = unknown/live)
declare -A YT_SEEK=()      # device -> offset (s) the next start_grabber seeks to, used once;
                           # unset = resume at the current position (e.g. an SD/HD switch)
declare -A YT_STARTED=()   # device -> unix-ts the video was at 0 s (position = now - this)

# Resolve the current entry of $1 to a playable URL in REPLY. A playlist entry that does
# not resolve (private / deleted video) is skipped. Returns 1 when nothing resolves.
youtube_resolve() {
  local index="$1" out url duration video tries=1 n=0
  local -a ids=(${YT_IDS[$index]})
  n=${#ids[@]}
  [ "$n" -gt 0 ] && tries=$n
  while [ "$tries" -gt 0 ]; do
    tries=$((tries - 1))
    if [ "$n" -gt 0 ]; then
      video="https://www.youtube.com/watch?v=${ids[${YT_POS[$index]}]}"
    else
      video="${YT_SRC[$index]}"
    fi
    # -f caps the pick at H.264 <=480p <=30fps: yt-dlp's default best is 2160p60 AV1,
    # which a Pi decodes in software at ~0.45x realtime (4 fps out of 10 = laggy stream).
    # 480p30 decodes at ~2.4x on a Pi 4; 720p30 would be ~1.1x, no headroom next to the
    # other grabbers. The capture is scaled down anyway. --no-playlist: a watch?v=X&list=Y
    # link resolves video X only (the playlist itself is walked by YT_IDS).
    out=$(timeout 60 yt-dlp --no-warnings --no-progress --no-playlist \
          -f 'bv*[vcodec^=avc1][height<=480][fps<=30]/b' --print duration --print urls "$video" 2>/dev/null)
    duration=$(sed -n 1p <<< "$out")
    url=$(sed -n '2,$p' <<< "$out" | grep -m1 '^http')
    if [ -n "$url" ]; then
      YT_VIDEO[$index]="$video"
      [[ "$duration" =~ ^[0-9]+ ]] && YT_DURATION[$index]=${BASH_REMATCH[0]} || YT_DURATION[$index]=0
      if [[ "$url" =~ [?\&/]expire[=/]([0-9]+) ]]; then YT_EXPIRE[$index]=${BASH_REMATCH[1]}; else YT_EXPIRE[$index]=0; fi
      local where="" ; [ "$n" -gt 0 ] && where=" $(( YT_POS[$index] + 1 ))/$n"
      echo "▶️  $index: YouTube $video${where} (duration ${YT_DURATION[$index]}s, URL expires $(date -d "@${YT_EXPIRE[$index]}" '+%F %T' 2>/dev/null))"
      [ -n "${YT_DIR[$index]}" ] && echo "$video${where}" > "${YT_DIR[$index]}/youtube_now_playing.txt" 2>/dev/null
      REPLY="$url"
      return 0
    fi
    echo "ERROR: $index: yt-dlp could not resolve $video (private? DRM? region-locked?)" >&2
    [ "$n" -gt 0 ] && YT_POS[$index]=$(( (YT_POS[$index] + 1) % n ))
  done
  return 1
}

# Point device $1 at YouTube link $2 (capture_dir $3) from its start: list the playlist if
# the link has list=, start at its v= entry, resolve. Playable URL in REPLY.
youtube_set_source() {
  local index="$1" link="$2" capture_dir="$3" list="" vid="" ids i
  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "ERROR: $index: YouTube link $link set but yt-dlp is not installed. Install with: pip install yt-dlp" >&2
    return 1
  fi
  YT_SRC[$index]="$link"; YT_DIR[$index]="$capture_dir"
  YT_IDS[$index]=""; YT_POS[$index]=0; YT_SEEK[$index]=0
  [[ "$link" =~ [?\&]list=([A-Za-z0-9_-]+) ]] && list=${BASH_REMATCH[1]}
  [[ "$link" =~ [?\&]v=([A-Za-z0-9_-]+) ]] && vid=${BASH_REMATCH[1]}
  if [ -n "$list" ]; then
    ids=$(timeout 120 yt-dlp --no-warnings --flat-playlist --print id \
          "https://www.youtube.com/playlist?list=$list" 2>/dev/null | grep -E '^[A-Za-z0-9_-]{11}$' | tr '\n' ' ')
    if [ -n "$ids" ]; then
      YT_IDS[$index]="${ids% }"
      local -a arr=($ids)
      for i in "${!arr[@]}"; do [ "${arr[$i]}" = "$vid" ] && YT_POS[$index]=$i && break; done
      echo "📃 $index: YouTube playlist $list: ${#arr[@]} videos, starting at $(( YT_POS[$index] + 1 ))"
    else
      echo "⚠️  $index: YouTube playlist $list did not list (private? bad id?) — playing the link as one video" >&2
    fi
  fi
  youtube_resolve "$index"
}

# Forget device $1's YouTube state (its source is no longer a YouTube link).
youtube_clear() {
  local index="$1"
  [ -n "${YT_DIR[$index]:-}" ] && rm -f "${YT_DIR[$index]}/youtube_now_playing.txt"
  unset "YT_SRC[$index]" "YT_DIR[$index]" "YT_IDS[$index]" "YT_POS[$index]" "YT_VIDEO[$index]" \
        "YT_EXPIRE[$index]" "YT_DURATION[$index]" "YT_SEEK[$index]" "YT_STARTED[$index]"
}

declare -A GRABBERS=()
declare -A RUNNING_QUALITY=()  # Track what quality each device is actually running
declare -A FAIL_COUNT=()       # Watchdog: consecutive failed restarts per device
declare -A LAST_RESTART_TS=()  # Watchdog: unix-ts of last restart attempt per device
declare -A DORMANT=()          # Watchdog: "1" when retry cap exhausted; auto-exits on device reappear
declare -A RESTART_HISTORY=()  # Watchdog: space-separated unix-ts of recent restarts (flap detector)
declare -A FLAP_UNTIL=()       # Watchdog: unix-ts until which a flapping device is left idle (0 = not flapping)
declare -A HLS_LOOP_PID=()     # Looping HLS device -> ffmpeg PID, restarted when the playlist ends
declare -A HLS_LOOP_START=()   # Looping HLS device -> unix-ts that ffmpeg started

# Build GRABBERS array (filtered by target device if in single mode).
# STREAM_TYPE[name] holds the optional DEVICE{name}_STREAM_TYPE override (TASK-31).
# When set, start_grabber skips autodetect and uses this type directly.
declare -A STREAM_TYPE=()
# Device -> which runtime source override it honours (BUG-0488): "url" (active_rtsp_url.conf,
# written by RTSPStreamController: rtsp_video, tello), "path" (active_video_path.conf, written by
# VideoFileStreamController: local_video), or unset = none. Both files are keyed by capture dir
# only and outlive .env edits, so a capture dir reassigned to a camera / HDMI device would
# otherwise keep playing the old file or URL.
declare -A OVERRIDE_KIND=()
override_kind_for_model() {
  case "$1" in
    rtsp_video|tello) echo url ;;
    local_video) echo path ;;
  esac
}
if [ -n "$HOST_VIDEO_SOURCE" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "host" ]; }; then
    # Strip carriage returns from Windows line endings
    clean_capture_path=$(echo "${HOST_VIDEO_CAPTURE_PATH}" | tr -d '\r')
    # No runtime source override: the host (VNC) controller never writes one (BUG-0488).
    # HOST_VIDEO_FPS default is 5, not 2: VNC captures are pinned to fps=5 (freeze
    # detection), so a <5 input upsamples them (duplicate frames -> false freeze). See
    # docs/agent/devices/STREAM.md §4.
    GRABBERS["host"]="$HOST_VIDEO_SOURCE|${HOST_VIDEO_AUDIO:-null}|${clean_capture_path}|${HOST_VIDEO_FPS:-5}"
    [ -n "$HOST_STREAM_TYPE" ] && STREAM_TYPE["host"]="$HOST_STREAM_TYPE"
fi

for i in {1..30}; do
    video_var="DEVICE${i}_VIDEO"
    audio_var="DEVICE${i}_VIDEO_AUDIO"
    capture_var="DEVICE${i}_VIDEO_CAPTURE_PATH"
    fps_var="DEVICE${i}_VIDEO_FPS"
    stream_type_var="DEVICE${i}_STREAM_TYPE"
    youtube_var="DEVICE${i}_YOUTUBE_URL"

    video_source="${!video_var}"
    audio_device="${!audio_var}"
    capture_path="${!capture_var}"
    fps="${!fps_var}"
    stream_type="${!stream_type_var}"
    youtube_url="${!youtube_var}"

    # TASK-31 follow-up: check for runtime URL / file-path overrides. These come
    # from RTSPController.set_url() and VideoFileStreamController.load_or_download()
    # which write to active_rtsp_url.conf / active_video_path.conf. The watcher
    # picks them up on its next 1 s tick and replaces the source for the matching
    # capture_dir. This loop runs once per (re)start, so we merge the override
    # here so even a fresh start_grabber uses the latest URL.
    # An override replaces the env source, so its type is autodetected rather than
    # taken from DEVICE{i}_STREAM_TYPE (which described the env source).
    model_var="DEVICE${i}_MODEL"
    override_kind=$(override_kind_for_model "${!model_var}")
    [ -n "$override_kind" ] && OVERRIDE_KIND["device$i"]="$override_kind"
    url_override=""; path_override=""
    [ "$override_kind" = "url" ] && url_override=$(get_rtsp_url_state "$capture_path")
    [ "$override_kind" = "path" ] && path_override=$(get_video_path_state "$capture_path")
    if [ -z "$override_kind" ] && [ -n "$(get_rtsp_url_state "$capture_path")$(get_video_path_state "$capture_path")" ]; then
        echo "Device${i}: ignoring leftover source override for $capture_path (model ${!model_var:-unset} does not take one)"
    fi
    if [ -n "$url_override" ]; then
        echo "Device${i}: applying runtime URL override → $url_override"
        video_source="$url_override"
        youtube_url=$(get_rtsp_url_state "$capture_path" yt)
        stream_type=""
    fi
    if [ -n "$path_override" ]; then
        echo "Device${i}: applying runtime file-path override → $path_override"
        video_source="$path_override"
        youtube_url=""
        stream_type="videofile"
    fi

    # TASK-31: if DEVICE{i}_YOUTUBE_URL is set, resolve it via yt-dlp and use that as
    # the source. The resolved URL is fed into DEVICE{i}_VIDEO so the rest of the
    # pipeline (autodetect, FFmpeg input) treats it like any other HLS source.
    if [ -n "$youtube_url" ]; then
        youtube_set_source "device$i" "$youtube_url" "$(echo "${capture_path}" | tr -d '\r')" || {
            echo "ERROR: DEVICE${i}: yt-dlp resolution failed for $youtube_url"
            continue
        }
        video_source="$REPLY"
        # The resolved URL is HLS or a direct media URL — force the stream type so the
        # autodetect does not mis-classify a .m3u8 returned by YouTube.
        [ -z "$stream_type" ] && stream_type="hls"
    fi

    # VIDEO wins over ADB_SERIAL: an Android TV behind an HDMI grabber sets ADB_SERIAL only
    # for remote control, and must keep its HDMI capture (BUG-0344). scrcpy is the video
    # source only for a device with no VIDEO (emulator, phone on USB).
    adb_var="DEVICE${i}_ADB_SERIAL"
    if [ -n "$video_source" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "device$i" ]; }; then
        # Strip carriage returns from Windows line endings
        clean_capture_path=$(echo "${capture_path}" | tr -d '\r')
        GRABBERS["device$i"]="$video_source|${audio_device:-null}|${clean_capture_path}|${fps:-10}"
        [ -n "$stream_type" ] && STREAM_TYPE["device$i"]="$stream_type"
    elif [ -n "${!adb_var}" ] && { [ "$SINGLE_DEVICE_MODE" = false ] || [ "$TARGET_DEVICE" = "device$i" ]; }; then
        clean_capture_path=$(echo "${capture_path}" | tr -d '\r')
        # source = the serial, typed ADB: start_grabber reads field 1 as the source
        # (the old "ADB|serial|..." made it "ADB" -> "Unknown source type for ADB").
        GRABBERS["device$i"]="${!adb_var}|null|${clean_capture_path}|${fps:-5}"
        STREAM_TYPE["device$i"]="ADB"
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

# Function to detect source type (hardware video device, VNC display, network stream, or video file)
detect_source_type() {
  local source="$1"
  if [[ "$source" =~ ^:[0-9]+$ ]]; then
    echo "x11grab"
  elif [[ "$source" =~ ^(rtsp|rtsps|udp):// ]]; then
    # RTSP / RTSPS — IP cameras, public test streams, IPTV. udp:// is a raw live feed the
    # device pushes to this host (a Tello drone's H.264 on udp://0.0.0.0:11111, TASK-32).
    echo "rtsp"
  elif [[ "$source" =~ \.m3u8($|\?) ]] || [[ "$source" =~ ^(http|https)://.*\.m3u8($|\?) ]]; then
    # HLS playlist — public HLS endpoints, .m3u8 URLs.
    echo "hls"
  elif [[ "$source" =~ ^(http|https)://.*\.(mp4|mkv|mov|ts|webm|avi|flv|m4v)($|\?) ]]; then
    # Plain HTTP(S) video file URL — treat as a video file (single-shot, no looping the file itself).
    echo "videofile"
  elif [[ "$source" =~ \.(png|jpg|jpeg)$ ]]; then
    echo "imagefile"
  elif [[ "$source" == /dev/* ]]; then
    # Any /dev path: /dev/videoN, port-pinned symlinks like /dev/stb1
    # (see docs/agent/devices/PERSISTENT_DEVICES.md), /dev/v4l/by-path/..., etc.
    echo "v4l2"
  elif [[ "$source" =~ \.(mp4|mkv|mov|ts|webm|avi|flv|m4v)$ ]]; then
    # Local video file. Loop semantics controlled by active_loop.conf (TASK-31).
    echo "videofile"
  else
    echo "unknown"
  fi
}

# 0 when HLS URL $1 is a VOD media playlist (#EXT-X-ENDLIST) of MPEG-TS segments (no
# #EXT-X-MAP), the one case -stream_loop -1 loops gaplessly (measured on ffmpeg 5.1, Pi 5:
# Apple bipbop gear2, Mux pts_shift variant). A master playlist is excluded: ffmpeg 5.1
# cannot seek it back to the start ("Operation not permitted") and exits at the end.
# 1 for master, fMP4, live, or a playlist that cannot be read. One curl per start.
hls_is_ts_vod() {
  local body
  body=$(curl -fsL --max-time 5 "$1" 2>/dev/null) || return 1
  grep -q '#EXT-X-ENDLIST' <<< "$body" && ! grep -q -e '#EXT-X-MAP' -e '#EXT-X-STREAM-INF' <<< "$body"
}

# Per-device loop flag (TASK-31). Reads active_loop.conf (capture_dir,flag). Defaults to 1
# (loop) when the file does not exist or has no entry for this device. RTSP / HLS / videofile
# sources honour this; v4l2 / x11grab / imagefile do not.
get_loop_state() {
  local capture_dir="$1"
  local conf_file="/var/www/html/stream/active_loop.conf"
  if [ ! -f "$conf_file" ]; then
    echo "1"
    return
  fi
  local line=$(grep "^${capture_dir}," "$conf_file" 2>/dev/null)
  if [ -z "$line" ]; then
    echo "1"
    return
  fi
  IFS=',' read -r _ flag <<< "$line"
  echo "${flag:-1}"
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

# Map spec for a network source's embedded audio. `0:a?` maps an audio stream even
# when it carries no packets (e.g. a TS whose PMT declares AAC but never sends any:
# sample_rate=0, channels=0); its encoder then never opens and the HLS muxer writes
# NOTHING, so the watchdog restart-loops the device. The `u` specifier ("usable":
# codec + sample rate known) skips such a stream, but its optional spelling differs:
# ffmpeg 5.1 takes `0:a:u?`, ffmpeg 7.1 rejects that ("Trailing garbage") and wants
# `0:a:u:?`. Probe both once on a silent lavfi source (~0.1-0.3s at startup).
AUDIO_MAP_SPEC="0:a?"
detect_audio_map() {
  local spec
  for spec in '0:a:u?' '0:a:u:?'; do
    if /usr/bin/ffmpeg -hide_banner -loglevel quiet -f lavfi -i anullsrc -t 0.05 -map "$spec" -f null - </dev/null 2>/dev/null; then
      AUDIO_MAP_SPEC="$spec"
      break
    fi
  done
  echo "ℹ️  Network-source audio map: -map $AUDIO_MAP_SPEC"
}

# Function to resolve the Xauthority file backing a VNC/TigerVNC display.
#
# vpt-vnc.service runs TigerVNC with Environment=HOME=/var/lib/vpt_user, so the MIT-MAGIC-COOKIE-1
# for display :1 lives in /var/lib/vpt_user/.Xauthority. vpt-stream.service runs this script as the
# same vpt_user but WITHOUT overriding HOME, so systemd gives it /home/vpt_user — a different home
# that has no .Xauthority. Xlib then has no cookie for :1 and every x11grab input dies with
# "Authorization required, but no authorization protocol specified" / "Cannot open display :1".
#
# Resolution order: explicit XAUTHORITY -> the -auth path of the live X server -> the VNC home ->
# $HOME. The X server's own -auth argument is authoritative, so prefer it over guessing a path.
setup_x11_auth() {
    # An XAUTHORITY already exported and readable wins — do not second-guess the caller.
    if [ -n "${XAUTHORITY:-}" ] && [ -r "${XAUTHORITY}" ]; then
        return 0
    fi

    local display="${1:-}"
    [ -z "$display" ] && display="${DISPLAY:-}"
    [ -z "$display" ] && return 0
    # Strip an optional :N so it can be matched against the X server command line.
    local disp_num="${display#:}"

    local auth_file=""
    if [ -n "$disp_num" ]; then
        # Ask the live X server which authority file it is using (-auth), if it exposes one.
        auth_file=$(pgrep -a -f "Xtigervnc.*:${disp_num}\b|Xorg.*:${disp_num}\b|Xvfb.*:${disp_num}\b" 2>/dev/null \
            | grep -oE '\-auth [^ ]+' | head -1 | cut -d' ' -f2)
    fi

    # Fall back to the VNC home used by vnc.service, then the script's own HOME.
    if [ -z "$auth_file" ] || [ ! -r "$auth_file" ]; then
        for candidate in "/var/lib/vpt_user/.Xauthority" "${HOME:-}/.Xauthority"; do
            [ -n "$candidate" ] && [ "$candidate" != "/.Xauthority" ] && [ -r "$candidate" ] && { auth_file="$candidate"; break; }
        done
    fi

    if [ -n "$auth_file" ] && [ -r "$auth_file" ]; then
        export XAUTHORITY="$auth_file"
        echo "🔐 X11 auth: XAUTHORITY=$auth_file"
    else
        echo "⚠️  X11 auth: no readable .Xauthority found for $display — x11grab may fail" >&2
    fi
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
  unset "HLS_LOOP_PID[$index]"  # an intentional kill: restart_ended_hls must not undo it

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
  
  # Wait for the kernel to reap them (SIGKILL: normally a few ms). Poll instead of a
  # fixed sleep so a restart does not add a dead second to the capture gap.
  local _w
  for _w in 1 2 3 4 5 6 7 8 9 10; do
    [ $(( $(pgrep -f "$capture_pattern" 2>/dev/null | wc -l) + $(pgrep -f "$hot_capture_pattern" 2>/dev/null | wc -l) )) -eq 0 ] && break
    sleep 0.1
  done
  
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

# Delete <prefix>N<suffix> files in <dir> whose N >= <start>: the ones the new run
# would overwrite or that would sit numerically ahead of it (a counter rewind for
# capture_monitor). Files below <start> are older frames in the same monotonic
# sequence, so they are kept: the monitor and the UI keep the last frames across a
# restart, and the archiver's newest-N rotation (cleanup_hot_files) removes them.
prune_from_number() {
  local dir="$1" prefix="$2" suffix="$3" start="$4"
  local f base
  for f in "$dir/${prefix}"*"${suffix}"; do
    base="${f##*/}"; base="${base#"$prefix"}"; base="${base%"$suffix"}"
    [[ "$base" =~ ^[0-9]+$ ]] || continue
    (( 10#$base >= start )) && rm -f "$f"
  done
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
# Output-stall guard: how long a RUNNING grabber may go without writing a segment
# before we treat it as down. Segments are sub-second, so anything beyond a few
# tens of seconds means the input stopped delivering frames. Kept above STALE_SEC
# so a grabber that is merely slow to produce its first segment after a restart
# is never caught by it.
OUTPUT_STALL_SEC=60
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
# filesystem path so we check the node directly. For ADB (USB serial), x11grab (:0),
# rtsp / hls (network) and unknown we return success — watchdog will just attempt restart,
# which is the right behavior when we have no cheap presence signal.
device_present() {
  local source="$1"
  if [[ "$source" == /dev/* ]]; then
    # -c follows symlinks, so /dev/stb1 → /dev/video0 still resolves correctly
    [ -c "$source" ]
  elif [[ "$source" =~ \.(png|jpg|jpeg)$ ]]; then
    [ -r "$source" ]
  elif [[ "$source" =~ \.(mp4|mkv|mov|ts|webm|avi|flv|m4v)$ ]]; then
    # Local video file (TASK-31) — readable? otherwise no point trying.
    [ -r "$source" ]
  else
    # rtsp / hls / x11grab / ADB / http(s) / unknown → return success, no cheap signal.
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

# One guarded restart of a grabber the watchdog has judged unhealthy, whatever the
# symptom was: rate limit, dormant cap and flap back-off are applied here so every
# detector shares exactly the same policy. $reason is echoed in the messages.
# Returns 0 when it restarted, 1 when it declined (rate-limited, dormant or backed off).
restart_unhealthy_grabber() {
  local index="$1" source="$2" audio_device="$3" capture_dir="$4" fps="$5" now="$6" reason="$7"
  local fails=${FAIL_COUNT[$index]:-0}
  local since_last=$(( now - ${LAST_RESTART_TS[$index]:-0} ))

  # Rate limit: don't restart more than once every RESTART_SPACING_SEC.
  [ "$since_last" -lt "$RESTART_SPACING_SEC" ] && return 1

  # Cap: after MAX_RESTART_ATTEMPTS failures, go dormant.
  if [ "$fails" -ge "$MAX_RESTART_ATTEMPTS" ]; then
    echo "🛑 $index: $reason but exhausted $MAX_RESTART_ATTEMPTS restarts — entering dormant; will auto-resume when $source reappears. Manual fix: check the $source capture dongle, then systemctl restart vpt-stream"
    DORMANT[$index]=1
    return 1
  fi

  # Flap guard: convert the Nth rapid restart into an idle back-off instead. USB device
  # nodes only: the pattern is a grabber browning out and re-enumerating. A network /
  # file source restarting often is a source problem; the rate limit and cap above apply.
  if [[ "$source" == /dev/* ]]; then
    maybe_backoff "$index" "$capture_dir" "$now" && return 1
  fi

  local quality=$(get_device_quality "$capture_dir")
  echo "⚠️  $index: $reason — restarting attempt=$((fails + 1))/$MAX_RESTART_ATTEMPTS (quality=$quality)"
  # YouTube: a stall is usually the signed URL refused (403), so restart with a fresh one.
  if [ -n "${YT_SRC[$index]:-}" ]; then
    youtube_at_end "$index" && YT_SEEK[$index]=0
    if youtube_resolve "$index"; then
      source="$REPLY"
      GRABBERS[$index]="$source|$audio_device|$capture_dir|$fps"
    fi
  fi
  kill_all_ffmpeg_for_device "$capture_dir" "$index"
  start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$fps" "$quality"
  FAIL_COUNT[$index]=$((fails + 1))
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
      restart_unhealthy_grabber "$index" "$source" "$audio_device" "$capture_dir" "$fps" "$now" \
        "ffmpeg log runaway ${size_mb}MB ≥ ${LOG_RUNAWAY_MB}MB (corrupt input?)"
      continue
    fi

    # Output-stall guard, and the mirror image of the runaway case above. An ffmpeg
    # whose INPUT stalls keeps printing its progress line every second — same frame
    # number, forever — so the log mtime stays fresh, the log never grows enough to
    # be a runaway, and the staleness path below never fires. Meanwhile not one
    # segment is written. That is how vpt-pi1/S21x stayed dead for ~67h with a
    # perfectly healthy-looking grabber (frame=2441384 frozen, no manifest) until a
    # human restarted the service. A capture that produces nothing IS down, however
    # healthy the process looks, so measure the OUTPUT and not the process.
    local seg_dir="$capture_dir/hot/segments"
    [ -d "$seg_dir" ] || seg_dir="$capture_dir/segments"
    local newest_seg
    newest_seg=$(ls -t "$seg_dir"/*.ts 2>/dev/null | head -1)
    if [ -n "$newest_seg" ]; then
      local seg_mtime=$(stat -c %Y "$newest_seg" 2>/dev/null || echo "$now")
      local seg_age=$(( now - seg_mtime ))
      if [ "$seg_age" -gt "$OUTPUT_STALL_SEC" ]; then
        restart_unhealthy_grabber "$index" "$source" "$audio_device" "$capture_dir" "$fps" "$now" \
          "no segment written for ${seg_age}s (input stalled; log looks alive)"
        continue
      fi
    fi

    # Healthy again: reset counter if we had failures and the log is now fresh.
    if [ "$age" -le "$STALE_SEC" ] && [ "$fails" -gt 0 ]; then
      echo "✅ $index recovered (log_age=${age}s) — resetting failure counter (was $fails)"
      FAIL_COUNT[$index]=0
      continue
    fi

    # Stale — the log itself stopped moving.
    if [ "$age" -gt "$STALE_SEC" ]; then
      restart_unhealthy_grabber "$index" "$source" "$audio_device" "$capture_dir" "$fps" "$now" \
        "stale ffmpeg log_age=${age}s"
    fi
  done
}

# Check if any device needs quality change (called from main loop)
# HLS loop (LOOP=1, see start_grabber): ffmpeg exits at the end of a VOD playlist;
# restart it right away instead of leaving a ~60s hole for the watchdog. Idle cost is
# one `kill -0` per looping HLS device per tick. An ffmpeg that dies within
# HLS_LOOP_MIN_RUN_SEC (bad URL, upstream down) is left to the rate-limited watchdog
# so a broken source can't restart every second.
HLS_LOOP_MIN_RUN_SEC=20
restart_ended_hls() {
  local index ran source audio_device capture_dir input_fps
  for index in "${!HLS_LOOP_PID[@]}"; do
    kill -0 "${HLS_LOOP_PID[$index]}" 2>/dev/null && continue
    unset "HLS_LOOP_PID[$index]"
    ran=$(( $(date +%s) - ${HLS_LOOP_START[$index]:-0} ))
    if [ -n "${YT_SRC[$index]:-}" ] && youtube_at_end "$index"; then
      youtube_ended "$index"  # even a video shorter than HLS_LOOP_MIN_RUN_SEC moves on
      continue
    fi
    if [ "$ran" -lt "$HLS_LOOP_MIN_RUN_SEC" ]; then
      echo "⚠️  $index: HLS ffmpeg exited after ${ran}s — leaving the restart to the watchdog"
      continue
    fi
    if [ -n "${YT_SRC[$index]:-}" ]; then
      youtube_ended "$index"
      continue
    fi
    echo "🔁 $index: HLS playlist ended after ${ran}s — restarting it (loop)"
    IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$index]}"
    start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$input_fps" "${RUNNING_QUALITY[$index]}"
  done
}

# Restart YouTube device $1 at offset $2 s with a freshly resolved URL ($3 = reason).
# Returns 1, leaving the running ffmpeg alone, when nothing resolves.
youtube_restart() {
  local index="$1" seek="$2" reason="$3" source audio_device capture_dir input_fps
  echo "🔄 $index: $reason — restarting at ${seek}s with a fresh YouTube URL"
  if ! youtube_resolve "$index"; then
    YT_EXPIRE[$index]=$(( $(date +%s) + YOUTUBE_REFRESH_MARGIN_SEC + 60 ))  # retry in ~60 s
    return 1
  fi
  YT_SEEK[$index]=$seek
  IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$index]}"
  kill_all_ffmpeg_for_device "$capture_dir" "$index"
  GRABBERS[$index]="$REPLY|$audio_device|$capture_dir|$input_fps"
  start_grabber "$REPLY" "$audio_device" "$capture_dir" "$index" "$input_fps" "${RUNNING_QUALITY[$index]}"
}

# The YouTube ffmpeg of device $1 exited: the video ended (next playlist entry, wrapping to
# the first, or the same video again) or it died mid-video (resume with a fresh URL).
youtube_ended() {
  local index="$1" n
  if ! youtube_at_end "$index"; then
    youtube_restart "$index" "$REPLY" "YouTube ffmpeg exited at ${REPLY}s of ${YT_DURATION[$index]}s (URL expired? network?)"
    return
  fi
  local -a ids=(${YT_IDS[$index]})
  n=${#ids[@]}
  if [ "$n" -gt 0 ]; then
    YT_POS[$index]=$(( (YT_POS[$index] + 1) % n ))
    youtube_restart "$index" 0 "YouTube video ended — playlist entry $(( YT_POS[$index] + 1 ))/$n"
  else
    youtube_restart "$index" 0 "YouTube video ended — looping it"
  fi
}

# 0 when device $1's video is (about) at its end; its position in s goes to REPLY.
# Position = wall time since the video was at 0 s (ffmpeg reads it with -re).
youtube_at_end() {
  local index="$1" now duration=${YT_DURATION[$1]:-0}
  printf -v now '%(%s)T' -1
  REPLY=$(( now - ${YT_STARTED[$index]:-$now} ))
  [ "$duration" -gt 0 ] && [ $(( REPLY + YOUTUBE_END_SLACK_SEC )) -ge "$duration" ]
}

# Re-resolve every YouTube device whose URL expires within YOUTUBE_REFRESH_MARGIN_SEC,
# resuming where it is. Called every tick: integer compares only.
check_youtube_refresh() {
  local index now
  printf -v now '%(%s)T' -1
  for index in "${!YT_EXPIRE[@]}"; do
    [ "${YT_EXPIRE[$index]}" -gt 0 ] || continue
    [ "$now" -lt $(( YT_EXPIRE[$index] - YOUTUBE_REFRESH_MARGIN_SEC )) ] && continue
    youtube_restart "$index" $(( now - ${YT_STARTED[$index]:-$now} )) \
      "YouTube URL expires in $(( YT_EXPIRE[$index] - now ))s"
  done
}

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

      # No settle sleep (it was 2 s): kill_all_ffmpeg_for_device waits until the old ffmpeg
      # is gone, closing the v4l2 node with it, and a slow USB-audio release is covered by
      # the audio probe's retries. Every second here is black WEB/HLS after a quality click.

      # Restart with new quality
      IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$device_id]}"
      start_grabber "$source" "$audio_device" "$capture_dir" "$device_id" "$input_fps" "$config_quality"
    fi
  done < "$conf_file"
}

# Runtime source switch (TASK-31), same pattern as the SD/HD switch above:
# /host/av/setUrl and /host/av/loadVideo write active_rtsp_url.conf /
# active_video_path.conf, and only the device whose entry changed gets its ffmpeg
# restarted. Idle cost is two stat calls per tick; the files are read only when one
# of them changed.
SOURCE_CONFS="/var/www/html/stream/active_rtsp_url.conf /var/www/html/stream/active_video_path.conf"
SOURCE_CONFS_MTIME=""
declare -A SOURCE_SPEC=()  # device -> "<url>,<yt>|<path>|<restart token>" override last applied

# Only the override kind the device honours (OVERRIDE_KIND) counts; the rest reads as empty.
source_spec_for() {
  local capture_dir="$1" kind="${OVERRIDE_KIND[$2]}"
  case "$kind" in
    url) echo "$(get_rtsp_url_state "$capture_dir"),$(get_rtsp_url_state "$capture_dir" yt)||" ;;
    path) echo ",|$(get_video_path_state "$capture_dir")|$(get_video_path_state "$capture_dir" restart)" ;;
    *) echo ",||" ;;
  esac
}

init_source_specs() {
  SOURCE_CONFS_MTIME=$(stat -c %Y $SOURCE_CONFS 2>/dev/null | tr '\n' ' ')
  local device_id capture_dir
  for device_id in "${!GRABBERS[@]}"; do
    IFS='|' read -r _ _ capture_dir _ <<< "${GRABBERS[$device_id]}"
    SOURCE_SPEC[$device_id]=$(source_spec_for "$capture_dir" "$device_id")
  done
}

check_source_changes() {
  local mtime
  mtime=$(stat -c %Y $SOURCE_CONFS 2>/dev/null | tr '\n' ' ')
  [ "$mtime" = "$SOURCE_CONFS_MTIME" ] && return
  SOURCE_CONFS_MTIME="$mtime"

  local device_id source audio_device capture_dir input_fps spec url yt path new_source new_type
  for device_id in "${!GRABBERS[@]}"; do
    IFS='|' read -r source audio_device capture_dir input_fps <<< "${GRABBERS[$device_id]}"
    spec=$(source_spec_for "$capture_dir" "$device_id")
    [ "$spec" = "${SOURCE_SPEC[$device_id]}" ] && continue
    SOURCE_SPEC[$device_id]="$spec"

    IFS='|' read -r url path _ <<< "$spec"
    IFS=',' read -r url yt <<< "$url"
    new_type=""
    if [ -n "$path" ]; then
      new_source="$path"; new_type="videofile"
    elif [ -n "$yt" ]; then
      youtube_set_source "$device_id" "$yt" "$capture_dir" || { echo "ERROR: $device_id: yt-dlp failed for $yt, source unchanged"; continue; }
      new_source="$REPLY"
      new_type="hls"
    elif [ -n "$url" ]; then
      new_source="$url"  # type autodetected (rtsp / hls / http video file)
    else
      continue  # override removed: keep the running source until the next restart
    fi

    [ -z "$yt" ] && youtube_clear "$device_id"
    echo "🔄 Source change detected: $device_id → ${new_source:0:120}"
    # No settle sleep: kill_all_ffmpeg_for_device waits until the old ffmpeg is gone,
    # and these sources (file / network) have no device node to release.
    kill_all_ffmpeg_for_device "$capture_dir" "$device_id"
    GRABBERS[$device_id]="$new_source|$audio_device|$capture_dir|$input_fps"
    if [ -n "$new_type" ]; then STREAM_TYPE[$device_id]="$new_type"; else unset "STREAM_TYPE[$device_id]"; fi
    start_grabber "$new_source" "$audio_device" "$capture_dir" "$device_id" "$input_fps" "${RUNNING_QUALITY[$device_id]}"
  done
}

# Point this process at the user's PulseAudio daemon, starting it if needed.
# By design pulse is started by the VNC session's xstartup (install_host.sh), NOT by
# vpt-stream — so on a fresh VM boot, if the session came up without it (or pulse died),
# the grabber fails with "Error opening input file default". `pulseaudio --start` is
# idempotent: a no-op when a daemon for this user already runs, so this strictly
# self-heals the missing case. Used by both the VNC (x11grab) and emulator (imagefile)
# grabbers; ALSA/null sources skip it.
ensure_pulse_server() {
  local audio_device="$1"
  [ "$audio_device" = "default" ] || [ "$audio_device" = "pulse" ] || return 0

  # Fixed endpoints first. unix:/run/vpt-pulse/native is the emulator host's own daemon
  # (vpt-pulse.service, setup/proxmox/vm/runner/enable_emulator_audio.sh) — the one the
  # emulator plays into. tcp:127.0.0.1:4713 is the module install_host.sh adds to default.pa
  # and the VNC xstartup uses. Resolving through $HOME comes last: vpt-vnc runs with
  # HOME=/var/lib/vpt_user, vpt-stream with /home/vpt_user, each HOME grows its own daemon,
  # and recording from the wrong one is silence from an empty null sink.
  local candidate
  for candidate in unix:/run/vpt-pulse/native tcp:127.0.0.1:4713; do
    if pactl -s "$candidate" info >/dev/null 2>&1; then
      export PULSE_SERVER="$candidate"
      return 0
    fi
  done

  if ! pactl info >/dev/null 2>&1; then
    echo "⚠️  PulseAudio not reachable — starting user daemon" >&2
    pulseaudio --start --exit-idle-time=-1 >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5; do pactl info >/dev/null 2>&1 && break; sleep 0.3; done
  fi

  # Find PulseAudio socket for this user session.
  # Prefer the active server from pactl (most reliable when multiple pulse daemons exist)
  local pulse_socket=""
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
}

start_grabber() {
  local source=$1 audio_device=$2 capture_dir=$3 index=$4 input_fps=$5
  local target_quality=$6  # Optional: if provided, use this quality instead of get_device_quality
  
  # Use target_quality if provided, otherwise fallback to get_device_quality
  local quality=${target_quality:-$(get_device_quality "$capture_dir")}
  local source_type
  if [ -n "${STREAM_TYPE[$index]:-}" ]; then
    source_type="${STREAM_TYPE[$index]}"
  else
    source_type=$(detect_source_type "$source")
  fi

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
  # TASK-79 Phase D: the RTSP publish path used by MediaMTX for the WebRTC/WHEP
  # bridge. storage_base is /var/www/html/stream/capture1/hot; the parent
  # /var/www/html/stream/capture1 is the device folder, so we take dirname
  # twice to land on 'capture1'. MediaMTX listens on :8554 and exposes the
  # path as WHEP on :8889.
  local output_basename="$(basename "$(dirname "$storage_base")")"
  # TASK-48: always-current latest frame, written by every grabber beside the thumbnails.
  # RAM mode: output_thumbnails is hot (tmpfs). SD mode has no hot dir (creating one would
  # flip is_ram_mode), so it sits in the live thumbnails dir. nginx try_files checks cold
  # first, so a RAM-mode cold latest.jpg would shadow the live one: never leave one behind.
  local latest_jpg="$output_thumbnails/latest.jpg"
  [ "$storage_base" != "$capture_dir" ] && rm -f "$capture_dir/thumbnails/latest.jpg"

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
  # TASK-79: live tier is 0.4 s segments on every source type. Captures stay at 5 fps
  # (independent of segment duration, required by freeze detection), so the ratio
  # is 5 fps × 0.4 s = 2 captures per segment for every non-v4l2 branch. The v4l2
  # branch is already 2; everything else dropped from 5 to 2 alongside the 1 s → 0.4 s
  # segment switch below.
  case "$source_type" in
    v4l2)          captures_per_segment=2 ;;
    x11grab|ADB|rtsp|hls|videofile) captures_per_segment=2 ;;
    imagefile)     captures_per_segment=4 ;;   # 0.8 s segments x ~5 fps captures (BUG-0491)
    *)             captures_per_segment=2 ;;
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
  # Prune the prior run's segments: with a high -start_number FFmpeg's HLS muxer
  # does not track them under delete_segments, so the RAM tmpfs would leak one run's
  # worth of segments every restart.
  find "$output_segments"   -maxdepth 1 -name 'segment_*.ts'           -delete 2>/dev/null || true
  # Captures/thumbnails: keep everything numbered below cap_start (BUG-0285). Wiping
  # them left the folder empty until the new ffmpeg wrote its first frame, so
  # capture_monitor had nothing to analyse and the UI lost its latest frames. The
  # archiver's newest-N rotation bounds them, so nothing leaks. Only files at or above
  # cap_start go: the new run would overwrite them, or they would sit ahead of it
  # (segments reset to 0 -> cap_start 0 -> everything goes, as before).
  prune_from_number "$output_captures"   "capture_" ".jpg"           "$cap_start"
  prune_from_number "$output_thumbnails" "capture_" "_thumbnail.jpg" "$cap_start"


  # ADB/scrcpy path for Android emulators and real devices
  if [ "$source_type" = "ADB" ]; then
    local serial="$source"
    echo "📱 Starting scrcpy→FFmpeg for ADB device: $serial"
    adb connect "$serial" 2>/dev/null || true
    scrcpy --serial "$serial" --no-audio --video-bit-rate 2M --record - --record-format mkv 2>/dev/null \
    | /usr/bin/ffmpeg -y -i pipe:0 \
        -filter_complex "[0:v]fps=$input_fps,split=3[str][cap][thm];[str]scale=320:180:flags=fast_bilinear[streamout];[cap]scale=1280:720:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]scale=320:180:flags=neighbor,split=2[thumbout][latestout]" \
        -map "[captureout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 -start_number $cap_start "$output_captures/capture_%09d.jpg" \
        -map "[thumbout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 -start_number $thumb_start "$output_thumbnails/capture_%09d_thumbnail.jpg" \
        -map "[latestout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -update 1 -atomic_writing 1 "$latest_jpg" \
        -map "[streamout]" -c:v libx264 -preset ultrafast -tune zerolatency -b:v 150k -maxrate 200k -bufsize 400k -pix_fmt yuv420p \
        -x264opts "keyint=$((input_fps*2/5)):min-keyint=$((input_fps*2/5)):no-scenecut:bframes=0" \
        -f hls -hls_time 0.4 -hls_list_size 375 -hls_delete_threshold 375 -hls_flags delete_segments+omit_endlist+split_by_time+program_date_time -lhls 1 \
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
    # 0.4s GOP above 10 fps (24 at 60, 8 at 20); 4 at <=10 fps keeps Pis and VNC unchanged.
    local stream_gop=$(( stream_fps > 10 ? (stream_fps * 2 + 4) / 5 : 4 ))
    local stream_tqs=512        # v4l2 input thread queue
    local stream_hls_time=0.4   # live tiers: 0.4s segments for low latency
    local stream_hls_list=300   # 300 * 0.4s = 120s DVR window (the live slider caps at 150s)
    # Every HLS writer here also passes -hls_delete_threshold = its list size: ffmpeg keeps that
    # many segments past the playlist before delete_segments removes them. The archiver merges
    # "the oldest 60s" into each 1-min MP4; with the default threshold (1) ffmpeg deleted those
    # very files mid-merge and the whole minute was lost from the 10-min archive chunk (BUG-0230).
    # ffmpeg never keeps more past the playlist than the playlist's own duration, whatever the
    # threshold (measured on 5.1: list 10 + threshold 30 leaves 22 on disk, not 40), so the
    # time on disk can only grow with the list. At 150 + 150 (120s) a finished minute survived
    # 60-120s and a late archiver cycle lost part of it; 300 + 300 (240s) gives it ~3-4 min
    # (BUG-0297). The 1s-segment writers below keep 150 + 150 = 300s. RAM: the archiver deletes
    # what it merges, so the extra ~300 x 85KB = ~25MB per device is only used while it is
    # behind. HOT_LIMITS['segments'] in hot_cold_archiver.py must stay above 2 x list.
    # split_by_time cuts segments at an exact wall-clock boundary even mid-GOP, so a
    # segment can start on a P-frame → MSE decode glitch at that boundary (the live
    # tiers accept this for latency). HD+ omits it so HLS splits ON keyframes.
    local stream_hls_flags="delete_segments+omit_endlist+split_by_time+program_date_time"
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
      stream_hls_list=30 # 30 * 2s = 60s DVR window; 60 * 2s = 120s on disk. Not raised with the
                         # live tiers (BUG-0297): at 12M a 2s segment is ~3MB, 60 more = ~180MB of hot
      stream_tqs=2048   # 3x the frames need a bigger input queue, else frames back up
                        # and audio (alsa, tqs=2048) drifts ahead → A/V desync
      stream_hls_flags="delete_segments+omit_endlist+program_date_time"  # split on keyframes (see above)
    fi
    # Pi5-optimized FFmpeg configuration (real-time streaming priority)
    # Test if audio device is available (0.1 s read: -s 4410 at 44.1 kHz; opening the
    # device is the test, a full second only delayed every start). Retry: on a restart the previous
    # ffmpeg's USB-audio handle (MS2109) is released slowly, so a single 2s
    # probe can lose the race and doom the device to video-only for the whole
    # process lifetime. Probe up to 3 times (1s apart) before giving up.
    local audio_available=false
    local audio_input_flags=""
    local audio_map_flags=""
    local audio_codec_flags=""
    # WEBRTC_ENABLED=false (host .env): no Opus encode and no RTSP slave for MediaMTX,
    # so WEB falls back to HLS. For hosts where the extra output is too much load.
    local webrtc_enabled=true
    case "${WEBRTC_ENABLED:-true}" in false|0|no|off) webrtc_enabled=false ;; esac
    # HOST_PROFILE=lite (one device on a 1 GB board, TASK-83): HLS only (no MediaMTX there), and
    # one thread for the MJPEG decoder, the filter graph and every encoder. Measured on vpt-pi1:
    # 31 threads / 78 MB private -> 1 thread / 51 MB at the same CPU; 10 fps keeps up easily.
    local lite_in_threads="" lite_out_threads="" lite_graph_threads=""
    if [ "${HOST_PROFILE:-}" = "lite" ]; then
      webrtc_enabled=false
      lite_in_threads="-threads 1"
      lite_out_threads="-threads 1"
      lite_graph_threads="-filter_complex_threads 1"
    fi
    if [ "$audio_device" != "null" ] && [ -n "$audio_device" ]; then
      local audio_try
      for audio_try in 1 2 3; do
        if timeout 2 arecord -D "$audio_device" -s 4410 -f cd /dev/null >/dev/null 2>&1; then
          audio_available=true
          audio_input_flags="-f alsa -thread_queue_size 2048 -async 1 -err_detect ignore_err -i \"$audio_device\""
          # Two audio encodes of the same input: AAC (output stream 1) for HLS, Opus
          # (stream 2) for the RTSP/WebRTC slave — WebRTC cannot carry AAC.
          if [ "$webrtc_enabled" = true ]; then
            audio_map_flags="-map 1:a? -map 1:a?"
            audio_codec_flags="-c:a:0 aac -b:a:0 32k -c:a:1 libopus -b:a:1 32k -ar 48000 -ac 2"
          else
            audio_map_flags="-map 1:a?"
            audio_codec_flags="-c:a aac -b:a 32k -ar 48000 -ac 2"
          fi
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
      # -bf 0: this one encode also feeds WebRTC (tee below), which rejects B-frames.
      # Validated on vpt-mf1 at 60 fps (perf/webrtc-vaapi-fps 97c280981). Still no
      # -rc_mode: ICQ support varies by driver (iHD vs radeonsi).
      stream_codec="-c:v h264_vaapi -bf 0 -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize -g $stream_gop"
    else
      stream_filter="[str]fps=${stream_fps},scale=${stream_scale}:flags=fast_bilinear[streamout]"
      stream_codec="-c:v libx264 -preset ultrafast -tune zerolatency -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize -x264opts keyint=${stream_gop}:min-keyint=${stream_gop}:no-scenecut:bframes=0 -pix_fmt yuv420p -profile:v baseline -level 3.0"
    fi

    # HLS + RTSP (WebRTC, TASK-79) outputs: ONE encode, fanned out by the tee muxer.
    # The stream encode has no B-frames on both paths (x264 baseline, VAAPI -bf 0) —
    # what WebRTC needs — so MediaMTX gets the same packets as HLS (and the same
    # LOW/SD/HD/HD+ tier). A second 720p x264 encode for RTSP cost each ffmpeg on
    # vpt-pi1 25-40% of its CPU. select by output stream index: 0 video, 1 AAC (HLS),
    # 2 Opus (RTSP → WebRTC audio); a missing audio stream just selects nothing.
    # onfail=ignore: MediaMTX down (at start or later) drops only the RTSP slave; HLS
    # keeps running. A dropped slave is not reopened — WEB falls back to HLS until this
    # ffmpeg restarts (restart vpt-stream after restarting vpt-mediamtx).
    # onfail=abort on HLS: a dead HLS writer must still kill ffmpeg so the watchdog restarts it.
    # No lhls: it is a dash-muxer option — `-lhls 1` with -f hls was a silent no-op (live
    # playlists carried no #EXT-X-PREFETCH) and is "Unknown option" in an hls tee slave.
    local rtsp_slave="|[f=rtsp:select=0,2:onfail=ignore:rtsp_transport=tcp]rtsp://127.0.0.1:8554/$output_basename"
    if [ "$webrtc_enabled" = false ]; then
      rtsp_slave=""
      echo "ℹ️  WEBRTC_ENABLED=false — no RTSP/WebRTC output, HLS only"
    fi
    local stream_outputs="-f tee \"[f=hls:select=0,1:onfail=abort:hls_time=$stream_hls_time:hls_list_size=$stream_hls_list:hls_delete_threshold=$stream_hls_list:hls_flags=$stream_hls_flags:start_number=$seg_start:hls_segment_filename=$output_segments/segment_%09d.ts]$output_segments/output.m3u8$rtsp_slave\""

    # -loglevel error: drop the per-frame info/decoder chatter (a corrupt-input
    # grabber floods it). -stats: keep the ~1/s progress line so the log mtime
    # still advances — check_grabber_health uses that as the liveness signal.
    FFMPEG_CMD="/usr/bin/ffmpeg -loglevel error -stats -y \
      $vaapi_dev_flag \
      -fflags +nobuffer+genpts+flush_packets \
      -use_wallclock_as_timestamps 1 \
      -thread_queue_size $stream_tqs \
      $lite_in_threads -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate $stream_fps -i $source \
      $audio_input_flags \
      $lite_graph_threads -filter_complex \"[0:v]split=3[str][cap][thm]; \
        $stream_filter; \
        [cap]fps=5,scale=${capture_scale}:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor,split=2[thumbout][latestout]\" \
      -map \"[streamout]\" $audio_map_flags \
      $stream_codec $lite_out_threads \
      $audio_codec_flags \
      $stream_outputs \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg $lite_out_threads -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg $lite_out_threads -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg \
      -map \"[latestout]\" -fps_mode passthrough -c:v mjpeg $lite_out_threads -q:v 8 -f image2 -update 1 -atomic_writing 1 $latest_jpg"

  # NOTE: hls_list_size on the imagefile branch below is 150, matching every other source
  # type. It was 30, which kept only 30s of 1s segments — and the archiver needs
  # round(60 / segment_duration) = 60 of them to build its 1-minute MP4. It never built one,
  # so it never appended a 10-minute chunk and COLD stayed permanently empty for every
  # imagefile device (emulators and paired phones), capping their report videos at the live
  # window. 150 x 1s segments is ~300KB of the hot tmpfs.
  #
  # Comments MUST stay out of the ffmpeg invocations themselves: a `#` line between two
  # backslash-continued lines ends the command early, and the truncated filter graph fails
  # with "Filter scale:default has an unconnected output" — which `bash -n` does not catch.
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
    # A screenshot stream keys every 0.8 s (stream_gop below), not 0.4 s like a capture card,
    # and gets half a capture card's bitrate. Its picture barely moves between keyframes, so
    # the keyframes ARE the bitrate: at 0.4 s, 720x1280 needs 1.5 Mbit/s to stay sharp (SSIM
    # 0.987; 0.962 and blocky at 750k), while at 0.8 s 750k gives 0.984. Screenshot devices
    # are often phones on WiFi, where 1.5 Mbit/s per tile queued their playlists for seconds
    # and stalled the HD player (BUG-0491). This is what these streams effectively ran before
    # their clock was fixed, when 0.4 s of their half-speed media time was 0.8 s of real time.
    local thumb_scale="320:180"
    if [ "$orientation" = "portrait" ]; then
      thumb_scale="180:320"
      if [ "$quality" = "hd" ]; then
        local stream_scale="720:1280"; local stream_bitrate="750k"
      elif [ "$quality" = "sd" ]; then
        local stream_scale="360:640"; local stream_bitrate="175k"
      else
        local stream_scale="180:320"; local stream_bitrate="60k"
      fi
    else
      if [ "$quality" = "hd" ]; then
        local stream_scale="1280:720"; local stream_bitrate="750k"
      elif [ "$quality" = "sd" ]; then
        local stream_scale="640:360"; local stream_bitrate="175k"
      else
        local stream_scale="320:180"; local stream_bitrate="60k"
      fi
    fi
    local stream_gop=$((input_fps*4/5))

    echo "Starting ffmpeg: quality=$quality orient=$orientation scale=$stream_scale thumb=$thumb_scale bitrate=$stream_bitrate"

    # Audio for a screenshot-fed device (Android emulator): the frames carry none, so
    # audio comes from the emulator's own output routed into this user's PulseAudio
    # (`-audio pa` on the AVD). Without it the device reports audio N/A, which is
    # truthful but means the heatmap can never show an audio loss for it.
    # Audio is stamped with the arrival wall clock, the same clock as the video's RTCTIME,
    # and aresample stretches it (up to 1000 samples/s) to stay on that clock (BUG-0169).
    # The audio drift once blamed on stamping was input starvation, fixed in the filter graph
    # below; wall-clock stamps plus aresample still cover any jitter in pulse delivery.
    ensure_pulse_server "$audio_device"
    local audio_input=""
    local audio_codec=""
    local audio_map=""
    if [ "$audio_device" != "null" ] && [ -n "$audio_device" ]; then
      if [ "$audio_device" = "default" ] || [ "$audio_device" = "pulse" ]; then
        audio_input="-f pulse -use_wallclock_as_timestamps 1 -thread_queue_size 2048 -i default"
      else
        audio_input="-f alsa -use_wallclock_as_timestamps 1 -thread_queue_size 2048 -i \"$audio_device\""
      fi
      audio_codec="-c:a aac -b:a 64k -ar 44100 -ac 2 -af aresample=async=1000:first_pts=0"
      audio_map="-map 1:a?"
      echo "🔊 Audio enabled for emulator capture via: $audio_device"
    fi

    # The frames carry a synthetic clock (frame N is at N/$input_fps) but the cat loop below
    # delivers well under $input_fps (cat + sleep overhead: ~4.2 fps measured for 5, ~5 fps
    # for 10), so that timeline runs slower than the wall clock the pulse packets are stamped
    # with. Interleaving by timestamp then pairs each second of video with audio recorded
    # earlier and earlier (28 s behind after 2 min on labox-mobile, unbounded), while ffmpeg
    # holds the surplus audio in RAM. Without audio the slow clock still hurts the live
    # player: at half speed a 0.4 s segment takes 0.8 s to fill and the player's 1 s behind
    # live edge is 2 s of real time (BUG-0491). So the frames are ALWAYS stamped with the wall
    # clock. The stream output is then resampled to a constant $input_fps (`-r`): the wall
    # clock carries no frame rate, so without it ffmpeg pads the HLS output to 25 fps, a third
    # of them keyframes, and the same bitrate turns blocky (SSIM 0.94 vs 0.985 on a phone home
    # screen); passed through as VFR, x264 sizes its bit budget for a microsecond tick and is
    # far worse (SSIM 0.65). At $input_fps, -g keeps keyframes and segments at 0.8 s.
    # The clock goes before the split so EVERY output runs on it (BUG-0169): ffmpeg paces its
    # inputs by the slowest output, so JPEG outputs left on the synthetic clock (~1.4% slow)
    # starve the audio input; after ~17 min its queue overflows and samples are lost until the
    # player goes black. The JPEG encoders get a 1 ms time base, or two wall-clock frames in
    # one 1/$input_fps tick share a pts and mjpeg stalls ffmpeg (BUG-0165).
    local video_clock="settb=AVTB,setpts=RTCTIME-RTCSTART,"

    # The PNG decoder runs single-threaded (`-threads 1` before `-i -`). Left at the default,
    # ffmpeg frame-threads it across every core, and each decoder thread holds a frame: on a
    # 20-core host that is ~20 frames in flight, ~4 s of lag at ~5 fps and 1 GB of RAM
    # (BUG-0491). One full-HD PNG decodes in a few tens of ms, far under the frame interval.
    # Use piped cat loop — re-reads source file each frame
    # The outer while-true loop in run_one_grabber will restart on quality change
    FFMPEG_CMD="(while true; do cat \"$source\" 2>/dev/null || break; sleep 0.2; done) | \
      /usr/bin/ffmpeg -loglevel error -stats -y -fflags +flush_packets -threads 1 -f image2pipe -framerate $input_fps -i - \
      $audio_input \
      -filter_complex \"[0:v]${video_clock}split=3[str][cap][thm]; \
        [str]scale=${stream_scale}[streamout]; \
        [cap]setpts=PTS-STARTPTS[captureout]; \
        [thm]scale=${thumb_scale},split=2[thumbout][latestout]\" \
      -map \"[streamout]\" $audio_map -c:v libx264 -preset ultrafast -tune zerolatency \
        -r $input_fps -g $stream_gop -keyint_min $stream_gop -x264opts no-scenecut:bframes=0 \
        -b:v ${stream_bitrate} -maxrate ${stream_bitrate} -bufsize $((${stream_bitrate%k} * 2))k \
        -pix_fmt yuv420p \
        $audio_codec \
        -f hls -hls_time 0.8 -hls_list_size 375 -hls_delete_threshold 375 -hls_flags delete_segments+program_date_time \
        -start_number $seg_start \
        -hls_segment_filename $output_segments/segment_%09d.ts \
        $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -enc_time_base 1:1000 -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
        -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -enc_time_base 1:1000 -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
        -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg \
        -map \"[latestout]\" -fps_mode passthrough -enc_time_base 1:1000 -c:v mjpeg -q:v 8 -f image2 -update 1 -atomic_writing 1 $latest_jpg"

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
    
    # Resolve the X cookie BEFORE anything touches the display: xdpyinfo below needs it just as
    # much as x11grab does, and a failed lookup silently degrades to the 1280x720 fallback.
    setup_x11_auth "$source"
    export DISPLAY="$source"

    ensure_pulse_server "$audio_device"

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
      -fflags +nobuffer+flush_packets \
      -probesize 32M -analyzeduration 0 \
      -draw_mouse 0 -show_region 0 \
      -f x11grab -video_size $resolution -framerate $input_fps -i $source \
      $audio_input \
      -filter_complex \"[0:v]split=3[str][cap][thm]; \
        [str]scale=${stream_scale}:flags=neighbor[streamout]; \
        [cap]fps=5,scale=${capture_scale}:flags=neighbor,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor,split=2[thumbout][latestout]\" \
      -map \"[streamout]\" $audio_map \
      -c:v libx264 -preset ultrafast -tune zerolatency \
      -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize \
      $audio_codec \
      -pix_fmt yuv420p -profile:v baseline -level 3.0 \
      -x264opts keyint=$((input_fps*2/5)):min-keyint=$((input_fps*2/5)):no-scenecut:bframes=0:ref=1:me=dia:subme=0 \
      -f hls -hls_time 0.4 -hls_list_size 375 -hls_delete_threshold 375 -hls_flags delete_segments+omit_endlist+split_by_time+program_date_time -lhls 1 \
      -start_number $seg_start \
      -hls_segment_filename $output_segments/segment_%09d.ts \
      $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 10 -f image2 -atomic_writing 1 \
      -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 10 -f image2 -atomic_writing 1 \
      -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg \
      -map \"[latestout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -update 1 -atomic_writing 1 $latest_jpg"
  elif [ "$source_type" = "rtsp" ] || [ "$source_type" = "hls" ] || [ "$source_type" = "videofile" ]; then
    # TASK-31: network streams (RTSP / HLS / public IPTV) and local / HTTP(S) video files.
    # The branch reuses the v4l2 / imagefile output pipeline (mjpeg captures + HLS stream)
    # but with a generic FFmpeg demuxer (-i $source) instead of a device-specific input.
    #
    # Loop semantics:
    #   - RTSP / HLS / MJPEG (live): LOOP=0 keeps the source as a live stream; FFmpeg exits
    #     naturally when the upstream ends. Setting LOOP=1 wraps -stream_loop -1 around it,
    #     which restarts the input after EOF — useful for IPTV that ends on its own.
    #   - HLS with LOOP=1: -stream_loop -1 only for a TS VOD media playlist (gapless loop,
    #     hls_is_ts_vod).
    #     On an fMP4 VOD (#EXT-X-MAP) it stalls at EOF (ffmpeg alive, no segment for ever,
    #     so the watchdog restarts it ~60s later), so fMP4, master, live and unreadable playlists
    #     play once: ffmpeg ends at the end of the playlist and restart_ended_hls restarts
    #     it within ~1s (HLS_LOOP_PID below). A TS VOD whose looping ffmpeg exits anyway
    #     is restarted the same way. YouTube never loops in ffmpeg: its end moves to the
    #     next playlist entry (youtube_ended).
    #   - videofile: LOOP=1 (default) is -stream_loop -1 (loop forever); LOOP=0 plays once
    #     and exits (on-demand mode).
    #
    # Audio from the source codec when present (HLS IPTV often has AC-3, RTSP cameras
    # usually don't). The audio_input / audio_map flags below only apply when
    # audio_device was *not* set in the env (i.e. embedded audio is wanted); when an
    # external audio_device is set we treat this as video-only and let ALSA / Pulse route
    # the audio — same convention as the v4l2 branch.
    local loop_state
    loop_state=$(get_loop_state "$capture_dir")
    local stream_loop_flag=""
    if [ "$loop_state" = "1" ] && [[ ! "$source" =~ ^udp:// ]]; then  # a UDP push feed has no EOF to loop on
      if [ "$source_type" != "hls" ]; then
        stream_loop_flag=" -stream_loop -1"
      elif [ -z "${YT_SRC[$index]:-}" ] && hls_is_ts_vod "$source"; then
        stream_loop_flag=" -stream_loop -1"
      fi
    fi
    # YouTube resumes at YT_SEEK after a URL refresh (input seek: HTTP range, no decode).
    # -reconnect: googlevideo resets the connection mid-file ("Connection reset by peer");
    # without it ffmpeg takes that as EOF and a 52 s video ended after 27 s. With it ffmpeg
    # re-requests the rest by range. An expired URL still fails (403) and exits.
    local yt_input_flags=""
    if [ -n "${YT_SRC[$index]:-}" ]; then
      yt_input_flags="-reconnect 1 -reconnect_on_network_error 1 -reconnect_delay_max 5"
      local seek="${YT_SEEK[$index]:-}"
      if [ -z "$seek" ]; then youtube_at_end "$index" && seek=0 || seek=$REPLY; fi
      unset "YT_SEEK[$index]"
      [ "$seek" -gt 0 ] && yt_input_flags="$yt_input_flags -ss $seek"
      YT_STARTED[$index]=$(( $(date +%s) - seek ))
    fi
    echo "Starting ffmpeg: type=$source_type loop=$loop_state${stream_loop_flag:+ (stream_loop)}${yt_input_flags:+ $yt_input_flags} source=${source:0:120}"

    # Quality-tier bitrate scaling (same table as v4l2, simpler — no HD+ gate here).
    local stream_scale stream_bitrate stream_maxrate stream_bufsize capture_scale
    case "$quality" in
      hd_plus|hd) stream_scale="1280:720"; stream_bitrate="1500k"; stream_maxrate="1800k"; stream_bufsize="3600k"; capture_scale="1280:720" ;;
      sd)         stream_scale="640:360";  stream_bitrate="350k";  stream_maxrate="400k";  stream_bufsize="800k";  capture_scale="1280:720" ;;
      *)          stream_scale="320:180";  stream_bitrate="150k";  stream_maxrate="200k";  stream_bufsize="400k";  capture_scale="1280:720" ;;
    esac

    # Embedded audio from the source codec when no external audio_device was set.
    # AUDIO_MAP_SPEC maps only a usable audio stream if present, otherwise no error
    # (see detect_audio_map).
    local audio_input="" audio_map="-map '$AUDIO_MAP_SPEC'" audio_codec="-c:a aac -b:a 32k -ar 48000 -ac 2"
    if [ "$audio_device" != "null" ] && [ -n "$audio_device" ]; then
      # External audio device — same probe-and-fall-back logic as v4l2.
      local audio_available=false
      local audio_input_flags="" audio_map_flags="" audio_codec_flags=""
      local audio_try
      for audio_try in 1 2 3; do
        if timeout 2 arecord -D "$audio_device" -s 4410 -f cd /dev/null >/dev/null 2>&1; then
          audio_available=true
          audio_input_flags="-f alsa -thread_queue_size 2048 -async 1 -err_detect ignore_err -i \"$audio_device\""
          audio_map_flags="-map 1:a?"
          audio_codec_flags="-c:a aac -b:a 32k -ar 48000 -ac 2"
          echo "Audio device $audio_device available (probe attempt ${audio_try})"
          break
        fi
        [ "$audio_try" -lt 3 ] && sleep 1
      done
      audio_input="$audio_input_flags"
      audio_map="$audio_map_flags"
      audio_codec="$audio_codec_flags"
    fi

    # Reuse the proven v4l2 / x11grab output pipeline: split into [str]/[cap]/[thm],
    # encode HLS with libx264 ultrafast, dump mjpeg captures + thumbnails to disk.
    # -re throttles read rate to native fps so wall-clock playback matches the source.
    # Without it a local file is read as fast as the disk allows and the HLS segments
    # play at ~3-4x with stop-and-go gaps. Not for rtsp: a live source is already paced
    # by the sender, and -re on top makes frames bunch up then stall, which ffmpeg fills
    # with duplicates (the monitor reports a freeze every few seconds).
    # -fflags +genpts regenerates PTS so HLS segments are continuous even if the source codec
    # has missing/duplicate timestamps. The flags are ONE value joined by `+` with no
    # spaces, otherwise ffmpeg reads `+genpts` as an output filename and exits.
    #
    # +nobuffer only for rtsp (BUG-0285). With it, avformat_find_stream_info throws
    # away the packets it read while probing instead of handing them to the decoder;
    # they include the first keyframe, so H.264 decodes nothing until the source's
    # NEXT keyframe: 25 s on smoke.mp4 (keyint 250 @ 10 fps), 8.3 s on smoke.mkv,
    # 4-5 s on HLS bipbop, with no capture and no segment written meanwhile. A file
    # or HLS source gains no latency from it (it is read whole, paced by -re).
    local re_flag="-re" input_fflags="+genpts+flush_packets"
    if [ "$source_type" = "rtsp" ]; then
      re_flag=""
      input_fflags="+nobuffer+genpts+flush_packets"
    fi

    # VAAPI hosts: decode the source AND encode the HLS stream on the GPU. Unlike the
    # v4l2 branch (MJPEG input, nothing to offload on decode) a network source is
    # H.264/HEVC, and its decode is the bigger cost: on vpt-nipogi (Ryzen Vega) a 720p60
    # source at HD went from 59% to 24% of a core. -hwaccel without
    # -hwaccel_output_format hands software frames to the filter graph, so [cap]/[thm]
    # are unchanged, and a codec the GPU cannot decode falls back to software silently.
    # TASK-50 subtitle QA: a local file with a sidecar `<file>.subtrack` (one number: the index
    # among the file's subtitle streams) has that soft track drawn into the picture BEFORE the
    # split, so the stream, the captures and the thumbnails all show it (a capture cannot show a
    # soft track otherwise). No sidecar = unchanged behaviour.
    local sub_filter=""
    if [ "$source_type" = "videofile" ] && [ -f "${source}.subtrack" ]; then
      local sub_idx sub_src
      sub_idx=$(tr -dc '0-9' < "${source}.subtrack")
      sub_src=${source//\\/\\\\}; sub_src=${sub_src//:/\\:}; sub_src=${sub_src//\'/\\\'}
      [ -n "$sub_idx" ] && sub_filter="subtitles='${sub_src}':si=${sub_idx},"
      echo "Subtitle burn-in: track ${sub_idx:-?} of ${source}"
    fi

    local hw_input_flags="" stream_filter stream_codec
    if [ -n "$VAAPI_RENDER_NODE" ]; then
      hw_input_flags="-hwaccel vaapi -hwaccel_device $VAAPI_RENDER_NODE -vaapi_device $VAAPI_RENDER_NODE"
      stream_filter="[str]fps=${input_fps},scale=${stream_scale}:flags=fast_bilinear,format=nv12,hwupload[streamout]"
      # Same profile/rc as the v4l2 VAAPI branch (see the iHD note there); -g = 1 s GOP.
      stream_codec="-c:v h264_vaapi -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize -g $((input_fps*2/5))"
    else
      stream_filter="[str]fps=${input_fps},scale=${stream_scale}:flags=fast_bilinear[streamout]"
      stream_codec="-c:v libx264 -preset ultrafast -tune zerolatency -b:v $stream_bitrate -maxrate $stream_maxrate -bufsize $stream_bufsize \
      -x264opts keyint=$((input_fps*2/5)):min-keyint=$((input_fps*2/5)):no-scenecut:bframes=0 -pix_fmt yuv420p -profile:v baseline -level 3.0"
    fi
    FFMPEG_CMD="/usr/bin/ffmpeg -loglevel error -stats -y \
      $hw_input_flags \
      -fflags $input_fflags \
      $re_flag $stream_loop_flag $yt_input_flags -i \"$source\" \
      $audio_input \
      -filter_complex \"[0:v]${sub_filter}split=3[str][cap][thm]; \
        $stream_filter; \
        [cap]fps=5,scale=${capture_scale}:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor,split=2[thumbout][latestout]\" \
      -map \"[streamout]\" $audio_map \
      $stream_codec \
      $audio_codec \
      -f hls -hls_time 0.4 -hls_list_size 375 -hls_delete_threshold 375 -hls_flags delete_segments+omit_endlist+split_by_time+program_date_time -lhls 1 \
      -start_number $seg_start \
      -hls_segment_filename $output_segments/segment_%09d.ts \
      $output_segments/output.m3u8 \
      -map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $cap_start $output_captures/capture_%09d.jpg \
      -map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
      -start_number $thumb_start $output_thumbnails/capture_%09d_thumbnail.jpg \
      -map \"[latestout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -update 1 -atomic_writing 1 $latest_jpg"
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

  # Looping HLS: remember the PID so restart_ended_hls restarts it when the playlist ends.
  if [ "$source_type" = "hls" ] && [ "${loop_state:-0}" = "1" ]; then
    HLS_LOOP_PID[$index]=$FFMPEG_PID
    HLS_LOOP_START[$index]=$(date +%s)
  else
    unset "HLS_LOOP_PID[$index]"
  fi
  
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
detect_audio_map

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
init_source_specs

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
  # Check if any device quality or source changed or died
  check_quality_changes
  check_source_changes
  restart_ended_hls
  check_youtube_refresh

  tick=$((tick + 1))
  if [ $((tick % HEALTH_INTERVAL)) -eq 0 ]; then
    check_grabber_health
  fi

  sleep 1  # Check every second
done
