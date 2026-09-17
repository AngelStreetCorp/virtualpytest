#!/bin/bash
# Delivery note — the one page that describes a customer delivery.
#
#   What changed, which features that customer gets, and what the operator must DO to roll
#   it out (migrations, .env keys, restarts). All of it already existed before this script:
#   the release note in docs/release_note/README.md, the feature list in BUNDLE_MANIFEST.txt
#   (inside the 35 MB archive) and the rollout checklist only as the terminal output of
#   upgrade_notes.py, which nobody saved. Scattered across three places, none of them the
#   overlay repo, so "what did they get on <date>?" had no answer short of untarring the
#   bundle. This assembles the three into one file that is committed to the overlay
#   (deliveries/) and used as the GitHub Release body.
#
# Usage:
#   scripts/release/delivery_note.sh --pin <ref> [--prev-pin <ref>] [--overlay <dir>]
#                                    [--manifest <file>] [--archive <file>]
#
#   --pin <ref>       platform ref being delivered (tag, branch or sha)
#   --prev-pin <ref>  platform ref the customer runs TODAY. Omitted = read it from the
#                     previous release-* tag's customer.conf in --overlay; none found = the
#                     delivery is treated as a first install (no delta, no upgrade block)
#   --overlay <dir>   customer overlay clone (for --prev-pin auto-detect and overlay version)
#   --manifest <file> BUNDLE_MANIFEST.txt to take the feature lists from
#   --archive <file>  the built archive, to name it with its size and sha256
#
# Writes markdown to stdout. Reads git only; never ssh-es, never writes into either repo.
set -euo pipefail

REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"
PIN="" PREV_PIN="" OVERLAY_DIR="" MANIFEST="" ARCHIVE="" PREV_TAG=""
usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pin)       [[ $# -gt 1 ]] || { echo "--pin needs a value" >&2; exit 1; }; PIN="$2"; shift ;;
    --prev-pin)  [[ $# -gt 1 ]] || { echo "--prev-pin needs a value" >&2; exit 1; }; PREV_PIN="$2"; shift ;;
    --overlay)   [[ $# -gt 1 ]] || { echo "--overlay needs a value" >&2; exit 1; }; OVERLAY_DIR="$2"; shift ;;
    --manifest)  [[ $# -gt 1 ]] || { echo "--manifest needs a value" >&2; exit 1; }; MANIFEST="$2"; shift ;;
    --archive)   [[ $# -gt 1 ]] || { echo "--archive needs a value" >&2; exit 1; }; ARCHIVE="$2"; shift ;;
    --help|-h)   usage; exit 0 ;;
    *)           echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
  shift
done
[[ -n "${PIN}" ]] || { echo "--pin is required" >&2; exit 1; }

g() { git -C "${REPO_DIR}" "$@"; }
mfield() { [[ -n "${MANIFEST}" && -f "${MANIFEST}" ]] && sed -n "s/^$1:[[:space:]]*//p" "${MANIFEST}" | head -n 1 || true; }

# Version identity of a ref = its own VERSION.txt, not the tag name: a PIN may be a branch or
# a sha, and the build counter is what the release-note sections are keyed by.
version_at() { g show "$1:VERSION.txt" 2>/dev/null | sed -n 's/^current:[[:space:]]*//p' | head -n 1; }
build_of()   { local v="${1##*-}"; [[ "${v}" =~ ^[0-9]+$ ]] && echo "${v}" || echo ""; }

PIN_VERSION="$(version_at "${PIN}")"
[[ -n "${PIN_VERSION}" ]] || { echo "no VERSION.txt current: line at ${PIN} (is it fetched?)" >&2; exit 1; }
PIN_BUILD="$(build_of "${PIN_VERSION}")"

# --prev-pin auto-detect: the newest release-* tag on the overlay that is not HEAD carries, in
# its customer.conf, the PIN the customer is running right now.
PREV_SOURCE="given on the command line"
# The previous release-* tag is looked up whenever there is an overlay, even when --prev-pin was
# given by hand: it is what the overlay's own diff (its dashboards, scripts and vhosts) is taken
# against, and dropping it silently loses every customer-side change from the note.
if [[ -n "${OVERLAY_DIR}" ]]; then
  head_sha="$(git -C "${OVERLAY_DIR}" rev-parse HEAD 2>/dev/null || true)"
  while IFS= read -r t; do
    [[ -n "${t}" ]] || continue
    [[ "$(git -C "${OVERLAY_DIR}" rev-parse "${t}^{commit}" 2>/dev/null)" == "${head_sha}" ]] && continue
    p="$(git -C "${OVERLAY_DIR}" show "${t}:customer.conf" 2>/dev/null | sed -n 's/^PIN=//p' | head -n 1)"
    p="${p%%#*}"; p="$(echo "${p}" | tr -d '[:space:]')"
    [[ -n "${p}" ]] || continue
    PREV_TAG="${t}"
    if [[ -z "${PREV_PIN}" ]]; then PREV_PIN="${p}"; PREV_SOURCE="from \`${t}\` in the overlay"; fi
    break
  done < <(git -C "${OVERLAY_DIR}" tag -l 'release-*' --sort=-creatordate 2>/dev/null)
fi
# A delivery note is always an UPDATE: the customer is on release N and moves to N+1. There is
# no first-install case here -- installing is a different document with different steps -- so
# without a previous pin there is no delta to describe and nothing worth printing.
# Third fallback: the build tag immediately before the pin. That is exactly the range the
# pinned build section of the release note covers, so the checklist matches the changelog --
# and it means a release always has a previous release, which is what a release note describes.
if [[ -z "${PREV_PIN}" ]]; then
  pin_tag="$(g tag -l 'main-*' --points-at "${PIN}^{commit}" 2>/dev/null | head -1)"
  if [[ -n "${pin_tag}" ]]; then
    PREV_PIN="$(g tag -l 'main-*' --sort=creatordate | awk -v t="${pin_tag}" '$0 == t { print prev; exit } { prev = $0 }')"
    [[ -z "${PREV_PIN}" ]] || PREV_SOURCE="the build tag before it"
  fi
fi
if [[ -z "${PREV_PIN}" ]]; then
  echo "cannot resolve the previous release: pass --prev-pin <ref>." >&2
  exit 1
fi
PREV_BUILD="$(build_of "$(version_at "${PREV_PIN}")")"
[[ -n "${PREV_BUILD}" ]] || PREV_BUILD="$(build_of "${PREV_PIN}")"

VERSION="$(mfield version)"; VERSION="${VERSION:-${PIN_VERSION}}"
OVERLAY_VERSION="$(mfield overlay_version)"
ENABLED="$(mfield enabled_features)"
DISABLED="$(mfield disabled_features)"
[[ -n "${OVERLAY_VERSION}" || -z "${OVERLAY_DIR}" ]] || \
  OVERLAY_VERSION="$(git -C "${OVERLAY_DIR}" show HEAD:VERSION.txt 2>/dev/null | sed -n 's/^current:[[:space:]]*//p' | head -n 1)"

# The note opens on the delivery itself. No title line -- the release title already names both
# versions and the table repeats them -- and no provenance line: who generated it and from what
# is our business, and it was the first thing on the customer's screen.

# No heading over the table: the rows say what they are.
printf '| | |\n|---|---|\n'
STAGED_VERSION="$(mfield platform_version)"; STAGED_VERSION="${STAGED_VERSION:-${PIN_VERSION}}"
printf '| Platform | `%s` (`%s`) |\n' "${STAGED_VERSION}" "$(g rev-parse --short "${PIN}^{commit}" 2>/dev/null || echo '?')"
[[ "${STAGED_VERSION}" == "${PIN_VERSION}" ]] || \
  printf '| ⚠ Built from | a working tree at `%s`, not the pin `%s` (`--no-checkout`) — not reproducible from the tags |\n' "${STAGED_VERSION}" "${PIN_VERSION}"
[[ -n "${OVERLAY_VERSION}" ]] && printf '| Overlay | `%s` |\n' "${OVERLAY_VERSION}"
[[ -n "${ENABLED}" ]]  && printf '| Features enabled | `%s` |\n' "${ENABLED}"
# DISABLED is not shown: a release note says what the customer gets. It still does the work --
# every list below is filtered by it -- but naming the features they do not have is our
# bookkeeping, not part of the delivery.
if [[ -n "${ARCHIVE}" && -f "${ARCHIVE}" ]]; then
  if command -v sha256sum >/dev/null 2>&1; then s="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  else s="$(shasum -a 256 "${ARCHIVE}" | awk '{print $1}')"; fi
  printf '| Archive | `%s` (%s) |\n' "$(basename "${ARCHIVE}")" "$(du -h "${ARCHIVE}" | awk '{print $1}')"
  printf '| sha256 | `%s` |\n' "${s}"
fi
printf '\n'

PLATFORM_MOVED=true
[[ "$(version_at "${PREV_PIN}")" != "${PIN_VERSION}" ]] || PLATFORM_MOVED=false

# ---- readability: one collapsed line per change, expand for the detail ----
# A build section is 400 lines of dense paragraphs. Nobody reads that to find out whether a
# delivery affects them. Each bullet becomes a <details> whose summary is the change title plus
# its bug id and migration marker, so the section scans as a list and opens where it matters.
# <details> renders on the GitHub release page and in the repo file view alike.
format_changes() {
  printf '%s' "${1}" | python3 -c '
import re, sys

# A delivery can span several builds, each with its own Features / Bug fixes / Security
# subsections. Kept per build, the same three headings repeat and the reader has to stitch them
# together to answer "what security work is in this?". Merged into three groups instead, each a
# collapsed section over collapsed items.
GROUPS = [("features", "✨ Features"), ("bugs", "🐛 Bug fixes"), ("security", "🔒 Security")]
buckets = {k: [] for k, _ in GROUPS}
group, cur = "features", None

def flush():
    global cur
    if not cur: return
    title, body = cur[0], cur[1].strip()
    bug = commit = task = None
    kept = []
    for seg in body.split(" · "):
        t = seg.strip()
        m = re.fullmatch(r"\[(BUG-\d+)\]\([^)]*\)", t)
        if m: bug = bug or m.group(1); continue
        if re.fullmatch(r"`[0-9a-f]{7,40}`", t) or t == "`this commit`":
            commit = commit or t.strip("`"); continue
        m = re.fullmatch(r"(TASK-\d+)", t)
        if m: task = task or m.group(1); continue
        kept.append(seg)
    body = " · ".join(kept).strip()
    badges = [b for b in (task, "🗄 migration" if "DB migration" in body else None) if b]
    head = "<b>%s</b>" % title
    if bug: head = "<b>%s</b> — %s" % (bug, title)
    if commit and commit != "this commit": head += " — <code>%s</code>" % commit
    if badges: head += " — <sub>%s</sub>" % " · ".join(badges)
    if body:
        buckets[group].extend(["<details>", "<summary>%s</summary>" % head, "", body, "", "</details>", ""])
    else:
        buckets[group].append("- %s" % head)
    cur = None

for line in sys.stdin.read().splitlines():
    if line.startswith("#"):
        flush()
        h = line.lstrip("# ").strip()
        if "security" in h.lower(): group = "security"
        elif "bug" in h.lower(): group = "bugs"
        elif "feature" in h.lower(): group = "features"
        continue
    m = re.match(r"^\s*-\s+\*\*(.+?)\*\*\s*[—-]?\s*(.*)$", line)
    if m:
        flush(); cur = [m.group(1), m.group(2)]
    elif re.match(r"^\s*-\s+\S", line):
        flush(); cur = [re.sub(r"^\s*-\s+", "", line)[:80], ""]
    elif not line.strip():
        flush()
    elif cur is not None:
        cur[1] += " " + line.strip()
flush()

out = []
for key, label in GROUPS:
    items = [x for x in buckets[key] if x.strip()]
    n = sum(1 for x in buckets[key] if x.startswith("<summary>") or x.startswith("- "))
    if not n: continue
    out += ["<details>", "<summary><h2>%s — %d</h2></summary>" % (label, n), ""]
    out += buckets[key]
    out += ["</details>", ""]
print("\n".join(out))
' 2>/dev/null || printf '%s' "${1}"
}

# Overlay commits the same way: subject collapsed, commit body on expand.
format_commits() {
  python3 -c '
import sys
out = []
for rec in sys.stdin.read().split("\x00"):
    if not rec.strip(): continue
    subject, _, body = rec.partition("\x01")
    subject, body = subject.strip(), body.strip()
    if body:
        out += ["<details>", "<summary>%s</summary>" % subject, "", body, "", "</details>", ""]
    else:
        out.append("- %s" % subject)
print("\n".join(out))
' 2>/dev/null || true
}

# ---- what we deliver ----
if ! ${PLATFORM_MOVED}; then
  printf 'This delivery is **the overlay only** — your scripts, dashboards and identity map. The platform is unchanged.\n\n'
fi
note=""
${PLATFORM_MOVED} && note="$(g show "${PIN}:docs/release_note/README.md" 2>/dev/null || true)"
changed=""
if ${PLATFORM_MOVED} && [[ -n "${note}" ]]; then
  changed="$(printf '%s\n' "${note}" | awk -v floor="${PREV_BUILD:-0}" '
    /^## / { inblk = 0; if ($0 ~ /^## build [0-9]+/ && ($3 + 0) > (floor + 0)) inblk = 1 }
    inblk { print }')"
fi
[[ -z "${changed}" ]] || printf '%s\n' "$(format_changes "${changed}")"

# The platform release note structurally cannot cover this customer's own dashboards, scripts and
# identity map: they live in the overlay, and for an overlay-only delivery they are the delivery.
if [[ -n "${OVERLAY_DIR}" && -n "${PREV_TAG}" ]]; then
  ov_log="$(git -C "${OVERLAY_DIR}" log --no-merges --pretty=format:'%x00%s%x01%b' "${PREV_TAG}..HEAD" 2>/dev/null | format_commits)"
  if [[ -n "${ov_log}" ]]; then
    n_ov="$(git -C "${OVERLAY_DIR}" log --no-merges --oneline "${PREV_TAG}..HEAD" 2>/dev/null | grep -c . || true)"
    printf '<details>\n<summary><h2>🎛 Your dashboards &amp; scripts — %s</h2></summary>\n\n%s\n</details>\n\n' "${n_ov}" "${ov_log}"
  fi
fi

# ---- roll it out ----
# Computed by delivery_rollout.py, which imports upgrade_notes.py rather than filtering its
# rendered text: it drops every section with nothing to do, every item belonging to a feature
# this customer does not run, our own lab vhosts, and the platform dashboards their overlay
# overrides. What survives is the list that breaks a rollout when skipped.
RELNOTE_TMP="$(mktemp "${TMPDIR:-/tmp}/vpt-relnote.XXXXXX")"
trap 'rm -f "${RELNOTE_TMP}"' EXIT
printf '%s' "${changed:-}" > "${RELNOTE_TMP}"
if ! ${PLATFORM_MOVED}; then
  printf '## Roll it out\n\n'
  printf '**At a glance:** no database migration · no new setting · no nginx change · no service restart beyond the deploy.\n\n'
  printf 'The core tree is identical to what is already running. Unpack and `bash ~/update_core.sh`; the frontend rebuilds and the hosts pick up the new scripts. **Grafana dashboards are the exception** — they are hand-deployed:\n\n'
  ov_dash="$(git -C "${OVERLAY_DIR:-.}" diff --name-only "${PREV_TAG:-HEAD}..HEAD" -- '*grafana*' 2>/dev/null | grep '\.json$' || true)"
  if [[ -n "${ov_dash}" ]]; then
    printf '%s\n' "${ov_dash}" | sed 's/^/- `/; s/$/`/'
    printf '\n```bash\npython3 infra/monitoring/grafana/dashboards/_push_dashboard.py <file>\n```\n\n'
  fi
elif [[ -f "${REPO_DIR}/scripts/release/delivery_rollout.py" ]]; then
  ( cd "${REPO_DIR}" && python3 scripts/release/delivery_rollout.py \
      --from "${PREV_PIN}" --to "${PIN}" --disabled "${DISABLED}" \
      ${OVERLAY_DIR:+--overlay "${OVERLAY_DIR}"} ${PREV_TAG:+--prev-tag "${PREV_TAG}"} \
      --relnote "${RELNOTE_TMP}" ) \
    || printf '## Roll it out\n\n_delivery_rollout.py failed; run it by hand._\n\n'
else
  printf '## Roll it out\n\n_`scripts/release/delivery_rollout.py` not found in %s._\n\n' "${REPO_DIR}"
fi
