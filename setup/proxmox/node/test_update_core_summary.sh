#!/usr/bin/env bash
# Checks the deploy summary and the config block of update_core.sh:
#   - a host whose code was synced but whose restart was deferred is NOT reported under OK,
#   - DEPLOY_OK and DEPLOY_OK_ROLE still hold that host (the per-target ledger needs it),
#   - every host lands in exactly one row of the grouped "SKIPPED" view,
#   - the fleet targets are read from the environment, with today's template value as the default,
#   - the installer merges a fleet target by VALUE: 'KEY="${KEY:-<the node's value>}"'.
#
# NEVER deploys and never contacts a host: the summary block is cut out of the script and run
# against fixtures, and the installer is only asked to merge a local copy.
#   UPDATE_CORE=/path/to/update_core.sh            (default: the one next to this file)
#   INSTALLER=/path/to/install_update_core.py      (default: the one next to this file)
#
# Unlike test_update_core_skip_leased.sh this harness NEVER skips: a missing prerequisite, a
# missing marker or an extraction that fails is a FAIL, not a SKIP. A silent skip would look like a
# green test while nothing was checked.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC="${UPDATE_CORE:-${here}/update_core.sh}"
INSTALLER="${INSTALLER:-${here}/install_update_core.py}"
FLEET_KEYS=(SERVER_IP FRONTEND_IP HOST_IPS RUNNER_IPS HOST_WINDOWS_IPS DOCKER_IPS)
fails=0
checks=0

die() { echo "FAIL: $*"; exit 1; }          # a missing prerequisite: loud, never a skip
ok() { echo "ok   $*"; checks=$((checks+1)); }
fail() { echo "FAIL $*"; fails=$((fails+1)); }
check() {   # check <name> <pattern that must match OUT> [!pattern that must not match OUT]
  local name="$1"; shift
  local bad=""
  for pat in "$@"; do
    if [[ "${pat}" == '!'* ]]; then grep -qE -- "${pat:1}" <<< "${OUT}" && bad="${bad}; unexpected /${pat:1}/"
    else grep -qE -- "${pat}" <<< "${OUT}" || bad="${bad}; missing /${pat}/"; fi
  done
  if [[ -z "${bad}" ]]; then ok "${name}"; else fail "${name}: ${bad}"; echo "${OUT}" | sed 's/^/     | /'; fi
}
contains() {   # contains <name> <haystack> <needle>: the needle must be in the haystack
  local name="$1" hay="$2" needle="$3"
  if [[ "${hay}" == *"${needle}"* ]]; then ok "${name}"; else fail "${name}: '${needle}' not in '${hay}'"; fi
}
lacks() {      # lacks <name> <haystack> <needle>: the needle must NOT be in the haystack
  local name="$1" hay="$2" needle="$3"
  if [[ "${hay}" != *"${needle}"* ]]; then ok "${name}"; else fail "${name}: '${needle}' is in '${hay}'"; fi
}

[[ -f "${UC}" ]] || die "no deploy script at ${UC}"
[[ -f "${INSTALLER}" ]] || die "no installer at ${INSTALLER}"
command -v python3 >/dev/null || die "python3 is needed to run the installer"
tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT

# ---- the summary block ----
# The summary lives past the point where the skip-leased harness truncates the script, so it is
# cut out here the same way that harness cuts out the ledger block (sed between two markers).
a="$(grep -n '^# ---- Summary ----$' "${UC}" | head -1 | cut -d: -f1)"
b="$(grep -n '^# ---- Service restart summary' "${UC}" | head -1 | cut -d: -f1)"
[[ -n "${a}" && -n "${b}" ]] || die "the summary markers are not in ${UC}"
(( b > a )) || die "the summary markers are in the wrong order in ${UC}"
sed -n "${a},$((b-1))p" "${UC}" > "${tmp}/summary.sh"
grep -q '_sk_line' "${tmp}/summary.sh" || die "the summary block in ${UC} has no _sk_line helper"

cat > "${tmp}/summary_run.sh" <<'EOS'
set -u
DEPLOY_OK=(); DEPLOY_FAIL=(); DEPLOY_OK_ROLE=(); DEPLOY_FAIL_ROLE=()
DEFERRED_RESTARTS=(); SKIPPED_HOSTS=(); SKIPPED_BY=(); SYNC_LEASED=(); SYNC_LEASED_BY=()
DOWN_SKIPPED=(); PINNED_SKIPPED=(); UNREACHABLE_SKIPPED=(); HOST_RESTART_SKIPPED=()
DOCKER_STARTED=(); DOCKER_FAIL=()
UNIT_DRIFT_WARNINGS=""; OWNERSHIP_WARNINGS=""
eval "${FIXTURE}"
source "${SUMMARY}"
echo "STATE DEPLOY_OK=${DEPLOY_OK[*]} DEPLOY_OK_ROLE=${DEPLOY_OK_ROLE[*]}"
EOS

