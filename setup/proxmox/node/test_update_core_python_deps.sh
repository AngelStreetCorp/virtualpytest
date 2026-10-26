#!/usr/bin/env bash
# Dry check of update_core.sh's Python-dependency step: the pins a server deploy installs when the
# venv on the target does not have the version the repository declares.
#
# NEVER deploys and never touches a real host: the script is cut just before its first real step
# ("Restart-only mode"), the ssh helpers are replaced by stubs that only record their calls, and
# REPO_DIR points at a temp tree with a fake requirements file.
#
#   UPDATE_CORE=/path/to/update_core.sh  (default: the one next to this file)
#
# What this protects (BUG-0946, 2026-10-26): a server deploy shipped the code but never installed
# the Python packages, so a pinned dependency changed in the repository and the running service kept
# the old one. A critical certifi bump was in the tree for months and the trust store on the live
# servers never moved.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC="${UPDATE_CORE:-${here}/update_core.sh}"

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
mkdir -p "${tmp}/home/bin" "${tmp}/home/leases" "${tmp}/repo/backend_server"

# The cut script claims a lease before it reaches the tail, and it fails closed when it cannot.
# The frozen lease CLI in fixtures/ keeps its registry in a local directory (VPT_LEASE_DIR), so the
# claim below never reaches the shared registry. This harness must not skip in CI: a skipped check
# is a green run that tested nothing.
LEASE_BIN="${here}/fixtures/vpt-lease"
if [[ ! -f "${LEASE_BIN}" ]] || ! grep -q "VPT_LEASE_DIR" "${LEASE_BIN}" 2>/dev/null; then
  if [[ "${CI:-}" == "true" || "${GITHUB_ACTIONS:-}" == "true" ]]; then
    echo "FAIL: no usable lease CLI at ${LEASE_BIN} (it must support VPT_LEASE_DIR)"; exit 1
  fi
  echo "SKIP: no usable lease CLI at ${LEASE_BIN}. Not CI, so this is a skip, not a pass."
  exit 0
fi
ln -s "${LEASE_BIN}" "${tmp}/home/bin/vpt-lease"

# A fake requirements file: two exact pins, two ranges, one range with an environment marker.
cat > "${tmp}/repo/backend_server/requirements.txt" <<'REQ'
# Backend Server Dependencies
Flask>=2.3.0
requests==2.33.0
certifi==2026.10.19
pydantic-core==2.33.2
typing-extensions==4.16.0
gunicorn>=21.0.0; platform_system != "Windows"
REQ

n="$(grep -n -m1 -E '^# ---- (Restart-only mode|Deploy ledger:)' "${UC}" | cut -d: -f1)"
[[ -n "${n}" ]] || { echo "FAIL: no '# ---- Restart-only mode' marker in ${UC}"; exit 1; }
head -n "$((n-1))" "${UC}" > "${tmp}/uc.sh"
cat >> "${tmp}/uc.sh" <<'TAIL'
# ---- the Python pin logic, with the ssh helpers stubbed out ----
# The stub EATS stdin, the way ssh does when it forwards the loop's input to the remote command.
# A real ssh that consumed the loop's input would make the loop stop after the first package, and
# the deploy would quietly install one pin out of seven.
run_ssh() { cat >/dev/null 2>&1; echo "SSH $*" >> "${TEST_SSH_LOG}"; return 0; }
read_remote() { printf '%s' "${TEST_FREEZE}"; }
echo "PINS [$(pins_to_install "${TEST_FREEZE}" | tr '\n' ' ')]"
: > "${TEST_SSH_LOG}"
install_server_python_pins "host-a" "${TEST_FREEZE}" >/dev/null 2>&1
echo "INSTALL_RC $?"
echo "CALLS"
cat "${TEST_SSH_LOG}" 2>/dev/null
exit 0
TAIL

