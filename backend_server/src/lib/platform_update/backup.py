"""
Backup of Platform update step 1 (TASK-109): what the update could break, saved before anything changes.

One timestamped folder under ``<state dir>/platform-update/backups/``, folder 0700, files 0600:

  server/<file>              the .env files of the server
  hosts/<host>/<file>        the .env files of every registered host (``GET /host/system/envFiles``)
  frontend/<file>            the .env files of the frontend VM over the existing SSH path (skipped when the frontend
                             is ``local`` - the server's own .env covers it - or ``none``)
  manifest.json              what is in the folder (no secrets)

The database is not in the folder: the server asks the DATABASE VM for a fresh full backup (``db_backup.py``; the
server never runs ``pg_dump``, its client may be older than the database). That backup stays on the database VM and its
NFS share. The folder holds secrets, so it stays on the server: nothing here, and no route, offers it for download.
Restoring a ``.env`` is a button per file (``restore.py``, TASK-128 G7); the database dump is restored by hand
(the page shows the command). A run that cannot save every item is KO and its folder is
removed, so a folder on disk is always a complete backup.

Everything that touches another machine or the OS goes through ``Deps`` so the tests mock it.
"""

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import db_backup, frontend_ssh, prerequisites
from .runs import PlatformUpdateError

DIR_MODE, FILE_MODE = 0o700, 0o600
HOST_TIMEOUT = 30
FRONTEND_TIMEOUT = 40
FILE_MARK = '::VPT-FILE:: '
# remote name / host-reported name -> stored file name. Anything else a machine reports is ignored.
SERVER_FILES = {'.env': 'env', 'backend_server/src/.env': 'backend_server_src.env'}
HOST_FILES = {'.env': 'env', 'backend_host/src/.env': 'backend_host_src.env'}
FRONTEND_FILES = {'.env': 'env', 'frontend/.env.production': 'frontend_env.production'}


def project_root() -> str:
    return os.getenv('VPT_PROJECT_ROOT', '/opt/virtualpytest')


def _hosts() -> List[dict]:
    return prerequisites._hosts()


def _call_host(host: dict, endpoint: str, method: str = 'GET', timeout: int = HOST_TIMEOUT):
    from shared.src.lib.utils.build_url_utils import call_host
    return call_host(host, endpoint, method=method, timeout=timeout)


def _run(argv: List[str], timeout: int, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, **(env or {})})


@dataclass
class Deps:
    database: Callable[[Callable[[str], None]], Dict[str, Any]] = lambda log: db_backup.request_backup(db_backup.Deps(), log)  # noqa: E731
    hosts: Callable[[], List[dict]] = _hosts
    call_host: Callable = _call_host
    run: Callable = _run
    frontend_cfg: Callable[[], Dict[str, str]] = lambda: frontend_ssh.config()  # noqa: E731
    project_root: Callable[[], str] = project_root
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731


def backups_dir(store_dir: Path) -> Path:
    return Path(store_dir) / 'backups'


def _mkdir(path: Path) -> None:
    """Create ``path`` and every missing parent as 0700 (``mkdir(mode=)`` alone leaves parents at the umask)."""
    missing = []
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent
    for directory in reversed(missing):
        directory.mkdir(mode=DIR_MODE, exist_ok=True)
        os.chmod(directory, DIR_MODE)


def _write(path: Path, data: bytes) -> int:
    _mkdir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(data)
    os.chmod(path, FILE_MODE)
    return len(data)


def _safe(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]', '_', name)[:80] or 'host'


def _restorable(allowed: Dict[str, str], files: List[str]) -> List[Dict[str, str]]:
    """The stored files the page may offer a Restore button for (TASK-128 G7): ``[{file, name}]``, ``name`` = where it goes."""
    back = {stored: name for name, stored in allowed.items()}
    return [{'file': f, 'name': back[Path(f).name]} for f in files if Path(f).name in back]


