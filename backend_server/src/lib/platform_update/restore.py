"""
Restore one ``.env`` from a Platform update backup (TASK-128 G7). One file, one admin click, nothing restarted.

What can be restored is exactly what step 1 saved: the request names a backup folder, an item and a stored file, and all
three are checked against that folder's ``manifest.json``. The target name is then looked up in the fixed tables of
``backup.py`` (the same ones that decided what to save), so no request can name another path.

  server item     written on this server, under the project root (atomic; the current file is first copied to
                  ``<file>.bak-<timestamp>``; owner and mode are kept)
  host:<name>     sent to that host: ``POST /host/system/restoreEnvFile`` through ``call_host`` (the host writes it the
                  same way, only for the fixed names ``env_backup.py`` knows)
  frontend        piped over the existing SSH path to the frontend VM, as the service user (key mode only: in the older
                  password mode the file would have to travel in a command line)
  database        never: a dump replaces the whole database. The page shows the command (``db_backup.restore_command``).

The reply carries the command that makes the file take effect. The app never restarts a service.
"""

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from shared.src.lib.utils.atomic_replace import replace_keeping_mode

from . import backup as bk
from . import frontend_ssh, prerequisites
from .runs import PlatformUpdateError

FOLDER_RE = re.compile(r'^\d{8}-\d{6}(-\d+)?$')
HOST_RESTORE_TIMEOUT = 30
FRONTEND_RESTORE_TIMEOUT = 40
MAX_BYTES = 256 * 1024


def _call_host(host: dict, endpoint: str, method: str = 'POST', timeout: int = HOST_RESTORE_TIMEOUT, data: Optional[dict] = None):
    from shared.src.lib.utils.build_url_utils import call_host
    return call_host(host, endpoint, method=method, data=data, timeout=timeout)


def _run_input(argv: List[str], timeout: int, env: Dict[str, str], stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, **env})


@dataclass
class Deps:
    hosts: Callable[[], List[dict]] = prerequisites._hosts
    call_host: Callable = _call_host
    run_input: Callable = _run_input
    frontend_cfg: Callable[[], Dict[str, str]] = lambda: frontend_ssh.config()  # noqa: E731
    project_root: Callable[[], str] = bk.project_root
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731


class NotFound(PlatformUpdateError):
    code = 404


def _bad(message: str) -> PlatformUpdateError:
    return PlatformUpdateError(message)


def _stamp(deps: Deps) -> str:
    return deps.now().strftime('%Y%m%d-%H%M%S')


def _saved_file(store_dir: Path, folder: str, item_id: str, file: str) -> str:
    """The text of one stored file, after checking the folder, the manifest and the path. Raises on anything unexpected."""
    if not isinstance(folder, str) or not FOLDER_RE.match(folder):
        raise _bad('unknown backup folder')
    path = bk.backups_dir(store_dir) / folder
    if path.is_symlink() or not path.is_dir():
        raise NotFound('this backup folder no longer exists (Free space deletes the older ones)')
    try:
        manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise _bad('this backup has no manifest')
    if item_id == 'database':
        raise _bad('the database is restored by hand: use the command shown with the backup')
    item = next((i for i in manifest.get('items', []) if i.get('id') == item_id), None)
    if item is None or item.get('status') != 'ok':
        raise _bad('this item is not part of the backup')
    if not isinstance(file, str) or file not in (item.get('files') or []):
        raise _bad('this file is not part of the backup')
    target = path / file
    real_folder = os.path.realpath(path)
    if target.is_symlink() or not target.is_file() or not os.path.realpath(target).startswith(real_folder + os.sep):
        raise _bad('this file is not a plain file inside the backup')
    if target.stat().st_size > MAX_BYTES:
        raise _bad('this file is too large for an env file')
    try:
        return target.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise _bad('this file cannot be read as text')


def _name_for(allowed: Dict[str, str], file: str) -> str:
    back = {stored: name for name, stored in allowed.items()}
    name = back.get(Path(file).name)
    if not name:
        raise _bad('this file is not one the update restores')
    return name


def _result(machine: str, name: str, backup_of_current: str, service: str, note: str = '') -> Dict[str, Any]:
    return {'restored': name, 'machine': machine, 'backup_of_current': backup_of_current,
            'restart': {'machine': machine, 'command': f'sudo systemctl restart {service}'}, 'note': note}


