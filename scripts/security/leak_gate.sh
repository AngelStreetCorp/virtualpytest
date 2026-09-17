#!/usr/bin/env bash
#
# Leak gate — refuses to let customer identifiers or credentials leave the repo.
#
# Two independent checks over the SAME set of changes:
#
#   1. identifiers  customer names, codenames, site hostnames and lab addresses — in added
#                   lines, in file paths, and in commit messages (a message is pushed too). The real
#                   terms are sensitive themselves (publishing "the strings to grep for"
#                   recreates the leak), so they are never committed — they come from the
#                   gitignored docs/agent/leak-terms.local.txt, or from $LEAK_TERMS in CI.
#                   Policy + replacement convention: docs/agent/release/ANONYMIZATION.md.
#   2. secrets      gitleaks over the same range, using .gitleaks.toml.
#
# Scope is the change set, not the tree. A full-tree scan reports ~94 documentation
# placeholders and would be ignored within a week; gating what you are about to push keeps
# the signal at 100% and the run under a second. Use --all for the pre-publish audit
# (TASK-14 §2) where the whole tree genuinely has to be clean.
#
# Usage:
#   leak_gate.sh                       # origin/<branch>..HEAD (what a push would send)
#   leak_gate.sh --range A..B          # an explicit commit range
#   leak_gate.sh --staged              # the index, for a pre-commit hook
#   leak_gate.sh --all                 # every tracked file at HEAD (pre-publish audit).
#                                      # Ignored/untracked files are out of scope in BOTH
#                                      # checks — .env and dist/ are not what gets published.
#   leak_gate.sh --require-terms       # fail if no term list is available (use in CI)
#
# Exit: 0 clean · 1 findings · 2 misconfigured (missing terms under --require-terms)

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2

TERMS_FILE="${LEAK_TERMS_FILE:-docs/agent/leak-terms.local.txt}"
MODE="range"
RANGE=""
REQUIRE_TERMS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --range)          MODE="range";  RANGE="${2:-}"; shift 2 ;;
    --staged)         MODE="staged"; shift ;;
    --all)            MODE="all";    shift ;;
    --require-terms)  REQUIRE_TERMS=1; shift ;;
    -h|--help)        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "leak_gate: unknown argument '$1'" >&2; exit 2 ;;
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
    [[ -z "$RANGE" ]] && { echo "${YELLOW}leak_gate: no upstream and no origin/main — nothing to compare against, skipping${NC}"; exit 0; }
  fi
fi

# Rewrite a unified diff into `+<path>:<lineno>:<text>` — one line per ADDED line, carrying
# the file it lives in and its line number in the new file. Two reasons this matters:
#
#   1. the tier-2 path exemption below is per-line, so every finding needs its path;
#   2. it is what a human needs anyway. Before this, a range-mode finding read
#      `line: 6:+# ...` where "6" was the offset into the diff stream — not a file, not a
#      usable line number. Now it reads `line: +path/to/file.py:21:+# ...`.
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

case "$MODE" in
  range)
    if [[ -z "$(git rev-list "$RANGE" 2>/dev/null)" ]]; then
      echo "${GREEN}✓ leak gate: nothing to scan (${RANGE} is empty)${NC}"; exit 0
    fi
    SCOPE_DESC="$RANGE"
    changed_files() { git diff --name-only --diff-filter=ACMR "$RANGE"; }
    added_lines()   { git diff --unified=0 --diff-filter=ACMR "$RANGE" -- . | diff_to_located; }
    # Commit messages travel with the push and are just as public as the tree — the first
    # real catch by this gate was a customer name in a commit subject, not in a file.
    messages()      { git log --format='%h %s%n%b' "$RANGE"; }
    ;;
  staged)
    SCOPE_DESC="staged changes"
    changed_files() { git diff --cached --name-only --diff-filter=ACMR; }
    added_lines()   { git diff --cached --unified=0 --diff-filter=ACMR -- . | diff_to_located; }
    messages()      { :; }   # no message written yet at pre-commit time
    ;;
  all)
    SCOPE_DESC="every tracked file at HEAD"
    changed_files() { git ls-files; }
    # Every line is "added" in a full-tree audit. The '+' prefix is not cosmetic: the caller
    # filters on it to skip diff context lines, so without it --all silently checked PATHS
    # ONLY and passed a tree with customer identifiers in file contents (found 2026-09-14,
    # three occurrences of a customer product name in features/avq/.../localize/).
    added_lines()   { git ls-files -z | xargs -0 grep -nIH '' 2>/dev/null | sed 's/^/+/'; }
    messages()      { :; }   # history is out of scope; TASK-14 publishes a fresh tree
    ;;
