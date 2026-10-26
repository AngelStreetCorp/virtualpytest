#!/usr/bin/env bash
# Self-test for the auto-sign token gate (scripts/security/auto_sign_token_gate.sh).
#
#     bash scripts/security/auto_sign_token_gate_selftest.sh     # 17 assertions, ~20s
#
# It builds throwaway commits on a scratch branch and asserts what the gate does with each.
#
# The value it compares against is an OBVIOUS FAKE — "deadbeef" eight times over, 64
# characters like the real one — handed over in $AUTO_SIGN_TOKEN. The real token is never
# used, never printed and never fetched: the helper is pointed at a path that does not exist,
# so this suite never contacts the server and never reads a real .env.
#
# What it pins down, and why each one is load-bearing:
#   an added line carrying the value FAILS, names <path>:<line>, and masks the value;
#   the same change without it PASSES;
#   the report never contains the value itself (a finding that prints it would leak it into
#     the terminal, the CI log and the transcript);
#   a value that only TRAVELS with a renamed file is caught — a rename shows no added line
#     at all, so this is the case that would slip through a plain "added lines" check;
#   a value inside a BINARY is caught — a diff of a binary says "Binary files differ" and
#     shows no line, so this is the case the content layer exists for;
#   a value in a commit MESSAGE is caught — the message travels with the push;
#   with no token available the gate says exactly what was NOT checked, exits 0 without
#     claiming a pass, and exits non-zero under --require-token.
#   a change set that cannot be resolved — or that is empty — is its OWN outcome (rc 3),
#     never a pass: a caller that maps "0" to "the value was compared and it is clean"
#     must never be handed a check that did not run.
#   the CALLERS map that outcome the same way: the CI step says NOT PERFORMED and does not
#     fail the job, the pre-push hook says the check did not run and lets the push continue
#     (there is nothing to refuse), and both still refuse a real finding.
#
# Two traps this file could fall into; keep both fixes:
#   - never `git add -A` here. It sweeps the work-in-progress onto the scratch branch and
#     deletes it with the branch. Stage only the fixture.
#   - restore VERSION.txt before switching back: the pre-commit hook stamps it from the
#     CURRENT BRANCH NAME, so every commit made on the scratch branch leaves a stamp behind.
#
# Two more, learned the hard way (2026-10-24, the suite run on a detached HEAD):
#   - the base must be a COMMIT, not a branch NAME. `git rev-parse --abbrev-ref HEAD` returns
#     the literal string "HEAD" on a detached HEAD, so the scratch branch was created FROM
#     HEAD and the range under test came out empty — the whole suite collapsed to rc=3
#     ("NOTHING TO COMPARE") and every real assertion failed for the wrong reason.
#   - the caller's state must be restored EXACTLY: the original branch when there was one,
#     the original COMMIT (still detached) when there was not, the scratch branch deleted, the
#     fixtures out of the index AND the working tree, and VERSION.txt as it was. Otherwise a
#     failed run leaves the caller on a scratch branch whose fixture carries a token-shaped
#     string — exactly what this whole guard exists to keep out of the repository.
set -uo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

