#!/bin/bash
# Start the adb screencap loop of every screencap device in .env on each vpt-stream start.
#
# vpt-stream only READS DEVICEn_VIDEO=/var/www/html/stream/emulator_frames/deviceN/latest.png;
# the PNG is written by vpt-emulator-fifo@deviceN (emulator_screencap.sh). Invoked by
# vpt-stream.service as:
#
#   ExecStartPre=-+/opt/virtualpytest/setup/local/linux/backend_host/ensure_screencap_loops.sh
#
# `-` ignores a non-zero exit and `+` runs as root; the script also always exits 0, so a
# screencap problem never stops the other grabbers.
#
# What it does:
#   1. Find every DEVICEn with DEVICEn_ADB_SERIAL set and DEVICEn_VIDEO under
#      emulator_frames/deviceN/ (the per-slot path; the legacy singleton
#      vpt-emulator-fifo.service writes emulator_frames/latest.png and is left alone).
#   2. Install the vpt-emulator-fifo@ template unit if it is missing.
#   3. Enable + start vpt-emulator-fifo@deviceN for each of them (--no-block: this runs
#      inside vpt-stream's start job and the loop unit is ordered Before= it).
#   4. Disable + stop instances whose slot is no longer a screencap device in .env.
#
# No `set -e` — every failure is logged and ignored.

PROJECT_ROOT="/opt/virtualpytest"
ENV_FILE="$PROJECT_ROOT/backend_host/src/.env"
TEMPLATE="/etc/systemd/system/vpt-emulator-fifo@.service"

log_info() { echo "INFO: $*"; }
log_warn() { echo "WARN: $*"; }

trap 'exit 0' EXIT

[ -f "$ENV_FILE" ] || { log_warn "$ENV_FILE missing — no screencap loops"; exit 0; }

env_value() {
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r"'
}

wanted=()
for n in $(grep -oE '^DEVICE[0-9]+_ADB_SERIAL=' "$ENV_FILE" | grep -oE '[0-9]+' | sort -un); do
  serial=$(env_value "DEVICE${n}_ADB_SERIAL")
  video=$(env_value "DEVICE${n}_VIDEO")
  [ -n "$serial" ] || continue
  case "$video" in
    */emulator_frames/device${n}/*) wanted+=("device${n}") ;;
  esac
done

if [ ${#wanted[@]} -gt 0 ] && [ ! -f "$TEMPLATE" ]; then
  log_info "installing the vpt-emulator-fifo@ template"
  bash "$PROJECT_ROOT/setup/local/linux/backend_host/install_service.sh" emulator-fifo \
    || log_warn "template install failed"
fi

for dev in "${wanted[@]}"; do
  unit="vpt-emulator-fifo@${dev}.service"
  if ! systemctl is-enabled --quiet "$unit" 2>/dev/null || ! systemctl is-active --quiet "$unit" 2>/dev/null; then
    log_info "starting $unit"
    systemctl enable --now --no-block "$unit" || log_warn "could not start $unit"
  fi
done

for unit in $(systemctl list-units --all --plain --no-legend 'vpt-emulator-fifo@*.service' 2>/dev/null | awk '{print $1}'); do
  dev=${unit#vpt-emulator-fifo@}
  dev=${dev%.service}
  if [[ ! " ${wanted[*]} " == *" $dev "* ]]; then
    log_info "stopping $unit (no longer a screencap device in .env)"
    systemctl disable --now --no-block "$unit" || log_warn "could not stop $unit"
  fi
done
