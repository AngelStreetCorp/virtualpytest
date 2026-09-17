#!/usr/bin/env python3
"""Feature delivery report — is a feature actually delivered *and* tested?

Answers one question: for `features/<name>/`, which tests are supposed to exist, did
they run, and where is the evidence. Prints a markdown table with a report link per
test, so the result can be pasted straight into the release-note entry
(docs/release_note/README.md) as the delivery evidence for that feature.

    python3 scripts/feature_delivery_report.py quicktest
    python3 scripts/feature_delivery_report.py cicd --run 201
    python3 scripts/feature_delivery_report.py --all

Exit code is 1 when a feature has at least one gap, so CI or a pre-release check can
gate on it. `--server` overrides the CI/CD API base (default: the LAN server).

The expected test set per feature (see docs/technical/FEATURES.md → "Testing a feature"):

  tier A  features/<name>/**/*.test.ts(x)   pure logic — compile/transform helpers
  tier A  tests/frontend/<Page>.test.tsx    one per page in frontend/routes.tsx
  tier A  tests/backend_server/test_<name>.py   only when the feature has backend_server
  tier A  every routes[].path present in tests/e2e/playwright/specs/ui.pages.spec.js

Tier B (execution on host-clone-1) is deliberately NOT inferred here: whether a feature
needs a device is a judgement call, so it is recorded in the feature's own row in
FEATURES.md rather than guessed from the folder layout.

Granularity caveat, so the table is not read as more than it is: `ci_jobs` stores one row
per CI *job*, not per test. A row therefore means "this test exists and the job that runs
it passed", not "this individual test passed" — several rows legitimately share one report
link. A ⛔ is exact (the file or route is genuinely absent); a ✅ is job-level.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVER = os.environ.get('CICD_SERVER_URL', 'http://localhost:5109')
SPEC = ROOT / 'tests/e2e/playwright/specs/ui.pages.spec.js'

#: Which CI job actually executes each kind of test, so a row can be tied to its report.
JOB_FOR_KIND = {
    'unit': 'frontend-component-tests',
    'component': 'frontend-component-tests',
    'backend': 'backend-server-tests',
    'route': 'e2e-pages',
}


def feature_names() -> List[str]:
    return sorted(
        p.parent.name for p in ROOT.glob('features/*/manifest.json')
    )


def spec_routes() -> set:
    if not SPEC.exists():
        return set()
    return set(re.findall(r"path:\s*'([^']+)'", SPEC.read_text()))


def feature_routes(name: str) -> List[str]:
    """Paths the feature registers. De-duplicated: `nav:` entries repeat the same path
    as their `routes:` entry, and counting them twice double-reports every gap."""
    f = ROOT / f'features/{name}/frontend/routes.tsx'
    if not f.exists():
        return []
    seen: List[str] = []
    for p in re.findall(r"path:\s*'([^']+)'", f.read_text()):
        if p not in seen:
            seen.append(p)
    return seen


def route_components(name: str) -> List[tuple]:
    """[(path, ComponentName)] for each registered route, read from the `element:` JSX.

    The component name is what ties a route to its test file; the URL slug is not
    specific enough (two cicd routes share the substring "cicd").
    """
    f = ROOT / f'features/{name}/frontend/routes.tsx'
    if not f.exists():
        return []
    pairs = re.findall(r"path:\s*'([^']+)'\s*,\s*element:\s*<\s*([A-Za-z0-9_]+)", f.read_text())
    out: List[tuple] = []
    for path, comp in pairs:
        if (path, comp) not in out:
            out.append((path, comp))
    return out


def expected_tests(name: str) -> List[Dict[str, Any]]:
    """The test set a feature is supposed to ship, each marked present or missing."""
    rows: List[Dict[str, Any]] = []
    fdir = ROOT / 'features' / name

    # tier A — pure logic living inside the feature
    own = sorted(glob.glob(str(fdir / '**' / '*.test.ts'), recursive=True) +
                 glob.glob(str(fdir / '**' / '*.test.tsx'), recursive=True))
    helpers = sorted(glob.glob(str(fdir / 'frontend' / 'utils' / '*.ts')))
    if helpers:
        rows.append({
            'kind': 'unit',
            'what': f'pure logic ({len(helpers)} file(s) in frontend/utils/)',
            'present': bool(own),
            'detail': ', '.join(Path(p).name for p in own) if own
                      else 'no *.test.ts beside ' + ', '.join(Path(h).name for h in helpers),
        })

    # tier A — one component test per page the feature registers. Matched on the route's
    # *component* name, not on the URL slug: slug matching made `/test-execution/cicd`
    # (RunCICDPage) match CICDReports.test.tsx and report a page as covered when it is not.
    # Path('X.test.tsx').stem is 'X.test' — strip the '.test' too, or nothing ever matches.
    stems = {Path(p).name[: -len('.test.tsx')].lower(): Path(p).name
             for p in glob.glob(str(ROOT / 'tests/frontend/*.test.tsx'))}
    for route, component in route_components(name):
        candidates = {component.lower(), re.sub(r'page$', '', component, flags=re.I).lower()}
        hit = next((stems[c] for c in candidates if c in stems), None)
        rows.append({
            'kind': 'component',
            'what': f'component test for `{route}` (`{component}`)',
            'present': bool(hit),
            'detail': hit or f'no tests/frontend/{component}.test.tsx',
        })

    # tier A — a feature with backend_server routes REQUIRES a backend test file; a feature
    # without one may still have API tests (quicktest has no backend of its own but drives
    # the core /server/testcase/* routes), so credit the file whenever it exists rather than
    # only looking when backend_server/ is present — otherwise the report understates work
    # that was actually done.
    f = ROOT / f'tests/backend_server/test_{name.replace("-", "_")}.py'
    required = (fdir / 'backend_server').exists()
    if required or f.exists():
        rows.append({
            'kind': 'backend',
            'what': f'`tests/backend_server/{f.name}`',
            'present': f.exists(),
            'detail': 'present' if f.exists() else 'missing (feature has backend_server routes)',
        })

    # tier A — every page must be in the all-pages sweep. A parameterised route
    # (/monitoring/avq/:hostName/:deviceId) can never appear literally, since the sweep
    # needs a concrete URL to visit — match it by shape instead, or such a route would be
    # permanently unsatisfiable and the report would nag forever.
    in_spec = spec_routes()
    for route in feature_routes(name):
        if ':' in route:
            pattern = re.compile(
                '^' + re.sub(r':[A-Za-z0-9_]+', '[^/]+', re.escape(route).replace(r'\:', ':')) + '$'
            )
            hit = next((p for p in in_spec if pattern.match(p)), None)
            present, detail = bool(hit), (f'covered by `{hit}`' if hit
                                          else 'no concrete URL for this route in the PAGES array')
        else:
            present = route in in_spec
            detail = 'in the sweep' if present else 'NOT in the PAGES array'
        rows.append({
            'kind': 'route',
            'what': f'`{route}` in ui.pages.spec.js',
            'present': present,
            'detail': detail,
        })

    return rows


def fetch_run(server: str, run: Optional[str]) -> Optional[Dict[str, Any]]:
    url = f'{server}/server/cicd/runs?expand=jobs&limit=25'
    # Cloudflare fronts the public hostname and 403s the default python-urllib UA, so send a
    # browser one — that makes --server https://virtualpytest.angelstreet.io work from a laptop
    # as well as the LAN address from a runner.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    }
    # Non-browser caller: authenticate with the shared service key when one is exported
    # (docs/agent/platform/SERVER_AUTH.md). Without it this 401s on any server that
    # enforces login, and on an open-mode one — open mode waives only the browser login.
    api_key = os.environ.get('API_KEY')
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            runs = json.loads(r.read()).get('runs') or []
    except Exception as e:                                    # noqa: BLE001 - reported, not raised
        print(f'  ! could not reach {server}: {e}', file=sys.stderr)
        return None
    if not runs:
        return None
    if run:
        return next((x for x in runs if str(x.get('run')) == str(run)), None)
    return runs[0]


def report(name: str, server: str, run_id: Optional[str]) -> bool:
    rows = expected_tests(name)
    run = fetch_run(server, run_id)
    jobs = (run or {}).get('jobs_detail') or {}

    if run:
        head = (f"### `{name}` — run #{run.get('run')} "
                f"({run.get('branch')} @ {run.get('sha')}, {run.get('overall')})")
    else:
        head = f'### `{name}` — no CI run data'
    print(head)
    print()
    if not rows:
        print('_No frontend routes and no backend part — nothing expected._\n')
        return True

    print('| Test | Tier | CI job | Result | Evidence |')
    print('|---|---|---|---|---|')
    gaps = 0
    for r in rows:
        job = JOB_FOR_KIND[r['kind']]
        detail = jobs.get(job) or {}
        if not r['present']:
            gaps += 1
            result, link = '⛔ **missing**', f"_{r['detail']}_"
        elif not detail:
            result, link = '— not run', '_no job row in the last run_'
        else:
            ok = detail.get('status') == 'success'
            result = '✅ pass' if ok else f"❌ {detail.get('status')}"
            link = f"[report]({detail.get('report_url')})"
            if not ok:
                gaps += 1
        print(f"| {r['what']} | A | `{job}` | {result} | {link} |")
    print()
    if gaps:
        print(f'**{gaps} gap(s) — `{name}` is not delivery-ready.**\n')
    else:
        print(f'**All expected tests present and passing — `{name}` is delivery-ready.**\n')
    return gaps == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('feature', nargs='?', help='feature folder name (features/<name>/)')
    ap.add_argument('--all', action='store_true', help='report on every feature')
    ap.add_argument('--run', help='CI run number (default: latest)')
    ap.add_argument('--server', default=DEFAULT_SERVER, help=f'CI/CD API base (default {DEFAULT_SERVER})')
    a = ap.parse_args()

    names = feature_names() if a.all else ([a.feature] if a.feature else [])
    if not names:
        ap.error('give a feature name or --all; known: ' + ', '.join(feature_names()))

    print('# Feature delivery report\n')
    ok = True
    for n in names:
        if n not in feature_names():
            print(f'### `{n}` — unknown feature\n')
            ok = False
            continue
        ok = report(n, a.server, a.run) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
