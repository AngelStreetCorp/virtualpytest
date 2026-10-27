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
#
# Every target is read from the environment with the value below as its default, so one
# deploy can be pointed somewhere else without editing the script:
#   SERVER_IP=<ip> bash ~/update_core.sh main --server
# The installer (install_update_core.py) keeps the node's own targets as these defaults,
# so the environment still wins on the node.
SERVER_IP="${SERVER_IP:-192.168.0.103}"
FRONTEND_IP="${FRONTEND_IP:-192.168.0.105}"
HOST_IPS="${HOST_IPS:-192.168.0.109,192.168.0.110}"
# Retired hosts — NOT deploy targets any more, and not to be re-added without the
# owner's yes (TASK-170, 2026-10-23):
#   labox-web, labox-dongle — their VMs were stopped by Proxmox on 2026-10-16.
#   vpt-pi3 — the Pi-site host; the owner retired it on 2026-10-23.
# All three were dropped from the node1 host list and from ~/.vpt-down-hosts on that
# day, so neither this script's defaults nor the node's live copy names them any more.
# Why each one went away, and what was cleaned up with it (the device roster rows, the
# gateway forwards), is written up in docs/tasks/TASK-170-hosts-not-registered.md.
RUNNER_IPS="${RUNNER_IPS:-}"
HOST_WINDOWS_IPS="${HOST_WINDOWS_IPS:-}"  # e.g. "192.168.0.150,192.168.0.151"
# Docker-compose stacks built from source (VPT_IMAGE_TAG=local), e.g. "vpt-gcloud". Any deploy
# (server, frontend or host) pushes the tree there and rebuilds the matching containers in the
# background on that machine — see docker_deploy. SSH alias user = the account that owns the
# stack (in the docker group); DOCKER_DIR is that account's checkout.
DOCKER_IPS="${DOCKER_IPS:-}"
DOCKER_DIR="${DOCKER_DIR:-/home/virtualpytest/virtualpytest}"

# ---- Internal config (rarely need to change) ----
SSH_USER="${SSH_USER:-$(id -un)}"   # the invoking account; override with SSH_USER=
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_ed25519}"
# ConnectTimeout bounds the SYN phase: an unreachable host (powered off, or a
# firewall that DROPs) otherwise burns the kernel's full SYN-retry budget (~130s)
# on every single ssh call to it. ServerAlive* bounds the other half -- a peer
# that answers the handshake and then goes silent mid-transfer (wedged Pi, dead
# Wi-Fi, SD-card I/O lockup) leaves ssh blocked on read forever without it, which
# is what hung the "[proxmox -> vpt-pi3] rsync push" step instead of failing it.
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
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
  vpt-monitor-img
  vpt-monitor-subtitle
  vpt-monitor-audio
  vpt-archiver
  vpt-avq
  vpt-kpi
)

