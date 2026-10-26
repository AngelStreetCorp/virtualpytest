"""
Prerequisites of a Platform update (TASK-101): one small function per named check, run concurrently.

``run_all(core, overlay)`` returns ``{'ok', 'core', 'overlay', 'checks': [...]}``. Each check is
``{id, title, required, status: ok|ko|na, detail, log, fix, doc_anchor}``; ``ok`` means no *required* check is KO.
It never raises: a check that raises, or runs past its timeout, is a KO with the reason in ``detail``.

Every machine-touching call goes through ``Deps`` (a runner for commands, an HTTP getter, the host list,
``call_host``...), so each check is tested with mocks. ``doc_anchor`` is the section id in
``docs/user-guide/update-setup.md``. Logs mask tokens and passwords.

Required when (the rule each check applies, see ``docs/agent/platform/MAINTENANCE.md``):
  frontend_ssh  frontend host (Settings, else FRONTEND_DEPLOY_HOST) = host (ssh) or local; none = N/A; unset = KO  hosts_api      there are hosts
  hosts_download there are hosts         database  migrations are pending (or unknown)   tools   always
  db_backup     always (the VM agent action answers, or the last nightly backup is < 24 h)
  disk          always                   host_sudo always (hosts AND this server)  host_version   there are hosts
  github        core or overlay = github          gitlab  overlay = gitlab       no_test_running  never (warning)
"""

import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.src.lib.utils import git_auth
from shared.src.lib.utils import package_install
from shared.src.lib.utils import update_privileges as priv

from . import db_backup, frontend_ssh, server_key, settings

CHECK_TIMEOUT = 10
GB = 1024 ** 3
MIN_SERVER_FREE = 2 * GB
HOST_START_COMMAND = 'sudo systemctl start vpt-host'
ANCHOR = {
    'frontend_ssh': 'frontend-ssh', 'hosts_api': 'hosts-api', 'hosts_download': 'hosts-download',
    'database': 'database', 'db_backup': 'db-backup', 'tools': 'tools', 'disk': 'disk', 'host_sudo': 'host-sudo',
    'host_version': 'host-version', 'github': 'source-github', 'gitlab': 'source-gitlab',
    'no_test_running': 'no-test-running',
}
TITLES = {
    'frontend_ssh': 'Server to frontend VM over SSH',
    'hosts_api': 'Server to every host API',
    'hosts_download': 'Hosts download from the server',
    'database': 'Server to database',
    'db_backup': 'Database backup on request',
    'tools': 'Tools on the server and the hosts',
    'disk': 'Disk space',
    'host_sudo': 'Sudo rights on hosts',
    'host_version': 'Host version supports bundle pull',
    'github': 'Source: GitHub reachable',
    'gitlab': 'Source: GitLab configured and reachable',
    'no_test_running': 'No test run in progress',
}
ORDER = list(TITLES)
_SECRET_RES = (re.compile(r'(glpat-[A-Za-z0-9_\-]{8,})'), re.compile(r'(gh[pousr]_[A-Za-z0-9]{16,})'),
               re.compile(r'(://[^/\s:@]+:)[^@\s]+@'))


def mask(text: str, secrets: Optional[List[str]] = None) -> str:
    for s in secrets or []:
        if s:
            text = text.replace(s, '***')
    text = _SECRET_RES[0].sub('***', text)
    text = _SECRET_RES[1].sub('***', text)
    return _SECRET_RES[2].sub(r'\1***@', text)


def _run(argv: List[str], timeout: int, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, **(env or {})})


def _get_host_call(host: dict, endpoint: str, method: str = 'GET', timeout: int = 9) -> Tuple[Any, int]:
    from shared.src.lib.utils.build_url_utils import call_host
    return call_host(host, endpoint, method=method, timeout=timeout)


def _hosts() -> List[dict]:
    from backend_server.src.lib.utils.server_utils import get_host_manager
    return list(get_host_manager().get_all_hosts().values())


def _http_get(url: str, headers: Dict[str, str], timeout: int):
    import requests
    return requests.get(url, headers=headers, timeout=timeout)


def _locks() -> Dict[str, Dict[str, Any]]:
    from backend_server.src.lib.utils.lock_utils import get_all_locked_devices
    return get_all_locked_devices()


def _migration_status():
    from . import migrations as mig
    return mig.status(mig.PsycopgBackend()), mig.PsycopgBackend()


def _default_build_root() -> str:
    from backend_server.src.lib.utils.integration_state import state_dir
    return str(state_dir())


