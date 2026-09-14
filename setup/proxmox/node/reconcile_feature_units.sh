#!/usr/bin/env bash
# reconcile_feature_units.sh — reconcile the feature systemd units ON this host (no ssh).
#
#   Standalone equivalent of deploy_customer.sh's reconcile_feature_units (which does the
#   same over ssh from the deploy host). Meant for the classic deploy path: update_core.sh
#   runs it on every host after the rsync push (also from an offline bundle,
#   DEPLOY_CUSTOMER.md "Deploying without GitHub access"). install_host.sh renders the
#   units only at install time, so without this a deploy that moves/adds/removes a
#   feature leaves a stale /etc/systemd/system/vpt-<unit>.service behind.
#
# Usage (run as root: sudo bash setup/proxmox/node/reconcile_feature_units.sh ...):
#   reconcile_feature_units.sh [--project-root /opt/virtualpytest] [--dry-run]
#                              [--remove-units a,b] [--no-restart] [--systemd-dir <dir>]
#
#   --project-root <dir>  deployed tree (default /opt/virtualpytest); its
#                         features/*/backend_host/services/*.service are the source of
#                         truth and %PROJECT_ROOT% is rendered as this path
#   --dry-run             print what would change (with a unified diff per changed unit),
#                         touch nothing; needs no root
#   --remove-units a,b    extra unit names (vpt- prefix optional) to disable + remove when
#                         the tree does not ship them (units of a disabled feature that
#                         install_host.sh rendered before the marker existed). The
#                         `disabled_feature_units:` line of <project-root>/BUNDLE_MANIFEST.txt
#                         (written by build_customer_bundle.sh) is read automatically.
#   --no-restart          install/enable/remove but do not restart the re-rendered units
#   --systemd-dir <dir>   where units live (default /etc/systemd/system; env SYSTEMD_DIR)
#                         — for tests; systemctl is still only called when not --dry-run
#
# What it does (same rules as deploy_customer.sh, shared lib/feature_units.sh):
#   1. every feature unit shipped by the tree is rendered (marker header + %PROJECT_ROOT%
#      substitution) and compared with the installed file: changed/missing -> installed,
#      daemon-reload, enable, restart (x@.service templates: installed + reload only);
#   2. every installed vpt-*.service carrying the marker `# vpt-feature: <name>` (or listed
#      by --remove-units / the bundle manifest) that the tree no longer ships ->
#      systemctl disable --now + removed + daemon-reload;
#   3. core units (vpt-host, vpt-stream, ... and anything with a core template under
#      backend_host/config/services/linux) are never touched, whatever a marker says.
# Exit 0 when everything applied (or nothing to do), 1 when an install/remove/restart
# failed (callers treat it as best-effort). Never fails on a missing features/ folder.
set -euo pipefail

PROJECT_ROOT="/opt/virtualpytest"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
DRY_RUN=false
DO_RESTART=true
EXTRA_REMOVE=""

usage() { sed -n '2,39p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)   [[ $# -gt 1 ]] || { echo "--project-root needs a value" >&2; exit 1; }; PROJECT_ROOT="$2"; shift ;;
    --project-root=*) PROJECT_ROOT="${1#--project-root=}" ;;
    --systemd-dir)    [[ $# -gt 1 ]] || { echo "--systemd-dir needs a value" >&2; exit 1; }; SYSTEMD_DIR="$2"; shift ;;
    --systemd-dir=*)  SYSTEMD_DIR="${1#--systemd-dir=}" ;;
    --remove-units)   [[ $# -gt 1 ]] || { echo "--remove-units needs a value" >&2; exit 1; }; EXTRA_REMOVE="$2"; shift ;;
    --remove-units=*) EXTRA_REMOVE="${1#--remove-units=}" ;;
    --dry-run)        DRY_RUN=true ;;
    --no-restart)     DO_RESTART=false ;;
    --help|-h)        usage; exit 0 ;;
    *)                echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

PROJECT_ROOT="$(cd "${PROJECT_ROOT}" 2>/dev/null && pwd)" || { echo "project root not found: ${PROJECT_ROOT}" >&2; exit 1; }
[[ -d "${SYSTEMD_DIR}" ]] || { echo "systemd dir not found: ${SYSTEMD_DIR}" >&2; exit 1; }
# Root is needed to write /etc/systemd/system and drive systemctl; a custom --systemd-dir
# (tests with a stub systemctl on PATH) is the caller's responsibility.
if ! ${DRY_RUN} && [[ "${EUID}" -ne 0 && "${SYSTEMD_DIR}" == "/etc/systemd/system" ]]; then
  echo "must run as root (sudo) unless --dry-run" >&2; exit 1
