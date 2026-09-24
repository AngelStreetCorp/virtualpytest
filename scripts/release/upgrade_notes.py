#!/usr/bin/env python3
"""
Print the **Upgrade** block of a release-note build section from the git diff between two refs.

    scripts/release/upgrade_notes.py [<from-ref>] [<to-ref>] [--branch main]

Defaults: <from-ref> = the newest `<branch>-*` tag reachable from HEAD (the previous build),
<to-ref> = HEAD. Output is markdown, meant to be pasted verbatim under the new
`## build NNNN — date` heading (docs/agent/release/RELEASING.md, "Upgrade block") and then

What it derives, and from where (nothing is hard-coded per release):

- **Database**: `.sql` files added under `setup/db/migrations/` (core) and `features/<name>/db/`
  (feature — skipped where the feature is disabled). No deploy script applies either kind.
- **Dependencies**: packages added to `frontend/package.json` or either `requirements.txt`.
  A deploy excludes `node_modules` and never installs, so a new package fails the build ON THE
  VM and leaves the old bundle serving.
- **Settings**: keys added to the `.env.example` files. A deploy never edits a VM's `.env`, so
  each new key has to be added by hand where it matters.
- **Services**: which systemd units run code that changed. Core units come from the unit
  templates in `backend_host/config/services/linux/` and `backend_server/config/services/linux/`
  (unit = `vpt-<stem>`, script = the `.py`/`.sh` in `ExecStart`), feature units from
  `features/*/backend_host/services/`. `vpt-server`, `vpt-host` and `vpt-frontend-prod` are
  restarted by the deploy scripts; host aux units only with `--restart`; server-side aux units
  (heatmap, discard workers, fleet health) and hand-installed unit templates never — those are
  called out as manual.
- **Proxy / Grafana**: nginx config and dashboard JSON changes, both hand-deployed.
- **New optional features**: a `features/<name>/manifest.json` added in the range — customers
  who must not get it need it in `DISABLED_FEATURES` before their next deploy.

Exit code is always 0; the block is a starting point for a human, not a gate.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import OrderedDict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

ENV_EXAMPLES = (
    'backend_server/src/.env.example',
    'backend_host/src/.env.example',
    'frontend/.env.example',
    'setup/docker/.env.example',
)
UNIT_DIRS = (
    ('server', 'backend_server/config/services/linux'),
    ('host', 'backend_host/config/services/linux'),
)
# Units the deploy scripts restart themselves (update_core.sh / deploy_customer.sh).
DEPLOY_RESTARTS = {'vpt-server', 'vpt-host', 'vpt-frontend-prod'}
# Host aux units the deploy scripts restart only when asked (--restart [unit]).
OPT_IN_RESTARTS = {'vpt-stream', 'vpt-monitor', 'vpt-subtitle', 'vpt-transcript', 'vpt-archiver', 'vpt-avq', 'vpt-kpi'}
# Interactive/desktop units that carry no VPT code: never worth a line.
IGNORED_UNITS = {'vpt-vnc', 'vpt-websockify', 'vpt-emulator-fifo', 'vpt-ble-remote@', 'vpt-hid-agent@', 'vpt-hid-remote@'}


def git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=REPO, check=True, capture_output=True, text=True).stdout


def default_from_ref(branch: str) -> str:
    try:
        return git('describe', '--tags', '--match', f'{branch}-*', '--abbrev=0').strip()
    except subprocess.CalledProcessError:
        sys.exit(f'no {branch}-* tag reachable from HEAD; pass <from-ref> explicitly')


def version_at(ref: str) -> str:
    try:
        txt = git('show', f'{ref}:VERSION.txt')
    except subprocess.CalledProcessError:
        return ref
    m = re.search(r'^current:(\S+)', txt, re.M)
    return m.group(1) if m else ref


# ---- units -----------------------------------------------------------------------------------

class Unit:
    def __init__(self, name: str, where: str, script: str, feature: str | None = None):
        self.name, self.where, self.script, self.feature = name, where, script, feature
        self.reasons: list[str] = []


def _script_from_execstart(line: str, workdir: str) -> str | None:
    """First token of ExecStart that is a .py/.sh file, made repo-relative."""
    body = line.split('=', 1)[1].strip()
    for tok in body.split():
        if not (tok.endswith('.py') or tok.endswith('.sh')):
            continue
        tok = tok.replace('%PROJECT_ROOT%/', '').replace('/opt/virtualpytest/', '')
        if tok.startswith('/'):
            return None  # a system binary
        if not os.path.exists(os.path.join(REPO, tok)) and workdir:
            cand = os.path.join(workdir, tok)
            if os.path.exists(os.path.join(REPO, cand)):
                tok = cand
        return tok
    return None


def _is_oneshot(rel_path: str) -> bool:
    """A Type=oneshot unit runs to completion and is started again by its timer."""
    try:
        return bool(re.search(r'^Type=oneshot\s*$',
                              open(os.path.join(REPO, rel_path), encoding='utf-8', errors='replace').read(),
                              re.M))
    except OSError:
        return False


def load_units() -> list[Unit]:
    units: list[Unit] = []
    dirs = [(w, d, None) for w, d in UNIT_DIRS]
    feats = os.path.join(REPO, 'features')
    if os.path.isdir(feats):
        for name in sorted(os.listdir(feats)):
            d = f'features/{name}/backend_host/services'
            if os.path.isdir(os.path.join(REPO, d)) and os.path.exists(os.path.join(feats, name, 'manifest.json')):
                dirs.append(('host', d, name))
    for where, d, feature in dirs:
        full = os.path.join(REPO, d)
        if not os.path.isdir(full):
            continue
        for fn in sorted(os.listdir(full)):
            if not fn.endswith('.service'):
                continue
            stem = fn[:-len('.service')]
            name = stem if stem.startswith('vpt-') else f'vpt-{stem}'
            text = open(os.path.join(full, fn), encoding='utf-8', errors='replace').read()
            wd = ''
            m = re.search(r'^WorkingDirectory=(.+)$', text, re.M)
            if m:
                wd = m.group(1).strip().replace('%PROJECT_ROOT%', '').replace('/opt/virtualpytest', '').strip('/')
            m = re.search(r'^ExecStart=(.+)$', text, re.M)
            script = _script_from_execstart(m.group(0), wd) if m else None
            if script is None or name in IGNORED_UNITS:
                continue
            # A Type=oneshot unit runs to completion and is started again by its timer, so each
            # run already executes whatever code is on disk -- restarting it changes nothing.
            # vpt-fleet-health (oneshot + a 07:00 timer) was being listed as "restart by hand"
            # on every release alongside the daemons, which it is not.
            if re.search(r'^Type=oneshot\s*$', text, re.M):
                continue
            units.append(Unit(name, where, script, feature))
    return units


# ---- analysis --------------------------------------------------------------------------------

def under(path: str, *prefixes: str) -> bool:
    return any(path == p or path.startswith(p.rstrip('/') + '/') for p in prefixes)


def analyse(changed: list[str], added: list[str]) -> dict:
    out: dict = OrderedDict()
    # A *_rollback.sql ships NEXT TO the migration it undoes. Listing it beside the migration
    # as something to "apply once per database" invites an operator working down the list to
    # run both and silently revert the release. Kept, but separated and labelled.
    _sql = [
        (p, 'core') for p in added if under(p, 'setup/db/migrations') and p.endswith('.sql')
    ] + [
        (p, p.split('/')[1]) for p in added if re.match(r'^features/[^/]+/db/.*\.sql$', p)
    ]
    out['migrations'] = [(p, o) for p, o in _sql if not p.endswith('_rollback.sql')]
    out['rollbacks'] = [p for p, _ in _sql if p.endswith('_rollback.sql')]
    out['new_features'] = [p.split('/')[1] for p in added if re.match(r'^features/[^/]+/manifest\.json$', p)]
    out['nginx'] = [p for p in changed if under(p, 'infra/proxy/nginx') and p.endswith('.conf')]
    out['grafana'] = [p for p in changed if p.endswith('.json') and (
        under(p, 'infra/monitoring/grafana/dashboards') or re.match(r'^features/[^/]+/grafana/', p))]
    # A oneshot unit's template is skipped like the unit itself: nothing about it is a restart,
    # and its next timer-driven run reads whatever is installed.
    out['unit_templates'] = [p for p in changed if p.endswith('.service')
                             and under(p, 'backend_host/config/services', 'backend_server/config/services')
                             and not _is_oneshot(p)]

    shared = [p for p in changed if under(p, 'shared/src')]
    feat_lib = [p for p in changed if re.match(r'^features/[^/]+/lib/', p)]
    server_src = [p for p in changed if under(p, 'backend_server/src') or re.match(r'^features/[^/]+/backend_server/', p)]
    host_src = [p for p in changed if under(p, 'backend_host/src', 'backend_host/app.py')
                or re.match(r'^features/[^/]+/backend_host/(?!services/)', p)]
    frontend = [p for p in changed if (under(p, 'frontend') and not under(p, 'frontend/public/docs'))
                or re.match(r'^features/[^/]+/frontend/', p)]
    docs = [p for p in changed if under(p, 'docs') and p.endswith('.md')]

    units = load_units()
    by_name = {u.name: u for u in units}

    def hit(name: str, why: str) -> None:
        u = by_name.get(name)
        if u is not None and why not in u.reasons:
            u.reasons.append(why)

    if server_src:
        hit('vpt-server', 'backend_server')
    if host_src:
        hit('vpt-host', 'backend_host')
    for u in units:
        if u.name in DEPLOY_RESTARTS:
            continue
        if u.script in changed:
            u.reasons.append(u.script)
        elif u.feature and any(p.startswith(f'features/{u.feature}/backend_host/') for p in changed):
            u.reasons.append(f'features/{u.feature}/backend_host')
        elif u.where == 'host' and u.script.startswith('backend_host/') and host_src:
            u.reasons.append('backend_host/src (may be imported by the worker)')
        elif u.where == 'server' and u.script.startswith('backend_server/') and server_src:
            u.reasons.append('backend_server/src (may be imported by the worker)')
    if shared or feat_lib:
        why = 'shared/src' if shared else 'features/*/lib'
        for u in units:
            if u.script.endswith('.py') and why not in u.reasons:
                u.reasons.append(why)
    fe = Unit('vpt-frontend-prod', 'frontend', 'frontend')
    if frontend:
        fe.reasons.append('frontend')
    if docs:
        fe.reasons.append('docs (bundled into the frontend build)')
    out['units'] = [u for u in units if u.reasons] + ([fe] if fe.reasons else [])
    return out


def env_keys_added(frm: str, to: str) -> list[tuple[str, list[str]]]:
    res = []
    for f in ENV_EXAMPLES:
        try:
            diff = git('diff', f'{frm}..{to}', '--', f)
        except subprocess.CalledProcessError:
            continue
        # Active lines only: an `xKEY=` line is the examples' convention for a disabled sample.
        added = {m.group(1) for m in re.finditer(r'^\+([A-Z][A-Za-z0-9_]*)=', diff, re.M)}
        removed = {m.group(1) for m in re.finditer(r'^-([A-Z][A-Za-z0-9_]*)=', diff, re.M)}
        keys = sorted(added - removed)
        if keys:
            res.append((f, keys))
    return res


DEP_MANIFESTS = (
    ('frontend/package.json', 'frontend'),
    ('backend_server/requirements.txt', 'server'),
    ('backend_host/requirements.txt', 'every host'),
)


def deps_added(frm: str, to: str) -> list[tuple[str, str, list[str]]]:
    """Dependencies added to a manifest since the last build.

    A deploy rsyncs source and EXCLUDES node_modules (update_core.sh), and nothing in
    the deploy path runs an install. So a release that adds a dependency builds fine
    on a dev machine and fails on the VM with "Rollup failed to resolve import", which
    is what happened when recharts arrived with the Analytics page: the build aborted
    and the frontend kept serving a stale bundle.

    Detected rather than remembered, for the same reason the .env keys are.
    """
    res = []
    for f, where in DEP_MANIFESTS:
        try:
            diff = git('diff', f'{frm}..{to}', '--', f)
        except subprocess.CalledProcessError:
            continue
        if f.endswith('package.json'):
            # `    "recharts": "3.10.1",` — a dependency line, not a script or a field.
            added = {m.group(1) for m in re.finditer(r'^\+\s*"([@A-Za-z0-9._/-]+)":\s*"[~^]?[0-9]', diff, re.M)}
            removed = {m.group(1) for m in re.finditer(r'^-\s*"([@A-Za-z0-9._/-]+)":\s*"[~^]?[0-9]', diff, re.M)}
        else:
            added = {m.group(1) for m in re.finditer(r'^\+([A-Za-z][A-Za-z0-9._-]*)', diff, re.M)}
            removed = {m.group(1) for m in re.finditer(r'^-([A-Za-z][A-Za-z0-9._-]*)', diff, re.M)}
        names = sorted(added - removed)
        if names:
            res.append((f, where, names))
    return res


# ---- render ----------------------------------------------------------------------------------

def render(frm: str, to: str, branch: str, nfiles: int, a: dict, env: list) -> str:
    v_from, v_to = version_at(frm), version_at(to)
    L: list[str] = []
    L.append('### Upgrade')
    L.append('')
    L.append(f'**Compared with** `{v_from}` → `{v_to}` ({nfiles} files changed).')
    L.append('')

    # Database
    # No psql incantation and no paragraph on why: whoever applies a migration knows how, and the
    # release note is read far more often than it is acted on.
    if a['migrations']:
        L.append('**Database** — apply these once per database:')
        for p, owner in a['migrations']:
            note = '' if owner == 'core' else f' (feature `{owner}`)'
            L.append(f'- `{p}`{note}')
    else:
        L.append('**Database** — no migration.')
    if a.get('rollbacks'):
        L.append('')
        L.append('_Do **not** apply:_ ' + ', '.join(f'`{os.path.basename(p)}`' for p in a['rollbacks'])
                 + ' — they undo a migration above.')
    L.append('')

    # Settings
    # setup/docker/.env.example is never listed: nobody edits an .example, and that one belongs to
    # the standalone docker install, so its keys (VPT_IMAGE_TAG, VPT_REGISTRY …) are noise for
    # everybody else. The keys are named; where they go is obvious from the file they came from.
    rows = [(f, keys) for f, keys in env if not f.startswith('setup/docker/')]
    if rows:
        L.append('**Settings** — add to the `.env` on each machine:')
        for f, keys in rows:
            where = {'backend_server/src/.env.example': 'server',
                     'backend_host/src/.env.example': 'every host',
                     'frontend/.env.example': 'frontend'}.get(f, f)
            L.append(f'- {where}: ' + ', '.join(f'`{k}`' for k in keys))
    else:
        L.append('**Settings** — no new key.')
    L.append('')

    # Dependencies. A deploy excludes node_modules and never installs, so a new package
    # makes the build fail ON THE VM and leaves the old bundle serving.
    if a['deps']:
        L.append('**Dependencies** — install BEFORE building, on every machine of that kind:')
        for f, where, names in a['deps']:
            L.append(f'- {where} (`{f}`): ' + ', '.join(f'`{n}`' for n in names))
        if any(f.endswith('package.json') for f, _, _ in a['deps']):
            L.append('  ```')
            L.append('  cd /opt/virtualpytest/frontend && sudo -u vpt_user npm install')
            L.append('  ```')
            L.append('  Skipping this fails the build with "Rollup failed to resolve import" and')
            L.append('  the site keeps serving the previous bundle.')
    else:
        L.append('**Dependencies** — no new package.')
    L.append('')

    # Services — only what a deploy will not restart on its own. The rest was a table of our own
    # reasoning: which unit imports which module is why WE think a restart is needed, not work.
    manual = [u for u in a['units'] if u.name not in DEPLOY_RESTARTS
              and u.name not in OPT_IN_RESTARTS and not u.feature]
    if manual:
        L.append('**Services** — restart by hand (the deploy restarts the rest itself): '
                 + ', '.join(f'`{u.name}`' for u in manual))
    else:
        L.append('**Services** — nothing to restart by hand.')
    if a['unit_templates']:
        L.append('')
        L.append('Unit templates changed, reinstall where they run: '
                 + ', '.join(f'`{os.path.basename(p)}`' for p in a['unit_templates']))
    L.append('')

    # Proxy / Grafana
    if a['nginx']:
        L.append('**Proxy** — ' + ', '.join(f'`{os.path.basename(p)}`' for p in a['nginx']))
        L.append('')
    if a['grafana']:
        L.append('**Grafana** — ' + ', '.join(f'`{os.path.basename(p)}`' for p in a['grafana']))
        L.append('')

    return '\n'.join(L) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('from_ref', nargs='?', help='previous build (default: newest <branch>-* tag)')
    ap.add_argument('to_ref', nargs='?', default='HEAD')
    ap.add_argument('--branch', default='main', help='branch name used in tags and the deploy command')
    args = ap.parse_args()
    frm = args.from_ref or default_from_ref(args.branch)
    to = args.to_ref
    rng = f'{frm}..{to}'
    changed = git('diff', '--name-only', rng).split()
    added = git('diff', '--name-only', '--diff-filter=A', rng).split()
    a = analyse(changed, added)
    a['deps'] = deps_added(frm, to)
    env = env_keys_added(frm, to)
    sys.stdout.write(render(frm, to, args.branch, len(changed), a, env))
    return 0


if __name__ == '__main__':
    sys.exit(main())