@dataclass
class Deps:
    run: Callable = _run
    which: Callable = shutil.which
    disk_free: Callable[[str], int] = lambda p: shutil.disk_usage(p).free  # noqa: E731
    hosts: Callable[[], List[dict]] = _hosts
    call_host: Callable = _get_host_call
    http_get: Callable = _http_get
    locks: Callable = _locks
    migration_status: Callable = _migration_status
    build_root: Callable[[], str] = _default_build_root
    env: Dict[str, str] = field(default_factory=lambda: dict(os.environ))
    gitlab_credentials: Optional[Callable[[], Tuple[str, str]]] = None
    github_token: Optional[Callable[[], str]] = None
    core_remote: Optional[Callable[[], str]] = None
    db_backup: Optional[Callable[[], 'db_backup.Deps']] = None


class Ctx:
    """What the checks share: the chosen sources, the dependencies and the per-host reports (fetched once)."""

    def __init__(self, core: str, overlay: str, deps: Deps, fmt: str = 'zip'):
        self.core, self.overlay, self.fmt, self.deps = core, overlay, fmt, deps
        self._reports: Optional[List[dict]] = None
        self._lock = threading.Lock()

    def host_reports(self) -> List[dict]:
        """One entry per host: {name, health_status, report (updatePrereqs body) | None, status, error}."""
        with self._lock:
            if self._reports is None:
                hosts = self.deps.hosts()
                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(hosts)))) as pool:
                    self._reports = list(pool.map(self._one, hosts))
            return self._reports

    def _one(self, host: dict) -> dict:
        name = str(host.get('host_name') or host.get('name') or '?')
        entry = {'name': name, 'status': None, 'report': None, 'error': ''}
        try:
            body, status = self.deps.call_host(host, '/host/system/updatePrereqs', 'GET', 9)
            entry['status'] = status
            if status == 200 and isinstance(body, dict):
                entry['report'] = body
            else:
                entry['error'] = (body.get('error') if isinstance(body, dict) else '') or f'HTTP {status}'
        except Exception as exc:
            entry['error'] = f'{type(exc).__name__}: {exc}'[:200]
        return entry


def _res(cid: str, required: bool, status: str, detail: str, log: str = '', fix: str = '',
         actions: Optional[List[Dict[str, str]]] = None, update_hosts: Optional[List[str]] = None) -> Dict[str, Any]:
    """``actions`` (TASK-128): what an admin runs as root to fix a KO, ``[{machine, command, reason}]``. The page shows
    each command with a Copy button; the app never runs it. Any check may return them.
    ``update_hosts`` (G11): hosts the page may update once itself (the existing shared-source update); only ``host_version``."""
    return {'id': cid, 'title': TITLES[cid], 'required': bool(required) and status != 'na', 'status': status,
            'detail': detail, 'log': log, 'fix': fix if status == 'ko' else '', 'doc_anchor': ANCHOR[cid],
            'actions': list(actions or []) if status == 'ko' else [],
            'update_hosts': list(update_hosts or []) if status == 'ko' else []}


def _human(n: Optional[int]) -> str:
    return 'unknown' if n is None else f'{n / GB:.1f} GB'


# -- 1 ---------------------------------------------------------------------------------------------
def check_frontend_ssh(ctx: Ctx) -> Dict[str, Any]:
    cfg = frontend_ssh.config(ctx.deps.env)
    if cfg['mode'] == 'none':
        return _res('frontend_ssh', False, 'na', 'No frontend to update (frontend host = none).')
    if cfg['mode'] == 'unset':
        return _res('frontend_ssh', True, 'ko', 'The frontend host (FRONTEND_DEPLOY_HOST) is not set.',
                    fix='Platform update -> Settings -> Frontend host (host, local or none; or FRONTEND_DEPLOY_HOST in the server .env): host = the frontend VM address, '
                        'local = the frontend runs on the server VM, none = no frontend to update. See the guide.')
    if cfg['mode'] == 'local':
        return _check_frontend_local(ctx, cfg)
    if not cfg['user']:
        return _res('frontend_ssh', True, 'ko', 'The frontend SSH user (FRONTEND_DEPLOY_SSH_USER) is not set.',
                    fix='Platform update -> Settings -> SSH user (or FRONTEND_DEPLOY_SSH_USER in the server .env), then follow the guide.')
    missing = frontend_ssh.missing_local_tools(cfg, ctx.deps.which)
    if missing:
        return _res('frontend_ssh', True, 'ko', f'Missing on the server: {", ".join(missing)}.',
                    fix=f'Install {" and ".join(missing)} on the server VM.')
    secrets, env = frontend_ssh.secrets(cfg), frontend_ssh.child_env(cfg)
    svc = cfg['service']
    probes = [
        ('ssh login', 'echo ssh-ok', 'Create the server key (Settings -> Server key) and run the command shown here as root on the frontend VM.'),
        ('rsync on the frontend VM', 'command -v rsync', 'Install rsync on the frontend VM.'),
        ('sudo as the service user',
         frontend_ssh.sudo(cfg, f'-H -u {cfg["service_user"]} true'),
         f'Allow {cfg["user"]} to run commands as {cfg["service_user"]} with sudo -n (sudoers drop-in in the guide).'),
        (f'sudo systemctl restart {svc}', frontend_ssh.sudo(cfg, f'-l systemctl restart {svc}'),
         f'Allow {cfg["user"]} to run systemctl restart {svc} with sudo -n (sudoers drop-in in the guide).'),
    ]
    log, failed, fixes = [], [], []
    for label, remote, fix in probes:
        argv = frontend_ssh.ssh_argv(cfg, remote)
        try:
            res = ctx.deps.run(argv, 12, env)
            ok = res.returncode == 0
            out = ((res.stdout or '') + (res.stderr or '')).strip()
        except subprocess.TimeoutExpired:
            ok, out = False, 'timed out'
        except Exception as exc:
            ok, out = False, f'{type(exc).__name__}: {exc}'
        log.append(f'{"ok  " if ok else "FAIL"} {label}' + (f'\n     {out[-300:]}' if out and not ok else ''))
        if not ok:
            failed.append(label)
            fixes.append(fix)
            if label == 'ssh login':
                break  # nothing else can work without it
    text = mask('\n'.join(log), secrets)
    if failed:
        return _res('frontend_ssh', True, 'ko', f'{cfg["user"]}@{cfg["host"]}: failed: {failed[0]}.', text, fixes[0],
                    server_key.actions(f'{failed[0]} failed', ctx.deps.env))
    return _res('frontend_ssh', True, 'ok', f'{cfg["user"]}@{cfg["host"]}: login, rsync, sudo and restart rights ok.', text)