def _item(item_id: str, label: str, status: str, detail: str = '', size: int = 0, files: Optional[List[str]] = None,
          fix: str = '', restore: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    return {'id': item_id, 'label': label, 'status': status, 'detail': detail, 'size': size,
            'files': files or [], 'fix': fix if status == 'ko' else '', 'restore': restore or []}


# -- items -------------------------------------------------------------------------------------------
def backup_database(deps: Deps, log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """The database VM makes the backup (its own pg_dump version); this only asks for it and waits for the report."""
    try:
        res = deps.database(log)
    except Exception as exc:
        res = {'status': 'ko', 'detail': f'The database backup request failed: {type(exc).__name__}.', 'size': 0,
               'fix': db_backup.FIX_RUN_ON_VM}
    item = _item('database', 'Database', res['status'], res['detail'], res.get('size', 0), [], res.get('fix', ''))
    # never restored by the app: a dump replaces the whole database. The page shows this command for the database VM.
    item['restore_command'] = db_backup.restore_command(res['detail']) if res['status'] == 'ok' else ''
    return item


def _store_files(folder: Path, sub: str, allowed: Dict[str, str], files: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    size, written = 0, []
    for entry in files:
        stored = allowed.get(str(entry.get('name')))
        if not stored or not isinstance(entry.get('content'), str):
            continue
        size += _write(folder / sub / stored, entry['content'].encode('utf-8'))
        written.append(f'{sub}/{stored}')
    return size, written


def backup_server(deps: Deps, folder: Path) -> Dict[str, Any]:
    label, root = 'Server .env', deps.project_root()
    files = []
    for name in SERVER_FILES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            try:
                with open(path, 'rb') as fh:
                    files.append({'name': name, 'content': fh.read().decode('utf-8', errors='replace')})
            except OSError as exc:
                return _item('server', label, 'ko', f'Cannot read {name}: {type(exc).__name__}.',
                             fix='Make the .env readable by the service user, then back up again.')
    if not files:
        return _item('server', label, 'ko', f'No .env found under {root}.',
                     fix='Check VPT_PROJECT_ROOT points at the install, then back up again.')
    size, written = _store_files(folder, 'server', SERVER_FILES, files)
    return _item('server', label, 'ok', ', '.join(f['name'] for f in files), size, written, restore=_restorable(SERVER_FILES, written))


def backup_host(deps: Deps, folder: Path, host: dict) -> Dict[str, Any]:
    name = str(host.get('host_name') or host.get('name') or '?')
    label = f'{name} .env'
    item_id = f'host:{name}'
    try:
        body, status = deps.call_host(host, '/host/system/envFiles', 'GET', HOST_TIMEOUT)
    except Exception as exc:
        return _item(item_id, label, 'ko', f'Host did not answer: {type(exc).__name__}.',
                     fix='Start the host service (vpt-host), then back up again.')
    if status == 404:
        return _item(item_id, label, 'ko', 'This host predates the backup endpoint.',
                     fix='Update this host once by hand (git pull, restart vpt-host), then back up again.')
    if status != 200 or not isinstance(body, dict) or not body.get('success'):
        return _item(item_id, label, 'ko', f'Host refused: HTTP {status}.',
                     fix='Check the host service and that API_KEY matches the server, then back up again.')
    files = body.get('files') if isinstance(body.get('files'), list) else []
    size, written = _store_files(folder, f'hosts/{_safe(name)}', HOST_FILES, files)
    if not written:
        return _item(item_id, label, 'ko', 'The host has no .env file.', fix='Create the .env on that host, then back up again.')
    return _item(item_id, label, 'ok', ', '.join(Path(w).name for w in written), size, written, restore=_restorable(HOST_FILES, written))


def backup_frontend(deps: Deps, folder: Path) -> Dict[str, Any]:
    label = 'Frontend .env'
    cfg = deps.frontend_cfg()
    if cfg['mode'] == 'local':
        return _item('frontend', label, 'na', 'The frontend runs on this server: its .env is the server one.')
    if cfg['mode'] in ('none', 'unset'):
        return _item('frontend', label, 'na', 'No frontend VM to back up.')
    secrets = frontend_ssh.secrets(cfg)
    files_sh = ' '.join(FRONTEND_FILES)
    remote = (f'cd {cfg["target_dir"]} && for f in {files_sh}; do if [ -f "$f" ]; then '
              f'printf "\\n{FILE_MARK}%s\\n" "$f"; cat "$f"; fi; done')
    argv = frontend_ssh.ssh_argv(cfg, frontend_ssh.as_service_user(cfg, remote))
    try:
        res = deps.run(argv, FRONTEND_TIMEOUT, frontend_ssh.child_env(cfg))
    except Exception as exc:
        return _item('frontend', label, 'ko', f'SSH to the frontend VM failed: {type(exc).__name__}.',
                     fix='Fix the SSH access (Prerequisites, frontend VM), then back up again.')
    if res.returncode != 0:
        why = prerequisites.mask(((res.stderr or res.stdout or '').strip().splitlines() or [''])[-1], secrets)[:160]
        return _item('frontend', label, 'ko', f'SSH to the frontend VM failed: {why}',
                     fix='Fix the SSH access (Prerequisites, frontend VM), then back up again.')
    files, current = [], None
    for line in (res.stdout or '').splitlines(keepends=True):
        if line.startswith(FILE_MARK):
            current = {'name': line[len(FILE_MARK):].strip(), 'content': ''}
            files.append(current)
        elif current is not None:
            current['content'] += line
    for f in files:  # the printf newline before each marker belongs to the marker, not to the previous file
        f['content'] = f['content'][:-1] if f['content'].endswith('\n\n') else f['content']
    size, written = _store_files(folder, 'frontend', FRONTEND_FILES, files)
    if not written:
        return _item('frontend', label, 'na', f'No .env file under {cfg["target_dir"]} on the frontend VM.')
    return _item('frontend', label, 'ok', ', '.join(Path(w).name for w in written), size, written, restore=_restorable(FRONTEND_FILES, written))


# -- the whole backup --------------------------------------------------------------------------------
def run_backup(store_dir: Path, run_id: str, deps: Optional[Deps] = None,
               log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Create one backup folder. -> ``{ok, folder, path, created_at, items[]}``; a folder is kept only when ok."""
    deps = deps or Deps()
    now = deps.now()
    stamp = now.strftime('%Y%m%d-%H%M%S')
    root = backups_dir(store_dir)
    _mkdir(root)
    folder = root / stamp
    n = 1
    while folder.exists():
        n += 1
        folder = root / f'{stamp}-{n}'
    _mkdir(folder)
    items: List[Dict[str, Any]] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as db_pool:
            database = db_pool.submit(backup_database, deps, log)   # minutes long: runs beside the .env items
            items.append(None)
            items.append(backup_server(deps, folder))
            hosts = deps.hosts()
            if hosts:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
                    items += list(pool.map(lambda h: backup_host(deps, folder, h), hosts))
            items.append(backup_frontend(deps, folder))
            items[0] = database.result()
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise PlatformUpdateError(f'backup failed: {type(exc).__name__}')
    ok = not any(i['status'] == 'ko' for i in items)
    for i in items:
        log(f'Backup {i["label"]}: {i["status"].upper()}{" - " + i["detail"] if i["detail"] else ""}'
            f'{" (" + str(i["size"]) + " bytes)" if i["status"] == "ok" else ""}')
    result = {'ok': ok, 'folder': folder.name, 'path': str(folder),
              'created_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'items': items}
    if ok:
        _write(folder / 'manifest.json', json.dumps(
            {'run_id': run_id, 'created_at': result['created_at'], 'items': items}, indent=2).encode('utf-8'))
    else:
        shutil.rmtree(folder, ignore_errors=True)  # never leave a half backup (it holds secrets) behind
    return result
