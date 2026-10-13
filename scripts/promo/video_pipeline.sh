#!/usr/bin/env bash
# One take of a promo video, end to end, on the machine that runs it (the Mac: 16 cores, direct LAN reach to
# the vpt-pi4 server, no tunnel). Guide §3: the builder (Haiku) edits the capture script; this script does the
# mechanical part, so a take costs minutes of machine time, not model time.
#
#   scripts/promo/video_pipeline.sh <capture.js> <build2 key> <N> [--check-only]
#
#   1. preflight  node <capture.js> preflight  -> the capture's own fast check of every beat's selector/label,
#                 no recording (a capture that has no preflight mode skips this step). Fails in ~30 s instead
#                 of after a 6-min take.
#   2. take       node <capture.js>            -> raw*/<name>.mp4 (frames_to_mp4.py encodes on every core)
#   3. build      python3 build2.py <key>
#   4. check      promo_check.py on the built mp4 (+ the voiced one if present)
#   5. contact    out/<name>_contact<N>.png (fps 1/1.5, 4x8)
# Every step is timed into out/<key>_pipeline<N>.log, which the production log reads.
set -uo pipefail
CAP="$1"; KEY="$2"; N="$3"; MODE="${4:-}"
CAP="$(cd "$(dirname "$CAP")" 2>/dev/null && pwd)/$(basename "$CAP")"   # before the cd: accept a repo-relative path
cd "$(dirname "$0")" || exit 1
export PROMO_BASE="${PROMO_BASE:-https://virtualpytest.angelstreet.io}"   # promo_lib defaults to a local Vite
LOG="out/${KEY}_pipeline${N}.log"; mkdir -p out
t0=$(date +%s); step() { echo "$(date -u +%T) +$(( $(date +%s) - t0 ))s $*" | tee -a "$LOG"; }
: > "$LOG"

if grep -q "preflight" "$CAP"; then
  step "preflight"
  node "$CAP" preflight >> "$LOG" 2>&1 || { step "PREFLIGHT FAILED (see log)"; exit 2; }
fi
[ "$MODE" = "--check-only" ] && { step "DONE (check only)"; exit 0; }

step "take"
node "$CAP" >> "$LOG" 2>&1 || { step "TAKE FAILED (see log)"; exit 3; }
step "build"
python3 build2.py "$KEY" >> "$LOG" 2>&1 || { step "BUILD FAILED (see log)"; exit 4; }
MP4=$(python3 -c "import build2; print(build2.VIDEOS['$KEY'][1])")
step "promo_check"
rc=0
for f in "out/$MP4" "out/${MP4%.mp4}_voice-"*.mp4; do
  [ -f "$f" ] || continue
  python3 promo_check.py "$f" --srt "out/${MP4%.mp4}.srt" ${PROMO_CHECK_WAIVER:-} >> "$LOG" 2>&1 || rc=1
done
ffmpeg -v error -y -i "out/$MP4" -vf "fps=1/1.5,scale=480:-1,tile=4x8" -frames:v 1 "out/${MP4%.mp4}_contact${N}.png"
step "DONE promo_check_rc=$rc contact=out/${MP4%.mp4}_contact${N}.png"
exit $rc
