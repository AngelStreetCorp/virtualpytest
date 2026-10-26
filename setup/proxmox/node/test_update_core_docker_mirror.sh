#!/usr/bin/env bash
# Checks that the docker-stack push mirrors the tree instead of merging into it.
#
# The stack checkout is a mirror of the repo tree. When the push did NOT delete what upstream
# removed, a file that upstream renamed stayed on the stack and shadowed its replacement: a stale
# `Navigation_ItemStyle.ts` next to the new `Navigation_ItemStyle.tsx` made vite resolve the old
# one, so the gcloud standalone frontend image build failed and the stack stayed on an Oct-22
# image for three days (2026-10-25). The host push (rsync_push) always mirrored; the stacks did not.
#
# This harness NEVER deploys and never contacts a host: the rsync call is extracted from the
# script, the transport is replaced by a local copy, and it runs against a fixture tree.
#
# It checks:
#   - a file upstream removed is gone from the stack checkout afterwards,
#   - a file upstream renamed no longer shadows its replacement,
#   - the stack's own files survive: its compose override, its .env backups, the excluded paths
#     (the generated docs mirror, dist, node_modules),
#   - an upstream file still lands.
#
# It also checks that the background image build appends to its log instead of truncating it:
# two scopes of the same version share one log name, and the second run used to erase the first
# one's output, which is how a failing build stayed invisible.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC="${UPDATE_CORE:-${here}/update_core.sh}"
fails=0
checks=0

die() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok   $*"; checks=$((checks+1)); }
fail() { echo "FAIL $*"; fails=$((fails+1)); }

[[ -f "${UC}" ]] || die "no deploy script at ${UC}"
command -v rsync >/dev/null || die "rsync is needed to run this harness"
tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT

# ---- extract the two blocks the check needs ----
a="$(grep -n '^RSYNC_EXCLUDES=(' "${UC}" | head -1 | cut -d: -f1)"
[[ -n "${a}" ]] || die "RSYNC_EXCLUDES is not in ${UC}"
b="$(awk -v s="${a}" 'NR>s && /^\)$/{print NR; exit}' "${UC}")"
[[ -n "${b}" ]] && (( b > a )) || die "the RSYNC_EXCLUDES block is not closed in ${UC}"
sed -n "${a},${b}p" "${UC}" > "${tmp}/excludes.sh"

c="$(grep -n '^docker_deploy() {' "${UC}" | head -1 | cut -d: -f1)"
[[ -n "${c}" ]] || die "docker_deploy is not in ${UC}"
d="$(awk -v s="${c}" 'NR>s && /^\}$/{print NR; exit}' "${UC}")"
[[ -n "${d}" ]] && (( d > c )) || die "docker_deploy is not closed in ${UC}"
sed -n "${c},${d}p" "${UC}" > "${tmp}/docker_deploy.sh"

# ---- the fixture: an upstream tree and a stack checkout that drifted ----
src="${tmp}/src"; dst="${tmp}/dst"
mkdir -p "${src}/frontend/src/components/common" "${src}/setup/docker" "${src}/backend_host/src"
mkdir -p "${dst}/frontend/src/components/common" "${dst}/setup/docker" "${dst}/backend_host/src"
mkdir -p "${dst}/frontend/public/docs" "${dst}/frontend/dist" "${dst}/frontend/node_modules"

# upstream: the renamed file is a .tsx now, the old .ts is gone
: > "${src}/frontend/src/components/common/Navigation_ItemStyle.tsx"
: > "${src}/setup/docker/docker-compose.yml"
: > "${src}/backend_host/src/app.py"
# the stack: the stale .ts shadows the .tsx, plus the stack's own files
: > "${dst}/frontend/src/components/common/Navigation_ItemStyle.ts"
: > "${dst}/setup/docker/docker-compose.gcloud.yml"
: > "${dst}/setup/docker/.env.bak-2026-09-27-auth"
: > "${dst}/backend_host/src/.env.bak-20261015-0950"
: > "${dst}/frontend/public/docs/generated.md"
: > "${dst}/frontend/dist/index.html"
: > "${dst}/frontend/node_modules/left-pad.js"
: > "${dst}/upstream-removed.txt"

# ---- the harness: the transport is a local copy, nothing leaves the temp dir ----
cat > "${tmp}/run.sh" <<'EOS'
set -uo pipefail
source "${EXCLUDES}"
progress() { :; }
run_ssh() { :; }
build_ssh_target() { printf '%s\n' "stack"; }
SSH_OPTS="-o BatchMode=yes"
rsync() {   # same call, local destination, no ssh
  local -a args=()
  local dest=""
  while (( $# )); do
    case "$1" in
      -e) shift 2 ;;
      -*) args+=("$1"); shift ;;
      *:*) dest="${1#*:}"; shift ;;
      *) args+=("$1"); shift ;;
    esac
  done
  command rsync "${args[@]}" "${dest}"
}
REPO_DIR="${SRC}"
DOCKER_DIR="${DST}"
source "${FUNC}"
docker_deploy "stack" frontend
EOS
OUT="$(EXCLUDES="${tmp}/excludes.sh" FUNC="${tmp}/docker_deploy.sh" SRC="${src}" DST="${dst}" bash "${tmp}/run.sh" 2>&1)"; RC=$?
(( RC == 0 )) || { fail "docker_deploy did not run (rc ${RC})"; echo "${OUT}" | sed 's/^/     | /'; }

exists() { [[ -e "$1" ]] && { ok "$2"; return 0; } || { fail "$2 (missing $1)"; return 1; }; }
gone()   { [[ -e "$1" ]] && { fail "$2 (still there: $1)"; return 1; } || { ok "$2"; return 0; }; }

# ---- what the mirror must fix ----
gone "${dst}/frontend/src/components/common/Navigation_ItemStyle.ts" "the stale .ts no longer shadows the .tsx"
gone "${dst}/upstream-removed.txt" "a file upstream removed is gone from the stack"

# ---- what the mirror must not touch ----
exists "${dst}/setup/docker/docker-compose.gcloud.yml" "the stack's compose override survives"
exists "${dst}/setup/docker/.env.bak-2026-09-27-auth" "the stack's .env backup survives"
exists "${dst}/backend_host/src/.env.bak-20261015-0950" "the stack's backend .env backup survives"
exists "${dst}/frontend/public/docs/generated.md" "the generated docs mirror survives"
exists "${dst}/frontend/dist/index.html" "the stack's dist survives"
exists "${dst}/frontend/node_modules/left-pad.js" "the stack's node_modules survives"

# ---- what the push must still do ----
exists "${dst}/frontend/src/components/common/Navigation_ItemStyle.tsx" "the upstream .tsx landed"
exists "${dst}/backend_host/src/app.py" "an upstream file landed"

# ---- the background build log must not be truncated ----
if grep -qF '>> "\${log}"' "${tmp}/docker_deploy.sh"; then
  ok "the background build appends to its log"
else
  fail "the background build still truncates its log"
fi

echo "checks: ${checks}, failures: ${fails}"
(( fails == 0 )) || exit 1