def _check_frontend_local(ctx: Ctx, cfg: Dict[str, str]) -> Dict[str, Any]:
    """FRONTEND_DEPLOY_HOST=local: the frontend is built and restarted on this server VM."""
    root = (ctx.deps.env.get('VPT_PROJECT_ROOT') or '/opt/virtualpytest').rstrip('/')
    svc = cfg['service']
    probes = [
        ('build script', ['test', '-f', f'{root}/frontend/scripts/ensure_dist.sh'],
         f'{root}/frontend/scripts/ensure_dist.sh is missing: the project tree on this server has no frontend.'),
        (f'{svc} unit exists', ['systemctl', 'cat', svc],
         f'This server has no {svc} unit. Install it, or set the frontend host (Platform update -> Settings) to the frontend VM address (or none).'),
        (f'sudo systemctl restart {svc}', ['sudo', '-n', '-l', 'systemctl', 'restart', svc],
         'Install the sudoers drop-in (setup/sudoers/install_vpt_update_sudoers.sh), see the guide.'),
    ]
    log, failed, fixes = [], [], []
    for label, argv, fix in probes:
        try:
            res = ctx.deps.run(argv, 8)
            ok, out = res.returncode == 0, ((res.stderr or res.stdout or '').strip().splitlines() or [''])[-1][:200]
        except Exception as exc:
            ok, out = False, f'{type(exc).__name__}: {exc}'[:200]
        log.append(f'{"ok  " if ok else "FAIL"} {label}' + (f': {out}' if out and not ok else ''))
        if not ok:
            failed.append(label)
            fixes.append(fix)
    if failed:
        return _res('frontend_ssh', True, 'ko', f'Frontend on this server (local): failed: {failed[0]}.', '\n'.join(log), fixes[0])
    return _res('frontend_ssh', True, 'ok', f'Frontend on this server (local): build script, {svc} unit and restart right ok.', '\n'.join(log))


# -- TASK-128 G8: name the host setting that differs from this server -------------------------------------------
API_KEY_HINT = "copy API_KEY from the server's .env"


def _norm_url(url: str) -> str:
    return (url or '').strip().rstrip('/').lower()


def _env_where(root: str) -> str:
    return f'{root.rstrip("/")}/.env' if root else 'the .env'


def _mismatch(name: str, kind: str, server_url: str = '', host_url: str = '', root: str = '') -> Tuple[str, Dict[str, str]]:
    """-> (the detail sentence, the action) for one host. The key value is never printed: only where to copy it from."""
    where = _env_where(root)
    if kind == 'url':
        return (f'{name}: SERVER_URL is {host_url or "not set"}, this server is {server_url}',
                {'machine': name, 'command': f'SERVER_URL={server_url}',
                 'reason': f'Set this line in {where} on {name}, then restart its host service (sudo systemctl restart vpt-host).'})
    return (f"{name}: API_KEY differs from this server's",
            {'machine': name, 'command': f'API_KEY=<{API_KEY_HINT}>',
             'reason': f'Set API_KEY in {where} on {name} to the same value as on this server ({API_KEY_HINT}), then restart its host service (sudo systemctl restart vpt-host).'})


