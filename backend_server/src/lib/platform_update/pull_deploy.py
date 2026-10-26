"""
Pull deploy of Platform update step 3 (TASK-101): the server conducts, nothing depends on the proxmox node.

Order, and why:

  1. extract the bundle once on the server (safe extraction, ``bundle_archive``);
  2. the frontend VM over SSH when FRONTEND_DEPLOY_HOST is a host (rsync of the extracted tree to a staging folder, the bundle's own
     ``code-deploy.sh`` there, ``ensure_dist.sh`` build, restart). First: a UI that is a version ahead of the
     API is harmless, and nothing else depends on it. ``FRONTEND_DEPLOY_HOST=local`` means the frontend runs
     on the server VM: it is built and restarted right after the server tree is the new one;
     ``none`` skips it;
  3. every host, one at a time, through ``POST /host/system/applyBundle`` (the host pulls the archive from this
     server). It stops at the first failure so a bad bundle never reaches the whole fleet;
  4. the server itself LAST: backup, sync from the extracted tree, reconcile, schedule its own restart. The
     restart kills the job's own process, so the step is left ``running`` with job state
     ``awaiting_confirmation`` (recover_interrupted ignores it) and the operator confirms after the restart
     (``confirm``): that checks the server process started after the restart was scheduled and the running
     VERSION.txt is the bundle's.

Pause / abort (TASK-128 G12): the loop reads the run's control flags at SAFE POINTS only, before each machine
(``safe_point``), never mid-machine. Every machine it touched is recorded in the step data (``updated``, with the backup
it can be restored from) for the roll back (``rollback.py``).

Every machine's phases are written to the run log as ``VPT_PROGRESS`` lines (the host's own, relayed, plus the
server's for the machines it drives), so the TASK-99 cards show this deploy unchanged.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from shared.src.lib.utils import bundle_archive as ba
from shared.src.lib.utils import update_privileges as priv

from . import before_versions, bundle_jobs, frontend_ssh, prerequisites
from .deployment import build_view, timing_summary
from .runs import PlatformUpdateError, RunStore, require_backup

DEPLOY_STEP = bundle_jobs.DEPLOY_STEP
BUILD_STEP = bundle_jobs.BUILD_STEP
ARCHIVE_PATH = '/server/platform-update/bundle/{run_id}/archive'
PROCESS_START = time.time()
APPLY_TIMEOUT = 1800
PAUSE_POLL_SECONDS = 2
BACKUP_DIR_RE = re.compile(r'^BACKUP_DIR=(\S+)\s*$', re.M)


class DeployAborted(PlatformUpdateError):
    code = 409


def project_root() -> str:
    return os.getenv('VPT_PROJECT_ROOT', '/opt/virtualpytest')


def progress(host: str, role: str, phase: str, state: str, detail: str = '') -> str:
    from datetime import datetime, timezone
    return 'VPT_PROGRESS ' + json.dumps({
        'host': host, 'role': role, 'phase': phase, 'state': state, 'detail': detail[:300],
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}, ensure_ascii=True)


def read_version(root: str) -> str:
    for name in ('VERSION.txt', 'version'):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as fh:
                return fh.readline().strip() or 'unknown'
    return 'unknown'


class Env:
    """Everything the deploy touches on other machines or the OS; tests replace it."""

    def __init__(self):
        self.run: Callable = lambda argv, timeout, env=None: subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False, env={**os.environ, **(env or {})})
        self.hosts: Callable[[], List[dict]] = prerequisites._hosts
        self.call_host: Callable = lambda host, ep, method='POST', data=None, timeout=60: _call_host(host, ep, method, data, timeout)
        self.backup: Callable = _server_backup
        self.schedule_restart: Callable[[], None] = _schedule_server_restart
        self.sleep: Callable[[float], None] = time.sleep
        self.server_name: Callable[[], str] = lambda: os.getenv('HOST_NAME') or socket.gethostname()
        self.frontend_cfg: Callable[[], Dict[str, str]] = lambda: frontend_ssh.config()


def _call_host(host, endpoint, method, data, timeout):
    from shared.src.lib.utils.build_url_utils import call_host
    return call_host(host, endpoint, method=method, data=data, timeout=timeout)


def _server_backup(target: str, root: str):
    from backend_server.src.routes import server_system_routes as sysr
    result = sysr._create_backup_snapshot(target, root, reason='platform-update-bundle')
    sysr._prune_backup_entries(root, 5)
    return result


def _server_backup_root() -> str:
    from backend_server.src.routes import server_system_routes as sysr
    return sysr.SERVER_BACKUP_ROOT


def _schedule_server_restart() -> None:
    from backend_server.src.routes import server_system_routes as sysr
    sysr._schedule_server_restart()


# -- gate ------------------------------------------------------------------------------------------
def spec_of_run(store: RunStore, run_id: str) -> Dict[str, str]:
    spec = (store.get(run_id)['steps'][BUILD_STEP]['data'].get('spec') or {})
    return {'core': spec.get('core') or 'github', 'overlay': spec.get('overlay') or 'none'}


def gate(store: RunStore, run_id: str, deps: Optional[prerequisites.Deps] = None) -> Dict[str, Any]:
    """Refuse (PlatformUpdateError) while a required prerequisite is KO. -> the prerequisites result."""
    spec = spec_of_run(store, run_id)
    result = prerequisites.run_all(spec['core'], spec['overlay'], deps)
    if not result['ok']:
        bad = [c['title'] for c in result['checks'] if c['required'] and c['status'] == 'ko']
        raise PlatformUpdateError('prerequisites not met: ' + '; '.join(bad) + '. Fix them (Prerequisites badge), then deploy.')
    return result


# -- the frontend VM ---------------------------------------------------------------------------------
def deploy_frontend(env: Env, tree: str, log: Callable[[str], None],
                    on_backup: Optional[Callable[[str], None]] = None) -> None:
    cfg = env.frontend_cfg()
    host = cfg['host']
    secrets, child = frontend_ssh.secrets(cfg), frontend_ssh.child_env(cfg)

    def mask(text: str) -> str:
        return prerequisites.mask(text, secrets)

    def step(phase: str, label: str, argv: List[str], timeout: int) -> str:
        log(progress(host, 'frontend', phase, 'start', label))
        try:
            res = env.run(argv, timeout, child)
        except Exception as exc:
            log(progress(host, 'frontend', phase, 'failed', f'{label}: {type(exc).__name__}'))
            raise PlatformUpdateError(f'frontend {label} failed: {type(exc).__name__}: {mask(str(exc))[:200]}')
        out = mask(((res.stdout or '') + (res.stderr or '')).strip())
        for line in out.splitlines()[-12:]:
            log(f'[{host}] {line}')
        if res.returncode != 0:
            log(progress(host, 'frontend', phase, 'failed', f'{label} exited {res.returncode}'))
            raise PlatformUpdateError(f'frontend {label} failed (exit {res.returncode}): {out[-200:]}')
        log(progress(host, 'frontend', phase, 'ok', label))
        return out

    target, staging = cfg['target_dir'], frontend_ssh.STAGING_DIR
    step('rsync', 'push the bundle to the frontend VM', frontend_ssh.rsync_argv(cfg, tree, list(ba.RSYNC_EXCLUDES)), 1800)
    deploy_cmd = (f'VPT_SOURCE_DIR={staging} VPT_TARGET_DIR={target} VPT_BACKUP_ROOT={cfg["backup_root"]} VPT_KEEP_BACKUPS=5 '
                  f'VPT_DRY_RUN=0 VPT_TARGET_KIND=frontend VPT_RESTART_ENABLED=0 bash {staging}/scripts/code-deploy.sh')
    out = step('rsync', 'back up and sync the frontend tree',
               frontend_ssh.ssh_argv(cfg, frontend_ssh.as_service_user(cfg, deploy_cmd)), 1800)
    found = BACKUP_DIR_RE.findall(out)          # code-deploy.sh prints where it kept the pre-sync tree (rolled back from there)
    if found and on_backup:
        on_backup(found[-1])
    step('install', 'build the frontend (the live bundle stays served)',
         frontend_ssh.ssh_argv(cfg, frontend_ssh.as_service_user(cfg, f'bash {target}/frontend/scripts/ensure_dist.sh')), 1800)
    step('restart', f'restart {cfg["service"]}',
         frontend_ssh.ssh_argv(cfg, frontend_ssh.sudo(cfg, f'systemctl restart {cfg["service"]}')), 120)
    step('health', f'{cfg["service"]} is active',
         frontend_ssh.ssh_argv(cfg, f'systemctl is-active {cfg["service"]}'), 60)


# -- hosts -------------------------------------------------------------------------------------------
def deploy_host(env: Env, host: dict, run_id: str, sha256: str, log: Callable[[str], None],
                wait_seconds: int = 120) -> Dict[str, Any]:
    name = str(host.get('host_name') or host.get('name') or '?')
    body, status = env.call_host(host, '/host/system/applyBundle', 'POST',
                                 {'url': ARCHIVE_PATH.format(run_id=run_id), 'sha256': sha256}, APPLY_TIMEOUT + 30)
    body = body if isinstance(body, dict) else {}
    for line in body.get('progress') or []:
        if '"phase": "health"' in line:
            continue  # the host cannot see its own restart: the server reports health below
        log(line)
    for line in body.get('log') or []:
        log(f'[{name}] {line}')
    if status != 200 or not body.get('success'):
        why = body.get('error') or f'HTTP {status}'
        if not body.get('progress'):
            log(progress(name, 'host', 'rsync', 'failed', str(why)))
        return {'host': name, 'ok': False, 'detail': str(why)[:300], 'backup_id': body.get('backup_id')}
    log(progress(name, 'host', 'health', 'start', 'waiting for the restart'))
    env.sleep(6)
    deadline = time.monotonic() + wait_seconds
    while True:
        _b, st = env.call_host(host, '/host/system/health', 'GET', None, 5)
        if st == 200:
            log(progress(name, 'host', 'health', 'ok', f'version {body.get("version_after", "?")}'))
            return {'host': name, 'ok': True, 'detail': f'{body.get("version_before")} -> {body.get("version_after")}',
                    'backup_id': body.get('backup_id'), 'warnings': body.get('warnings') or []}
        if time.monotonic() > deadline:
            log(progress(name, 'host', 'health', 'failed', f'no answer {wait_seconds}s after the restart'))
            return {'host': name, 'ok': False, 'detail': 'the host did not come back after the restart',
                    'backup_id': body.get('backup_id')}
        env.sleep(3)


# -- the server itself -------------------------------------------------------------------------------
def deploy_server(env: Env, tree: str, log: Callable[[str], None],
                  on_backup: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    name, root = env.server_name(), project_root()
    log(progress(name, 'server', 'rsync', 'start', 'back up and sync'))
    try:
        backup_dir, meta = env.backup(root, _server_backup_root())
        if on_backup:
            on_backup((meta or {}).get('backup_id') or os.path.basename(str(backup_dir)))
        res = env.run(ba.rsync_command(tree, root), 1800)
        if res.returncode != 0:
            raise PlatformUpdateError(f'rsync failed (the backup can restore): {(res.stderr or res.stdout)[-300:]}')
    except PlatformUpdateError as exc:
        log(progress(name, 'server', 'rsync', 'failed', str(exc)))
        raise
    except Exception as exc:
        log(progress(name, 'server', 'rsync', 'failed', f'{type(exc).__name__}: {exc}'))
        raise PlatformUpdateError(f'server sync failed: {type(exc).__name__}: {str(exc)[:200]}')
    log(progress(name, 'server', 'rsync', 'ok', f'backup {(meta or {}).get("backup_id") or os.path.basename(str(backup_dir))}'))
    log(progress(name, 'server', 'install', 'start', 'feature units'))
    rec = env.run(['sudo', '-n'] + priv.reconcile_argv(root), 300)
    log(progress(name, 'server', 'install', 'ok' if rec.returncode == 0 else 'failed',
                 'feature units' if rec.returncode == 0 else f'reconcile failed (update not rolled back): {(rec.stderr or rec.stdout)[-150:]}'))
    return {'backup_id': (meta or {}).get('backup_id'), 'name': name}


def deploy_frontend_local(env: Env, cfg: Dict[str, str], log: Callable[[str], None]) -> None:
    """FRONTEND_DEPLOY_HOST=local: the frontend runs on this server VM. Build it from the (already updated)
    server tree, then restart its unit through the sudoers drop-in. A failure stops the deploy: a frontend
    that silently stays old is the defect this mode exists to remove."""
    name, root, svc = env.server_name(), project_root(), cfg['service']
    steps = [
        ('install', 'build the frontend (the live bundle stays served)', ['bash', os.path.join(root, 'frontend/scripts/ensure_dist.sh')], 1800),
        ('restart', f'restart {svc}', ['sudo', '-n', 'systemctl', 'restart', svc], 120),
        ('health', f'{svc} is active', ['systemctl', 'is-active', svc], 60),
    ]
    for phase, label, argv, timeout in steps:
        log(progress(name, 'frontend', phase, 'start', label))
        try:
            res = env.run(argv, timeout)
        except Exception as exc:
            log(progress(name, 'frontend', phase, 'failed', f'{label}: {type(exc).__name__}'))
            raise PlatformUpdateError(f'frontend {label} failed: {type(exc).__name__}: {str(exc)[:200]}')
        out = ((res.stdout or '') + (res.stderr or '')).strip()
        for line in out.splitlines()[-12:]:
            log(f'[{name}] {line}')
        if res.returncode != 0:
            log(progress(name, 'frontend', phase, 'failed', f'{label} exited {res.returncode}'))
            raise PlatformUpdateError(f'frontend {label} failed on the server (exit {res.returncode}): {out[-200:]}. '
                                      f'The server tree is already the new one; fix it and re-run, or rebuild the frontend by hand.')
        log(progress(name, 'frontend', phase, 'ok', label))


# -- pause / abort / what was touched (TASK-128 G12) -------------------------------------------------
def record_updated(store: RunStore, run_id: str, role: str, name: str, backup: Optional[str] = None,
                   ok: Optional[bool] = None) -> None:
    """Remember a machine the deploy touched (newest last) and the backup it can be restored from."""
    with store._lock:
        data = store.get(run_id)['steps'][DEPLOY_STEP]['data']
        updated = [dict(u) for u in data.get('updated') or []]
        entry = next((u for u in updated if u['role'] == role and u['name'] == name), None)
        if entry is None:
            entry = {'role': role, 'name': name, 'backup': None, 'ok': False}
            updated.append(entry)
        if backup and not entry['backup']:
            entry['backup'] = backup          # the FIRST backup wins: a re-run after a failure must not replace it with a half-updated tree
        if ok is not None:
            entry['ok'] = ok
        store.set_data(run_id, DEPLOY_STEP, {'updated': updated})


def set_job_state(store: RunStore, run_id: str, state: str) -> None:
    job = dict(store.get(run_id)['steps'][DEPLOY_STEP]['data'].get('job') or {})
    job['state'] = state
    store.set_data(run_id, DEPLOY_STEP, {'job': job})


def safe_point(store: RunStore, run_id: str, env: Env, before: str, log: Callable[[str], None]) -> None:
    """Called BEFORE each machine, never inside one. ``abort`` raises ``DeployAborted``; ``pause`` waits here (job state
    ``paused``) until resumed or aborted."""
    paused = False
    while True:
        control = store.control(run_id)
        if control.get('abort'):
            raise DeployAborted(f'Aborted by {control.get("by") or "the operator"} before {before}. Nothing was changed on {before} '
                                f'or on the machines after it; the machines already updated stay on the new version until you roll back.')
        if control.get('pause'):
            if not paused:
                paused = True
                set_job_state(store, run_id, 'paused')
                log(f'Paused before {before} (no machine is being updated); waiting for Resume or Abort')
            env.sleep(PAUSE_POLL_SECONDS)
            continue
        if paused:
            set_job_state(store, run_id, 'running')
            log(f'Resumed: continuing with {before}')
        return


# -- orchestration -----------------------------------------------------------------------------------
def run_pull(store: RunStore, run_id: str, archive: str, sha256: str, env: Env) -> None:
    log = lambda line: store.log(run_id, line, DEPLOY_STEP)  # noqa: E731
    hosts_result: List[Dict[str, Any]] = []
    try:
        tree_dir = store.dir / 'bundles' / run_id / 'extracted'
        shutil.rmtree(tree_dir, ignore_errors=True)
        tree = ba.safe_extract(archive, str(tree_dir))
        expected = read_version(tree)
        store.set_data(run_id, DEPLOY_STEP, {'expected_version': expected})
        log(f'Extracted bundle version {expected} on the server')

        cfg = env.frontend_cfg()
        if cfg['mode'] == 'ssh':
            safe_point(store, run_id, env, f'the frontend VM {cfg["host"]}', log)
            record_updated(store, run_id, 'frontend', cfg['host'])
            deploy_frontend(env, tree, log, lambda bk: record_updated(store, run_id, 'frontend', cfg['host'], backup=bk))
            record_updated(store, run_id, 'frontend', cfg['host'], ok=True)
        elif cfg['mode'] == 'local':
            log('Frontend runs on the server VM (FRONTEND_DEPLOY_HOST=local): built after the server tree is updated')
        elif cfg['mode'] == 'none':
            log('No frontend to update (FRONTEND_DEPLOY_HOST=none): skipped')
        else:
            raise PlatformUpdateError('FRONTEND_DEPLOY_HOST is not set (a host, local or none): the frontend would silently stay old')

        for host in env.hosts():
            hname = str(host.get('host_name') or host.get('name') or '?')
            safe_point(store, run_id, env, f'host {hname}', log)
            result = deploy_host(env, host, run_id, sha256, log)
            hosts_result.append(result)
            if result.get('backup_id'):
                record_updated(store, run_id, 'host', result['host'], backup=result['backup_id'], ok=bool(result['ok']))
            if not result['ok']:
                raise PlatformUpdateError(
                    f'{result["host"]}: {result["detail"]}. Stopped before the remaining machines and the server; '
                    f'the host keeps its backup (Roll back restores it).')
        store.set_data(run_id, DEPLOY_STEP, {'hosts': hosts_result})

        safe_point(store, run_id, env, f'the server {env.server_name()}', log)
        name = env.server_name()
        record_updated(store, run_id, 'server', name)
        info = deploy_server(env, tree, log, lambda bk: record_updated(store, run_id, 'server', name, backup=bk))
        record_updated(store, run_id, 'server', name, ok=True)
        if cfg['mode'] == 'local':
            deploy_frontend_local(env, cfg, log)
        store.set_data(run_id, DEPLOY_STEP, {
            'job': {'state': 'awaiting_confirmation', 'mode': 'pull', 'restart_scheduled_at': time.time()},
            'server_backup': info.get('backup_id')})
        log('Server tree updated; vpt-server restarts in a few seconds. Confirm this step after it is back.')
        env.schedule_restart()
        log(progress(info['name'], 'server', 'restart', 'start', 'vpt-server (scheduled)'))
    except Exception as exc:
        try:
            aborted = isinstance(exc, DeployAborted)
            msg = str(exc) if isinstance(exc, (PlatformUpdateError, ba.BundleError)) else f'pull deploy error: {type(exc).__name__}: {exc}'
            log(msg[:300])
            store.finish_step(run_id, DEPLOY_STEP, False, msg[:500],
                              {'job': {'state': 'aborted' if aborted else 'failed', 'mode': 'pull'}, 'hosts': hosts_result,
                               'aborted': aborted})
        except PlatformUpdateError:
            pass
    finally:
        bundle_jobs._release('deploy')


def start(store: RunStore, run_id: str, data: Dict[str, Any], threaded: bool = True, env: Optional[Env] = None,
          deps: Optional[prerequisites.Deps] = None) -> None:
    run = store.get(run_id)
    bundle = run['steps'][BUILD_STEP]['data'].get('bundle') or {}
    archive, sha256 = bundle.get('path') or '', (bundle.get('sha256') or '').lower()
    if run['steps'][BUILD_STEP]['state'] != 'done' or not archive:
        raise PlatformUpdateError('build the bundle in step 2 first')
    if not os.path.isfile(archive):
        raise PlatformUpdateError('the built archive is gone from this server; build it again')
    if not re.fullmatch(r'[0-9a-f]{64}', sha256):
        sha256 = ba.sha256_file(archive)
    if run['steps'][DEPLOY_STEP]['state'] == 'running':
        raise PlatformUpdateError('the deploy is already running or awaiting confirmation')
    require_backup(run)
    gate(store, run_id, deps)
    env = env or Env()
    bundle_jobs._claim('deploy', run_id)
    try:
        store.begin_step(run_id, DEPLOY_STEP)
        store.clear_control(run_id)
        store.set_data(run_id, DEPLOY_STEP, {'job': {'state': 'running', 'mode': 'pull', 'archive': bundle.get('name', '')},
                                             'aborted': False, 'rollback': None, 'partial': None, 'rolled_back': False})
        store.log(run_id, f'Pull deploy of {bundle.get("name", "")} (sha256 {sha256[:12]}): frontend, hosts, then the server', DEPLOY_STEP)
        before_versions.capture_for_deploy(store, run_id, project_root(), env.hosts, data.get('frontend_version'))
    except Exception:
        bundle_jobs._release('deploy')
        raise
    target = lambda: run_pull(store, run_id, archive, sha256, env)  # noqa: E731
    if threaded:
        threading.Thread(target=target, name=f'bundle-pull-{run_id}', daemon=True).start()
    else:
        target()


def confirm(store: RunStore, run_id: str, log: Callable[[str], None]) -> None:
    """After the server restarted: prove the new code is running, then close step 3."""
    step = store.get(run_id)['steps'][DEPLOY_STEP]
    job = step['data'].get('job') or {}
    if job.get('state') != 'awaiting_confirmation':
        raise PlatformUpdateError('nothing to confirm: this step is not waiting for the server restart')
    scheduled = float(job.get('restart_scheduled_at') or 0)
    if PROCESS_START <= scheduled:
        raise PlatformUpdateError('the server has not restarted yet (the same process is still running); wait a few seconds and confirm again')
    running, expected = read_version(project_root()), step['data'].get('expected_version') or ''
    if expected and running != expected:
        raise PlatformUpdateError(f'the server restarted but reports version {running}, the bundle is {expected}: check the server log')
    log(f'Server restarted and runs version {running}')
    view = build_view(store.log_lines(run_id, tail=10_000_000))
    store.finish_step(run_id, DEPLOY_STEP, True, f'version {running}',
                      {'job': {'state': 'done', 'mode': 'pull'}, 'timings': timing_summary(view)})
