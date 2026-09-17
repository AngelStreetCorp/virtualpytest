#!/bin/bash
# =============================================================================
# VirtualPyTest - Give an existing Android emulator host audio (idempotent)
# =============================================================================
# Turns a host's vpt-emulator.service from `-no-window -no-audio` into `-qt-hide-window
# -audio pa` playing into a PulseAudio daemon of our own, and installs the watchdog that
# restarts the emulator if it ever drops off that daemon. Safe to re-run; also called by
# install_android_emulator.sh on a fresh install (with --no-restart).
#
#   sudo bash /opt/virtualpytest/setup/proxmox/vm/runner/enable_emulator_audio.sh [--no-restart]
#
# What it installs / changes:
#   vpt-pulse.service         PulseAudio as $SERVICE_USER, no default script, one null sink
#                             `emulator`, anonymous unix socket /run/vpt-pulse/native. A daemon
#                             of our own because the per-login ones (`pulseaudio --start` from
#                             the VNC xstartup, a jndoye ssh session) come and go with their
#                             sessions and race for TCP 4713 — on labox-tablet that port
#                             belonged to a jndoye login, not to vpt_user.
#   vpt-emulator.service      patched in place: DISPLAY=:1 + XAUTHORITY (the hidden Qt window
#                             needs vpt-vnc's X server), PULSE_SERVER=unix:/run/vpt-pulse/native,
#                             After/Wants vpt-vnc + vpt-pulse, `-qt-hide-window -audio pa`.
#   vpt-emulator-audio.timer  every minute: emulator active >2 min with audio on, but no qemu
#                             client on the daemon -> restart vpt-emulator. QEMU's pa backend
#                             never reconnects, so a daemon restart would otherwise leave the
#                             emulator silent for good (backend_host/scripts/emulator_audio_watchdog.sh).
#   backend_host/src/.env     DEVICE1_VIDEO_AUDIO=default — the grabber records the sink monitor
# Then, unless --no-restart: restart vpt-emulator (a cold boot, ~5-8 min) and vpt-stream.
#
# Why -qt-hide-window rather than -no-window, and why PULSE_SERVER must be explicit:
# the comment above ExecStart in install_android_emulator.sh.
# =============================================================================
set -e

PROJECT_DIR="${PROJECT_DIR:-/opt/virtualpytest}"
SERVICE_USER="${SERVICE_USER:-vpt_user}"
RESTART=1
for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0 ;;
    *) echo "Unknown argument: $arg (only --no-restart)"; exit 1 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  exec sudo PROJECT_DIR="$PROJECT_DIR" SERVICE_USER="$SERVICE_USER" bash "$0" "$@"
fi

UNIT=/etc/systemd/system/vpt-emulator.service
ENV_FILE="$PROJECT_DIR/backend_host/src/.env"
WATCHDOG="$PROJECT_DIR/backend_host/scripts/emulator_audio_watchdog.sh"
XAUTH=/var/lib/$SERVICE_USER/.Xauthority        # vpt-vnc always runs with HOME=/var/lib/<user>
SOCK=/run/vpt-pulse/native

[ -f "$UNIT" ] || { echo "❌ $UNIT not found — run install_android_emulator.sh first"; exit 1; }
[ -f "$WATCHDOG" ] || { echo "❌ $WATCHDOG missing — update the checkout first"; exit 1; }
HOME_DIR=$(getent passwd "$SERVICE_USER" | cut -d: -f6)
[ -n "$HOME_DIR" ] || { echo "❌ user $SERVICE_USER not found"; exit 1; }

echo "🔊 Enabling emulator audio (user $SERVICE_USER, home $HOME_DIR)"

if ! command -v pulseaudio >/dev/null || ! command -v pactl >/dev/null; then
  echo "   → installing pulseaudio pulseaudio-utils"
  apt-get install -y -qq pulseaudio pulseaudio-utils >/dev/null
fi

# --- 1. vpt-pulse.service ---------------------------------------------------------------
tee /etc/systemd/system/vpt-pulse.service > /dev/null <<UNITEOF
[Unit]
Description=VirtualPyTest PulseAudio (emulator audio sink)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=HOME=$HOME_DIR
Environment=PULSE_RUNTIME_PATH=/run/vpt-pulse
RuntimeDirectory=vpt-pulse
RuntimeDirectoryMode=0755
# -n: no default.pa, so no udev/ALSA probing, no fight over TCP 4713 with a login daemon.
# The null sink is the only sink, hence the default; its monitor is the default source
# the grabber records with "-f pulse -i default". (No backticks in this heredoc: it is
# unquoted so that \$SERVICE_USER and friends expand, and backticks would run as commands.)
ExecStart=/usr/bin/pulseaudio --daemonize=no --disallow-exit --exit-idle-time=-1 --use-pid-file=no --log-target=journal -n \\
  --load="module-null-sink sink_name=emulator sink_properties=device.description=Emulator" \\
  --load="module-native-protocol-unix socket=$SOCK auth-anonymous=1"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNITEOF

# --- 2. watchdog timer ---------------------------------------------------------------
tee /etc/systemd/system/vpt-emulator-audio.service > /dev/null <<UNITEOF
[Unit]
Description=VirtualPyTest emulator audio watchdog (restart the emulator if it left PulseAudio)
After=vpt-pulse.service vpt-emulator.service

[Service]
Type=oneshot
Environment=SERVICE_USER=$SERVICE_USER
ExecStart=/bin/bash $WATCHDOG
UNITEOF
tee /etc/systemd/system/vpt-emulator-audio.timer > /dev/null <<UNITEOF
[Unit]
Description=VirtualPyTest emulator audio watchdog (every minute)

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
UNITEOF

# --- 3. patch vpt-emulator.service in place ---------------------------------------------
[ -f "$UNIT.bak-before-audio" ] || cp "$UNIT" "$UNIT.bak-before-audio"
if ! grep -q "vpt-pulse.service" "$UNIT"; then
  sed -i "/^\[Unit\]/a After=vpt-vnc.service vpt-pulse.service\nWants=vpt-vnc.service vpt-pulse.service" "$UNIT"
fi
if grep -q "^Environment=DISPLAY=" "$UNIT"; then
  sed -i "s|^Environment=DISPLAY=.*|Environment=DISPLAY=:1|" "$UNIT"
else
  sed -i "/^User=/a Environment=DISPLAY=:1" "$UNIT"
fi
if grep -q "^Environment=XAUTHORITY=" "$UNIT"; then
  sed -i "s|^Environment=XAUTHORITY=.*|Environment=XAUTHORITY=$XAUTH|" "$UNIT"
else
  sed -i "/^Environment=DISPLAY=/a Environment=XAUTHORITY=$XAUTH" "$UNIT"
fi
if grep -q "^Environment=PULSE_SERVER=" "$UNIT"; then
  sed -i "s|^Environment=PULSE_SERVER=.*|Environment=PULSE_SERVER=unix:$SOCK|" "$UNIT"
else
  sed -i "/^Environment=XAUTHORITY=/a Environment=PULSE_SERVER=unix:$SOCK" "$UNIT"
fi
sed -i -e "s/ -no-window / -qt-hide-window /" -e "s/ -no-audio / -audio pa /" -e "s/ -noaudio / -audio pa /" "$UNIT"
if ! grep -qE "^ExecStart=.* -audio pa( |$|\\\\)" "$UNIT"; then
  echo "❌ ExecStart in $UNIT still has no '-audio pa' — patch it by hand:"; grep "^ExecStart" "$UNIT"; exit 1
fi
echo "   ✅ $UNIT patched (backup: $UNIT.bak-before-audio)"

# --- 4. .env ------------------------------------------------------------------------------
if [ -f "$ENV_FILE" ]; then
  if grep -q "^DEVICE1_VIDEO_AUDIO=" "$ENV_FILE"; then
    sed -i "s/^DEVICE1_VIDEO_AUDIO=.*/DEVICE1_VIDEO_AUDIO=default/" "$ENV_FILE"
  else
    echo "DEVICE1_VIDEO_AUDIO=default" >> "$ENV_FILE"
  fi
  echo "   ✅ $ENV_FILE: DEVICE1_VIDEO_AUDIO=default"
else
  echo "   ⚠️  $ENV_FILE not found — set DEVICE1_VIDEO_AUDIO=default when it exists"
fi

# --- 5. activate --------------------------------------------------------------------------
systemctl daemon-reload
systemctl enable --now vpt-pulse.service >/dev/null 2>&1
systemctl enable --now vpt-emulator-audio.timer >/dev/null 2>&1
for _ in 1 2 3 4 5 6 7 8 9 10; do runuser -u "$SERVICE_USER" -- pactl -s "unix:$SOCK" info >/dev/null 2>&1 && break; sleep 0.5; done
if runuser -u "$SERVICE_USER" -- pactl -s "unix:$SOCK" info 2>/dev/null | grep -q "Default Sink: emulator"; then
  echo "   ✅ vpt-pulse.service answers on $SOCK (sink: emulator)"
else
  echo "❌ vpt-pulse.service is not answering on $SOCK:"; journalctl -u vpt-pulse --no-pager -n 10; exit 1
fi

if [ "$RESTART" = 1 ]; then
  echo "   → restarting vpt-emulator (cold boot, allow 5-8 min) and vpt-stream"
  systemctl restart vpt-emulator.service
  systemctl try-restart vpt-stream.service 2>/dev/null || true
fi

echo ""
echo "Check once the guest has booted:"
echo "  runuser -u $SERVICE_USER -- pactl -s unix:$SOCK list short clients | grep qemu   # emulator on the daemon"
echo "  ffprobe -v error -show_entries stream=codec_name -of csv=p=0 \$(ls -t /var/www/html/stream/capture1/hot/segments/*.ts | head -1)   # h264 + aac"
echo "  systemctl list-timers vpt-emulator-audio.timer --no-pager"