def _server_url(ctx: 'Ctx') -> str:
    return (ctx.deps.env.get('SERVER_URL') or '').strip().rstrip('/')


# -- 2 ---------------------------------------------------------------------------------------------
def check_hosts_api(ctx: Ctx) -> Dict[str, Any]:
    hosts = ctx.deps.hosts()
    if not hosts:
        return _res('hosts_api', False, 'na', 'No host is registered with this server.')

    def one(host):
        name = str(host.get('host_name') or host.get('name') or '?')
        try:
            _body, status = ctx.deps.call_host(host, '/host/system/health', 'GET', 8)
            return name, status == 200, f'HTTP {status}'
        except Exception as exc:
            return name, False, f'{type(exc).__name__}: {exc}'[:150]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
        rows = list(pool.map(one, hosts))
    log = '\n'.join(f'{"ok  " if ok else "FAIL"} {n}: {d}' for n, ok, d in rows)
    bad = [n for n, ok, _ in rows if not ok]
    keyed = [n for n, ok, d in rows if not ok and d in ('HTTP 401', 'HTTP 403')]
    if keyed:
        # The host answered but refused this server's key: the two API_KEY values differ. Not a stopped service.
        notes, actions = zip(*[_mismatch(n, 'key') for n in keyed])
        others = [n for n in bad if n not in keyed]
        actions = list(actions) + [{'machine': n, 'command': HOST_START_COMMAND, 'reason': f'{n} does not answer: start its host service.'}
                                   for n in others]
        detail = '; '.join(notes) + (f'; {len(others)} more do not answer: {", ".join(others)}' if others else '') + '.'
        return _res('hosts_api', True, 'ko', detail, log,
                    "Make API_KEY in the host .env the same as on this server, then restart the host service.", actions)
    if bad:
        # TASK-128 G5: a host that does not answer cannot be started through its own API (restartHostService is a host
        # API call), and the app has no other remote path to it: the one-line command is the action.
        actions = [{'machine': n, 'command': HOST_START_COMMAND, 'reason': f'{n} does not answer ({d}): start its host service.'}
                   for n, ok, d in rows if not ok]
        return _res('hosts_api', True, 'ko', f'{len(bad)} of {len(rows)} hosts do not answer: {", ".join(bad)}.', log,
                    'Start the host service (vpt-host) and check the server can reach its address and port.', actions)
    return _res('hosts_api', True, 'ok', f'All {len(rows)} hosts answer.', log)


# -- host-derived checks -----------------------------------------------------------------------------
def _host_state(entry: dict) -> str:
    if entry['status'] == 404:
        return 'old'
    if entry['report'] is None:
        return 'unreachable'
    if entry['report'].get('supports_apply_bundle') is False:
        return 'unsupported'
    return 'ok'


# Where an old host finds the new code (the shared source `updateCore` syncs from) and where its install lives.
OLD_HOST_ROOT = '/opt/virtualpytest'
OLD_HOST_SOURCE = '/mnt/shared/code/virtualpytest'


def _old_host_actions(name: str) -> List[Dict[str, str]]:
    """The manual first update of a host that has no ``updatePrereqs`` yet: pull when its install is a git checkout,
    copy the new tree over it when it is not. Run as the owner of the install; the restart needs root."""
    restart = 'sudo systemctl restart vpt-host'
    return [
        {'machine': name, 'command': f'cd {OLD_HOST_ROOT} && git pull --ff-only && {restart}',
         'reason': f'{name} is a git checkout: pull once as the install owner, then restart.'},
        {'machine': name, 'command': f'rsync -a --exclude=.env --exclude=venv --exclude=node_modules {OLD_HOST_SOURCE}/ {OLD_HOST_ROOT}/ && {restart}',
         'reason': f'{name} is not a git checkout: copy the new tree over it (the .env stays), then restart. Use any copy of the new code if the shared source is not mounted.'},
    ]


def check_host_version(ctx: Ctx) -> Dict[str, Any]:
    reports = ctx.host_reports()
    if not reports:
        return _res('host_version', False, 'na', 'No host is registered with this server.')
    log, bad, old = [], [], []
    for e in reports:
        state = _host_state(e)
        if state == 'ok':
            log.append(f'ok   {e["name"]}: version {e["report"].get("version", "?")}')
        else:
            why = {'old': 'no updatePrereqs endpoint: update this host once (button below, or the command)',
                   'unsupported': e['report'] and e['report'].get('error') or 'pull updates are not supported here',
                   'unreachable': e['error']}[state]
            log.append(f'FAIL {e["name"]}: {why}')
            bad.append(e['name'])
            if state == 'old':
                old.append(e['name'])
    if bad:
        actions = [a for name in old for a in _old_host_actions(name)]
        return _res('host_version', True, 'ko', f'{len(bad)} of {len(reports)} hosts cannot pull yet: {", ".join(bad)}.',
                    '\n'.join(log), 'Update these hosts once: press "Update host once" (needs the shared source mounted on the host) '
                    'or run the command, then re-check.', actions, update_hosts=old)
    return _res('host_version', True, 'ok', f'All {len(reports)} hosts can pull a bundle.', '\n'.join(log))


