#!/usr/bin/env bash
#
# Auto-sign token gate — refuses to push a change that carries the LIVE auto-sign token.
#
# The auto-sign token is a team-admin credential: it bypasses authentication on every
# VirtualPyTest page and API. It lives in the main backend server's .env and is handed out at
# run time by scripts/agent/auto_sign_token.sh, so a copy of it in the repository is a leaked
# credential, not a string.
#
# Why a gate of its own: scripts/security/leak_gate.sh checks customer IDENTIFIERS (stems,
# never values) and then runs gitleaks, which matches SHAPES. A 64-character hex token is
# indistinguishable from a sha256 digest, so neither half of the leak gate can see it — and
# nothing in the repository compared a diff against the live value. BUG-0881 (2026-10-23) is
# what that gap cost.
#
# What it compares, in two layers:
#   1. the ADDED LINES of the change, against the live value;
#   2. the CONTENT of the files the change touches, at the tip of the range. A diff of a
#      binary says "Binary files differ" and shows no line at all, so a token inside a binary
#      is invisible to layer 1; and a token in a line the change did not add is republished by
#      it anyway.
# The value is read at run time, once per run, and is never stored: it comes from
# $AUTO_SIGN_TOKEN, else from scripts/agent/auto_sign_token.sh. It is never printed, never
# written to a file and never passed on a command line, and nothing is cached — so the guard
# keeps working after the token is rotated.
#
# Usage:
#   auto_sign_token_gate.sh                      # origin/<branch>..HEAD (what a push would send)
#   auto_sign_token_gate.sh --range A..B         # an explicit commit range
#   auto_sign_token_gate.sh --staged             # the index, for a pre-commit hook
#   auto_sign_token_gate.sh --all                # every tracked file at HEAD (pre-publish audit)
#   auto_sign_token_gate.sh --tag-message <tag>  # one annotated tag's own message
#   auto_sign_token_gate.sh --require-token      # fail when the token cannot be obtained (CI)
#
# Exit: 0 clean · 1 findings · 2 the token could not be obtained (--require-token)
#       3 nothing to compare (the change set could not be resolved, or it is empty)
#
# 3 is NOT a pass. It says the check had nothing to compare, so a caller must report it as
# "not performed" and never as "the value was compared and it is clean".

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2

# The repo's own helper, or a path to it (the self-test points this at a file that does not
# exist so the suite never contacts the server).
TOKEN_SCRIPT="${AUTO_SIGN_TOKEN_SCRIPT:-scripts/agent/auto_sign_token.sh}"
MODE="range"
RANGE=""
TAGREF=""
REQUIRE_TOKEN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --range)         MODE="range";  RANGE="${2:-}"; shift 2 ;;
    --staged)        MODE="staged"; shift ;;
    --all)           MODE="all";    shift ;;
    --tag-message)   MODE="tagmsg"; TAGREF="${2:-}"; shift 2 ;;
    --require-token) REQUIRE_TOKEN=1; shift ;;
    -h|--help)       sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "auto_sign_token_gate: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BOLD=""; NC=""
fi

# ---------------------------------------------------------------- resolve the change set
if [[ "$MODE" == "range" && -z "$RANGE" ]]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
    RANGE="${upstream}..HEAD"
  elif git rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
    RANGE="origin/${branch}..HEAD"
  else
    # No upstream yet (a brand-new branch): fall back to the fork point from the default
    # branch so a first push is still scanned rather than silently skipped.
    base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
    RANGE="${base:+${base}..HEAD}"
    if [[ -z "$RANGE" ]]; then
      # Nothing to compare: there is no change set at all. This is its OWN outcome (exit 3),
      # never a pass: a caller that mapped "0" to "the value was compared and it is clean"
      # would otherwise report a check that never ran as one that passed.
      echo "${YELLOW}⚠ auto-sign token: NOTHING TO COMPARE — no upstream and no origin/main, so there is no change set to check.${NC}"
      echo "  The check did not run. That is not a pass."
      exit 3
    fi
  fi
fi

