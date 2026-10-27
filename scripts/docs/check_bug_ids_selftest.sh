#!/usr/bin/env bash
# Self-test for the bug-id gate (scripts/docs/check_bug_ids.sh).
#
#     bash scripts/docs/check_bug_ids_selftest.sh     # 6 assertions, ~5s
#
# It copies the release note and the bug files into a scratch tree, runs the gate there,
# and asserts what the gate does with each defect.
#
# Why this suite exists: the check that a bug is not cited twice in the same build section
# had never run, on any host. Its pattern spelled the four digits as {4}, and mawk (the awk
# on Ubuntu and on the Mac) has no interval expressions, so it was matched literally and
# nothing was ever found; and its duplicates were piped into `while ... done`, so `fail=1`
# ran in a pipeline subshell and never reached the shell that decides the exit code. A
# duplicate citation injected into Unreleased passed with "bug ids: unique, linked, and
# cited once per build" and exit code 0.
#
# A gate that cannot fail is worse than no gate: it reports a clean bill of health for a
# tree it never looked at. These assertions pin down that each defect below is now caught,
# and that a clean note still passes — a gate that refuses everything is broken too.
#
# Exit: 0 every assertion held, 1 one of them did not.
set -uo pipefail

if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  :
else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
GATE="scripts/docs/check_bug_ids.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; NC=$'\033[0m'
[[ -t 1 ]] || { RED=""; GREEN=""; NC=""; }

passed=0
failed=0

