#!/usr/bin/env bash
# Self-test for the two-tier leak gate (scripts/security/leak_gate.sh).
#
# Run it after ANY change to leak_gate.sh or scripts/security/internal-paths.txt:
#
#     bash scripts/security/leak_gate_selftest.sh        # 14 assertions, ~20s
#
# It builds throwaway commits on a scratch branch `_gatetest` and asserts what the gate does
# with each. The real terms are read from the gitignored list and NEVER printed, so the output
# is safe to paste. Requires that list to exist (see ANONYMIZATION.md).
#
# What it pins down, and why each one is load-bearing:
#   tier 1 flags in a publishable path, an internal path, docs/agent/, a commit MESSAGE and a
#     file PATH — the absoluteness of tier 1 is the whole safety floor, and two of this gate's
#     real catches arrived through a commit message rather than a file.
#   tier 2 flags where content publishes, and is silent in the internal paths and in messages.
#     The "flags in a publishable path" case is the one that matters: a refactor that quietly
#     turns the codename check off everywhere would still pass every other assertion here.
#   glob entries stay inside one path segment (docs/security/*.json exempt, .md not).
#   a MISSING internal-paths.txt fails CLOSED — tier 2 is then checked everywhere, with a
#     warning, rather than silently exempted.
#   findings name <path>:<line>.
#
# Two traps this file already fell into; keep both fixes:
#   - never `git add -A` here. It sweeps the work-in-progress gate onto the scratch branch and
#     deletes it with the branch. Stage only the fixture.
#   - never `cmd | grep -q` under `set -o pipefail`. grep -q closes the pipe on first match,
#     the producer dies of SIGPIPE, and the pipeline reports FAILURE on a successful match.
#     Capture into a variable first.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
T1="$(grep -vE '^(#|~|$)' docs/agent/leak-terms.local.txt | grep -v '^/' | head -1)"
T2="$(grep '^~' docs/agent/leak-terms.local.txt | sed 's/^~//' | head -1)"
[[ -n "$T1" && -n "$T2" ]] || { echo "could not load terms"; exit 2; }
FIXTURES=()
pass=0; fail=0

# A commit hook stamps VERSION.txt from the CURRENT BRANCH NAME, so every commit this suite
# makes on `_gatetest` writes `current:_gatetest-...` into the working tree and leaves it there
# after the branch is gone. Snapshot it now and put it back on the way out, however we exit.
VERSION_BACKUP="$(mktemp)"; cp VERSION.txt "$VERSION_BACKUP" 2>/dev/null || true
cleanup() {
  git checkout -q main 2>/dev/null
  git branch -qD _gatetest 2>/dev/null
  for f in "${FIXTURES[@]:-}"; do [[ -n "$f" ]] && rm -f "$f"; done
  [[ -s "$VERSION_BACKUP" ]] && cp "$VERSION_BACKUP" VERSION.txt
  rm -f "$VERSION_BACKUP"
}
trap cleanup EXIT

reset() {
  git checkout -q main 2>/dev/null
  git branch -qD _gatetest 2>/dev/null
  for f in "${FIXTURES[@]:-}"; do [[ -n "$f" ]] && rm -f "$f"; done
  FIXTURES=()
  # -B, not -b: a leftover _gatetest from an interrupted run (Ctrl-C before the EXIT trap,
  # or a `git branch -D` that failed because the branch was checked out) otherwise makes
  # every reset fail with "already exists" and silently skews the whole suite.
  git checkout -q -B _gatetest main
}
fixture() { # fixture <path> <content>
  mkdir -p "$(dirname "$1")"; printf '%s\n' "$2" > "$1"; FIXTURES+=("$1"); git add -f "$1" >/dev/null
}
commit() { git commit -q -m "$1" -- "${FIXTURES[@]}" 2>/dev/null || git commit -q -m "$1"; }
run() {
  local expect="$1" label="$2" out got=CLEAN
  out="$(${3:-} bash scripts/security/leak_gate.sh --range main.._gatetest 2>&1)"
  grep -q "✗ identifiers" <<<"$out" && got=FLAG
  if [[ "$got" == "$expect" ]]; then echo "  PASS  $label (=$got)"; ((pass++))
  else echo "  FAIL  $label — expected $expect, got $got"; ((fail++)); fi
}

echo "== tier 1 (real identifiers) — absolute, no exemptions =="
reset; fixture docs/get-started/_t.md "host $T1 here"; commit "t"; run FLAG "tier-1 in publishable path"
reset; fixture docs/tasks/_t.md        "host $T1 here"; commit "t"; run FLAG "tier-1 in deny-listed path"
reset; fixture docs/agent/_t.md        "host $T1 here"; commit "t"; run FLAG "tier-1 in docs/agent/"
reset; fixture docs/get-started/_t.md  "clean";         commit "mentions $T1 in subject"; run FLAG "tier-1 in commit message"
reset; fixture "docs/get-started/_${T1}.md" "clean";    commit "t"; run FLAG "tier-1 in file PATH"

echo "== tier 2 (codename) — only where it can publish =="
reset; fixture docs/get-started/_t.md "repo vpt-customer-$T2"; commit "t"; run FLAG  "tier-2 in publishable path"
reset; fixture features/_t.py         "# vpt-customer-$T2";    commit "t"; run FLAG  "tier-2 in source tree"
reset; fixture docs/tasks/_t.md       "repo vpt-customer-$T2"; commit "t"; run CLEAN "tier-2 in docs/tasks/ (exempt)"
reset; fixture docs/agent/_t.md       "repo vpt-customer-$T2"; commit "t"; run CLEAN "tier-2 in docs/agent/ (exempt)"
reset; fixture docs/get-started/_t.md "clean"; commit "subject names $T2 overlay";     run CLEAN "tier-2 in commit message (exempt)"

echo "== glob entries stay scoped to one path segment =="
reset; fixture docs/security/_t.json "repo vpt-customer-$T2"; commit "t"; run CLEAN "tier-2 in docs/security/*.json (exempt)"
reset; fixture docs/security/_t.md   "repo vpt-customer-$T2"; commit "t"; run FLAG  "tier-2 in docs/security/_t.md (NOT exempt)"

echo "== fail closed when the shared deny-list is missing =="
reset; fixture docs/tasks/_t.md "repo vpt-customer-$T2"; commit "t"
out="$(INTERNAL_PATHS_FILE=/nonexistent bash scripts/security/leak_gate.sh --range main.._gatetest 2>&1)"
if grep -q "✗ identifiers" <<<"$out" && grep -qi "missing" <<<"$out"; then
  echo "  PASS  missing deny-list => tier-2 checked everywhere, with a warning"; ((pass++))
else echo "  FAIL  missing deny-list did not fail closed"; ((fail++)); fi

echo "== findings name the file =="
reset; fixture docs/get-started/_t.md "host $T1 here"; commit "t"
# Capture first: `| grep -q` closes the pipe on its first match, the gate dies of SIGPIPE,
# and `set -o pipefail` then reports the whole pipeline as failed even though it MATCHED.
loc_out="$(bash scripts/security/leak_gate.sh --range main.._gatetest 2>&1)"
if grep -q "docs/get-started/_t.md:1:" <<<"$loc_out"; then
  echo "  PASS  finding reports <path>:<line>"; ((pass++))
else echo "  FAIL  finding does not report path:line"; ((fail++)); fi

echo; echo "RESULT: $pass passed, $fail failed"   # cleanup() runs on EXIT
exit $(( fail > 0 ))
