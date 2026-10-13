#!/usr/bin/env python3
"""Write the Project tab's numbers to frontend/public/analytics/project.json.

"Lines of code on this build" and "bugs fixed per release" are properties of the
REPOSITORY, not of the database, so they are computed once when the frontend is
built rather than queried at runtime. That also makes the Project tab the one tab
that costs nothing to open — it reads a static file.

Nothing here invents a number. Every value is parsed from the file that already
owns it, using the parser that already owns it:

  lines of code      scripts/count_lines.py           count_repo()
  bugs               docs/bugs/BUG-*.md               the same pipe-table `meta()`
                                                       shape check_bug_meta.py uses
  features per build docs/release_note/README.md      its own documented heading format
  build number       VERSION.txt

Run: python3 scripts/docs/build_project_metrics.py [--out PATH] [--print]
Called by frontend/scripts/prebuild.sh as a non-blocking step.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))

from count_lines import count_repo  # noqa: E402

BUGS_DIR = REPO / 'docs' / 'bugs'
RELEASE_NOTE = REPO / 'docs' / 'release_note' / 'README.md'
VERSION_FILE = REPO / 'VERSION.txt'
DEFAULT_OUT = REPO / 'frontend' / 'public' / 'analytics' / 'project.json'

# `Fixed in` values meaning "not shipped yet" rather than a build. Same set as
# scripts/docs/check_bug_meta.py — the two must agree or the page and CI would
# disagree about what shipped.
UNSHIPPED = {'', '—', '-', 'tbd', 'unreleased', 'n/a', 'none'}
# "shipped, but deliberately not in the release note" (internal-only fixes). These
# are NOT counted as shipped-to-customer fixes.
INTERNAL = 'internal'


def _meta(text: str, field: str) -> str:
    """Read one row out of a bug file's pipe table. Same shape as check_bug_meta.py."""
    m = re.search(rf'^\|\s*{field}\s*\|(.+?)\|\s*$', text, re.M)
    return m.group(1).strip() if m else ''


def _normalise_status(raw: str) -> str:
    """Collapse free-text Status into the four states worth charting.

    The field drifted badly — 'Fixed', '**Fixed', 'FIXED 2026-09-15, verified end to
    end...', 'Fixed — superseded, see "Aftermath"' are all the same state. Match on the
    leading word rather than pretending the field is an enum.
    """
    s = re.sub(r'[*_`]', '', raw).strip().lower()
    if s.startswith('closed'):
        return 'closed'
    if s.startswith('fixed'):
        return 'fixed'
    if s.startswith('open'):
        return 'open'
    if s.startswith('in progress'):
        return 'in progress'
    return 'other'


def _normalise_severity(raw: str) -> str:
    s = re.sub(r'[*_`]', '', raw).strip().lower()
    for level in ('critical', 'high', 'medium', 'low'):
        if s.startswith(level):
            return level.capitalize()
    return 'Unspecified'


def collect_bugs():
    """Every BUG-*.md, tallied by severity, status and the build that shipped it."""
    by_severity, by_status, by_build = Counter(), Counter(), Counter()
    total = 0
    unshipped = 0
    internal = 0
    fixed_unreleased = 0   # fixed on the running build, waiting for the next cut
    open_bugs = []

    for path in sorted(BUGS_DIR.glob('BUG-*.md')):
        text = path.read_text(encoding='utf-8', errors='replace')
        total += 1
        severity = _normalise_severity(_meta(text, 'Severity'))
        status = _normalise_status(_meta(text, 'Status'))
        by_severity[severity] += 1
        by_status[status] += 1
        if status in ('open', 'in progress'):
            h1 = re.search(r'^#\s+(.+)$', text, re.M)
            open_bugs.append({
                'id': path.stem[:8],
                # 'BUG-0190 — A web testcase…' -> 'A web testcase…'
                'title': re.sub(r'^BUG-\d+\s*[—-]\s*', '', h1.group(1).strip()) if h1 else path.stem,
                'status': status,
                'severity': severity,
                'doc': f'/docs/bugs/{path.stem}',
            })

        fixed_in = re.sub(r'[*_`]', '', _meta(text, 'Fixed in')).strip()
        low = fixed_in.lower()
        if low in UNSHIPPED:
            unshipped += 1
            if low == 'unreleased' and status == 'fixed':
                fixed_unreleased += 1
            continue
        if low.startswith(INTERNAL):
            internal += 1          # shipped, but deliberately not in the release note
            continue
        m = re.search(r'build\s+(\d+)', fixed_in)
        if m:
            by_build[m.group(1)] += 1
        else:
            unshipped += 1

    return {
        'total': total,
        'by_severity': dict(by_severity),
        'by_status': dict(by_status),
        'fixed_per_build': dict(by_build),
        'unshipped': unshipped,
        'fixed_unreleased': fixed_unreleased,
        'internal_only': internal,
        'open': open_bugs,
    }


