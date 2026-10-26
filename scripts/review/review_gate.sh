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
#   block  ESLint findings in changed frontend files, with CI's flags (unused eslint-disable, --max-warnings 0)
#   block  frontend ui-check and i18n-check, when frontend files changed (CI's lint job runs both)
#   block  docs that reference missing paths or bad BUG ids (CI's docs-paths job), on every push
#   warn   added console.log / raw fetch() in frontend (CONTRACTS §9)
#   warn   added DB queries in shared/src/lib/database/ with no team_id in the change (CONTRACTS §7)
#
# A worktree without frontend/node_modules borrows the main checkout's for the run (agent
# worktrees never have one, so the frontend checks used to be skipped there and red CI on main
# was the first place lint ran, 2026-10-14). A missing tool still skips with a note, never fails. The AI review is separate and on demand: the `review` mod in claude-mods/.
#
# Usage:
#   review_gate.sh                 # origin/<branch>..HEAD, else fork point from origin/main
#   review_gate.sh --range A..B    # an explicit commit range (what pre-push passes)
#
# Bypass (say why in the PR):  REVIEW_GATE_SKIP=1 git push
# Exit: 0 clean or warnings only · 1 blocking findings

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

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
  # One heavy frontend check at a time per host, at low priority: tsc alone takes ~1 GB, and a dozen agents pushing at
  # once swapped codebox to load 130 (2026-10-15). flock is Linux-only; without it the checks just run.
  NICE=""; command -v nice >/dev/null && NICE="nice -n 10"
  if command -v flock >/dev/null; then
    exec 9>"${TMPDIR:-/tmp}/vpt-review-gate.lock"
    flock -n 9 || { note "frontend: another push is running the frontend checks on this host, waiting for it"; flock 9; }
  fi
  if [[ ! -e frontend/node_modules ]]; then
    main_nm="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)/frontend/node_modules"
    if [[ -d "$main_nm" ]] && ln -s "$main_nm" frontend/node_modules 2>/dev/null; then
      trap 'rm -f frontend/node_modules' EXIT
      note "frontend: using the main checkout's node_modules ($main_nm)"
    fi
  fi
  if [[ -x "$BIN/tsc" ]]; then
    # Whole-project typecheck (types cross files), but only errors in changed files count.
    # tsc prints `src/x.ts(12,3): error ...`; match each changed path followed by `(`.
    out="$(cd frontend && $NICE $(command -v vpt-tsc) ./node_modules/.bin/tsc --noEmit 2>&1 | grep -F -f <(printf '%s(\n' "${TS[@]#frontend/}"))"
    if [[ -n "$out" ]]; then fail "frontend: type errors in changed files"; echo "$out" | sed 's/^/  /'; fi
  else
    note "frontend: no node_modules, tsc skipped (cd frontend && npm ci)"
  fi
  if [[ -x "$BIN/eslint" ]]; then
    # Same flags as `npm run lint` in CI: an unused eslint-disable or any warning fails there.
    out="$(cd frontend && $NICE ./node_modules/.bin/eslint --report-unused-disable-directives --max-warnings 0 "${TS[@]#frontend/}" 2>&1)"
    if [[ $? -ne 0 ]]; then fail "frontend: eslint findings (CI fails on warnings too)"; echo "$out" | sed 's/^/  /'; fi
    out="$(cd frontend && node scripts/ui-check.mjs 2>&1)" || { fail "frontend: ui-check"; echo "$out" | tail -20 | sed 's/^/  /'; }
    out="$(cd frontend && node scripts/i18n-check.mjs 2>&1)" || { fail "frontend: i18n-check"; echo "$out" | tail -20 | sed 's/^/  /'; }
    out="$(cd frontend && node scripts/notify_check.mjs 2>&1)" || { fail "frontend: notify-check (bare toast call, contract #43)"; echo "$out" | tail -20 | sed 's/^/  /'; }
  fi
  for f in "${TS[@]}"; do
    hits="$(added "$f" | grep -E 'console\.log\(|(^|[^.a-zA-Z_])fetch\(' || true)"
    [[ -n "$hits" ]] && { warn "frontend: console.log / raw fetch() added in $f (use apiClient, CONTRACTS §9)"; echo "$hits" | sed "s|^|  $f:|"; }
  done
  exec 9>&- 2>/dev/null || true   # release the host lock before the cheap checks
fi

# ---------------------------------------------------------------- docs
# Cheap (seconds) and any rename or delete can break a doc link, so it runs on every push.
CHECKS=(scripts/docs/check_paths.sh scripts/docs/check_bug_ids.sh)
# The release-note format check (kinds, areas, one heading each, TASK-108) only matters when the note changed.
for f in ${FILES[@]+"${FILES[@]}"}; do
  [[ "$f" == docs/release_note/README.md ]] && CHECKS+=(scripts/release/check_release_notes.py)
done
# Docs served over MCP must stay anonymized (lab IPs, internal hosts, home paths, secrets): runs when docs/ or the serving filter changes.
for f in ${FILES[@]+"${FILES[@]}"}; do
  if [[ "$f" == docs/* || "$f" == backend_server/src/mcp/tools/docs_tools.py ]]; then
    CHECKS+=(scripts/security/served_docs_check.py); break
  fi
done
for chk in "${CHECKS[@]}"; do
  [[ -x "$chk" ]] || continue
  out="$("$chk" 2>&1)" || { fail "docs: ${chk##*/}"; echo "$out" | tail -20 | sed 's/^/  /'; }
done

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
