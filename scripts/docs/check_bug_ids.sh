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

# A bug file whose own number disagrees with its file name: "BUG-0965-....md" whose title and ID
# field say BUG-0964. The tracker, the index and the release note then all read the wrong bug, and
# the check above (which counts file names) cannot see it. A file that was renumbered to dodge a
# collision keeps its old number in the title — which is exactly how one file ended up with three
# different numbers: its name said 0965, its title and the note's link text said 0964.
for f in docs/bugs/BUG-*.md; do
  [[ -e "$f" ]] || continue
  base="$(basename "$f")"
  want="$(printf '%s' "$base" | sed -n 's/^\(BUG-[0-9][0-9][0-9][0-9]\).*/\1/p')"
  [[ -n "$want" ]] || continue
  got="$(sed -n 's/^# \(BUG-[0-9][0-9][0-9][0-9]\)\b.*/\1/p' "$f" | head -n 1)"
  if [[ -n "$got" && "$got" != "$want" ]]; then
    echo "ERROR: ${base} is filed as ${want} but its title says ${got}" >&2
    fail=1
  fi
done

# A link whose label and its target disagree: "[BUG-0964](.../BUG-0965-....md)" sends the reader to
# another bug while the note claims this one. The target exists, so the check above cannot see it.
while IFS= read -r pair; do
  if [[ -z "${pair}" ]]; then continue; fi
  echo "ERROR: release note cites ${pair%% *} but links ${pair##* }" >&2
  fail=1
done < <(grep -oE '\[BUG-[0-9][0-9][0-9][0-9][^]]*\]\(\.\./bugs/BUG-[0-9][0-9][0-9][0-9][^)]*\)' docs/release_note/README.md \
         | sed -E 's/\[(BUG-[0-9][0-9][0-9][0-9])[^]]*\]\(\.\.\/bugs\/(BUG-[0-9][0-9][0-9][0-9]).*/\1 \2/' \
         | awk '$1 != $2')

# The same bug cited twice in ONE build section means two different fixes wear one number. Only
# Unreleased is checked: a shipped section is a record of what was said at the time, and editing
# it to satisfy a linter falsifies it.
#
# Two things had to change for this check to run at all, and until now it had never run: the
# pattern spelled the four digits as {4}, and mawk (the awk on Ubuntu and on the Mac) has no
# interval expressions, so it was matched literally and nothing was ever found; and the
# duplicates were piped straight into `while ... done`, so `fail=1` ran in a pipeline subshell and
# never reached this shell. The list is collected first and the loop reads it here.
dupes="$(awk '/^## / { section = $0; inblk = ($0 ~ /^## Unreleased/) } !inblk { next } /^## (Unreleased|build )/ { section = $0 } /\[BUG-[0-9][0-9][0-9][0-9]\]/ {
       while (match($0, /\[BUG-[0-9][0-9][0-9][0-9]\]/)) {
         id = substr($0, RSTART + 1, RLENGTH - 2); print section "\t" id
         $0 = substr($0, RSTART + RLENGTH)
       } }' docs/release_note/README.md | sort | uniq -d)"
while IFS= read -r line; do
  if [[ -z "${line}" ]]; then continue; fi
  echo "ERROR: ${line#*$'\t'} is cited twice in '${line%%$'\t'*}'" >&2
  fail=1
done <<< "${dupes}"

[[ ${fail} -eq 0 ]] && echo "bug ids: unique, linked, and cited once per build" || exit 1

# The other half: that each file's own Status/Fixed in agrees with what the note says shipped.
exec python3 "$(dirname "${BASH_SOURCE[0]}")/check_bug_meta.py"
