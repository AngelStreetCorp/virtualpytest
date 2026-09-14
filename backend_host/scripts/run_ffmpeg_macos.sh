#!/bin/bash

# VirtualPyTest macOS FFmpeg Stream Script
# macOS version of run_ffmpeg.sh
# Compatible with Bash 3.2 (macOS default)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BACKEND_HOST_DIR/src/.env"

# Use /tmp for logs (same as Linux version)
# macOS /tmp is a symlink to /private/tmp - world writable, no permission issues
LOG_DIR="/tmp"
PID_DIR="/tmp"

# FFmpeg path - use full path for compatibility with sudo/launchd
FFMPEG_BIN=$(which ffmpeg 2>/dev/null || echo "/opt/homebrew/bin/ffmpeg")
if [[ ! -x "$FFMPEG_BIN" ]]; then
    # Fallback paths for different macOS installations
    for path in /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg; do
        if [[ -x "$path" ]]; then
            FFMPEG_BIN="$path"
            break
        fi
    done
fi
echo "DEBUG: Using FFmpeg at: $FFMPEG_BIN"

# Load environment (Bash 3.2 compatible - no process substitution with source)
echo "DEBUG: ENV_FILE=$ENV_FILE"
if [[ -f "$ENV_FILE" ]]; then
    echo "DEBUG: Loading .env file..."
    # Read .env file line by line and export variables
    while IFS='=' read -r key value; do
        # Skip empty lines and comments
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
        # Remove leading/trailing whitespace from key
        key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        # Remove inline comments and trailing whitespace from value
        value=$(echo "$value" | sed 's/[[:space:]]*#.*$//;s/^[[:space:]]*//;s/[[:space:]]*$//')
        # Remove quotes if present
        value=$(echo "$value" | sed 's/^["'\'']\(.*\)["'\'']$/\1/')
        # Export the variable
        if [[ -n "$key" ]]; then
            export "$key=$value"
        fi
    done < "$ENV_FILE"
    echo "DEBUG: .env loaded"
    echo "DEBUG: HOST_VIDEO_SOURCE=[$HOST_VIDEO_SOURCE]"
    echo "DEBUG: HOST_VIDEO_CAPTURE_PATH=[$HOST_VIDEO_CAPTURE_PATH]"
    echo "DEBUG: DEVICE1_VIDEO=[$DEVICE1_VIDEO]"
    echo "DEBUG: DEVICE1_VIDEO_AUDIO=[$DEVICE1_VIDEO_AUDIO]"
    echo "DEBUG: DEVICE1_VIDEO_FPS=[$DEVICE1_VIDEO_FPS]"
    echo "DEBUG: DEVICE1_VIDEO_CAPTURE_PATH=[$DEVICE1_VIDEO_CAPTURE_PATH]"
else
    echo "ERROR: ENV_FILE not found at $ENV_FILE"
fi

# Build grabbers configuration for macOS (Bash 3.2 compatible - no associative arrays)
# Using parallel arrays instead of declare -A
GRABBER_NAMES=()
GRABBER_VALUES=()

# Host grabber (macOS screen capture)
# Default HOST_VIDEO_SOURCE to "1:0" on macOS if not specified but HOST_VIDEO_CAPTURE_PATH exists
if [[ -z "$HOST_VIDEO_SOURCE" && -n "$HOST_VIDEO_CAPTURE_PATH" ]]; then
    HOST_VIDEO_SOURCE="1:0"
    echo "DEBUG: HOST_VIDEO_SOURCE not set, defaulting to 1:0 (macOS screen capture)"
fi

echo "DEBUG: Checking HOST grabber (HOST_VIDEO_SOURCE=[$HOST_VIDEO_SOURCE])..."
if [[ -n "$HOST_VIDEO_SOURCE" ]]; then
    GRABBER_NAMES+=("host")
    # macOS AVFoundation supports 10-60fps, so default to 10fps (not 2fps like Linux)
    GRABBER_VALUES+=("$HOST_VIDEO_SOURCE|${HOST_VIDEO_AUDIO:-null}|$HOST_VIDEO_CAPTURE_PATH|${HOST_VIDEO_FPS:-30}")
    echo "DEBUG: ✓ Added host grabber (fps=${HOST_VIDEO_FPS:-30})"
else
    echo "DEBUG: ✗ HOST not configured (no HOST_VIDEO_CAPTURE_PATH in .env)"
fi

# Device grabbers (macOS cameras)
echo "DEBUG: Checking device grabbers..."
for i in 1 2 3 4 5; do
    video_var="DEVICE${i}_VIDEO"
    audio_var="DEVICE${i}_VIDEO_AUDIO"
    capture_var="DEVICE${i}_VIDEO_CAPTURE_PATH"
    fps_var="DEVICE${i}_VIDEO_FPS"

    video_source="${!video_var}"
    audio_device="${!audio_var}"
    capture_path="${!capture_var}"
    fps="${!fps_var}"

    echo "DEBUG: device$i: video_source=[$video_source], audio_device=[$audio_device], fps=[$fps]"

    if [[ -n "$video_source" ]]; then
        GRABBER_NAMES+=("device$i")
        GRABBER_VALUES+=("$video_source|${audio_device:-null}|$capture_path|${fps:-10}")
        echo "DEBUG: ✓ Added device$i grabber"
    fi
done

echo "DEBUG: Total grabbers configured: ${#GRABBER_NAMES[@]}"
echo "DEBUG: Grabber names: ${GRABBER_NAMES[*]}"

# List available AVFoundation devices (for debugging)
list_avfoundation_devices() {
    echo "Available AVFoundation devices:"
    $FFMPEG_BIN -f avfoundation -list_devices true -i "" 2>&1 | grep -E "^\[AVFoundation" || true
}

# Setup capture directory structure and detect storage mode (same as Linux)
setup_capture_directories() {
    local capture_dir=$1
    
    # Check if hot storage exists (RAM disk symlink on macOS)
    # On macOS, hot storage is a symlink to /Volumes/VirtualPyTest_{device}_Hot
    if [[ -d "$capture_dir/hot" ]] || [[ -L "$capture_dir/hot" && -d "$(readlink "$capture_dir/hot")" ]]; then
        echo "✓ RAM hot storage detected at $capture_dir/hot"
        # Create subdirectories in RAM hot storage
        mkdir -p "$capture_dir/hot/segments"
        mkdir -p "$capture_dir/hot/captures"
        mkdir -p "$capture_dir/hot/thumbnails"
        mkdir -p "$capture_dir/hot/metadata"
        echo "✓ Using RAM mode (reduced disk writes)"
        return 0  # RAM mode
    else
        echo "⚠️  No RAM hot storage found at $capture_dir/hot"
        echo "   Run install_host_macos.sh to setup RAM disks"
        # Create directories on disk (cold storage)
        mkdir -p "$capture_dir/segments"
        mkdir -p "$capture_dir/captures"
        mkdir -p "$capture_dir/thumbnails"
        mkdir -p "$capture_dir/metadata"
        echo "✓ Using disk mode (direct write)"
        return 1  # Disk mode
    fi
}

# Clean up playlist files for a specific capture directory
clean_playlist_files() {
    local capture_dir=$1
    echo "Cleaning playlist files in hot storage..."
    # Clean playlists in hot storage (RAM)
    rm -f "$capture_dir/hot/segments/output.m3u8" 2>/dev/null || true
    rm -f "$capture_dir/hot/segments/archive.m3u8" 2>/dev/null || true
    # Also clean cold storage playlists
    rm -f "$capture_dir/segments/output.m3u8" 2>/dev/null || true
}

# Function to start FFmpeg grabber for macOS
start_grabber() {
    local source=$1 audio_device=$2 capture_dir=$3 index=$4 input_fps=$5 quality=$6

    # Setup directories and detect hot/cold storage mode (same as Linux)
    if setup_capture_directories "$capture_dir"; then
        local storage_base="$capture_dir/hot"
    else
        local storage_base="$capture_dir"
    fi
    
    local output_segments="$storage_base/segments"
    local output_captures="$storage_base/captures"
    local output_thumbnails="$storage_base/thumbnails"
    
    # Clean old playlist files
    clean_playlist_files "$capture_dir"

    # Determine capture method based on source
    # Uses input_fps from .env (same as Linux), defaults are set in grabber config
    echo "DEBUG: $index using framerate=${input_fps}fps (from .env)"
    
    # macOS AVFoundation input format: "VIDEO_INDEX:AUDIO_INDEX" or just "VIDEO_INDEX"
    # Examples: "0" (video only), "0:3" (video 0, audio 3), "2:none" (screen, no audio)
    
    # Video index from source
    local video_idx="$source"
    local has_audio=false
    
    # Audio capture disabled for now - USB capture cards on macOS can't do separate audio
    # TODO: Re-enable when audio solution is found (e.g., separate mic input)
    has_audio=false
    if [[ -n "$audio_device" && "$audio_device" != "null" && "$audio_device" != "none" ]]; then
        echo "DEBUG: Audio device $audio_device configured but DISABLED (macOS USB capture limitation)"
        echo "DEBUG: AVFoundation video=$video_idx (video only mode)"
    else
        echo "DEBUG: AVFoundation video=$video_idx (no audio configured)"
    fi
    
    # Build FFmpeg command for macOS AVFoundation
    if [[ ! "$video_idx" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Invalid video device index: $video_idx (must be a number)"
        return 1
    fi
    
    # Screen capture (typically index 2+) vs camera/capture card (index 0-1)
    if [[ "$video_idx" -ge 2 ]]; then
        # Screen capture - no pixel_format needed
        FFMPEG_CMD="$FFMPEG_BIN -y -f avfoundation -framerate $input_fps -i \"$video_idx:none\""
        echo "DEBUG: Using AVFoundation screen capture (device $video_idx)"
    else
        # Camera or capture card - requires explicit pixel_format uyvy422, add probesize for stability
        FFMPEG_CMD="$FFMPEG_BIN -y -f avfoundation -probesize 32M -analyzeduration 20M -pixel_format uyvy422 -framerate $input_fps -i \"$video_idx\""
        echo "DEBUG: Using AVFoundation camera/capture card (device $video_idx) with pixel_format uyvy422"
    fi

    # Add video processing pipeline
    case $quality in
        "hd")
            stream_scale="1280:720"
            stream_bitrate="1500k"
            capture_scale="1280:720"
            ;;
        "sd")
            stream_scale="640:360"
            stream_bitrate="350k"
            capture_scale="1280:720"
            ;;
        *)
            stream_scale="320:180"
            stream_bitrate="150k"
            capture_scale="1280:720"
            ;;
    esac

    # Complete FFmpeg command for macOS (uses hot storage if available)
    echo "DEBUG: Output paths: segments=$output_segments, captures=$output_captures"
    
    # Build audio mapping if audio is present (audio is input 1 when present)
    # Currently disabled - USB capture cards on macOS can't do separate audio capture
    local audio_map=""
    local audio_codec=""
    if [[ "$has_audio" == true ]]; then
        audio_map="-map 1:a"
        audio_codec="-c:a aac -b:a 128k"
    else
        echo "DEBUG: No audio mapping (video only)"
    fi
    
    FFMPEG_CMD="$FFMPEG_CMD -filter_complex \"[0:v]split=3[str][cap][thm]; \
[str]scale=${stream_scale}:flags=lanczos[streamout]; \
[cap]fps=5,scale=${capture_scale}:flags=lanczos,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=lanczos[thumbout]\" \
-map \"[streamout]\" $audio_map \
-c:v libx264 -preset ultrafast -tune zerolatency \
-b:v $stream_bitrate -maxrate $stream_bitrate -bufsize $(( $(echo $stream_bitrate | sed 's/k//') * 2 ))k \
-pix_fmt yuv420p -profile:v baseline -level 3.0 $audio_codec \
-f hls -hls_time 1 -hls_list_size 150 -hls_flags delete_segments+omit_endlist+split_by_time -lhls 1 \
-hls_segment_filename \"$output_segments/segment_%09d.ts\" \
\"$output_segments/output.m3u8\" \
-map \"[captureout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
\"$output_captures/capture_%09d.jpg\" \
-map \"[thumbout]\" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 -atomic_writing 1 \
\"$output_thumbnails/capture_%09d_thumbnail.jpg\""

    # Clean up old segments (in the storage location we're using)
    rm -f "$output_segments/segment_"*.ts 2>/dev/null || true
    rm -f "$output_segments/output.m3u8" 2>/dev/null || true

    # Start FFmpeg (use same log naming as Linux: /tmp/ffmpeg_output_${index}.log)
    local FFMPEG_LOG="$LOG_DIR/ffmpeg_output_$index.log"
    > "$FFMPEG_LOG"
    
    # Print raw FFmpeg command for debugging
    echo ""
    echo "DEBUG: Raw FFmpeg command for $index:"
    echo "----------------------------------------"
    echo "$FFMPEG_CMD"
    echo "----------------------------------------"
    echo ""
    
    echo "Starting $index with quality $quality"
    eval "$FFMPEG_CMD > \"$FFMPEG_LOG\" 2>&1 &"
    local ffmpeg_pid=$!
    echo $ffmpeg_pid > "$PID_DIR/ffmpeg_$index.pid"
    
    # Verify FFmpeg started (give it a moment to fail on immediate errors)
    sleep 0.5
    if kill -0 $ffmpeg_pid 2>/dev/null; then
        echo "✓ $index started (PID: $ffmpeg_pid)"
        return 0
    else
        echo "✗ $index failed to start - check $FFMPEG_LOG"
        return 1
    fi
}

