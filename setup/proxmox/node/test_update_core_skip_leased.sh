#!/usr/bin/env bash
# Dry check of update_core.sh's host selection (--hosts / --skip-hosts / --skip-leased) and the lease-resource
# computation. NEVER deploys: the script is cut just before its first real step ("Restart-only mode"), a state
# line is appended, and it runs with HOME pointing at a temp dir whose ~/bin/vpt-lease is the real registry CLI
# on a temp lease dir.
#   VPT_LEASE_BIN=/path/to/vpt-lease  (default ~/.claude/skills/deploy/vpt-lease; the test skips if absent)
#   UPDATE_CORE=/path/to/update_core.sh  (default: the one next to this file; point it at a live copy to check it)
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC="${UPDATE_CORE:-${here}/update_core.sh}"
LEASE_BIN="${VPT_LEASE_BIN:-${HOME}/.claude/skills/deploy/vpt-lease}"
[[ -f "${LEASE_BIN}" ]] || { echo "SKIP: no vpt-lease at ${LEASE_BIN}"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "${tmp}"' EXIT
mkdir -p "${tmp}/home/bin" "${tmp}/leases"
ln -s "${LEASE_BIN}" "${tmp}/home/bin/vpt-lease"
export VPT_LEASE_DIR="${tmp}/leases"
n="$(grep -n -m1 -E '^# ---- (Restart-only mode|Deploy ledger:)' "${UC}" | cut -d: -f1)"   # older node copies have no restart-only block
[[ -n "${n}" ]] || { echo "FAIL: neither '# ---- Restart-only mode' nor '# ---- Deploy ledger' found in ${UC}"; exit 1; }
head -n "$((n-1))" "${UC}" | sed 's/^HOST_IPS=.*/HOST_IPS="host-a,Host-B,vpt-c"/; s/^RUNNER_IPS=.*/RUNNER_IPS=""/; s/^HOST_WINDOWS_IPS=.*/HOST_WINDOWS_IPS=""/' > "${tmp}/uc.sh"
cat >> "${tmp}/uc.sh" <<'TAIL'
echo "STATE server=${DEPLOY_SERVER} frontend=${DEPLOY_FRONTEND} hosts=${DEPLOY_HOSTS} HOST_IPS=${HOST_IPS} RES=${LEASE_RESOURCES[*]}"
exit 0
TAIL
V=(python3 "${LEASE_BIN}")
fails=0
run() { OUT="$(LEASE_ENV=node1-vpt HOME="${tmp}/home" VPT_LEASE_AGENT=update_core:test bash "${tmp}/uc.sh" "$@" 2>&1)"; RC=$?; }
reset() { rm -f "${tmp}"/leases/*.json "${tmp}"/leases/*.jsonl; }
ok() { # ok <name> <rc> <pattern that must match OUT> [more patterns...]
  local name="$1" rc="$2"; shift 2
  local bad=""
  [[ "${RC}" == "${rc}" ]] || bad="rc ${RC} != ${rc}"
  for pat in "$@"; do
    if [[ "${pat}" == '!'* ]]; then grep -qE -- "${pat:1}" <<< "${OUT}" && bad="${bad}; unexpected /${pat:1}/"
    else grep -qE -- "${pat}" <<< "${OUT}" || bad="${bad}; missing /${pat}/"; fi
  done
  if [[ -z "${bad}" ]]; then echo "ok   ${name}"; else echo "FAIL ${name}: ${bad}"; echo "${OUT}" | sed 's/^/     | /'; fails=$((fails+1)); fi
}
last_is() { [[ "$(tail -n1 <<< "${OUT}")" == "$1" ]]; }

reset; run
ok "no flags: unchanged" 0 'HOST_IPS=host-a,Host-B,vpt-c' 'RES=\*$' '!SKIPPED'
reset; run --skip-hosts host-b
ok "--skip-hosts drops (case-insensitive)" 0 'HOST_IPS=host-a,vpt-c ' 'Hosts: skipping host-b'
reset; run --hosts vpt-c,host-a
ok "--hosts: only those, host scope" 0 'server=false frontend=false hosts=true HOST_IPS=host-a,vpt-c' 'RES=host-a vpt-c$'
reset; run --hosts nope
ok "--hosts unknown name aborts" 1 'ABORT: --hosts names not in'
reset; run --server --hosts host-a
ok "--hosts with --server keeps both" 0 'server=true .*HOST_IPS=host-a ' 'RES=\*$'

# --skip-leased
reset; "${V[@]}" claim e2 x --agent z >/dev/null; run --skip-leased
ok "skip-leased, nothing leased here: no skip" 0 'HOST_IPS=host-a,Host-B,vpt-c' '!SKIPPED'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind host >/dev/null; run --skip-leased
ok "skip-leased: host-kind lease skipped, server goes ahead" 0 'SKIPPED \(leased by mac:m\): host-a' 'HOST_IPS=Host-B,vpt-c ' 'FREE'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind maintenance >/dev/null; run --skip-leased
ok "old alias maintenance: skip-leased: host-kind lease skipped, server goes ahead" 0 'SKIPPED \(leased by mac:m\): host-a' 'HOST_IPS=Host-B,vpt-c ' 'FREE'
last_is "STATE server=true frontend=true hosts=true HOST_IPS=Host-B,vpt-c RES=Host-B vpt-c frontend" || true
reset; "${V[@]}" claim node1-vpt vpt-c/stb1 --agent mac:m --kind host >/dev/null; run --skip-leased
ok "skip-leased: a device lease under a host skips the host" 0 'SKIPPED \(leased by mac:m\): vpt-c' 'HOST_IPS=host-a,Host-B '
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --skip-leased
ok "skip-leased: a run lease still blocks the server" 3 'SKIPPED \(leased by mac:m\): host-a' 'ABORT: agents are using' '!SKIPPED_HOSTS='
reset; "${V[@]}" claim node1-vpt '*' --agent mac:m --kind host >/dev/null; run --skip-leased
ok "skip-leased: an env-wide lease blocks" 3 'ABORT'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --host --skip-leased
ok "skip-leased --host: run lease on a host is just skipped" 0 'SKIPPED \(leased by mac:m\): host-a' 'HOST_IPS=Host-B,vpt-c ' 'server=false'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m >/dev/null; run --host --hosts host-a --skip-leased
ok "skip-leased: everything leased -> nothing to deploy, exit 0" 0 'Nothing left to deploy' 'SKIPPED \(leased by mac:m\): host-a' '!STATE'
last_is "SKIPPED_HOSTS=host-a" && echo "ok   SKIPPED_HOSTS is the last line (all leased)" || { echo "FAIL last line: $(tail -n1 <<< "${OUT}")"; fails=$((fails+1)); }
reset; "${V[@]}" claim node1-vpt host-a vpt-c --agent mac:m --kind host >/dev/null; run --skip-leased
[[ "$(grep -c '^SKIPPED_HOSTS=' <<< "${OUT}")" == 1 ]] && echo "ok   exactly one SKIPPED_HOSTS line" || { echo "FAIL SKIPPED_HOSTS count"; fails=$((fails+1)); }
ok "skip-leased: two hosts" 0 'SKIPPED_HOSTS=host-a,vpt-c|SKIPPED_HOSTS=vpt-c,host-a|STATE'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --frontend --skip-leased
ok "skip-leased --frontend: host leases irrelevant" 0 'server=false frontend=true hosts=false' '!SKIPPED'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m >/dev/null; run
ok "without --skip-leased a host lease blocks the full deploy as before" 3 'ABORT'
reset; run --force --skip-leased
ok "unreachable-free path with --force" 0 'STATE'

# --restart of a fast background service needs no lease; vpt-stream / all aux still do
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --restart vpt-archiver
ok "--restart vpt-archiver: no lease check, not blocked" 0 'restart of vpt-archiver only: no lease needed' '!ABORT'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --restart vpt-avq
ok "--restart vpt-avq: free too" 0 'no lease needed'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --restart vpt-stream
ok "--restart vpt-stream: still blocked by a lease" 3 'ABORT' '!no lease needed'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --restart
ok "--restart (all aux, includes vpt-stream): still blocked" 3 'ABORT'
reset; "${V[@]}" claim node1-vpt host-a --agent mac:m --kind server >/dev/null; run --host --restart vpt-archiver
ok "--host deploy + restart: still blocked (vpt-host restarts)" 3 'ABORT'

# ---- per-target deploy ledger: one failed host must not mark everything failed ----
a="$(grep -n '^DEPLOY_T0=' "${UC}" | head -1 | cut -d: -f1)"; b="$(grep -n '^deploy_exit_hook() {' "${UC}" | head -1 | cut -d: -f1)"
if [[ -z "${a}" || -z "${b}" ]]; then echo "FAIL: ledger block not found in ${UC}"; fails=$((fails+1)); else
sed -n "${a},$((b-1))p" "${UC}" > "${tmp}/ledger.sh"
cat > "${tmp}/ledger_run.sh" <<'EOS'
set -u
DEPLOY_SERVER=true; DEPLOY_FRONTEND=true; DEPLOY_HOSTS=true; DEPLOY_HOSTS_WINDOWS=false
HOST_IPS="h1,h2,h3"; RUNNER_IPS=""; HOST_WINDOWS_IPS=""
LEASE_ENV=e; LEASE_REGISTRY_HOST=""; DEPLOY_AGENT=test:agent; DEPLOY_BRANCH=main; REPO_DIR=/nonexistent
DEPLOY_OK_ROLE=(); DEPLOY_FAIL_ROLE=(); SKIPPED_HOSTS=()
lease_cmd() { python3 "${LEASE_BIN}" "$@"; }
source "${LEDGER}"
eval "$SETUP"
record_deploy_ledger "${RC}"
EOS
led() { # led <rc> <setup...>: run the ledger with the given role arrays
  RC="$1" SETUP="$2" LEDGER="${tmp}/ledger.sh" LEASE_BIN="${LEASE_BIN}" bash "${tmp}/ledger_run.sh"; }
last() { python3 "${LEASE_BIN}" deploy last --json | python3 -c "import json,sys; m=json.load(sys.stdin)['envs'].get('e',{}); print(' '.join(f'{k}={\"FAILED\" if \"lastAttempt\" in v else (\"done\" if v.get(\"at\") else \"-\")}' for k,v in sorted(m.items())))"; }
reset
led 1 'DEPLOY_OK_ROLE=(server:s1 frontend:f1 host:h1 host:h3); DEPLOY_FAIL_ROLE=(host:h2); SKIPPED_HOSTS=(h4)'
got="$(last)"
want="frontend=done h1=done h2=FAILED h3=done server=done"
if [[ "${got}" == "${want}" ]]; then echo "ok   ledger: one failed host, the rest recorded done (leased host untouched)"; else echo "FAIL ledger: got '${got}' want '${want}'"; fails=$((fails+1)); fi
grep -q '"skippedHosts": \["h4"\]' "${VPT_LEASE_DIR}/deploys.jsonl" && echo "ok   ledger: skipped host kept in the audit row" || { echo "FAIL ledger: skippedHosts missing"; fails=$((fails+1)); }
reset
led 1 'DEPLOY_OK_ROLE=(); DEPLOY_FAIL_ROLE=(server:s1)'
got="$(last)"; [[ "${got}" == "server=FAILED" ]] && echo "ok   ledger: server failed, nothing else attempted -> only the server marked" || { echo "FAIL ledger stop-early: '${got}'"; fails=$((fails+1)); }
reset
led 1 'DEPLOY_OK_ROLE=(); DEPLOY_FAIL_ROLE=()'
got="$(last)"; [[ "${got}" == *"server=FAILED"* && "${got}" == *"h2=FAILED"* ]] && echo "ok   ledger: no per-target info -> every intended target failed (as before)" || { echo "FAIL ledger fallback: '${got}'"; fails=$((fails+1)); }
reset
led 0 'DEPLOY_OK_ROLE=(server:s1 frontend:f1 host:h1 host:h2 host:h3)'
got="$(last)"; [[ "${got}" == "frontend=done h1=done h2=done h3=done server=done" ]] && echo "ok   ledger: clean run all done" || { echo "FAIL ledger clean: '${got}'"; fails=$((fails+1)); }
fi

echo
(( fails == 0 )) && echo "all update_core skip-leased checks passed" || { echo "${fails} FAILED"; exit 1; }
