"""
Host side of the pull update (TASK-101): ``POST /host/system/applyBundle`` and ``GET /host/system/updatePrereqs``.

The route file wires the real backup, restart and lock helpers into these functions; everything here takes
its collaborators as arguments so it is tested with real temp directories and a mocked download.

``apply_bundle`` runs the phases the TASK-99 cards know, and returns them as ``VPT_PROGRESS`` lines
(``setup/proxmox/node/lib/deploy_progress.py`` format) for the server to copy into the run log:

  rsync    download + sha256 + extract + backup + sync into the project root
  install  reconcile the feature systemd units (best effort, like update_core.sh)
  restart  the host service restart is scheduled (it kills the request, so the reply goes out first)
  health   skipped here; the server checks /host/system/health afterwards

What is never touched: the same list update_core.sh excludes (``.env``, venv, node_modules, the host's
own config/user data, the customer frontend config), so a host keeps its identity across an update.
"""

import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from shared.src.lib.utils import bundle_archive as ba
from shared.src.lib.utils import package_install
from shared.src.lib.utils import update_privileges as priv

SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
MAX_BUNDLE_BYTES = 2 * 1024 ** 3
MIN_FREE_BYTES = 1024 ** 3
KEEP_BACKUPS = 5

RSYNC_EXCLUDES = ba.RSYNC_EXCLUDES


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def progress_line(host: str, phase: str, state: str, detail: str = '', role: str = 'host') -> str:
    return 'VPT_PROGRESS ' + json.dumps({'host': host, 'role': role, 'phase': phase, 'state': state,
                                         'ts': utc_now(), 'detail': detail[:300]}, ensure_ascii=True)


def read_version(root: str) -> str:
    for name in ('VERSION.txt', 'version'):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    return fh.readline().strip() or 'unknown'
            except OSError:
                pass
    return 'unknown'


class ApplyError(Exception):
    pass