run_summary() {   # run_summary <fixture code>; sets OUT and RC
  OUT="$(FIXTURE="$1" SUMMARY="${tmp}/summary.sh" bash "${tmp}/summary_run.sh" 2>&1)"; RC=$?
}
ok_line() { grep -E '^  OK \(' <<< "${OUT}" | head -1; }

# ---- a host that was synced but whose restart was deferred ----
run_summary 'DEPLOY_OK=(host-a host-b); DEPLOY_OK_ROLE=(host:host-a host:host-b); DEFERRED_RESTARTS=(host-b); SKIPPED_HOSTS=(host-b); SKIPPED_BY=(other-agent)'
(( RC == 0 )) || { fail "the summary block did not run (rc ${RC})"; echo "${OUT}" | sed 's/^/     | /'; }
check "the deferred host is not reported under OK" '^  OK \(1\): +host-a$'
lacks "the OK line does not mention the deferred host" "$(ok_line)" "host-b"
check "the deferred host is listed as synced, restart deferred" 'synced, restart deferred: +host-b \(by other-agent\)'
lacks "the deferred host is not also listed as leased" "$(grep -E 'leased, catch-up queued' <<< "${OUT}")" "host-b"
check "the deferred host is counted once" '^  SKIPPED \(1, nothing failed\):$'
contains "DEPLOY_OK still holds the deferred host" "$(grep -E '^STATE ' <<< "${OUT}")" "DEPLOY_OK=host-a host-b"
contains "DEPLOY_OK_ROLE still holds the deferred host" "$(grep -E '^STATE ' <<< "${OUT}")" "host:host-b"

# ---- a host that was deployed, and a host that was only dropped ----
run_summary 'DEPLOY_OK=(host-a); DEPLOY_OK_ROLE=(host:host-a); SKIPPED_HOSTS=(host-c); SKIPPED_BY=(other-agent)'
(( RC == 0 )) || { fail "the summary block did not run (rc ${RC})"; echo "${OUT}" | sed 's/^/     | /'; }
check "a deployed host is reported under OK" '^  OK \(1\): +host-a$'
check "a dropped host is listed as leased, catch-up queued" 'leased, catch-up queued: +host-c \(by other-agent\)'
lacks "a dropped host is not listed as deferred" "${OUT}" "synced, restart deferred"
check "a dropped host is counted once" '^  SKIPPED \(1, nothing failed\):$'

# ---- the other skip reasons keep their own row ----
run_summary 'DEPLOY_OK=(host-a); DOWN_SKIPPED=(host-d); PINNED_SKIPPED=(host-e); UNREACHABLE_SKIPPED=(host-f)'
(( RC == 0 )) || { fail "the summary block did not run (rc ${RC})"; echo "${OUT}" | sed 's/^/     | /'; }
check "a host that is down on purpose keeps its row" 'down on purpose: +host-d'
check "a pinned host keeps its row" 'pinned, use --hosts: +host-e'
check "an unreachable host keeps its row" 'unreachable, no ssh: +host-f'
check "the three skipped hosts are counted" '^  SKIPPED \(3, nothing failed\):$'

# ---- the config block is env-driven ----
cfg="${tmp}/config.sh"
: > "${cfg}"
for key in "${FLEET_KEYS[@]}"; do
  line="$(grep -E "^${key}=" "${UC}" | head -1)"
  [[ -n "${line}" ]] || die "${key} is not in the config block of ${UC}"
  [[ "${line}" == *"\${${key}:-"* ]] || fail "${key} is not read from the environment: ${line}"
  echo "${line}" >> "${cfg}"
done
cat > "${tmp}/config_run.sh" <<'EOS'
set -u
source "${CFG}"
printf 'SERVER_IP=%s\nFRONTEND_IP=%s\nHOST_IPS=%s\nRUNNER_IPS=%s\nHOST_WINDOWS_IPS=%s\nDOCKER_IPS=%s\n' \
  "${SERVER_IP}" "${FRONTEND_IP}" "${HOST_IPS}" "${RUNNER_IPS}" "${HOST_WINDOWS_IPS}" "${DOCKER_IPS}"
EOS
defaults="$(env -u SERVER_IP -u FRONTEND_IP -u HOST_IPS -u RUNNER_IPS -u HOST_WINDOWS_IPS -u DOCKER_IPS \
  CFG="${cfg}" bash "${tmp}/config_run.sh" 2>&1)" || fail "the config block did not run"
overridden="$(env -u FRONTEND_IP -u HOST_IPS -u RUNNER_IPS -u HOST_WINDOWS_IPS -u DOCKER_IPS \
  SERVER_IP=10.99.0.1 CFG="${cfg}" bash "${tmp}/config_run.sh" 2>&1)" || fail "the config block did not run"