esac

echo "${BOLD}Leak gate${NC} — scanning ${SCOPE_DESC}"
FAILED=0

# ------------------------------------------------------------------- 1. identifier check
# The term file is gitignored, so it exists only in the clone it was created in — a linked
# worktree (git worktree add) has its own working dir and therefore NO copy, which silently
# downgraded the identifier check to SKIPPED on every push from a worktree. Fall back to the
# main worktree, which git names via --git-common-dir.
resolve_terms_file() {
  [[ -f "$TERMS_FILE" ]] && { printf '%s' "$TERMS_FILE"; return; }
  local common main
  common="$(git rev-parse --git-common-dir 2>/dev/null)" || return
  [[ -n "$common" ]] || return
  main="$(cd "$common/.." 2>/dev/null && pwd)" || return
  [[ -f "$main/$TERMS_FILE" ]] && printf '%s' "$main/$TERMS_FILE"
}

load_terms() {
  local f
  if [[ -n "${LEAK_TERMS:-}" ]]; then
    printf '%s\n' "$LEAK_TERMS" | tr ',' '\n'
  elif f="$(resolve_terms_file)" && [[ -n "$f" ]]; then
    cat "$f"
  fi | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v '^$'
}

TERMS="$(load_terms)"

if [[ -z "$TERMS" ]]; then
  if (( REQUIRE_TERMS )); then
    echo "${RED}✗ identifiers: no term list.${NC}"
    echo "  Set the LEAK_TERMS secret (CI) or create ${TERMS_FILE} (local)."
    echo "  See docs/agent/release/ANONYMIZATION.md and ${TERMS_FILE}.example"
    exit 2
  fi
  echo "${YELLOW}⚠ identifiers: SKIPPED — no ${TERMS_FILE} and no \$LEAK_TERMS.${NC}"
  echo "  cp ${TERMS_FILE}.example ${TERMS_FILE} and fill it in (gitignored) to enable this check."
