#!/usr/bin/env bash
# build_customer_bundle.sh — offline deploy bundle for a customer without GitHub access.
#
#   Packs the MERGED tree that deploy_customer.sh would push (public core @ PIN − disabled
#   features + customer overlay + generated files: VERSION.txt identity, frontend/.env.local,
#   BUNDLE_MANIFEST.txt) into ONE archive that unpacks to a single `virtualpytest/` folder.
#   The customer uploads it to their storage VM, extracts it in place of ~/virtualpytest
#   and runs their update_core.sh as always (DEPLOY_CUSTOMER.md, "Deploying without
#   GitHub access"). Staging is deploy_customer.sh --stage-only (not duplicated here).
#
# Usage:
#   build_customer_bundle.sh [overlay_dir] [--pin <ref>] [--disabled-features a,b]
#                            [--out <dir>] [--zip] [--no-checkout] [--keep-stage]
#
#   [overlay_dir]    customer overlay clone (customer.conf); omitted = pure platform
#                    (PIN from --pin or ~/deploy.local.conf, as deploy_customer.sh)
#   --pin <ref>      public git ref to bundle (overrides the conf files)
#   --disabled-features a,b   features NOT bundled (overrides the conf files)
#   --out <dir>      where the archive is written (default: current directory)
#   --zip            produce a .zip instead of .tar.gz (for customers that expect a zip;
#                    tar.gz keeps modes/symlinks and is smaller)
#   --no-checkout    use REPO_DIR's working tree as is (no fetch/checkout of PIN)
#   --keep-stage     keep the temp staged tree (path printed)
#
# Output: <out>/vpt-<overlay|platform>-<version>.tar.gz or .zip (+ .sha256), where <overlay> is
#   the overlay folder name without its vpt-customer- prefix and <version> is the deployed
#   identity with '/' replaced by '_' (e.g. vpt-demo-main-2026.09.02-8549_demo-2026.09.02-1).
#   The archive contains no .git, node_modules, venv, __pycache__, frontend/dist and NO .env
#   of any kind except the overlay's frontend/.env.production (+ the generated
#   frontend/.env.local = VITE_DISABLED_FEATURES). Prints path, size, sha256.
#
# Environment: REPO_DIR (public checkout, default ~/virtualpytest) and everything
#   deploy_customer.sh honours (DEPLOY_LOCAL_CONF, TARGET_DIR ...). Never ssh-es anywhere.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="${HERE}/deploy_customer.sh"
[[ -f "${DEPLOY_SCRIPT}" ]] || { echo "missing ${DEPLOY_SCRIPT}" >&2; exit 1; }
REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"
export REPO_DIR

usage() { sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; }

OVERLAY_DIR=""
OUT_DIR="${PWD}"
KEEP_STAGE=false
ZIP=false
PASS=()   # forwarded to deploy_customer.sh
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)          [[ $# -gt 1 ]] || { echo "--out needs a value" >&2; exit 1; }; OUT_DIR="$2"; shift ;;
    --out=*)        OUT_DIR="${1#--out=}" ;;
    --zip)          ZIP=true ;;
    --keep-stage)   KEEP_STAGE=true ;;
    --no-checkout)  PASS+=("$1") ;;
    --pin|--disabled-features)
                    [[ $# -gt 1 ]] || { echo "$1 needs a value" >&2; exit 1; }; PASS+=("$1" "$2"); shift ;;
    --pin=*|--disabled-features=*) PASS+=("$1") ;;
    --help|-h)      usage; exit 0 ;;
    --*)            echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *)
      [[ -z "${OVERLAY_DIR}" ]] || { echo "Only one <overlay_dir> is supported. Got extra value: $1" >&2; exit 1; }
      OVERLAY_DIR="$1"
      ;;
  esac
  shift
done
if [[ -n "${OVERLAY_DIR}" ]]; then
  _ov="${OVERLAY_DIR}"
  OVERLAY_DIR="$(cd "${_ov}" 2>/dev/null && pwd)" || { echo "overlay dir not found: ${_ov}" >&2; exit 1; }
fi
mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"

# ---- 1. stage (deploy_customer.sh --stage-only) into <tmp>/virtualpytest ----
BUILD_TMP="$(mktemp -d "${TMPDIR:-/tmp}/vpt-bundle.XXXXXX")"
${KEEP_STAGE} || trap 'rm -rf "${BUILD_TMP}"' EXIT
STAGE_DIR="${BUILD_TMP}/virtualpytest"     # archive top-level folder name
export STAGE_DIR
STAGE_LOG="${BUILD_TMP}/stage.log"
echo "=== Stage (deploy_customer.sh --stage-only) ==="
set +e
bash "${DEPLOY_SCRIPT}" ${OVERLAY_DIR:+"${OVERLAY_DIR}"} --stage-only ${PASS[@]+"${PASS[@]}"} 2>&1 | tee "${STAGE_LOG}"
rc=${PIPESTATUS[0]}
set -e
[[ ${rc} -eq 0 ]] || { echo "staging failed (rc=${rc})" >&2; exit "${rc}"; }