contains "the environment overrides the server target" "${overridden}" "SERVER_IP=10.99.0.1"
lacks "the environment override does not change the other targets" "${overridden}" "SERVER_IP=192.168.0.103"
# the defaults are the template values: the env-driven line must not have changed them
while IFS= read -r def; do
  key="${def%%=*}"; value="${def#*=}"
  contains "the default of ${key} is unchanged" "${defaults}" "${key}=${value}"
done <<< "$(python3 - "${UC}" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
for key in ("SERVER_IP", "FRONTEND_IP", "HOST_IPS", "RUNNER_IPS", "HOST_WINDOWS_IPS", "DOCKER_IPS"):
    match = re.search(rf'^{key}="\$\{{{key}:-(.*?)\}}"', text, re.M)
    print(f"{key}={match.group(1) if match else '<missing>'}")
PY
)"

# ---- the installer merges a fleet target by value ----
node_copy="${tmp}/node_copy.sh"
sed -e 's|^SERVER_IP=.*|SERVER_IP="10.99.0.1,fake-alpha"|' \
    -e 's|^FRONTEND_IP=.*|FRONTEND_IP="10.99.0.2"|' \
    -e 's|^HOST_IPS=.*|HOST_IPS="fake-host-a,fake-host-b"|' \
    -e 's|^RUNNER_IPS=.*|RUNNER_IPS=""|' \
    -e 's|^HOST_WINDOWS_IPS=.*|HOST_WINDOWS_IPS="fake-windows"|' \
    -e 's|^DOCKER_IPS=.*|DOCKER_IPS="fake-docker"|' \
    "${UC}" > "${node_copy}"
merged="$(python3 "${INSTALLER}" --print-merged "${node_copy}" 2>&1)" || fail "the installer did not merge the copy"
contains "the merged server target keeps the node's fleet as the default" "${merged}" 'SERVER_IP="${SERVER_IP:-10.99.0.1,fake-alpha}"'
contains "the merged frontend target keeps the node's fleet as the default" "${merged}" 'FRONTEND_IP="${FRONTEND_IP:-10.99.0.2}"'
contains "the merged host list keeps the node's fleet as the default" "${merged}" 'HOST_IPS="${HOST_IPS:-fake-host-a,fake-host-b}"'
contains "the merged runner list keeps the node's fleet as the default" "${merged}" 'RUNNER_IPS="${RUNNER_IPS:-}"'
contains "the merged windows list keeps the node's fleet as the default" "${merged}" 'HOST_WINDOWS_IPS="${HOST_WINDOWS_IPS:-fake-windows}"'
contains "the merged docker list keeps the node's fleet as the default" "${merged}" 'DOCKER_IPS="${DOCKER_IPS:-fake-docker}"'
lacks "the merged script does not carry the repo's template host list" "${merged}" 'HOST_IPS="${HOST_IPS:-192.168.0.109,192.168.0.110}"'

# a key the node does not set keeps the repo's line
node_without="${tmp}/node_without_docker.sh"
grep -v '^DOCKER_IPS=' "${node_copy}" > "${node_without}"
merged_without="$(python3 "${INSTALLER}" --print-merged "${node_without}" 2>&1)" || fail "the installer did not merge the copy"
repo_docker_line="$(grep -E '^DOCKER_IPS=' "${UC}" | head -1)"
contains "a key the node does not set keeps the repo's line" "${merged_without}" "${repo_docker_line}"

# a node value equal to the repo's default produces an unchanged line
node_same="${tmp}/node_same.sh"
sed -e 's|^SERVER_IP=.*|SERVER_IP="192.168.0.103"|' "${UC}" > "${node_same}"
merged_same="$(python3 "${INSTALLER}" --print-merged "${node_same}" 2>&1)" || fail "the installer did not merge the copy"
repo_server_line="$(grep -E '^SERVER_IP=' "${UC}" | head -1)"
contains "a node value equal to the repo default leaves the line unchanged" "${merged_same}" "${repo_server_line}"

# a node line that is not a plain value is kept verbatim
node_expr="${tmp}/node_expr.sh"
sed -e 's|^SERVER_IP=.*|SERVER_IP="$SOME_OTHER_VAR"|' "${UC}" > "${node_expr}"
merged_expr="$(python3 "${INSTALLER}" --print-merged "${node_expr}" 2>&1)" || fail "the installer did not merge the copy"
contains "a node line that is not a plain value is kept verbatim" "${merged_expr}" 'SERVER_IP="$SOME_OTHER_VAR"'

echo
(( checks > 0 )) || die "no check ran"
(( fails == 0 )) && echo "all update_core summary checks passed" || { echo "${fails} FAILED"; exit 1; }