def _restore_server(deps: Deps, file: str, content: str) -> Dict[str, Any]:
    if not file.startswith('server/'):
        raise _bad('this file does not belong to the server item')
    name = _name_for(bk.SERVER_FILES, file)
    path = os.path.join(deps.project_root(), name)
    try:
        previous = replace_keeping_mode(path, content.encode('utf-8'), _stamp(deps))
    except OSError as exc:
        raise _bad(f'cannot write {name} on this server: {type(exc).__name__}')
    return _result('this server', name, os.path.basename(previous) if previous else '', 'vpt-server')


def _restore_host(deps: Deps, item_id: str, file: str, content: str) -> Dict[str, Any]:
    host_name = item_id.split(':', 1)[1]
    host = next((h for h in deps.hosts() if str(h.get('host_name') or h.get('name') or '?') == host_name), None)
    if host is None:
        raise NotFound(f'host {host_name} is not registered with this server any more')
    if not file.startswith(f'hosts/{bk._safe(host_name)}/'):
        raise _bad('this file does not belong to that host')
    name = _name_for(bk.HOST_FILES, file)
    try:
        body, status = deps.call_host(host, '/host/system/restoreEnvFile', 'POST', HOST_RESTORE_TIMEOUT, {'name': name, 'content': content})
    except Exception as exc:
        raise _bad(f'{host_name} did not answer ({type(exc).__name__}): start its host service, then restore again')
    if status == 404:
        raise _bad(f'{host_name} predates the restore endpoint: update it once by hand, or copy the file there yourself')
    if status != 200 or not isinstance(body, dict) or not body.get('success'):
        why = body.get('error') if isinstance(body, dict) else ''
        raise _bad(f'{host_name} refused: {why or f"HTTP {status}"}')
    return _result(host_name, name, str(body.get('backup') or ''), 'vpt-host')


def _frontend_script(name: str, stamp: str, target_dir: str) -> str:
    return (f'cd {shlex.quote(target_dir)} && f={shlex.quote(name)} && umask 077 && '
            f'if [ -f "$f" ]; then cp -p "$f" "$f.bak-{stamp}"; fi && '
            f'cat > "$f.vpt-new" && if [ -f "$f" ]; then chmod --reference="$f" "$f.vpt-new"; fi && mv -f "$f.vpt-new" "$f"')


def _restore_frontend(deps: Deps, file: str, content: str) -> Dict[str, Any]:
    cfg = deps.frontend_cfg()
    if cfg['mode'] != 'ssh':
        raise _bad('there is no separate frontend VM configured: its .env is the server one')
    if cfg['password']:
        raise _bad('the SSH password mode cannot carry a file safely: copy the file to the frontend VM by hand, '
                   'or switch to a server key (Settings -> Server key)')
    if not file.startswith('frontend/'):
        raise _bad('this file does not belong to the frontend item')
    name = _name_for(bk.FRONTEND_FILES, file)
    stamp = _stamp(deps)
    argv = frontend_ssh.ssh_argv(cfg, frontend_ssh.as_service_user(cfg, _frontend_script(name, stamp, cfg['target_dir'])))
    try:
        res = deps.run_input(argv, FRONTEND_RESTORE_TIMEOUT, frontend_ssh.child_env(cfg), content)
    except Exception as exc:
        raise _bad(f'SSH to the frontend VM failed: {type(exc).__name__}')
    if res.returncode != 0:
        why = prerequisites.mask(((res.stderr or res.stdout or '').strip().splitlines() or [''])[-1], frontend_ssh.secrets(cfg))[:160]
        raise _bad(f'writing {name} on the frontend VM failed: {why}')
    note = 'The frontend reads .env.production when it is built: the next update (step 3) rebuilds it.' \
        if name.endswith('.env.production') else ''
    return _result('frontend VM', name, f'{name}.bak-{stamp}', cfg['service'], note)


def restore(store_dir: Path, folder: str, item_id: str, file: str, deps: Optional[Deps] = None) -> Dict[str, Any]:
    """Restore one saved file. -> ``{restored, machine, backup_of_current, restart: {machine, command}, note}``."""
    deps = deps or Deps()
    if not isinstance(item_id, str):
        raise _bad('unknown item')
    content = _saved_file(store_dir, folder, item_id, file)
    if item_id == 'server':
        return _restore_server(deps, file, content)
    if item_id.startswith('host:'):
        return _restore_host(deps, item_id, file, content)
    if item_id == 'frontend':
        return _restore_frontend(deps, file, content)
    raise _bad('unknown item')
