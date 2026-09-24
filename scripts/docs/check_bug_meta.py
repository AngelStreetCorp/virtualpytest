#!/usr/bin/env python3
"""The bug files and the release note must tell the same story.

`check_bug_ids.sh` already proves every BUG-nnnn is one bug, linked and cited once. This proves
the other half: that what a file claims about *shipping* matches what the note says shipped.

Four ways that drifted, each of which had gone unnoticed for at least two releases:

  1. `Fixed in` filled from VERSION.txt. That counter bumps on every commit and every branch
     carries its own series, so it never names a release. BUG-0122 came back with `build 9062`,
     a worktree's counter; BUG-0121 with `build 9047`, a number main passed through mid-sprint.
     Neither build was ever cut, so both fixes rendered under a heading no reader could place.
  2. `Fixed in` as free text. The index generator matches `build (\\d+)` and drops anything else
     into Unreleased without a word: `—`, `Unreleased`, `this commit (reverts ...)`,
     `mobile app 1.0.11 (versionCode 12)` and eight empty fields all landed there. Four of those
     bugs were inside the 8887 tag and three were cited in its own release-note section, so the
     two pages contradicted each other for two releases.
  3. A fix that ships with no bullet. The tracker says Fixed, the note never mentions it, and
     the customer reading the changelog never learns it was fixed.
  4. A shipped section edited after its tag. `f092aae7ee` added BUG-0092 — a CORS fix that
     reflected any origin with credentials — to `## build 8887` *after* that tag existed. The
     changelog told everyone on the 8887 bundle they had the fix. They did not.

Run: scripts/docs/check_bug_meta.py   (called by check_bug_ids.sh, which CI runs)
"""
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BUGS = os.path.join(REPO, 'docs', 'bugs')
NOTE = os.path.join(REPO, 'docs', 'release_note', 'README.md')

# `Fixed in` values that mean "not shipped yet" rather than a build.
UNSHIPPED = {'', '—', '-', 'tbd', 'unreleased', 'n/a', 'none'}
# ... and the one way to say "shipped, but deliberately not in the note" (internal-only fixes,
# which the note's own "when to update this file" rules exclude). Anything else must be a build.
INTERNAL = 'internal'
STATUSES = ('open', 'in progress', 'fixed', 'closed', 'wontfix', 'duplicate')

# Sections that already drifted before this check existed. Each was edited deliberately and the
# edit is not one we want to revert, so they are grandfathered by name and the rule starts at the
# next build. Nothing may join them: a section that needs changing after its tag is a bullet in
# the CURRENT build saying what was got wrong, not a quiet rewrite of the shipped one.
#
#   8414 — reformatted wholesale into the note's present conventions (`### Added` -> `### ✨
#          Features`, entries condensed) long after the tag.
#   8713 — the anonymization pass rewrote an internal lab name across the whole repo; reverting
#          would put it back into a published page (docs/agent/release/ANONYMIZATION.md).
#   8887 — `f092aae7ee` added a BUG-0092 bullet after the tag and reworded another. The bullet
#          has since been moved to the build that actually carries the fix; the reword stays.
FROZEN_EXEMPT = {'8414', '8713', '8887'}


def meta(text: str, field: str) -> str:
    m = re.search(rf'^\|\s*{field}\s*\|(.+?)\|\s*$', text, re.M)
    return m.group(1).strip() if m else ''


def sections_of(text: str) -> dict:
    """{build or None: raw section text} — None is Unreleased, other headings ignored."""
    out, cur, buf = {}, 'skip', []
    for line in text.splitlines(keepends=True):
        h = re.match(r'^##\s+(.+?)\s*$', line)
        if h:
            if cur != 'skip':
                out[cur] = ''.join(buf)
            title = h.group(1).strip()
            m = re.match(r'build\s+(\d+)', title)
            cur = m.group(1) if m else (None if title.lower().startswith('unreleased') else 'skip')
            buf = []
            continue
        if cur != 'skip':
            buf.append(line)
    if cur != 'skip':
        out[cur] = ''.join(buf)
    return out


# Section headings carried a decorative emoji until 2026-09-17 (`### ✨ Features`). Dropping it
# was a presentation change across every build at once, and comparing raw text would have called
# each shipped section falsified. This check exists to catch a changed CLAIM, not a changed
# glyph, so headings are normalized on both sides. Anything inside a bullet is untouched, so a
# reworded entry still fails.
HEADING = re.compile(r'^(#{2,3})\s*[^\w\s#]*\s*', re.M)


def comparable(text: str) -> str:
    return HEADING.sub(r'\1 ', text or '').strip()