# Rewrite a unified diff into `+<path>:<lineno>:<text>` — one line per ADDED line, carrying
# the file it lives in and its line number in the new file. Same shape as leak_gate.sh, so a
# finding reads the same in both gates: `path:line:text`.
#
# `--unified=0` means there are no context lines: only `+++ b/<path>` (the file), `@@ … +n,m @@`
# (the new-file line counter) and the `+`/`-` lines themselves. `-` lines do not advance the
# counter, so they simply fall through unmatched.
diff_to_located() {
  awk '
    /^\+\+\+ /  { p = substr($0, 5); sub(/^b\//, "", p); next }
    /^@@ /     { m = $3; sub(/^\+/, "", m); split(m, a, ","); n = a[1] + 0; next }
    /^\+/      { print "+" p ":" n ":" substr($0, 2); n++; next }
  '
}

# `--no-renames` on purpose: with rename detection on, a file that is only MOVED shows up as
# "rename from / rename to" with no added line, so a token that travels with the file would
# not be in the diff at all. Without it, a move is a delete plus an add, and the content is
# compared like any other addition.
case "$MODE" in
  range)
    SCOPE_DESC="$RANGE"
    TIP="${RANGE##*..}"                       # the tree the range ends at
    changed_paths() { git diff --name-only --diff-filter=ACMR --no-renames "$RANGE" -- .; }
    added_lines()   { git diff --unified=0 --diff-filter=ACMR --no-renames "$RANGE" -- . | diff_to_located; }
    ;;
  staged)
    SCOPE_DESC="staged changes"
    changed_paths() { git diff --cached --name-only --diff-filter=ACMR --no-renames -- .; }
    added_lines()   { git diff --cached --unified=0 --diff-filter=ACMR --no-renames -- . | diff_to_located; }
    ;;
  all)
    SCOPE_DESC="every tracked file at HEAD"
    changed_paths() { git ls-files; }
    added_lines()   { git ls-files -z | xargs -0 grep -nIH '' 2>/dev/null | sed 's/^/+/'; }
    ;;
  tagmsg)
    # An annotated tag's message is published content (publish_public.sh copies every
    # release-* tag on the published commit into the public repo), so it is compared too.
    SCOPE_DESC="the message of tag ${TAGREF}"
    changed_paths() { :; }
    added_lines()   { git for-each-ref --format='%(contents)' "refs/tags/${TAGREF}" \
                        | awk -v t="$TAGREF" '{ printf "+%s:%d:%s\n", t, NR, $0 }'; }
    ;;
esac

# ------------------------------------------------------- is there anything to compare?
# A change set that cannot be resolved, or that is empty, means the check has NOTHING to
# compare. That is its own outcome (exit 3) and never a pass: a caller that reads "0" as
# "the value was compared and it is clean" must not be handed a check that never ran.
#
# The check is done BEFORE the value is fetched, so an empty change set costs no token
# fetch, and so a missing value cannot mask the real reason the check did not run.
NOTHING_REASON=""
nothing_to_compare() {
  case "$MODE" in
    range)  NOTHING_REASON="${RANGE} is empty — there is no change in it"
            [[ -z "$(git rev-list "$RANGE" 2>/dev/null)" ]] ;;
    staged) NOTHING_REASON="the index carries no staged change"
            [[ -z "$(git diff --cached --name-only 2>/dev/null)" ]] ;;
    all)    NOTHING_REASON="the tree at HEAD is empty"
            [[ -z "$(git ls-files 2>/dev/null)" ]] ;;
    tagmsg) NOTHING_REASON="tag ${TAGREF} carries no message"
            [[ -z "$(git for-each-ref --format='%(contents)' "refs/tags/${TAGREF}" 2>/dev/null)" ]] ;;
  esac
}
if nothing_to_compare; then
  echo "${YELLOW}⚠ auto-sign token: NOTHING TO COMPARE — ${NOTHING_REASON}.${NC}"
  echo "  The check did not run. That is not a pass."
  exit 3
fi

# ------------------------------------------------------------------- the live value
# Obtained at run time, never stored. $AUTO_SIGN_TOKEN first (an agent's shell, CI's secret
# store), else the repo's own helper, which reads it from the backend server's .env over ssh
# and checks it live. One call, at most: the pre-push hook runs this on every push.
TOKEN=""
TOKEN_SOURCE=""
TOKEN_ERR=""
if [[ -n "${AUTO_SIGN_TOKEN:-}" ]]; then
  TOKEN="$AUTO_SIGN_TOKEN"
  TOKEN_SOURCE='$AUTO_SIGN_TOKEN'
elif [[ -x "$TOKEN_SCRIPT" ]]; then
  err_file="$(mktemp)"
  TOKEN="$("$TOKEN_SCRIPT" 2>"$err_file" || true)"
  TOKEN_ERR="$(cat "$err_file" 2>/dev/null || true)"
  rm -f "$err_file"
  TOKEN_SOURCE="$TOKEN_SCRIPT"