fi

# Shared logic: next to this script (the deployed tree ships it under setup/proxmox/node/lib).
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_fu_lib=""
for _p in "${_here}/lib/feature_units.sh" "${PROJECT_ROOT}/setup/proxmox/node/lib/feature_units.sh"; do
  [[ -f "${_p}" ]] && { _fu_lib="${_p}"; break; }
done
[[ -n "${_fu_lib}" ]] || { echo "missing lib/feature_units.sh (next to $0 or under ${PROJECT_ROOT}/setup/proxmox/node/lib/)" >&2; exit 1; }
# shellcheck source=lib/feature_units.sh
source "${_fu_lib}"
TARGET_DIR="${PROJECT_ROOT}"          # %PROJECT_ROOT% in the templates
FEATURE_UNITS_TREE="${PROJECT_ROOT}"  # core templates live here

DRY_TAG=""; ${DRY_RUN} && DRY_TAG=" (DRY-RUN)"
echo "Reconciling feature systemd units${DRY_TAG}: tree=${PROJECT_ROOT} units=${SYSTEMD_DIR}"

SHIPPED="$(list_feature_units "${PROJECT_ROOT}")"
echo "feature units shipped by the tree: $(printf '%s\n' "${SHIPPED}" | awk -F'\t' 'NF { printf "vpt-%s (features/%s) ", $2, $1 }' | sed 's/ $//')"
[[ -n "${SHIPPED}" ]] || echo "  (none — no features/*/backend_host/services/*.service in the tree)"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/vpt-units.XXXXXX")"
trap 'rm -rf "${tmp}"' EXIT
INSTALLED=()   # vpt-<unit>.service written this run (all)
ENABLE=()      # ... that must be enabled + restarted (non-template)
REMOVED=()
FAIL=()
unchanged=0
need_reload=false

# ---- 1. enabled features: render, compare, install when changed/missing ----
while IFS=$'\t' read -r feature unit tpl; do
  [[ -n "${unit}" ]] || continue
  svc="vpt-${unit}.service"; dest="${SYSTEMD_DIR}/${svc}"
  if is_core_unit "${unit}"; then
    echo "==> ${svc} (features/${feature}): name collides with a core unit -> NOT touched"
    FAIL+=("${svc} collides with a core unit name (rename it in features/${feature})")
    continue
  fi
  rendered="${tmp}/${svc}"
  render_feature_unit "${feature}" "${unit}" "${tpl}" "${rendered}"
  state="unchanged"
  if [[ -f "${dest}" ]]; then
    cmp -s "${rendered}" "${dest}" || state="changed"
  else
    state="missing"
  fi
  if [[ "${state}" == "unchanged" ]]; then
    echo "==> ${svc} (features/${feature}): unchanged"
    unchanged=$(( unchanged + 1 ))
    continue
  fi
  if ${DRY_RUN}; then
    if [[ "${unit}" == *@ ]]; then
      echo "==> DRY-RUN: would render ${svc} (features/${feature}, ${state}) and daemon-reload (template unit: no enable/restart)"
    else
      echo "==> DRY-RUN: would render ${svc} (features/${feature}, ${state}), daemon-reload, enable, and restart it"
    fi
    INSTALLED+=("${svc}")
    if [[ "${state}" == "changed" ]]; then
      diff -u -L "${dest} (installed)" -L "${svc} (rendered)" "${dest}" "${rendered}" | sed 's/^/    /' || true
    fi
    continue
  fi
  echo "==> ${svc} (features/${feature}): ${state} -> installing"
  if install -m 0644 "${rendered}" "${dest}"; then
    INSTALLED+=("${svc}"); need_reload=true
    [[ "${unit}" == *@ ]] || ENABLE+=("${svc}")
  else
    echo "==> ${svc} FAILED to install"
    FAIL+=("${svc} install failed")
  fi
done <<< "${SHIPPED}"

