#!/bin/bash
# =============================================================================
# emulator_audio_watchdog.sh — restart the emulator if it has fallen off PulseAudio
# =============================================================================
# Run every minute by vpt-emulator-audio.timer (installed by
# setup/proxmox/vm/runner/enable_emulator_audio.sh) on Android emulator hosts.
#
# QEMU's PulseAudio backend connects once, when the emulator process starts, and never
# reconnects. When vpt-pulse.service restarts (crash, package upgrade, a hand
# `systemctl restart`), the guest keeps playing into a dead stream and the device
# reports -91 dB forever — an audio-loss incident that no one can clear. Restarting
# vpt-emulator is the only cure, and it costs a cold boot (~5-8 min), so the check is
# deliberately conservative: it acts only when the emulator has been active for more
# than two minutes, its unit runs `-audio pa`, the daemon is reachable, and the daemon
# still lists no qemu client.
#
# The grabber needs no help here: when the daemon goes away its ffmpeg exits, and
# run_ffmpeg.sh's loop restarts it against whichever daemon ensure_pulse_server finds.
set -u

UNIT=vpt-emulator.service
PULSE=vpt-pulse.service
SOCK=unix:/run/vpt-pulse/native
USER_NAME="${SERVICE_USER:-vpt_user}"
GRACE_US=120000000   # 2 min: QEMU registers on the daemon within seconds of starting

log() { logger -t vpt-emulator-audio "$*"; echo "$*"; }

systemctl is-active --quiet "$UNIT" || exit 0
systemctl show "$UNIT" -p ExecStart --value | grep -q -- "-audio pa" || exit 0

started_us=$(systemctl show "$UNIT" -p ActiveEnterTimestampMonotonic --value)
now_us=$(awk '{printf "%d", $1 * 1000000}' /proc/uptime)
[ -n "$started_us" ] && [ "$((now_us - started_us))" -ge "$GRACE_US" ] || exit 0

if ! systemctl is-active --quiet "$PULSE"; then
  log "$PULSE is not active — starting it (the emulator is checked again next minute)"
  systemctl start "$PULSE"
  exit 0
fi

if ! clients=$(runuser -u "$USER_NAME" -- pactl -s "$SOCK" list short clients 2>/dev/null); then
  log "$PULSE is active but $SOCK does not answer — leaving it to systemd"
  exit 0
fi

echo "$clients" | grep -q "qemu-system" && exit 0

log "emulator has no stream on $SOCK ($PULSE up since $(systemctl show "$PULSE" -p ActiveEnterTimestamp --value)) — restarting $UNIT"
systemctl restart "$UNIT"
