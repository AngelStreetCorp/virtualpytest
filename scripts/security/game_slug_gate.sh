#!/usr/bin/env bash
#
# Game-slug gate — refuses to push any path under a configured commercial-game slug
# (TASK-81 §81.1 R4 / §Shared Privacy).
#
# The list of slugs lives in docs/agent/release/game-slug-paths.txt. The check is
# path-only: an added line of code that mentions the slug text in a different file
# (e.g. `test_scripts/android/app_install.py` lists the `clashofclans` install entry
# under a `test_scripts/android/` path) is NOT refused, because the file does not
# live under `**/clashofclans/**`. The privacy requirement is on where the
# companion code LIVES, not on what strings the rest of the tree knows.
#
# Style + shape match scripts/security/leak_gate.sh on purpose: same mode names
# (range / staged / all / tag-message), same diff streaming (`-file:line:text`),
# same scope-of-the-push over the change set, same precedence of safety. The
# release-note copy lives in docs/agent/release/GAME_SLUG_GATE.md.
#
# Usage:
#   game_slug_gate.sh                       # origin/<branch>..HEAD (what a push would send)
#   game_slug_gate.sh --range A..B          # an explicit commit range
#   game_slug_gate.sh --staged              # the index, for a pre-commit hook
#   game_slug_gate.sh --all                 # every tracked file at HEAD (pre-publish audit)
#   game_slug_gate.sh --tag-message <tag>   # tag's own message (pre-push hook)
#
# Bypass (say why in the PR):  GAME_SLUG_GATE_SKIP=1 git push
# Exit: 0 clean · 1 findings · 2 misconfigured (missing slug list)

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2

SLUGS_FILE="${GAME_SLUG_PATHS_FILE:-docs/agent/release/game-slug-paths.txt}"
MODE="range"
RANGE=""
TAGREF=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --range)        MODE="range";  RANGE="${2:-}"; shift 2 ;;
    --staged)       MODE="staged"; shift ;;
    --all)          MODE="all";    shift ;;
    --tag-message)  MODE="tagmsg"; TAGREF="${2:-}"; shift 2 ;;
    -h|--help)      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              echo "game_slug_gate: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; NC=""; BOLD=""
fi

# ---------------------------------------------------------------- resolve the change set
if [[ "$MODE" == "range" && -z "$RANGE" ]]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
    RANGE="${upstream}..HEAD"
  elif git rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
    RANGE="origin/${branch}..HEAD"
  else
    # New branch with no upstream yet — same fallback as leak_gate.sh, fall back to the
    # fork point from origin/main so a first push is still scanned rather than skipped.
    base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
    RANGE="${base:+${base}..HEAD}"
    [[ -z "$RANGE" ]] && { echo "${YELLOW}game_slug_gate: no upstream and no origin/main — nothing to compare against, skipping${NC}"; exit 0; }
  fi
fi

case "$MODE" in
  range)
    if [[ -z "$(git rev-list "$RANGE" 2>/dev/null)" ]]; then
      echo "${GREEN}✓ game-slug gate: nothing to scan (${RANGE} is empty)${NC}"; exit 0
    fi
    SCOPE_DESC="$RANGE"
    changed_files() { git diff --name-only --diff-filter=ACMR "$RANGE"; }
    ;;
  staged)
    SCOPE_DESC="staged changes"
    changed_files() { git diff --cached --name-only --diff-filter=ACMR; }
    ;;
  all)
    SCOPE_DESC="every tracked file at HEAD"
    changed_files() { git ls-files; }
    ;;
  tagmsg)
    # tag messages don't carry paths, so this gate has nothing to check — be loud anyway,
    # because callers wired this up next to leak_gate.sh and a silent "OK" looks like a
    # checked pass. The hook itself should be the only caller of this mode.
    echo "${YELLOW}game-slug gate: tag messages carry no paths; this mode is a no-op here.${NC}"
    exit 0
    ;;
esac

echo "${BOLD}Game-slug gate${NC} — scanning ${SCOPE_DESC}"

# ---------------------------------------------------------------- load the slug list
# Fail CLOSED on a missing list: the gate's safety floor is "no slug path leaves
# the machine", so a config that goes missing between editor and push MUST refuse
# the push. The fix is to put the file back, never to bypass the gate.
if [[ ! -f "$SLUGS_FILE" ]]; then
  echo "${RED}✗ game-slug gate: ${SLUGS_FILE} missing.${NC}"
  echo "  Restore it (git checkout), or bypass with GAME_SLUG_GATE_SKIP=1 git push (say why in the PR)."
  exit 2
fi

# Strip comments + blanks. Every slug must end with `/` so the match is `**/<slug>/**`
# (a directory test) — a leaf file named `clashofclans.py` somewhere else in the tree
# would otherwise leak. Reject the line silently if it doesn't end with `/`: the
# safeguard is "the next maintainer types it the way the rest of the file looks".
SLUG_REGEX="$(sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$SLUGS_FILE" \
              | grep -v '^$' \
              | grep '/$' \
              | sed -e 's/[][\.^$*+?(){}|\\]/\\&/g' \
              | paste -sd'|' - || true)"
if [[ -z "$SLUG_REGEX" ]]; then
  bad_lines="$(sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$SLUGS_FILE" \
               | grep -v '^$' | grep -v '/$' || true)"
  if [[ -n "$bad_lines" ]]; then
    echo "${RED}✗ game-slug gate: every entry in ${SLUGS_FILE} must end with '/'.${NC}"
    printf '%s\n' "$bad_lines" | sed 's/^/  /'
  else
    echo "${RED}✗ game-slug gate: no slug entries in ${SLUGS_FILE}.${NC}"
  fi
  exit 2
fi
# Anchor to the start of the path so `clashofclans/` matches `clashofclans/foo.py` AND
# `deep/nested/path/clashofclans/foo.py`, but not `docs/clashofclans.md` at the end.
SLUG_REGEX="^(${SLUG_REGEX})"

# ---------------------------------------------------------------- the check itself
all_paths="$(changed_files 2>/dev/null || true)"
hits="$(printf '%s\n' "$all_paths" | grep -E "${SLUG_REGEX}" || true)"

if [[ -n "${hits// /}" ]]; then
  echo "${RED}✗ game-slug gate: paths under a commercial-game slug are forbidden in pushed trees${NC}"
  printf '%s' "$hits" | sed 's/^/  /'
  echo "  → keep companion code local; for fixtures, use a top-level test path (e.g." >&2
  echo "    tests/shared/test_<slug>_*.py) instead of a real /<slug>/ tree." >&2
  echo "  → if the path is genuinely the right home, list it in" >&2
  echo "    ${SLUGS_FILE}'s override slots — they do not exist by design." >&2
  exit 1
fi

n="$(printf '%s\n' "$all_paths" | grep -cv '^$' || echo 0)"
slug_count="$(printf '%s' "$SLUG_REGEX" | tr '|' '\n' | grep -c '^')"
echo "${GREEN}✓ game-slug gate: clean${NC} (${n} changed files, ${slug_count} slug entries)"
exit 0