# Main loop
echo "VirtualPyTest macOS FFmpeg Stream Service starting..."

# Clean up old processes
for pid_file in "$PID_DIR/ffmpeg_"*.pid; do
    if [[ -f "$pid_file" ]]; then
        pid=$(cat "$pid_file")
        kill -9 $pid 2>/dev/null || true
        rm -f "$pid_file"
    fi
done

# Clear old logs and show which files will be used (based on .env config)
echo ""
echo "=========================================="
echo "Log/PID files (in $LOG_DIR):"
for grabber_name in "${GRABBER_NAMES[@]}"; do
    log_file="$LOG_DIR/ffmpeg_output_$grabber_name.log"
    pid_file="$PID_DIR/ffmpeg_$grabber_name.pid"
    > "$log_file" 2>/dev/null || true
    echo "  $grabber_name: $log_file"
done
echo "=========================================="
echo ""

# Check if any grabbers configured
if [[ ${#GRABBER_NAMES[@]} -eq 0 ]]; then
    echo "WARNING: No grabbers configured in $ENV_FILE"
    echo "Please configure HOST_VIDEO_CAPTURE_PATH or DEVICE{N}_VIDEO in .env"
    echo "Service will wait for configuration..."
fi

# Track grabber status
GRABBERS_STARTED=0
GRABBERS_FAILED=0
FAILED_GRABBERS=""

# Start all grabbers (Bash 3.2 compatible iteration)
for idx in "${!GRABBER_NAMES[@]}"; do
    index="${GRABBER_NAMES[$idx]}"
    value="${GRABBER_VALUES[$idx]}"
    IFS='|' read -r source audio_device capture_dir input_fps <<< "$value"
    quality="sd"  # Default quality
    echo "Configuring grabber: $index (source=$source, audio=$audio_device, capture_dir=$capture_dir)"
    if start_grabber "$source" "$audio_device" "$capture_dir" "$index" "$input_fps" "$quality"; then
        ((GRABBERS_STARTED++))
    else
        ((GRABBERS_FAILED++))
        FAILED_GRABBERS="$FAILED_GRABBERS $index"
    fi
done

# Report status
echo ""
echo "=========================================="
if [[ $GRABBERS_FAILED -eq 0 && $GRABBERS_STARTED -gt 0 ]]; then
    echo "✅ All $GRABBERS_STARTED grabber(s) started successfully"
    echo "   Running: ${GRABBER_NAMES[*]}"
elif [[ $GRABBERS_STARTED -gt 0 && $GRABBERS_FAILED -gt 0 ]]; then
    echo "⚠️  Partial success: $GRABBERS_STARTED started, $GRABBERS_FAILED failed"
    echo "   Running: $(echo ${GRABBER_NAMES[*]} | tr ' ' '\n' | grep -v -F "$FAILED_GRABBERS" | tr '\n' ' ')"
    echo "   Failed:$FAILED_GRABBERS"
elif [[ $GRABBERS_FAILED -gt 0 && $GRABBERS_STARTED -eq 0 ]]; then
    echo "❌ All grabbers failed to start"
    echo "   Failed:$FAILED_GRABBERS"
else
    echo "⚠️  No grabbers were configured"
fi
echo "=========================================="

# Keep service alive
while true; do
    sleep 10
done