# Long-running services on the SERVER VM that run server code next to vpt-server.
# A --server deploy updates their code on disk too, so they are restarted after
# vpt-server — same rule as AUX_SERVICES: only if already active (a worker that was
# switched off stays off). Without this they kept running the code they were started
# with: vpt-heatmap on vpt-pi1 ran a 3-week-old processor that never wrote its status
# file, so the status page and Grafana showed its heatmap as failing.
SERVER_AUX_SERVICES=(
  vpt-heatmap
  vpt-discard-incidents
  vpt-discard-scripts
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

# The remote output of a VALUE read, and nothing else.
#
# run_ssh prints its own banner line, so a value read through it is the banner whenever the remote
# command printed nothing: a MISSING marker read as "==> [host] cat ~/.vpt_server_code_id ..." and
# not as empty, so "no marker" was indistinguishable from "some marker" (2026-10-24). The banner
# belongs in the log, not in a value.
read_remote() {   # <host> <remote-command>: the last line of the remote stdout, whitespace stripped
  local host="$1"; shift
  local ssh_target out
  ssh_target="$(build_ssh_target "${host}")"
  out="$(ssh ${SSH_OPTS} "${ssh_target}" "$@" || true)"
  printf '%s' "$(printf '%s' "${out}" | tail -n1 | tr -d '[:space:]')"
}

# Machine-readable progress, one line per host phase boundary, alongside the human log (which is
# unchanged). Parsed by setup/proxmox/node/lib/deploy_progress.py; format and states in
# DEPLOY_CUSTOMER.md ("Deploy progress events"). Never fails the deploy.
#   progress <host> <rsync|install|restart|health> <start|ok|failed|skipped> [detail]
# role = server|frontend|host (DEPLOY_PHASE) or docker|windows (PROGRESS_ROLE): the same machine
# can be a server and a host, so (role, host) is the card.
PROGRESS_ROLE=""
progress_json_escape() {
  local v="$1"
  v="${v//\\/\\\\}"; v="${v//\"/\\\"}"; v="${v//$'\n'/ }"; v="${v//$'\r'/ }"; v="${v//$'\t'/ }"
  printf '%s' "${v}"
}
progress() {
  printf 'VPT_PROGRESS {"host":"%s","role":"%s","phase":"%s","state":"%s","ts":"%s","detail":"%s"}\n' \
    "$(progress_json_escape "$1")" "${PROGRESS_ROLE:-${DEPLOY_PHASE:-host}}" "$2" "$3" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(progress_json_escape "${4:-}")" || true
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
  # Capture the running PID BEFORE the restart so we can verify a new process
  # actually came up. systemd's Restart=always + Type=simple can race: the old
  # master exits, a long-lived worker keeps the port bound, systemd spawns a
  # fresh master with a different PID — but the visible "service state" is
  # still active/running the whole time. If the only thing that "restarted" was
  # the master while the worker (running the OLD code) kept serving, callers
  # see a green deploy and a process serving yesterday's code. Without a PID
  # check, update_core.sh would silently miss that.
  local pid_before
  pid_before="$(run_ssh "${host}" "sudo -n systemctl show \"${service}\" --property=MainPID --value --no-pager" 2>/dev/null | tr -d '[:space:]')"
  progress "${host}" restart start "${service}"
  local _restart_state=ok _health_state=ok
  run_ssh "${host}" "sudo -n systemctl restart \"${service}\"" || _restart_state=failed
  progress "${host}" restart "${_restart_state}" "${service}"
  progress "${host}" health start "${service}"
  wait_for_service_running "${host}" "${service}" || _health_state=failed
  local pid_after
  pid_after="$(run_ssh "${host}" "sudo -n systemctl show \"${service}\" --property=MainPID --value --no-pager" 2>/dev/null | tr -d '[:space:]')"
  if [[ -n "${pid_before}" && -n "${pid_after}" && "${pid_before}" == "${pid_after}" && "${pid_before}" != "0" ]]; then
    echo "==> [${host}] ${service} restart reported success but MainPID did not change (was=${pid_before}, still=${pid_after})"
    progress "${host}" health failed "${service}: MainPID did not change (${pid_before})"
    run_ssh "${host}" "sudo -n systemctl status --no-pager \"${service}\""
    return 2
  fi
  progress "${host}" health "${_health_state}" "${service}"
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
# Services after the host name replace AUX_SERVICES (the server passes
# SERVER_AUX_SERVICES); otherwise, if RESTART_SERVICE is set, only that one service
# is considered.
restart_aux_services() {
  local host="$1"
  shift
  local services=("${AUX_SERVICES[@]}")
  if [[ $# -gt 0 ]]; then
    services=("$@")
  elif [[ -n "${RESTART_SERVICE}" ]]; then
    services=("${RESTART_SERVICE}")
  fi
  echo -e "\n==> [${host}] Restarting aux services (only those already active): ${services[*]}"
  local failed=()
  local svc
  for svc in "${services[@]}"; do
    # A unit this host is configured to run must end the deploy RUNNING, not merely
    # enabled. Gating on `is-active` alone was a one-way ratchet: a unit that any
    # earlier deploy stopped, or that crashed, reported inactive forever, so every
    # later deploy skipped it and could never bring it back (the archiver stayed
    # stopped for 1.5 days on labox-backend, its capture archive grew until / was
    # 100% full, and every capture write failed with ENOSPC). Gate on the unit's
    # CONFIGURED state (`is-enabled`) so a wanted-but-down unit is started; only a
    # genuinely disabled/not-installed unit is skipped, which is what the original
    # "don't start what wasn't meant to run here" intent actually protected.
    if run_ssh "${host}" "sudo -n systemctl is-enabled --quiet \"${svc}\""; then
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
        # enabled but down: a crash or an earlier deploy's stop. Bring it up.
        echo "==> [${host}] ${svc} enabled but inactive -> starting"
        if run_ssh "${host}" "sudo -n systemctl start \"${svc}\"" \
           && wait_for_service_running "${host}" "${svc}" 30; then
          :
        else
          echo "==> [${host}] ${svc} FAILED to start"
          failed+=("${svc}")
        fi
      fi
    else
      echo "==> [${host}] ${svc} not enabled -> skipping"
    fi
  done
  if [[ ${#failed[@]} -gt 0 ]]; then
    local joined
    joined="$(printf '%s, ' "${failed[@]}")"
    AUX_RESTART_FAIL["${host}"]="${joined%, }"
  fi
  return 0
}

# ---- a long-running service that is still running the previous code ------------------
#
# The aux services are restarted only when the deploy says --restart. An ordinary deploy
# (the default: "deploy everything (no aux restart)") pushes the new code to the disk and
# restarts vpt-host, and the aux services keep the code they were started with.
#
# That gap is invisible from the deploy's own bookkeeping: the marker tracks the host
# service's code, so "the files on disk are new" and "the code that runs is new" look
# the same. It is not the same, and the difference matters -- vpt-monitor-img runs the
# Localize monitor and the freeze incident manager, i.e. everything that registers a
# screen, so a monitor left on the previous code registers screens the way the old code
# did (measured 2026-10-23: 293 screen rows were born with no fingerprint because the
# freeze path ran code that was 5.5 hours old, and the screen-label coverage metric went
# from 5 to 17 overnight with nothing but the morning log line to show it).
#
# So: when the host code changed, say out loud which services are still on the old code.
# This NEVER restarts anything -- restarting the capture monitor drops frames for every
# device on the host, which is why the aux restart stays opt-in. It only makes the gap
# visible, so the operator can restart the service under the lease when it is free.
STALE_AUX_SERVICES=()
report_stale_aux_services() {
  local host="$1" pushed_at="${HOST_CODE_PUSHED_AT:-0}" svc st
  [[ "${pushed_at}" == "0" ]] && return 0
  local services=("${AUX_SERVICES[@]}")
  [[ -n "${RESTART_SERVICE}" ]] && services=("${RESTART_SERVICE}")
  # One ssh round trip for the whole list: "<service> <start-epoch>" per running service.
  #
  # run_ssh prints a blank line and then its own banner ("==> [host] <cmd>") before the ssh
  # output, so the payload does not start at the first line. Counting the preamble lines is
  # fragile (an off-by-one reports the banner as a service -- measured 2026-10-24, the banner
  # line was read as a service named "==>" with the digit "1" scraped out of it as its epoch,
  # so every deploy would report a phantom service as stale). Instead a line is used only when it
  # IS what the remote command prints -- "<service> <epoch>", the second field all digits -- and
  # the service is one of the ones we asked about. A banner, a blank line or any other decoration
  # is dropped, whatever run_ssh prints, and no real line is lost.
  #
  # The whole line is matched, not the fields read apart: a line whose second field is not a
  # plain number is dropped instead of having its digits scraped out of it (scraping would turn
  # "17 21 86" into the epoch 172186 and compare it as ancient).
  local out
  out="$(run_ssh "${host}" "for s in ${services[*]}; do ts=\$(systemctl show -p ExecMainStartTimestamp --value \"\$s\" 2>/dev/null | tail -n1); [ -n \"\$ts\" ] && [ \"\$ts\" != n/a ] && echo \"\$s \$(date -d \"\$ts\" +%s 2>/dev/null)\"; done" 2>/dev/null)"
  local line
  while IFS= read -r line; do
    line="${line%$'\r'}"
    [[ "${line}" =~ ^([[:alnum:]_.-]+)[[:space:]]+([0-9]+)$ ]] || continue
    svc="${BASH_REMATCH[1]}"
    st="${BASH_REMATCH[2]}"
    case " ${services[*]} " in
      *" ${svc} "*) ;;
      *) continue ;;    # not one of the services we asked about: never report it
    esac
    if [[ "${st}" -lt "${pushed_at}" ]]; then
      echo "==> [${host}] ${svc} is STILL RUNNING THE PREVIOUS CODE (started $(date -u -d "@${st}" '+%Y-%m-%d %H:%M UTC'); this deploy pushed the new code at $(date -u -d "@${pushed_at}" '+%Y-%m-%d %H:%M UTC'))"
      echo "    it keeps the code it was started with until it is restarted; restart it under the lease when it is free"
      progress "${host}" stale-code "skipped" "${svc}: running the code from before this deploy"
      STALE_AUX_SERVICES+=("${host}:${svc}")
    fi
  done <<< "${out}"
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
  progress "${host}" install start "feature units"
  if ! run_ssh "${host}" "sudo -n test -f ${script}"; then
    echo "==> [${host}] ${script} not on the target (older tree) -> feature units not reconciled"
    progress "${host}" install skipped "older tree: feature units not reconciled"
    return 0
  fi
  if ! run_ssh "${host}" "sudo -n bash ${script} --project-root ${TARGET_DIR}"; then
    echo "==> [${host}] feature unit reconcile reported problems (deploy not failed)"
    FEATURE_UNIT_FAIL+=("${host}")
    progress "${host}" install failed "feature unit reconcile reported problems (deploy not failed)"
    return 0
  fi
  progress "${host}" install ok "feature units"
  return 0
}

# TASK-90: vpt-monitor, vpt-transcript and vpt-subtitle became vpt-monitor-img, -audio and -subtitle.
# The deployed tree ships setup/proxmox/node/migrate_monitor_units.sh (idempotent, runs on
# the host): it moves each old unit (enabled/active state and .service.d drop-ins included)
# to the new name. Runs right after the feature-unit reconcile, before the aux restart.
# Guarded for older trees; best-effort like the reconcile.
migrate_monitor_units_remote() {
  local host="$1"
  local script="${TARGET_DIR}/setup/proxmox/node/migrate_monitor_units.sh"
  if ! run_ssh "${host}" "sudo -n test -f ${script}"; then
    return 0
  fi
  if ! run_ssh "${host}" "sudo -n bash ${script} --project-root ${TARGET_DIR}"; then
    echo "==> [${host}] monitor unit migration reported problems (deploy not failed)"
  fi
  return 0
}

# TASK-90 follow-up: the deployed tree ships setup/proxmox/node/ensure_host_prereqs.sh (idempotent, runs on the host): vpt_user's
# `systemctl start|stop|restart vpt-*` sudoers rule (the Settings profile picker restarts units through it; checked with visudo -cf,
# own drop-in, existing files untouched) and the vpt-timeline unit (installed, not enabled). VPT_SKIP_SUDOERS=1 skips the sudoers part.
ensure_host_prereqs_remote() {
  local host="$1"
  local script="${TARGET_DIR}/setup/proxmox/node/ensure_host_prereqs.sh"
  if ! run_ssh "${host}" "sudo -n test -f ${script}"; then
    return 0
  fi
  if ! run_ssh "${host}" "sudo -n env VPT_SKIP_SUDOERS=${VPT_SKIP_SUDOERS:-0} bash ${script} --project-root ${TARGET_DIR}"; then
    echo "==> [${host}] host prerequisites reported problems (deploy not failed)"
  fi
  return 0
}

# Push code directly to /opt/virtualpytest on a Linux target VM
rsync_push() {
  local target_host="$1"
  local ssh_target
  ssh_target="$(build_ssh_target "${target_host}")"
  echo -e "\n==> [proxmox -> ${target_host}] rsync push"
  progress "${target_host}" rsync start
  # --chown: land the tree owned by ${SYNC_USER} instead of breaking it and
  # repairing it afterwards. `-a` implies -o/-g, and the remote rsync runs as
  # root (--rsync-path="sudo rsync"), so without this every push stamps the
  # whole target tree with the SOURCE's numeric uid/gid — the deploying user's
  # — and -p re-applies the source's mode. That is what un-owned test_scripts/
  # after each deploy, and what wiped the `chmod 777` workaround (BUG-0089).
  # --chown resolves the name on the receiver, so it is correct even though
  # vpt_user's uid differs per host (995 on a Pi, 999 on the VMs).
  # --timeout: rsync's own stall guard, for a transport that stays up while the
  # remote rsync stops making progress; ServerAlive* cannot see that case.
  if ! rsync -az -q --delete --timeout=90 "${PUSH_FILTERS[@]}" \
    --chown="${SYNC_USER}:${SYNC_USER}" \
    --rsync-path="sudo rsync" \
    -e "ssh ${SSH_OPTS}" \
    "${REPO_DIR}/" \
    "${ssh_target}:${TARGET_DIR}/"; then
    echo "==> [${target_host}] rsync FAILED"
    progress "${target_host}" rsync failed "rsync push failed"
    return 1
  fi
  progress "${target_host}" rsync ok
  # When the code landed. A service that was started before this moment is running the
  # previous code, whatever the deploy says about the files on disk.
  HOST_CODE_PUSHED_AT="$(date +%s)"
  # Secondary net for files rsync does not manage (runtime output a wrongly-owned
  # process created). --chown above already lands the pushed tree correct; this
  # step can no longer be the only thing standing between a deploy and a broken
  # test_scripts/, which is where a virtual script materializes its .vs_<uuid>.py
  # — and where a failure is invisible, because the host's completion callback
  # then carries neither a result nor an error and the server reads that as a
  # pass (BUG-0089).
  #
  # It is also the step a whitelist-sudo host cannot run at all: labox-web granted
  # NOPASSWD for rsync/git/bash/systemctl only (that host was retired on 2026-10-23,
  # but the constraint it showed is what any whitelist-sudo host hits), so `sudo -n find`
  # is refused there while the push itself succeeds. Hence the push, not the repair, must
  # be what gets ownership right.
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
  progress "${target_host}" rsync start
  local _rc=0
  rsync -rlz -q --delete --timeout=90 --blocking-io --no-perms --chmod=ugo=rwX --no-owner --no-group --omit-dir-times \
    "${PUSH_FILTERS[@]}" \
    -e "ssh ${SSH_OPTS}" \
    "${REPO_DIR}/" \
    "${ssh_target}:${TARGET_DIR_WINDOWS}/" || _rc=$?
  if (( _rc == 0 )); then progress "${target_host}" rsync ok; else progress "${target_host}" rsync failed "rsync exit ${_rc}"; fi
  return "${_rc}"
}

# Restart Windows scheduled task
restart_windows_task() {
  local host="$1"
  echo -e "\n==> [${host}] Restarting Windows scheduled task '${WINDOWS_TASK}'"
  progress "${host}" install skipped "windows: nothing to install"
  progress "${host}" restart start "${WINDOWS_TASK}"
  local _task_state=ok
  run_ssh "${host}" "powershell.exe -Command \"Stop-ScheduledTask -TaskName '${WINDOWS_TASK}' -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName '${WINDOWS_TASK}'\"" || _task_state=failed
  progress "${host}" restart "${_task_state}" "${WINDOWS_TASK}"
  progress "${host}" health skipped "windows: scheduled task state is printed in the log"
  sleep 5
  run_ssh "${host}" "powershell.exe -Command \"Get-ScheduledTask -TaskName '${WINDOWS_TASK}' | Select-Object TaskName, State | Format-Table -AutoSize\""
}

# ---- Deploy result tracking ----
DEPLOY_OK=()
DEPLOY_FAIL=()
DEPLOY_OK_ROLE=()    # "<server|frontend|host>:<name>" per attempted target, for the per-target ledger
DEPLOY_FAIL_ROLE=()
DEPLOY_PHASE=host
# Hosts whose chown to vpt_user failed (no passwordless sudo) — see BUG-0089.
OWNERSHIP_WARNINGS=""
# Hosts whose live systemd unit differs from the one this tree ships — see
# check_frontend_unit_drift.
UNIT_DRIFT_WARNINGS=""

# Sync + restart (critical — fails immediately)

# Host code identity (TASK-129 phase 1): a hash of the git trees the vpt-host process runs from. A deploy that only
# touched the frontend, docs or tests leaves it unchanged, and restarting vpt-host then only kills the runs on it
# (a full deploy every ~20 min restarted host-clone-1 under long runs). Empty = unknown (bundle without .git, dirty
# tree, VPT_FORCE_HOST_RESTART=1): always restart. The marker on the host is written only after a healthy restart.
# The dirty-tree guard looks at TRACKED files only (`--untracked-files=no`): the hash is `ls-tree HEAD`, so an
# untracked file does not change what it describes and must not empty the id. It did: one untracked file in
# backend_server/ emptied the server code id on every deploy, and the secondary-server catch-up skips an empty id,
# so that catch-up never fired at all (2026-10-24). A tracked file edited locally still empties the id: the tree on
# disk is then not the tree the hash describes.
# Not in the list: scripts/ and setup/ (tools and unit files the process never imports) and the game libraries under
# shared/src/lib/game*, which run in script subprocesses and are read from disk at each run (owner priority 2026-10-18:
# a game or script fix must not wait for, or cause, a vpt-host restart).
HOST_CODE_PATHS=(backend_host shared features requirements.txt)
HOST_CODE_IGNORE=$'\tshared/src/lib/game(2048)?/'
HOST_CODE_ID=""
compute_host_code_id() {
  [[ "${VPT_FORCE_HOST_RESTART:-0}" == 1 ]] && return 0
  git -C "${REPO_DIR}" rev-parse --git-dir >/dev/null 2>&1 || return 0
  [[ -z "$(git -C "${REPO_DIR}" status --porcelain --untracked-files=no -- "${HOST_CODE_PATHS[@]}" 2>/dev/null | grep -Ev ' shared/src/lib/game(2048)?/' || true)" ]] || return 0
  HOST_CODE_ID="$(git -C "${REPO_DIR}" ls-tree -r HEAD -- "${HOST_CODE_PATHS[@]}" 2>/dev/null | grep -Ev "${HOST_CODE_IGNORE}" | sha1sum | cut -d' ' -f1)"
}
SERVER_CODE_PATHS=(backend_server shared features scripts setup requirements.txt)
SERVER_CODE_ID=""
SERVER_CODE_MARKER='.vpt_server_code_id'
compute_server_code_id() {
  [[ "${VPT_FORCE_HOST_RESTART:-0}" == 1 ]] && return 0
  git -C "${REPO_DIR}" rev-parse --git-dir >/dev/null 2>&1 || return 0
  [[ -z "$(git -C "${REPO_DIR}" status --porcelain --untracked-files=no -- "${SERVER_CODE_PATHS[@]}" 2>/dev/null)" ]] || return 0
  SERVER_CODE_ID="$(git -C "${REPO_DIR}" ls-tree HEAD -- "${SERVER_CODE_PATHS[@]}" 2>/dev/null | sha1sum | cut -d' ' -f1)"
}
# A host deploy that reaches a Pi which also runs a secondary server: if that server was skipped earlier (its Pi was
# leased) its marker is stale, and now that the host lease is ours the server can be restarted. A missing marker counts
# as stale: the first host deploy after this ships restarts the secondary server once and writes the marker.
#
# An EMPTY code id never means "skip" here: we do not know what that server runs (no .git, a dirty tracked tree, a
# forced restart), so it is restarted. It used to return early on an empty id, and an empty id was what an untracked
# file in the server tree produced on every deploy, so this catch-up never fired once (2026-10-24) - and it failed
# quietly: the summary said "OK (1)" and nothing said the secondary server was never checked.
#
# Every outcome is printed, recorded in the deploy summary and pushed as a progress event: a silent no-op is what made
# that cost a day.
SECONDARY_CATCHUP=()
# The names a target can be called: itself, and the name its IP resolves to (~/.ssh/config).
# The lease code resolves an IP to a name, so a host addressed by IP and a secondary server
# addressed by name have to meet somewhere (2026-10-24).
target_identities() {   # <target>: its name, plus the name its IP resolves to
  local t="$1" n
  t="$(printf '%s' "${t}" | tr '[:upper:]' '[:lower:]')"
  printf '%s' "${t}"
  if [[ "${t}" =~ ^[0-9.]+$ ]]; then
    n="$(ip_host_name "${t}" | tr '[:upper:]' '[:lower:]')"
    if [[ -n "${n}" ]]; then printf ' %s' "${n}"; fi
  fi
  return 0
}
# Is <host> one of the secondary servers (the SERVER_IP entries after the node's own server)?
# Matched by name OR by the name an IP resolves to: the exact-name comparison never met a
# secondary server addressed by IP in SERVER_IP, so it was never caught up (2026-10-24).
# The list is the frozen one: the lease plan drops a LEASED secondary server from SERVER_IP, and
# that box is exactly the one the catch-up has to recognise.
is_secondary_server_host() {
  local host="$1" name a b list="${SECONDARY_SERVERS:-}"
  local -a hi=() si=()
  [[ -z "${list}" ]] && list="$(server_secondary_names)"
  read -ra hi <<< "$(target_identities "${host}")"
  for name in $(printf '%s' "${list}" | tr ',' ' '); do
    si=()
    read -ra si <<< "$(target_identities "${name}")"
    for a in ${hi[@]+"${hi[@]}"}; do
      for b in ${si[@]+"${si[@]}"}; do
        [[ "${a}" == "${b}" ]] && return 0
      done
    done
  done
  return 1
}
catch_up_secondary_server() {
  local host="$1" seen
  # matched by name OR by the name an IP resolves to (a secondary server addressed by IP in
  # SERVER_IP was never caught up: the exact-name comparison never met it)
  is_secondary_server_host "${host}" || return 0
  # what happens here is the SECONDARY SERVER's, not the host's: its events belong to the server's card
  local _prev_progress_role="${PROGRESS_ROLE:-}"; PROGRESS_ROLE=server
  seen="$(read_remote "${host}" "cat ~/${SERVER_CODE_MARKER} 2>/dev/null || true")"
  if [[ -z "${SERVER_CODE_ID}" ]]; then
    echo "==> [${host}] secondary server identity unknown (no code id): restarting ${SERVER_SERVICE} - we cannot tell what it runs"
    if restart_and_status "${host}" "${SERVER_SERVICE}"; then
      : # no marker is written: an empty id must never become "current" for the next deploy
      SECONDARY_CATCHUP+=("${host}: identity unknown, restarted")
    else
      SECONDARY_CATCHUP+=("${host}: identity unknown, RESTART FAILED")
    fi
  elif [[ "${seen}" == "${SERVER_CODE_ID}" ]]; then
    echo "==> [${host}] secondary server code is current (${SERVER_CODE_ID:0:10}): ${SERVER_SERVICE} NOT restarted (catch-up: nothing to do)"
    progress "${host}" install skipped "secondary server ${SERVER_SERVICE}: code is current, not restarted"
    SECONDARY_CATCHUP+=("${host}: code is current, not restarted")
  else
    echo "==> [${host}] secondary server code is stale (${seen:-no marker}): restarting ${SERVER_SERVICE} to catch up"
    if restart_and_status "${host}" "${SERVER_SERVICE}"; then
      run_ssh "${host}" "echo ${SERVER_CODE_ID} > ~/${SERVER_CODE_MARKER}" >/dev/null 2>&1 || true
      SECONDARY_CATCHUP+=("${host}: stale code, restarted")
    else
      SECONDARY_CATCHUP+=("${host}: stale code, RESTART FAILED")
    fi
  fi
  PROGRESS_ROLE="${_prev_progress_role}"
  return 0
}
HOST_CODE_MARKER='.vpt_host_code_id'   # in the ssh user's home on the host, outside the rsync'd tree
# The epoch second of the last code push to a host. A long-running service that was started
# BEFORE this push is running the code that was on the disk before it -- see
# report_stale_aux_services().
HOST_CODE_PUSHED_AT=0

# Hosts held by another agent in a --skip-leased run (TASK-129 phase 1 item C): their code is synced at once (script and
# game code is read from disk at each run) but vpt-host is not restarted under the holder. If a restart is due, the host
# goes into SKIPPED_HOSTS so the registry queues the catch-up deploy, which restarts it when the last lease is gone.
SYNC_LEASED=()
SYNC_LEASED_BY=()
DEFERRED_RESTARTS=()
sync_leased_index() {   # prints the SYNC_LEASED index of <host> (name or IP), returns 1 when it is not one
  local h="$1" n i=0 x
  n="${h}"; [[ "${h}" =~ ^[0-9.]+$ ]] && n="$(ip_host_name "${h}")"
  n="$(printf '%s' "${n}" | tr '[:upper:]' '[:lower:]')"
  [[ -z "${n}" ]] && return 1
  for x in ${SYNC_LEASED[@]+"${SYNC_LEASED[@]}"}; do
    if [[ "$(printf '%s' "${x}" | tr '[:upper:]' '[:lower:]')" == "${n}" ]]; then echo "${i}"; return 0; fi
    i=$((i+1))
  done
  return 1
}
is_sync_leased() { sync_leased_index "$1" >/dev/null; }
sync_leased_host() {
  local host="$1" idx by seen active need=false why=""
  idx="$(sync_leased_index "${host}")"; by="${SYNC_LEASED_BY[$idx]}"
  rsync_push "${host}" || return 1
  seen="$(read_remote "${host}" "cat ~/${HOST_CODE_MARKER} 2>/dev/null || true")"
  active="$(read_remote "${host}" "systemctl is-active ${HOST_SERVICE} 2>/dev/null || true")"
  if [[ -z "${HOST_CODE_ID}" || "${seen}" != "${HOST_CODE_ID}" || "${active}" != active ]]; then need=true; why="host code changed"; fi
  # A secondary server's OWN code can be stale while the host code is current: its marker says what
  # it runs, the host marker says nothing about it. Not gated on ${DEPLOY_SERVER}: the catch-up the
  # runner queues for a leased host is HOST-scoped, and that is exactly the path that has to notice
  # it -- without this the chain died there and the secondary server ran old code for ever
  # (E64, 2026-10-24). The restart itself waits for the lease: the catch-up does it.
  if is_secondary_server_host "${host}"; then
    local sseen
    sseen="$(read_remote "${host}" "cat ~/${SERVER_CODE_MARKER} 2>/dev/null || true")"
    # An empty id means "we do not know what it runs": restart, never skip (E62's rule).
    if [[ -z "${SERVER_CODE_ID}" || "${sseen}" != "${SERVER_CODE_ID}" ]]; then
      need=true; why="${why:+${why}; }server code changed"
      echo "==> [${host}] secondary server code is stale (${sseen:-no marker}): ${SERVER_SERVICE} restart deferred to the catch-up (leased by ${by})"
      SECONDARY_CATCHUP+=("${host}: server code stale, restart deferred to the catch-up")
    fi
  fi
  # a secondary server skipped earlier in this run also needs its catch-up
  if ${DEPLOY_SERVER} && is_secondary_server_host "${host}"; then need=true; why="${why:-server code}"; fi
  if ${need}; then
    echo "==> [${host}] code synced; ${HOST_SERVICE} restart DEFERRED (${why}): leased by ${by}, the catch-up deploy restarts it when the lease is released"
    progress "${host}" restart skipped "deferred: leased by ${by}"
    progress "${host}" health skipped "restart deferred"
    SKIPPED_HOSTS+=("${host}"); SKIPPED_BY+=("${by}"); DEFERRED_RESTARTS+=("${host}")
    # Same as a normal deploy: the code on disk changed, the services that run it did not.
    report_stale_aux_services "${host}"
  else
    echo "==> [${host}] code synced under a lease held by ${by}; ${HOST_SERVICE} NOT restarted: host code unchanged"
    progress "${host}" restart skipped "code unchanged"
    progress "${host}" health skipped "code unchanged"
    HOST_RESTART_SKIPPED+=("${host}")
  fi
  return 0
}

# One host of this run's host lists: deploy it, or sync it when it is leased, and catch up the
# secondary server it may also run. BOTH the host loop and the runner loop use it: a runner that
# also runs a secondary server was never caught up, because the catch-up was only called in the
# host loop (E62, 2026-10-24).
deploy_host_target() {
  local host="$1"
  if is_sync_leased "${host}"; then
    if sync_leased_host "${host}"; then DEPLOY_OK+=("${host}"); DEPLOY_OK_ROLE+=("host:${host}")
    else DEPLOY_FAIL+=("${host}"); DEPLOY_FAIL_ROLE+=("host:${host}"); fi
    return 0
  fi
  if try_deploy "${host}" "${HOST_SERVICE}"; then
    reconcile_feature_units_remote "${host}"
    migrate_monitor_units_remote "${host}"
    ensure_host_prereqs_remote "${host}"
    catch_up_secondary_server "${host}"
    if ${DEPLOY_RESTART}; then
      restart_aux_services "${host}"
    fi
  fi
}

# Defense in depth for the vpt-host restart (2026-10-19): a deploy that holds or sees no lease on a Pi still must not kill a script
# that Pi is running. Asks the host's own scheduler (GET /host/deployment/jobs, run on the host itself with its API key) whether a
# deployment execution is 'running'; if so the code is already synced and the restart is deferred exactly like a leased host:
# the host goes into SKIPPED_HOSTS and the registry queues the catch-up deploy. An unreachable host or API counts as idle (fail
# open: it never blocks a deploy of a host that is down). --force deploys anyway.
host_has_running_execution() {
  local host="$1" out
  out="$(run_ssh "${host}" "sudo -n bash -c 'cd ${TARGET_DIR} && k=\$(grep -hm1 ^API_KEY= .env backend_host/src/.env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d \"\\r\"); u=\$(grep -hm1 ^HOST_API_URL= .env backend_host/src/.env 2>/dev/null | head -n1 | cut -d= -f2- | tr -d \"\\r\"); [ -n \"\$u\" ] && curl -s -m 8 -H \"X-API-Key: \$k\" \"\$u/host/deployment/jobs\"'" 2>/dev/null || true)"
  printf '%s' "${out}" | grep -Eq '"running_executions": ?\[ *\{'
}
defer_busy_host_restart() {   # 0 = the restart was deferred (caller must not restart), 1 = go ahead
  local host="$1"
  ${FORCE_DEPLOY} && return 1
  host_has_running_execution "${host}" || return 1
  echo "==> [${host}] code synced; ${HOST_SERVICE} restart DEFERRED: a deployment execution is running on it, the catch-up deploy restarts it when it ends"
  progress "${host}" restart skipped "deferred: execution running"
  progress "${host}" health skipped "restart deferred"
  SKIPPED_HOSTS+=("${host}"); SKIPPED_BY+=("running-execution"); DEFERRED_RESTARTS+=("${host}")
  return 0
}

# ---- Python dependencies the services run on ---------------------------------------------------
#
# A deploy ships code, but the Python packages live in the venv on the target and nothing
# ever reinstalls them. A change to a pinned dependency -- a security bump, for example -- therefore
# never reached the running service: the repository said one version, the venv kept the old one, and
# the deploy restarted the service happily on the old bundle and looked green (BUG-0946, 2026-10-26:
# the certifi bundle that trusts a revoked CA chain stayed in the running server for months because
# the pin in requirements.txt was all that had changed).
#
# What is compared is the pin the repository declares against the version the venv actually has, not
# against the file the target had before the rsync: the file on the target is replaced by the rsync
# before anybody looks, so a file-to-file diff says "nothing changed" exactly when the venv is the
# thing that is out of date.
#
# Only exact pins (name==version) are handled. A range (>=) would need a full resolve of the whole
# file, which is a much bigger decision than a deploy should make on its own.
#
# The server and the host each have their own manifest: a host deploy installs the pins
# backend_host/requirements.txt declares, a server deploy the ones backend_server/requirements.txt
# declares. Before this, a host deploy shipped no Python package at all, so the Pillow 13.0.0 bump
# (BUG-0954) reached the server venv and never the host venvs -- the host service kept running on the
# vulnerable Pillow it was installed with.
VENV_USER="vpt_user"
SERVER_REQS="backend_server/requirements.txt"
HOST_REQS="backend_host/requirements.txt"

repo_python_pins() {   # [<manifest>]: the exact pins the repository declares, one "name==version" per line
  local reqs="${1:-$SERVER_REQS}"
  [[ -f "${REPO_DIR}/${reqs}" ]] || return 0
  sed -e 's/#.*//' -e 's/;.*//' "${REPO_DIR}/${reqs}" \
    | grep -E '^[A-Za-z0-9._-]+==' \
    | tr 'A-Z' 'a-z' \
    | awk -F'==' '{gsub(/_/,"-",$1); print $1"=="$2}' \
    | sort -u
}

installed_version() {   # <freeze text> <name>: the version the venv has, empty when it has none
  # pip reports a distribution the way it is spelled on the wheel (pydantic_core), the repository
  # pins it the way PyPI normalises it (pydantic-core). Both sides are compared in the normalised
  # form, or every underscored package looks missing and is reinstalled on every deploy.
  printf '%s\n' "$1" | tr ',' '\n' \
    | awk -F'==' -v n="$(printf '%s' "$2" | tr '_' '-' | tr 'A-Z' 'a-z')" \
        '{gsub(/_/,"-",$1); if (tolower($1)==n) {print tolower($2); exit}}'
}

pins_to_install() {   # <freeze text> [<manifest>]: the repository pins the venv does not have at that version
  local installed="$1" reqs="${2:-$SERVER_REQS}" pin name want have
  while IFS= read -r pin; do
    [[ -z "${pin}" ]] && continue
    name="${pin%%==*}"; want="${pin#*==}"
    have="$(installed_version "${installed}" "${name}")"
    [[ "${have}" == "${want}" ]] && continue
    printf '%s\n' "${pin}"
  done < <(repo_python_pins "${reqs}")
}

install_python_pins() {   # <host> <freeze text> <manifest>: 0 = ok, 1 = a pin could not be installed
  local host="$1" installed="$2" reqs="$3" pin rc=0 list
  list="$(pins_to_install "${installed}" "${reqs}")"
  [[ -z "${list}" ]] && return 0
  echo "==> [${host}] Python pins the venv does not have yet (${reqs}): $(printf '%s' "${list}" | tr '\n' ' ')"
  # The venv belongs to the user the installer created it for. If a package was ever installed as
  # root, pip as that user cannot write the distribution metadata and leaves an invalid
  # distribution behind, so the ownership is put back before installing anything.
  run_ssh "${host}" "sudo -n chown -R ${VENV_USER}:${VENV_USER} ${TARGET_DIR}/venv" </dev/null >/dev/null 2>&1 || true
  while IFS= read -r pin; do
    [[ -z "${pin}" ]] && continue
    echo "==> [${host}] installing ${pin}"
    # stdin is closed for the ssh call: ssh forwards the loop's input to the remote command, and a
    # command that reads it swallows the rest of the list -- the loop then stops after the first
    # package and the deploy quietly installs one pin out of seven.
    if ! run_ssh "${host}" "sudo -n -u ${VENV_USER} ${TARGET_DIR}/venv/bin/pip install --no-cache-dir --disable-pip-version-check ${pin}" </dev/null; then
      # A host whose sudoers lets the ssh user reach root but not the venv's user refuses the
      # first form (a password is required to become vpt_user). As root the install still works;
      # the ownership is put back right after, so the venv is left the way the installer made it.
      echo "==> [${host}] ${VENV_USER} cannot run pip here -- installing as root and putting the venv ownership back"
      if ! run_ssh "${host}" "sudo -n ${TARGET_DIR}/venv/bin/pip install --no-cache-dir --disable-pip-version-check ${pin}" </dev/null; then
        echo "==> [${host}] FAILED to install ${pin} -- the service is NOT restarted on a half-installed dependency"
        rc=1
      else
        run_ssh "${host}" "sudo -n chown -R ${VENV_USER}:${VENV_USER} ${TARGET_DIR}/venv" </dev/null >/dev/null 2>&1 || true
      fi
    fi
  done <<< "${list}"
  return ${rc}
}

install_server_python_pins() {   # <host> <freeze text>: 0 = ok, 1 = a pin could not be installed
  install_python_pins "$1" "$2" "${SERVER_REQS}"
}

install_host_python_pins() {   # <host> <freeze text>: 0 = ok, 1 = a pin could not be installed
  install_python_pins "$1" "$2" "${HOST_REQS}"
}

# rsync, then restart <service> on <host> unless the code it runs from is unchanged since its last healthy restart
# (HOST_CODE_ID / SERVER_CODE_ID, the marker lives in the ssh user's home on that host). 0 = ok (restarted or skipped), 1 = failed.
sync_and_restart() {
  local host="$1" service="$2" id="" marker="" installed="" reqs=""
  case "${service}" in
    "${HOST_SERVICE}") id="${HOST_CODE_ID}"; marker="${HOST_CODE_MARKER}"; reqs="${HOST_REQS}" ;;
    "${SERVER_SERVICE}") id="${SERVER_CODE_ID}"; marker="${SERVER_CODE_MARKER}"; reqs="${SERVER_REQS}" ;;
  esac
  # What the venv has right now, before anything is installed: one line, so read_remote can carry it.
  installed="$(read_remote "${host}" "sudo -n -u ${VENV_USER} ${TARGET_DIR}/venv/bin/pip list --format=freeze 2>/dev/null | tr '\n' ','")"
  [[ -z "${installed}" ]] && installed="$(read_remote "${host}" "${TARGET_DIR}/venv/bin/pip list --format=freeze 2>/dev/null | tr '\n' ','")"
  if [[ -z "${id}" ]]; then
    rsync_push "${host}" || return 1
    [[ "${service}" == "${HOST_SERVICE}" ]] && defer_busy_host_restart "${host}" && return 0
    install_python_pins "${host}" "${installed}" "${reqs}" || return 1
    restart_and_status "${host}" "${service}"; return
  fi
  rsync_push "${host}" || return 1
  # The venv is compared with what the repository declares on EVERY deploy, not only when the
  # code changed: a venv that drifted (a package installed by hand, a failed install, an image built
  # elsewhere) must be able to catch up even when the code on disk is the same.
  install_python_pins "${host}" "${installed}" "${reqs}" || return 1
  local seen active
  seen="$(read_remote "${host}" "cat ~/${marker} 2>/dev/null || true")"
  active="$(read_remote "${host}" "systemctl is-active ${service} 2>/dev/null || true")"
  if [[ "${seen}" == "${id}" && "${active}" == active ]]; then
    echo "==> [${host}] ${service} NOT restarted: its code is unchanged since the last restart (${id:0:10}); VPT_FORCE_HOST_RESTART=1 forces it"
    progress "${host}" restart skipped "code unchanged"
    progress "${host}" health skipped "code unchanged"
    HOST_RESTART_SKIPPED+=("${host}")
    return 0
  fi
  [[ "${service}" == "${HOST_SERVICE}" ]] && defer_busy_host_restart "${host}" && return 0
  restart_and_status "${host}" "${service}" || return 1
  run_ssh "${host}" "echo ${id} > ~/${marker}" >/dev/null 2>&1 || true
  # The host service now runs the new code; the aux services were not restarted by this
  # deploy (the aux restart is opt-in) and their disk copy just changed under them.
  [[ "${service}" == "${HOST_SERVICE}" ]] && report_stale_aux_services "${host}"
  return 0
}

critical_deploy() {
  local host="$1"
  local service="$2"
  if sync_and_restart "${host}" "${service}"; then
    DEPLOY_OK+=("${host}"); DEPLOY_OK_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
  else
    DEPLOY_FAIL+=("${host}"); DEPLOY_FAIL_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
    echo "==> [${host}] CRITICAL deploy failed"
    return 1
  fi
}

# Sync + restart (best-effort — skip on failure)
try_deploy() {
  local host="$1"
  local service="$2"
  if sync_and_restart "${host}" "${service}"; then
    DEPLOY_OK+=("${host}"); DEPLOY_OK_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
    return 0
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${host}"); DEPLOY_FAIL_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
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
#
# VPT_FORCE_BUILD=1 is passed unconditionally: a deploy that just rsync'd source
# is by definition a source change, so the bundle should always be rebuilt. The
# hash-skip is reserved for the systemd unit's ExecStartPre (where it actually
# saves 30s on a hot restart). Without the force, a deploy whose source happens
# to hash identically to the previous dist's stamp — rsync that brought the
# same files twice, or a commit that only touched docs/ — would silently keep
# serving the OLD bundle, which is exactly the failure mode that bit
# /tmp/t113-poc.js twice (TASK-113, 2026-10-16).
build_frontend_bundle() {
  local host="$1"
  echo -e "\n==> [${host}] Building frontend bundle (previous bundle stays served)"
  progress "${host}" install start "frontend build"
  lease_expiry_guard "frontend build on ${host}"   # the build is the longest single step
  # -H: npm's cache must land in ${SYNC_USER}'s home, not the deploying user's.
  if ! run_ssh "${host}" "sudo -n -H -u ${SYNC_USER} VPT_FORCE_BUILD=1 bash ${TARGET_DIR}/frontend/scripts/ensure_dist.sh"; then
    echo "==> [${host}] frontend build FAILED — not restarting (live bundle left untouched)"
    progress "${host}" install failed "frontend build failed; the live bundle is untouched"
    return 1
  fi
  progress "${host}" install ok "frontend build"
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
    DEPLOY_OK+=("${host}"); DEPLOY_OK_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
  else
    DEPLOY_FAIL+=("${host}"); DEPLOY_FAIL_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
    echo "==> [${host}] CRITICAL deploy failed"
    return 1
  fi
}

# Windows sync + restart (best-effort)
# ---- Docker-compose stacks (DOCKER_IPS) ----
# Push the tree into the stack's checkout, then rebuild + recreate the given compose services
# DETACHED on that machine: an image build can take minutes and must not hold the deploy lease.
# Builds queue behind a flock and log to ~/build-logs/update_core-<version>.log there.
# - no --delete and no --chown: the checkout belongs to the stack's account and holds VM-local
#   files (both .env, docker-compose.<vm>.yml overrides, the generated docs mirror).
# - the public-snapshot deny-list (scripts/security/internal-paths.txt) is excluded too: these
#   stacks are public showcases and get what the public snapshot would carry, no internal paths.
# - compose files come from the running stack's own labels, so VM overrides keep applying.
#   A machine with no running stack is refused: install it by hand first.
docker_deploy() {
  local host="$1"; shift
  local services="$*"
  local ssh_target version p
  local -a deny=()
  ssh_target="$(build_ssh_target "${host}")"
  if [[ -f "${REPO_DIR}/scripts/security/internal-paths.txt" ]]; then
    while IFS= read -r p; do
      p="${p%%#*}"; p="${p#"${p%%[![:space:]]*}"}"; p="${p%"${p##*[![:space:]]}"}"
      [[ -n "${p}" ]] && deny+=("--exclude=/${p%/}")
    done < "${REPO_DIR}/scripts/security/internal-paths.txt"
  fi
  echo -e "\n==> [proxmox -> ${host}] rsync push (docker: ${DOCKER_DIR})"
  progress "${host}" rsync start
  # The stack checkout is a MIRROR of the tree, not a merge (rsync_push has always mirrored).
  # Without --delete a file that upstream renamed or removed stays behind on the stack and can
  # shadow its replacement: a stale `Foo.ts` next to the new `Foo.tsx` makes vite resolve the old
  # one and the image build fails with "NavLabel is not exported by ..." (2026-10-25: the gcloud
  # standalone frontend was frozen on an Oct-22 image for three days because of this).
  # The stack's own files are kept: rsync never deletes an excluded file, and the 'P' rules below
  # protect the ones the exclude list does not cover (its compose override, its .env backups).
  if ! rsync -az -q --timeout=90 --delete \
    --filter='P /**/.env*' \
    --filter='P /setup/docker/docker-compose.*.yml' \
    --filter='P /setup/docker/*.bak' \
    "${RSYNC_EXCLUDES[@]}" ${deny[@]+"${deny[@]}"} \
    -e "ssh ${SSH_OPTS}" "${REPO_DIR}/" "${ssh_target}:${DOCKER_DIR}/"; then
    echo "==> [${host}] rsync FAILED"
    progress "${host}" rsync failed "rsync push failed"
    return 1
  fi
  progress "${host}" rsync ok
  version="$(sed -n 's/^current://p' "${REPO_DIR}/VERSION.txt" 2>/dev/null | head -1)"
  progress "${host}" install start "docker compose build (background)"
  local _docker_rc=0
  run_ssh "${host}" "bash -s" <<REMOTE || _docker_rc=$?
set -euo pipefail
cd "${DOCKER_DIR}/setup/docker"
files="\$(docker ps -a --filter label=com.docker.compose.service=backend_host \
  --format '{{.Label "com.docker.compose.project.config_files"}}' | head -1)"
if [[ -z "\${files}" ]]; then echo "no compose stack here: install it by hand first"; exit 1; fi
args=""; IFS=',' read -ra fs <<< "\${files}"; for f in "\${fs[@]}"; do args="\${args} -f \${f}"; done
mkdir -p ~/build-logs
log=~/build-logs/update_core-${version:-unknown}.log
# Append, do not truncate: two scopes of the SAME version (a frontend and a hosts deploy in the
# same minute) write to one log name, and the second run used to wipe the first one's output —
# which is how a failing image build stayed invisible (2026-10-25).
nohup flock ~/build-logs/.update_core.lock bash -c "export VPT_IMAGE_TAG=local; docker compose \${args} build ${services} && docker compose \${args} up -d --force-recreate --no-deps ${services}" >> "\${log}" 2>&1 < /dev/null &
echo "build started in the background (${services}) -> \${log}"
REMOTE
  if (( _docker_rc == 0 )); then progress "${host}" install ok "build started in the background"
  else progress "${host}" install failed "could not start the build (exit ${_docker_rc})"; fi
  progress "${host}" restart skipped "docker: recreated by the background build"
  progress "${host}" health skipped "docker: recreated by the background build"
  return "${_docker_rc}"
}

try_deploy_windows() {
  local host="$1"
  if rsync_push_windows "${host}" && restart_windows_task "${host}"; then
    DEPLOY_OK+=("${host}"); DEPLOY_OK_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${host}"); DEPLOY_FAIL_ROLE+=("${DEPLOY_PHASE:-host}:${host}")
  fi
}

usage() {
  cat <<'EOF'
Usage:
  bash update_core.sh [branch] [--frontend] [--server] [--host] [--host-windows] [--force] [--redeploy]

Examples:
  bash update_core.sh
  bash update_core.sh debug
  bash update_core.sh --frontend
  bash update_core.sh debug --frontend
  bash update_core.sh --server --host
  bash update_core.sh --skip-leased             # full deploy, leased hosts synced, restarts deferred
  bash update_core.sh --host --hosts vpt-pi1    # only that host
  bash update_core.sh --skip-hosts labox-mobile # everything except one host
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
  - DOCKER_IPS (compose stacks built from source, e.g. vpt-gcloud) follow every deploy: the tree
    is pushed (public-snapshot deny-list applied) and the matching services are rebuilt in the
    BACKGROUND there — server->backend_server, frontend->frontend, host->backend_host.
    --hosts / --skip-hosts filter them like hosts.
  - Aux services: vpt-stream vpt-monitor-img vpt-monitor-subtitle vpt-monitor-audio vpt-archiver vpt-avq vpt-kpi

Flow:
  1. Git pull on proxmox (directly from GitHub) — skipped when REPO_DIR is an
     extracted offline bundle (BUNDLE_MANIFEST.txt present, no .git; see
     DEPLOY_CUSTOMER.md "Deploying without GitHub access")
  2. Print VERSION.txt (source-controlled / written by the bundle builder)
  3. Rsync push to each target VM + restart services; on hosts also
     setup/proxmox/node/reconcile_feature_units.sh (feature systemd units)

REPO_DIR=<dir> overrides the source tree (default ~/virtualpytest).

Already-current targets: a target whose last successful deploy (vpt-lease deploy last) is the requested commit,
or a descendant of it, is skipped ("already on <commit>: <target> (skipped)"); never rolled back. Checked before
the lease claim and again once it is granted. --redeploy (or --force) deploys them anyway.
Restarting only a lease-free service (`--restart <svc>`, svc in LEASE_FREE_SERVICES) needs no lease.

Busy env: the deploy queues behind the holder (vpt-lease claim --wait) instead of exiting 3;
VPT_DEPLOY_NO_QUEUE=1 restores fail-fast, --force skips the queue.

Agent leases: before deploying, the shared lease registry (vpt-lease) is checked for
this node's env (LEASE_ENV). If any agent holds a lease there, the deploy aborts (exit 3) and prints
who holds what. Only leases on what this run touches count: --frontend checks
'frontend', --host checks each host, and the server (or a host given by IP) counts
as the whole env. --force deploys anyway. While the deploy runs it holds a lease on
the same resources, released on exit. VPT_LEASE_AGENT=<id> names the deploying agent, so its
own leases do not block it. With no registry configured, the check is skipped.

Choosing hosts (HOST_IPS / RUNNER_IPS / HOST_WINDOWS_IPS are filtered for this run only):
  --hosts a,b      deploy only these hosts (implies --host for them; a name this node does not know
                   is dropped with a WARNING, and the deploy aborts only if EVERY name is unknown)
  --skip-hosts a,b drop these hosts from this run
  --skip-leased    a host of this run's host lists that another agent holds a lease on is
                   synced without a lease (its vpt-host restart is deferred to the catch-up
                   deploy), printed as `SYNC ONLY (leased by <agent>): <host>`; a leased host
                   that is not part of this run (a Windows host, a secondary server) is dropped
                   and printed as `SKIPPED (leased by <agent>): <host>`. The server part is
                   blocked only by `server` leases (anywhere in the env) and env-wide leases,
                   not by `host` leases on a host (vpt-lease claim --kind host); frontend as
                   without the flag. Still blocked -> abort (exit 3). When hosts were skipped
                   the LAST output line is `SKIPPED_HOSTS=a,b` (the deploy runner queues a
                   catch-up deploy for them).
Without these flags the behaviour is unchanged.
EOF
}

# ---- Parse args ----
DEPLOY_BRANCH=""
DEPLOY_SERVER=false
DEPLOY_FRONTEND=false
DEPLOY_HOSTS=false
DEPLOY_HOSTS_WINDOWS=false
FORCE_DEPLOY=false
REDEPLOY=false       # deploy targets already on the requested commit too (--force implies it)
SKIP_LEASED=false
SKIP_HOSTS_ARG=""
ONLY_HOSTS_ARG=""
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
    --skip-leased)   SKIP_LEASED=true ;;
    --skip-hosts)
      [[ $# -ge 2 ]] || { echo "--skip-hosts needs a comma-separated host list" >&2; exit 1; }
      SKIP_HOSTS_ARG="${SKIP_HOSTS_ARG},$2"; shift ;;
    --hosts)
      [[ $# -ge 2 ]] || { echo "--hosts needs a comma-separated host list" >&2; exit 1; }
      ONLY_HOSTS_ARG="${ONLY_HOSTS_ARG},$2"; DEPLOY_HOSTS=true; shift ;;
    --force)         FORCE_DEPLOY=true ;;
    --redeploy)      REDEPLOY=true ;;
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

# A pure --server deploy (no host, frontend or restart part) is --skip-leased: a vpt-server restart does not kill scripts
# running on hosts, so host-kind leases must not block it; server-kind leases and a leased Pi's server still do (2026-10-19).
if ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS} && ! ${DEPLOY_RESTART}; then
  SKIP_LEASED=true
fi

# Restarting ONLY a background service that starts in seconds needs no lease: the few seconds it misses mean
# nothing (deploy skill, "Which services need a lease"). vpt-host and vpt-stream are not in this list.
LEASE_FREE_SERVICES=(vpt-archiver vpt-monitor-img vpt-kpi vpt-monitor-audio vpt-monitor-subtitle vpt-avq vpt-heatmap)
FREE_RESTART=false
if ${RESTART_ONLY} && [[ -n "${RESTART_SERVICE:-}" && " ${LEASE_FREE_SERVICES[*]} " == *" ${RESTART_SERVICE} "* ]]; then
  FREE_RESTART=true
fi

# Default (no target flags AND no --restart): deploy everything (no aux restart).
if ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS} && ! ${DEPLOY_RESTART}; then
  DEPLOY_SERVER=true
  DEPLOY_FRONTEND=true
  DEPLOY_HOSTS=true
  DEPLOY_HOSTS_WINDOWS=true