def _pull_capable(ctx: Ctx) -> List[dict]:
    return [e for e in ctx.host_reports() if _host_state(e) == 'ok']


def check_hosts_download(ctx: Ctx) -> Dict[str, Any]:
    reports = ctx.host_reports()
    if not reports:
        return _res('hosts_download', False, 'na', 'No host is registered with this server.')
    capable = _pull_capable(ctx)
    log, bad = [], []
    for e in reports:
        if e not in capable:
            log.append(f'n/a  {e["name"]}: the host cannot report (see "Host version supports bundle pull")')
            bad.append(e['name'])
            continue
        dl = e['report'].get('download') or {}
        log.append(f'{"ok  " if dl.get("ok") else "FAIL"} {e["name"]}: {dl.get("url", "")} {dl.get("detail", "")}'.rstrip())
        if not dl.get('ok'):
            bad.append(e['name'])
    if bad:
        server_url = _server_url(ctx)
        notes, actions = [], []
        for e in capable:
            if e['name'] not in bad:
                continue
            report = e['report']
            dl = report.get('download') or {}
            host_url = str(report.get('server_url') or '')
            root = str(report.get('project_root') or '')
            if server_url and _norm_url(host_url) != _norm_url(server_url):
                note, action = _mismatch(e['name'], 'url', server_url, host_url, root)
            elif re.search(r'HTTP (401|403)', str(dl.get('detail') or '')):
                note, action = _mismatch(e['name'], 'key', root=root)
            else:
                continue
            notes.append(note)
            actions.append(action)
        detail = f'{len(bad)} of {len(reports)} hosts cannot download from the server: {", ".join(bad)}.'
        if notes:
            detail += ' ' + '; '.join(notes) + '.'
        return _res('hosts_download', True, 'ko', detail, mask('\n'.join(log)),
                    'Open HTTPS (or HTTP) from the host to the server URL in SERVER_URL, and check API_KEY matches the server.', actions)
    return _res('hosts_download', True, 'ok', f'All {len(reports)} hosts download the test file from the server.', mask('\n'.join(log)))


def _server_sudo(ctx: Ctx) -> List[Tuple[str, bool, str]]:
    """The server updates itself last: it needs the same two rights as a host (restart its service, reconcile)."""
    root = (ctx.deps.env.get('VPT_PROJECT_ROOT') or '/opt/virtualpytest').rstrip('/')
    probes = [('systemctl restart vpt-server', ['systemctl', 'restart', 'vpt-server']),
              ('vpt-reconcile-feature-units', priv.reconcile_argv(root))]
    rows = []
    for label, cmd in probes:
        try:
            res = ctx.deps.run(['sudo', '-n', '-l'] + cmd, 8)
            ok = res.returncode == 0
            detail = '' if ok else ((res.stderr or res.stdout or 'not allowed').strip().splitlines() or ['not allowed'])[-1][:200]
            if ok and cmd[0] == priv.HELPER and priv.helper_stale(root):
                ok, detail = False, priv.STALE
            rows.append((label, ok, detail))
        except Exception as exc:
            rows.append((label, False, f'{type(exc).__name__}: {exc}'[:200]))
    return rows


def _sudo_action(machine: str, root: str, reason: str) -> Dict[str, str]:
    return {'machine': machine, 'command': priv.install_command(root), 'reason': reason}