def collect_releases(version):
    """Features and bug-fix bullets per cut build, from the release note.

    The note's own preamble documents this format: an H2 per build, then
    '### ✨ Features' / '### 🐛 Bug fixes' lists. The heading carries only the build
    number and date, so the full name (main-2026.09.26-9369, what the footer shows)
    is rebuilt on the main series — not VERSION.txt's branch, which on a feature
    branch deploy would rename every past release. '## Unreleased' is what the running
    build ships on top of the last cut, so it is reported as that build, flagged
    unreleased — dropping it meant the build in the footer never had a bar.
    """
    if not RELEASE_NOTE.exists():
        return []

    text = RELEASE_NOTE.read_text(encoding='utf-8', errors='replace')
    heads = [(m.group(1), m.group(2), m.start())
             for m in re.finditer(r'^## (?:build (\d+) — (\d{4}-\d{2}-\d{2})|Unreleased)\s*$', text, re.M)]

    releases = []
    for i, (build, date, start) in enumerate(heads):
        end = heads[i + 1][2] if i + 1 < len(heads) else len(text)
        body = text[start:end]

        def bullets(heading):
            # The note's preamble documents emoji headings ("### ✨ Features") but every
            # actual section is written plain ("### Features"). Matching only one form
            # returns 0 for every build without complaining — which is exactly how this
            # behaved the first time it ran. Accept either.
            pattern = rf'^###\s+[^\w\n]*\s*{heading}\s*$(.*?)(?=^### |\Z)'
            m = re.search(pattern, body, re.M | re.S)
            return len(re.findall(r'^- ', m.group(1), re.M)) if m else 0

        if build:
            name, unreleased = f"main-{date.replace('-', '.')}-{build}", False
        elif version['build']:
            build, date, name, unreleased = version['build'], version['date'], version['name'], True
        else:
            continue

        releases.append({
            'build': build,
            'date': date,
            'name': name,
            'unreleased': unreleased,
            'features': bullets('Features'),
            'fixes': bullets('Bug fixes'),
            'security': bullets('Security'),
        })

    # The running build last: a branch's counter can be lower than the last cut.
    releases.sort(key=lambda r: (r['unreleased'], int(r['build'])))
    return releases


def read_version():
    """current:main-2026.09.17-9151 -> name, branch 'main', build '9151', date '2026-09-17'."""
    version: dict = {'name': None, 'branch': None, 'build': None, 'date': None}
    if not VERSION_FILE.exists():
        return version
    for line in VERSION_FILE.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('current:'):
            m = re.search(r'(\S+)-(\d{4})\.(\d{2})\.(\d{2})-(\d+)', line[len('current:'):].strip())
            if m:
                version.update(name=m.group(0), branch=m.group(1), build=m.group(5),
                               date=f'{m.group(2)}-{m.group(3)}-{m.group(4)}')
    return version


def build_payload():
    loc = count_repo(REPO)
    version = read_version()
    bugs = collect_bugs()
    releases = collect_releases(version)

    # The release note counts its own bullets; the bug files carry the authoritative
    # "Fixed in". They answer different questions and do not have to match, so both
    # are exposed rather than one being quietly preferred.
    for r in releases:
        r['bugs_fixed'] = (bugs['fixed_unreleased'] if r['unreleased']
                           else bugs['fixed_per_build'].get(r['build'], 0))

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'build': version['build'],
        'build_name': version['name'],
        'build_date': version['date'],
        'loc': {
            'total': loc['total'],
            'files': loc['files'],
            'method': loc['method'],
            'by_area': [
                {'name': area, 'value': data['lines'], 'files': data['files']}
                for area, data in sorted(loc['by_area'].items(),
                                         key=lambda kv: kv[1]['lines'], reverse=True)
            ],
        },
        'releases': releases,
        'bugs': bugs,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='where to write the JSON')
    ap.add_argument('--print', action='store_true', dest='do_print',
                    help='also print the payload')
    args = ap.parse_args()

    payload = build_payload()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')

    loc, bugs = payload['loc'], payload['bugs']
    print(f"✓ {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    print(f"  build {payload['build']} ({payload['build_date']})")
    print(f"  {loc['total']:,} lines in {loc['files']} files [{loc['method']}] "
          f"across {len(loc['by_area'])} areas")
    print(f"  {bugs['total']} bug reports, {sum(bugs['fixed_per_build'].values())} tied to a build, "
          f"{bugs['unshipped']} unshipped, {bugs['internal_only']} internal-only")
    cut = sum(not r['unreleased'] for r in payload['releases'])
    print(f"  {cut} cut builds in the release note, plus {payload['build_name']} (unreleased)"
          if cut < len(payload['releases']) else f"  {cut} cut builds in the release note")

    # A parser that silently returns zero is worse than one that fails: the chart
    # would render four empty bars and read as a slow quarter rather than a bug.
    if payload['releases'] and not any(r['features'] or r['fixes'] for r in payload['releases']):
        print('✗ every release parsed as 0 features and 0 fixes — the release-note heading '
              'format changed; fix collect_releases() before trusting this file',
              file=sys.stderr)
        return 1

    if args.do_print:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