fails=0
run() {   # run <freeze text>
  OUT="$(REPO_DIR="${tmp}/repo" TEST_FREEZE="$1" TEST_SSH_LOG="${tmp}/ssh.log" HOME="${tmp}/home" PATH="${tmp}/home/bin:${PATH}" VPT_LEASE_DIR="${tmp}/leases" bash "${tmp}/uc.sh" 2>&1)"; RC=$?
}
ok() {   # ok <name> <rc> <pattern that must match OUT> [...]
  local name="$1" rc="$2"; shift 2
  local bad=""
  [[ "${RC}" == "${rc}" ]] || bad="rc ${RC} != ${rc}"
  for pat in "$@"; do
    if [[ "${pat}" == '!'* ]]; then grep -qE -- "${pat:1}" <<< "${OUT}" && bad="${bad}; unexpected /${pat:1}/"
    else grep -qE -- "${pat}" <<< "${OUT}" || bad="${bad}; missing /${pat}/"; fi
  done
  if [[ -z "${bad}" ]]; then echo "ok   ${name}"; else echo "FAIL ${name}: ${bad}"; echo "${OUT}" | sed 's/^/     | /'; fails=$((fails+1)); fi
}

# A venv that has every pin at the right version; each case below changes exactly one thing.
CURRENT="requests==2.33.0,certifi==2026.10.19,pydantic_core==2.33.2,typing_extensions==4.16.0"

# The venv is behind on certifi and current on everything else: only certifi is installed.
run "requests==2.33.0,certifi==2025.8.3,pydantic_core==2.33.2,typing_extensions==4.16.0"
ok "a pin the venv is behind on is installed" 0 'PINS \[certifi==2026\.10\.19 \]' \
  'INSTALL_RC 0' 'SSH .*pip install .*certifi==2026\.10\.19'
ok "a pin the venv already has is left alone" 0 '!SSH .*pip install .*requests==2\.33\.0'
ok "a range is never installed by the deploy" 0 '!SSH .*Flask' '!SSH .*gunicorn'
ok "the venv ownership is put back before installing" 0 'SSH .*chown -R vpt_user:vpt_user /opt/virtualpytest/venv'

# The venv already has everything: nothing is installed and no ssh call is made at all.
run "${CURRENT}"
ok "an up-to-date venv installs nothing" 0 'PINS \[\]' 'INSTALL_RC 0' '!SSH .*pip install'

# Nothing is installed at all (a fresh venv): every exact pin is installed.
run ""
ok "a venv with nothing in it gets every exact pin" 0 \
  'PINS \[certifi==2026\.10\.19 pydantic-core==2\.33\.2 requests==2\.33\.0 typing-extensions==4\.16\.0 \]' \
  'SSH .*certifi==2026\.10\.19' 'SSH .*requests==2\.33\.0'
# Every pin behind is installed, not only the first one: ssh eats the loop's stdin unless it is
# closed, and then the loop stops after the first package and the deploy reports success anyway.
n_installed="$(grep -c 'pip install' <<< "${OUT}")"
[[ "${n_installed}" == 4 ]] && echo "ok   every pin behind is installed, not only the first" \
  || { echo "FAIL every pin behind is installed: ${n_installed} install(s), expected 4"; fails=$((fails+1)); }

# The comparison is case-insensitive on the package name, like pip itself.
run "Certifi==2026.10.19,requests==2.33.0,pydantic_core==2.33.2,typing_extensions==4.16.0"
ok "the package name is compared case-insensitively" 0 'PINS \[\]' '!SSH .*pip install'

# pip spells a distribution the way the wheel does (pydantic_core), the repository pins it the way
# PyPI normalises it (pydantic-core). Without the normalisation every underscored package looks
# missing and is reinstalled on every deploy.
run "${CURRENT}"
ok "an underscored distribution name matches the normalised pin" 0 'PINS \[\]' '!SSH .*pip install'
run "requests==2.33.0,certifi==2026.10.19,pydantic_core==2.33.2,typing_extensions==4.15.0"
ok "an underscored distribution that is behind is still installed" 0 'PINS \[typing-extensions==4\.16\.0 \]' \
  'SSH .*pip install .*typing-extensions==4\.16\.0' '!SSH .*pydantic-core'

if [[ "${fails}" == 0 ]]; then echo "all python-dependency checks passed"; exit 0; fi
echo "${fails} check(s) failed"; exit 1
