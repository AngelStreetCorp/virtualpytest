#!/usr/bin/env bash
# publish_public.sh — publish ONE release tag of the internal repo as ONE snapshot commit in the
# public repo (docs/tasks/TASK-14-public-snapshot-repo.md §2).
#
#   scripts/release/publish_public.sh <tag> [--target <git-url>] [--dry-run] [--keep] [--selftest]
#
#   <tag>        an existing tag of THIS repo (e.g. main-2026.09.15-8881 or release-2026.09.15)
#   --target     public repo to push into (default: $PUBLIC_REPO_URL or
#                git@github.com:AngelStreetCorp/virtualpytest.git)
#   --dry-run    do everything except `git push` — the prepared clone is left for inspection
#   --keep       keep the work directory even on success (printed at the end)
#   --selftest   plant a secret and a leak term into the export and PROVE the gates refuse
#                them (TASK-14 acceptance criterion); nothing is pushed
#   --reseed     REPLACE the public history with this single snapshot (orphan commit, force
#                push, tags re-pointed). Only for a repo that has never been public — it
#                rewrites what others may have cloned. Needs force-push allowed on the target.
#
# What it guarantees before anything leaves the machine:
#   1. the export is `git archive <tag>` — a tree, never history;
#   2. every path in scripts/security/internal-paths.txt (read from the EXPORT, so it matches
#      the tag) is deleted, plus the generated docs mirror frontend/public/docs (prebuild.sh
#      rebuilds it) and any real .env;
#   3. the identifier gate (leak_gate.sh --all, terms from the gitignored local list or
#      $LEAK_TERMS) and gitleaks are clean ON THE EXPORT — the codename is tier-1 here because
#      the paths where it is tolerated no longer exist;
#   4. VERSION.txt `current:` names the tag (or a tag on the same commit), BUNDLE_MANIFEST.txt is
#      absent, no .git directory travels;
#   5. the public commit is `release: <tag>` with the release-note build section as body, tagged
#      with <tag> and with every other `release-*`/`main-*` tag that points at the same commit.
#
# Exit codes: 0 published (or dry-run/selftest OK), 1 a gate refused the tree, 2 usage/setup.
set -euo pipefail

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
die()  { echo "${RED}✗ $*${NC}" >&2; exit 1; }
usage(){ sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

TAG=""; TARGET="${PUBLIC_REPO_URL:-git@github.com:AngelStreetCorp/virtualpytest.git}"
DRY_RUN=0; KEEP=0; SELFTEST=0; RESEED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)   TARGET="${2:-}"; shift 2 ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --keep)     KEEP=1; shift ;;
    --selftest) SELFTEST=1; shift ;;
    --reseed)   RESEED=1; shift ;;
    -h|--help)  usage ;;
    -*)         echo "unknown option: $1" >&2; usage ;;
    *)          [[ -z "$TAG" ]] || usage; TAG="$1"; shift ;;
  esac
done
[[ -n "$TAG" ]] || usage

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run inside the internal repo"
cd "$REPO_ROOT"
command -v gitleaks >/dev/null || die "gitleaks not installed (brew install gitleaks)"
[[ -x scripts/security/leak_gate.sh ]] || die "scripts/security/leak_gate.sh missing"
git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null || die "tag '${TAG}' does not exist here"
COMMIT="$(git rev-list -n1 "refs/tags/${TAG}")"
SHORT="${COMMIT:0:10}"

# The term list: the gate needs it even though docs/agent/ is gone from the export.
TERMS_FILE_ABS=""
if [[ -n "${LEAK_TERMS_FILE:-}" ]]; then TERMS_FILE_ABS="$(cd "$(dirname "$LEAK_TERMS_FILE")" && pwd)/$(basename "$LEAK_TERMS_FILE")"
elif [[ -f docs/agent/leak-terms.local.txt ]]; then TERMS_FILE_ABS="$REPO_ROOT/docs/agent/leak-terms.local.txt"; fi
[[ -n "$TERMS_FILE_ABS" || -n "${LEAK_TERMS:-}" ]] || die "no term list: create docs/agent/leak-terms.local.txt or set LEAK_TERMS"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/vpt-publish.XXXXXX")"
EXPORT="$WORK/export"; PUBLIC="$WORK/public"; GITLEAKS_REPORT="$WORK/gitleaks.json"
cleanup() { if [[ $KEEP -eq 0 && $DRY_RUN -eq 0 && $SELFTEST -eq 0 ]]; then rm -rf "$WORK"; else echo "work dir kept: $WORK"; fi; }
trap cleanup EXIT

echo "${BOLD}publish_public${NC} — tag ${TAG} (${SHORT}) → ${TARGET}"

# ------------------------------------------------------------------ 1. export the tree
mkdir -p "$EXPORT"
git archive "refs/tags/${TAG}" | tar -x -C "$EXPORT"
n_files_raw="$(find "$EXPORT" -type f | wc -l | tr -d ' ')"

