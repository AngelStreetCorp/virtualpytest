#!/usr/bin/env bash
# migrate_monitor_units.sh — rename the monitor units ON this host (TASK-90 goal 1). Run as root.
#
#   vpt-monitor    -> vpt-monitor-img
#   vpt-transcript -> vpt-monitor-audio
#   vpt-subtitle   -> vpt-monitor-subtitle
#
# Idempotent. Called by update_core.sh and deploy_customer.sh after the code is pushed, and by install_host.sh before it
# installs units (enabling a new unit whose Alias= names an existing unit file fails, so the old file must go first).
#
# For each pair with an old unit file and no new one:
#   1. remember enabled / active (activating counts as active) in <old>.service.state-task90;
#   2. render the new unit from the deployed tree first, without enabling it (a render failure leaves the old unit untouched);
#   3. back the old file up as <old>.service.bak-task90, disable --now it, delete it, move its .service.d drop-ins
#      (e.g. transcription.conf) to the new name, daemon-reload;
#   4. enable and start the new unit as the old one was, and report a failure of either (exit 1).
# The new unit's [Install] has Alias=<old name>, so `systemctl restart vpt-transcript` keeps working where it was enabled.
# A unit that was disabled (lite hosts) stays disabled and its old name no longer resolves.
# Recovery: old file gone, new unit absent, a .bak-task90 present (an interrupted run) -> the new unit is rendered and the
# state recorded in the sidecar is restored.
#
# Usage: sudo bash migrate_monitor_units.sh [--project-root /opt/virtualpytest] [--systemd-dir <dir>] [--dry-run]
# Exit 0 when nothing to do or everything migrated, 1 when a render / enable / start failed.
set -uo pipefail

PROJECT_ROOT="/opt/virtualpytest"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift ;;
    --systemd-dir)  SYSTEMD_DIR="$2"; shift ;;
    --dry-run)      DRY_RUN=true ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

# old unit | new unit | template basename (backend_host/config/services/linux/<basename>.service)
PAIRS=(
  "vpt-monitor|vpt-monitor-img|monitor-img"
  "vpt-transcript|vpt-monitor-audio|monitor-audio"
  "vpt-subtitle|vpt-monitor-subtitle|monitor-subtitle"
)
INSTALL_SERVICE="${PROJECT_ROOT}/setup/local/linux/backend_host/install_service.sh"
rc=0
say() { echo "migrate_monitor_units: $*"; }

render_new() { bash "$INSTALL_SERVICE" "$1" --no-enable >/dev/null; }

restore_state() {   # restore_state <new> <enabled> <active>
  local new="$1" was_enabled="$2" was_active="$3"
  systemctl daemon-reload
  if [[ "$was_enabled" = enabled ]]; then
    systemctl enable "$new" >/dev/null 2>&1 || { say "${new}: enable FAILED"; rc=1; }
  fi
  if [[ "$was_active" = active || "$was_active" = activating ]]; then
    systemctl start "$new" || { say "${new}: start FAILED"; rc=1; }
  fi
}

for pair in "${PAIRS[@]}"; do
  IFS='|' read -r old new tmpl <<< "$pair"
  oldf="${SYSTEMD_DIR}/${old}.service"; newf="${SYSTEMD_DIR}/${new}.service"
  bak="${oldf}.bak-task90"; sidecar="${oldf}.state-task90"

  if [[ ! -f "$oldf" && ! -f "$newf" && -f "$bak" ]]; then
    say "${old}: recovering an interrupted migration (${new} missing, backup present)"
    $DRY_RUN && continue
    read -r was_enabled was_active < "$sidecar" 2>/dev/null || { was_enabled=""; was_active=""; }
    if ! render_new "$tmpl"; then say "${old} -> ${new}: render FAILED (backup kept: ${bak})"; rc=1; continue; fi
    restore_state "$new" "$was_enabled" "$was_active"
    say "${old} -> ${new} (recovered; was ${was_enabled:-unknown}/${was_active:-unknown})"
    continue
  fi
  if [[ ! -f "$oldf" ]]; then
    say "${old}: no old unit file, nothing to do"
    continue
  fi
  if [[ -f "$newf" ]]; then
    say "${old}: ${new} already exists, skipping"
    continue
  fi
  if $DRY_RUN; then
    say "${old} -> ${new}: DRY-RUN would migrate"
    continue
  fi

  was_enabled=$(systemctl is-enabled "$old" 2>/dev/null || true)
  was_active=$(systemctl is-active "$old" 2>/dev/null || true)
  echo "${was_enabled} ${was_active}" > "$sidecar"

  # render first: the new unit coexists with the old one until the old file goes; only `enable` would conflict
  if ! render_new "$tmpl"; then
    say "${old} -> ${new}: render FAILED, old unit left untouched"
    rm -f "$sidecar"
    rc=1
    continue
  fi
  cp -a "$oldf" "$bak"
  systemctl disable --now "$old" 2>/dev/null || true
  rm -f "$oldf"
  if [[ -d "${oldf%.service}.service.d" ]]; then
    mv "${oldf%.service}.service.d" "${newf%.service}.service.d"
  fi
  restore_state "$new" "$was_enabled" "$was_active"
  say "${old} -> ${new} (was ${was_enabled:-unknown}/${was_active:-unknown}; old file kept as ${bak})"
  rm -f "$sidecar"
done
exit $rc