def check_host_sudo(ctx: Ctx) -> Dict[str, Any]:
    reports = ctx.host_reports()
    server_root = (ctx.deps.env.get('VPT_PROJECT_ROOT') or '/opt/virtualpytest').rstrip('/')
    log, bad, actions = [], [], []
    server_why = ''
    for label, ok, detail in _server_sudo(ctx):
        log.append(f'{"ok  " if ok else "FAIL"} this server: sudo -n {label} {detail}'.rstrip())
        if not ok and 'this server' not in bad:
            bad.append('this server')
            server_why = detail or f'sudo -n {label} is not allowed'
    if server_why:
        actions.append(_sudo_action('this server', server_root, server_why))
    for e in reports:
        if e not in _pull_capable(ctx):
            log.append(f'n/a  {e["name"]}: the host cannot report')
            bad.append(e['name'])
            continue
        sd = e['report'].get('sudo') or {}
        why = ''
        for key, label in (('restart', 'systemctl restart vpt-host'), ('reconcile', 'vpt-reconcile-feature-units')):
            item = sd.get(key) or {}
            log.append(f'{"ok  " if item.get("ok") else "FAIL"} {e["name"]}: sudo -n {label} {item.get("detail", "")}'.rstrip())
            if not item.get('ok') and e['name'] not in bad:
                bad.append(e['name'])
                why = item.get('detail') or f'sudo -n {label} is not allowed'
        if why:
            root = str(e['report'].get('project_root') or server_root).rstrip('/') or server_root
            actions.append(_sudo_action(e['name'], root, why))
    if bad:
        return _res('host_sudo', True, 'ko', f'sudo -n is not allowed on: {", ".join(bad)}.',
                    '\n'.join(log), 'Run the command shown for each machine as root on that machine (installs the sudoers drop-in and the reconcile helper; run it again after an update of the helper), see the guide.',
                    actions)
    return _res('host_sudo', True, 'ok', f'sudo -n works for the restart and the reconcile on this server and {len(reports)} hosts.', '\n'.join(log))


# -- 4 ---------------------------------------------------------------------------------------------
def check_database(ctx: Ctx) -> Dict[str, Any]:
    try:
        state, backend = ctx.deps.migration_status()
    except Exception as exc:
        # we cannot even read the tracker: the step could not run either way
        return _res('database', True, 'ko', f'Cannot read the migration tracker: {type(exc).__name__}: {str(exc)[:150]}',
                    mask(str(exc)), 'Platform update -> Settings -> Database connection (or PLATFORM_UPDATE_DB_URI in the server .env).')
    pending = len(state.get('pending') or [])
    needed = pending > 0 or state.get('tracker') == 'missing'
    log = [f'tracker: {state.get("tracker")}', f'migration files: {state.get("total")}, applied: {state.get("applied")}, pending: {pending}',
           f'connection string configured: {"yes" if backend.can_execute else "no"}']
    if state.get('tracker') == 'missing':
        return _res('database', needed, 'ko', 'The migration tracker table is missing.', '\n'.join(log),
                    'Create the tracker in step 4 (Migrations) once, then re-check.')
    if not backend.can_execute:
        if pending:
            return _res('database', True, 'ko', f'{pending} migrations are pending and no connection string is set.', '\n'.join(log),
                        'Platform update -> Settings -> Database connection (or PLATFORM_UPDATE_DB_URI in the server .env; see the guide).')
        return _res('database', False, 'ko', 'No connection string is set (needed only when migrations are pending).',
                    '\n'.join(log), 'Platform update -> Settings -> Database connection (or PLATFORM_UPDATE_DB_URI in the server .env; see the guide).')
    return _res('database', needed, 'ok', f'Connected; {pending} migrations pending.', '\n'.join(log))


# -- 5 ---------------------------------------------------------------------------------------------
def _bash_major(ctx: Ctx) -> Optional[int]:
    try:
        out = ctx.deps.run(['bash', '-c', 'echo ${BASH_VERSINFO[0]}'], 5).stdout.strip()
        return int(out)
    except Exception:
        return None


def _tools_action(machine: str, manager: str, missing: List[str]) -> List[Dict[str, str]]:
    """TASK-128 G10: ONE command for everything this machine lacks, with its own package manager. No button: installing
    needs root and the sudoers drop-in allows only restarts and the reconcile helper."""
    cmd = package_install.install_command(manager, missing)
    if not cmd:
        return []
    return [{'machine': machine, 'command': cmd, 'reason': f'{machine} lacks {", ".join(missing)}: install needs root, copy the line.'}]


def check_tools(ctx: Ctx) -> Dict[str, Any]:
    which = ctx.deps.which
    need = ['git', 'tar', 'rsync', 'python3'] + (['zip'] if ctx.fmt == 'zip' else [])
    log, bad, actions = [], [], []
    server_missing: List[str] = []
    for tool in need:
        found = tool == 'python3' and bool(sys.executable) or bool(which(tool))
        log.append(f'{"ok  " if found else "FAIL"} server: {tool}')
        if not found:
            bad.append(f'{tool} (server)')
            server_missing.append(tool)
    major = _bash_major(ctx)
    log.append(f'{"ok  " if major and major >= 4 else "FAIL"} server: bash {major if major is not None else "?"} (>= 4 needed)')
    if not major or major < 4:
        bad.append('bash >= 4 (server)')
        server_missing.append('bash')
    if server_missing:
        actions += _tools_action('this server', package_install.detect(which), server_missing)
    for e in ctx.host_reports():
        if _host_state(e) != 'ok':
            continue
        tools = e['report'].get('tools') or {}
        miss = tools.get('missing') or []
        log.append(f'{"FAIL" if miss else "ok  "} {e["name"]}: ' + (f'missing {", ".join(miss)}' if miss else 'rsync, tar, sudo, bash'))
        bad += [f'{m} ({e["name"]})' for m in miss]
        if miss:
            actions += _tools_action(e['name'], str(tools.get('pkg_manager') or ''), list(miss))
    if bad:
        return _res('tools', True, 'ko', f'Missing: {", ".join(bad)}.', '\n'.join(log),
                    'Install the missing tools with the package manager of each machine (the command is shown). Installing needs root.',
                    actions)
    return _res('tools', True, 'ok', 'All required tools are present.', '\n'.join(log))