# ------------------------------------------------------------------ 2. deny-list
DENY=()
if [[ -f "$EXPORT/scripts/security/internal-paths.txt" ]]; then
  while IFS= read -r p; do
    p="${p%%#*}"; p="${p#"${p%%[![:space:]]*}"}"; p="${p%"${p##*[![:space:]]}"}"
    [[ -n "$p" ]] && DENY+=("$p")
  done < "$EXPORT/scripts/security/internal-paths.txt"
else
  DENY=(docs/tasks/ docs/agent/ security_report/ 'docs/security/*.json' .claude/ .cursor/ .husky/ tests/backend_server/.env.test.jwt)
fi
DENY+=(frontend/public/docs/)          # generated mirror; frontend/scripts/prebuild.sh rebuilds it
removed=0
for p in "${DENY[@]}"; do
  # shellcheck disable=SC2086  # deliberate glob expansion for entries like docs/security/*.json
  for hit in $EXPORT/${p%/}; do
    [[ -e "$hit" ]] || continue
    removed=$((removed + $(find "$hit" -type f | wc -l | tr -d ' ')))
    rm -rf "$hit"
  done
done
# real env files never travel (templates *.example do)
while IFS= read -r f; do rm -f "$f"; removed=$((removed+1)); done < <(find "$EXPORT" -type f -name '.env' -o -type f -name '.env.*' ! -name '*.example' 2>/dev/null | grep -v '\.example$' || true)
[[ ! -f "$EXPORT/BUNDLE_MANIFEST.txt" ]] || die "BUNDLE_MANIFEST.txt in the export: this is a staged customer tree, not a platform tag"
[[ -z "$(find "$EXPORT" -name .git -maxdepth 3)" ]] || die ".git inside the export"
n_files="$(find "$EXPORT" -type f | wc -l | tr -d ' ')"
echo "export: ${n_files_raw} files at tag, ${removed} removed by the deny-list, ${n_files} to publish"

# ------------------------------------------------------------------ 3. selftest plants
if [[ $SELFTEST -eq 1 ]]; then
  term=""
  if [[ -n "$TERMS_FILE_ABS" ]]; then term="$(grep -vE '^\s*(#|$|/)' "$TERMS_FILE_ABS" | sed 's/^~//' | head -1)"; fi
  [[ -n "$term" ]] || term="$(printf '%s' "${LEAK_TERMS:-}" | tr ',' '\n' | sed 's/^~//' | head -1)"
  [[ -n "$term" ]] || die "selftest: could not read a term"
  mkdir -p "$EXPORT/docs/technical"
  printf '# planted\nSee the %s dashboards.\n' "$term" > "$EXPORT/docs/technical/PLANTED_TERM.md"
  # assembled at run time so this script never contains a credential-shaped literal itself
  k_id="AKIA"; k_id+="IOSFODNN7SELFTEST"; k_sec="wJalrXUtnFEMI/K7MDENG"; k_sec+="/bPxRfiCYzxLPQMKEY1"
  printf 'AWS_SECRET_ACCESS_KEY = "%s"\naws_access_key_id = "%s"\n' "$k_sec" "$k_id" > "$EXPORT/docs/technical/PLANTED_SECRET.py"
  echo "${YELLOW}selftest: planted one tier-1 term and one AWS key pair under docs/technical/${NC}"
fi

# ------------------------------------------------------------------ 4. gates on the export
# leak_gate.sh --all needs a git checkout to enumerate files: a throwaway repo in the export.
# `-f`: the export contains files that are tracked-but-ignored in the internal repo (VERSION.txt,
# screenshots); without it they escape the identifier gate AND the snapshot (61 files, 2026-09-15).
( cd "$EXPORT" && git init -q && git add -A -f && git -c user.name=publish -c user.email=publish@local commit -qm export )
gate_rc=0
( cd "$EXPORT" && LEAK_TERMS_FILE="${TERMS_FILE_ABS:-}" LEAK_TERMS="${LEAK_TERMS:-}" "$REPO_ROOT/scripts/security/leak_gate.sh" --all --require-terms ) || gate_rc=$?
gl_rc=0
gitleaks detect --no-git --no-banner --redact --source "$EXPORT" --config "$EXPORT/.gitleaks.toml" --report-format json --report-path "$GITLEAKS_REPORT" >/dev/null 2>&1 || gl_rc=$?
rm -rf "$EXPORT/.git"
if [[ $SELFTEST -eq 1 ]]; then
  if [[ $gate_rc -ne 0 && $gl_rc -ne 0 ]]; then
    echo "${GREEN}✓ selftest: the identifier gate (rc=$gate_rc) and gitleaks (rc=$gl_rc) both refused the planted export${NC}"; exit 0
  fi
  die "selftest FAILED: identifier gate rc=$gate_rc, gitleaks rc=$gl_rc — a planted leak got through"
fi
[[ $gate_rc -eq 0 ]] || die "identifier/secret gate refused the export (see above)"
if [[ $gl_rc -ne 0 ]]; then
  echo "${RED}gitleaks findings (${GITLEAKS_REPORT}):${NC}"; python3 - "$GITLEAKS_REPORT" <<'PY' || true
import json,sys
for f in json.load(open(sys.argv[1])): print(f"  {f['File']}:{f['StartLine']}  {f['RuleID']}")
PY
  die "gitleaks refused the export"
fi
echo "${GREEN}✓ gates clean on the export${NC}"

# ------------------------------------------------------------------ 5. sanity: version identity
VERSION_CURRENT="$(grep -E '^current:' "$EXPORT/VERSION.txt" | cut -d: -f2- | tr -d ' ')"
SAME_COMMIT_TAGS="$(git tag --points-at "$COMMIT" | grep -E '^(main|prod|release)-' || true)"
if [[ "$VERSION_CURRENT" != "$TAG" ]] && ! grep -qx "$VERSION_CURRENT" <<<"$SAME_COMMIT_TAGS"; then
  die "VERSION.txt current: '${VERSION_CURRENT}' is neither '${TAG}' nor a tag on ${SHORT} (tags there: $(echo $SAME_COMMIT_TAGS))"
fi

# ------------------------------------------------------------------ 6. commit body = release-note build section
BODY="$WORK/body.txt"
build_no="${VERSION_CURRENT##*-}"
awk -v n="$build_no" '
  $0 ~ "^## build "n" " {f=1}
  f && /^## / && $0 !~ "^## build "n" " {exit}
  f {print}
' "$EXPORT/docs/release_note/README.md" > "$BODY" || true
if [[ ! -s "$BODY" ]]; then
  git tag -l --format='%(contents)' "$TAG" > "$BODY"
  [[ -s "$BODY" ]] || printf 'release: %s\n' "$TAG" > "$BODY"
  echo "${YELLOW}no '## build ${build_no}' section in the release note; using the tag message as body${NC}"
fi

# ------------------------------------------------------------------ 7. snapshot commit in the public clone
git clone -q "$TARGET" "$PUBLIC" 2>/dev/null || die "cannot clone ${TARGET}"
cd "$PUBLIC"
if [[ $RESEED -eq 0 ]] && git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null; then die "tag ${TAG} already exists in the public repo"; fi
if git show-ref --verify --quiet refs/remotes/origin/main; then git checkout -q main 2>/dev/null || git checkout -q -b main origin/main; else git checkout -q -b main; fi
if [[ $RESEED -eq 1 ]]; then
  echo "${YELLOW}reseed: replacing the public history with one orphan snapshot commit${NC}"
  git checkout -q --orphan reseed && git rm -rfq --cached . >/dev/null 2>&1 || true
fi
non_snapshot="$(git log --format='%s' 2>/dev/null | grep -vE '^release: ' | head -3 || true)"
[[ -z "$non_snapshot" ]] || echo "${YELLOW}warning: public history has non-snapshot commits:${NC} $non_snapshot"
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a "$EXPORT/." .
git add -A -f     # -f: see the gate step — ignored-but-tracked files are part of the release
{ printf 'release: %s\n\n' "$TAG"; cat "$BODY"; } > "$WORK/commit.txt"
git -c user.name="${PUBLISH_GIT_NAME:-VirtualPyTest release}" -c user.email="${PUBLISH_GIT_EMAIL:-release@virtualpytest.com}" commit -q -F "$WORK/commit.txt"
tagf=(); [[ $RESEED -eq 1 ]] && tagf=(-f)
git -c user.name="${PUBLISH_GIT_NAME:-VirtualPyTest release}" -c user.email="${PUBLISH_GIT_EMAIL:-release@virtualpytest.com}" tag -a "${tagf[@]}" "$TAG" -F "$BODY"
extra_tags=()
while IFS= read -r t; do [[ -n "$t" && "$t" != "$TAG" ]] && extra_tags+=("$t"); done <<<"$SAME_COMMIT_TAGS"
for t in "${extra_tags[@]:-}"; do [[ -n "$t" ]] && git -c user.name="${PUBLISH_GIT_NAME:-VirtualPyTest release}" -c user.email="${PUBLISH_GIT_EMAIL:-release@virtualpytest.com}" tag -a "${tagf[@]}" "$t" -F "$BODY"; done
PUB_SHA="$(git rev-parse --short=10 HEAD)"
echo "public commit ${PUB_SHA}  tags: ${TAG} ${extra_tags[*]:-}"
echo "history in the public clone: $(git rev-list --count HEAD) commit(s)"

# ------------------------------------------------------------------ 8. push
if [[ $DRY_RUN -eq 1 ]]; then
  echo "${YELLOW}dry-run: nothing pushed. Inspect: cd ${PUBLIC} && git log --stat | head; git tag${NC}"
  exit 0
fi
if [[ $RESEED -eq 1 ]]; then
  git push -q --force origin HEAD:main
  git push -q --force origin "refs/tags/$TAG"
  for t in "${extra_tags[@]:-}"; do [[ -n "$t" ]] && git push -q --force origin "refs/tags/$t"; done
else
  git push -q origin main --follow-tags
  for t in "${extra_tags[@]:-}"; do [[ -n "$t" ]] && git push -q origin "refs/tags/$t"; done
fi
echo "${GREEN}✓ published ${TAG} → ${TARGET} (${PUB_SHA}, ${n_files} files)${NC}"
