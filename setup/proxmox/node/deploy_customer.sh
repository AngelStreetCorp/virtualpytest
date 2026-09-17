#!/usr/bin/env bash
# deploy_customer.sh — layered customer deploy (docs/tasks/TASK-01-*.md, step 4)
#
#   staged tree = public core @ PIN  −  features/<DISABLED_FEATURES>  +  customer overlay
#   then rsync --delete the staged tree to every TARGET and restart services, exactly
#   like the canonical ~/update_core.sh on proxmox (helpers mirrored from it).
#   On host targets the feature systemd units (features/*/backend_host/services) are
#   reconciled after the push: re-rendered + enabled + restarted when changed/missing,
#   disabled + removed when their feature is disabled/removed (DEPLOY_CUSTOMER.md,
#   "Feature systemd units"). Core units are never touched.
#
# Usage:
#   deploy_customer.sh [overlay_dir] [--pin <ref>] [--disabled-features a,b]
#                      [--targets role:alias,...] [--dry-run] [--stage-only]
#                      [--no-checkout] [--restart [service]] [--keep-stage]
#
#   [overlay_dir]   clone of a customer overlay repo (holds customer.conf). Without it
#                   the PURE PLATFORM is deployed (no overlay rsync, version identity =
#                   core value alone); PIN/DISABLED_FEATURES/TARGETS then come from the
#                   flags below or from the deploy host's ~/deploy.local.conf.
#   --pin <ref>     public git ref to deploy (overrides the conf files)
#   --disabled-features a,b  features NOT deployed (overrides the conf files)
#   --targets       role:alias[:target_dir[:service]],... (overrides the conf files)
#   --dry-run       per target: print rsync's itemized change list (rsync -n -i), copy
#                   nothing, restart nothing
#   --stage-only    build the staged tree and stop (prints its path; no ssh at all)
#   --no-checkout   do not fetch/checkout PIN, use REPO_DIR's working tree as is
#                   (local proofs / already-checked-out pin)
#   --restart [svc] after a host deploy also restart aux services (all, or one) —
#                   opt-in, mirrors update_core.sh
#   --keep-stage    do not delete the temp staged tree at exit
#
# Conf files (KEY=VALUE, '#' comments; keys PIN / DISABLED_FEATURES / TARGETS):
#   PIN=<tag|branch|sha>           public git ref to deploy
#   DISABLED_FEATURES=a,b          features/<name> folders NOT deployed (deny-list)
#   TARGETS=role:alias[:target_dir[:service]],...
#                                  role = server|frontend|host|windows; bare alias = host;
#                                  target_dir (absolute) and service default to TARGET_DIR
#                                  and the role's unit (vpt-server / vpt-frontend-prod /
#                                  vpt-host) — set them to run a 2nd instance on one VM,
#                                  e.g. frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo
#                                  windows: alias only. empty (and no --targets) => refuse
#   WITH an overlay:  <overlay_dir>/customer.conf, overridden key by key by
#                     <overlay_dir>/customer.local.conf (git-ignored; keeps TARGETS =
#                     internal addresses out of a publishable overlay).
#   WITHOUT overlay:  ~/deploy.local.conf on the deploy host ($DEPLOY_LOCAL_CONF).
#   CLI flags override the conf files in both modes. The banner prints where each
#   value came from.
#
# An overlay ships frontend/.env.production (VITE_* branding/navigation) — NEVER
#   frontend/.env (the VM's own environment URLs/tokens): staging refuses any .env file
#   found in the overlay. Same safety rules in both modes: backend .env never touched,
#   frontend/.env never pushed, feature units reconciled, frontend/.env.local generated.
#
# Environment overrides: REPO_DIR (public checkout, default ~/virtualpytest),
#   STAGE_DIR (default mktemp; honoured as is, never deleted), DEPLOY_LOCAL_CONF, SSH_KEY,
#   SSH_USER, SYNC_USER, TARGET_DIR. Needs lib/feature_units.sh next to it (or in REPO_DIR).
#   Offline customers: build_customer_bundle.sh wraps --stage-only into a tar.gz.
#
# Never defaults to any host: the target list comes only from the conf files / --targets.
set -euo pipefail

# ---- Internal config (same values as the canonical update_core.sh) ----
SSH_USER="${SSH_USER:-$(id -un)}"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_ed25519}"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=accept-new"
SYNC_USER="${SYNC_USER:-vpt_user}"
REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"
TARGET_DIR="${TARGET_DIR:-/opt/virtualpytest}"
TARGET_DIR_WINDOWS="/cygdrive/c/virtualpytest/virtualpytest"
SERVER_SERVICE="vpt-server.service"
FRONTEND_SERVICE="vpt-frontend-prod.service"
HOST_SERVICE="vpt-host.service"
WINDOWS_TASK="vpt-host"

# Aux long-running services restarted after vpt-host on each host, ONLY if already
# active there, and only with --restart. Best-effort, never aborts the deploy.
AUX_SERVICES=(
  vpt-stream
  vpt-monitor
  vpt-subtitle
  vpt-transcript
  vpt-archiver
  vpt-avq
  vpt-kpi
)

# Rsync excludes — verbatim from the canonical update_core.sh (single source of truth
# there; keep in sync), plus ONE addition of this script (frontend/.env.production, marked
# below). Applied when staging core, when staging the overlay (minus the
# FRONTEND_CONFIG_PATHS includes below) and again on the push (via push_filters) so
# --delete never touches receiver-side .env / venv / node_modules / dist / branding.
# '.env' has no '/' and no wildcard, so rsync matches the exact basename only:
# frontend/.env.production and the generated frontend/.env.local are NOT matched by it.
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
  --exclude='docs/tasks'                # internal-only (BUG-0088): other customers' runbooks,
  --exclude='docs/agent'                # pentest write-ups, lab layout — never on a customer host
  --exclude='docs/security/*.json'
  --exclude='.claude'
  --exclude='tests/backend_server/.env.test.jwt'
  --exclude='backend_host/config/user_data'
  --exclude='backend_host/config/webkit_user_data'
  --exclude='frontend/.env.production'   # deploy_customer.sh addition (overlay-owned, FRONTEND_CONFIG_PATHS)
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

# Overlay-repo housekeeping files that must never land on a host (anchored at the
# overlay root). customer.local.conf holds the internal target addresses; .gitignore,
# .githooks and bump_version.sh are the overlay repo's own versioning tooling (a deployed
# tree has no git) and would otherwise shadow the platform's copies.
OVERLAY_EXCLUDES=(
  --exclude='/.git'
  --exclude='/.gitignore'
  --exclude='/.githooks'
  --exclude='/scripts/bump_version.sh'
  --exclude='/customer.conf'
  --exclude='/customer.local.conf'
  --exclude='/customer.local.conf.example'
  --exclude='/README.md'
  --exclude='/OVERRIDES.md'
  --exclude='/deliveries'    # our record of what was delivered when, not part of the tree
  --exclude='/VERSION.txt'   # merged into the staged core VERSION.txt (write_version_identity)
)

# Filled at runtime from scripts/disabled_features_excludes.sh (one --exclude per
# disabled feature). Used ONLY while staging: the push must NOT carry them, otherwise
# --delete would leave a previously deployed features/<name>/ behind on the host.
FEATURE_EXCLUDES=()

# ---- Frontend config from the overlay ----
# NON-SECRET frontend configuration the customer overlay is the source of truth for
# (DEPLOY_CUSTOMER.md "Customer frontend configuration"; every VITE_* value ends up in
# the public bundle anyway). Each path is matched by one of the RSYNC_EXCLUDES above,
# which is what we want when staging CORE (a dev checkout's own copy never leaks). For
# the OVERLAY and the PUSH the matching entries are re-included first — rsync filter
# rules are first-match, so an anchored --include='/frontend/.env.production' placed
# BEFORE the excludes lets exactly that path through:
#   - staging overlay: include what the OVERLAY has;
#   - push:            include what the STAGE has (= what the overlay shipped), so with
#                      --delete the target gets the overlay copy; what the stage does NOT
#                      have stays excluded and the target's hand-placed copy survives.
# frontend/.env is NOT in this list and is never included anywhere (incident 2026-09-02:
# an overlay carrying frontend/.env replaced the demo VM's hand-placed env). It is the
# VM's own file (environment URLs, tokens — never in git); the overlay ships
# frontend/.env.production, which Vite layers on top of it at build time. Every .env
# (root, backend_server, backend_host/src, frontend, ...) stays behind --exclude='.env'
# on all three rsyncs, so --delete never touches it either.
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

