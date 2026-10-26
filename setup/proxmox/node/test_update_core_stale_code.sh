#!/usr/bin/env bash
# Checks the stale-code report of update_core.sh: after a deploy changes the host code, it names
# the services that are still running the code from before that deploy.
#
# NEVER deploys and never contacts a host: the report function is cut out of the script and run
# against a fake ssh output. The fake ssh output is fed through the REAL run_ssh, so the banner
# run_ssh prints before the ssh output ("==> [host] <cmd>", after a blank line) is part of what
# the parser has to cope with -- that is what made the first version of this report read the
# banner as a service named "==>" (2026-10-24).
#
#   UPDATE_CORE=/path/to/update_core.sh   (default: the one next to this file)
#
# Unlike test_update_core_skip_leased.sh this harness NEVER skips: a missing prerequisite or an
# extraction that fails is a FAIL, not a SKIP. A silent skip would look like a green test while
# nothing was checked.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UC="${UPDATE_CORE:-${here}/update_core.sh}"
fails=0
checks=0

die() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok   $*"; checks=$((checks+1)); }
fail() { echo "FAIL $*"; fails=$((fails+1)); }

[[ -f "${UC}" ]] || die "no deploy script at ${UC}"
TMP_OUT="$(mktemp)"; trap 'rm -f "${TMP_OUT}"' EXIT

# The function is cut out of the script the way the other harnesses cut their blocks out, so the
# test runs the code that is really there (and fails loudly when it is not).
extract() {   # extract <function name>
  awk -v fn="$1" '
    $0 ~ "^" fn "\\(\\) \\{" { p = 1 }
    p { print }
    p && /^\}/ { exit }
  ' "${UC}"
}
for fn in run_ssh report_stale_aux_services progress progress_json_escape; do
  body="$(extract "${fn}")"
  [[ -n "${body}" ]] || die "could not extract ${fn} from ${UC}"
  eval "${body}"
done

# ---- the stubs ----
build_ssh_target() { printf '%s\n' "$1"; }         # no ssh config needed
ssh() { printf '%s\n' "${FAKE_SSH_OUTPUT[@]}"; }   # the fake payload; run_ssh adds the banner
SSH_OPTS=""                                        # run_ssh expands it; nothing to connect to here
AUX_SERVICES=(vpt-stream vpt-monitor-img vpt-monitor-audio)
RESTART_SERVICE=""
PROGRESS_ROLE=host
DEPLOY_PHASE=host
STALE_AUX_SERVICES=()
# 2023-11-14 22:13:20 UTC. A service that started before this is on the previous code.
HOST_CODE_PUSHED_AT=1700000000

report() {   # report <name>: run the function with the current FAKE_SSH_OUTPUT
  NAME="$1"
  STALE_AUX_SERVICES=()
  # NOT a command substitution: the function fills STALE_AUX_SERVICES, and a subshell would throw
  # that away. The script calls it directly for the same reason.
  report_stale_aux_services "h1" > "${TMP_OUT}" 2>&1
  OUT="$(cat "${TMP_OUT}")"
}

contains() {   # contains <name> <haystack> <needle>
  if [[ "$2" == *"$3"* ]]; then ok "$1"; else fail "$1: '$3' not in the output"; echo "$OUT" | sed 's/^/     | /'; fi
}
lacks() {      # lacks <name> <haystack> <needle>
  if [[ "$2" != *"$3"* ]]; then ok "$1"; else fail "$1: '$3' IS in the output"; echo "$OUT" | sed 's/^/     | /'; fi
}
exact() {      # exact <name> <actual> <expected>
  if [[ "$2" == "$3" ]]; then ok "$1"; else fail "$1: got [$2] want [$3]"; fi
}

# ---- 1. the plain case: one stale, one fresh, one that is not running at all ----
FAKE_SSH_OUTPUT=(
  "vpt-stream 1699999999"        # started before the push  -> stale
  "vpt-monitor-img 1700000001"    # started after the push   -> fresh
  "vpt-monitor-audio 1699000000"  # started before the push  -> stale
)
report "plain"
exact "exactly the two stale services are named" \
  "${STALE_AUX_SERVICES[*]}" "h1:vpt-stream h1:vpt-monitor-audio"
contains "the stale service is reported" "$OUT" "vpt-stream is STILL RUNNING THE PREVIOUS CODE"
contains "the second stale service is reported" "$OUT" "vpt-monitor-audio is STILL RUNNING THE PREVIOUS CODE"
lacks "the fresh service is not reported" "$OUT" "vpt-monitor-img is STILL RUNNING"

# ---- 2. the banner run_ssh prints must never be read as a service ----
# run_ssh prints a blank line and then "==> [h1] <the command>", so the payload starts at line 3.
# The first version of this report skipped one line instead of two and read the banner as a
# service named "==>", with the digit "1" of the host name scraped out of it as its epoch --
# which compares as ancient, so every deploy would report a phantom service.
FAKE_SSH_OUTPUT=(
  "vpt-stream 1699999999"
)
report "banner"
exact "the banner is not reported as a service" "${STALE_AUX_SERVICES[*]}" "h1:vpt-stream"
lacks "the banner text is not in the report" "$OUT" "==> is STILL RUNNING"
lacks "no phantom service named '==>'" "$OUT" "'=='"

# ---- 3. a line that names a service we did not ask about is ignored ----
FAKE_SSH_OUTPUT=(
  "vpt-monitor-img 1699999999"     # not in AUX_SERVICES in this run
  "vpt-stream 1699999999"
)
RESTART_SERVICE="vpt-stream"
report "unknown service"
exact "a service that was not asked about is ignored" "${STALE_AUX_SERVICES[*]}" "h1:vpt-stream"
RESTART_SERVICE=""

# ---- 4. the progress event is emitted with the phase the parser accepts ----
FAKE_SSH_OUTPUT=(
  "vpt-stream 1699999999"
)
report "progress"
contains "the progress line carries the stale-code phase" "$OUT" '"phase":"stale-code"'
contains "the progress line is a skipped event" "$OUT" '"state":"skipped"'
contains "the progress line names the service" "$OUT" "vpt-stream: running the code from before this deploy"

# ---- 5. a service that started after the push is never reported, whatever the preamble ----
FAKE_SSH_OUTPUT=(
  ""
  "==> [h1] for s in vpt-stream vpt-monitor-img"
  "vpt-stream 1700000001"
)
report "fresh with a preamble"
exact "a fresh service is never reported" "${STALE_AUX_SERVICES[*]}" ""

# ---- 6. a line whose second field is not a plain number is dropped, not digit-scraped ----
# Scraping the digits out of a malformed epoch would turn "17 21 86" into the epoch 172186,
# which compares as ancient and would report the service as stale on a wrong number.
FAKE_SSH_OUTPUT=(
  "vpt-stream 17 21 86"        # three fields: not what the remote command prints
  "vpt-monitor-img n/a"        # no epoch at all
  "vpt-monitor-audio 1699000000"  # the only real line
)
report "malformed epoch"
exact "a line with a malformed epoch is ignored" "${STALE_AUX_SERVICES[*]}" "h1:vpt-monitor-audio"
lacks "the malformed line is not in the report" "$OUT" "vpt-stream is STILL RUNNING"
lacks "the service with no epoch is not in the report" "$OUT" "vpt-monitor-img is STILL RUNNING"

echo
if [[ "${fails}" -gt 0 ]]; then
  echo "FAILED ${fails}/${checks}"
  exit 1
fi
echo "ok   ${checks} checks"