fi

# ---- Host selection: --hosts / --skip-hosts (filters this run's host lists; the lists are not edited) ----
# host_list_filter <list> keep|drop <names>: names match case-insensitively, result is comma-joined.
host_list_filter() {
  local list="$1" mode="$2" names h out="" hit
  names=",$(printf '%s' "$3" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'),"
  local -a _hf
  IFS=',' read -ra _hf <<< "${list}"
  for h in "${_hf[@]}"; do
    h="${h//[[:space:]]/}"
    [[ -z "${h}" ]] && continue
    hit=false
    if [[ "${names}" == *",$(printf '%s' "${h}" | tr '[:upper:]' '[:lower:]'),"* ]]; then hit=true; fi
    if [[ "${mode}" == keep && "${hit}" == true ]] || [[ "${mode}" == drop && "${hit}" == false ]]; then
      out="${out:+${out},}${h}"
    fi
  done
  printf '%s' "${out}"
}
# the names of <names> this node does NOT know: a retired host is unknown too (it was removed from
# the node's lists), and ~/.ssh/config must not be used as the source of "known" — it would re-admit
# a host that was retired on purpose.
hosts_unknown() {
  local n known=",$(printf '%s' "${HOST_IPS},${RUNNER_IPS},${HOST_WINDOWS_IPS},${DOCKER_IPS}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'),"
  local -a _hn
  IFS=',' read -ra _hn <<< "$1"
  for n in "${_hn[@]}"; do
    n="${n//[[:space:]]/}"
    [[ -z "${n}" ]] && continue
    if [[ "${known}" != *",$(printf '%s' "${n}" | tr '[:upper:]' '[:lower:]'),"* ]]; then printf '%s ' "${n}"; fi
  done
}
# the names of <names> this node DOES know, in the caller's order (the unknown ones are dropped)
hosts_filter_known() {
  local n known out=""
  known=",$(printf '%s' "${HOST_IPS},${RUNNER_IPS},${HOST_WINDOWS_IPS},${DOCKER_IPS}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'),"
  local -a _hk
  IFS=',' read -ra _hk <<< "$1"
  for n in "${_hk[@]}"; do
    n="${n//[[:space:]]/}"
    [[ -z "${n}" ]] && continue
    if [[ "${known}" == *",$(printf '%s' "${n}" | tr '[:upper:]' '[:lower:]'),"* ]]; then out="${out:+${out},}${n}"; fi
  done
  printf '%s' "${out}"
}
# the names the request dropped because this node does not know them: they go into the deploy NOTE
# only, never into SKIPPED_HOSTS (that queues a catch-up deploy, which for a retired host never ends)
DROPPED_HOSTS=()
if [[ -n "${ONLY_HOSTS_ARG}" ]]; then
  ONLY_HOSTS_ARG="${ONLY_HOSTS_ARG#,}"
  # a request that names no host at all would deploy nothing, silently: refuse it
  if [[ ! "${ONLY_HOSTS_ARG}" =~ [^[:space:],] ]]; then
    echo "ABORT: --hosts names not in this node's host lists (the requested list is empty: no host named)" >&2
    exit 1
  fi
  unknown="$(hosts_unknown "${ONLY_HOSTS_ARG}")"
  known_hosts="$(hosts_filter_known "${ONLY_HOSTS_ARG}")"
  if [[ -z "${known_hosts}" ]]; then
    # every name is unknown: the request itself is wrong (a typo, or a node that was retired) — abort
    echo "ABORT: --hosts names not in this node's host lists (every name unknown): ${unknown}" >&2
    echo "       known: ${HOST_IPS}${RUNNER_IPS:+,${RUNNER_IPS}}${HOST_WINDOWS_IPS:+,${HOST_WINDOWS_IPS}}" >&2
    exit 1
  fi
  if [[ -n "${unknown}" ]]; then
    # ONE unknown name must not kill the deploy of the other hosts: drop it loudly and go on
    # (a retired host looked exactly like a typo here, and it took the whole deploy down with it)
    echo "WARNING: --hosts names not in this node's host lists (dropped): ${unknown}" >&2
    echo "       known: ${HOST_IPS}${RUNNER_IPS:+,${RUNNER_IPS}}${HOST_WINDOWS_IPS:+,${HOST_WINDOWS_IPS}}" >&2
    IFS=' ' read -ra DROPPED_HOSTS <<< "${unknown}"
  fi
  ONLY_HOSTS_ARG="${known_hosts}"
  HOST_IPS="$(host_list_filter "${HOST_IPS}" keep "${ONLY_HOSTS_ARG}")"
  RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" keep "${ONLY_HOSTS_ARG}")"
  HOST_WINDOWS_IPS="$(host_list_filter "${HOST_WINDOWS_IPS}" keep "${ONLY_HOSTS_ARG}")"
  DOCKER_IPS="$(host_list_filter "${DOCKER_IPS}" keep "${ONLY_HOSTS_ARG}")"
  echo "Hosts: only ${ONLY_HOSTS_ARG}"
