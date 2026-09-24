#!/usr/bin/env bash
#
# platform_release_note.sh — the GitHub release body for a PLATFORM build.
#
#   platform_release_note.sh <tag> [--prev <tag>] [--commit <sha>] [--out <file>]
#
# The customer overlays have had a readable release page since 2026-09-08 (delivery_note.sh).
# The platform repo had nothing: a tag rendered as GitHub's bare "Source code (zip)" and the
# changelog stayed buried in docs/release_note/README.md, so the one repo the release note
# lives in was the one repo you could not read it from.
#
# THE OVERLAY NOTE IS THE MODEL, not a starting point to improvise on. The first version of
# this script invented its own shape — a Build/Commit/Date table and one "Upgrade" blob pasted
# out of the release note — so the two pages describing the same release disagreed on how to
# describe it. It now assembles from the same parts, in the same order:
#
#   a header table          the delivery note's, minus what only a customer has
#   the collapsed groups    format_changes.py, shared verbatim
#   ## Roll it out          delivery_rollout.py, shared verbatim — the numbered
#                           Database / Nginx / Services / Settings / Grafana steps
#
# The platform runs every optional feature, so --disabled is empty and nothing is filtered:
# this page is the superset each customer's delivery note is a subset of.
#
# Nothing here may name a customer — the platform repo is public-facing and RELEASING.md is
# explicit that a platform tag or page never carries a name or a codename. Everything it
# prints comes from the release note and the git tags, which the leak gate already covers.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

TAG=""; OUT=""; PREV=""; COMMIT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)  OUT="${2:-}";  shift 2 ;;
    --prev) PREV="${2:-}"; shift 2 ;;
    # The snapshot repo's commit differs from ours -- it gets one squashed commit per release,
    # not our history -- so a page published there must name ITS commit. Printing ours sends a
    # reader looking for a sha that does not exist in the repo they are reading.
    --commit) COMMIT="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) [[ -z "$TAG" ]] && { TAG="$1"; shift; } || { echo "unexpected argument '$1'" >&2; exit 2; } ;;
  esac
done
[[ -n "$TAG" ]] || { echo "usage: platform_release_note.sh <tag> [--prev <tag>] [--commit <sha>] [--out <file>]" >&2; exit 2; }

NOTE="docs/release_note/README.md"
BUILD="${TAG##*-}"
[[ "$BUILD" =~ ^[0-9]+$ ]] || { echo "cannot read a build number out of '${TAG}'" >&2; exit 2; }

# The build this one follows: the newest main-* tag below it, unless told otherwise.
if [[ -z "$PREV" ]]; then
  PREV="$(git tag --list 'main-*' | awk -F- -v b="$BUILD" '($NF+0) < (b+0) { print ($NF+0), $0 }' \
          | sort -rn | head -1 | cut -d' ' -f2-)"
fi

# This build's section, heading and Upgrade block excluded — the rollout is recomputed below
# rather than pasted, so it is filtered exactly the way a customer's is.
section="$(awk -v b="## build ${BUILD}" '
  index($0, b) == 1 { f = 1; next }
  f && /^## build /          { exit }
  f && /^### (🚚 )?Upgrade/  { f = 2; next }
  f == 1                     { print }
' "$NOTE")"

# `${section// /}` would be the obvious emptiness test, but bash 3.2 (macOS) does pattern
# substitution on a ~50 KB string in minutes, not milliseconds — it hung the whole script.
has_content() { [[ -n "$(printf '%s' "$1" | tr -d '[:space:]')" ]]; }
has_content "$section" || { echo "no '## build ${BUILD}' section in ${NOTE}" >&2; exit 2; }

sha="${COMMIT:-$(git rev-list -n1 "$TAG" 2>/dev/null)}"; sha="${sha:0:8}"
date="$(awk -v b="## build ${BUILD}" 'index($0,b)==1 { print $NF; exit }' "$NOTE")"
# Every feature ships on the platform; a customer's page lists the subset they run.
# `paste -sd', '` cycles the two characters as alternating delimiters -- "a,b c,d" -- so the
# separator is joined explicitly.
feats="$(ls -d features/*/ 2>/dev/null | xargs -n1 basename 2>/dev/null \
         | grep -vx 'node_modules' | sort | tr '\n' '|' | sed -e 's/|$//' -e 's/|/, /g' || true)"

relnote_tmp="$(mktemp "${TMPDIR:-/tmp}/vpt-relnote.XXXXXX")"
body="$(mktemp)"
trap 'rm -f "$relnote_tmp" "$body"' EXIT
printf '%s' "$section" > "$relnote_tmp"

{
  printf '| | |\n|---|---|\n'
  printf '| Platform | `%s` (`%s`) |\n' "$TAG" "$sha"
  [[ -n "$PREV" ]]  && printf '| Previous | `%s` |\n' "$PREV"
  [[ -n "$date" ]]  && printf '| Date | %s |\n' "$date"
  [[ -n "$feats" ]] && printf '| Features | `%s` |\n' "$feats"
  printf '\n'

  printf '%s\n' "$section" | python3 scripts/release/format_changes.py

  if [[ -n "$PREV" ]]; then
    python3 scripts/release/delivery_rollout.py --from "$PREV" --to "$TAG" --disabled '' \
        --relnote "$relnote_tmp" \
      || printf '## Roll it out\n\n_delivery_rollout.py failed; run it by hand._\n\n'
  fi
} > "$body"

if [[ -n "$OUT" ]]; then cp "$body" "$OUT"; echo "${OUT}"; else cat "$body"; fi
