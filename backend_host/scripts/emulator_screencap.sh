#!/bin/bash

# Usage: ./emulator_screencap.sh [serial] [output_file] [device_id]
#
# Feeds `output_file` from `adb -s serial exec-out screencap -p` every 0.2 s, so
# run_ffmpeg.sh's `imagefile` source type can read it as a live frame for one
# device. One instance per device — multiple real handsets on a single host
# (e.g. a Mac with several USB-tethered Android phones) need one process per
# serial, each writing to its own path.
#
# Argument resolution (all optional, all default to the original emulator-5554
# behaviour so the singleton vpt-emulator-fifo.service keeps working):
#   $1 serial        — adb serial. Default: emulator-5554.
#                      Ignored if $3 (device_id) is set and resolves the serial
#                      from backend_host/src/.env (DEVICE<n>_ADB_SERIAL).
#   $2 output_file   — full path to the PNG the loop writes. Default:
#                      /var/www/html/stream/emulator_frames/latest.png
#                      (the canonical emulator path; pair with
#                      DEVICEn_VIDEO=/var/www/html/stream/emulator_frames/latest.png).
#                      Ignored if $3 is set — resolved from DEVICEn_VIDEO.
#   $3 device_id     — logical slot, e.g. "device6". When set, both the serial
#                      and the output file are read from the host .env so the
#                      same loop binary serves any number of slots. The matching
#                      template unit is vpt-emulator-fifo@<device_id>.service.
#
# Self-heal: the emulator sometimes finishes booting with every SurfaceFlinger layer
# hidden — the guest keeps rendering but the display composes nothing, so screencap
# returns an all-zero frame and the stream is black until someone power-cycles the
# display. Sampling the frame and sending SLEEP+WAKEUP forces SF to re-evaluate.

umask 0000

SERIAL="${1:-}"
OUT_FILE="${2:-}"
DEV_ID="${3:-}"

# Resolve serial + output file from .env when $3 (device_id) is set. Lets the
# vpt-emulator-fifo@.service template unit stay generic — one unit, every slot.
if [ -n "$DEV_ID" ]; then
  ENV_FILE="/opt/virtualpytest/backend_host/src/.env"
  if [ ! -f "$ENV_FILE" ]; then
    echo "emulator_screencap.sh: DEV_ID=$DEV_ID but $ENV_FILE is missing" >&2
    exit 1
  fi
  DEV_ID_UPPER=$(echo "$DEV_ID" | tr '[:lower:]' '[:upper:]')
  if [ -z "$SERIAL" ]; then
    SERIAL=$(grep -E "^${DEV_ID_UPPER}_ADB_SERIAL=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r')
  fi
  if [ -z "$OUT_FILE" ]; then
    OUT_FILE=$(grep -E "^${DEV_ID_UPPER}_VIDEO=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r')
  fi
fi

# Defaults — preserve the original emulator-5554 behaviour.
SERIAL="${SERIAL:-emulator-5554}"
OUT_FILE="${OUT_FILE:-/var/www/html/stream/emulator_frames/latest.png}"
OUT_DIR=$(dirname "$OUT_FILE")
OUT="$OUT_FILE"

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
