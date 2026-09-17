#!/usr/bin/env bash
set -euo pipefail

# ---- VM targets (IPs or SSH aliases) ----
#
# Per-node lists. This script is copied to each Proxmox node and its copy keeps
# that node's own targets, so these are defaults for a fresh node, not the live
# values — check the copy on the node before assuming what it reaches.
#
# `host1` used to appear here and resolves nowhere: an alias that does not exist
# in the node's ~/.ssh/config is skipped silently, so a target can look
# configured while never being deployed to. Use an IP, or an alias you have
# verified with `ssh -G <alias>`.
SERVER_IP="192.168.0.103"
FRONTEND_IP="192.168.0.105"
HOST_IPS="192.168.0.109,192.168.0.110"
RUNNER_IPS=""
HOST_WINDOWS_IPS=""  # e.g. "192.168.0.150,192.168.0.151"

# ---- Internal config (rarely need to change) ----
SSH_USER="${SSH_USER:-$(id -un)}"   # the invoking account; override with SSH_USER=
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_ed25519}"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new"
SYNC_USER="vpt_user"
REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"   # git checkout, or an extracted offline bundle (BUNDLE_MANIFEST.txt)
TARGET_DIR="/opt/virtualpytest"
TARGET_DIR_WINDOWS="/cygdrive/c/virtualpytest/virtualpytest"
SERVER_SERVICE="vpt-server.service"
FRONTEND_SERVICE="vpt-frontend-prod.service"
HOST_SERVICE="vpt-host.service"
WINDOWS_TASK="vpt-host"

# Aux long-running services restarted after vpt-host on each host, but ONLY if
# already active on that host (never start a service that isn't running). This
# step is best-effort / non-blocking: a failure here never aborts the deploy,
# it is collected and reported in the SERVICE RESTART FAILED summary.
AUX_SERVICES=(
  vpt-stream
  vpt-monitor
  vpt-subtitle
  vpt-transcript
  vpt-archiver
  vpt-avq
  vpt-kpi
)

# Rsync excludes (single source of truth)
RSYNC_EXCLUDES=(
  --exclude='.git'
  --exclude='.github'
  --exclude='.cursor'
  --exclude='.husky'
  --exclude='.env'
  --exclude='venv'
  --exclude='node_modules'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='frontend/public/docs'
  --exclude='frontend/dist'
  --exclude='playwright-report*'
  --exclude='playwright-viewport-report*'
  --exclude='security_report'
  --exclude='backend_host/config/user_data'
  --exclude='backend_host/config/webkit_user_data'
  # frontend/.env.production is overlay-owned (deploy_customer.sh / offline bundle). Not
  # matched by '.env' (exact basename), so without this line a run from a plain checkout
  # (which has none) would DELETE the target's overlay-deployed copy via --delete.
  # Bundle mode re-includes it (push_filters) when the bundle carries it.
  --exclude='frontend/.env.production'
  --exclude='frontend/vite.config.local.json'
  --exclude='frontend/public/branding.json'
  --exclude='frontend/public/brand'
  --exclude='frontend/public/favicon.ico'
  --exclude='frontend/public/logo.png'
  # Identity maps are customer-owned (overlay): excluded from a plain push so a target's
  # copies survive, re-included by bundle mode / the overlay stage like the frontend config.
  # The frontend reads ONLY frontend/public/data/*.json (identityMapCache.ts); the backend
  # reads test_scripts/*.json. Both pairs travel together (BUG-0066).
  --exclude='test_scripts/script_identity_map.json'
  --exclude='test_scripts/campaign_identity_map.json'
  --exclude='test_campaign/campaign_identity_map.json'
  --exclude='frontend/public/data/script_identity_map.json'
  --exclude='frontend/public/data/campaign_identity_map.json'
)

# ---- Source tree: git checkout (canonical) or extracted offline bundle ----
# build_customer_bundle.sh writes BUNDLE_MANIFEST.txt at the root of the merged tree it
# packs (no .git inside). In that mode Step 1 (git pull) is skipped and the customer
# frontend configuration the bundle carries (= what the overlay shipped, nothing else:
# staging already excluded the public copies) is re-included ahead of the excludes, like
# deploy_customer.sh does on its push. A git checkout keeps the classic behaviour: those
# paths stay excluded so the checkout's public logo/favicon never replace a target's.
BUNDLE_MODE=false
if [[ ! -e "${REPO_DIR}/.git" && -f "${REPO_DIR}/BUNDLE_MANIFEST.txt" ]]; then
  BUNDLE_MODE=true
