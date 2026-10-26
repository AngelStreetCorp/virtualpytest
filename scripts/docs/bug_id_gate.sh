#!/usr/bin/env bash
#
# bug_id_gate: refuses a push that adds a bug document whose number is already used.
#
# Why this exists: two sessions pick the same free number while both are working, and the
# tree check (scripts/docs/check_bug_ids.sh) only sees the MERGED result. Measured on
# 2026-10-26, three collisions reached main in one day (0923, 0925, 0933) and each one
# turned main red for every agent until somebody renumbered a file. This gate runs BEFORE
# the push and compares the numbers the push ADDS with the numbers the target branch
# already carries, so the collision is refused at the push that would cause it.
#
# Usage:
#   bash scripts/docs/bug_id_gate.sh --range <base>..<tip> [--target <ref>]
#   bash scripts/docs/bug_id_gate.sh --selftest
#
# --range   the commits the push would send (the pre-push hook hands it over).
# --target  the ref whose numbers are the reference (default: origin/main — the branch
#           every merge lands on). It is fetched first, because a session that pushed
#           straight to main may be ahead of the local copy of that ref.
#
# Exit: 0 clean | 1 a number is used twice (refuse the push) | 2 usage | 3 could not
#       check (say so out loud; do NOT refuse: a gate that cannot look is not a pass)
#
# Bypass (say why in the PR):  BUG_ID_GATE_SKIP=1 git push

set -uo pipefail

SELFTEST_TMP=""

usage() {
  echo "usage: bug_id_gate.sh --range <base>..<tip> [--target <ref>] | --selftest" >&2
}

# The number a file claims: the BUG-NNNN at the start of its name.
id_of() { basename "$1" | grep -oE '^BUG-[0-9]{4}'; }

# Every number the target ref already carries, with the file that carries it.
ids_on_target() {
  git ls-tree -r --name-only "$1" -- docs/bugs/ 2>/dev/null | grep -E '^docs/bugs/BUG-[0-9]{4}' || true
}