fi
# A value this short is not a credential — comparing a diff against it would flag every line
# that happens to contain it. Treat it as "not obtained" rather than as a value.
[[ ${#TOKEN} -lt 16 ]] && TOKEN=""

if [[ -z "$TOKEN" ]]; then
  # Say exactly what was NOT checked. A push must not pass for want of a token: in the normal
  # mode this is a loud warning (the hook prints it, the push continues), and under
  # --require-token it is a hard failure.
  echo "${YELLOW}⚠ auto-sign token: SKIPPED — the live token could not be obtained, so this change was NOT compared against it.${NC}"
  [[ -n "$TOKEN_ERR" ]] && echo "  ${TOKEN_ERR}"
  echo "  Set AUTO_SIGN_TOKEN, or make ${TOKEN_SCRIPT} work (it reads the token from the backend server's .env over ssh)."
  if (( REQUIRE_TOKEN )); then
    echo "${RED}✗ auto-sign token: no token, so the check did not run.${NC}"
    echo "  → set AUTO_SIGN_TOKEN (CI: the Actions secret) or run this where the server is reachable."
    echo
    echo "${RED}${BOLD}Auto-sign token gate MISCONFIGURED.${NC} Nothing was pushed."
    exit 2
  fi
  exit 0
fi

# The base64 form of the same value: a token pasted into a blob as base64 is still the
# credential, and it is one `base64` call to look for. (The unpadded form too — a blob
# written by hand often drops the padding.)
MASK='<AUTO_SIGN_TOKEN>'
MASK_B64='<AUTO_SIGN_TOKEN base64>'
TOKEN_B64="$(printf '%s' "$TOKEN" | base64 | tr -d '\n')"
TOKEN_B64_NP="${TOKEN_B64%%=*}"
PATTERNS=("$TOKEN")
[[ -n "$TOKEN_B64" ]] && PATTERNS+=("$TOKEN_B64")
[[ -n "$TOKEN_B64_NP" && "$TOKEN_B64_NP" != "$TOKEN_B64" ]] && PATTERNS+=("$TOKEN_B64_NP")

# Does this line carry the value? A literal comparison — the value is 64 hex characters, and
# a pattern built from it would be a regex over a secret.
carries_value() {
  local l="$1"
  case "$l" in *"$TOKEN"*) return 0 ;; esac
  [[ -n "$TOKEN_B64" ]] && { case "$l" in *"$TOKEN_B64"*) return 0 ;; esac; }
  [[ -n "$TOKEN_B64_NP" ]] && { case "$l" in *"$TOKEN_B64_NP"*) return 0 ;; esac; }
  return 1
}

# The value is masked wherever it is reported: it is a live credential, and a finding that
# prints it would leak it into the terminal, the CI log and the transcript.
mask_value() {
  local t="$1"
  t="${t//"$TOKEN"/$MASK}"
  [[ -n "$TOKEN_B64" ]] && t="${t//"$TOKEN_B64"/$MASK_B64}"
  [[ -n "$TOKEN_B64_NP" ]] && t="${t//"$TOKEN_B64_NP"/$MASK_B64}"
  # Any other auto_signed= value is masked as well: a credential-looking value must not
  # leave the machine, and scripts/_auto_sign.py's redact() does the same.
  printf '%s' "$t" | sed -E "s/(auto_signed=)[^&[:space:]\"']+/\1${MASK}/g"
}

echo "${BOLD}Auto-sign token gate${NC} — scanning ${SCOPE_DESC}"

# ------------------------------------------------------------------- layer 1: added lines
hits=""
n_hits=0
while IFS= read -r l; do
  [[ -n "$l" ]] || continue
  if carries_value "$l"; then
    (( n_hits++ ))
    [[ $n_hits -le 20 ]] && hits+="  line: $(mask_value "$l" | cut -c1-200)"$'\n'
  fi
done < <(added_lines 2>/dev/null || true)

# ---------------------------------------------------------------- layer 3: every commit
# The tree diff above is the NET change of the range. A commit that adds the value and a
# later commit in the same push that removes it leaves the tree unchanged — and the value
# in that commit is pushed all the same. So every commit's own added lines are compared too,
# the way gitleaks walks the range. This is the layer that sees what the tree diff cannot.
if [[ "$MODE" == "range" ]]; then
  while IFS= read -r l; do
    [[ -n "$l" ]] || continue
    if carries_value "$l"; then
      (( n_hits++ ))
      [[ $n_hits -le 20 ]] && hits+="  commit: $(mask_value "$l" | cut -c1-200)"$'\n'
    fi
  done < <(git log -p --unified=0 --no-renames --format='' "$RANGE" -- . 2>/dev/null | diff_to_located)
  # A commit message travels with the push, and the leak gate reads messages for the same
  # reason: the first real catch by that gate was a customer name in a subject, not a file.
  while IFS= read -r l; do
    [[ -n "$l" ]] || continue
    if carries_value "$l"; then
      (( n_hits++ ))
      [[ $n_hits -le 20 ]] && hits+="  message: $(mask_value "$l" | cut -c1-200)"$'\n'
    fi
  done < <(git log --format='%B' "$RANGE" 2>/dev/null)