# stage.<key>=<value> trailer of --stage-only
stage_val() { sed -n "s/^stage\.$1=//p" "${STAGE_LOG}" | tail -n 1; }
[[ "$(stage_val dir)" == "${STAGE_DIR}" ]] || { echo "stage dir mismatch: expected ${STAGE_DIR}, got '$(stage_val dir)'" >&2; exit 1; }
VERSION="$(stage_val version)"
PIN="$(stage_val pin)"
DISABLED="$(stage_val disabled_features)"
FEATURE_UNITS="$(stage_val feature_units)"
DISABLED_UNITS="$(stage_val disabled_feature_units)"
[[ -n "${VERSION}" && "${VERSION}" != unknown ]] || { echo "no version identity in the stage (VERSION.txt missing a current: line?)" >&2; exit 1; }

# ---- 2. manifest ----
vfield() { sed -n "s/^$1:[[:space:]]*//p" "${STAGE_DIR}/VERSION.txt" | head -n 1; }
core_ref="$(vfield core_ref)"                 # "<PIN> <sha>"
core_sha="${core_ref#* }"                     # staged commit (empty when core_ref is)
overlay_ref="$(vfield overlay_ref)"           # "<branch> <sha>" (overlay only)
platform_version="${VERSION%%/*}"
overlay_version=""; [[ "${VERSION}" == */* ]] && overlay_version="${VERSION#*/}"
if [[ -n "${OVERLAY_DIR}" ]]; then
  overlay_name="$(basename "${OVERLAY_DIR}")"
  short_name="${overlay_name#vpt-customer-}"
else
  overlay_name="(none — pure platform)"
  short_name="platform"
fi
enabled=""
for d in "${STAGE_DIR}"/features/*/; do
  [[ -f "${d}manifest.json" ]] && enabled+="$(basename "${d}") "
done
enabled="${enabled% }"
ARCHIVE_BASE="vpt-${short_name}-${VERSION//\//_}"
{
  echo "bundle: ${ARCHIVE_BASE}"
  echo "version: ${VERSION}"
  echo "built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "builder: $(hostname) ($(id -un))"
  echo "platform_ref: ${core_ref%% *}"
  echo "platform_sha: ${core_ref#* }"
  echo "platform_version: ${platform_version}"
  echo "overlay: ${overlay_name}"
  if [[ -n "${overlay_ref}" ]]; then
    echo "overlay_branch: ${overlay_ref%% *}"
    echo "overlay_sha: ${overlay_ref#* }"
  else
    echo "overlay_branch: (none)"
    echo "overlay_sha: (none)"
  fi
  echo "overlay_version: ${overlay_version:-(none)}"
  echo "disabled_features: ${DISABLED:-(none)}"
  echo "enabled_features: ${enabled:-(none)}"
  echo "feature_units: ${FEATURE_UNITS:-(none)}"
  echo "disabled_feature_units: ${DISABLED_UNITS:-(none)}"
  echo "deploy: extract next to your update_core.sh so it becomes ~/virtualpytest, then run update_core.sh (it calls setup/proxmox/node/reconcile_feature_units.sh on every host)"
} > "${STAGE_DIR}/BUNDLE_MANIFEST.txt"
echo -e "\n=== BUNDLE_MANIFEST.txt ==="
cat "${STAGE_DIR}/BUNDLE_MANIFEST.txt"

# ---- 3. guards: no .env, nothing heavy, reconcile script present ----
echo -e "\n=== Checks ==="
# Every .env* in the stage must be either the overlay's frontend/.env.production, the
# generated frontend/.env.local, or a file git-tracked in the public repo (the
# *.example / setup/docker/.env.docker templates — public by definition). A real .env is
# never tracked, so anything else here is a leak and aborts the build.
# The reference list comes from the COMMIT THAT WAS STAGED (core_ref's sha), not from
# REPO_DIR's working tree: staging restores the checkout to its previous branch before we
# get here, so `ls-files` would describe that branch instead and reject any template the
# pin carried but the branch has since deleted (BUG-0076).
tracked_env=""
if [[ -n "${core_sha:-}" && "${core_sha}" != unknown ]]; then
  tracked_env="$(git -C "${REPO_DIR}" ls-tree -r --name-only "${core_sha}" 2>/dev/null | grep -E '(^|/)\.env' || true)"
fi
[[ -n "${tracked_env}" ]] || tracked_env="$(git -C "${REPO_DIR}" ls-files | grep -E '(^|/)\.env' || true)"
bad_env=""
while IFS= read -r f; do
  [[ -n "${f}" ]] || continue
  case "${f}" in frontend/.env.production|frontend/.env.local) continue ;; esac
  printf '%s\n' "${tracked_env}" | grep -qx "${f}" || bad_env+="${f}"$'\n'
done < <(cd "${STAGE_DIR}" && find . -name '.env*' | sed 's|^\./||' | sort)
[[ -z "${bad_env}" ]] || { echo "ERROR: stage carries .env file(s) that are neither frontend/.env.production, frontend/.env.local nor git-tracked templates:" >&2; printf '  %s\n' ${bad_env} >&2; exit 1; }
for p in .git node_modules venv frontend/dist; do
  [[ ! -e "${STAGE_DIR}/${p}" ]] || { echo "ERROR: stage carries ${p}" >&2; exit 1; }
done
[[ -f "${STAGE_DIR}/setup/proxmox/node/reconcile_feature_units.sh" ]] \
  || echo "WARNING: setup/proxmox/node/reconcile_feature_units.sh is not in this tree (PIN predates it): feature units will not be reconciled on the hosts"
echo "env files in bundle: $(cd "${STAGE_DIR}" && ls frontend/.env.production frontend/.env.local 2>/dev/null | tr '\n' ' ')(no other .env* except the $(printf '%s\n' "${tracked_env}" | grep -c . || true) git-tracked templates)"
echo "reconcile script: $( [[ -f "${STAGE_DIR}/setup/proxmox/node/reconcile_feature_units.sh" ]] && echo present || echo ABSENT )"

# ---- 4. pack (tar.gz keeps modes + symlinks; --zip for customers that expect a zip) ----
PACK_EXCLUDES=(.git node_modules venv __pycache__ '*.pyc' '*.pyo' frontend/dist .DS_Store)
# Internal-only paths never reach a customer: the same deny-list the public snapshot uses
# (scripts/security/internal-paths.txt), read from the STAGED tree so it matches the PIN;
# a PIN that predates the file gets the frozen fallback. docs/tasks and docs/agent carry other
# customers' runbooks, pentest write-ups and the lab layout — the first package (TASK-13)
# shipped them (BUG-0088).
INTERNAL_PATHS_FILE="${STAGE_DIR}/scripts/security/internal-paths.txt"
if [[ -f "${INTERNAL_PATHS_FILE}" ]]; then
  while IFS= read -r ip; do
    ip="${ip%%#*}"; ip="${ip#"${ip%%[![:space:]]*}"}"; ip="${ip%"${ip##*[![:space:]]}"}"
    [[ -z "${ip}" ]] && continue
    PACK_EXCLUDES+=("${ip%/}")
  done < "${INTERNAL_PATHS_FILE}"
else
  PACK_EXCLUDES+=(docs/tasks docs/agent security_report 'docs/security/*.json' .claude .cursor .husky tests/backend_server/.env.test.jwt)
fi
echo -e "\n=== Pack ==="
if ${ZIP}; then
  command -v zip >/dev/null 2>&1 || { echo "ERROR: zip not installed" >&2; exit 1; }
  ARCHIVE="${OUT_DIR}/${ARCHIVE_BASE}.zip"
  zx=(); for e in "${PACK_EXCLUDES[@]}"; do zx+=(-x "virtualpytest/${e}" -x "virtualpytest/${e}/*" -x "virtualpytest/*/${e}" -x "virtualpytest/*/${e}/*" -x "*/${e}"); done
  rm -f "${ARCHIVE}"
  (cd "${BUILD_TMP}" && zip -qr -y "${ARCHIVE}" virtualpytest "${zx[@]}")
  list_archive() { unzip -Z1 "${ARCHIVE}"; }
else
  ARCHIVE="${OUT_DIR}/${ARCHIVE_BASE}.tar.gz"
  tx=(); for e in "${PACK_EXCLUDES[@]}"; do tx+=(--exclude="${e}"); done
  COPYFILE_DISABLE=1 tar "${tx[@]}" -czf "${ARCHIVE}" -C "${BUILD_TMP}" virtualpytest
  list_archive() { tar -tzf "${ARCHIVE}"; }
fi
tops="$(list_archive | awk -F/ '{ print $1 }' | sort -u | tr '\n' ' ')"
# Hard stop: an archive that still carries an internal folder is not a customer bundle.
leaked="$(list_archive | grep -E '^virtualpytest/(docs/tasks|docs/agent|security_report|\.claude|\.cursor|\.husky)(/|$)' | head -3 || true)"
if [[ -n "${leaked}" ]]; then
  echo "ERROR: internal paths in the archive (BUG-0088):" >&2; printf '  %s\n' ${leaked} >&2; rm -f "${ARCHIVE}"; exit 1
fi
[[ "${tops}" == "virtualpytest " ]] || { echo "ERROR: archive top-level is not a single virtualpytest/ folder: ${tops}" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then sum="$(sha256sum "${ARCHIVE}" | awk '{ print $1 }')"
else sum="$(shasum -a 256 "${ARCHIVE}" | awk '{ print $1 }')"; fi
printf '%s  %s\n' "${sum}" "$(basename "${ARCHIVE}")" > "${ARCHIVE}.sha256"
echo "archive: ${ARCHIVE}"
echo "size:    $(du -h "${ARCHIVE}" | awk '{ print $1 }') ($(list_archive | grep -vc '/$' || true) files)"
echo "sha256:  ${sum}  (also in ${ARCHIVE}.sha256)"
echo "version: ${VERSION}"
${KEEP_STAGE} && echo "stage kept at ${STAGE_DIR}"
exit 0
