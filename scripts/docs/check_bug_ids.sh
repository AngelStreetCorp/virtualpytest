#!/bin/bash
# Every BUG-nnnn is one bug. Fails on a number used by two files, or a release-note link that
# points at a file that is not there.
#
# Two files sharing a number is not cosmetic: the release note links one of them, the tracker
# lists the other, and a reader following either believes they have the whole story. It happened
# four times before anyone noticed (0059, 0066, 0103, 0109) because nothing looked.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
fail=0

# Two collisions predate this check and have SHIPPED -- they are in build 8713, in the bundle a
# customer holds and in the delivery note that links them. Renumbering now would make their copy
# disagree with ours to fix a cosmetic problem, so they are grandfathered by name. Nothing else
# may join them.
SHIPPED_DUPES='BUG-0059 BUG-0066'
dupes="$(ls docs/bugs | grep -oE '^BUG-[0-9]{4}' | sort | uniq -d || true)"
for known in ${SHIPPED_DUPES}; do dupes="$(printf '%s\n' "${dupes}" | grep -v "^${known}$" || true)"; done
if [[ -n "${dupes}" ]]; then
  echo "ERROR: bug number used by more than one file:" >&2
  while IFS= read -r n; do
    [[ -n "${n}" ]] || continue
    printf '  %s\n' "${n}" >&2
    ls docs/bugs | grep "^${n}" | sed 's/^/    /' >&2
  done <<< "${dupes}"
  echo "  Renumber the one that has NOT shipped to the next free number." >&2
  fail=1
fi

# A link the release note makes to a bug file that does not exist. The placeholder in the
# instructions block is not a link to anything.
while IFS= read -r f; do
  [[ "${f}" == *"<"* ]] && continue
  [[ -f "docs/bugs/${f}" ]] || { echo "ERROR: release note links docs/bugs/${f}, which does not exist" >&2; fail=1; }
done < <(grep -oE '\(\.\./bugs/BUG-[^)]+\)' docs/release_note/README.md | tr -d '()' | sed 's|\.\./bugs/||' | sort -u)

# The same bug cited twice in ONE build section means two different fixes wear one number. Only
# Unreleased is checked: a shipped section is a record of what was said at the time, and editing
# it to satisfy a linter falsifies it.
awk '/^## / { section = $0; inblk = ($0 ~ /^## Unreleased/) } !inblk { next } /^## (Unreleased|build )/ { section = $0 } /\[BUG-[0-9]{4}\]/ {
       while (match($0, /\[BUG-[0-9]{4}\]/)) {
         id = substr($0, RSTART + 1, RLENGTH - 2); print section "\t" id
         $0 = substr($0, RSTART + RLENGTH)
       } }' docs/release_note/README.md | sort | uniq -d | while IFS= read -r line; do
  echo "ERROR: ${line#*$'\t'} is cited twice in '${line%%$'\t'*}'" >&2
  fail=1
done

[[ ${fail} -eq 0 ]] && echo "bug ids: unique, linked, and cited once per build" || exit 1

# The other half: that each file's own Status/Fixed in agrees with what the note says shipped.
exec python3 "$(dirname "${BASH_SOURCE[0]}")/check_bug_meta.py"