fi
FRONTEND_CONFIG_PATHS=(
  frontend/.env.production
  frontend/vite.config.local.json
  frontend/public/branding.json
  frontend/public/brand
  frontend/public/favicon.ico
  frontend/public/logo.png
  # identity maps (display names + TC prefixes): frontend copy read by the browser,
  # test_scripts copy read by the server — customer-owned, see BUG-0066
  frontend/public/data/script_identity_map.json
  frontend/public/data/campaign_identity_map.json
  test_scripts/script_identity_map.json
  test_scripts/campaign_identity_map.json
)
PUSH_FILTERS=()
push_filters() {
  PUSH_FILTERS=()
  local p
  if ${BUNDLE_MODE}; then
    for p in "${FRONTEND_CONFIG_PATHS[@]}"; do
      [[ -e "${REPO_DIR}/${p}" ]] || continue
      PUSH_FILTERS+=("--include=/${p}")
      [[ -d "${REPO_DIR}/${p}" ]] && PUSH_FILTERS+=("--include=/${p}/**")
    done
  fi
  PUSH_FILTERS+=("${RSYNC_EXCLUDES[@]}")
}

# ---- Helpers ----
is_ipv4_target() {
  local target="$1"
  [[ "${target}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

build_ssh_target() {
  local target="$1"

  if [[ "${target}" == *"@"* ]]; then
    printf '%s\n' "${target}"
    return
  fi

  if is_ipv4_target "${target}"; then
    printf '%s@%s\n' "${SSH_USER}" "${target}"
    return
  fi

  # SSH aliases / hostnames should be used as-is so ~/.ssh/config can define user/port/jump host.
  printf '%s\n' "${target}"
}

run_ssh() {
  local host="$1"; shift
  local ssh_target
  ssh_target="$(build_ssh_target "${host}")"
  echo -e "\n==> [${host}] $*"
  ssh ${SSH_OPTS} "${ssh_target}" "$@"
}

wait_for_service_running() {
  local host="$1"
  local service="$2"
  local timeout_seconds="${3:-45}"
  local poll_interval=3
  local attempt=0
  local max_attempts=$(( timeout_seconds / poll_interval ))

  while (( attempt < max_attempts )); do
    attempt=$(( attempt + 1 ))

    local state_output
    state_output="$(run_ssh "${host}" "sudo -n systemctl show \"${service}\" --property=ActiveState --property=SubState --property=Result --property=ExecMainStatus --no-pager" | tail -n 4)"

    local active_state sub_state result_state exec_main_status
    active_state="$(printf '%s\n' "${state_output}" | awk -F= '/^ActiveState=/{print $2}')"
    sub_state="$(printf '%s\n' "${state_output}" | awk -F= '/^SubState=/{print $2}')"
    result_state="$(printf '%s\n' "${state_output}" | awk -F= '/^Result=/{print $2}')"
    exec_main_status="$(printf '%s\n' "${state_output}" | awk -F= '/^ExecMainStatus=/{print $2}')"

    echo "==> [${host}] ${service} state: ActiveState=${active_state:-unknown} SubState=${sub_state:-unknown} Result=${result_state:-unknown} ExecMainStatus=${exec_main_status:-unknown}"

    if [[ "${active_state}" == "active" && "${sub_state}" == "running" ]]; then
      return 0
    fi

    if [[ "${result_state}" != "success" && "${result_state}" != "none" && -n "${result_state}" ]]; then
      echo "==> [${host}] ${service} failed during startup (Result=${result_state})"
      run_ssh "${host}" "sudo -n systemctl status --no-pager \"${service}\" || true"
      run_ssh "${host}" "sudo -n journalctl -u \"${service}\" -n 80 --no-pager || true"
      return 1
    fi

    if [[ "${active_state}" == "failed" || "${active_state}" == "inactive" ]]; then
      echo "==> [${host}] ${service} is not running (ActiveState=${active_state})"
      run_ssh "${host}" "sudo -n systemctl status --no-pager \"${service}\" || true"
      run_ssh "${host}" "sudo -n journalctl -u \"${service}\" -n 80 --no-pager || true"
      return 1
    fi

    sleep "${poll_interval}"
  done

  echo "==> [${host}] ${service} did not reach active/running within ${timeout_seconds}s"
  run_ssh "${host}" "sudo -n systemctl status --no-pager \"${service}\" || true"
  run_ssh "${host}" "sudo -n journalctl -u \"${service}\" -n 80 --no-pager || true"
  return 1
}

restart_and_status() {
  local host="$1"
  local service="$2"
  run_ssh "${host}" "sudo -n systemctl restart \"${service}\""
  wait_for_service_running "${host}" "${service}"
  run_ssh "${host}" "sudo -n systemctl status --no-pager \"${service}\""
}

# host -> "svc1, svc2" of aux services that failed to restart (populated by
# restart_aux_services, rendered in the SERVICE RESTART FAILED summary).
declare -A AUX_RESTART_FAIL=()

# Optional single aux service to restart (set via `--restart <service>`).
# Empty means restart all of AUX_SERVICES.
RESTART_SERVICE=""

# Restart the aux long-running services on a host, but only those currently
# active. Best-effort: always returns 0 so it never aborts the deploy under
# `set -e`. Per-host failures are recorded in AUX_RESTART_FAIL.
# If RESTART_SERVICE is set, only that one service is considered.
restart_aux_services() {
  local host="$1"
  local services=("${AUX_SERVICES[@]}")
  if [[ -n "${RESTART_SERVICE}" ]]; then
    services=("${RESTART_SERVICE}")
  fi
  echo -e "\n==> [${host}] Restarting aux services (only those already active): ${services[*]}"
  local failed=()
  local svc
  for svc in "${services[@]}"; do
    # is-active is true only when the unit is running; skip otherwise so we
    # never start a service that wasn't already up on this host.
    if run_ssh "${host}" "sudo -n systemctl is-active --quiet \"${svc}\""; then
      echo "==> [${host}] ${svc} active -> restarting"
      if run_ssh "${host}" "sudo -n systemctl restart \"${svc}\"" \
         && wait_for_service_running "${host}" "${svc}" 30; then
        : # came back healthy
      else
        echo "==> [${host}] ${svc} FAILED to restart"
        failed+=("${svc}")
      fi
    else
      echo "==> [${host}] ${svc} not active -> skipping"
    fi
  done
  if [[ ${#failed[@]} -gt 0 ]]; then
    local joined
    joined="$(printf '%s, ' "${failed[@]}")"
    AUX_RESTART_FAIL["${host}"]="${joined%, }"
  fi
  return 0
}

# Feature systemd units (features/*/backend_host/services/*.service): rendered by
# install_host.sh at install time only, so a deploy that moves/adds/removes a feature
# would leave a stale vpt-<unit>.service behind. The deployed tree ships
# setup/proxmox/node/reconcile_feature_units.sh (standalone, runs on the host): render +
# enable + restart changed/missing units, disable + remove units of features no longer
# in the tree, core units never touched. Runs after vpt-host is back and before the aux
# restart (a unit it just restarted may be restarted once more there — harmless).
# Guarded: a target whose tree predates the script is left as before. Best-effort.
FEATURE_UNIT_FAIL=()
reconcile_feature_units_remote() {
  local host="$1"
  local script="${TARGET_DIR}/setup/proxmox/node/reconcile_feature_units.sh"
  if ! run_ssh "${host}" "sudo -n test -f ${script}"; then
    echo "==> [${host}] ${script} not on the target (older tree) -> feature units not reconciled"
    return 0
  fi
  if ! run_ssh "${host}" "sudo -n bash ${script} --project-root ${TARGET_DIR}"; then
    echo "==> [${host}] feature unit reconcile reported problems (deploy not failed)"
    FEATURE_UNIT_FAIL+=("${host}")
  fi
  return 0
}

# Push code directly to /opt/virtualpytest on a Linux target VM
rsync_push() {
  local target_host="$1"
  local ssh_target
  ssh_target="$(build_ssh_target "${target_host}")"
  echo -e "\n==> [proxmox -> ${target_host}] rsync push"
  # --chown: land the tree owned by ${SYNC_USER} instead of breaking it and
  # repairing it afterwards. `-a` implies -o/-g, and the remote rsync runs as
  # root (--rsync-path="sudo rsync"), so without this every push stamps the
  # whole target tree with the SOURCE's numeric uid/gid — the deploying user's
  # — and -p re-applies the source's mode. That is what un-owned test_scripts/
  # after each deploy, and what wiped the `chmod 777` workaround (BUG-0089).
  # --chown resolves the name on the receiver, so it is correct even though
  # vpt_user's uid differs per host (995 on a Pi, 999 on the VMs).
  if ! rsync -az -q --delete "${PUSH_FILTERS[@]}" \
    --chown="${SYNC_USER}:${SYNC_USER}" \
    --rsync-path="sudo rsync" \
    -e "ssh ${SSH_OPTS}" \
    "${REPO_DIR}/" \
    "${ssh_target}:${TARGET_DIR}/"; then
    echo "==> [${target_host}] rsync FAILED"
    return 1
  fi
  # Secondary net for files rsync does not manage (runtime output a wrongly-owned
  # process created). --chown above already lands the pushed tree correct; this
  # step can no longer be the only thing standing between a deploy and a broken
  # test_scripts/, which is where a virtual script materializes its .vs_<uuid>.py
  # — and where a failure is invisible, because the host's completion callback
  # then carries neither a result nor an error and the server reads that as a
  # pass (BUG-0089).
  #
  # It is also the step a whitelist-sudo host cannot run at all: labox-web grants
  # NOPASSWD for rsync/git/bash/systemctl only, so `sudo -n find` is refused there
  # while the push itself succeeds. Hence the push, not the repair, must be what
  # gets ownership right.
  #
  # `chown -h` (do not dereference): the browser profile directories a host
  # leaves behind under backend_host/config/{user_data,webkit_user_data} hold
  # dangling Singleton{Lock,Cookie,Socket} symlinks. Plain chown follows them,
  # prints "cannot dereference", and `find -exec … +` then exits 1 even though
  # every real file was chowned — which flagged vpt-pi1 and host-clone-1 as
  # OWNERSHIP NOT FIXED when their ownership was in fact fine. -h chowns the
  # link itself, which is also what we want for every symlink in a deploy tree.
  local chown_rc=0
  run_ssh "${target_host}" "sudo -n find ${TARGET_DIR} \
    -path ${TARGET_DIR}/frontend/public/docs -prune -o \
    -path ${TARGET_DIR}/frontend/public/brand -prune -o \
    -not -path '*/.env' -not -path '*/venv/*' \
    -exec chown -h ${SYNC_USER}:${SYNC_USER} {} +" || chown_rc=$?

  # A non-zero chown is a symptom, not the fault itself. Warn only when the
  # invariant BUG-0089 depends on is actually broken: ${SYNC_USER} must be able
  # to write test_scripts/ (owner, or group+group-write, or other-write).
  if (( chown_rc != 0 )) && ! run_ssh "${target_host}" "d=${TARGET_DIR}/test_scripts; \
      [ -d \"\$d\" ] || exit 0; \
      o=\$(stat -c %U \"\$d\"); g=\$(stat -c %G \"\$d\"); m=\$(stat -c %a \"\$d\" | tail -c 4); \
      [ \"\$o\" = '${SYNC_USER}' ] && exit 0; \
      case \"\$m\" in *[2367]) exit 0 ;; esac; \
      [ \"\$g\" = '${SYNC_USER}' ] && case \"\$m\" in ?[2367]?) exit 0 ;; esac; \
      exit 1"; then
    echo "==> [${target_host}] ⚠️  ${TARGET_DIR}/test_scripts is not writable by ${SYNC_USER}"
    echo "==> [${target_host}]    (chown exited ${chown_rc} — no passwordless sudo?)."
    echo "==> [${target_host}]    That breaks virtual-script materialization *silently* (BUG-0089)."
    echo "==> [${target_host}]    Workaround: chmod 777 ${TARGET_DIR}/test_scripts"
    OWNERSHIP_WARNINGS="${OWNERSHIP_WARNINGS} ${target_host}"
  fi

  # Defensive: re-assert exec bit on shell scripts the runtime invokes via
  # `sudo <absolute-path>`. Git tracks these as 100755, but mode arrives as
  # 0664 on some hosts (observed after editor/copy operations on the
  # proxmox source tree). Without +x, sudo rejects the absolute path with
  # "command not found" and the BLE pairing/resume flow fails silently in
  # the controller's background thread — symptom: Repair button on the
  # frontend appears to do nothing. Idempotent.
  run_ssh "${target_host}" "sudo -n chmod +x \
    ${TARGET_DIR}/backend_host/src/controllers/remote/bluetooth/start.sh \
    ${TARGET_DIR}/backend_host/src/controllers/remote/bluetooth/resume.sh \
    2>/dev/null || true"
}

# Push from local repo to a Windows target VM
#
# Permissions model: each Windows host must be bootstrapped ONCE so that the
# vpt-host scheduled-task account inherits access to C:\virtualpytest, e.g.:
#   icacls C:\virtualpytest /reset /T /Q
#   icacls C:\virtualpytest /grant 'vpt_user:(OI)(CI)M' /T /Q
# Once inheritance is in place, this rsync uses -rlz (no -ptgoD) so Cygwin
# does NOT translate POSIX mode bits into explicit NTFS ACEs that would
# override the inherited ACL — every new file/dir created by rsync inherits
# from C:\virtualpytest automatically. No per-file icacls during deploy.
rsync_push_windows() {
  local target_host="$1"
  local ssh_target
  ssh_target="$(build_ssh_target "${target_host}")"
  echo -e "\n==> [proxmox -> ${target_host}] rsync push (Windows)"
  # --blocking-io: Windows hosts running the inbox Win32-OpenSSH (sshd 9.5.5.x) hand the
  # remote rsync non-blocking pipes and it dies on the first write ("safe_write failed …
  # Resource temporarily unavailable (11)"); blocking I/O on the transport avoids it.
  # Verified 2026-09-09 on a failing host (dry run OK with the flag, EAGAIN without).
  rsync -rlz -q --delete --blocking-io --no-perms --chmod=ugo=rwX --no-owner --no-group --omit-dir-times \
    "${PUSH_FILTERS[@]}" \
    -e "ssh ${SSH_OPTS}" \
    "${REPO_DIR}/" \
    "${ssh_target}:${TARGET_DIR_WINDOWS}/"
}

# Restart Windows scheduled task
restart_windows_task() {
  local host="$1"
  echo -e "\n==> [${host}] Restarting Windows scheduled task '${WINDOWS_TASK}'"
  run_ssh "${host}" "powershell.exe -Command \"Stop-ScheduledTask -TaskName '${WINDOWS_TASK}' -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName '${WINDOWS_TASK}'\""
  sleep 5
  run_ssh "${host}" "powershell.exe -Command \"Get-ScheduledTask -TaskName '${WINDOWS_TASK}' | Select-Object TaskName, State | Format-Table -AutoSize\""
}

# ---- Deploy result tracking ----
DEPLOY_OK=()
DEPLOY_FAIL=()
# Hosts whose chown to vpt_user failed (no passwordless sudo) — see BUG-0089.
OWNERSHIP_WARNINGS=""
# Hosts whose live systemd unit differs from the one this tree ships — see
# check_frontend_unit_drift.
UNIT_DRIFT_WARNINGS=""

# Sync + restart (critical — fails immediately)
critical_deploy() {
  local host="$1"
  local service="$2"
  if rsync_push "${host}" && restart_and_status "${host}" "${service}"; then
    DEPLOY_OK+=("${host}")
  else
    DEPLOY_FAIL+=("${host}")
    echo "==> [${host}] CRITICAL deploy failed"
    return 1
  fi
}

# Sync + restart (best-effort — skip on failure)
try_deploy() {
  local host="$1"
  local service="$2"
  if rsync_push "${host}" && restart_and_status "${host}" "${service}"; then
    DEPLOY_OK+=("${host}")
    return 0
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${host}")
    return 1
  fi
}

# Frontend sync + build + restart (critical).
#
# The build MUST run before the restart, not inside the unit. `systemctl restart`
# stops `serve` first, so a build in ExecStartPre happens with the site already
# down — 4+ minutes of it on every deploy (BUG-0103). scripts/ensure_dist.sh
# builds into frontend/dist.new while the OLD bundle keeps being served, swaps it
# in at the end, and stamps it; the restart that follows finds the stamp current
# and comes back in about a second.
#
# A failed build is not a failed site: dist/ still holds the previous bundle, so
# we skip the restart, keep serving it, and report the host as failed.
build_frontend_bundle() {
  local host="$1"
  echo -e "\n==> [${host}] Building frontend bundle (previous bundle stays served)"
  # -H: npm's cache must land in ${SYNC_USER}'s home, not the deploying user's.
  if ! run_ssh "${host}" "sudo -n -H -u ${SYNC_USER} bash ${TARGET_DIR}/frontend/scripts/ensure_dist.sh"; then
    echo "==> [${host}] frontend build FAILED — not restarting (live bundle left untouched)"
    return 1
  fi
}

# The frontend's systemd unit is hand-installed at /etc/systemd/system and is NOT
# what the rsync ships: core units are deliberately never reconciled (the host
# VMs' reconcile_feature_units.sh says so in as many words). That is a silent
# trap — the BUG-0103 ExecStartPre change rode along in the tree through a whole
# deploy while the old unit kept running, and the deploy reported success. Warn
# when the two drift rather than letting it pass unnoticed.
check_frontend_unit_drift() {
  local host="$1"
  local repo_unit="${TARGET_DIR}/frontend/config/services/linux/frontend_prod.service"
  local live_unit="/etc/systemd/system/${FRONTEND_SERVICE}"
  if run_ssh "${host}" "sudo -n diff -q '${repo_unit}' '${live_unit}' >/dev/null 2>&1"; then
    return 0
  fi
  echo "==> [${host}] ⚠️  ${FRONTEND_SERVICE} on disk differs from the unit this tree ships"
  echo "==> [${host}]     live: ${live_unit}"
  echo "==> [${host}]     tree: ${repo_unit}"
  echo "==> [${host}]     Core units are hand-installed on purpose, so this deploy did NOT touch it."
  echo "==> [${host}]     To adopt the tree's version:"
  echo "==> [${host}]       sudo cp ${repo_unit} ${live_unit} && sudo systemctl daemon-reload"
  UNIT_DRIFT_WARNINGS="${UNIT_DRIFT_WARNINGS} ${host}"
}

frontend_deploy() {
  local host="$1"
  if rsync_push "${host}" && check_frontend_unit_drift "${host}" \
     && build_frontend_bundle "${host}" \
     && restart_and_status "${host}" "${FRONTEND_SERVICE}"; then
    DEPLOY_OK+=("${host}")
  else
    DEPLOY_FAIL+=("${host}")
    echo "==> [${host}] CRITICAL deploy failed"
    return 1
  fi
}

# Windows sync + restart (best-effort)
try_deploy_windows() {
  local host="$1"
  if rsync_push_windows "${host}" && restart_windows_task "${host}"; then
    DEPLOY_OK+=("${host}")
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${host}")
  fi
}

usage() {
  cat <<'EOF'
Usage:
  bash update_core.sh [branch] [--frontend] [--server] [--host] [--host-windows]

Examples:
  bash update_core.sh
  bash update_core.sh debug
  bash update_core.sh --frontend
  bash update_core.sh debug --frontend
  bash update_core.sh --server --host
  bash update_core.sh --host-windows
  bash update_core.sh --restart                 # restart-only: all aux services on hosts (no deploy)
  bash update_core.sh --restart vpt-stream      # restart-only: just vpt-stream on hosts
  bash update_core.sh debug --host --restart    # deploy hosts, then restart aux services

Behavior:
  - If no target flags are provided (and no --restart), deploys server + frontend + host + host-windows VMs.
  - [branch] is optional and can appear before or after flags.
  - --restart [service] is opt-in (aux services are NOT restarted otherwise).
      * On its own  -> restart-only: skips git pull + rsync, just restarts aux services on host VMs.
      * With a deploy target (e.g. --host) -> deploy first, then restart aux services on the hosts.
      * With a service name -> only that one aux service is restarted (still only if already active).
  - Aux services: vpt-stream vpt-monitor vpt-subtitle vpt-transcript vpt-archiver vpt-avq vpt-kpi

Flow:
  1. Git pull on proxmox (directly from GitHub) — skipped when REPO_DIR is an
     extracted offline bundle (BUNDLE_MANIFEST.txt present, no .git; see
     DEPLOY_CUSTOMER.md "Deploying without GitHub access")
  2. Print VERSION.txt (source-controlled / written by the bundle builder)
  3. Rsync push to each target VM + restart services; on hosts also
     setup/proxmox/node/reconcile_feature_units.sh (feature systemd units)

REPO_DIR=<dir> overrides the source tree (default ~/virtualpytest).
EOF
}

# ---- Parse args ----
DEPLOY_BRANCH=""
DEPLOY_SERVER=false
DEPLOY_FRONTEND=false
DEPLOY_HOSTS=false
DEPLOY_HOSTS_WINDOWS=false
DEPLOY_RESTART=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)        DEPLOY_SERVER=true ;;
    --frontend)      DEPLOY_FRONTEND=true ;;
    --host)          DEPLOY_HOSTS=true ;;
    --host-windows)  DEPLOY_HOSTS_WINDOWS=true ;;
    --restart)
      # Opt-in aux-service restart. Optional next arg names a single service
      # (e.g. `--restart vpt-stream`); otherwise all AUX_SERVICES are restarted.
      DEPLOY_RESTART=true
      if [[ $# -gt 1 && "$2" != --* ]]; then
        RESTART_SERVICE="$2"
        shift
      fi
      ;;
    --help|-h)       usage; exit 0 ;;
    --*)             echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *)
      if [[ -n "${DEPLOY_BRANCH}" ]]; then
        echo "Only one branch argument is supported. Got extra value: $1" >&2
        usage; exit 1
      fi
      DEPLOY_BRANCH="$1"
      ;;
  esac
  shift
