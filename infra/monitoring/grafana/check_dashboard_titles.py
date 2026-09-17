#!/usr/bin/env python3
"""Check that a single-script Grafana dashboard is titled like the rest of the platform.

A dashboard whose panels all query ONE script is that script's dashboard, so its
title must be the script's identity label — the same string Run Tests, the Test
Cases page, the reports and the generic dashboards (script-results,
home-dashboard) show:

    [prefix] display_name  ->  display_name  ->  [prefix] script_name  ->  script_name

That is `format_script_label()` in shared/src/lib/utils/script_identity_utils.py.
Nothing enforced it on dashboard titles, which are hand-typed, so a customer
dashboard ended up titled "Microsoft Teams Network Assessment" for a script the
UI called "[TC015] Windows Network Assessment" and the file called
windows_networkassessmenttools — three names for one test, which is what the
customer reported.

Dashboards that query zero scripts (system monitoring) or several (home,
service-kpi, wifi correlation) are aggregate views and are skipped: their titles
are free text, and their per-row data labels already build the label in SQL.

Usage (from the repo whose dashboards you are checking — platform or overlay):
    python3 infra/monitoring/grafana/check_dashboard_titles.py [--fix]

Exits 1 on drift so it can gate a push. Note the identity map's source of truth
is the executable_identity table (Test Cases page); this offline check reads the
repo's script_identity_map.json, so a name edited only in the UI reads as drift
until the map is exported back. Re-import with scripts/import_script_identity_map.py.
"""

import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# 'script_name = 'x'' and 'script_name IN ('x', 'y')', in any casing/spacing.
EQ_RE = re.compile(r"script_name\s*=\s*'([^']+)'", re.IGNORECASE)
IN_RE = re.compile(r"script_name\s+IN\s*\(([^)]*)\)", re.IGNORECASE)

# Scripts a dashboard joins for context rather than reports on. gw_info is the
# gateway-metadata LATERAL that the gateway dashboards carry; it must not make
# every one of them look like a two-script dashboard.
CONTEXT_SCRIPTS = {'gw_info'}


def basename(script_ref):
    return script_ref.rsplit('/', 1)[-1]


def format_label(script_name, entry):
    """The one label chain — mirrors format_script_label() / formatScriptLabel()."""
    prefix = (entry.get('prefix') or '').strip()
    display = (entry.get('display_name') or '').strip()
    if prefix and display:
        return f'[{prefix}] {display}'
    if display:
        return display
    if prefix:
        return f'[{prefix}] {script_name}'
    return script_name


def scripts_in(raw):
    """Every script_name literal a dashboard's SQL filters on, by basename."""
    found = set(EQ_RE.findall(raw))
    for group in IN_RE.findall(raw):
        found.update(re.findall(r"'([^']+)'", group))
    return {basename(s) for s in found}


def load_identity_map(repo_root):
    path = os.path.join(repo_root, 'test_scripts', 'script_identity_map.json')
    if not os.path.exists(path):
        return {}, path
    scripts = (json.load(open(path, encoding='utf-8')) or {}).get('scripts', {})
    return {basename(k): v for k, v in scripts.items() if isinstance(v, dict)}, path


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fix', action='store_true',
                        help='rewrite drifted titles in place instead of only reporting')
    parser.add_argument('--repo-root', default=REPO_ROOT,
                        help='repo to check (default: the repo this script lives in)')
    args = parser.parse_args()

    identity, map_path = load_identity_map(args.repo_root)
    if not identity:
        print(f'No identity map entries in {map_path} — nothing to check.')
        return 0

    pattern = os.path.join(args.repo_root, 'infra', 'monitoring', 'grafana', 'dashboards', '*.json')
    drift = []

    for path in sorted(glob.glob(pattern)):
        name = os.path.basename(path)
        raw = open(path, encoding='utf-8').read()
        try:
            title = json.loads(raw).get('title')
        except json.JSONDecodeError as e:
            print(f'SKIP {name}: not valid JSON ({e})')
            continue

        found = scripts_in(raw)
        subjects = found - CONTEXT_SCRIPTS or found
        if len(subjects) != 1:
            continue  # aggregate or non-script dashboard

        script_name = next(iter(subjects))
        entry = identity.get(script_name)
        if not entry:
            continue  # unmapped script: the bare name is already the right title

        expected = format_label(script_name, entry)
        if title == expected:
            continue

        drift.append((name, title, expected))
        if args.fix:
            fixed, n = re.subn(r'(\n  "title": )' + re.escape(json.dumps(title)),
                               lambda m: m.group(1) + json.dumps(expected), raw)
            if n != 1:
                print(f'  ! {name}: could not locate the dashboard-level title, fix by hand')
                continue
            open(path, 'w', encoding='utf-8').write(fixed)

    if not drift:
        print('All single-script dashboard titles match the identity map.')
        return 0

    verb = 'Fixed' if args.fix else 'Drifted'
    print(f'{verb} {len(drift)} dashboard title(s):')
    for name, title, expected in drift:
        print(f'  {name}: {title!r} -> {expected!r}')
    if not args.fix:
        print('\nRe-run with --fix to apply, then push with _push_dashboard.py.')
    return 0 if args.fix else 1


if __name__ == '__main__':
    sys.exit(main())
