#!/bin/bash

# Usage: ./emulator_screencap.sh [serial]
# Feeds /var/www/html/stream/emulator_frames/latest.png from adb screencap for run_ffmpeg.sh.
#
# Self-heal: the emulator sometimes finishes booting with every SurfaceFlinger layer
# hidden — the guest keeps rendering but the display composes nothing, so screencap
# returns an all-zero frame and the stream is black until someone power-cycles the
# display. Sampling the frame and sending SLEEP+WAKEUP forces SF to re-evaluate.

umask 0000

SERIAL="${1:-emulator-5554}"
OUT_DIR=/var/www/html/stream/emulator_frames
OUT="$OUT_DIR/latest.png"

CHECK_INTERVAL=30
STRIKES_TO_RECOVER=2
RECOVERY_COOLDOWN=300

mkdir -p "$OUT_DIR"

is_black() {
  python3 - "$1" <<'PY' 2>/dev/null
import sys
from PIL import Image
try:
    hi = Image.open(sys.argv[1]).convert("RGB").getextrema()
except Exception:
    sys.exit(2)
sys.exit(0 if all(band[1] == 0 for band in hi) else 1)
PY
}

is_awake() {
  adb -s "$SERIAL" shell dumpsys power 2>/dev/null | grep -q "mWakefulness=Awake"
}

recover_display() {
  echo "[screencap] display composing nothing — sending SLEEP/WAKEUP to $SERIAL"
  adb -s "$SERIAL" shell input keyevent KEYCODE_SLEEP
  sleep 2
  adb -s "$SERIAL" shell input keyevent KEYCODE_WAKEUP
  sleep 3
}

strikes=0
last_check=0
last_recovery=$((-RECOVERY_COOLDOWN))

while true; do
  adb -s "$SERIAL" exec-out screencap -p > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"

  now=$SECONDS
  if [ $((now - last_check)) -ge "$CHECK_INTERVAL" ]; then
    last_check=$now
    if is_black "$OUT" && is_awake; then
      strikes=$((strikes + 1))
      if [ "$strikes" -ge "$STRIKES_TO_RECOVER" ] && [ $((now - last_recovery)) -ge "$RECOVERY_COOLDOWN" ]; then
        recover_display
        last_recovery=$SECONDS
        strikes=0
      fi
    else
      strikes=0
    fi
  fi

  sleep 0.2
done