GATE="scripts/security/auto_sign_token_gate.sh"
# The base is a COMMIT: it does not move when the suite checks out its scratch branch, and it
# is the same thing on a named branch and on a detached HEAD.
BASE="$(git rev-parse HEAD)"
# The caller's own state, to be put back exactly: the branch it was on, or nothing at all
# when it was detached (then it goes back to BASE, still detached).
ORIG_BRANCH="$(git symbolic-ref -q --short HEAD 2>/dev/null || true)"
SCRATCH="_autosigngatetest"
# 64 characters, obviously not a real credential.
FAKE="$(printf 'deadbeef%.0s' $(seq 8))"
[[ ${#FAKE} -eq 64 ]] || { echo "could not build the fake token"; exit 2; }

# The gate must never reach the network from here: point the helper at a path that does not
# exist, and hand it the fake.
export AUTO_SIGN_TOKEN="$FAKE"
export AUTO_SIGN_TOKEN_SCRIPT="/nonexistent/auto_sign_token.sh"

FIXTURES=()
pass=0; fail=0
check() {  # check <ok> <label> [detail]
  if [[ "$1" == "0" ]]; then echo "  PASS  $2"; ((pass++))
  else echo "  FAIL  $2${3:+ — $3}"; ((fail++)); fi
}

VERSION_BACKUP="$(mktemp)"; cp VERSION.txt "$VERSION_BACKUP" 2>/dev/null || true
CLEANED=0
cleanup() {
  # Idempotent: the trap can fire twice (EXIT after INT/TERM), and a second run must not
  # undo the first one's work.
  [[ $CLEANED -eq 1 ]] && return 0
  CLEANED=1
  # 1. VERSION.txt as it was, so the switch back is clean.
  [[ -s "$VERSION_BACKUP" ]] && cp "$VERSION_BACKUP" VERSION.txt
  # 2. the caller's own state back: the branch it was on, or the same commit, still detached.
  #    This also drops the fixtures from the index — they were only ever committed on the
  #    scratch branch.
  if [[ -n "$ORIG_BRANCH" ]]; then
    git checkout -q "$ORIG_BRANCH" 2>/dev/null || git checkout -q --detach "$BASE" 2>/dev/null || true
  else
    git checkout -q --detach "$BASE" 2>/dev/null || true
  fi
  # 3. belt and braces, for a switch back that failed: the fixtures must not stay in the
  #    index either — a leftover fixture carries a token-shaped string, and the caller's
  #    next commit would carry it.
  if [[ ${#FIXTURES[@]} -gt 0 ]]; then
    git rm -q --cached --ignore-unmatch -- "${FIXTURES[@]}" >/dev/null 2>&1 || true
  fi
  # 4. the scratch branch, which is not checked out anywhere any more.
  if git show-ref --verify --quiet "refs/heads/$SCRATCH"; then
    git branch -qD "$SCRATCH" 2>/dev/null \
      || echo "warning: the scratch branch $SCRATCH could not be deleted — it is checked out in another worktree" >&2
  fi
  # 5. the fixture files, which a failed switch back may have left behind as untracked.
  for f in "${FIXTURES[@]:-}"; do [[ -n "$f" ]] && rm -f "$f"; done
  rm -f "$VERSION_BACKUP"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

reset() {
  for f in "${FIXTURES[@]:-}"; do [[ -n "$f" ]] && rm -f "$f"; done
  FIXTURES=()
  # -B, not -b: a leftover scratch branch from an interrupted run otherwise makes every
  # reset fail with "already exists" and silently skews the whole suite.
  if ! git checkout -q -B "$SCRATCH" "$BASE"; then
    # Another worktree has the scratch branch checked out, and git will not move it. Say so
    # instead of running the suite against a base that is not the one under test.
    echo "could not check out the scratch branch $SCRATCH — it is checked out in another worktree" >&2
    exit 2
  fi
}
fixture() {  # fixture <path> <content>
  mkdir -p "$(dirname "$1")"; printf '%s\n' "$2" > "$1"; FIXTURES+=("$1"); git add -f "$1" >/dev/null
}
commit() { git commit -q -m "$1" -- "${FIXTURES[@]}" 2>/dev/null || git commit -q -m "$1"; }
gate() {  # gate <extra args...> → sets GATE_OUT and GATE_RC
  GATE_OUT="$(bash "$GATE" --range "$BASE..$SCRATCH" "$@" 2>&1)" && GATE_RC=0 || GATE_RC=$?
}

echo "== the value is refused, named and masked =="
reset; fixture docs/agent/release/_t.md "value = \"$FAKE\""; commit "t"; gate
if [[ $GATE_RC -eq 1 ]] && grep -q "✗ auto-sign token" <<<"$GATE_OUT"; then
  check 0 "an added line carrying the value makes the gate FAIL"
else check 1 "an added line carrying the value makes the gate FAIL" "rc=$GATE_RC"; fi
if grep -q "docs/agent/release/_t.md:1:" <<<"$GATE_OUT"; then
  check 0 "the finding names <path>:<line>"
else check 1 "the finding names <path>:<line>" "$GATE_OUT"; fi
if grep -q "<AUTO_SIGN_TOKEN>" <<<"$GATE_OUT" && ! grep -qF "$FAKE" <<<"$GATE_OUT"; then
  check 0 "the report masks the value and never prints it"
else check 1 "the report masks the value and never prints it"; fi

echo "== the same change without the value passes =="
reset; fixture docs/agent/release/_t.md "value = 1"; commit "t"; gate
if [[ $GATE_RC -eq 0 ]] && grep -q "✓ auto-sign token: clean" <<<"$GATE_OUT"; then
  check 0 "a clean change passes"
else check 1 "a clean change passes" "rc=$GATE_RC"; fi

echo "== a value that only travels with a rename is caught =="
reset; fixture docs/agent/release/_t.md "value = \"$FAKE\""; commit "t"
git mv docs/agent/release/_t.md docs/agent/release/_t2.md
git commit -q -m "rename" -- docs/agent/release/_t2.md 2>/dev/null || git commit -q -m "rename"
gate
if [[ $GATE_RC -eq 1 ]] && grep -q "✗ auto-sign token" <<<"$GATE_OUT"; then
  check 0 "a renamed file carrying the value is caught"
else check 1 "a renamed file carrying the value is caught" "rc=$GATE_RC"; fi

echo "== a value inside a binary is caught =="
reset
printf 'bin\0prefix %s suffix\n' "$FAKE" > docs/agent/release/_t.bin
FIXTURES+=("docs/agent/release/_t.bin"); git add -f docs/agent/release/_t.bin >/dev/null
commit "t"; gate
if [[ $GATE_RC -eq 1 ]] && grep -q "✗ auto-sign token" <<<"$GATE_OUT"; then
  check 0 "a binary carrying the value is caught"
else check 1 "a binary carrying the value is caught" "rc=$GATE_RC"; fi

echo "== a value in a commit MESSAGE is caught =="
reset; fixture docs/agent/release/_t.md "value = 1"; commit "the value is $FAKE"; gate
if [[ $GATE_RC -eq 1 ]] && grep -q "✗ auto-sign token" <<<"$GATE_OUT"; then
  check 0 "a commit message carrying the value is caught"
else check 1 "a commit message carrying the value is caught" "rc=$GATE_RC"; fi

echo "== with no token the gate says what was NOT checked =="
reset; fixture docs/agent/release/_t.md "value = 1"; commit "t"
out="$(env -u AUTO_SIGN_TOKEN AUTO_SIGN_TOKEN_SCRIPT="/nonexistent/auto_sign_token.sh" \
        bash "$GATE" --range "$BASE..$SCRATCH" 2>&1)" && rc=0 || rc=$?
if [[ $rc -eq 0 ]] && grep -q "SKIPPED" <<<"$out" && grep -q "NOT compared" <<<"$out" \
   && ! grep -q "✓ auto-sign token: clean" <<<"$out"; then
  check 0 "no token: loud, and no claim of a pass"
else check 1 "no token: loud, and no claim of a pass" "rc=$rc"; fi
out="$(env -u AUTO_SIGN_TOKEN AUTO_SIGN_TOKEN_SCRIPT="/nonexistent/auto_sign_token.sh" \
        bash "$GATE" --range "$BASE..$SCRATCH" --require-token 2>&1)" && rc=0 || rc=$?
if [[ $rc -ne 0 ]] && grep -q "NOT compared" <<<"$out"; then
  check 0 "no token with --require-token: the gate fails"
else check 1 "no token with --require-token: the gate fails" "rc=$rc"; fi

echo "== nothing to compare is its own outcome, never a pass =="
# (a) a change set that cannot be resolved: a repo with no upstream and no origin/main
tmp_repo="$(mktemp -d)"
( cd "$tmp_repo" && git init -q . && git config user.email t@t && git config user.name t \
    && printf 'x\n' > a.txt && git add -A && git commit -qm init ) >/dev/null 2>&1
out="$(cd "$tmp_repo" && bash "$REPO_ROOT/scripts/security/auto_sign_token_gate.sh" 2>&1)" && rc=0 || rc=$?
if [[ $rc -eq 3 ]] && grep -q "NOTHING TO COMPARE" <<<"$out" \
   && ! grep -q "auto-sign token: clean" <<<"$out"; then
  check 0 "an unresolvable range: rc=3, and no claim of a pass"
else check 1 "an unresolvable range: rc=3, and no claim of a pass" "rc=$rc"; fi
rm -rf "$tmp_repo"
# (b) a range with nothing in it
sha="$(git rev-parse HEAD)"
out="$(bash "$GATE" --range "$sha..$sha" 2>&1)" && rc=0 || rc=$?
if [[ $rc -eq 3 ]] && grep -q "NOTHING TO COMPARE" <<<"$out" \
   && ! grep -q "auto-sign token: clean" <<<"$out"; then
  check 0 "an empty range: rc=3, and no claim of a pass"
else check 1 "an empty range: rc=3, and no claim of a pass" "rc=$rc"; fi

echo "== the CI step maps rc=3 to NOT PERFORMED, never to a pass =="
# The CI step's own run block, read out of the workflow file: its rc mapping is part of the
# contract, so the test reads it from there instead of keeping a copy that can drift.
ci_step="$(awk '
  /^      - name: Run the auto-sign token gate/ { in_step=1; next }
  in_step && /^        run: \|/ { in_run=1; next }
  in_run {
    if ($0 ~ /^          /) { sub(/^          /, ""); print; next }
    in_run=0
  }' .github/workflows/regression.yml)"
if [[ -z "$ci_step" ]]; then
  check 1 "the CI step's run block is found in .github/workflows/regression.yml" "could not extract it"
else
  check 0 "the CI step's run block is found in .github/workflows/regression.yml"
  tmp_step="$(mktemp -d)"
  mkdir -p "$tmp_step/scripts/security"
  printf '%s\n' "$ci_step" | sed 's|\${{ steps.range.outputs.range }}|HEAD~1..HEAD|g' > "$tmp_step/step.sh"
  summary="$tmp_step/summary.md"
  for stub_rc in 3 0 1; do
    printf '#!/usr/bin/env bash\necho "stub gate: rc=%s"\nexit %s\n' "$stub_rc" "$stub_rc" \
      > "$tmp_step/scripts/security/auto_sign_token_gate.sh"
    : > "$summary"
    ( cd "$tmp_step" && GITHUB_STEP_SUMMARY="$summary" bash step.sh ) >/dev/null 2>&1; rc=$?
    case "$stub_rc" in
      3) if [[ $rc -eq 0 ]] && grep -qF "NOT PERFORMED" "$summary" \
                 && ! grep -qF "**Performed**" "$summary"; then
           check 0 "rc=3: the CI step says NOT PERFORMED, and does not fail the job"
         else check 1 "rc=3: the CI step says NOT PERFORMED, and does not fail the job" "rc=$rc"; fi ;;
      0) if [[ $rc -eq 0 ]] && grep -qF "**Performed**" "$summary"; then
           check 0 "rc=0: the CI step still says Performed"
         else check 1 "rc=0: the CI step still says Performed" "rc=$rc"; fi ;;
      1) if [[ $rc -eq 1 ]]; then
           check 0 "rc=1: the CI step still fails the job"
         else check 1 "rc=1: the CI step still fails the job" "rc=$rc"; fi ;;
    esac
  done
  rm -rf "$tmp_step"
fi

echo "== the pre-push hook: rc=3 is loud, and the push continues =="
tmp_hook="$(mktemp -d)"
(
  cd "$tmp_hook" || exit 1
  git init -q .; git config user.email t@t; git config user.name t
  mkdir -p .githooks scripts/security scripts/review
  cp "$REPO_ROOT/.githooks/pre-push" .githooks/pre-push
  for g in scripts/security/leak_gate.sh scripts/security/game_slug_gate.sh scripts/review/review_gate.sh; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$g"; chmod +x "$g"
  done
  printf '#!/usr/bin/env bash\necho "stub gate: rc=3"\nexit 3\n' > scripts/security/auto_sign_token_gate.sh
  chmod +x scripts/security/auto_sign_token_gate.sh
  printf 'x\n' > a.txt; git add -A; git commit -qm init >/dev/null
) >/dev/null 2>&1
sha="$(cd "$tmp_hook" && git rev-parse HEAD)"
out="$(cd "$tmp_hook" && printf 'refs/heads/feature %s refs/heads/feature %s\n' "$sha" "$sha" \
       | bash .githooks/pre-push 2>&1)" && rc=0 || rc=$?
if [[ $rc -eq 0 ]] && grep -q "the check did not run" <<<"$out"; then
  check 0 "rc=3: the hook says the check did not run, and the push continues"
else check 1 "rc=3: the hook says the check did not run, and the push continues" "rc=$rc"; fi
printf '#!/usr/bin/env bash\necho "stub gate: rc=1"\nexit 1\n' > "$tmp_hook/scripts/security/auto_sign_token_gate.sh"
out="$(cd "$tmp_hook" && printf 'refs/heads/feature %s refs/heads/feature %s\n' "$sha" "$sha" \
       | bash .githooks/pre-push 2>&1)" && rc=0 || rc=$?
if [[ $rc -eq 1 ]]; then
  check 0 "rc=1: the hook still refuses the push"
else check 1 "rc=1: the hook still refuses the push" "rc=$rc"; fi
rm -rf "$tmp_hook"

echo; echo "RESULT: $pass passed, $fail failed"   # cleanup() runs on EXIT
exit $(( fail > 0 ))