# A fresh scratch tree holding the gate, the bug files and the release note. The gate cds to
# its own repo root, so the copy it runs IS the tree it checks.
fixture() {
  local d="$WORK/$1"
  mkdir -p "$d/scripts/docs" "$d/docs/release_note" "$d/docs/bugs"
  cp "$REPO_ROOT/$GATE" "$d/scripts/docs/"
  cp "$REPO_ROOT/scripts/docs/check_bug_meta.py" "$d/scripts/docs/"
  cp "$REPO_ROOT/docs/release_note/README.md" "$d/docs/release_note/"
  cp "$REPO_ROOT"/docs/bugs/*.md "$d/docs/bugs/"
  echo "$d"
}

# run_gate <tree> -> prints the output, returns the gate's exit code
run_gate() {
  ( cd "$1" && bash "$GATE" 2>&1 )
}

assert() { # assert <name> <expected-rc> <expected-substring> <tree> [expected-rc]
  local name="$1" want_rc="$2" want_msg="$3" tree="$4"
  local out rc
  out="$(run_gate "$tree")"; rc=$?
  if [[ "$rc" != "$want_rc" ]]; then
    printf '%sFAIL%s %s: exit code %s, expected %s\n%s\n' "$RED" "$NC" "$name" "$rc" "$want_rc" "$out" >&2
    failed=$((failed + 1)); return
  fi
  if [[ -n "$want_msg" ]] && ! grep -qF -- "$want_msg" <<< "$out"; then
    printf '%sFAIL%s %s: the output does not mention %s\n%s\n' "$RED" "$NC" "$name" "$want_msg" "$out" >&2
    failed=$((failed + 1)); return
  fi
  printf '%sok%s   %s\n' "$GREEN" "$NC" "$name"
  passed=$((passed + 1))
}

# --- 1. a clean note passes -------------------------------------------------------
t="$(fixture clean)"
assert "a clean release note passes" 0 "" "$t"

# --- 2. the same bug cited twice in Unreleased is refused ---------------------------
t="$(fixture dup)"
bullet="$(grep -m1 '^- \*\*The operator-tree inventory' "$t/docs/release_note/README.md")"
python3 - "$t/docs/release_note/README.md" "$bullet" <<'PY'
import sys
path, bullet = sys.argv[1], sys.argv[2]
t = open(path, encoding='utf-8').read()
t = t.replace(bullet, bullet + "\n- **A second fix wearing the same number** - a test · [BUG-0964](../bugs/BUG-0964-2026-10-26-the-software-version-under-test-cannot-be-read-from-the-operator-trees.md)")
open(path, 'w', encoding='utf-8').write(t)
PY
assert "a duplicate citation in Unreleased is refused" 1 "BUG-0964 is cited twice" "$t"

# --- 3. a link whose label and target disagree is refused --------------------------
t="$(fixture label)"
python3 - "$t/docs/release_note/README.md" <<'PY'
import sys
path = sys.argv[1]
t = open(path, encoding='utf-8').read()
old = '[BUG-0964](../bugs/BUG-0964-2026-10-26-the-software-version-under-test-cannot-be-read-from-the-operator-trees.md)'
new = '[BUG-0963](../bugs/BUG-0964-2026-10-26-the-software-version-under-test-cannot-be-read-from-the-operator-trees.md)'
assert t.count(old) == 1, t.count(old)
open(path, 'w', encoding='utf-8').write(t.replace(old, new))
PY
assert "a mislabelled link is refused" 1 "cites BUG-0963 but links BUG-0964" "$t"

# --- 4. a link to a bug file that is not there is refused --------------------------
t="$(fixture missing)"
python3 - "$t/docs/release_note/README.md" <<'PY'
import sys
path = sys.argv[1]
t = open(path, encoding='utf-8').read()
old = '[BUG-0964](../bugs/BUG-0964-2026-10-26-the-software-version-under-test-cannot-be-read-from-the-operator-trees.md)'
new = '[BUG-0964](../bugs/BUG-9999-does-not-exist.md)'
assert t.count(old) == 1
open(path, 'w', encoding='utf-8').write(t.replace(old, new))
PY
assert "a link to a missing bug file is refused" 1 "which does not exist" "$t"

# --- 5. one bug in two different build sections is not a duplicate -----------------
# Only Unreleased is checked on purpose: a shipped section is a record of what was said
# at the time, and editing it to satisfy a linter falsifies it.
t="$(fixture twobuilds)"
python3 - "$t/docs/release_note/README.md" <<'PY'
import sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().split('\n')
line = '- **A citation in a shipped section** - a test · [BUG-0964](../bugs/BUG-0964-2026-10-26-the-software-version-under-test-cannot-be-read-from-the-operator-trees.md)'
for i, l in enumerate(lines):
    if l.startswith('## build '):
        lines.insert(i + 1, line)      # inside that build section, not before its heading
        break
else:
    raise SystemExit('no build section in the release note')
open(path, 'w', encoding='utf-8').write('\n'.join(lines))
PY
assert "one bug in two build sections is allowed" 0 "" "$t"

# --- 6. a bug file whose title disagrees with its file name is refused ---------------
# A file that was renumbered to dodge a collision keeps its old number in the title. One file
# had three different numbers: its name said 0965, its title and the note's link text said 0964.
t="$(fixture title)"
python3 - "$t/docs/bugs" <<'PY'
import glob, sys
files = sorted(glob.glob(sys.argv[1] + '/BUG-0965-*.md'))
if not files:
    raise SystemExit('no BUG-0965 file to work on')
p = files[0]
t = open(p, encoding='utf-8').read()
open(p, 'w', encoding='utf-8').write(t.replace('# BUG-0965', '# BUG-0964', 1))
print("renamed the number in a title without renaming the file")
PY
assert "a bug file titled with another number is refused" 1 "is filed as BUG-0965 but its title says BUG-0964" "$t"

# --- 7. the gate works on an awk without interval expressions ----------------------
# mawk is the awk on Ubuntu and on the Mac. If the pattern ever goes back to {4}, this
# assertion is the one that catches it.
if command -v mawk >/dev/null 2>&1; then
  t="$(fixture mawk)"
  out="$( cd "$t" && mawk '/\[BUG-[0-9][0-9][0-9][0-9]\]/ {print "MATCHED"}' <<< '[BUG-0964]' )"
  if grep -q MATCHED <<< "$out"; then
    printf '%sok%s   the bug pattern matches under mawk\n' "$GREEN" "$NC"; passed=$((passed + 1))
  else
    printf '%sFAIL%s the bug pattern does not match under mawk\n' "$RED" "$NC" >&2; failed=$((failed + 1))
  fi
else
  printf '%sskip%s  mawk is not installed here (the interval-expression assertion needs it)\n' "$NC" "$NC"
fi

echo
if [[ "$failed" -eq 0 ]]; then
  printf '%s✓ bug-id gate self-test: %d assertions passed%s\n' "$GREEN" "$passed" "$NC"
  exit 0
fi
printf '%s✗ bug-id gate self-test: %d of %d assertions failed%s\n' "$RED" "$failed" "$((passed + failed))" "$NC" >&2
exit 1