# frontend_config_includes <root>: one line per rsync --include for every
# FRONTEND_CONFIG_PATHS entry that exists under <root> (anchored with a leading '/';
# directories get a second '/<path>/**' rule so their content passes too).
frontend_config_includes() {
  local root="$1" p
  for p in "${FRONTEND_CONFIG_PATHS[@]}"; do
    [[ -e "${root}/${p}" ]] || continue
    printf -- '--include=/%s\n' "${p}"
    [[ -d "${root}/${p}" ]] && printf -- '--include=/%s/**\n' "${p}"
  done
  return 0
}

# frontend_config_report <root>: "frontend config from overlay: .env.production yes, ..." (one line).
frontend_config_report() {
  local root="$1" p label out=""
  for p in "${FRONTEND_CONFIG_PATHS[@]}"; do
    case "${p}" in
      frontend/.env.production)        label=".env.production" ;;
      frontend/vite.config.local.json) label="vite.config.local.json" ;;
      frontend/public/branding.json)   label="branding.json" ;;
      frontend/public/brand)           label="brand/" ;;
      frontend/public/favicon.ico)     label="favicon" ;;
      frontend/public/logo.png)        label="logo" ;;
      frontend/public/data/script_identity_map.json)   label="script map (frontend)" ;;
      frontend/public/data/campaign_identity_map.json) label="campaign map (frontend)" ;;
      test_scripts/script_identity_map.json)           label="script map (server)" ;;
      test_scripts/campaign_identity_map.json)         label="campaign map (server)" ;;
      *)                               label="${p}" ;;
    esac
    if [[ -e "${root}/${p}" ]]; then out+="${label} yes, "; else out+="${label} no, "; fi
  done
  printf 'frontend config from overlay: %s\n' "${out%, }"
}

# PUSH_FILTERS: the rsync filter list of every push (all roles) = includes for the
# frontend config the STAGE carries + the canonical RSYNC_EXCLUDES. Computed once the
# stage is built (push_filters); never contains FEATURE_EXCLUDES (see above).
PUSH_FILTERS=()
push_filters() {
  PUSH_FILTERS=()
  local line
  while IFS= read -r line; do
    [[ -n "${line}" ]] && PUSH_FILTERS+=("${line}")
  done < <(frontend_config_includes "${STAGE_DIR}")
  PUSH_FILTERS+=("${RSYNC_EXCLUDES[@]}")
}
# ---- End frontend config from the overlay ----

# ---- Version identity ----
# The deployed tree identifies itself as <platform>/<config>, e.g.
# main-2026.09.02-8549/prod-2026.09.02-8553: the public core version (staged VERSION.txt
# = the tree at PIN, its `current:` value) + the overlay's own VERSION.txt `current:`
# value (same scheme, bumped by the same pre-commit hook on the overlay repo's branch
# prod). Written into the STAGED VERSION.txt only — never into any repo: the
# pre-commit hook (scripts/bump_version.sh) would MISPARSE it (its branch group accepts
# '/', so it would read build 8553 from the overlay half and continue the core counter
# from there); the hook only runs from git hooks, which never fire on a deployed tree.
# `current:` stays the FIRST line so every
# reader keeps working unchanged: frontend Footer.tsx (/version.txt, `current:` line),
# vite.config.ts (__APP_VERSION__ at build time), the host ping (`deployed_version` =
# first line of VERSION.txt, backend_host host_utils.py), backend_server
# server_system_routes.py, the fleet health report (scripts/fleet_health_report.py).
# An overlay without VERSION.txt (demo) keeps the core value alone.
DEPLOY_VERSION="unknown"

# version_field <file> <key>: value of the first "<key>:" line, trimmed ('' when absent).
version_field() {
  local f="$1" key="$2" line
  [[ -f "${f}" ]] || return 0
  line="$(grep -m1 -E "^${key}:" "${f}" | tr -d '\r' || true)"
  [[ -n "${line}" ]] && trim "${line#"${key}":}"
  return 0
}