else
  # Two kinds of term:
  #
  #   plain     matched case-insensitively as a PREFIX at a word boundary, so a listed stem
  #             like `acme07` catches `acme07vmd41` and `acme07vfr101` without enumerating
  #             every host. (A trailing \b would miss both — digit->letter is word-to-word.)
  #
  #   /regex/   a term wrapped in slashes is used verbatim as an ERE, with no escaping and no
  #             implied \b. This exists because a prefix match is unusable for a term that is
  #             also the stem of an ordinary English word — one real product name here matched
  #             296 lines in this tree, 293 of them an unrelated CSS keyword, which is why it
  #             had been left out of the list entirely. Such a term goes in as
  #             /stem([^a-z]|$)/ so it still catches `stem_nav` and "Stem TV" but not
  #             "stemlike". Keep the regex anchored and specific — it is not escaped, so a
  #             sloppy one matches everything.
  #
  # Both kinds are matched against added lines AND against changed paths, since a file named
  # after a customer leaks as loudly as its contents.
  # ---- tiers -----------------------------------------------------------------------------
  # A term prefixed with `~` is TIER 2: the customer's CODENAME. It is checked only where the
  # content can actually reach the public repo. Everything else is TIER 1 and is absolute.
  #
  # Why the split (full rationale: ANONYMIZATION.md "Two tiers"):
  #   tier 1  the customer's real name, real site hostnames, real product names, lab addresses.
  #           These must not exist in this repo at all — no path, no message, no exception.
  #   tier 2  the codename. ANONYMIZATION.md PRESCRIBES it as the replacement for tier-1
  #           material, and it names real things (the overlay repo, the working dir, bundle
  #           filenames), so internal runbooks cannot avoid it without becoming wrong. But it
  #           is pseudonymisation, not anonymisation — publish it next to a bundle name and it
  #           joins straight back to the customer — so it stays gated everywhere that publishes.
  #
  # Tier 2 is exempt in exactly two places, and both are places the public snapshot can never
  # see, because TASK-14 §2 builds that snapshot from a fresh tree per tag:
  #   - paths listed in scripts/security/internal-paths.txt, which publish_public.sh deletes
  #     from the export (§2.2);
  #   - commit messages, since history is never published at all (§0).
  # Tier 1 applies to both of those regardless.
  tier2_terms="$(printf '%s\n' "$TERMS" | grep '^~' | sed 's/^~//' || true)"
  tier1_terms="$(printf '%s\n' "$TERMS" | grep -v '^~' || true)"

  # Build the line/path regexes for one tier. Plain terms are escaped and word-anchored;
  # /regex/ terms are passed through verbatim. Sets ${2}_LINE_RE and ${2}_PATH_RE.
  build_tier_re() {
    local terms="$1" prefix="$2" plain regex plain_re raw_re line_re path_re
    plain="$(printf '%s\n' "$terms" | grep -v '^/.*/$' | grep -v '^$' || true)"
    regex="$(printf '%s\n' "$terms" | grep '^/.*/$' | sed -e 's|^/||' -e 's|/$||' || true)"
    plain_re="$(printf '%s\n' "$plain" | grep -v '^$' | sed 's/[][\.^$*+?(){}|\\]/\\&/g' | paste -sd'|' - || true)"
    raw_re="$(printf '%s\n' "$regex" | grep -v '^$' | paste -sd'|' - || true)"
    line_re=""; path_re=""
    [[ -n "$plain_re" ]] && { line_re="\\b(${plain_re})"; path_re="(${plain_re})"; }
    [[ -n "$raw_re" ]] && { line_re="${line_re:+${line_re}|}(${raw_re})"; path_re="${path_re:+${path_re}|}(${raw_re})"; }
    printf -v "${prefix}_LINE_RE" '%s' "$line_re"
    printf -v "${prefix}_PATH_RE" '%s' "$path_re"
  }
  build_tier_re "$tier1_terms" T1
  build_tier_re "$tier2_terms" T2

  # ---- the internal-only path list (shared with publish_public.sh) -------------------------
  # Missing file => FAIL CLOSED: no exemption, tier 2 is checked everywhere. Noisier, never
  # weaker — the one outcome we must not have is silently waving a codename through because a
  # config file went missing.
  INTERNAL_PATHS_FILE="${INTERNAL_PATHS_FILE:-scripts/security/internal-paths.txt}"
  INTERNAL_RE=""
  if [[ -f "$INTERNAL_PATHS_FILE" ]]; then
    # Escape every regex metacharacter, then re-enable `*` as "anything but a slash" so a
    # glob like docs/security/*.json stays scoped to one path segment.
    INTERNAL_RE="$(sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$INTERNAL_PATHS_FILE" \
                    | grep -v '^$' | sed -e 's/[][\.^$*+?(){}|\\]/\\&/g' -e 's/\\\*/[^\/]*/g' \
                    | paste -sd'|' - || true)"
  elif [[ -n "$T2_LINE_RE" ]]; then
    echo "${YELLOW}⚠ identifiers: ${INTERNAL_PATHS_FILE} missing — codename terms checked everywhere.${NC}"
  fi
  # added_lines emits `+<path>:<line>:<text>`; changed_files emits a bare path.
  drop_internal_lines() { [[ -n "$INTERNAL_RE" ]] && grep -vE "^\\+(${INTERNAL_RE})" || cat; }
  drop_internal_paths() { [[ -n "$INTERNAL_RE" ]] && grep -vE "^(${INTERNAL_RE})" || cat; }

  hits=""
  all_lines="$(added_lines 2>/dev/null | grep -E '^\+' | grep -v '^+++' || true)"
  all_paths="$(changed_files 2>/dev/null || true)"
  all_msgs="$(messages 2>/dev/null || true)"

  # Tier 1 — everywhere.
  lines=""; paths=""; msgs=""
  if [[ -n "$T1_LINE_RE" ]]; then
    lines="$(printf '%s\n' "$all_lines" | grep -iE "${T1_LINE_RE}" || true)"
    msgs="$(printf '%s\n' "$all_msgs" | grep -inE "${T1_LINE_RE}" || true)"
  fi
  [[ -n "$T1_PATH_RE" ]] && paths="$(printf '%s\n' "$all_paths" | grep -inE "${T1_PATH_RE}" || true)"

  # Tier 2 — publishable paths only; commit messages skipped entirely.
  if [[ -n "$T2_LINE_RE" ]]; then
    t2_lines="$(printf '%s\n' "$all_lines" | drop_internal_lines | grep -iE "${T2_LINE_RE}" || true)"
    [[ -n "$t2_lines" ]] && lines="${lines:+${lines}$'\n'}${t2_lines}"
  fi
  if [[ -n "$T2_PATH_RE" ]]; then
    t2_paths="$(printf '%s\n' "$all_paths" | drop_internal_paths | grep -inE "${T2_PATH_RE}" || true)"
    [[ -n "$t2_paths" ]] && paths="${paths:+${paths}$'\n'}${t2_paths}"
  fi

  [[ -n "$paths" ]] && hits+="  path: ${paths//$'\n'/$'\n'  path: }"$'\n'
  [[ -n "$msgs" ]] && hits+="$(printf '%s\n' "$msgs" | sed 's/^/  msg:  /' | cut -c1-200)"$'\n'
  [[ -n "$lines" ]] && hits+="$(printf '%s\n' "$lines" | sed 's/^/  line: /' | cut -c1-200)"$'\n'

  if [[ -n "${hits// /}" ]]; then
    echo "${RED}✗ identifiers: customer-identifying strings found${NC}"
    printf '%s' "$hits"
    echo "  → replace per docs/agent/release/ANONYMIZATION.md (customer material belongs in the overlay repo)"
    FAILED=1
  else
    n_t1="$(printf '%s\n' "$tier1_terms" | grep -cv '^$' || true)"
    n_t2="$(printf '%s\n' "$tier2_terms" | grep -cv '^$' || true)"
    echo "${GREEN}✓ identifiers: clean${NC} (${n_t1} tier-1 + ${n_t2} tier-2 terms)"
  fi
