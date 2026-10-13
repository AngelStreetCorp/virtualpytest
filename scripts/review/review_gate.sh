#!/usr/bin/env bash
#
# Review gate — cheap, deterministic checks on exactly what a push sends. No AI, no tokens.
#
# Runs from .githooks/pre-push next to the leak gate, so every clone that ran bootstrap.sh
# (Mac, codebox, VMs) gets it — nothing per-machine to install. Checks only the files the
# push changes, so pre-existing debt elsewhere never blocks you.
#
#   block  Python fatal errors in changed .py files (syntax, undefined names) — ruff E9,F63,F7,F82
#   block  TypeScript errors located in changed frontend files — tsc --noEmit, filtered
#   block  ESLint errors in changed frontend files
#   warn   added console.log / raw fetch() in frontend (CONTRACTS §9)
#   warn   added DB queries in shared/src/lib/database/ with no team_id in the change (CONTRACTS §7)
#
# A missing tool (no ruff, no frontend/node_modules) skips that check with a note — it never
# fails the push. The AI review is separate and on demand: the `review` mod in claude-mods/.
#
# Usage:
#   review_gate.sh                 # origin/<branch>..HEAD, else fork point from origin/main
#   review_gate.sh --range A..B    # an explicit commit range (what pre-push passes)
#
# Bypass (say why in the PR):  REVIEW_GATE_SKIP=1 git push
# Exit: 0 clean or warnings only · 1 blocking findings

set -uo pipefail

if [[ -n "${REVIEW_GATE_SKIP:-}" ]]; then
  echo "review_gate: SKIPPED (REVIEW_GATE_SKIP set)" >&2
  exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

RANGE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --range) RANGE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "review_gate: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; NC=""
fi

if [[ -z "$RANGE" ]]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if git rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
    RANGE="origin/${branch}..HEAD"
  else
    base="$(git merge-base HEAD origin/main 2>/dev/null || true)"
    RANGE="${base:+${base}..HEAD}"
  fi
fi
[[ -z "$RANGE" ]] && { echo "${YELLOW}review_gate: nothing to compare against, skipping${NC}"; exit 0; }

# Files that still exist at the tip of the range.
# (no mapfile: macOS ships bash 3.2)
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(git diff --name-only --diff-filter=ACMR "$RANGE" 2>/dev/null)
[[ ${#FILES[@]} -eq 0 ]] && { echo "${GREEN}✓ review gate: no changed files${NC}"; exit 0; }

PY=(); TS=()
for f in "${FILES[@]}"; do
  [[ -f "$f" ]] || continue
  case "$f" in
    *.py) PY+=("$f") ;;
    frontend/*.ts|frontend/*.tsx) TS+=("$f") ;;
  esac
done

blocked=0; warned=0
fail() { echo "${RED}✗ $1${NC}"; blocked=1; }
warn() { echo "${YELLOW}! $1${NC}"; warned=1; }
note() { echo "  $1"; }

# Added lines of one path in the range, as `<lineno>:<text>`.
added() {
  git diff --unified=0 "$RANGE" -- "$1" | awk '
    /^@@ / { m = $3; sub(/^\+/, "", m); split(m, a, ","); n = a[1] + 0; next }
    /^\+\+\+ / { next }
    /^\+/ { print n ":" substr($0, 2); n++ }'
}

# ---------------------------------------------------------------- python
if [[ ${#PY[@]} -gt 0 ]]; then
  if command -v ruff >/dev/null; then
    out="$(ruff check --isolated --select E9,F63,F7,F82 --output-format concise -q "${PY[@]}" 2>&1)"
    if [[ -n "$out" ]]; then fail "python: fatal errors in changed files"; echo "$out" | sed 's/^/  /'; fi
  else
    note "python: ruff not installed, skipped (pip install ruff)"
  fi
fi

# ---------------------------------------------------------------- frontend
if [[ ${#TS[@]} -gt 0 ]]; then
  BIN="frontend/node_modules/.bin"
  if [[ -x "$BIN/tsc" ]]; then
    # Whole-project typecheck (types cross files), but only errors in changed files count.
    # tsc prints `src/x.ts(12,3): error ...`; match each changed path followed by `(`.
    out="$(cd frontend && ./node_modules/.bin/tsc --noEmit 2>&1 | grep -F -f <(printf '%s(\n' "${TS[@]#frontend/}"))"
    if [[ -n "$out" ]]; then fail "frontend: type errors in changed files"; echo "$out" | sed 's/^/  /'; fi
  else
    note "frontend: no node_modules, tsc skipped (cd frontend && npm ci)"
  fi
  if [[ -x "$BIN/eslint" ]]; then
    out="$(cd frontend && ./node_modules/.bin/eslint --quiet "${TS[@]#frontend/}" 2>&1)"
    if [[ -n "$out" ]]; then fail "frontend: eslint errors"; echo "$out" | sed 's/^/  /'; fi
  fi
  for f in "${TS[@]}"; do
    hits="$(added "$f" | grep -E 'console\.log\(|(^|[^.a-zA-Z_])fetch\(' || true)"
    [[ -n "$hits" ]] && { warn "frontend: console.log / raw fetch() added in $f (use apiClient, CONTRACTS §9)"; echo "$hits" | sed "s|^|  $f:|"; }
  done
fi

# ---------------------------------------------------------------- team_id
for f in ${PY[@]+"${PY[@]}"}; do
  [[ "$f" == shared/src/lib/database/* ]] || continue
  [[ "$f" == */ai_routing_db.py ]] && continue   # named exception, CONTRACTS §7
  lines="$(added "$f")"
  if echo "$lines" | grep -qE '\.(table|rpc)\(' && ! echo "$lines" | grep -q 'team_id'; then
    warn "db: new query in $f with no team_id in the change (CONTRACTS §7)"
  fi
done

# ---------------------------------------------------------------- verdict
if [[ $blocked -eq 1 ]]; then
  echo "${RED}review gate: blocked. Fix, or bypass with REVIEW_GATE_SKIP=1 git push (say why in the PR)${NC}"
  exit 1
fi
[[ $warned -eq 1 ]] && echo "${YELLOW}review gate: passed with warnings${NC}" || echo "${GREEN}✓ review gate: clean (${#FILES[@]} files)${NC}"
exit 0