def check_db_backup(ctx: Ctx) -> Dict[str, Any]:
    deps = ctx.deps.db_backup() if ctx.deps.db_backup else db_backup.Deps(env=ctx.deps.env)
    ok, detail, log = db_backup.prerequisite(deps)
    if ok:
        return _res('db_backup', True, 'ok', detail, log)
    return _res('db_backup', True, 'ko', detail, log, db_backup.FIX_AGENT)


# -- 6 ---------------------------------------------------------------------------------------------
def check_disk(ctx: Ctx) -> Dict[str, Any]:
    root = ctx.deps.build_root()
    probe = root
    while probe and not os.path.exists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    try:
        free = ctx.deps.disk_free(probe or '/')
    except OSError as exc:
        return _res('disk', True, 'ko', f'Cannot read the free space of {root}: {exc}', fix='Check the build folder exists and is readable.')
    log, bad = [f'{"ok  " if free >= MIN_SERVER_FREE else "FAIL"} server {root}: {_human(free)} free (need {_human(MIN_SERVER_FREE)})'], []
    if free < MIN_SERVER_FREE:
        bad.append('server')
    for e in ctx.host_reports():
        if _host_state(e) != 'ok':
            continue
        d = e['report'].get('disk') or {}
        log.append(f'{"ok  " if d.get("ok") else "FAIL"} {e["name"]}: project {_human(d.get("project_free"))}, '
                   f'backups {_human(d.get("backup_free"))} free (need {_human(d.get("need_backup"))} for one backup)')
        if not d.get('ok'):
            bad.append(e['name'])
    if bad:
        return _res('disk', True, 'ko', f'Not enough free disk on: {", ".join(bad)}.', '\n'.join(log),
                    'Free space (old backups under /var/tmp/virtualpytest_backups, old bundles) or enlarge the disk.')
    return _res('disk', True, 'ok', f'Server {_human(free)} free; hosts have room for a bundle and one backup.', '\n'.join(log))


# -- 9 ---------------------------------------------------------------------------------------------
def check_github(ctx: Ctx) -> Dict[str, Any]:
    need = ctx.core == 'github' or ctx.overlay == 'github'
    if not need:
        return _res('github', False, 'na', 'Neither the core nor the overlay comes from GitHub.')
    remote = (ctx.deps.core_remote() if ctx.deps.core_remote else
              (ctx.deps.env.get('VPT_CORE_REMOTE') or 'https://github.com/AngelStreetCorp/virtualpytest.git').strip())
    token = (ctx.deps.github_token() if ctx.deps.github_token else
             settings.get('github_token', ctx.deps.env))
    # Basic auth through askpass (user x-access-token), never `-c http.extraHeader` (argv shows in ps, and
    # GitHub git-over-HTTPS does not take Bearer). A token is only offered to github.com.
    argv = ['git', 'ls-remote', '--exit-code', '--heads', remote, 'HEAD']
    try:
        with git_auth.askpass_env(token if git_auth.is_github_url(remote) else '') as env:
            res = ctx.deps.run(argv, 9, env)
        ok = res.returncode in (0, 2) and 'fatal' not in (res.stderr or '')  # 2 = reachable, no such ref
        out = ((res.stdout or '') + (res.stderr or '')).strip()
    except subprocess.TimeoutExpired:
        ok, out = False, 'timed out'
    except Exception as exc:
        ok, out = False, f'{type(exc).__name__}: {exc}'
    log = mask(f'git ls-remote {remote}\n{out[-400:]}', [token])
    if ok:
        return _res('github', True, 'ok', f'{remote} answers.', log)
    return _res('github', True, 'ko', f'{remote} is not reachable.', log,
                'Open outbound HTTPS to github.com from the server, or set VPT_CORE_REMOTE to your mirror; a private repo needs VPT_GITHUB_TOKEN.')