fi

# ------------------------------------------------------------------ layer 2: file content
# The files the change touches, at the tip of the range. This is what catches a token in a
# binary (a diff of one shows no line) and a token in a line the change did not add.
# git grep reads the patterns from a pipe, so the value never reaches a command line.
emit_patterns() { printf '%s\n' "${PATTERNS[@]}"; }

content_hits=""
GREP_ERR=""
SCAN_OUT=""
grep_tree=""
case "$MODE" in
  range)  grep_tree="$TIP" ;;
  all)    grep_tree="HEAD" ;;
  staged) grep_tree="" ;;
esac

scan_paths() {  # scan_paths <tree> <paths...>  → sets SCAN_OUT / GREP_ERR
  local tree="$1"; shift
  local -a pre=(-n -a -F)
  [[ "$MODE" == "staged" ]] && pre=(--cached -n -a -F)
  # The process substitution has to sit in the command itself: a process substitution
  # assigned into an array is closed when that assignment ends, and git grep would then be
  # handed a dead /dev/fd/N and quietly match nothing. It also has to come BEFORE the
  # tree-ish: git stops parsing options at the first revision, so "HEAD -f <file>" asks
  # git to resolve "-f" as a revision.
  local rc=0
  # `tr -d '\0'` keeps the NUL bytes of a binary match out of the command substitution: bash
  # drops them with a warning on stderr that would otherwise show up in the report.
  if [[ -n "$tree" ]]; then
    SCAN_OUT="$(git grep "${pre[@]}" -f <(emit_patterns) "$tree" -- "$@" 2>&1 | tr -d '\0')" || rc=$?
  else
    SCAN_OUT="$(git grep "${pre[@]}" -f <(emit_patterns) -- "$@" 2>&1 | tr -d '\0')" || rc=$?
  fi
  if (( rc > 1 )); then
    GREP_ERR+="${SCAN_OUT}"$'\n'
    SCAN_OUT=""
  fi
  return 0
}

paths=()
if [[ "$MODE" == "all" ]]; then
  # The whole tree at HEAD, in one pass — no pathspec.
  scan_paths "$grep_tree"
  content_hits+="${SCAN_OUT}"$'\n'
else
  while IFS= read -r p; do [[ -n "$p" ]] && paths+=("$p"); done < <(changed_paths 2>/dev/null || true)
  if [[ ${#paths[@]} -gt 0 ]]; then
    chunk=(); n=0
    for p in "${paths[@]}"; do
      chunk+=("$p"); n=$((n+1))
      if (( n >= 100 )); then
        scan_paths "$grep_tree" "${chunk[@]}"
        content_hits+="${SCAN_OUT}"$'\n'
        chunk=(); n=0
      fi
    done
    if [[ ${#chunk[@]} -gt 0 ]]; then
      scan_paths "$grep_tree" "${chunk[@]}"
      content_hits+="${SCAN_OUT}"$'\n'
    fi
  fi
fi

# git grep prefixes its output with the tree it searched ("<sha>:path:line:text").
if [[ -n "$grep_tree" ]]; then
  content_hits="$(printf '%s' "$content_hits" | sed -e "s|^${grep_tree}:||")"
fi
while IFS= read -r l; do
  [[ -n "$l" ]] || continue
  if carries_value "$l"; then
    (( n_hits++ ))
    [[ $n_hits -le 20 ]] && hits+="  file: $(mask_value "$l" | cut -c1-200)"$'\n'
  fi
done <<< "$content_hits"

if [[ -n "$GREP_ERR" ]]; then
  # The content layer could not run. Say so instead of letting a weaker check read as a pass.
  echo "${YELLOW}⚠ auto-sign token: the file-content layer could not run — only the added lines and the commits were compared.${NC}"
  printf '%s' "$GREP_ERR" | sed 's/^/  /'
fi

if (( n_hits > 0 )); then
  echo "${RED}✗ auto-sign token: the live auto-sign token is in this change${NC}"
  printf '%s' "$hits"
  [[ $n_hits -gt 20 ]] && echo "  … and more (${n_hits} findings in all)"
  echo "  → the value is live: rotate it (the owner's call), take it out of the commit, then push again."
  echo "  → the value is masked on purpose. It is never printed, never stored and never passed on a command line."
  echo
  echo "${RED}${BOLD}Auto-sign token gate FAILED.${NC} Nothing was pushed."
  exit 1
fi

echo "${GREEN}✓ auto-sign token: clean${NC} (the live token is not in ${SCOPE_DESC}, source: ${TOKEN_SOURCE})"
exit 0