fi
if [[ -n "${SKIP_HOSTS_ARG}" ]]; then
  SKIP_HOSTS_ARG="${SKIP_HOSTS_ARG#,}"
  unknown="$(hosts_unknown "${SKIP_HOSTS_ARG}")"
  [[ -n "${unknown}" ]] && echo "WARNING: --skip-hosts names not in this node's host lists (ignored): ${unknown}"
  HOST_IPS="$(host_list_filter "${HOST_IPS}" drop "${SKIP_HOSTS_ARG}")"
  RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" drop "${SKIP_HOSTS_ARG}")"
  HOST_WINDOWS_IPS="$(host_list_filter "${HOST_WINDOWS_IPS}" drop "${SKIP_HOSTS_ARG}")"
  DOCKER_IPS="$(host_list_filter "${DOCKER_IPS}" drop "${SKIP_HOSTS_ARG}")"
  echo "Hosts: skipping ${SKIP_HOSTS_ARG}"
fi

# ---- Hosts that are down on purpose, or unreachable right now: skipped, never failed ----
# A host that cannot take the deploy must not turn the whole deploy "failed": agents rerun a failed full deploy,
# and every rerun restarts vpt-host on the reachable hosts under their long runs (TASK-129, TASK-33).
#  1. DOWN_HOSTS_FILE (default ~/.vpt-down-hosts, one name per line, # comments): hosts switched off on purpose.
#     Dropped from every host list. A deploy that NAMES them with --hosts ignores the file (the person means it).
#  2. Preflight: one short ssh per remaining host, in parallel. No route / refused / timeout = skipped (unreachable).
#     VPT_SKIP_PROBE=1 turns the probe off.
# Both are printed and recorded in the deploy note as "skipped (down|unreachable)". They are NOT in SKIPPED_HOSTS:
# that line queues a catch-up deploy, which for a down host would loop for ever.
DOWN_HOSTS_FILE="${DOWN_HOSTS_FILE:-${HOME}/.vpt-down-hosts}"
DOWN_SKIPPED=()
PINNED_SKIPPED=()
PINNED_HOSTS_FILE="${PINNED_HOSTS_FILE:-${HOME}/.vpt-pinned-hosts}"
HOST_RESTART_SKIPPED=()
UNREACHABLE_SKIPPED=()
drop_hosts_everywhere() {
  HOST_IPS="$(host_list_filter "${HOST_IPS}" drop "$1")"
  RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" drop "$1")"
  HOST_WINDOWS_IPS="$(host_list_filter "${HOST_WINDOWS_IPS}" drop "$1")"
  DOCKER_IPS="$(host_list_filter "${DOCKER_IPS}" drop "$1")"
}
all_deploy_hosts() {
  printf '%s,%s,%s,%s' "${HOST_IPS}" "${RUNNER_IPS}" "${HOST_WINDOWS_IPS}" "${DOCKER_IPS}" | tr ',' '\n' | tr -d ' \t' | sed '/^$/d' | sort -u
}
plan_down_and_unreachable() {
  local h line down_names=""
  if [[ -z "${ONLY_HOSTS_ARG}" && -r "${DOWN_HOSTS_FILE}" ]]; then
    while IFS= read -r line || [[ -n "${line}" ]]; do
      line="${line%%#*}"; line="$(printf '%s' "${line}" | tr -d '[:space:]')"
      [[ -z "${line}" ]] && continue
      down_names="${down_names:+${down_names},}${line}"
    done < "${DOWN_HOSTS_FILE}"
    for h in $(all_deploy_hosts); do
      if [[ ",$(printf '%s' "${down_names}" | tr '[:upper:]' '[:lower:]')," == *",$(printf '%s' "${h}" | tr '[:upper:]' '[:lower:]'),"* ]]; then
        DOWN_SKIPPED+=("${h}")
      fi
    done
    if (( ${#DOWN_SKIPPED[@]} > 0 )); then drop_hosts_everywhere "$(IFS=,; echo "${DOWN_SKIPPED[*]}")"; fi
  fi
  # Pinned hosts (PINNED_HOSTS_FILE, same format): hosts that run long jobs. A push-driven deploy (full, --host, --skip-leased)
  # leaves them on the code they have; they are updated only by a deploy that NAMES them (--hosts a,b), which the manager
  # runs in an idle gap. Not in SKIPPED_HOSTS: no catch-up is queued, that is the point.
  if [[ -z "${ONLY_HOSTS_ARG}" && -r "${PINNED_HOSTS_FILE}" ]]; then
    local pin_names=""
    while IFS= read -r line || [[ -n "${line}" ]]; do
      line="${line%%#*}"; line="$(printf '%s' "${line}" | tr -d '[:space:]')"
      [[ -z "${line}" ]] && continue
      pin_names="${pin_names:+${pin_names},}${line}"
    done < "${PINNED_HOSTS_FILE}"
    for h in $(all_deploy_hosts); do
      if [[ ",$(printf '%s' "${pin_names}" | tr '[:upper:]' '[:lower:]')," == *",$(printf '%s' "${h}" | tr '[:upper:]' '[:lower:]'),"* ]]; then
        PINNED_SKIPPED+=("${h}")
      fi
    done
    if (( ${#PINNED_SKIPPED[@]} > 0 )); then drop_hosts_everywhere "$(IFS=,; echo "${PINNED_SKIPPED[*]}")"; fi
  fi
  if [[ "${VPT_SKIP_PROBE:-0}" == 1 ]]; then return 0; fi
  local pdir; pdir="$(mktemp -d)"
  for h in $(all_deploy_hosts); do
    # Windows hosts have no `true`: probe them with a command cmd.exe knows.
    local probe_cmd=true
    [[ ",${HOST_WINDOWS_IPS//[[:space:]]/}," == *",${h},"* ]] && probe_cmd='cmd /c exit 0'
    ( ssh ${SSH_OPTS} -o BatchMode=yes -o ConnectTimeout=6 "$(build_ssh_target "${h}")" ${probe_cmd} >/dev/null 2>&1 || : > "${pdir}/${h}.down" ) &
  done
  wait
  for h in $(all_deploy_hosts); do if [[ -e "${pdir}/${h}.down" ]]; then UNREACHABLE_SKIPPED+=("${h}"); fi; done
  rm -rf "${pdir}"
  if (( ${#UNREACHABLE_SKIPPED[@]} > 0 )); then drop_hosts_everywhere "$(IFS=,; echo "${UNREACHABLE_SKIPPED[*]}")"; fi
  return 0
}
if ${DEPLOY_HOSTS} || ${DEPLOY_HOSTS_WINDOWS} || ${DEPLOY_RESTART} || [[ -n "${DOCKER_IPS}" ]]; then
  plan_down_and_unreachable
  if (( ${#DOWN_SKIPPED[@]} > 0 )); then echo "SKIPPED (down on purpose, ${DOWN_HOSTS_FILE}): ${DOWN_SKIPPED[*]}"; fi
  if (( ${#UNREACHABLE_SKIPPED[@]} > 0 )); then echo "SKIPPED (unreachable, no ssh): ${UNREACHABLE_SKIPPED[*]}"; fi
  if (( ${#PINNED_SKIPPED[@]} > 0 )); then echo "SKIPPED (pinned for long runs, ${PINNED_HOSTS_FILE}; deploy with --hosts to update): ${PINNED_SKIPPED[*]}"; fi
fi

echo "Starting VirtualPyTest deployment..."
echo "Targets: server=${DEPLOY_SERVER} frontend=${DEPLOY_FRONTEND} hosts=${DEPLOY_HOSTS} hosts-windows=${DEPLOY_HOSTS_WINDOWS} restart=${DEPLOY_RESTART}"
echo "Branch: ${DEPLOY_BRANCH:-<current branch>}"

# ---- Agent lease guard ----
# Several agents test on the same platform; a deploy restarts services under them.
# They claim what they use in a shared registry (vpt-lease, see the `deploy` skill),
# and a deploy only goes ahead when nobody holds a lease on this node's env.
# Registry: ~/bin/vpt-lease on this node if present, else on ${LEASE_REGISTRY_HOST}.
LEASE_ENV="${LEASE_ENV:-node1-vpt}"
LEASE_REGISTRY_HOST="${LEASE_REGISTRY_HOST:-}"
DEPLOY_AGENT="${VPT_LEASE_AGENT:-update_core:$(id -un)@$(hostname -s)}"
LEASE_ID=""
# The Windows game box leases in its own env, not in the node's: a Windows host deploy breaks what runs there
# (vpt-windows/game ...) and nothing on LEASE_ENV, so it is claimed separately as <WIN_LEASE_ENV>/*.
WIN_LEASE_ENV="${WIN_LEASE_ENV:-vpt-windows}"
WIN_LEASE_ID=""
# Owner rule 2026-10-19: a deployment never holds a lease for more than 10 minutes (measured deploys: median 0.8 min,
# max 6.2 min). The claim carries this TTL and nothing renews it, so the registry drops the lease 10 minutes after the
# FIRST grant (time queued behind another holder does not count). DEPLOY_LEASE_TTL_MIN overrides it for tests only.
DEPLOY_LEASE_TTL_MIN="${DEPLOY_LEASE_TTL_MIN:-10}"
LEASE_GRANTED_EPOCH=""
CLAIM_ENV=""
# Central lease cut-over (mycodebox LEASES-CENTRAL §10, step 2, 2026-10-18). The client's own config says which
# registry decides: the legacy one only knows a server restart as '*'; the central service types it as <env>/server.
lease_mode() { { sed -n 's/^VPT_LEASE_MODE=//p' "${HOME}/.config/vpt-lease/config" 2>/dev/null | tr -d "'\" " | tail -1; } || true; }
LEASE_MODE="${VPT_LEASE_MODE:-$(lease_mode)}"
server_resource() { if [[ "${LEASE_MODE}" == central ]]; then printf 'server'; else printf '*'; fi; }
# A host given by IP: its name from ~/.ssh/config (Host <name> ... HostName <ip>), else '' (the caller counts it as '*').
ip_host_name() { awk -v ip="$1" 'tolower($1)=="host"{h=$2} tolower($1)=="hostname" && $2==ip && h!="" {print h; exit}' "${HOME}/.ssh/config" 2>/dev/null || true; }
lease_cmd() {
  if [[ -x "${HOME}/bin/vpt-lease" ]]; then
    "${HOME}/bin/vpt-lease" "$@"
  elif [[ -n "${LEASE_REGISTRY_HOST}" ]]; then
    ssh -o BatchMode=yes -o ConnectTimeout=10 "${LEASE_REGISTRY_HOST}" "~/bin/vpt-lease $(printf '%q ' "$@")"
  else
    return 127
  fi
}
SKIPPED_HOSTS=()
SKIPPED_BY=()
SKIPPED_EMITTED=false
emit_skipped_hosts() {
  if (( ${#SKIPPED_HOSTS[@]} > 0 )) && ! ${SKIPPED_EMITTED}; then
    SKIPPED_EMITTED=true
    echo "SKIPPED_HOSTS=$(IFS=,; echo "${SKIPPED_HOSTS[*]}")"
  fi
}
JOINED_LEASE=false   # LEASE_ID is the queue runner's deploy lease (VPT_LEASE_ID): the runner releases it, never this script
release_deploy_lease() {
  if [[ -n "${LEASE_ID}" ]] && ! ${JOINED_LEASE}; then
    lease_cmd release "${LEASE_ID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${WIN_LEASE_ID}" ]]; then
    lease_cmd release "${WIN_LEASE_ID}" >/dev/null 2>&1 || true
  fi
  emit_skipped_hosts
}
# What this run touches, so a partial deploy is only blocked by leases it would disturb
# (host-clone-1 in use must not block a --frontend deploy). A server restart breaks every
# in-flight run (hosts report results to it), so it counts as '*'. A host listed by IP
# cannot be matched to a lease name, so it counts as '*' too.
# Defined before its first use: add_lease_hosts below runs at load time.
trim_host() {
  local h="$1"
  h="${h#"${h%%[![:space:]]*}"}"
  h="${h%"${h##*[![:space:]]}"}"
  printf '%s' "$h"
}
LEASE_RESOURCES=()
add_lease_hosts() {
  local h
  IFS=',' read -ra _lease_hosts <<< "$1"
  for h in "${_lease_hosts[@]}"; do
    h="$(trim_host "${h}")"
    [[ -z "${h}" ]] && continue
    is_sync_leased "${h}" && continue    # synced without a lease, never restarted in this run
    if [[ "${h}" =~ ^[0-9.]+$ ]]; then local n; n="$(ip_host_name "${h}")"; LEASE_RESOURCES+=("${n:-*}"); else LEASE_RESOURCES+=("${h}"); fi
  done
}
server_secondary_names() {
  local -a _s; local i=0 out="" x
  IFS=',' read -ra _s <<< "${SERVER_IP}"
  for x in ${_s[@]+"${_s[@]}"}; do
    x="${x//[[:space:]]/}"; [[ -z "${x}" ]] && continue
    if (( i++ > 0 )); then out="${out:+${out},}${x}"; fi
  done
  printf '%s' "${out}"
}
# The boxes that run a secondary server, frozen here -- before the lease plan can change the list.
# plan_skip_leased drops a LEASED secondary server from SERVER_IP (the server deploy must not touch
# a box another agent holds), but "this box runs a secondary server" is a fact about the fleet, not
# about this run's leases: the catch-up has to recognise the box it is catching up, and a leased
# box is exactly the one it has to (E64, 2026-10-24).
SECONDARY_SERVERS="$(server_secondary_names)"
NO_CLAIM=false
NODE_CLAIM_KIND=()   # extra claim args of the node claim (never of the Windows claim): `--kind host` for a host-only run
# A host-only run (hosts or a restart-only, no server, no frontend) restarts vpt-host only. The client defaults any non-device
# claim to kind=server, and a kind=server host claim conflicts with every `server` claim, so server deploys queued behind host
# deploys. `--kind host` keeps the conflicts that matter (every lease on the same host or its devices, other host deploys of
# it) and drops the one with `server` claims. Exception: a host that also runs a secondary server (SERVER_IP entries after
# the first, e.g. vpt-pi1) stays kind=server, because a server deploy syncs and restarts vpt-server on that same Pi.
lease_kind_args() {
  NODE_CLAIM_KIND=()
  ${DEPLOY_SERVER} && return 0
  ${DEPLOY_FRONTEND} && return 0
  { ${DEPLOY_HOSTS} || ${RESTART_ONLY:-false}; } || return 0
  [[ " ${LEASE_RESOURCES[*]} " == *" * "* ]] && return 0
  local r s n sec=",$(server_secondary_names | tr '[:upper:]' '[:lower:]'),"
  for s in $(server_secondary_names | tr ',' ' '); do
    if [[ "${s}" =~ ^[0-9.]+$ ]]; then n="$(ip_host_name "${s}")"; [[ -n "${n}" ]] && sec="${sec}$(printf '%s' "${n}" | tr '[:upper:]' '[:lower:]'),"; fi
  done
  for r in ${LEASE_RESOURCES[@]+"${LEASE_RESOURCES[@]}"}; do
    [[ "${sec}" == *",$(printf '%s' "${r}" | tr '[:upper:]' '[:lower:]'),"* ]] && return 0
  done
  NODE_CLAIM_KIND=(--kind host)
}
WIN_CLAIM=false     # a Windows host is deployed: claim ${WIN_LEASE_ENV}/* (never on LEASE_ENV)
NODE_CLAIM_SKIP=false   # nothing of this run lives on LEASE_ENV (Windows-only deploy)
compute_lease_resources() {
  LEASE_RESOURCES=()
  if ${DEPLOY_SERVER}; then LEASE_RESOURCES+=("$(server_resource)"); fi
  if ${DEPLOY_FRONTEND}; then LEASE_RESOURCES+=(frontend); fi
  if ${DEPLOY_HOSTS} || ${RESTART_ONLY:-false}; then add_lease_hosts "${HOST_IPS}"; add_lease_hosts "${RUNNER_IPS}"; fi
  WIN_CLAIM=false; NODE_CLAIM_SKIP=false
  if ${DEPLOY_HOSTS_WINDOWS} && [[ -n "$(trim_host "${HOST_WINDOWS_IPS//,/}")" ]]; then WIN_CLAIM=true; fi
  NO_CLAIM=false
  if ${WIN_CLAIM} && (( ${#LEASE_RESOURCES[@]} == 0 )); then NODE_CLAIM_SKIP=true; return 0; fi
  if (( ${#LEASE_RESOURCES[@]} == 0 && ${#SYNC_LEASED[@]} > 0 )); then NO_CLAIM=true; return 0; fi
  if [[ " ${LEASE_RESOURCES[*]} " == *" * "* || ${#LEASE_RESOURCES[@]} -eq 0 ]]; then LEASE_RESOURCES=('*'); fi
  lease_kind_args
}
# ---- Skip targets already on the requested commit ----
# The registry records the commit each target last deployed (`vpt-lease deploy last --json`). A target on the requested
# commit, or on a descendant of it (the requested commit is an ancestor: never roll back), is dropped from this run. Run
# before the lease claim and again right after it is granted: a waiter may have been overtaken by another deploy while
# queued. Fail open: no git, no registry answer or no python3 -> deploy as before, with one warning. --redeploy/--force
# deploy regardless. Not applied to restart-only runs or offline bundles (no commit).
declare -A DEPLOYED_COMMIT=()
SKIP_TARGET_COMMIT=""
SKIP_CURRENT_WARNED=false
# Hosts whose files are already on the requested commit, but that run a secondary server: they are
# decided later, when the server code id is known (see drop_current_hosts).
CURRENT_HOSTS=()
current_host_remember() {   # <host>: remember it once (the check runs twice: before and after the claim)
  local x
  for x in ${CURRENT_HOSTS[@]+"${CURRENT_HOSTS[@]}"}; do [[ "${x}" == "${1}" ]] && return 0; done
  CURRENT_HOSTS+=("${1}")
  return 0
}
skip_current_warn() { ${SKIP_CURRENT_WARNED} || echo "WARNING: already-deployed check skipped ($1): deploying as usual"; SKIP_CURRENT_WARNED=true; }
target_is_current() {   # $1 = target name (frontend, server, host name or IP)
  local k c n
  k="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  c="${DEPLOYED_COMMIT[$k]:-}"
  if [[ -z "${c}" && "$1" =~ ^[0-9.]+$ ]]; then
    n="$(ip_host_name "$1" | tr '[:upper:]' '[:lower:]')"; [[ -n "${n}" ]] && c="${DEPLOYED_COMMIT[$n]:-}"
  fi
  [[ -n "${c}" ]] || return 1
  [[ "${c}" == "${SKIP_TARGET_COMMIT}" ]] && return 0
  git -C "${REPO_DIR}" merge-base --is-ancestor "${SKIP_TARGET_COMMIT}" "${c}" 2>/dev/null
}
# Does the secondary server on <host> still need the catch-up?
#
# The commit-level skip answers "are the FILES on that host current?"; the catch-up answers "is the
# RUNNING server current?". The registry records the commit a host was deployed at, and a deploy
# that synced the code under a lease is recorded at that commit too, so the commit-level skip alone
# dropped exactly the host whose secondary server still ran the old code (E64, 2026-10-24).
secondary_server_needs_catch_up() {
  local host="$1" seen
  is_secondary_server_host "${host}" || return 1
  seen="$(read_remote "${host}" "cat ~/${SERVER_CODE_MARKER} 2>/dev/null || true")"
  # An empty id means "we do not know what it runs": restart, never skip (E62's rule).
  [[ -z "${SERVER_CODE_ID}" || "${seen}" != "${SERVER_CODE_ID}" ]]
}
# The hosts the commit-level skip held back: their files are current, but a secondary server on
# them may still run the old code. The marker says what the RUNNING server was started with, so
# only that marker can settle it - and only the host loop can act on it. Called after the pull,
# when the server code id of the tree that is about to be pushed is known.
drop_current_hosts() {
  local host short="${SKIP_TARGET_COMMIT:0:10}"
  [[ ${#CURRENT_HOSTS[@]} -eq 0 ]] && return 0
  for host in "${CURRENT_HOSTS[@]}"; do
    target_is_current "${host}" || continue   # the registry says otherwise now: deploy it as usual
    if secondary_server_needs_catch_up "${host}"; then
      echo "already on ${short}: ${host} (secondary server catch-up still needed)"
    else
      echo "already on ${short}: ${host} (skipped)"
      HOST_IPS="$(host_list_filter "${HOST_IPS}" drop "${host}")"
      RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" drop "${host}")"
    fi
  done
  return 0
}
skip_current_targets() {
  ${FORCE_DEPLOY} && return 0
  ${REDEPLOY} && return 0
  ${RESTART_ONLY} && return 0
  ${BUNDLE_MODE} && return 0
  if ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS}; then return 0; fi
  local ref json rows k c
  ref="${DEPLOY_BRANCH:-$(git -C "${REPO_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)}"
  if [[ -z "${ref}" || "${ref}" == HEAD ]]; then skip_current_warn "no branch to resolve"; return 0; fi
  timeout 60 git -C "${REPO_DIR}" fetch -q origin 2>/dev/null || true
  SKIP_TARGET_COMMIT="$(git -C "${REPO_DIR}" rev-parse --verify -q "origin/${ref}^{commit}" 2>/dev/null || true)"
  if [[ -z "${SKIP_TARGET_COMMIT}" ]]; then skip_current_warn "cannot resolve origin/${ref}"; return 0; fi
  if ! json="$(lease_cmd deploy last --json 2>/dev/null)"; then skip_current_warn "registry read failed"; return 0; fi
  if ! rows="$(printf '%s' "${json}" | python3 -c '
import sys, json
env = sys.argv[1]
d = json.load(sys.stdin)
for k, v in ((d.get("envs") or {}).get(env) or {}).items():
    if isinstance(v, dict) and v.get("status") == "done" and v.get("commit"):
        print(k.lower(), v["commit"])
' "${LEASE_ENV}" 2>/dev/null)"; then skip_current_warn "registry answer unreadable"; return 0; fi
  DEPLOYED_COMMIT=()
  while read -r k c; do if [[ -n "${k}" ]]; then DEPLOYED_COMMIT["${k}"]="${c}"; fi; done <<< "${rows}"
  local short="${SKIP_TARGET_COMMIT:0:10}" h
  if ${DEPLOY_SERVER} && target_is_current server; then
    echo "already on ${short}: server (skipped)"; DEPLOY_SERVER=false
  fi
  if ${DEPLOY_FRONTEND} && target_is_current frontend; then
    echo "already on ${short}: frontend (skipped)"; DEPLOY_FRONTEND=false
  fi
  local -a dropped=() dropped_win=()
  if ${DEPLOY_HOSTS}; then
    for h in $(printf '%s,%s' "${HOST_IPS}" "${RUNNER_IPS}" | tr ',' ' '); do
      if target_is_current "${h}"; then
        # "already on <commit>" answers "are the FILES on that host current?". A secondary server
        # that still runs the old code is a different question ("is the RUNNING server current?"),
        # and only the host loop can settle it. Such a host is therefore NOT dropped here: the
        # decision needs the server code id, which is only known after the pull, and dropping it
        # made the catch-up unreachable for exactly the host it exists for (E64, 2026-10-24).
        if is_secondary_server_host "${h}"; then
          current_host_remember "${h}"
        else
          echo "already on ${short}: ${h} (skipped)"; dropped+=("${h}")
        fi
      fi
    done
    if (( ${#dropped[@]} > 0 )); then
      k="$(IFS=,; echo "${dropped[*]}")"
      HOST_IPS="$(host_list_filter "${HOST_IPS}" drop "${k}")"
      RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" drop "${k}")"
    fi
    if [[ -z "$(trim_host "${HOST_IPS}${RUNNER_IPS}")" ]]; then DEPLOY_HOSTS=false; fi
  fi
  if ${DEPLOY_HOSTS_WINDOWS}; then
    for h in $(printf '%s' "${HOST_WINDOWS_IPS}" | tr ',' ' '); do
      if target_is_current "${h}"; then echo "already on ${short}: ${h} (skipped)"; dropped_win+=("${h}"); fi
    done
    if (( ${#dropped_win[@]} > 0 )); then
      HOST_WINDOWS_IPS="$(host_list_filter "${HOST_WINDOWS_IPS}" drop "$(IFS=,; echo "${dropped_win[*]}")")"
    fi
    if [[ -z "$(trim_host "${HOST_WINDOWS_IPS//,/}")" ]]; then DEPLOY_HOSTS_WINDOWS=false; fi
  fi
  if ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${DEPLOY_HOSTS} && ! ${DEPLOY_HOSTS_WINDOWS}; then
    echo "nothing to deploy: every target already on ${short}"
    exit 0   # the EXIT trap (if a lease was claimed) releases only what this run claimed; a joined runner lease is the runner's
  fi
}
skip_current_targets
compute_lease_resources

# --skip-leased: ask the registry which of this run's named hosts another agent holds, drop them, and let
# the registry decide what still blocks (server: server leases anywhere + env-wide leases; host leases
# on a host do not). Hosts given by IP cannot be matched to a lease name: they count as '*' as before.
# the SERVER_IP entries after the first, as a comma list ("" when there are none)
SKIP_PLAN_ACTIVE=false
SKIP_PLAN_RC=0
SKIP_PLAN_OUT=""
plan_skip_leased() {
  local -a res=() cands=() lists=() items=()
  local list h line ag
  if ${DEPLOY_SERVER}; then res+=("$(server_resource)"); fi
  if ${DEPLOY_FRONTEND}; then res+=(frontend); fi
  if ${DEPLOY_HOSTS} || ${RESTART_ONLY:-false}; then lists+=("${HOST_IPS}" "${RUNNER_IPS}"); fi
  # (Windows hosts lease in ${WIN_LEASE_ENV}, claimed separately: not part of this env's plan)
  # secondary servers (vpt-pi1, vpt-pi4: the entries after the node's own server) run on a Pi that other agents lease;
  # a lease on that Pi drops its server from this run, and the catch-up host deploy restarts it later (TASK-129)
  if ${DEPLOY_SERVER}; then lists+=("$(server_secondary_names)"); fi
  for list in ${lists[@]+"${lists[@]}"}; do
    IFS=',' read -ra items <<< "${list}"
    for h in ${items[@]+"${items[@]}"}; do
      h="${h//[[:space:]]/}"
      [[ -z "${h}" ]] && continue
      if [[ "${h}" =~ ^[0-9.]+$ ]]; then local n; n="$(ip_host_name "${h}")"; if [[ -n "${n}" ]]; then cands+=("${n}"); else res+=('*'); fi; else cands+=("${h}"); fi
    done
  done
  SKIP_PLAN_RC=0
  SKIP_PLAN_OUT="$(lease_cmd check "${LEASE_ENV}" ${res[@]+"${res[@]}"} --skip-leased \
    --hosts "$(IFS=,; echo "${cands[*]-}")" --ignore-agent "${DEPLOY_AGENT}" 2>&1)" || SKIP_PLAN_RC=$?
  if (( SKIP_PLAN_RC == 127 )); then return 0; fi          # no registry: nothing to skip
  SKIP_PLAN_ACTIVE=true
  while IFS= read -r line; do
    if [[ "${line}" == "LEASED "* ]]; then
      read -r _ h ag <<< "${line}"
      SKIPPED_HOSTS+=("${h}"); SKIPPED_BY+=("${ag}")
    fi
  done <<< "${SKIP_PLAN_OUT}"
  if (( ${#SKIPPED_HOSTS[@]} > 0 )); then
    # a leased host of this run's host lists is synced without a lease and its restart deferred (sync_leased_host);
    # leased Windows hosts and secondary servers are dropped as before
    local joined all_joined; all_joined="$(IFS=,; echo "${SKIPPED_HOSTS[*]}")"
    local -a _keep_h=() _keep_by=(); local _i=0
    if ${DEPLOY_HOSTS}; then
      for h in "${SKIPPED_HOSTS[@]}"; do
        if [[ -n "$(host_list_filter "${HOST_IPS},${RUNNER_IPS}" keep "${h}")" ]]; then
          SYNC_LEASED+=("${h}"); SYNC_LEASED_BY+=("${SKIPPED_BY[$_i]}")
        else
          _keep_h+=("${h}"); _keep_by+=("${SKIPPED_BY[$_i]}")
        fi
        _i=$((_i+1))
      done
      SKIPPED_HOSTS=(${_keep_h[@]+"${_keep_h[@]}"}); SKIPPED_BY=(${_keep_by[@]+"${_keep_by[@]}"})
    fi
    joined="$(IFS=,; echo "${SKIPPED_HOSTS[*]-}")"
    HOST_IPS="$(host_list_filter "${HOST_IPS}" drop "${joined}")"
    RUNNER_IPS="$(host_list_filter "${RUNNER_IPS}" drop "${joined}")"
    HOST_WINDOWS_IPS="$(host_list_filter "${HOST_WINDOWS_IPS}" drop "${all_joined}")"
    SERVER_IP="$(host_list_filter "${SERVER_IP}" drop "${all_joined}")"
  fi
}
if ${SKIP_LEASED}; then
  plan_skip_leased
  if ${SKIP_PLAN_ACTIVE}; then
    # leased hosts are dropped even when the server part stays blocked: that run aborts or --force deploys the rest
    compute_lease_resources
    if (( ${#SKIPPED_HOSTS[@]} > 0 && ${#SYNC_LEASED[@]} == 0 )); then
      # nothing left to deploy (every host of a host-only run was leased): done, the runner queues the catch-up
      if ! ${DEPLOY_SERVER} && ! ${DEPLOY_FRONTEND} && ! ${RESTART_ONLY:-false} \
         && [[ -z "${HOST_IPS}${RUNNER_IPS}" ]] && { ! ${DEPLOY_HOSTS_WINDOWS} || [[ -z "${HOST_WINDOWS_IPS}" ]]; }; then
        i=0
        for h in "${SKIPPED_HOSTS[@]}"; do echo "SKIPPED (leased by ${SKIPPED_BY[$i]}): ${h}"; i=$((i+1)); done
        echo "Nothing left to deploy: every requested host is leased."
        emit_skipped_hosts
        exit 0
      fi
    fi
  fi
fi

echo -e "\n=== Lease check (${LEASE_ENV}: ${LEASE_RESOURCES[*]})$(${SKIP_PLAN_ACTIVE} && echo ' [skip-leased]') ==="
if ${SKIP_PLAN_ACTIVE}; then
  _i=0
  for h in ${SKIPPED_HOSTS[@]+"${SKIPPED_HOSTS[@]}"}; do echo "SKIPPED (leased by ${SKIPPED_BY[$_i]}): ${h}"; _i=$((_i+1)); done
  _i=0
  for h in ${SYNC_LEASED[@]+"${SYNC_LEASED[@]}"}; do echo "SYNC ONLY (leased by ${SYNC_LEASED_BY[$_i]}): ${h}: code is synced, vpt-host restart deferred if due"; _i=$((_i+1)); done
fi
lease_rc=0
lease_out=""
if ${SKIP_PLAN_ACTIVE}; then
  lease_rc=${SKIP_PLAN_RC}; lease_out="$(printf '%s\n' "${SKIP_PLAN_OUT}" | grep -v '^LEASED ' || true)"
fi
# Fail closed: only 0 (free / granted) goes ahead; busy (3), a pending deploy (4) and any other answer, including an
# unreachable or missing registry, stop the deploy. --force stays the explicit human override.
lease_abort() {
  [[ -n "${lease_out}" ]] && echo "${lease_out}"
  if ! ${FORCE_DEPLOY}; then echo "ABORT: $2"; exit "$1"; fi
  echo "--force: deploying anyway"
}
# 10-minute cap: called before each host/server step. Once the lease has expired in the registry other agents may start
# on the same env, so restarting more hosts without it would trample them: stop with a loud error (exit 6) instead. The
# step in flight is never cut; the unfinished hosts are listed so the operator reruns the deploy (it claims a new lease).
lease_expiry_guard() {   # $1 = the step about to run
  [[ -n "${LEASE_GRANTED_EPOCH}" ]] || return 0
  local held=$(( $(date +%s) - LEASE_GRANTED_EPOCH ))
  (( held > DEPLOY_LEASE_TTL_MIN * 60 )) || return 0
  echo "" >&2
  echo "!!! DEPLOY LEASE EXPIRED: held ${held}s, the cap is ${DEPLOY_LEASE_TTL_MIN} min. The lease is gone and other agents may now start on this env." >&2
  echo "!!! ABORT before ${1}: no more hosts are restarted without a lease. Hosts already done stay deployed; rerun the deploy to finish." >&2
  exit 6
}
# Busy means queue (round 13): the claim waits in the registry's queue (`vpt-lease claim --wait`, no polling) instead of
# exiting 3. VPT_DEPLOY_NO_QUEUE=1 restores the old fail-fast exit 3. A registry without --wait keeps exit 3.
QUEUE_WHEN_BUSY=true
[[ "${VPT_DEPLOY_NO_QUEUE:-}" == 1 ]] && QUEUE_WHEN_BUSY=false
${FORCE_DEPLOY} && QUEUE_WHEN_BUSY=false
# a legacy registry has no --wait: keep the fail-fast exit 3 there
${QUEUE_WHEN_BUSY} && ! lease_cmd claim --help 2>&1 | grep -q -- '--wait' && QUEUE_WHEN_BUSY=false
claim_lease() {   # one atomic claim: the registry checks and grants in one step (no check-then-claim gap)
  local err rc=0
  err="$(mktemp)"
  local out
  local -a waitflag=()
  ${QUEUE_WHEN_BUSY} && waitflag=(--wait)
  local -a kindflag=()
  [[ -z "${CLAIM_ENV:-}" ]] && kindflag=(${NODE_CLAIM_KIND[@]+"${NODE_CLAIM_KIND[@]}"})
  out="$(lease_cmd claim "${CLAIM_ENV:-${LEASE_ENV}}" "$@" ${kindflag[@]+"${kindflag[@]}"} --agent "${DEPLOY_AGENT}" \
    --purpose "update_core ${DEPLOY_BRANCH:-<current branch>}$(${SKIP_PLAN_ACTIVE} && echo ' (skip-leased)')" --ttl "${DEPLOY_LEASE_TTL_MIN}" ${waitflag[@]+"${waitflag[@]}"} 2>"${err}")" || rc=$?
  LEASE_ID="${out%%$'\n'*}"
  if [[ -z "${LEASE_ID}" ]] && (( rc == 0 )); then rc=1; fi
  if (( rc == 0 )) && [[ -z "${LEASE_GRANTED_EPOCH}" ]]; then LEASE_GRANTED_EPOCH="$(date +%s)"; fi
  lease_out="$(cat "${err}")"; rm -f "${err}"
  return "${rc}"
}
if ${FREE_RESTART}; then
  echo "restart of ${RESTART_SERVICE} only: no lease needed (background service, starts in seconds)"
elif ${NODE_CLAIM_SKIP}; then
  echo "Windows-only deploy: nothing to claim on ${LEASE_ENV}"
elif ${NO_CLAIM}; then
  echo "every requested host is leased by another agent: code is synced without a lease, vpt-host restarts are deferred to the catch-up deploy"
elif (( lease_rc == 3 )) && ! ${QUEUE_WHEN_BUSY}; then
  lease_abort 3 "agents are using ${LEASE_ENV}. Wait for them to release, or rerun with --force."
elif (( lease_rc != 0 )); then
  lease_abort 5 "the lease registry did not answer (rc=${lease_rc}): not deploying without a lease (fail closed)."
else
  [[ -n "${lease_out}" ]] && echo "${lease_out}"
  if (( lease_rc == 3 )); then echo "busy: queueing for the lease (vpt-lease claim --wait)"; fi
  claim_rc=0
  # Started by the deploy runner, which already holds this deploy's lease on the env and hands it over as VPT_LEASE_ID:
  # claiming again would queue this run behind the runner's own lease (self-deadlock). Join it when the registry confirms it
  # is held, exclusive and ours (`vpt-lease validate`); otherwise claim as usual (fail closed). The 10-minute cap is measured
  # from now. The runner owns the lease: it is not released on exit.
  if [[ -n "${VPT_LEASE_ID:-}" ]] && lease_cmd validate "${VPT_LEASE_ID}" --agent "${DEPLOY_AGENT}" >/dev/null 2>&1; then
    LEASE_ID="${VPT_LEASE_ID}"; JOINED_LEASE=true; LEASE_GRANTED_EPOCH="$(date +%s)"
  else
    [[ -n "${VPT_LEASE_ID:-}" ]] && echo "VPT_LEASE_ID ${VPT_LEASE_ID} is not valid for ${DEPLOY_AGENT}: claiming a lease of our own"
    claim_lease "${LEASE_RESOURCES[@]}" || claim_rc=$?
  fi
  if (( claim_rc != 0 )) && ${SKIP_PLAN_ACTIVE} && [[ " ${LEASE_RESOURCES[*]} " == *" * "* ]]; then
    # a host-kind lease elsewhere in the env stops us holding '*': hold what we can (named hosts, frontend)
    _hold=()
    for h in $(printf '%s,%s,%s' "${HOST_IPS}" "${RUNNER_IPS}" "${HOST_WINDOWS_IPS}" | tr ',' ' '); do
      is_sync_leased "${h}" && continue
      [[ "${h}" =~ ^[0-9.]+$ ]] || _hold+=("${h}")
    done
    ${DEPLOY_FRONTEND} && _hold+=(frontend)
    if (( ${#_hold[@]} > 0 )); then
      claim_rc=0
      claim_lease "${_hold[@]}" || claim_rc=$?
      LEASE_RESOURCES=("${_hold[@]}")
    fi
  fi
  if (( claim_rc == 0 )); then
    echo "holding lease ${LEASE_ID} on ${LEASE_ENV} (${LEASE_RESOURCES[*]}) for the deploy$(${JOINED_LEASE} && echo ' (joined: the deploy runner releases it)')"
    trap release_deploy_lease EXIT
  elif (( claim_rc == 3 || claim_rc == 4 )); then
    lease_abort 3 "the claim on ${LEASE_ENV} (${LEASE_RESOURCES[*]}) was refused: busy or a deploy is pending. Wait, or rerun with --force."
  else
    lease_abort 5 "the lease claim failed (rc=${claim_rc}): not deploying without a lease (fail closed)."
  fi
fi
# Windows hosts: their leases live in ${WIN_LEASE_ENV}; a restart there breaks only those. Same fail-closed rules.
if ${WIN_CLAIM} && ! ${FREE_RESTART}; then
  echo -e "\n=== Lease check (${WIN_LEASE_ENV}: *) ==="
  _node_lease_id="${LEASE_ID}"; CLAIM_ENV="${WIN_LEASE_ENV}"; win_rc=0
  VPT_DEPLOY_ID= claim_lease '*' || win_rc=$?   # fresh claim in another env: never join the node deploy (E_INVALID)
  WIN_LEASE_ID="${LEASE_ID}"; LEASE_ID="${_node_lease_id}"; CLAIM_ENV=""
  if (( win_rc == 0 )); then
    echo "holding lease ${WIN_LEASE_ID} on ${WIN_LEASE_ENV} (*) for the deploy"
    trap release_deploy_lease EXIT
  elif (( win_rc == 3 || win_rc == 4 )); then
    WIN_LEASE_ID=""; lease_abort 3 "the claim on ${WIN_LEASE_ENV} (*) was refused: busy or a deploy is pending. Wait, or rerun with --force."
  else
    WIN_LEASE_ID=""; lease_abort 5 "the lease claim on ${WIN_LEASE_ENV} failed (rc=${win_rc}): not deploying without a lease (fail closed)."
  fi
fi
# a waiter may have been overtaken while queued for the lease: check again, before any build or restart
if ! ${FREE_RESTART}; then skip_current_targets; fi
# skipped hosts are reported on the last line of output even when no lease was taken (the EXIT trap runs it)
if (( ${#SKIPPED_HOSTS[@]} + ${#SYNC_LEASED[@]} > 0 )) && [[ -z "$(trap -p EXIT)" ]]; then trap release_deploy_lease EXIT; fi

# ---- Restart-only mode: no git pull / no rsync, just restart aux services ----
if ${RESTART_ONLY}; then
  echo -e "\n=== Restart-only mode: ${RESTART_SERVICE:-all aux services} ==="
  echo -e "\n--- Host VMs ---"
  IFS=',' read -ra hosts <<< "${HOST_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    restart_aux_services "${host}"
  done

  echo -e "\n--- Runner VMs ---"
  IFS=',' read -ra hosts <<< "${RUNNER_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
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

# ---- Deploy ledger: record what this run deployed, PER TARGET ----
# Past this point a real deploy is under way. On exit (any path, incl. set -e) the shared registry gets one
# `deploy record`: env, scope, hosts, ref, commit, version, agent. A target that deployed is recorded done, a
# target that failed is recorded failed (--fail-targets) — one unreachable host must not mark the server, the
# frontend and every other host failed. Targets never attempted (the run stopped early) and hosts skipped
# because they were leased (--skipped-hosts, audit only) are left out. With no per-target information at all
# (died before any target ran) every intended target is recorded failed, as before.
# It must never fail or slow the deploy: every error is swallowed and the call is time-boxed.
# VPT_DEPLOY_ID (set by the queue runner) is forwarded so the same run is recorded once.
DEPLOY_T0="$(date +%s)"
record_deploy_ledger() {
  local rc="$1" scope="" hosts="" ref commit version status="done" note="" fail_targets="" skipped=""
  local -a targets=() ok_hosts=() fail_hosts=() all_hosts=() ftl=()
  local e role h server_seen=false fe_seen=false server_fail=false fe_fail=false
  for e in ${DEPLOY_OK_ROLE[@]+"${DEPLOY_OK_ROLE[@]}"}; do
    role="${e%%:*}"; h="${e#*:}"
    case "${role}" in server) server_seen=true ;; frontend) fe_seen=true ;; *) ok_hosts+=("${h}") ;; esac
  done
  for e in ${DEPLOY_FAIL_ROLE[@]+"${DEPLOY_FAIL_ROLE[@]}"}; do
    role="${e%%:*}"; h="${e#*:}"
    case "${role}" in
      server) server_seen=true; server_fail=true ;;
      frontend) fe_seen=true; fe_fail=true ;;
      *) fail_hosts+=("${h}") ;;
    esac
  done
  if (( ${#DEPLOY_OK_ROLE[@]} + ${#DEPLOY_FAIL_ROLE[@]} == 0 )); then
    # nothing was attempted/tracked: the intended targets, all failed if the run failed
    ${DEPLOY_SERVER} && targets+=(server)
    ${DEPLOY_FRONTEND} && targets+=(frontend)
    { ${DEPLOY_HOSTS} || ${DEPLOY_HOSTS_WINDOWS}; } && targets+=(host)
    [[ ${#targets[@]} -eq 0 ]] && return 0
    if ${DEPLOY_HOSTS}; then hosts="${HOST_IPS},${RUNNER_IPS}"; fi
    if ${DEPLOY_HOSTS_WINDOWS}; then hosts="${hosts},${HOST_WINDOWS_IPS}"; fi
    if (( rc != 0 )); then status="failed"; note="exit ${rc}"; fi
  else
    ${server_seen} && targets+=(server)
    ${fe_seen} && targets+=(frontend)
    all_hosts=(${ok_hosts[@]+"${ok_hosts[@]}"} ${fail_hosts[@]+"${fail_hosts[@]}"})
    (( ${#all_hosts[@]} > 0 )) && targets+=(host)
    hosts="$(IFS=,; echo "${all_hosts[*]-}")"
    ${server_fail} && ftl+=(server)
    ${fe_fail} && ftl+=(frontend)
    ftl+=(${fail_hosts[@]+"${fail_hosts[@]}"})
    if (( ${#ftl[@]} > 0 )); then
      status="failed"; fail_targets="$(IFS=,; echo "${ftl[*]}")"; note="failed: ${ftl[*]}"
    elif (( rc != 0 )); then
      note="exit ${rc} (every attempted target deployed)"
    fi
  fi
  scope="$(IFS=,; echo "${targets[*]}")"
  hosts="$(printf '%s' "${hosts}" | tr -d ' ' | sed 's/,,*/,/g; s/^,//; s/,$//')"
  if (( ${#SKIPPED_HOSTS[@]} > 0 )); then skipped="$(IFS=,; echo "${SKIPPED_HOSTS[*]}")"; fi
  _l=""; for _h in ${SKIPPED_HOSTS[@]+"${SKIPPED_HOSTS[@]}"}; do [[ " ${DEFERRED_RESTARTS[*]-} " == *" ${_h} "* ]] || _l="${_l:+${_l},}${_h}"; done
  if [[ -n "${_l}" ]]; then note="${note:+${note}; }skipped (leased): ${_l}"; fi
  _l="$(IFS=,; echo "${DEFERRED_RESTARTS[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }code synced, vpt-host restart deferred until the lease is released or the running execution ends (catch-up queued): ${_l}"; fi
  _l="$(IFS=,; echo "${DOWN_SKIPPED[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }skipped (down): ${_l}"; fi
  _l="$(IFS=,; echo "${PINNED_SKIPPED[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }skipped (pinned): ${_l}"; fi
  _l="$(IFS=,; echo "${UNREACHABLE_SKIPPED[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }skipped (unreachable): ${_l}"; fi
  _l="$(IFS=,; echo "${HOST_RESTART_SKIPPED[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }no restart (host code unchanged): ${_l}"; fi
  _l="$(IFS=,; echo "${DROPPED_HOSTS[*]-}")"; if [[ -n "${_l}" ]]; then note="${note:+${note}; }dropped (unknown host): ${_l}"; fi
  ref="${DEPLOY_BRANCH:-$(git -C "${REPO_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)}"
  commit="$(git -C "${REPO_DIR}" rev-parse HEAD 2>/dev/null || true)"
  version="$(head -n 1 "${REPO_DIR}/VERSION.txt" 2>/dev/null | tr -d '\r' | sed 's/^current://' || true)"
  # A ledger row with an empty commit or an empty version cannot be audited: there is
  # nothing to compare a running build against, and an empty string reads like "not
  # recorded" instead of "not resolved". Record `unknown` and say why in the note, so an
  # unauditable row is visible as such (TASK-170: labox-mobile carried commit="" and
  # version="" from a deploy on 2026-10-20).
  # The commit is checked by its shape, not by its emptiness: `git rev-parse HEAD` in a
  # repo that has no commit yet prints "HEAD" and exits non-zero, so an empty check
  # would let that through as if it were a sha.
  if [[ ! "${commit}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; then
    commit="unknown"
    note="${note:+${note}; }commit unresolved (git rev-parse HEAD failed)"
  fi
  if [[ -z "${version}" ]]; then
    version="unknown"
    note="${note:+${note}; }version unresolved (VERSION.txt empty or missing)"
  fi
  local -a args=(deploy record "${LEASE_ENV}" --scope "${scope}" --ref "${ref}" --commit "${commit}"
    --version "${version}" --agent "${DEPLOY_AGENT}" --status "${status}" --started "${DEPLOY_T0}")
  [[ -n "${hosts}" ]] && args+=(--hosts "${hosts}")
  [[ -n "${fail_targets}" ]] && args+=(--fail-targets "${fail_targets}")
  [[ -n "${skipped}" ]] && args+=(--skipped-hosts "${skipped}")
  [[ -n "${note}" ]] && args+=(--note "${note}")
  [[ -n "${VPT_DEPLOY_ID:-}" ]] && args+=(--deploy-id "${VPT_DEPLOY_ID}")
  LEASE_REGISTRY_HOST="${LEASE_REGISTRY_HOST}" timeout 30 bash -c "$(declare -f lease_cmd); lease_cmd \"\$@\"" _ "${args[@]}" \
    >/dev/null 2>&1 || true
}
deploy_exit_hook() {
  local rc=$?
  trap - EXIT
  release_deploy_lease || true
  record_deploy_ledger "${rc}" || true
  exit "${rc}"
}
trap deploy_exit_hook EXIT

# Hosts the lease check dropped: one event each, so their cards show "skipped" and not "never ran".
_i=0
for h in ${SKIPPED_HOSTS[@]+"${SKIPPED_HOSTS[@]}"}; do
  progress "${h}" rsync skipped "leased by ${SKIPPED_BY[$_i]}"; _i=$((_i+1))
done

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

# The code ids describe the tree that is about to be PUSHED, so they must be computed
# AFTER the pull. Computed before it, they described the tree of the PREVIOUS deploy,
# and the "is the host code unchanged since the last restart?" check compared that
# with a marker written the same way - so it compared the deploy before last with the
# one before it. A deploy that changed host code (backend_host/, shared/, features/)
# then pushed the new code but did NOT restart vpt-host, and the host kept running
# the previous code until something else restarted it (2026-10-20, TASK-146).
compute_host_code_id
compute_server_code_id

# The hosts whose files are already on the requested commit are settled now: the server code id
# of the tree that is about to be pushed is known, so the marker on each of them says whether its
# secondary server still runs the old code (E64, 2026-10-24).
drop_current_hosts

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
if ${DEPLOY_SERVER}; then
  DEPLOY_PHASE=server; echo -e "\n--- Server ---"
  IFS=',' read -ra hosts <<< "${SERVER_IP}"
  # The first entry is the node's own server: a failure there stops the deploy (set -e). Later
  # entries are secondary servers on remote boxes (vpt-pi1, vpt-pi4) and are best-effort like
  # hosts: one being offline must not stop the frontend and the hosts from deploying.
  primary_server=true
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    if ${primary_server}; then
      primary_server=false
      critical_deploy "${host}" "${SERVER_SERVICE}"
    elif ! try_deploy "${host}" "${SERVER_SERVICE}"; then
      continue
    fi
    restart_aux_services "${host}" "${SERVER_AUX_SERVICES[@]}"
  done
fi

if ${DEPLOY_FRONTEND}; then
  DEPLOY_PHASE=frontend; echo -e "\n--- Frontend ---"
  IFS=',' read -ra hosts <<< "${FRONTEND_IP}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    frontend_deploy "${host}"
  done
fi

if ${DEPLOY_HOSTS}; then
  DEPLOY_PHASE=host; echo -e "\n--- Host VMs ---"
  IFS=',' read -ra hosts <<< "${HOST_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    deploy_host_target "${host}"
  done

  echo -e "\n--- Runner VMs ---"
  IFS=',' read -ra hosts <<< "${RUNNER_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    deploy_host_target "${host}"
  done
fi

DOCKER_SERVICES=""
if ${DEPLOY_SERVER}; then DOCKER_SERVICES="${DOCKER_SERVICES} backend_server"; fi
if ${DEPLOY_FRONTEND}; then DOCKER_SERVICES="${DOCKER_SERVICES} frontend"; fi
if ${DEPLOY_HOSTS}; then DOCKER_SERVICES="${DOCKER_SERVICES} backend_host"; fi
DOCKER_STARTED=(); DOCKER_FAIL=()
if [[ -n "${DOCKER_IPS}" && -n "${DOCKER_SERVICES}" ]]; then
  echo -e "\n--- Docker stacks (${DOCKER_SERVICES# }) ---"
  PROGRESS_ROLE=docker
  IFS=',' read -ra hosts <<< "${DOCKER_IPS}"
  for host in "${hosts[@]}"; do
    host="$(trim_host "${host}")"
    [[ -z "${host}" ]] && continue
    lease_expiry_guard "${host}"
    if docker_deploy "${host}" ${DOCKER_SERVICES}; then DOCKER_STARTED+=("${host}"); else DOCKER_FAIL+=("${host}"); fi
  done
fi

if ${DEPLOY_HOSTS_WINDOWS}; then
  if [[ -n "${HOST_WINDOWS_IPS}" ]]; then
    echo -e "\n--- Windows Host VMs ---"
    PROGRESS_ROLE=windows
    IFS=',' read -ra hosts <<< "${HOST_WINDOWS_IPS}"
    for host in "${hosts[@]}"; do
      host="$(trim_host "${host}")"
      [[ -z "${host}" ]] && continue
      lease_expiry_guard "${host}"
      try_deploy_windows "${host}"
    done
  else
    echo -e "\n--- Windows Host VMs --- (none configured, skipping)"
  fi
fi

# ---- Summary ----
echo -e "\n========== DEPLOY SUMMARY =========="
# A host whose code was synced but whose restart was deferred is NOT ok: its service still runs the old
# code until the catch-up deploy restarts it. DEPLOY_OK keeps that host - the per-target ledger needs it
# (record_deploy_ledger), and dropping it there would make the ledger report every target as failed - so
# the list below is computed for the DISPLAY only. DEPLOY_OK and DEPLOY_OK_ROLE stay untouched.
_ok_list=""; _ok_count=0
for _ok_h in ${DEPLOY_OK[@]+"${DEPLOY_OK[@]}"}; do
  [[ " ${DEFERRED_RESTARTS[*]-} " == *" ${_ok_h} "* ]] && continue
  _ok_list+="${_ok_list:+ }${_ok_h}"; _ok_count=$((_ok_count+1))
done
if (( _ok_count > 0 )); then
  echo -e "  OK (${_ok_count}):     ${_ok_list}"
fi
if [[ ${#DEPLOY_FAIL[@]} -gt 0 ]]; then
  echo -e "  FAILED (${#DEPLOY_FAIL[@]}): ${DEPLOY_FAIL[*]}"
fi
# ---- Summary: every host that did NOT get the code ----
# The per-host "SKIPPED (...)" lines scroll off during a long run, so the summary repeats them.
# A summary that lists OK and nothing else hides exactly the hosts that silently kept old code.
# None of this is a failure: that is the whole point of skipping them (see plan_down_and_unreachable).
_sk_line() {   # <label> <space-joined hosts>; prints nothing when the list is empty
  if [[ -n "$2" ]]; then printf '     %-27s %s\n' "$1:" "$2"; fi
  return 0
}
# Every host lands in exactly one row: DEFERRED_RESTARTS is the authoritative "synced, restart deferred"
# set (a leased host whose code changed, or a host with a running execution), so those hosts are listed
# as deferred and NOT under OK; SKIPPED_HOSTS alone holds the hosts that were dropped without a deploy.
_sk_who() {   # <host>: who holds it (or why it was skipped)
  local h="$1" i=0 x
  for x in ${SKIPPED_HOSTS[@]+"${SKIPPED_HOSTS[@]}"}; do
    if [[ "${x}" == "${h}" ]]; then printf '%s' "${SKIPPED_BY[$i]:-another agent}"; return 0; fi
    i=$((i+1))
  done
  printf 'another agent'
}
_sk_leased=""; _sk_leased_n=0; _sk_i=0
for _sk_h in ${SKIPPED_HOSTS[@]+"${SKIPPED_HOSTS[@]}"}; do
  if [[ " ${DEFERRED_RESTARTS[*]-} " != *" ${_sk_h} "* ]]; then
    _sk_leased+="${_sk_leased:+ }${_sk_h} (by ${SKIPPED_BY[_sk_i]:-another agent})"; _sk_leased_n=$((_sk_leased_n+1))
  fi
  _sk_i=$((_sk_i+1))
done
_sk_defer=""; _sk_defer_n=0
for _sk_h in ${DEFERRED_RESTARTS[@]+"${DEFERRED_RESTARTS[@]}"}; do
  _sk_defer+="${_sk_defer:+ }${_sk_h} (by $(_sk_who "${_sk_h}"))"; _sk_defer_n=$((_sk_defer_n+1))
done
_sk_down="${DOWN_SKIPPED[*]-}"; _sk_pin="${PINNED_SKIPPED[*]-}"; _sk_unr="${UNREACHABLE_SKIPPED[*]-}"
_sk_total=$(( ${#DOWN_SKIPPED[@]} + ${#PINNED_SKIPPED[@]} + ${#UNREACHABLE_SKIPPED[@]} + _sk_leased_n + _sk_defer_n ))
if (( _sk_total > 0 )); then
  echo -e "  SKIPPED (${_sk_total}, nothing failed):"
  _sk_line "down on purpose"         "${_sk_down}"
  _sk_line "unreachable, no ssh"      "${_sk_unr}"
  _sk_line "pinned, use --hosts"      "${_sk_pin}"
  _sk_line "leased, catch-up queued"  "${_sk_leased}"
  _sk_line "synced, restart deferred" "${_sk_defer}"
fi
if [[ -n "${HOST_RESTART_SKIPPED[*]-}" ]]; then
  _sk_line "not restarted (same code)" "${HOST_RESTART_SKIPPED[*]-}"
fi
# What the catch-up did for each secondary server it reached. It used to say nothing at all, so
# "OK (1): <pi>" read like a deliberate skip rather than a check that never ran.
if [[ -n "${SECONDARY_CATCHUP[*]-}" ]]; then
  echo -e "  SECONDARY SERVER (catch-up): ${SECONDARY_CATCHUP[*]-}"
fi
if [[ ${#DOCKER_STARTED[@]} -gt 0 ]]; then
  echo -e "  DOCKER BUILD STARTED (${#DOCKER_STARTED[@]}): ${DOCKER_STARTED[*]}  (log there: ~/build-logs/update_core-<version>.log)"
fi
if [[ ${#DOCKER_FAIL[@]} -gt 0 ]]; then
  echo -e "  DOCKER FAILED (${#DOCKER_FAIL[@]}): ${DOCKER_FAIL[*]}  (deploy not failed)"
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

# ---- Services still running the previous code (non-blocking) ----
# The aux services are restarted only with --restart; an ordinary deploy leaves them on the
# code they were started with, and the marker cannot see that. Say it once more, in the
# summary, so it is not lost in the deploy output.
if [[ ${#STALE_AUX_SERVICES[@]} -gt 0 ]]; then
  echo -e "\n======= STILL RUNNING THE PREVIOUS CODE ======="
  for entry in "${STALE_AUX_SERVICES[@]}"; do
    echo "  ${entry}"
  done
  echo "  (the deploy pushed the new code to the disk; these services keep the code they were"
  echo "   started with until they are restarted. Restart them under the lease when it is free."
  echo "   A deploy with --restart restarts them all.)"
  echo "===================================================="
fi

if [[ ${#DEPLOY_FAIL[@]} -gt 0 ]]; then
  echo -e "\nDone (with failures)."
else
  echo -e "\nDone."
fi