# -- 10 --------------------------------------------------------------------------------------------
def check_gitlab(ctx: Ctx) -> Dict[str, Any]:
    if ctx.overlay != 'gitlab':
        return _res('gitlab', False, 'na', 'The overlay does not come from GitLab.')
    if ctx.deps.gitlab_credentials:
        base, token = ctx.deps.gitlab_credentials()
    else:
        from . import bundle_jobs
        base, token = bundle_jobs.gitlab_credentials()
    if not (base and token):
        return _res('gitlab', True, 'ko', 'No GitLab instance with a token is configured on this server.',
                    fix='Add the GitLab instance and its token in Settings -> GitLab (see the guide).')
    url = f'{base.rstrip("/")}/api/v4/version'
    try:
        resp = ctx.deps.http_get(url, {'PRIVATE-TOKEN': token}, 9)
        status = getattr(resp, 'status_code', 0)
        body = resp.json() if status == 200 else {}
    except Exception as exc:
        return _res('gitlab', True, 'ko', f'{base} does not answer.', mask(f'GET {url}\n{type(exc).__name__}: {exc}', [token]),
                    'Check the instance URL and that the server can reach it.')
    log = mask(f'GET {url} -> HTTP {status}', [token])
    if status == 200:
        return _res('gitlab', True, 'ok', f'{base} answers (GitLab {body.get("version", "?")}).', log)
    if status in (401, 403):
        return _res('gitlab', True, 'ko', f'{base} refuses the token (HTTP {status}).', log,
                    'Create a new token with read_api and read_repository and save it in Settings -> GitLab.')
    return _res('gitlab', True, 'ko', f'{base} answered HTTP {status}.', log, 'Check the instance URL in Settings -> GitLab.')


# -- 11 --------------------------------------------------------------------------------------------
def check_no_test_running(ctx: Ctx) -> Dict[str, Any]:
    locks = ctx.deps.locks() or {}
    busy = {k: v for k, v in locks.items() if (v or {}).get('owner_type') != 'manual_control'}
    manual = len(locks) - len(busy)
    log = '\n'.join(f'{k}: {v.get("owner_type")} {v.get("lock_reason") or ""}'.rstrip() for k, v in busy.items())
    if busy:
        return _res('no_test_running', False, 'ko', f'{len(busy)} device(s) are busy with a run: an update restarts the hosts under them.',
                    log, 'Wait for the runs to end or stop them; pause queued runs in your scheduler.')
    return _res('no_test_running', False, 'ok', 'No run in progress' + (f' ({manual} manual take-control sessions open).' if manual else '.'), log)


CHECKS: Dict[str, Callable[[Ctx], Dict[str, Any]]] = {
    'frontend_ssh': check_frontend_ssh, 'hosts_api': check_hosts_api, 'hosts_download': check_hosts_download,
    'database': check_database, 'db_backup': check_db_backup, 'tools': check_tools, 'disk': check_disk, 'host_sudo': check_host_sudo,
    'host_version': check_host_version, 'github': check_github, 'gitlab': check_gitlab,
    'no_test_running': check_no_test_running,
}


def _guarded(cid: str, ctx: Ctx) -> Dict[str, Any]:
    try:
        return CHECKS[cid](ctx)
    except Exception as exc:
        return _res(cid, cid != 'no_test_running', 'ko', f'The check failed: {type(exc).__name__}: {str(exc)[:200]}',
                    mask(f'{type(exc).__name__}: {exc}'), 'Re-check; if it keeps failing, read the server log.')


def summarize(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = not any(c['required'] and c['status'] == 'ko' for c in checks)
    applicable = [c for c in checks if c['status'] != 'na']
    return {'ok': ok, 'passed': len([c for c in applicable if c['status'] == 'ok']), 'total': len(applicable)}


def run_all(core: str = 'github', overlay: str = 'none', deps: Optional[Deps] = None, fmt: str = 'zip',
            timeout: float = CHECK_TIMEOUT) -> Dict[str, Any]:
    core = core if core in ('github', 'zip') else 'github'
    overlay = overlay if overlay in ('gitlab', 'github', 'zip', 'none') else 'none'
    ctx = Ctx(core, overlay, deps or Deps(), 'tar.gz' if fmt == 'tar.gz' else 'zip')
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(ORDER))
    futures = {cid: pool.submit(_guarded, cid, ctx) for cid in ORDER}
    checks = []
    t0 = time.monotonic()
    for cid in ORDER:
        try:  # every check started together, so they all share one window
            checks.append(futures[cid].result(timeout=max(0.01, t0 + timeout - time.monotonic())))
        except concurrent.futures.TimeoutError:
            checks.append(_res(cid, cid != 'no_test_running', 'ko', f'Timed out after {int(timeout)} s.', '',
                               'Re-check; if it keeps timing out, the machine or network is too slow or blocked.'))
    pool.shutdown(wait=False)
    return {'core': core, 'overlay': overlay, **summarize(checks), 'checks': checks}