# write_version_identity: rewrite ${STAGE_DIR}/VERSION.txt as
#   current:<core current>/<overlay current>
#   previous:<core previous>
#   overlay_previous:<overlay previous>     (only when the overlay has one)
#   core_ref:<PIN> <core sha>
#   overlay_ref:<overlay branch> <overlay sha>   (only with an overlay)
# and set DEPLOY_VERSION. Must run while PIN is still checked out in REPO_DIR.
# Without an overlay (pure platform) the identity is the core value alone.
write_version_identity() {
  local staged="${STAGE_DIR}/VERSION.txt" overlay_vf="${OVERLAY_DIR:+${OVERLAY_DIR}/VERSION.txt}"
  local core_cur core_prev ov_cur="" ov_prev="" core_sha ov_branch="" ov_sha=""
  core_cur="$(version_field "${staged}" current)"
  if [[ -z "${core_cur}" ]]; then
    echo "WARNING: no current: line in the staged VERSION.txt -> version identity not written (hosts will report 'unknown')"
    return 0
  fi
  core_prev="$(version_field "${staged}" previous)"
  core_sha="$(git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if [[ -n "${OVERLAY_DIR}" ]]; then
    ov_cur="$(version_field "${overlay_vf}" current)"
    ov_prev="$(version_field "${overlay_vf}" previous)"
    ov_branch="$(git -C "${OVERLAY_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    ov_sha="$(git -C "${OVERLAY_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
  if [[ -n "${ov_cur}" ]]; then
    DEPLOY_VERSION="${core_cur}/${ov_cur}"
  elif [[ -n "${OVERLAY_DIR}" ]]; then
    DEPLOY_VERSION="${core_cur}"
    echo "overlay has no VERSION.txt -> version identity = core value alone"
  else
    DEPLOY_VERSION="${core_cur}"
    echo "no overlay -> version identity = core value alone"
  fi
  {
    printf 'current:%s\n' "${DEPLOY_VERSION}"
    [[ -n "${core_prev}" ]] && printf 'previous:%s\n' "${core_prev}"
    [[ -n "${ov_prev}" ]] && printf 'overlay_previous:%s\n' "${ov_prev}"
    printf 'core_ref:%s %s\n' "${PIN}" "${core_sha}"
    [[ -n "${OVERLAY_DIR}" ]] && printf 'overlay_ref:%s %s\n' "${ov_branch}" "${ov_sha}"
  } > "${staged}"
  if [[ -n "${OVERLAY_DIR}" ]]; then
    echo "version: ${DEPLOY_VERSION}  (core ${PIN} @ ${core_sha}, overlay ${ov_branch} @ ${ov_sha})"
  else
    echo "version: ${DEPLOY_VERSION}  (core ${PIN} @ ${core_sha}, no overlay)"
  fi
}
# ---- End version identity ----

# ---- Helpers (mirrored from update_core.sh) ----
is_ipv4_target() {
  local target="$1"
  [[ "${target}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

build_ssh_target() {
  local target="$1"
  if [[ "${target}" == *"@"* ]]; then printf '%s\n' "${target}"; return; fi
  if is_ipv4_target "${target}"; then printf '%s@%s\n' "${SSH_USER}" "${target}"; return; fi
  # SSH aliases / hostnames as-is so ~/.ssh/config can define user/port/jump host.
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

# "host : svc1, svc2" per host whose aux restart failed (plain array: the canonical
# script uses an associative array, which bash 3.2 on macOS cannot parse).
AUX_RESTART_FAIL=()
RESTART_SERVICE=""

restart_aux_services() {
  local host="$1"
  local services=("${AUX_SERVICES[@]}")
  # + every enabled feature unit shipped by the stage (deduped; template units excluded)
  local feature unit tpl
  while IFS=$'\t' read -r feature unit tpl; do
    [[ -n "${unit}" && "${unit}" != *@ ]] || continue
    [[ " ${services[*]} " == *" vpt-${unit} "* ]] || services+=("vpt-${unit}")
  done <<< "${STAGED_FEATURE_UNITS:-}"
  if [[ -n "${RESTART_SERVICE}" ]]; then
    services=("${RESTART_SERVICE}")
  fi
  echo -e "\n==> [${host}] Restarting aux services (only those already active): ${services[*]}"
  local failed=()
  local svc
  for svc in "${services[@]}"; do
    if [[ " ${FEATURE_RESTART_UNITS[*]:-} " == *" ${svc}.service "* ]]; then
      echo "==> [${host}] ${svc} already restarted (re-rendered feature unit) -> skipping"
      continue
    fi
    if run_ssh "${host}" "sudo -n systemctl is-active --quiet \"${svc}\""; then
      echo "==> [${host}] ${svc} active -> restarting"
      if run_ssh "${host}" "sudo -n systemctl restart \"${svc}\"" \
         && wait_for_service_running "${host}" "${svc}" 30; then
        :
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
    AUX_RESTART_FAIL+=("${host} : ${joined%, }")
  fi
  return 0
}

# ---- Feature systemd units (features/<name>/backend_host/services/<unit>.service) ----
# install_host.sh renders these templates only at install time, so a deploy that moves,
# adds or removes a feature used to leave a stale /etc/systemd/system/vpt-<unit>.service
# behind (2026-09-02, demo host: vpt-avq still ran backend_host/scripts/avq_monitor.py,
# a path the deploy had just deleted). Every host deploy therefore reconciles them
# after the rsync push and before vpt-host restarts:
#   1. every unit shipped by the STAGED tree (= enabled features) is rendered
#      (marker header + %PROJECT_ROOT% -> TARGET_DIR) and compared with the installed
#      file; changed/missing -> tee + daemon-reload + enable, restarted after vpt-host;
#      unchanged -> nothing (unless --restart, as before);
#   2. every installed vpt-*.service that carries the marker but is no longer shipped,
#      plus the units of DISABLED_FEATURES in the pinned tree (rendered by
#      install_host.sh before the marker existed) -> disable --now + rm + daemon-reload.
# Only units carrying the marker or listed by a feature (manifest "units": [...] or
# the template file names) are ever touched; core unit names are guarded on top.
#
# The pure parts (marker, core-unit rule, list/render helpers) live in
# lib/feature_units.sh, shared with reconcile_feature_units.sh — the standalone,
# on-host equivalent of this reconcile used by the classic update_core.sh / offline
# bundle path (DEPLOY_CUSTOMER.md, "Deploying without GitHub access"). Looked up next to
# this script first (run it from the checkout, or copy lib/ along when copying it to ~),
# then in REPO_DIR's checkout.
_fu_lib=""
for _p in "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/feature_units.sh" \
          "${REPO_DIR}/setup/proxmox/node/lib/feature_units.sh"; do
  [[ -f "${_p}" ]] && { _fu_lib="${_p}"; break; }
done
[[ -n "${_fu_lib}" ]] || { echo "missing lib/feature_units.sh next to $0 (and not in ${REPO_DIR}/setup/proxmox/node/lib/)" >&2; exit 1; }
# shellcheck source=lib/feature_units.sh
source "${_fu_lib}"
FEATURE_UNITS_TREE=""       # = STAGE_DIR once staged (extra core units = core templates there)
FEATURE_RESTART_UNITS=()   # per host: vpt-<unit>.service rendered in this deploy -> restart
FEATURE_UNIT_FAIL=()       # "host : what" — listed in the summary, never fails the deploy
DISABLED_FEATURE_UNITS=()  # "<feature>\t<unit>\t<template>" of DISABLED_FEATURES @ PIN

# ssh without the "==> [host] cmd" banner, for output that is captured/parsed.
ssh_capture() {
  local host="$1"; shift
  ssh ${SSH_OPTS} "$(build_ssh_target "${host}")" "$@"
}

# staged_has_unit <unit>: is vpt-<unit> shipped by the staged tree (any feature)?
staged_has_unit() {
  units_has "${STAGED_FEATURE_UNITS}" "$1"
}

# reconcile_feature_units <host> <target_dir>: steps 1 + 2 above. Fills
# FEATURE_RESTART_UNITS for restart_feature_units; --dry-run only prints. Always returns 0
# (best-effort; problems go to FEATURE_UNIT_FAIL). The units are rendered against the
# target's own directory: render_feature_unit (lib) reads the global TARGET_DIR, so it is
# shadowed here with a `local` for the duration of the call (bash dynamic scoping).
reconcile_feature_units() {
  local host="$1"
  local TARGET_DIR="${2:-${TARGET_DIR}}"
  FEATURE_RESTART_UNITS=()
  echo -e "\n==> [${host}] Reconciling feature systemd units${DRY_TAG}"
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/vpt-units.XXXXXX")"
  local feature unit tpl svc remote_file rendered installed state cmd

  # 1. enabled features: render, compare with the installed file, install if it differs
  while IFS=$'\t' read -r feature unit tpl; do
    [[ -n "${unit}" ]] || continue
    svc="vpt-${unit}.service"; remote_file="/etc/systemd/system/${svc}"
    if is_core_unit "${unit}"; then
      echo "==> [${host}] ${svc} (features/${feature}): name collides with a core unit -> NOT touched"
      FEATURE_UNIT_FAIL+=("${host} : ${svc} collides with a core unit name (rename it in features/${feature})")
      continue
    fi
    rendered="${tmp}/${svc}"; installed="${tmp}/${svc}.installed"
    render_feature_unit "${feature}" "${unit}" "${tpl}" "${rendered}"
    state="unchanged"
    if ssh_capture "${host}" "sudo -n cat ${remote_file}" > "${installed}" 2>/dev/null </dev/null; then
      cmp -s "${rendered}" "${installed}" || state="changed"
    else
      state="missing"
    fi
    if [[ "${state}" == "unchanged" ]]; then
      echo "==> [${host}] ${svc} (features/${feature}): unchanged"
      continue
    fi
    if ${DRY_RUN}; then
      if [[ "${unit}" == *@ ]]; then
        echo "==> [${host}] DRY-RUN: would render ${svc} (features/${feature}, ${state}) and daemon-reload (template unit: no enable/restart)"
      else
        echo "==> [${host}] DRY-RUN: would render ${svc} (features/${feature}, ${state}), daemon-reload, enable, and restart it after ${HOST_SERVICE}"
      fi
      if [[ "${state}" == "changed" ]]; then
        diff -u -L "${remote_file} (installed)" -L "${svc} (rendered)" "${installed}" "${rendered}" | sed 's/^/    /' || true
      fi
      continue
    fi
    echo "==> [${host}] ${svc} (features/${feature}): ${state} -> installing"
    cmd="sudo -n tee ${remote_file} >/dev/null && sudo -n systemctl daemon-reload"
    [[ "${unit}" == *@ ]] || cmd+=" && sudo -n systemctl enable ${svc}"
    if ssh_capture "${host}" "${cmd}" < "${rendered}"; then
      [[ "${unit}" == *@ ]] || FEATURE_RESTART_UNITS+=("${svc}")
    else
      echo "==> [${host}] ${svc} FAILED to install"
      FEATURE_UNIT_FAIL+=("${host} : ${svc} install failed")
    fi
  done <<< "${STAGED_FEATURE_UNITS}"

  # 2. units of disabled/removed features: marker on the host, or DISABLED_FEATURES @ PIN
  local candidates="" entry rest seen=" "
  candidates="$(ssh_capture "${host}" "sudo -n grep -H -m1 '^${FEATURE_UNIT_MARKER} ' /etc/systemd/system/vpt-*.service 2>/dev/null || true" </dev/null | marker_lines_to_units)"
  [[ -n "${candidates}" ]] && candidates+=$'\n'
  for entry in ${DISABLED_FEATURE_UNITS[@]+"${DISABLED_FEATURE_UNITS[@]}"}; do
    rest="${entry#*$'\t'}"
    candidates+="${rest%%$'\t'*}"$'\t'"${entry%%$'\t'*}"$'\n'
  done
  while IFS=$'\t' read -r unit feature; do
    [[ -n "${unit}" ]] || continue
    [[ "${seen}" == *" ${unit} "* ]] && continue
    seen+="${unit} "
    svc="vpt-${unit}.service"; remote_file="/etc/systemd/system/${svc}"
    staged_has_unit "${unit}" && continue          # still shipped: handled in step 1
    if is_core_unit "${unit}"; then
      echo "==> [${host}] ${svc}: core unit name -> NOT touched"
      continue
    fi
    ssh_capture "${host}" "sudo -n test -f ${remote_file}" </dev/null 2>/dev/null || continue
    if ${DRY_RUN}; then
      echo "==> [${host}] DRY-RUN: would disable --now ${svc} (features/${feature} disabled/removed), remove ${remote_file}, daemon-reload"
      continue
    fi
    echo "==> [${host}] ${svc} (features/${feature}): disabled/removed -> disable --now + remove"
    cmd="sudo -n rm -f ${remote_file} && sudo -n systemctl daemon-reload"
    [[ "${unit}" == *@ ]] || cmd="sudo -n systemctl disable --now ${svc} && ${cmd}"
    if ! ssh_capture "${host}" "${cmd}" </dev/null; then
      echo "==> [${host}] ${svc} FAILED to disable/remove"
      FEATURE_UNIT_FAIL+=("${host} : ${svc} disable/remove failed")
    fi
  done <<< "${candidates}"
  rm -rf "${tmp}"
  return 0
}

# restart_feature_units <host>: step 3 — restart the units (re)rendered by
# reconcile_feature_units, after vpt-host. Best-effort, never aborts the deploy.
restart_feature_units() {
  local host="$1"
  [[ ${#FEATURE_RESTART_UNITS[@]} -gt 0 ]] || return 0
  echo -e "\n==> [${host}] Restarting re-rendered feature units: ${FEATURE_RESTART_UNITS[*]}"
  local svc
  for svc in "${FEATURE_RESTART_UNITS[@]}"; do
    if run_ssh "${host}" "sudo -n systemctl restart \"${svc}\"" \
       && wait_for_service_running "${host}" "${svc}" 30; then
      :
    else
      echo "==> [${host}] ${svc} FAILED to restart"
      FEATURE_UNIT_FAIL+=("${host} : ${svc} restart failed")
    fi
  done
  return 0
}
# ---- End feature systemd units ----

# new_target_dir_hint <host> <dir> <rsync -i output>: rsync itemizes a missing target
# directory as `cd+++++++++ ./` (GNU rsync; openrsync on macOS: `cd+++++++ ./`). The
# receiver runs as root via --rsync-path="sudo rsync", so it creates the directory itself
# and the chown below hands it to SYNC_USER — no pre-created folder needed. Print the
# one-time setup the new instance still needs.
new_target_dir_hint() {
  local host="$1" dir="$2" out="$3"
  # here-string, not a pipe: grep -q exits at the first match and pipefail would turn
  # printf's SIGPIPE into a failure (hint silently skipped).
  grep -qE '^cd\++ \./$' <<< "${out}" || return 0
  echo "==> [${host}] ${dir} does not exist yet: created by this push (sudo rsync) and chown'ed to ${SYNC_USER} — still needed once on ${host}: the VM's own frontend/.env (never deployed), npm install in ${dir}/frontend, and the instance's systemd unit (DEPLOY_CUSTOMER.md, 'Two frontends on one VM')"
}

# Push the STAGED tree to <target_dir> on a Linux target (canonical rsync_push, source =
# STAGE_DIR instead of REPO_DIR, destination = the target's own directory). --dry-run
# prints the itemized change list.
rsync_push() {
  local target_host="$1" target_dir="${2:-${TARGET_DIR}}"
  local ssh_target out
  ssh_target="$(build_ssh_target "${target_host}")"
  if ${DRY_RUN}; then
    echo -e "\n==> [proxmox -> ${target_host}:${target_dir}] rsync DRY-RUN (itemized changes, nothing copied)"
    out="$(rsync -n -i -az --delete "${PUSH_FILTERS[@]}" \
      --rsync-path="sudo rsync" \
      -e "ssh ${SSH_OPTS}" \
      "${STAGE_DIR}/" \
      "${ssh_target}:${target_dir}/")" || { echo "==> [${target_host}] rsync dry-run FAILED"; return 1; }
    printf '%s\n' "${out}"
    echo "==> [${target_host}] would change: $(printf '%s\n' "${out}" | grep -c '^[<>ch*]' || true) entries (deletions: $(printf '%s\n' "${out}" | grep -c '^\*deleting' || true))"
    new_target_dir_hint "${target_host}" "${target_dir}" "${out}"
    return 0
  fi
  echo -e "\n==> [proxmox -> ${target_host}:${target_dir}] rsync push"
  # -i (captured, not printed) instead of the canonical -q: same transfer, lets the
  # push report the change count and notice a freshly created target directory.
  if ! out="$(rsync -az -i --delete "${PUSH_FILTERS[@]}" \
    --rsync-path="sudo rsync" \
    -e "ssh ${SSH_OPTS}" \
    "${STAGE_DIR}/" \
    "${ssh_target}:${target_dir}/")"; then
    echo "==> [${target_host}] rsync FAILED"
    return 1
  fi
  echo "==> [${target_host}] changed: $(printf '%s\n' "${out}" | grep -c '^[<>ch*]' || true) entries (deletions: $(printf '%s\n' "${out}" | grep -c '^\*deleting' || true))"
  new_target_dir_hint "${target_host}" "${target_dir}" "${out}"
  # Fix ownership (canonical)
  run_ssh "${target_host}" "sudo -n find ${target_dir} \
    -path ${target_dir}/frontend/public/docs -prune -o \
    -path ${target_dir}/frontend/public/brand -prune -o \
    -not -path '*/.env' -not -path '*/venv/*' \
    -exec chown ${SYNC_USER}:${SYNC_USER} {} + 2>/dev/null || true"
  # Defensive (from the private update_core.sh): re-assert exec bit on the BLE
  # scripts invoked via `sudo <abs path>`; mode sometimes arrives 0664. Idempotent.
  run_ssh "${target_host}" "sudo -n chmod +x \
    ${target_dir}/backend_host/src/controllers/remote/bluetooth/start.sh \
    ${target_dir}/backend_host/src/controllers/remote/bluetooth/resume.sh \
    2>/dev/null || true"
}

rsync_push_windows() {
  local target_host="$1"
  local ssh_target
  ssh_target="$(build_ssh_target "${target_host}")"
  local dry=()
  ${DRY_RUN} && dry=(-n -i)
  echo -e "\n==> [proxmox -> ${target_host}] rsync push (Windows)${DRY_TAG}"
  # --blocking-io: Windows hosts on the inbox Win32-OpenSSH 9.5.5.x hand the remote rsync
  # non-blocking pipes and it dies on the first write ("safe_write … Resource temporarily
  # unavailable (11)"); blocking I/O on the transport avoids it (verified 2026-09-09).
  rsync ${dry[@]+"${dry[@]}"} -rlz --delete --blocking-io --no-perms --chmod=ugo=rwX --omit-dir-times --no-group --no-owner "${PUSH_FILTERS[@]}" \
    -e "ssh ${SSH_OPTS}" \
    "${STAGE_DIR}/" \
    "${ssh_target}:${TARGET_DIR_WINDOWS}/"
}

restart_windows_task() {
  local host="$1"
  echo -e "\n==> [${host}] Restarting Windows scheduled task '${WINDOWS_TASK}'"
  run_ssh "${host}" "powershell.exe -Command \"Stop-ScheduledTask -TaskName '${WINDOWS_TASK}' -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName '${WINDOWS_TASK}'\""
  sleep 5
  run_ssh "${host}" "powershell.exe -Command \"Get-ScheduledTask -TaskName '${WINDOWS_TASK}' | Select-Object TaskName, State | Format-Table -AutoSize\""
}

DEPLOY_OK=()
DEPLOY_FAIL=()

# In --dry-run the restart step is skipped (nothing was copied).
maybe_restart() {
  local host="$1" service="$2"
  if ${DRY_RUN}; then
    echo "==> [${host}] DRY-RUN: would restart ${service}"
    return 0
  fi
  restart_and_status "${host}" "${service}"
}

# The try_* helpers take <host> <target_dir> <service> <label>; <label> is what the
# summary shows for the target (target_label: the alias, plus "(dir, service)" when
# they differ from the defaults).
critical_deploy() {
  local host="$1" dir="$2" service="$3" label="${4:-$1}"
  if rsync_push "${host}" "${dir}" && maybe_restart "${host}" "${service}"; then
    DEPLOY_OK+=("${label}")
  else
    DEPLOY_FAIL+=("${label}")
    echo "==> [${host}] CRITICAL deploy failed"
    return 1
  fi
}

try_deploy() {
  local host="$1" dir="$2" service="$3" label="${4:-$1}"
  if rsync_push "${host}" "${dir}" && maybe_restart "${host}" "${service}"; then
    DEPLOY_OK+=("${label}")
    return 0
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${label}")
    return 1
  fi
}

# Host role: like try_deploy, with the feature-unit reconcile between push and restart
# (reconcile is best-effort and cannot fail the host; --dry-run only prints).
try_deploy_host() {
  local host="$1" dir="$2" service="$3" label="${4:-$1}"
  if rsync_push "${host}" "${dir}" && reconcile_feature_units "${host}" "${dir}" && maybe_restart "${host}" "${service}"; then
    DEPLOY_OK+=("${label}")
    return 0
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${label}")
    return 1
  fi
}

try_deploy_windows() {
  local host="$1" label="${2:-$1}"
  if rsync_push_windows "${host}" && { ${DRY_RUN} || restart_windows_task "${host}"; }; then
    DEPLOY_OK+=("${label}")
  else
    echo "==> [${host}] SKIPPED (unreachable or sync failed)"
    DEPLOY_FAIL+=("${label}")
  fi
}

# ---- Target tuples: role:alias[:target_dir[:service]] ----
# Every Linux role accepts an optional target directory and service name, so one VM can
# host two instances of a role (e.g. frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo
# next to the default frontend:10.0.0.5 — DEPLOY_CUSTOMER.md "Two frontends on one VM").
# Missing fields fall back to TARGET_DIR (env, default /opt/virtualpytest) and the role's
# default unit; '.service' is appended when missing. windows = alias only (fixed
# TARGET_DIR_WINDOWS + scheduled task). Same syntax in customer.conf /
# customer.local.conf TARGETS, --targets and ~/deploy.local.conf. The push, the
# post-push chown/chmod, the feature-unit render (host role) and the restart/status/wait
# helpers all use the tuple's values. The role arrays hold one
# "<alias>\t<dir>\t<service>" tuple per target (bash 3.2: no associative arrays).
role_default_service() {
  case "$1" in
    server)   printf '%s\n' "${SERVER_SERVICE}" ;;
    frontend) printf '%s\n' "${FRONTEND_SERVICE}" ;;
    host)     printf '%s\n' "${HOST_SERVICE}" ;;
    windows)  printf '%s\n' "${WINDOWS_TASK}" ;;
  esac
}

# parse_target <entry>: sets T_ROLE T_ALIAS T_DIR T_SERVICE (bare alias = host role).
# Returns 1 with a message on stderr for an unknown role, an empty alias, a relative
# target_dir, more than 4 fields, or dir/service given for a windows target.
parse_target() {
  local entry="$1" rest dir="" svc="" extra=""
  T_ROLE=""; T_ALIAS=""; T_DIR=""; T_SERVICE=""
  if [[ "${entry}" == *:* ]]; then T_ROLE="${entry%%:*}"; rest="${entry#*:}"
  else T_ROLE="host"; rest="${entry}"; fi
  case "${T_ROLE}" in
    server|frontend|host|windows) ;;
    *) echo "Unknown target role in '${entry}' (server|frontend|host|windows)" >&2; return 1 ;;
  esac
  IFS=':' read -r T_ALIAS dir svc extra <<< "${rest}"
  T_ALIAS="$(trim "${T_ALIAS}")"; dir="$(trim "${dir}")"; svc="$(trim "${svc}")"
  [[ -n "${T_ALIAS}" ]] || { echo "Empty alias in target '${entry}'" >&2; return 1; }
  [[ -z "${extra}" ]] || { echo "Too many fields in target '${entry}' (role:alias[:target_dir[:service]])" >&2; return 1; }
  if [[ "${T_ROLE}" == "windows" ]]; then
    [[ -z "${dir}${svc}" ]] || { echo "windows target '${entry}' takes no target_dir/service (fixed ${TARGET_DIR_WINDOWS} + task ${WINDOWS_TASK})" >&2; return 1; }
    T_DIR="${TARGET_DIR_WINDOWS}"; T_SERVICE="${WINDOWS_TASK}"
    return 0
  fi
  if [[ -n "${dir}" && "${dir}" != /* ]]; then
    echo "target_dir must be absolute in target '${entry}' (got '${dir}')" >&2; return 1
  fi
  T_DIR="${dir:-${TARGET_DIR}}"; T_DIR="${T_DIR%/}"
  T_SERVICE="${svc:-$(role_default_service "${T_ROLE}")}"
  [[ "${T_SERVICE}" == *.service ]] || T_SERVICE="${T_SERVICE}.service"
  return 0
}

# target_tuple: the "<alias>\t<dir>\t<service>" stored in the role arrays.
target_tuple() { printf '%s\t%s\t%s\n' "${T_ALIAS}" "${T_DIR}" "${T_SERVICE}"; }

# target_label <role> <alias> <dir> <service>: "alias", or "alias (dir, service)" when
# either differs from the role's defaults (banner + DEPLOY SUMMARY).
target_label() {
  local role="$1" alias="$2" dir="$3" svc="$4"
  if [[ "${role}" == "windows" || ( "${dir}" == "${TARGET_DIR}" && "${svc}" == "$(role_default_service "${role}")" ) ]]; then
    printf '%s\n' "${alias}"
  else
    printf '%s (%s, %s)\n' "${alias}" "${dir}" "${svc}"
  fi
}

# role_labels <role> <tuple>...: space-separated labels of a role's targets (banner).
role_labels() {
  local role="$1" t h d s out=""; shift
  for t in "$@"; do
    IFS=$'\t' read -r h d s <<< "${t}"
    out+="$(target_label "${role}" "${h}" "${d}" "${s}") "
  done
  printf '%s\n' "${out% }"
}

# deploy_target <role> <tuple>: print the resolved tuple, then run the role's deploy.
# frontend is critical (a failure aborts the run, as before); server/host/windows are
# best-effort.
deploy_target() {
  local role="$1" h d s label
  IFS=$'\t' read -r h d s <<< "$2"
  label="$(target_label "${role}" "${h}" "${d}" "${s}")"
  echo -e "\n==> [${h}] ${role} target: dir=${d} service=${s}"
  case "${role}" in
    server)   try_deploy "${h}" "${d}" "${s}" "${label}" || true ;;
    frontend) critical_deploy "${h}" "${d}" "${s}" "${label}" ;;
    host)
      # push -> reconcile feature units -> restart vpt-host -> restart re-rendered units
      # -> (--restart) aux services. Only the push + vpt-host restart can fail the host.
      if try_deploy_host "${h}" "${d}" "${s}" "${label}"; then
        restart_feature_units "${h}"
        if ${DEPLOY_RESTART} && ! ${DRY_RUN}; then restart_aux_services "${h}"; fi
      fi
      ;;
    windows)  try_deploy_windows "${h}" "${label}" ;;
  esac
}
# ---- End target tuples ----

# ---- Conf file parsing (customer.conf / customer.local.conf / ~/deploy.local.conf) ----
# Same KEY=VALUE syntax everywhere. CONF_FILES lists the files in override order (first
# match wins): with an overlay = customer.local.conf (git-ignored) then customer.conf,
# so a key present in the local file (even with an empty value) overrides customer.conf;
# without an overlay = ~/deploy.local.conf alone.
CONF_FILES=()
# conf_has <file> KEY -> 0 when the file has a KEY= line.
conf_has() {
  [[ -f "$1" ]] && grep -qE "^[[:space:]]*$2=" "$1"
}
# conf_file KEY -> the conf file that supplies KEY (first in CONF_FILES), '' when none has it.
conf_file() {
  local key="$1" f
  for f in ${CONF_FILES[@]+"${CONF_FILES[@]}"}; do
    if conf_has "${f}" "${key}"; then printf '%s\n' "${f}"; return 0; fi
  done
  return 0
}
# conf_get KEY -> value from conf_file KEY, trailing '#' comment and all whitespace stripped.
conf_get() {
  local key="$1" f
  f="$(conf_file "${key}")"
  [[ -n "${f}" ]] || return 0
  sed -n "s/^[[:space:]]*${key}=\([^#]*\).*/\1/p" "${f}" | tail -n 1 | tr -d '[:space:]'
}
# conf_source KEY -> file name that supplies KEY ('customer.local.conf', 'customer.conf',
# '~/deploy.local.conf') or '(unset)' for the banner.
conf_source() {
  local f
  f="$(conf_file "$1")"
  if [[ -z "${f}" ]]; then echo "(unset)"
  elif [[ "${f}" == "${DEPLOY_LOCAL_CONF}" ]]; then echo "${DEPLOY_LOCAL_CONF/#${HOME}/~}"
  else basename "${f}"; fi
}
# setting VALUE_FROM_FLAG FLAG_NAME KEY -> prints "<value>|<source>": the CLI flag when
# given, else the conf files (source = conf_source KEY).
setting() {
  local flag_val="$1" flag_name="$2" key="$3"
  if [[ -n "${flag_val}" ]]; then printf '%s|%s\n' "${flag_val}" "${flag_name}"
  else printf '%s|%s\n' "$(conf_get "${key}")" "$(conf_source "${key}")"; fi
}

# trim <string> comes from lib/feature_units.sh (sourced above).

usage() { sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'; }

# ---- Parse args ----
OVERLAY_DIR=""
DRY_RUN=false
STAGE_ONLY=false
NO_CHECKOUT=false
KEEP_STAGE=false
DEPLOY_RESTART=false
TARGETS_ARG=""
PIN_ARG=""
DISABLED_ARG=""
DEPLOY_LOCAL_CONF="${DEPLOY_LOCAL_CONF:-${HOME}/deploy.local.conf}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=true ;;
    --stage-only)   STAGE_ONLY=true ;;
    --no-checkout)  NO_CHECKOUT=true ;;
    --keep-stage)   KEEP_STAGE=true ;;
    --targets)      [[ $# -gt 1 ]] || { echo "--targets needs a value" >&2; exit 1; }; TARGETS_ARG="$2"; shift ;;
    --targets=*)    TARGETS_ARG="${1#--targets=}" ;;
    --pin)          [[ $# -gt 1 ]] || { echo "--pin needs a value" >&2; exit 1; }; PIN_ARG="$2"; shift ;;
    --pin=*)        PIN_ARG="${1#--pin=}" ;;
    --disabled-features)   [[ $# -gt 1 ]] || { echo "--disabled-features needs a value" >&2; exit 1; }; DISABLED_ARG="$2"; shift ;;
    --disabled-features=*) DISABLED_ARG="${1#--disabled-features=}" ;;
    --restart)
      DEPLOY_RESTART=true
      if [[ $# -gt 1 && "$2" != --* ]]; then RESTART_SERVICE="$2"; shift; fi
      ;;
    --help|-h)      usage; exit 0 ;;
    --*)            echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *)
      if [[ -n "${OVERLAY_DIR}" ]]; then echo "Only one <overlay_dir> is supported. Got extra value: $1" >&2; exit 1; fi
      OVERLAY_DIR="$1"
      ;;
  esac
  shift
done

NOCO_TAG=""; ${NO_CHECKOUT} && NOCO_TAG=" (no checkout)"
git -C "${REPO_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "REPO_DIR is not a git checkout: ${REPO_DIR}" >&2; exit 1; }

if [[ -n "${OVERLAY_DIR}" ]]; then
  # ---- Overlay mode: customer.local.conf (git-ignored) overrides customer.conf ----
  _ov="${OVERLAY_DIR}"
  OVERLAY_DIR="$(cd "${_ov}" 2>/dev/null && pwd)" || { echo "overlay dir not found: ${_ov}" >&2; exit 1; }
  CUSTOMER_CONF="${OVERLAY_DIR}/customer.conf"
  CUSTOMER_LOCAL_CONF="${OVERLAY_DIR}/customer.local.conf"
  [[ -f "${CUSTOMER_CONF}" ]] || { echo "missing ${CUSTOMER_CONF}" >&2; exit 1; }
  CONF_FILES=("${CUSTOMER_LOCAL_CONF}" "${CUSTOMER_CONF}")
  CONF_TAG="customer.conf$( [[ -f "${CUSTOMER_LOCAL_CONF}" ]] && echo " + customer.local.conf (overrides)" || echo " (no customer.local.conf)")"

  # Refuse an overlay that carries ANY .env file (before touching REPO_DIR). frontend/.env
  # is the VM's own environment file (never in git): an overlay must ship
  # frontend/.env.production instead. Every other .env holds backend secrets.
  _overlay_envs="$(cd "${OVERLAY_DIR}" && find . -name '.env' -not -path './.git/*' | sed 's|^\./||' | sort)"
  if [[ -n "${_overlay_envs}" ]]; then
    echo "ERROR: the overlay carries .env file(s) — an overlay must never ship a .env:" >&2
    while IFS= read -r _f; do
      if [[ "${_f}" == "frontend/.env" ]]; then
        echo "  ${_f}  -> rename it to frontend/.env.production (VITE_* branding/navigation only; the VM keeps its own frontend/.env)" >&2
      else
        echo "  ${_f}  -> remove it (backend .env files stay on the machines, never in an overlay)" >&2
      fi
    done <<< "${_overlay_envs}"
    exit 1
  fi
else
  # ---- No overlay: pure platform; flags, else ~/deploy.local.conf on the deploy host ----
  CONF_FILES=("${DEPLOY_LOCAL_CONF}")
  CONF_TAG="$( [[ -f "${DEPLOY_LOCAL_CONF}" ]] && echo "${DEPLOY_LOCAL_CONF/#${HOME}/~}" || echo "no ${DEPLOY_LOCAL_CONF/#${HOME}/~} (flags only)")"
fi

# Each value: CLI flag first, else the conf files (source printed in the banner).
IFS='|' read -r PIN PIN_SOURCE                       <<< "$(setting "${PIN_ARG}"      --pin               PIN)"
IFS='|' read -r DISABLED_FEATURES DISABLED_SOURCE    <<< "$(setting "${DISABLED_ARG}" --disabled-features DISABLED_FEATURES)"
IFS='|' read -r TARGETS TARGETS_SOURCE               <<< "$(setting "${TARGETS_ARG}"  --targets           TARGETS)"
if [[ -z "${PIN}" ]]; then
  if [[ -n "${OVERLAY_DIR}" ]]; then echo "PIN is empty (set it in customer.conf or pass --pin <ref>)" >&2
  else echo "PIN is empty: pass --pin <ref> or set PIN in ${DEPLOY_LOCAL_CONF/#${HOME}/~}" >&2; fi
  exit 1
fi

# ---- Targets: role:alias[:target_dir[:service]] list; refuse to run with none (unless --stage-only) ----
SERVER_TARGETS=(); FRONTEND_TARGETS=(); HOST_TARGETS=(); WINDOWS_TARGETS=()
IFS=',' read -ra _entries <<< "${TARGETS}"
for _e in "${_entries[@]:-}"; do
  _e="$(trim "${_e}")"; [[ -z "${_e}" ]] && continue
  parse_target "${_e}" || exit 1
  case "${T_ROLE}" in
    server)   SERVER_TARGETS+=("$(target_tuple)") ;;
    frontend) FRONTEND_TARGETS+=("$(target_tuple)") ;;
    host)     HOST_TARGETS+=("$(target_tuple)") ;;
    windows)  WINDOWS_TARGETS+=("$(target_tuple)") ;;
  esac
