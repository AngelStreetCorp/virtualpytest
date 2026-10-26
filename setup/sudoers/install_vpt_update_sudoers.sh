#!/usr/bin/env bash
# install_vpt_update_sudoers.sh - install the rights the Platform update needs on this machine (TASK-101).
#
#   sudo bash /opt/virtualpytest/setup/sudoers/install_vpt_update_sudoers.sh [--project-root /opt/virtualpytest]
#
# Installs, all root:root:
#   /usr/local/sbin/vpt-reconcile-feature-units   0755  copy of setup/proxmox/node/reconcile_feature_units.sh
#   /usr/local/lib/vpt-update/feature_units.sh    0644  copy of setup/proxmox/node/lib/feature_units.sh
#   /etc/sudoers.d/vpt-update                     0440  setup/sudoers/vpt-update, validated with visudo -cf
# The sudoers rule names the root-owned copy, never a file under the project tree (the service user owns
# that tree). Idempotent: run it again after an update of reconcile_feature_units.sh or feature_units.sh.
# Read the two source files before the first run: root will execute these copies.
set -euo pipefail

PROJECT_ROOT="/opt/virtualpytest"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)   [[ $# -gt 1 ]] || { echo "--project-root needs a value" >&2; exit 1; }; PROJECT_ROOT="$2"; shift ;;
    --project-root=*) PROJECT_ROOT="${1#--project-root=}" ;;
    -h|--help)        sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ "${EUID}" -eq 0 ]] || { echo "run as root: sudo bash $0" >&2; exit 1; }
[[ "${PROJECT_ROOT}" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "unsafe --project-root: ${PROJECT_ROOT}" >&2; exit 1; }

SCRIPT_SRC="${PROJECT_ROOT}/setup/proxmox/node/reconcile_feature_units.sh"
LIB_SRC="${PROJECT_ROOT}/setup/proxmox/node/lib/feature_units.sh"
DROPIN_SRC="${PROJECT_ROOT}/setup/sudoers/vpt-update"
HELPER="/usr/local/sbin/vpt-reconcile-feature-units"
LIB_DIR="/usr/local/lib/vpt-update"
DROPIN="/etc/sudoers.d/vpt-update"
for f in "${SCRIPT_SRC}" "${LIB_SRC}" "${DROPIN_SRC}"; do
  [[ -f "${f}" ]] || { echo "missing ${f}" >&2; exit 1; }
done
command -v visudo >/dev/null || { echo "visudo not found (install sudo)" >&2; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
# The drop-in is generated first and validated BEFORE anything is installed.
sed "s#/opt/virtualpytest#${PROJECT_ROOT}#g" "${DROPIN_SRC}" > "${tmp}/vpt-update"
visudo -cf "${tmp}/vpt-update" >/dev/null || { echo "the sudoers drop-in does not validate; nothing installed" >&2; exit 1; }

install -d -o root -g root -m 0755 "${LIB_DIR}"
install -o root -g root -m 0644 "${LIB_SRC}" "${LIB_DIR}/feature_units.sh"
install -o root -g root -m 0755 "${SCRIPT_SRC}" "${HELPER}"
install -o root -g root -m 0440 "${tmp}/vpt-update" "${DROPIN}"
visudo -cf "${DROPIN}"
echo "installed: ${HELPER}, ${LIB_DIR}/feature_units.sh, ${DROPIN}"
