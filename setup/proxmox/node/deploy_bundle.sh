#!/usr/bin/env bash
# deploy_bundle.sh — step 2 of a platform update: deploy EXACTLY the bundle that was built. TASK-99.
#
#   Checks the archive against its `.sha256`, backs up the current REPO_DIR, puts the bundle in
#   its place and runs update_core.sh on it. update_core.sh already knows this layout: a REPO_DIR
#   with BUNDLE_MANIFEST.txt and no .git is "bundle mode" (no git pull, frontend config of the
#   bundle re-included). This script adds what that mode lacks: integrity, backup, extraction.
#
# Usage:
#   deploy_bundle.sh <archive.zip|archive.tar.gz> [--replace-checkout] [update_core args...]
#
#   <archive>            built by build_customer_bundle.sh / customer_bundle.py; its
#                        `<archive>.sha256` must sit next to it (missing or wrong = refuse)
#   --replace-checkout   REPO_DIR is a git checkout (has .git): refuse unless this is given,
#                        so a developer's working tree is never replaced by accident
#   everything else      passed to update_core.sh as is (e.g. --server, --frontend, a target list)
#
# Order, and the guarantee: every check (sha256, archive paths, single top-level virtualpytest/
# folder, BUNDLE_MANIFEST.txt, no .git inside, checkout guard) runs BEFORE REPO_DIR is touched. The
# archive is extracted into a fresh sibling folder; only then is REPO_DIR renamed to
# `<REPO_DIR>.bak-<timestamp>` (the backup, kept) and the new tree renamed into place. If that
# second rename fails the backup is renamed back.
#
# Environment:
#   REPO_DIR            where the platform tree lives (default ~/virtualpytest, as update_core.sh)
#   VPT_LEASE_AGENT     the deploying agent's id for the lease registry; passed through untouched
#   VPT_UPDATE_CORE     the update_core.sh to run. Default: ~/update_core.sh when present (that copy
#                       keeps THIS node's own target lists), else the bundle's own copy
set -euo pipefail

usage() { sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "deploy_bundle: $*" >&2; exit 1; }

ARCHIVE="" REPLACE_CHECKOUT=false PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)          usage; exit 0 ;;
    --replace-checkout) REPLACE_CHECKOUT=true ;;
    *)
      if [[ -z "${ARCHIVE}" ]]; then
        [[ "$1" != -* ]] || die "unknown option before the archive: $1 (see --help)"
        ARCHIVE="$1"
      else
        PASS+=("$1")
      fi
      ;;
  esac
  shift
done
[[ -n "${ARCHIVE}" ]] || { usage >&2; exit 1; }

REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"
REPO_DIR="${REPO_DIR%/}"
export REPO_DIR

# ---- 1. integrity ----
[[ -f "${ARCHIVE}" ]] || die "archive not found: ${ARCHIVE}"
SUM_FILE="${ARCHIVE}.sha256"
[[ -f "${SUM_FILE}" ]] || die "no checksum file ${SUM_FILE} — refusing to deploy an unverified bundle"
expected="$(awk '{ print tolower($1); exit }' "${SUM_FILE}")"
[[ "${expected}" =~ ^[0-9a-f]{64}$ ]] || die "${SUM_FILE} does not hold a sha256"
if command -v sha256sum >/dev/null 2>&1; then actual="$(sha256sum "${ARCHIVE}" | awk '{ print $1 }')"
else actual="$(shasum -a 256 "${ARCHIVE}" | awk '{ print $1 }')"; fi
[[ "${actual}" == "${expected}" ]] || die "sha256 mismatch for ${ARCHIVE}: expected ${expected}, got ${actual}"
echo "sha256 ok: ${actual}"

# ---- 2. archive format and paths ----
case "${ARCHIVE}" in
  *.zip)            KIND=zip;  command -v unzip >/dev/null 2>&1 || die "unzip is not installed" ;;
  *.tar.gz|*.tgz)   KIND=tar ;;
  *)                die "unsupported archive (expected .zip or .tar.gz): ${ARCHIVE}" ;;
