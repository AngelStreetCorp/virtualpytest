#!/usr/bin/env bash
# ensure_host_prereqs.sh — two things a deploy must guarantee ON every host (TASK-90 follow-up). Run as root. Idempotent.
#
#   1. sudoers: the account vpt-host runs as (vpt_user) may `systemctl start|stop|restart vpt-*`. The Settings profile picker, the dashboard
#      autofix and "restart service" all restart units through `sudo -n systemctl`; on a host installed before that rule existed they fail
#      ("Restart failed for vpt-monitor-img ..."). install_host.sh writes the rule on a new host (STEP 9); this adds it to an old one, as its
#      own drop-in file (`<sudoers dir>/vpt-restart`) with exactly the three lines install_host.sh writes, checked with `visudo -cf` before
#      it is moved into place. Nothing is touched when some sudoers file already grants `restart vpt-*`, and the existing files are never edited.
#   2. the vpt-timeline unit (TASK-94): rendered from backend_host/config/services/linux/timeline.service into <systemd dir>/vpt-timeline.service
#      and NOT enabled or started. The service is opt-in per device (DEVICE<N>_TIMELINE=true in the host .env) and per host (systemctl enable
#      --now vpt-timeline); update_core.sh pushes code only, so without this the unit would never exist on a host that was installed earlier.
#      Skipped on a lite host (HOST_PROFILE=lite).
#   3. the HID udev rule (`71-vpt-hid-signal.rules`, from setup/local/linux/backend_host/udev/): lets vpt_user read the HDMI signal flag of
#      MacroSilicon capture dongles (shared/src/lib/utils/hdmi_signal.py). Without it the monitor keeps the image detector (no error).
#
# Called by update_core.sh after the code is pushed. Opt out of the sudoers part with VPT_SKIP_SUDOERS=1 in the environment of the run.
#
# Usage: sudo bash ensure_host_prereqs.sh [--project-root /opt/virtualpytest] [--systemd-dir <dir>] [--sudoers-dir <dir>] [--dry-run]
#        (env: VISUDO, SYSTEMCTL override the commands, UDEV_DIR the rules dir, for tests)
# Exit 0 when everything is in place or was put in place, 1 when a step failed (the deploy is not failed by it).
set -uo pipefail

PROJECT_ROOT="/opt/virtualpytest"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SUDOERS_DIR="${SUDOERS_DIR:-/etc/sudoers.d}"
VISUDO="${VISUDO:-visudo}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
UDEV_DIR="${UDEV_DIR:-/etc/udev/rules.d}"
RUN_AS="${VPT_RUN_AS:-vpt_user}"
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift ;;
    --systemd-dir)  SYSTEMD_DIR="$2"; shift ;;
    --sudoers-dir)  SUDOERS_DIR="$2"; shift ;;
    --dry-run)      DRY_RUN=true ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

rc=0

ensure_sudoers() {
  if [[ "${VPT_SKIP_SUDOERS:-}" == "1" ]]; then
    echo "ensure_host_prereqs: sudoers skipped (VPT_SKIP_SUDOERS=1)"; return 0
  fi
  [[ -d "$SUDOERS_DIR" ]] || { echo "ensure_host_prereqs: no sudoers dir $SUDOERS_DIR, nothing done"; return 0; }
  if grep -rqsE "systemctl restart vpt-\*" "$SUDOERS_DIR"; then
    echo "ensure_host_prereqs: sudoers already lets $RUN_AS restart vpt-* units"; return 0
  fi
  local target="$SUDOERS_DIR/vpt-restart"
  if $DRY_RUN; then echo "ensure_host_prereqs: would install $target (start|stop|restart vpt-*)"; return 0; fi
  local tmp
  tmp="$(mktemp "$SUDOERS_DIR/.vpt-restart.XXXXXX")" || { echo "ensure_host_prereqs: cannot write in $SUDOERS_DIR" >&2; rc=1; return; }
  cat > "$tmp" <<RULES
# Added by update_core.sh (ensure_host_prereqs.sh): the same three lines install_host.sh STEP 9 writes. Start/stop/restart of any vpt-* unit:
# the Settings monitoring-profile picker, dashboard autofix and the per-service controls need them.
$RUN_AS ALL=(root) NOPASSWD: /bin/systemctl start vpt-*, /usr/bin/systemctl start vpt-*
$RUN_AS ALL=(root) NOPASSWD: /bin/systemctl stop vpt-*, /usr/bin/systemctl stop vpt-*
$RUN_AS ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*
RULES
  chmod 0440 "$tmp"
  chown root:root "$tmp" 2>/dev/null || true
  if ! $VISUDO -cf "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    echo "ensure_host_prereqs: the sudoers rule did not pass visudo -cf; nothing installed" >&2; rc=1; return
  fi
  mv -f "$tmp" "$target"
  echo "ensure_host_prereqs: installed $target"
}

ensure_timeline_unit() {
  local tpl="$PROJECT_ROOT/backend_host/config/services/linux/timeline.service"
  local unit="$SYSTEMD_DIR/vpt-timeline.service"
  [[ -f "$tpl" ]] || { echo "ensure_host_prereqs: no timeline template in this tree, unit not touched"; return 0; }
  local envf
  for envf in "$PROJECT_ROOT/backend_host/src/.env" "$PROJECT_ROOT/.env"; do
    if [[ -r "$envf" ]] && grep -qE '^HOST_PROFILE=lite' "$envf"; then
      echo "ensure_host_prereqs: lite host, no vpt-timeline unit"; return 0
    fi
  done
  local rendered
  rendered="$(sed "s#%PROJECT_ROOT%#$PROJECT_ROOT#g" "$tpl")"
  if [[ -f "$unit" ]] && [[ "$(cat "$unit")" == "$rendered" ]]; then
    echo "ensure_host_prereqs: vpt-timeline.service is up to date"; return 0
  fi
  if $DRY_RUN; then echo "ensure_host_prereqs: would write $unit (not enabled, not started)"; return 0; fi
  local tmp="$unit.tmp.$$"
  printf '%s\n' "$rendered" > "$tmp" && mv -f "$tmp" "$unit" || { rm -f "$tmp"; echo "ensure_host_prereqs: cannot write $unit" >&2; rc=1; return; }
  $SYSTEMCTL daemon-reload || { echo "ensure_host_prereqs: daemon-reload failed" >&2; rc=1; return; }
  echo "ensure_host_prereqs: installed $unit (not enabled, not started: opt in with DEVICE<N>_TIMELINE=true and systemctl enable --now vpt-timeline)"
}

ensure_hid_signal_rule() {
  local src="$PROJECT_ROOT/setup/local/linux/backend_host/udev/71-vpt-hid-signal.rules"
  local dst="$UDEV_DIR/71-vpt-hid-signal.rules"
  [[ -f "$src" ]] || { echo "ensure_host_prereqs: no HID udev rule in this tree, not touched"; return 0; }
  if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
    echo "ensure_host_prereqs: 71-vpt-hid-signal.rules is up to date"; return 0
  fi
  if $DRY_RUN; then echo "ensure_host_prereqs: would install $dst"; return 0; fi
  cp "$src" "$dst" || { echo "ensure_host_prereqs: cannot write $dst" >&2; rc=1; return; }
  udevadm control --reload-rules 2>/dev/null || true
  udevadm trigger --subsystem-match=hidraw 2>/dev/null || true
  echo "ensure_host_prereqs: installed $dst"
}

ensure_sudoers
ensure_timeline_unit
ensure_hid_signal_rule
exit $rc