# ---- 2. units of disabled/removed features: marker on disk, manifest list, --remove-units ----
candidates="$(grep -H -m1 "^${FEATURE_UNIT_MARKER} " "${SYSTEMD_DIR}"/vpt-*.service 2>/dev/null | marker_lines_to_units || true)"
[[ -n "${candidates}" ]] && candidates+=$'\n'
manifest_units_line=""
if [[ -f "${PROJECT_ROOT}/BUNDLE_MANIFEST.txt" ]]; then
  manifest_units_line="$(sed -n 's/^disabled_feature_units:[[:space:]]*//p' "${PROJECT_ROOT}/BUNDLE_MANIFEST.txt" | head -n 1)"
fi
for u in $(printf '%s' "${EXTRA_REMOVE},${manifest_units_line}" | tr ', ' '\n\n'); do
  u="${u#vpt-}"; u="${u%.service}"
  [[ -n "${u}" && "${u}" != "(none)" ]] || continue
  candidates+="${u}"$'\t'"?"$'\n'
done
seen=" "
while IFS=$'\t' read -r unit feature; do
  [[ -n "${unit}" ]] || continue
  [[ "${seen}" == *" ${unit} "* ]] && continue
  seen+="${unit} "
  svc="vpt-${unit}.service"; dest="${SYSTEMD_DIR}/${svc}"
  units_has "${SHIPPED}" "${unit}" && continue       # still shipped: handled in step 1
  if is_core_unit "${unit}"; then
    echo "==> ${svc}: core unit name -> NOT touched"
    continue
  fi
  [[ -f "${dest}" ]] || continue
  [[ "${feature}" == "?" ]] && feature="$(sed -n "s/^${FEATURE_UNIT_MARKER} //p" "${dest}" | head -n 1)"
  if ${DRY_RUN}; then
    echo "==> DRY-RUN: would disable --now ${svc} (features/${feature:-?} disabled/removed), remove ${dest}, daemon-reload"
    REMOVED+=("${svc}")
    continue
  fi
  echo "==> ${svc} (features/${feature:-?}): disabled/removed -> disable --now + remove"
  ok=true
  if [[ "${unit}" != *@ ]]; then
    systemctl disable --now "${svc}" || ok=false
  fi
  rm -f "${dest}" || ok=false
  need_reload=true
  if ${ok}; then REMOVED+=("${svc}"); else echo "==> ${svc} FAILED to disable/remove"; FAIL+=("${svc} disable/remove failed"); fi
done <<< "${candidates}"

# ---- 3. daemon-reload once, enable + restart what was (re)rendered ----
if ! ${DRY_RUN}; then
  if ${need_reload}; then
    systemctl daemon-reload || FAIL+=("daemon-reload failed")
  fi
  for svc in ${ENABLE[@]+"${ENABLE[@]}"}; do
    systemctl enable "${svc}" >/dev/null 2>&1 || FAIL+=("${svc} enable failed")
    if ${DO_RESTART}; then
      if systemctl restart "${svc}"; then
        echo "==> ${svc}: restarted ($(systemctl is-active "${svc}" 2>/dev/null || true))"
      else
        echo "==> ${svc} FAILED to restart"; FAIL+=("${svc} restart failed")
      fi
    else
      echo "==> ${svc}: enabled (restart left to the caller, --no-restart)"
    fi
  done
fi

# Informative: the core units present here, which this script never touches.
core_here=""
for f in "${SYSTEMD_DIR}"/vpt-*.service; do
  [[ -f "${f}" ]] || continue
  u="$(basename "${f}" .service)"; u="${u#vpt-}"
  is_core_unit "${u}" && core_here+="vpt-${u}.service "
done
echo "core units (never touched): ${core_here:-(none installed)}"

verb_r="rendered"; verb_d="removed"; ${DRY_RUN} && { verb_r="would-render"; verb_d="would-remove"; }
echo "reconcile summary${DRY_TAG}: ${verb_r}=${#INSTALLED[@]}${INSTALLED[*]:+ (${INSTALLED[*]})} ${verb_d}=${#REMOVED[@]}${REMOVED[*]:+ (${REMOVED[*]})} unchanged=${unchanged} problems=${#FAIL[@]}"
if [[ ${#FAIL[@]} -gt 0 ]]; then
  for f in "${FAIL[@]}"; do echo "  PROBLEM: ${f}"; done
  exit 1
fi
exit 0