done
N_TARGETS=$(( ${#SERVER_TARGETS[@]} + ${#FRONTEND_TARGETS[@]} + ${#HOST_TARGETS[@]} + ${#WINDOWS_TARGETS[@]} ))
if ! ${STAGE_ONLY} && (( N_TARGETS == 0 )); then
  if [[ -n "${OVERLAY_DIR}" ]]; then
    echo "Refusing to run: no targets. Set TARGETS in customer.local.conf (or customer.conf) or pass --targets role:alias,..." >&2
  else
    echo "Refusing to run: no targets. Pass --targets role:alias,... or set TARGETS in ${DEPLOY_LOCAL_CONF/#${HOME}/~}" >&2
  fi
  exit 1
fi

echo "Starting layered customer deployment..."
echo "Overlay:  ${OVERLAY_DIR:-(none — pure platform)}"
echo "Conf:     ${CONF_TAG}"
echo "Core:     ${REPO_DIR} @ PIN=${PIN}${NOCO_TAG} (from ${PIN_SOURCE})"
echo "Disabled: ${DISABLED_FEATURES:-<none>} (from ${DISABLED_SOURCE})"
echo "Targets:  server=$(role_labels server ${SERVER_TARGETS[@]+"${SERVER_TARGETS[@]}"}) frontend=$(role_labels frontend ${FRONTEND_TARGETS[@]+"${FRONTEND_TARGETS[@]}"}) host=$(role_labels host ${HOST_TARGETS[@]+"${HOST_TARGETS[@]}"}) windows=$(role_labels windows ${WINDOWS_TARGETS[@]+"${WINDOWS_TARGETS[@]}"}) (from ${TARGETS_SOURCE}; defaults dir=${TARGET_DIR} service=${SERVER_SERVICE}/${FRONTEND_SERVICE}/${HOST_SERVICE})"
echo "Mode:     dry-run=${DRY_RUN} stage-only=${STAGE_ONLY} restart-aux=${DEPLOY_RESTART}${RESTART_SERVICE:+ (${RESTART_SERVICE})}"
DRY_TAG=""; ${DRY_RUN} && DRY_TAG=" (DRY-RUN)"

# ---- Step 1: checkout the pin in the public checkout ----
echo -e "\n=== Step 1: core @ PIN ==="
if ${NO_CHECKOUT}; then
  echo "--no-checkout: using ${REPO_DIR} working tree as is ($(git -C "${REPO_DIR}" rev-parse --short HEAD), $(git -C "${REPO_DIR}" rev-parse --abbrev-ref HEAD))"
else
  git -C "${REPO_DIR}" fetch --all --tags --prune
  if git -C "${REPO_DIR}" rev-parse -q --verify "refs/remotes/origin/${PIN}" >/dev/null; then
    PIN_REF="origin/${PIN}"           # branch: always the remote tip, never a stale local branch
  elif git -C "${REPO_DIR}" rev-parse -q --verify "refs/tags/${PIN}" >/dev/null; then
    PIN_REF="refs/tags/${PIN}"
  else
    PIN_REF="${PIN}"                  # sha
  fi
  # Remember the branch the checkout was on so it can be restored after staging
  # (the canonical update_core.sh assumes ~/virtualpytest sits on a branch).
  PREV_BRANCH="$(git -C "${REPO_DIR}" symbolic-ref -q --short HEAD || true)"
  git -C "${REPO_DIR}" checkout -q --detach "${PIN_REF}"
  echo "checked out ${PIN_REF} = $(git -C "${REPO_DIR}" rev-parse --short HEAD)"
fi
if [[ -f "${REPO_DIR}/VERSION.txt" ]]; then
  echo "VERSION.txt: $(head -n 1 "${REPO_DIR}/VERSION.txt" | tr -d '\r')"
else
  echo "WARNING: VERSION.txt is missing in ${REPO_DIR}"
fi

# ---- Step 2: excludes for disabled features (from the pinned tree's own helper) ----
if [[ -n "${DISABLED_FEATURES}" ]]; then
  if [[ -f "${REPO_DIR}/scripts/disabled_features_excludes.sh" ]]; then
    while IFS= read -r _line; do
      [[ -n "${_line}" ]] && FEATURE_EXCLUDES+=("${_line}")
    done < <(DISABLED_FEATURES="${DISABLED_FEATURES}" bash "${REPO_DIR}/scripts/disabled_features_excludes.sh")
  else
    # Pin predates the helper: same output, inline.
    IFS=',' read -ra _names <<< "${DISABLED_FEATURES}"
    for _n in "${_names[@]}"; do
      _n="${_n//[[:space:]]/}"; [[ -n "${_n}" ]] && FEATURE_EXCLUDES+=("--exclude=/features/${_n}/")
    done
  fi
fi
echo "Feature excludes: ${FEATURE_EXCLUDES[*]:-<none>}"

# ---- Step 3: stage core + overlay ----
echo -e "\n=== Step 3: stage merged tree ==="
if [[ -z "${STAGE_DIR:-}" ]]; then
  STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/vpt-stage.XXXXXX")"
  ${KEEP_STAGE} || trap 'rm -rf "${STAGE_DIR}"' EXIT
else
  mkdir -p "${STAGE_DIR}"
fi
echo "stage: ${STAGE_DIR}"
FEATURE_UNITS_TREE="${STAGE_DIR}"

# Everything git ignores is excluded, on top of the deny-list above. The deny-list is
# hand-maintained and can only name what someone thought of: it had no entry for tmp/,
# pitch-deck/, or features/mobile-app/app/android/app/build/ (283 MB of Android build output),
# so a bundle came out at 385 MB instead of 34 MB -- and the online deploy pushed the same
# files to the customer's VMs. .gitignore already knows what is not source; ask it rather than
# keep guessing. Only paths, never content: a tracked file is never excluded by this.
IGNORE_FILE=""
if git -C "${REPO_DIR}" rev-parse --git-dir >/dev/null 2>&1; then
  IGNORE_FILE="$(mktemp "${TMPDIR:-/tmp}/vpt-ignored.XXXXXX")"
  git -C "${REPO_DIR}" ls-files --others --ignored --exclude-standard --directory 2>/dev/null \
    | sed 's|^|/|' > "${IGNORE_FILE}" || true
  n_ign="$(grep -c . "${IGNORE_FILE}" || true)"
  echo "excluding ${n_ign} git-ignored path(s) from the stage"
fi
rsync -a --delete "${RSYNC_EXCLUDES[@]}" ${IGNORE_FILE:+--exclude-from="${IGNORE_FILE}"} \
  ${FEATURE_EXCLUDES[@]+"${FEATURE_EXCLUDES[@]}"} "${REPO_DIR}/" "${STAGE_DIR}/"
[[ -z "${IGNORE_FILE}" ]] || rm -f "${IGNORE_FILE}"
# Overlay on top: same excludes, except the frontend config it carries (FRONTEND_CONFIG_PATHS)
# which is re-included BEFORE the canonical excludes (first-match). '.env' is never
# re-included, so no .env can come from the overlay (and the overlay was refused above
# if it had one). No overlay = nothing to layer: the stage is the pure platform.
if [[ -n "${OVERLAY_DIR}" ]]; then
  OVERLAY_INCLUDES=()
  while IFS= read -r _line; do
    [[ -n "${_line}" ]] && OVERLAY_INCLUDES+=("${_line}")
  done < <(frontend_config_includes "${OVERLAY_DIR}")
  rsync -a "${OVERLAY_EXCLUDES[@]}" ${OVERLAY_INCLUDES[@]+"${OVERLAY_INCLUDES[@]}"} "${RSYNC_EXCLUDES[@]}" ${FEATURE_EXCLUDES[@]+"${FEATURE_EXCLUDES[@]}"} "${OVERLAY_DIR}/" "${STAGE_DIR}/"
  frontend_config_report "${STAGE_DIR}"
else
  echo "frontend config from overlay: (no overlay)"
fi
# Guard: the stage must not carry ANY .env (frontend/.env is the VM's own file, every
# other .env holds backend secrets). Both rsyncs above exclude '.env'; belt and braces.
_stray_env="$(cd "${STAGE_DIR}" && find . -name '.env' | sed 's|^\./||')"
if [[ -n "${_stray_env}" ]]; then
  echo "ERROR: stage carries a .env (must never be deployed): ${_stray_env}" >&2; exit 1
fi
push_filters

# Distribute the disabled list without touching any host .env:
#  - runtime env for anything this script runs locally (a future local frontend build);
#  - frontend/.env.local in the staged tree: vite.config.ts loadEnv() reads it at build
#    time on the frontend VM (vpt-frontend-prod.service runs `npm run build` in
#    ExecStartPre; the canonical script does not build). Absence of the feature folder
#    already keeps it out of the bundle; the variable is belt and braces + visible.
# Vite 6 loadEnv(mode) reads .env -> .env.local -> .env.<mode> -> .env.<mode>.local and
# a later file wins for a key defined twice (Object.fromEntries over the concatenated
# entries). So on the frontend VM:
#   - `vite build` (mode production, client bundle):
#       frontend/.env (VM) < frontend/.env.local (generated) < frontend/.env.production
#       (overlay); .env.production.local is not used by any overlay;
#   - vite.config.ts itself calls loadEnv('development'), so for VITE_DISABLED_FEATURES
#       (read only there) .env.production plays no part: .env < .env.local wins.
# Hence never put VITE_DISABLED_FEATURES in an overlay .env.production.
export DISABLED_FEATURES
export VITE_DISABLED_FEATURES="${DISABLED_FEATURES}"
printf '# generated by deploy_customer.sh — do not edit on the host\nVITE_DISABLED_FEATURES=%s\n' "${DISABLED_FEATURES}" > "${STAGE_DIR}/frontend/.env.local"

# Version identity: staged VERSION.txt = <core current>/<overlay current> (section above).
write_version_identity

# Sanity: disabled feature folders must be absent from the staged tree.
IFS=',' read -ra _names <<< "${DISABLED_FEATURES}"
for _n in "${_names[@]:-}"; do
  _n="${_n//[[:space:]]/}"; [[ -z "${_n}" ]] && continue
  if [[ -e "${STAGE_DIR}/features/${_n}" ]]; then
    echo "ERROR: features/${_n} still present in staged tree" >&2; exit 1
  fi
  echo "features/${_n}: absent from stage (ok)"
done
echo "staged files: $(find "${STAGE_DIR}" -type f | wc -l | tr -d ' ')"

# Feature systemd units: what the stage ships (enabled features) and what the disabled
# features of the pinned tree would ship (their units are removed from every host by
# reconcile_feature_units; they may predate the marker). The second list must be read
# while PIN is still checked out in REPO_DIR.
STAGED_FEATURE_UNITS="$(list_feature_units "${STAGE_DIR}")"
_disabled_names=()
for _n in "${_names[@]:-}"; do
  _n="${_n//[[:space:]]/}"; [[ -n "${_n}" ]] && _disabled_names+=("${_n}")
done
if [[ ${#_disabled_names[@]} -gt 0 ]]; then
  while IFS= read -r _line; do
    [[ -n "${_line}" ]] && DISABLED_FEATURE_UNITS+=("${_line}")
  done < <(list_feature_units "${REPO_DIR}" "${_disabled_names[@]}")
fi
echo "feature units shipped: $(printf '%s\n' "${STAGED_FEATURE_UNITS}" | awk -F'\t' 'NF { printf "vpt-%s (features/%s) ", $2, $1 }')"
echo "feature units of disabled features (removed on hosts): $(printf '%s\n' ${DISABLED_FEATURE_UNITS[@]+"${DISABLED_FEATURE_UNITS[@]}"} | awk -F'\t' 'NF { printf "vpt-%s (features/%s) ", $2, $1 }')"

# The stage is a copy: put REPO_DIR back on the branch it was on.
if [[ -n "${PREV_BRANCH:-}" ]]; then
  git -C "${REPO_DIR}" checkout -q "${PREV_BRANCH}"
  echo "restored ${REPO_DIR} to branch ${PREV_BRANCH}"
fi

if ${STAGE_ONLY}; then
  trap - EXIT
  echo -e "\n--stage-only: staged tree left at ${STAGE_DIR} (version: ${DEPLOY_VERSION})"
  # Machine-readable trailer for callers that wrap the stage phase
  # (build_customer_bundle.sh): one `stage.<key>=<value>` line each, nothing else starts
  # with "stage.". Unit lists are space-separated unit names (vpt- prefix stripped).
  echo "stage.dir=${STAGE_DIR}"
  echo "stage.version=${DEPLOY_VERSION}"
  echo "stage.pin=${PIN}"
  echo "stage.overlay=${OVERLAY_DIR}"
  echo "stage.disabled_features=${DISABLED_FEATURES}"
  echo "stage.feature_units=$(printf '%s\n' "${STAGED_FEATURE_UNITS}" | awk -F'\t' 'NF { printf "%s ", $2 }' | sed 's/ $//')"
  echo "stage.disabled_feature_units=$(printf '%s\n' ${DISABLED_FEATURE_UNITS[@]+"${DISABLED_FEATURE_UNITS[@]}"} | awk -F'\t' 'NF { printf "%s ", $2 }' | sed 's/ $//')"
  exit 0
fi

# ---- Step 4: push to targets (+ restart) ----
echo -e "\n=== Step 4: deploy to targets${DRY_TAG} ==="
echo "push includes (frontend config carried by the stage; anything else in FRONTEND_CONFIG_PATHS stays untouched on the targets): $(frontend_config_includes "${STAGE_DIR}" | tr '\n' ' ')"
# Each entry is an "<alias>\t<dir>\t<service>" tuple (deploy_target splits it).
if [[ ${#SERVER_TARGETS[@]} -gt 0 ]]; then
  echo -e "\n--- Server ---"
  for _t in "${SERVER_TARGETS[@]}"; do deploy_target server "${_t}"; done
fi
if [[ ${#FRONTEND_TARGETS[@]} -gt 0 ]]; then
  echo -e "\n--- Frontend ---"
  for _t in "${FRONTEND_TARGETS[@]}"; do deploy_target frontend "${_t}"; done
fi
if [[ ${#HOST_TARGETS[@]} -gt 0 ]]; then
  echo -e "\n--- Host VMs ---"
  for _t in "${HOST_TARGETS[@]}"; do deploy_target host "${_t}"; done
fi
if [[ ${#WINDOWS_TARGETS[@]} -gt 0 ]]; then
  echo -e "\n--- Windows Host VMs ---"
  for _t in "${WINDOWS_TARGETS[@]}"; do deploy_target windows "${_t}"; done
fi

# ---- Summary ----
echo -e "\n========== DEPLOY SUMMARY${DRY_TAG} =========="
echo "  version:    ${DEPLOY_VERSION}"
# One label per target: the alias, or "alias (dir, service)" for a non-default instance.
[[ ${#DEPLOY_OK[@]} -gt 0 ]]   && echo -e "  OK (${#DEPLOY_OK[@]}):     $(printf '%s; ' "${DEPLOY_OK[@]}" | sed 's/; $//')"
[[ ${#DEPLOY_FAIL[@]} -gt 0 ]] && echo -e "  FAILED (${#DEPLOY_FAIL[@]}): $(printf '%s; ' "${DEPLOY_FAIL[@]}" | sed 's/; $//')"
echo "===================================="
if [[ ${#AUX_RESTART_FAIL[@]} -gt 0 ]]; then
  echo -e "\n======= SERVICE RESTART FAILED ======="
  for _f in "${AUX_RESTART_FAIL[@]}"; do echo "  ${_f}"; done
  echo "======================================"
fi
if [[ ${#FEATURE_UNIT_FAIL[@]} -gt 0 ]]; then
  echo -e "\n======= FEATURE UNIT PROBLEMS (deploy not failed) ======="
  for _f in "${FEATURE_UNIT_FAIL[@]}"; do echo "  ${_f}"; done
  echo "=========================================================="
fi
if [[ ${#DEPLOY_FAIL[@]} -gt 0 ]]; then echo -e "\nDone (with failures)."; exit 1; fi
echo -e "\nDone."