check() {
  local range="$1" target="${2:-origin/main}"
  local added existing id file other dupes rc=0

  [[ -n "$range" ]] || { echo "bug_id_gate: --range is required" >&2; usage; return 2; }

  # The files the push ADDS under docs/bugs/ (a rename shows up as an add of the new name).
  added="$(git diff --name-only --diff-filter=A "$range" -- docs/bugs/ 2>/dev/null | grep -E '^docs/bugs/BUG-[0-9]{4}' || true)"

  # The numbers the target branch already carries. Fetch it first: the reference has to be
  # the truth on the remote, not a stale local copy of it.
  if [[ "$target" == origin/* ]]; then
    git fetch --quiet origin "${target#origin/}" 2>/dev/null || true
  fi
  if ! git rev-parse --verify --quiet "$target" >/dev/null 2>&1; then
    echo "bug_id_gate: could not read ${target} — the check did not run (that is not a pass)." >&2
    return 3
  fi
  existing="$(ids_on_target "$target")"

  # Two files with the same number inside ONE push: the tree check finds it after the
  # merge, so it is refused here too.
  dupes="$(printf '%s\n' "$added" | xargs -r -n1 basename 2>/dev/null | grep -oE '^BUG-[0-9]{4}' | sort | uniq -d)"
  for id in $dupes; do
    echo "bug_id_gate: refusing the push: this push adds ${id} twice:" >&2
    printf '%s\n' "$added" | while read -r f; do
      [[ "$(id_of "$f")" == "$id" ]] && echo "  $f" >&2
    done
    rc=1
  done

  for file in $added; do
    id="$(id_of "$file")"
    [[ -n "$id" ]] || continue
    other="$(printf '%s\n' "$existing" | while read -r f; do [[ "$(id_of "$f")" == "$id" ]] && echo "$f"; done | head -n1)"
    [[ -n "$other" ]] || continue
    next="$(printf '%s\n' "$existing" | grep -oE 'BUG-[0-9]{4}' | sed 's/BUG-//' | sort -n | tail -n1)"
    next="$(printf 'BUG-%04d' $(( 10#${next:-0} + 1 )))"   # 10#: a number with a leading zero is octal to bash, and 0933 is not an octal number
    echo "bug_id_gate: refusing the push: ${id} is already used on ${target}." >&2
    echo "  already there: ${other}" >&2
    echo "  this push:     ${file}" >&2
    echo "  Rename yours to the next free number (${next} or later), then:" >&2
    echo "    - put ${next} in the ID row and the title of the file," >&2
    echo "    - update the release note entry that cites it," >&2
    echo "    - regenerate the index: python3 scripts/docs/build_bug_index.py" >&2
    rc=1
  done

  return $rc
}

selftest() {
  local rc=0
  local here="$PWD"
  SELFTEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/bug-id-gate.XXXXXX")" || return 2
  local tmp="$SELFTEST_TMP"
  (
    cd "$tmp" || exit 1
    git init -q -b main . >/dev/null 2>&1
    git config user.email t@t; git config user.name t
    mkdir -p docs/bugs
    printf '# BUG-0001 — one\n' > docs/bugs/BUG-0001-2026-01-01-one.md
    git add -A; git commit -qm base
    git branch -q target
    # a push that adds a free number
    printf '# BUG-0002 — two\n' > docs/bugs/BUG-0002-2026-01-01-two.md
    git add -A; git commit -qm two
    printf '# BUG-0003 — three\n' > docs/bugs/BUG-0003-2026-01-01-three.md
    git add -A; git commit -qm three
  ) || return 2
  cd "$tmp" || return 2
  local free_range="target..HEAD"
  check "$free_range" target >/dev/null 2>&1; local free_rc=$?
  [[ "$free_rc" == 0 ]] || { echo "selftest: a free number was refused (rc=$free_rc)" >&2; rc=1; }
  # a push that adds a number the target already carries
  ( cd "$tmp" && git checkout -q -b dup target && printf '# BUG-0001 — again\n' > docs/bugs/BUG-0001-2026-01-01-again.md && git add -A && git commit -qm dup )
  check "target..dup" target >/dev/null 2>&1; local dup_rc=$?
  [[ "$dup_rc" == 1 ]] || { echo "selftest: a duplicate number was not refused (rc=$dup_rc)" >&2; rc=1; }
  # a target that cannot be read: no refusal, but the gate says it did not run
  check "target..HEAD" "origin/does-not-exist" >/dev/null 2>&1; local unknown_rc=$?
  [[ "$unknown_rc" == 3 ]] || { echo "selftest: an unreadable target did not report 3 (rc=$unknown_rc)" >&2; rc=1; }
  # one push that adds the same number twice: refused even when the number is free
  ( cd "$tmp" && git checkout -q -b twice target && printf '# BUG-0002 — a\n' > docs/bugs/BUG-0002-2026-01-01-a.md && printf '# BUG-0002 — b\n' > docs/bugs/BUG-0002-2026-01-02-b.md && git add -A && git commit -qm twice )
  check "target..twice" target >/dev/null 2>&1; local twice_rc=$?
  [[ "$twice_rc" == 1 ]] || { echo "selftest: a number used twice in one push was not refused (rc=$twice_rc)" >&2; rc=1; }
  [[ "$rc" == 0 ]] && echo "bug_id_gate selftest: ok (4 assertions)"
  cd "$here" || return 1     # leave the tree before removing it: a cleanup never runs in the directory it deletes
  rm -rf "$SELFTEST_TMP"
  return $rc
}

if [[ "${1:-}" == "--selftest" ]]; then selftest; exit $?; fi
SELFTEST_TMP=""

RANGE=""; TARGET="origin/main"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --range) RANGE="${2:-}"; shift 2 ;;
    --target) TARGET="${2:-origin/main}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

check "$RANGE" "$TARGET"
exit $?
