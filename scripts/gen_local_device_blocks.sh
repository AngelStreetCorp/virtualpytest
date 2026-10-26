#!/usr/bin/env bash
# Print DEVICE<N> .env blocks for a host that loops local clips (stream_local_* profiles).
# Usage: gen_local_device_blocks.sh <count> [clip_dir] [name_prefix] >> backend_host/src/.env
# Always emits DEVICE<N>_MODEL=rtsp_video (without it the device registers as model "unknown"
# and is invisible in the Rec/Dashboard target picker) and a quoted NAME (the installer sources the .env).
# Clips are taken in sorted order from clip_dir; if fewer clips than devices, they repeat.
set -euo pipefail
COUNT="${1:?count}"; DIR="${2:-/var/lib/vpt-movies}"; PREFIX="${3:-Clip}"
CLIPS=(); while IFS= read -r f; do CLIPS+=("$f"); done < <(ls "$DIR"/*.mp4 | sort)
[ "${#CLIPS[@]}" -gt 0 ] || { echo "no .mp4 in $DIR" >&2; exit 1; }
for n in $(seq 1 "$COUNT"); do
  clip="${CLIPS[$(( (n-1) % ${#CLIPS[@]} ))]}"
  cat <<BLOCK
DEVICE${n}_NAME="${PREFIX} ${n}"
DEVICE${n}_MODEL=rtsp_video
DEVICE${n}_STREAM_TYPE=videofile
DEVICE${n}_VIDEO=${clip}
DEVICE${n}_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture${n}
DEVICE${n}_VIDEO_STREAM_PATH=/host/stream/capture${n}
DEVICE${n}_MONITOR_PROFILE=tv_lite
BLOCK
done