done

# `--restart` on its own (no deploy targets) = restart-only mode: skip git pull
# and rsync entirely, just restart aux services on the host VMs.
RESTART_ONLY=false
if ${DEPLOY_RESTART} && ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS}; then
  RESTART_ONLY=true
fi

# Default (no target flags AND no --restart): deploy everything (no aux restart).
if ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS} && ! ${DEPLOY_RESTART}; then
  DEPLOY_SERVER=true
  DEPLOY_FRONTEND=true
  DEPLOY_HOSTS=true
  DEPLOY_HOSTS_WINDOWS=true
fi

echo "Starting VirtualPyTest deployment..."
echo "Targets: server=${DEPLOY_SERVER} frontend=${DEPLOY_FRONTEND} hosts=${DEPLOY_HOSTS} hosts-windows=${DEPLOY_HOSTS_WINDOWS} restart=${DEPLOY_RESTART}"
echo "Branch: ${DEPLOY_BRANCH:-<current branch>}"

# ---- Restart-only mode: no git pull / no rsync, just restart aux services ----
if ${RESTART_ONLY}; then
  echo -e "\n=== Restart-only mode: ${RESTART_SERVICE:-all aux services} ==="
  echo -e "\n--- Host VMs ---"
  IFS=',' read -ra hosts <<< "${HOST_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    restart_aux_services "${host}"
  done

  echo -e "\n--- Runner VMs ---"
  IFS=',' read -ra hosts <<< "${RUNNER_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    restart_aux_services "${host}"
  done

  echo -e "\n========== RESTART SUMMARY =========="
  if [[ ${#AUX_RESTART_FAIL[@]} -gt 0 ]]; then
    echo -e "\n======= SERVICE RESTART FAILED ======="
    for host in "${!AUX_RESTART_FAIL[@]}"; do
      echo "  ${host} : ${AUX_RESTART_FAIL[$host]}"
    done
    exit 1
  fi
  echo "all requested aux services restarted (or were not active)"
  exit 0
fi

# ---- Step 1: Git pull on proxmox (or: offline bundle, nothing to pull) ----
echo -e "\n=== Step 1: Git pull ==="
cd "${REPO_DIR}"
if ${BUNDLE_MODE}; then
  echo "offline bundle (no git): ${REPO_DIR}"
  sed 's/^/  /' "${REPO_DIR}/BUNDLE_MANIFEST.txt"
  [[ -z "${DEPLOY_BRANCH}" ]] || echo "WARNING: branch argument '${DEPLOY_BRANCH}' ignored (bundle is fixed at its platform_ref)"
elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git fetch --all
  if [[ -n "${DEPLOY_BRANCH}" ]]; then
    git checkout "${DEPLOY_BRANCH}"
  fi
  git reset --hard "origin/$(git rev-parse --abbrev-ref HEAD)"
else
  echo "ERROR: ${REPO_DIR} is neither a git checkout nor an extracted bundle (no BUNDLE_MANIFEST.txt)" >&2
  exit 1
fi

# VERSION.txt is source-controlled and bumped before commit by the local hook.
# Deploy should sync the tracked file from git without rewriting it into a
# different format.
if [[ -f "${REPO_DIR}/VERSION.txt" ]]; then
  echo "VERSION.txt: $(head -n 1 "${REPO_DIR}/VERSION.txt" | tr -d '\r')"
else
  echo "WARNING: VERSION.txt is missing after git reset"
fi

# ---- Step 2: Deploy to target VMs ----
echo -e "\n=== Step 2: Deploy to target VMs ==="
push_filters
if ${BUNDLE_MODE}; then
  echo "bundle mode: frontend config re-included from the bundle: $(printf '%s\n' "${PUSH_FILTERS[@]}" | grep '^--include' | tr '\n' ' ')"
fi

# Trim leading/trailing whitespace from a host entry parsed out of a
# comma-separated HOST_IPS-style list. A single literal space in the
# config — e.g. HOST_IPS="host2, host3" — becomes " host3" after
# `IFS=',' read -ra`, which rsync and ssh reject with
# "hostname contains invalid characters". Strip all whitespace
# (including tabs and CRs) defensively so config typos never break the
# deploy.
trim_host() {
  local h="$1"
  h="${h#"${h%%[![:space:]]*}"}"
  h="${h%"${h##*[![:space:]]}"}"
  printf '%s' "$h"
}

if ${DEPLOY_SERVER}; then
  echo -e "\n--- Server ---"
  IFS=',' read -ra hosts <<< "${SERVER_IP}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    critical_deploy "${host}" "${SERVER_SERVICE}"
  done
fi

if ${DEPLOY_FRONTEND}; then
  echo -e "\n--- Frontend ---"
  IFS=',' read -ra hosts <<< "${FRONTEND_IP}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    frontend_deploy "${host}"
  done
fi

if ${DEPLOY_HOSTS}; then
  echo -e "\n--- Host VMs ---"
  IFS=',' read -ra hosts <<< "${HOST_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    if try_deploy "${host}" "${HOST_SERVICE}"; then
      reconcile_feature_units_remote "${host}"
      if ${DEPLOY_RESTART}; then
        restart_aux_services "${host}"
      fi
    fi
  done

  echo -e "\n--- Runner VMs ---"
  IFS=',' read -ra hosts <<< "${RUNNER_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    if try_deploy "${host}" "${HOST_SERVICE}"; then
      reconcile_feature_units_remote "${host}"
      if ${DEPLOY_RESTART}; then
        restart_aux_services "${host}"
      fi
    fi
  done
fi

if ${DEPLOY_HOSTS_WINDOWS}; then
  if [[ -n "${HOST_WINDOWS_IPS}" ]]; then
    echo -e "\n--- Windows Host VMs ---"
    IFS=',' read -ra hosts <<< "${HOST_WINDOWS_IPS}"
    for host in "${hosts[@]}"; do
      host="$(trim_host "${host}")"
      [[ -z "${host}" ]] && continue
      try_deploy_windows "${host}"
    done
  else
    echo -e "\n--- Windows Host VMs --- (none configured, skipping)"
  fi
fi

# ---- Summary ----
echo -e "\n========== DEPLOY SUMMARY =========="
if [[ ${#DEPLOY_OK[@]} -gt 0 ]]; then
  echo -e "  OK (${#DEPLOY_OK[@]}):     ${DEPLOY_OK[*]}"
fi
if [[ ${#DEPLOY_FAIL[@]} -gt 0 ]]; then
  echo -e "  FAILED (${#DEPLOY_FAIL[@]}): ${DEPLOY_FAIL[*]}"
fi
if [[ -n "${UNIT_DRIFT_WARNINGS// /}" ]]; then
  echo -e "  ⚠️  SYSTEMD UNIT DRIFT (live unit is not the one this tree ships):${UNIT_DRIFT_WARNINGS}"
fi
if [[ -n "${OWNERSHIP_WARNINGS// /}" ]]; then
  echo -e "  ⚠️  OWNERSHIP NOT FIXED:${OWNERSHIP_WARNINGS}"
  echo -e "      ${SYNC_USER} cannot write ${TARGET_DIR}/test_scripts on these hosts, so"
  echo -e "      virtual scripts fail to materialize — and fail SILENTLY (BUG-0089)."
  echo -e "      Run: chmod 777 ${TARGET_DIR}/test_scripts"
fi
echo "===================================="

# ---- Service restart summary (non-blocking; aux services only) ----
if [[ ${#AUX_RESTART_FAIL[@]} -gt 0 ]]; then
  echo -e "\n======= SERVICE RESTART FAILED ======="
  for host in "${!AUX_RESTART_FAIL[@]}"; do
    echo "  ${host} : ${AUX_RESTART_FAIL[$host]}"
  done
  echo "======================================"
fi

if [[ ${#FEATURE_UNIT_FAIL[@]} -gt 0 ]]; then
  echo -e "\n======= FEATURE UNIT PROBLEMS (deploy not failed) ======="
  echo "  see the reconcile output above for: ${FEATURE_UNIT_FAIL[*]}"
  echo "=========================================================="
fi

if [[ ${#DEPLOY_FAIL[@]} -gt 0 ]]; then
  echo -e "\nDone (with failures)."
else
  echo -e "\nDone."
fi