# -- url -----------------------------------------------------------------------------------------
def resolve_download_url(url: str, server_url: str) -> str:
    """The URL this host may fetch: a path on its own ``SERVER_URL``, or an absolute URL on the same origin.
    Anything else is refused, so the service key (sent as X-API-Key) can never go to another machine."""
    url = (url or '').strip()
    base = urlparse(server_url)
    if not base.scheme or not base.netloc:
        raise ApplyError('SERVER_URL is not configured on this host')
    if url.startswith('/') and not url.startswith('//'):
        return f'{server_url.rstrip("/")}{url}'
    parsed = urlparse(url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ApplyError('the download URL is not on this host\'s server (SERVER_URL); refusing to send the key elsewhere')
    return url


def _sniff_suffix(path: str) -> str:
    with open(path, 'rb') as fh:
        head = fh.read(4)
    if head[:2] == b'PK':
        return '.zip'
    if head[:2] == b'\x1f\x8b':
        return '.tar.gz'
    raise ApplyError('the download is neither a zip nor a tar.gz')


# -- sync ----------------------------------------------------------------------------------------
rsync_command = ba.rsync_command


def _run(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)


def reconcile_command(project_root: str) -> List[str]:
    return ['sudo', '-n'] + priv.reconcile_argv(project_root)


def apply_bundle(
    *, project_root: str, backup_root: str, url: str, sha256: str, host_name: str, server_url: str,
    headers: Dict[str, str], backup_fn: Callable[[str, str, str], Any], prune_fn: Callable[[str, int], None],
    restart_fn: Callable[[], None], work_root: Optional[str] = None,
    get: Optional[Callable] = None, run: Callable = _run, max_bytes: int = MAX_BUNDLE_BYTES,
) -> Dict[str, Any]:
    """Pull, verify, back up, extract, sync, reconcile, schedule the restart. Never raises:
    the result carries ``success``, ``error`` and the ``progress`` lines."""
    lines: List[str] = []
    log: List[str] = []
    result: Dict[str, Any] = {'success': False, 'progress': lines, 'log': log, 'restart_scheduled': False,
                              'warnings': []}

    def emit(phase: str, state: str, detail: str = '') -> None:
        lines.append(progress_line(host_name, phase, state, detail))

    sha256 = (sha256 or '').strip().lower()
    version_before = read_version(project_root)
    result['version_before'] = version_before
    workdir = None
    emit('rsync', 'start', 'download')
    try:
        if not SHA256_RE.match(sha256):
            raise ApplyError('sha256 must be 64 hex characters')
        if not os.path.isdir(project_root):
            raise ApplyError(f'project root not found: {project_root}')
        full_url = resolve_download_url(url, server_url)
        workdir = tempfile.mkdtemp(prefix='vpt-bundle-', dir=work_root or os.path.dirname(backup_root.rstrip('/')) or '/var/tmp')
        part = os.path.join(workdir, 'bundle.part')
        actual = ba.download(full_url, part, headers=headers, max_bytes=max_bytes, get=get)
        if not hmac.compare_digest(actual, sha256):
            raise ApplyError(f'sha256 mismatch: expected {sha256[:12]}..., got {actual[:12]}...')
        log.append(f'downloaded and verified sha256 {actual[:12]}')
        archive = part.replace('.part', _sniff_suffix(part))
        os.replace(part, archive)
        tree = ba.safe_extract(archive, os.path.join(workdir, 'x'))
        version_after = read_version(tree)
        log.append(f'extracted bundle version {version_after}')
        try:
            backup_dir, meta = backup_fn(project_root, backup_root, 'pre_bundle')
            prune_fn(backup_root, KEEP_BACKUPS)
        except Exception as exc:
            raise ApplyError(f'backup failed, nothing was changed: {exc}')
        result['backup_path'] = backup_dir
        result['backup_id'] = (meta or {}).get('backup_id') or os.path.basename(str(backup_dir))
        log.append(f'backup {result["backup_id"]}')
        sync = run(rsync_command(tree, project_root), 1800)
        if sync.returncode != 0:
            raise ApplyError(f'rsync failed (the backup {result["backup_id"]} can restore): {(sync.stderr or sync.stdout)[-300:]}')
        result['version_after'] = read_version(project_root)
        emit('rsync', 'ok', f'{version_before} -> {result["version_after"]}')
    except (ApplyError, ba.BundleError) as exc:
        result['error'] = str(exc)
        emit('rsync', 'failed', str(exc))
        return result
    except Exception as exc:  # a host must answer, not crash the route
        result['error'] = f'{type(exc).__name__}: {exc}'[:300]
        emit('rsync', 'failed', result['error'])
        return result
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    emit('install', 'start', 'feature units')
    try:
        rec = run(reconcile_command(project_root), 300)
        if rec.returncode == 0:
            emit('install', 'ok', 'feature units')
        else:
            detail = (rec.stderr or rec.stdout or '').strip()[-200:]
            emit('install', 'failed', f'feature unit reconcile failed (update not rolled back): {detail}')
            result['warnings'].append('reconcile failed: ' + detail)
    except Exception as exc:
        emit('install', 'failed', f'feature unit reconcile could not run: {exc}')
        result['warnings'].append(f'reconcile could not run: {exc}')

    emit('restart', 'start', 'vpt-host')
    try:
        restart_fn()
        result['restart_scheduled'] = True
        emit('restart', 'ok', 'vpt-host restart scheduled')
    except Exception as exc:
        emit('restart', 'failed', str(exc))
        result['warnings'].append(f'restart could not be scheduled: {exc}')
    emit('health', 'skipped', 'checked by the server after the restart')
    result['success'] = result['restart_scheduled']
    if not result['success']:
        result['error'] = 'the code is updated but the host service restart could not be scheduled'
    return result


# -- roll back (TASK-128 G12) --------------------------------------------------------------------
BACKUP_ID_RE = re.compile(r'^\d{8}_\d{6}(_\d{6})?$')
BACKUP_META_FILENAME = '.vpt-backup-meta.json'


def resolve_backup(backup_root: str, backup_id: str) -> str:
    """The backup folder ``applyBundle`` made, by id. Fixed shape + must be a direct child of the backup root: the
    server can only name a backup, never a path."""
    backup_id = (backup_id or '').strip()
    if not BACKUP_ID_RE.match(backup_id):
        raise ApplyError('backup_id is not a backup id')
    root = os.path.realpath(backup_root)
    path = os.path.realpath(os.path.join(root, backup_id))
    if os.path.dirname(path) != root or not os.path.isdir(path):
        raise ApplyError(f'backup {backup_id} not found on this host')
    try:
        with open(os.path.join(path, BACKUP_META_FILENAME), encoding='utf-8') as fh:
            reason = (json.load(fh) or {}).get('reason')
    except (OSError, ValueError):
        reason = None
    if reason != 'pre_bundle':
        raise ApplyError(f'backup {backup_id} is not a pre-update backup (reason: {reason or "unknown"}); refusing to restore it')
    return path


def rollback_bundle(
    *, project_root: str, backup_root: str, backup_id: str, host_name: str,
    backup_fn: Callable[[str, str, str], Any], restart_fn: Callable[[], None], run: Callable = _run,
) -> Dict[str, Any]:
    """Put the tree back to the backup ``applyBundle`` took before its sync: snapshot the current tree first (so the
    roll back can itself be undone), rsync back with the SAME excludes as ``apply_bundle`` (``.env``, venv, local state
    stay), reconcile the feature units, schedule the restart. Never raises."""
    lines: List[str] = []
    log: List[str] = []
    result: Dict[str, Any] = {'success': False, 'progress': lines, 'log': log, 'restart_scheduled': False, 'warnings': [],
                              'backup_id': backup_id, 'version_before': read_version(project_root)}

    def emit(phase: str, state: str, detail: str = '') -> None:
        lines.append(progress_line(host_name, phase, state, detail))

    try:
        if not os.path.isdir(project_root):
            raise ApplyError(f'project root not found: {project_root}')
        source = resolve_backup(backup_root, backup_id)
        try:
            snap_dir, snap_meta = backup_fn(project_root, backup_root, 'pre_rollback')
        except Exception as exc:
            raise ApplyError(f'could not snapshot the current tree, nothing was changed: {exc}')
        result['pre_rollback_backup_id'] = (snap_meta or {}).get('backup_id') or os.path.basename(str(snap_dir))
        log.append(f'current tree saved as {result["pre_rollback_backup_id"]}')
        sync = run(rsync_command(source, project_root), 1800)
        if sync.returncode != 0:
            raise ApplyError(f'rsync failed (the snapshot {result["pre_rollback_backup_id"]} can restore): {(sync.stderr or sync.stdout)[-300:]}')
        result['version_after'] = read_version(project_root)
        log.append(f'restored backup {backup_id}')
        emit('rollback', 'ok', f'{result["version_before"]} -> {result["version_after"]}')
    except (ApplyError, ba.BundleError) as exc:
        result['error'] = str(exc)
        emit('rollback', 'failed', str(exc))
        return result
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'[:300]
        emit('rollback', 'failed', result['error'])
        return result
    try:
        rec = run(reconcile_command(project_root), 300)
        if rec.returncode != 0:
            result['warnings'].append('reconcile failed: ' + (rec.stderr or rec.stdout or '').strip()[-200:])
    except Exception as exc:
        result['warnings'].append(f'reconcile could not run: {exc}')
    try:
        restart_fn()
        result['restart_scheduled'] = True
    except Exception as exc:
        result['warnings'].append(f'restart could not be scheduled: {exc}')
    result['success'] = result['restart_scheduled']
    if not result['success']:
        result['error'] = 'the tree is restored but the host service restart could not be scheduled'
    return result


# -- self check ----------------------------------------------------------------------------------
def _free(path: str) -> Optional[int]:
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe.rstrip('/'))
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe or '/').free
    except OSError:
        return None


