#!/bin/bash
# One command per customer delivery: bundle, note, overlay commit, tags, GitHub release.
#
# WHY. The note's shape is guaranteed by delivery_note.sh, but nothing guaranteed the note was
# regenerated after the PIN moved, committed to the overlay, or used as the release body -- those
# were four commands in a fixed order, and a delivery that skipped one looked fine until someone
# went looking for it months later. That is exactly how the 2026.09.08 delivery ended up with a
# one-line release body and no record in the overlay. This runs the order for you.
#
# Usage:
#   publish_delivery.sh <overlay_dir> [--prev-pin <ref>] [--summary "<one line>"] [--yes]
#
#   <overlay_dir>   customer overlay clone (customer.conf carries the PIN being shipped)
#   --prev-pin      release the customer runs today; default: resolved by delivery_note.sh
#   --summary       the release title's trailing phrase, e.g. "feat: quicktest"
#   --yes           actually push and publish. WITHOUT IT NOTHING LEAVES THIS MACHINE: the
#                   bundle and the note are built, everything else is printed as a plan.
#
# What it does, in order:
#   1. build_customer_bundle.sh          -> archive + .sha256 + DELIVERY-<base>.md
#   2. copy the note to <overlay>/deliveries/DELIVERY-<pair-tag>.md, commit it
#   3. tag BOTH repos with the pair tag release-<build date>  (customer-neutral, no codename)
#   4. gh release create on the OVERLAY repo: title = archive basename + summary,
#      body = the note, assets = archive + .sha256
set -euo pipefail

REPO_DIR="${REPO_DIR:-${HOME}/virtualpytest}"
OUT_DIR="${OUT_DIR:-${HOME}/bundles}"
OVERLAY_DIR="" PREV_PIN="" SUMMARY="" YES=false
usage() { sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prev-pin) PREV_PIN="$2"; shift ;;
    --summary)  SUMMARY="$2"; shift ;;
    --yes)      YES=true ;;
    --help|-h)  usage; exit 0 ;;
    --*)        echo "Unknown option: $1" >&2; exit 1 ;;
    *)          OVERLAY_DIR="$(cd "$1" && pwd)" ;;
  esac
  shift
done
[[ -n "${OVERLAY_DIR}" ]] || { echo "overlay dir is required" >&2; usage; exit 1; }
[[ -f "${OVERLAY_DIR}/customer.conf" ]] || { echo "no customer.conf in ${OVERLAY_DIR}" >&2; exit 1; }

# The overlay must be clean and pushed: the note records a commit sha, and a sha that exists only
# on this laptop makes the delivery unreproducible.
[[ -z "$(git -C "${OVERLAY_DIR}" status --porcelain)" ]] \
  || { echo "overlay has uncommitted changes -- commit them first, the note records its sha" >&2; exit 1; }
# The platform clone gets checked out at the PIN during staging, which a dirty tree blocks --
# and a bundle built from uncommitted work is not reproducible from the tags it claims.
[[ -z "$(git -C "${REPO_DIR}" status --porcelain --untracked-files=no)" ]] \
  || { echo "${REPO_DIR} has uncommitted changes -- staging checks out the PIN and would fail" >&2; exit 1; }

echo "=== 1. bundle ==="
BUILD_LOG="$(mktemp)"; trap 'rm -f "${BUILD_LOG}"' EXIT
bash "${REPO_DIR}/setup/proxmox/node/build_customer_bundle.sh" "${OVERLAY_DIR}" \
     --out "${OUT_DIR}" ${PREV_PIN:+--prev-pin "${PREV_PIN}"} | tee "${BUILD_LOG}"
ARCHIVE="$(sed -n 's/^archive: //p' "${BUILD_LOG}" | tail -1)"
NOTE="$(sed -n 's/^delivery: //p' "${BUILD_LOG}" | tail -1)"
[[ -f "${ARCHIVE}" ]] || { echo "no archive produced" >&2; exit 1; }
[[ -f "${NOTE}" ]] || { echo "no delivery note produced -- refusing to publish a delivery with no record" >&2; exit 1; }

BASE="$(basename "${ARCHIVE}")"; BASE="${BASE%.tar.gz}"; BASE="${BASE%.zip}"
# The pair tag is dated by the BUILD, like the two version tags (RELEASING.md, "Pair tag").
DATE_TAG="release-$(date -u +%Y.%m.%d)"
TITLE="${BASE}${SUMMARY:+ — ${SUMMARY}}"
DEST="${OVERLAY_DIR}/deliveries/DELIVERY-${DATE_TAG}.md"
PIN="$(sed -n 's/^PIN=//p' "${OVERLAY_DIR}/customer.conf" | head -1)"; PIN="${PIN%%#*}"; PIN="$(echo "${PIN}" | tr -d '[:space:]')"

# Self-check: a note missing a section means the generator failed quietly, and an empty roll-out
# means we are about to tell a customer there is nothing to do.
for want in '## Roll it out' 'Features' '| Platform |'; do
  grep -q "${want}" "${NOTE}" || { echo "delivery note has no '${want}' -- not publishing" >&2; exit 1; }
done

echo
echo "=== 2. plan ==="
cat <<PLAN
archive   ${ARCHIVE}
note      ${NOTE}
  -> ${DEST}
pair tag  ${DATE_TAG}   on both repos (platform at ${PIN}, overlay at HEAD)
release   ${TITLE}
  repo    $(git -C "${OVERLAY_DIR}" remote get-url origin)
  assets  $(basename "${ARCHIVE}"), $(basename "${ARCHIVE}").sha256
PLAN

if ! ${YES}; then
  echo
  echo "Dry run: nothing pushed or published. Re-run with --yes to do the above."
  exit 0
fi

echo; echo "=== 3. overlay record ==="
mkdir -p "$(dirname "${DEST}")"
cp "${NOTE}" "${DEST}"
git -C "${OVERLAY_DIR}" add "deliveries/DELIVERY-${DATE_TAG}.md"
git -C "${OVERLAY_DIR}" commit -m "docs(deliveries): ${DATE_TAG}" -m "${TITLE}"
git -C "${OVERLAY_DIR}" tag -a "${DATE_TAG}" -m "${TITLE}"
git -C "${OVERLAY_DIR}" push origin HEAD --follow-tags

git -C "${REPO_DIR}" tag -a "${DATE_TAG}" "${PIN}^{commit}" -m "Release ${DATE_TAG} — platform ${PIN}"
git -C "${REPO_DIR}" push origin "${DATE_TAG}"

echo; echo "=== 4. github release ==="
gh release create "${DATE_TAG}" --repo "$(git -C "${OVERLAY_DIR}" remote get-url origin | sed 's#.*github.com[:/]##; s/\.git$//')" \
  --title "${TITLE}" --notes-file "${DEST}" "${ARCHIVE}" "${ARCHIVE}.sha256"