fi

# ---------------------------------------------------------------------- 2. secrets check
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "${YELLOW}⚠ secrets: SKIPPED — gitleaks not installed (brew install gitleaks).${NC}"
else
  gl_out="$(mktemp)"; gl_rep="$(mktemp)"; gl_tree=""
  case "$MODE" in
    range)  gitleaks detect --redact --no-banner --config .gitleaks.toml \
              --log-opts="$RANGE" --report-format json --report-path "$gl_rep" >"$gl_out" 2>&1 ;;
    staged) gitleaks protect --staged --redact --no-banner --config .gitleaks.toml \
              --report-format json --report-path "$gl_rep" >"$gl_out" 2>&1 ;;
    # --all means "every TRACKED file at HEAD", the same scope the identifier check above
    # gets from `git ls-files`. gitleaks --no-git walks the filesystem and does NOT honour
    # .gitignore, so pointing it at the repo scanned the developer's real .env, frontend/dist
    # and every other build artifact — on this machine 13 of ~20 findings were in files git
    # has never seen. A pre-publish audit that cannot pass on a working checkout is an audit
    # everyone learns to skip. Export HEAD to a scratch tree and scan exactly that; the
    # reported paths stay repo-relative because gitleaks reports relative to --source.
    all)    gl_tree="$(mktemp -d)"
            git archive HEAD | tar -x -C "$gl_tree"
            gitleaks detect --redact --no-banner --no-git --source "$gl_tree" \
              --config .gitleaks.toml --report-format json --report-path "$gl_rep" >"$gl_out" 2>&1 ;;
  esac
  count="$(grep -o '"RuleID"' "$gl_rep" 2>/dev/null | wc -l | tr -d ' ')"
  count="${count:-0}"
  if (( count > 0 )); then
    echo "${RED}✗ secrets: ${count} finding(s)${NC}"
    python3 - "$gl_rep" "$gl_tree" <<'PY' 2>/dev/null || cat "$gl_rep"
import json, sys
# --all scans an export of HEAD in a scratch dir, so gitleaks reports absolute paths into it.
# Strip that prefix: a finding has to name the repo path a human can open and fix.
root = (sys.argv[2] if len(sys.argv) > 2 else '').rstrip('/')
for f in json.load(open(sys.argv[1]))[:20]:
    path = f['File']
    if root and path.startswith(root + '/'):
        path = path[len(root) + 1:]
    print(f"  {f['RuleID']}: {path}:{f['StartLine']}  {f.get('Match','')[:80]!r}")
PY
    echo "  → rotate the value, then remove it from the commit (git rebase -i / amend)."
    echo "  → false positive? add a narrow allowlist entry to .gitleaks.toml, never a blanket path."
    FAILED=1
  else
    echo "${GREEN}✓ secrets: clean${NC}"
  fi
  rm -f "$gl_out" "$gl_rep"
  [[ -n "$gl_tree" ]] && rm -rf "$gl_tree"
fi

if (( FAILED )); then
  echo
  echo "${RED}${BOLD}Leak gate FAILED.${NC} Nothing was pushed."
  echo "Genuinely a false positive and you need to push now: ${BOLD}LEAK_GATE_SKIP=1 git push${NC} (say why in the PR)."
  exit 1
fi

echo "${GREEN}${BOLD}✓ Leak gate passed.${NC}"
exit 0
