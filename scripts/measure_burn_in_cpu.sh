#!/bin/bash
# CPU cost of the telemetry burn-in (TASK-90 goal 12): the network-source graph of run_ffmpeg.sh (split into stream, 5 fps captures and
# thumbnails) over a 960x720 30 fps H.264 clip (a Tello's picture), with and without the drawtext in front of the split. Prints user+sys CPU
# seconds per run and the mean. Usage: scripts/measure_burn_in_cpu.sh [runs=5] [seconds=20]
set -u
RUNS=${1:-5}; SECS=${2:-20}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FFMPEG=${FFMPEG:-$(command -v ffmpeg)}
FONT=${TELEMETRY_HUD_FONT:-}
for f in /usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf /System/Library/Fonts/Menlo.ttc; do [ -z "$FONT" ] && [ -f "$f" ] && FONT=$f; done
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
printf 'BAT 87%%  62C  ALT 1.2m  0.5m/s  47.37690,8.54170' > "$W/hud.txt"
"$FFMPEG" -loglevel error -y -f lavfi -i "testsrc2=s=960x720:r=30:d=$SECS" -c:v libx264 -preset veryfast -b:v 3M -pix_fmt yuv420p "$W/in.mp4"
HUD="drawtext=fontfile='$FONT':textfile='$W/hud.txt':reload=1:expansion=none:fontcolor=white:fontsize=h/30:x=w-tw-h/36:y=h/36:box=1:boxcolor=black@0.55:boxborderw=10,"
run() {   # $1 = filter prefix; prints CPU seconds (user+sys)
  mkdir -p "$W/out"; rm -f "$W/out"/*
  /usr/bin/time -p "$FFMPEG" -loglevel error -y -i "$W/in.mp4" -filter_complex "[0:v]${1}split=3[str][cap][thm];[str]fps=30,scale=640:480:flags=fast_bilinear[streamout];[cap]fps=5,scale=1280:720:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];[thm]fps=5,scale=320:180:flags=neighbor[thumbout]" \
    -map "[streamout]" -c:v libx264 -preset ultrafast -tune zerolatency -b:v 1500k -f mpegts "$W/out/stream.ts" \
    -map "[captureout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 "$W/out/capture_%05d.jpg" \
    -map "[thumbout]" -fps_mode passthrough -c:v mjpeg -q:v 8 -f image2 "$W/out/thumb_%05d.jpg" 2>&1 | awk '/^user|^sys/ {s+=$2} END {print s}'
}
echo "clip: 960x720 30 fps, ${SECS} s; font $FONT; $("$FFMPEG" -version | head -1)"
base=0; burn=0
for i in $(seq "$RUNS"); do
  a=$(run ""); b=$(run "$HUD")
  echo "run $i: clean ${a}s  burned ${b}s"
  base=$(echo "$base + $a" | bc -l); burn=$(echo "$burn + $b" | bc -l)
done
echo "mean clean  $(echo "$base / $RUNS" | bc -l | cut -c1-6) s CPU for ${SECS} s of video"
echo "mean burned $(echo "$burn / $RUNS" | bc -l | cut -c1-6) s CPU for ${SECS} s of video"
echo "extra       $(echo "($burn - $base) / $RUNS" | bc -l | cut -c1-6) s CPU = $(echo "100 * ($burn - $base) / $base" | bc -l | cut -c1-5) % of the clean pipeline = $(echo "100 * ($burn - $base) / $RUNS / $SECS" | bc -l | cut -c1-5) % of one core in real time"