def _tree_size(root: str, run: Callable) -> Optional[int]:
    try:
        res = run(['du', '-sk', '--exclude=venv', '--exclude=node_modules', '--exclude=.git', root], 8)
        return int(res.stdout.split()[0]) * 1024 if res.returncode == 0 and res.stdout.split() else None
    except Exception:
        return None


def self_check(*, project_root: str, backup_root: str, host_name: str, server_url: str, headers: Dict[str, str],
               service_unit: str = 'vpt-host', get: Optional[Callable] = None, run: Callable = _run,
               which: Callable = shutil.which) -> Dict[str, Any]:
    """Everything a host needs to take part in a pull update. Read-only; every probe is bounded."""
    out: Dict[str, Any] = {'success': True, 'host_name': host_name, 'version': read_version(project_root),
                           'supports_apply_bundle': True,
                           'project_root': project_root,
                           'server_url': server_url}   # TASK-128 G8: the server's address as this host uses it (SERVER_URL)
    # disk
    p_free, b_free = _free(project_root), _free(backup_root)
    tree = _tree_size(project_root, run)
    need_backup = max(MIN_FREE_BYTES, tree or 0)
    out['disk'] = {
        'project_free': p_free, 'backup_free': b_free, 'tree_size': tree, 'need_project': MIN_FREE_BYTES,
        'need_backup': need_backup,
        'ok': bool(p_free is not None and b_free is not None and p_free >= MIN_FREE_BYTES and b_free >= need_backup),
    }
    # tools
    tools = {name: bool(which(name)) for name in ('rsync', 'tar', 'sudo', 'bash')}
    out['tools'] = {'present': tools, 'ok': all(tools.values()), 'missing': [k for k, v in tools.items() if not v],
                    'pkg_manager': package_install.detect(which)}   # TASK-128 G10: the server builds the install line from it
    # sudo -n for the exact commands the update runs
    def can_sudo(argv: List[str]) -> Dict[str, Any]:
        try:
            res = run(['sudo', '-n', '-l'] + argv, 8)
            return {'ok': res.returncode == 0, 'detail': '' if res.returncode == 0 else
                    ((res.stderr or res.stdout or 'not allowed').strip().splitlines() or ['not allowed'])[-1][:200]}
        except Exception as exc:
            return {'ok': False, 'detail': f'{type(exc).__name__}: {exc}'[:200]}
    out['sudo'] = {
        'restart': can_sudo(['systemctl', 'restart', service_unit]),
        'reconcile': can_sudo(priv.reconcile_argv(project_root)),
    }
    stale = priv.helper_stale(project_root)
    if stale and out['sudo']['reconcile']['ok']:
        out['sudo']['reconcile'] = {'ok': False, 'detail': stale}
    out['sudo']['ok'] = out['sudo']['restart']['ok'] and out['sudo']['reconcile']['ok']
    # download from the server
    out['download'] = _probe_download(server_url, headers, get)
    out['ok'] = bool(out['disk']['ok'] and out['tools']['ok'] and out['sudo']['ok'] and out['download']['ok'])
    return out


def _probe_download(server_url: str, headers: Dict[str, str], get: Optional[Callable]) -> Dict[str, Any]:
    import hashlib
    if not server_url:
        return {'ok': False, 'detail': 'SERVER_URL is not set on this host'}
    url = f'{server_url.rstrip("/")}/server/platform-update/bundle/ping'
    try:
        if get is None:
            import requests
            get = requests.get
        resp = get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {'ok': False, 'url': url, 'detail': f'the server answered HTTP {resp.status_code}'}
        body = resp.json()
        text = str(body.get('body') or '')
        ok = hashlib.sha256(text.encode('utf-8')).hexdigest() == body.get('sha256')
        return {'ok': ok, 'url': url, 'detail': 'downloaded and verified' if ok else 'the test file did not match its sha256'}
    except Exception as exc:
        return {'ok': False, 'url': url, 'detail': f'{type(exc).__name__}: {exc}'[:200]}