esac
list_archive() { if [[ "${KIND}" == zip ]]; then unzip -Z1 "${ARCHIVE}"; else tar -tzf "${ARCHIVE}"; fi; }
entries="$(list_archive)" || die "cannot read ${ARCHIVE}"
[[ -n "${entries}" ]] || die "${ARCHIVE} is empty"
# grep -q exits at the first match; with `printf | grep -q` under pipefail that is a SIGPIPE race
# (flaky "not a bundle" on a loaded machine) -> here-strings, no pipe.
if grep -Eq '^/|(^|/)\.\.(/|$)|\\' <<<"${entries}"; then
  die "${ARCHIVE} holds an absolute path, a '..' or a backslash — refusing"
fi
tops="$(printf '%s\n' "${entries}" | awk -F/ '{ print $1 }' | sort -u | tr '\n' ' ')"
[[ "${tops}" == "virtualpytest " ]] || die "archive top level is not a single virtualpytest/ folder: ${tops}"
grep -qx 'virtualpytest/BUNDLE_MANIFEST.txt' <<<"${entries}" || die "no BUNDLE_MANIFEST.txt in ${ARCHIVE} — not a bundle"
if grep -Eq '^virtualpytest/\.git(/|$)' <<<"${entries}"; then die "${ARCHIVE} carries a .git — not a bundle"; fi

# ---- 3. the checkout guard ----
if [[ -e "${REPO_DIR}/.git" ]] && ! ${REPLACE_CHECKOUT}; then
  die "${REPO_DIR} is a git checkout; replacing it needs --replace-checkout (it is kept as a backup)"
fi

# ---- 4. extract into a fresh sibling, verify, THEN swap ----
mkdir -p "$(dirname "${REPO_DIR}")"
INCOMING="$(mktemp -d "${REPO_DIR}.incoming.XXXXXX")"
trap 'rm -rf "${INCOMING}"' EXIT
if [[ "${KIND}" == zip ]]; then unzip -q "${ARCHIVE}" -d "${INCOMING}" || die "unzip failed"
else tar -xzf "${ARCHIVE}" -C "${INCOMING}" || die "tar failed"; fi
NEW="${INCOMING}/virtualpytest"
[[ -d "${NEW}" && -f "${NEW}/BUNDLE_MANIFEST.txt" ]] || die "extracted tree has no BUNDLE_MANIFEST.txt"
[[ ! -e "${NEW}/.git" ]] || die "extracted tree carries a .git"
[[ -f "${NEW}/setup/proxmox/node/update_core.sh" ]] || die "extracted tree has no setup/proxmox/node/update_core.sh"

BACKUP=""
if [[ -e "${REPO_DIR}" ]]; then
  BACKUP="${REPO_DIR}.bak-$(date +%Y%m%d-%H%M%S)"
  [[ ! -e "${BACKUP}" ]] || BACKUP="${BACKUP}-$$"
  mv "${REPO_DIR}" "${BACKUP}" || die "cannot move ${REPO_DIR} to ${BACKUP}"
  echo "backup: ${BACKUP}"
fi
if ! mv "${NEW}" "${REPO_DIR}"; then
  [[ -z "${BACKUP}" ]] || mv "${BACKUP}" "${REPO_DIR}"
  die "could not put the bundle in place; ${REPO_DIR} restored"
fi
rmdir "${INCOMING}" 2>/dev/null || true
echo "deployed tree: ${REPO_DIR}"
echo "=== BUNDLE_MANIFEST.txt ==="
cat "${REPO_DIR}/BUNDLE_MANIFEST.txt"

# ---- 5. update_core.sh on it ----
UPDATE_CORE="${VPT_UPDATE_CORE:-}"
if [[ -z "${UPDATE_CORE}" ]]; then
  if [[ -f "${HOME}/update_core.sh" ]]; then UPDATE_CORE="${HOME}/update_core.sh"
  else UPDATE_CORE="${REPO_DIR}/setup/proxmox/node/update_core.sh"; fi
fi
[[ -f "${UPDATE_CORE}" ]] || die "update_core.sh not found: ${UPDATE_CORE}"
echo "=== ${UPDATE_CORE} ${PASS[*]:-} ==="
trap - EXIT
# exec: the lease agent (VPT_LEASE_AGENT) and REPO_DIR travel in the environment, and the
# caller sees update_core.sh's own exit status.
exec bash "${UPDATE_CORE}" ${PASS[@]+"${PASS[@]}"}