def cited(sections: dict) -> dict:
    """{BUG-nnnn: earliest build citing it, or None for Unreleased}."""
    out = {}
    for build, body in sections.items():
        for bug_id in re.findall(r'\[(BUG-\d+)\]\(\.\./bugs/', body):
            if bug_id not in out:
                out[bug_id] = build
            elif build is not None and out[bug_id] is not None and int(build) < int(out[bug_id]):
                out[bug_id] = build
            elif out[bug_id] is None:
                out[bug_id] = build          # a real build beats Unreleased
    return out


def git(*args):
    try:
        return subprocess.run(['git', '-C', REPO, *args], capture_output=True, text=True,
                              check=True).stdout
    except subprocess.CalledProcessError:
        return None


def main() -> int:
    errors, warnings = [], []
    sections = sections_of(open(NOTE, encoding='utf-8').read())
    builds = {b for b in sections if b is not None}
    where = cited(sections)

    for fn in sorted(os.listdir(BUGS)):
        if not (fn.startswith('BUG-') and fn.endswith('.md')) or fn.startswith('BUG-XXXX'):
            continue
        text = open(os.path.join(BUGS, fn), encoding='utf-8').read()
        h1 = re.search(r'^#\s*(BUG-\d+)\b', text, re.M)
        if not h1:
            continue
        bug_id = h1.group(1)
        fixed_raw = meta(text, 'Fixed in')
        fixed = fixed_raw.strip().strip('*').strip()
        status = meta(text, 'Status').strip().strip('*').strip().lower()

        # --- 3. Status must start with a word from the documented vocabulary -----------------
        if status and not status.startswith(STATUSES):
            errors.append(f'{fn}: Status "{status}" does not start with one of '
                          f'{" / ".join(s.title() for s in STATUSES[:4])}')

        # --- 1. `Fixed in` must name a build that was actually cut --------------------------
        m = re.match(r'build\s*(\d+)\s*$', fixed, re.I)
        if m:
            if m.group(1) not in builds:
                errors.append(
                    f'{fn}: Fixed in says "build {m.group(1)}", but no "## build {m.group(1)}" '
                    f'section exists in the release note. VERSION.txt is a per-commit, '
                    f'per-branch counter — it is not a release. Leave this "Unreleased"; '
                    f'the cut fills it in.')
            elif where.get(bug_id) not in (None, m.group(1)):
                errors.append(f'{fn}: Fixed in says "build {m.group(1)}" but the release note '
                              f'cites it under build {where[bug_id]}')
        elif fixed.lower() not in UNSHIPPED and INTERNAL not in fixed.lower():
            errors.append(f'{fn}: Fixed in is "{fixed_raw.strip()}" — must be "build NNNN", '
                          f'"Unreleased", or "— (internal)" for a fix with no note entry')

        # --- 2 & 3. a shipped fix the note never mentions ------------------------------------
        shipped = status.startswith(('fixed', 'closed'))
        if shipped and bug_id not in where and INTERNAL not in fixed.lower():
            errors.append(f'{fn}: Status is "{meta(text, "Status").strip()}" but no release-note '
                          f'section cites it. Add a bullet under Unreleased, or set Fixed in to '
                          f'"— (internal)" if it is not user-facing.')

    # --- 4. a shipped section must still say what its tag says ------------------------------
    tags = (git('tag', '--list', 'main-*') or '').split()
    for build in sorted(builds, key=int, reverse=True):
        if build in FROZEN_EXEMPT:
            continue
        tag = next((t for t in tags if t.endswith(f'-{build}')), None)
        if tag is None:
            continue                      # not cut here, or a shallow clone with no tags
        old = git('show', f'{tag}:docs/release_note/README.md')
        if old is None:
            continue
        was = sections_of(old).get(build)
        if was is None:
            errors.append(f'release note: "## build {build}" did not exist at tag {tag}, but the '
                          f'section is there now — it was written after the build shipped')
        elif comparable(was) != comparable(sections[build]):
            errors.append(f'release note: "## build {build}" differs from what tag {tag} carries. '
                          f'A shipped section is the record of what was said at the time; put the '
                          f'change in the current build instead.')

    for w in warnings:
        print(f'WARN: {w}', file=sys.stderr)
    for e in errors:
        print(f'ERROR: {e}', file=sys.stderr)
    if errors:
        print(f'\n{len(errors)} problem(s) — docs/agent/release/RELEASING.md, "Cut a release"',
              file=sys.stderr)
        return 1
    print('bug meta: builds real, files and release note agree, shipped sections unchanged')
    return 0


if __name__ == '__main__':
    sys.exit(main())
