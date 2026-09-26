"""
System routes for client registration and health management
Handles server/client communication and registry
"""

from flask import Blueprint, request, jsonify, current_app
import threading
import time
import requests
import os
import subprocess
import psutil
from datetime import datetime, timezone
import json
import shlex
from typing import TypedDict, Optional, List, Any
from pathlib import Path
import shutil
import tempfile
import zipfile
import uuid
from backend_server.src.lib.utils.response_cache import get_cached_response, set_cached_response
from backend_server.src.lib.utils.server_utils import get_host_manager, get_server_system_stats
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_user_auth, require_role
from backend_server.src.routes.server_system_socket_routes import emit_system_update
from shared.src.lib.config.constants import CACHE_CONFIG
from shared.src.lib.database.system_metrics_db import store_system_metrics, get_latest_system_metrics
from backend_host.src.lib.utils.system_info_utils import (
    _check_linux_service,
    _check_supervisor_service,
)

server_system_bp = Blueprint('server_system', __name__, url_prefix='/server/system')
_last_ping_emit_by_host = {}
_PING_EMIT_MIN_INTERVAL_SECONDS = 5.0

# Stale lock liveness probe — runs during host pings
_STALE_LOCK_CHECK_INTERVAL_SECONDS = 60.0   # check at most once per minute per host
_STALE_LOCK_GRACE_PERIOD_SECONDS = 120.0    # lock must be >2 min old before probing
_last_stale_lock_check_by_host = {}
SERVER_UPDATE_LOCK_FILE = '/tmp/vpt_server_update_core.lock'
SERVER_DEPLOY_STATE_FILE = '/var/tmp/virtualpytest_server_deploy_state.json'
SERVER_BACKUP_ROOT = '/var/tmp/virtualpytest_backups'
SOURCE_UPLOAD_ROOT = '/var/tmp/vpt_source_uploads'
DEFAULT_STORAGE_SOURCE_PATH = '/mnt/shared/code/virtualpytest'
DEFAULT_GIT_SOURCE_ORGANIZATION = 'AngelStreetCorp'
BACKUP_META_FILENAME = '.vpt-backup-meta.json'
DEFAULT_FRONTEND_DEPLOY_HOST = '192.168.0.105'
DEFAULT_FRONTEND_DEPLOY_USER = 'jndoye'
FRONTEND_DEPLOY_STATE_CACHE_TTL_SECONDS = 30
_frontend_deploy_state_cache = {
    'value': None,
    'expires_at': 0.0,
}


def _read_local_deployed_version(base_dir: str = '/opt/virtualpytest') -> str:
    # Search several common locations. On a Pi/Pi-host the file lives at
    # /opt/virtualpytest/VERSION.txt. On Render / Docker the file lands under
    # /app/VERSION.txt (the Dockerfile's WORKDIR is /app/backend_server, so
    # /app/VERSION.txt is the project-root version the image actually ships).
    # The relative path './VERSION.txt' is a CWD fallback for `python -m` runs
    # and pytest. First hit wins, no exception if every path is missing.
    candidates: list[str] = []
    for root in (base_dir, '/app', os.getcwd()):
        for name in ('VERSION.txt', 'version'):
            candidates.append(os.path.join(root, name))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8') as file:
                    value = file.readline().strip()
                if value:
                    return value
            except Exception:
                pass
    return 'unknown'


def _project_root() -> str:
    return str(Path(__file__).resolve().parents[3])


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'n', 'off'}:
            return False
    return default


def _parse_kv_output(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in (output or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            parsed[key.strip()] = value.strip()
    return parsed


def _read_server_deploy_state() -> dict:
    default = {
        'deployed_version': _read_local_deployed_version('/opt/virtualpytest'),
        'last_deploy_at': None,
        'deploy_state': 'idle',
    }
    try:
        if os.path.isfile(SERVER_DEPLOY_STATE_FILE):
            with open(SERVER_DEPLOY_STATE_FILE, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                default.update({
                    'deployed_version': payload.get('deployed_version') or default['deployed_version'],
                    'last_deploy_at': payload.get('last_deploy_at'),
                    'deploy_state': payload.get('deploy_state') or 'idle',
                })
    except Exception:
        pass
    return default


def _write_server_deploy_state(payload: dict) -> None:
    os.makedirs(os.path.dirname(SERVER_DEPLOY_STATE_FILE), exist_ok=True)
    with open(SERVER_DEPLOY_STATE_FILE, 'w', encoding='utf-8') as file:
        json.dump(payload, file, ensure_ascii=True)


def _set_server_deploy_state(state: str, version: Optional[str] = None, error: Optional[str] = None) -> None:
    current = _read_server_deploy_state()
    current['deploy_state'] = state
    current['last_deploy_at'] = _utc_now_iso()
    current['deployed_version'] = version or _read_local_deployed_version('/opt/virtualpytest')
    if error:
        current['last_error'] = error[:2000]
    else:
        current.pop('last_error', None)
    _write_server_deploy_state(current)


def _acquire_server_update_lock() -> bool:
    try:
        fd = os.open(SERVER_UPDATE_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode('utf-8'))
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_server_update_lock() -> None:
    try:
        os.remove(SERVER_UPDATE_LOCK_FILE)
    except FileNotFoundError:
        pass


def _list_backups() -> list[str]:
    if not os.path.isdir(SERVER_BACKUP_ROOT):
        return []
    return sorted(
        [os.path.join(SERVER_BACKUP_ROOT, entry) for entry in os.listdir(SERVER_BACKUP_ROOT)
         if os.path.isdir(os.path.join(SERVER_BACKUP_ROOT, entry))],
        reverse=True
    )


def _backup_excludes() -> list[str]:
    return [
        '.env',
        'venv',
        'node_modules',
        'frontend/public/docs',
        'frontend/dist',
        'playwright-report*',
        'playwright-viewport-report*',
        'security_report',
        'frontend/vite.config.local.json',
        'frontend/public/branding.json',
        '.backups',
    ]


def _backup_meta_path(backup_dir: str) -> str:
    return os.path.join(backup_dir, BACKUP_META_FILENAME)


def _write_backup_metadata(backup_dir: str, payload: dict) -> None:
    os.makedirs(backup_dir, exist_ok=True)
    with open(_backup_meta_path(backup_dir), 'w', encoding='utf-8') as file:
        json.dump(payload, file, ensure_ascii=True, indent=2)


def _read_backup_metadata(backup_dir: str) -> dict:
    meta_path = _backup_meta_path(backup_dir)
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    stat = os.stat(backup_dir)
    return {
        'backup_id': os.path.basename(backup_dir),
        'backup_path': backup_dir,
        'created_at': datetime.utcfromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat() + 'Z',
        'version': _read_local_deployed_version(backup_dir),
        'status': 'stable',
        'reason': 'legacy',
    }


def _run_backup_rsync(source_dir: str, destination_dir: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    command = ['rsync', '-a', '--delete']
    for pattern in _backup_excludes():
        command.append(f'--exclude={pattern}')
    command.extend([f'{source_dir}/', f'{destination_dir}/'])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _create_backup_snapshot(
    target_dir: str,
    backup_root: str,
    reason: str,
    source_path: Optional[str] = None,
    source_ref: Optional[str] = None,
    rolled_forward_to: Optional[str] = None,
) -> tuple[str, dict]:
    created_at = _utc_now_iso()
    backup_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    backup_dir = os.path.join(backup_root, backup_id)
    os.makedirs(backup_root, exist_ok=True)
    result = _run_backup_rsync(target_dir, backup_dir)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-400:] or result.stdout[-400:] or 'backup snapshot failed')

    metadata = {
        'backup_id': backup_id,
        'backup_path': backup_dir,
        'created_at': created_at,
        'version': _read_local_deployed_version(target_dir),
        'status': 'stable',
        'reason': reason,
    }
    if source_path:
        metadata['source_path'] = source_path
    if source_ref:
        metadata['source_ref'] = source_ref
    if rolled_forward_to:
        metadata['rolled_forward_to'] = rolled_forward_to
    git_info = _read_git_head_info(source_path or target_dir)
    if git_info.get('is_git_repo'):
        metadata['source_branch'] = git_info.get('branch')
        metadata['source_commit'] = git_info.get('short_commit')
    _write_backup_metadata(backup_dir, metadata)
    return backup_dir, metadata


def _list_backup_entries(backup_root: str, target_dir: str, ensure_baseline: bool = False) -> list[dict]:
    if ensure_baseline and os.path.isdir(target_dir):
        existing_dirs = [
            os.path.join(backup_root, entry)
            for entry in os.listdir(backup_root)
            if os.path.isdir(os.path.join(backup_root, entry))
        ] if os.path.isdir(backup_root) else []
        if not existing_dirs:
            _create_backup_snapshot(target_dir, backup_root, reason='baseline')

    if not os.path.isdir(backup_root):
        return []

    entries = []
    for backup_dir in sorted(
        [
            os.path.join(backup_root, entry)
            for entry in os.listdir(backup_root)
            if os.path.isdir(os.path.join(backup_root, entry))
        ],
        reverse=True,
    ):
        metadata = _read_backup_metadata(backup_dir)
        metadata['backup_path'] = backup_dir
        entries.append(metadata)
    return entries


def _prune_backup_entries(backup_root: str, keep_backups: int) -> None:
    if keep_backups <= 0 or not os.path.isdir(backup_root):
        return
    backup_dirs = sorted(
        [
            os.path.join(backup_root, entry)
            for entry in os.listdir(backup_root)
            if os.path.isdir(os.path.join(backup_root, entry))
        ]
    )
    if len(backup_dirs) <= keep_backups:
        return
    for backup_dir in backup_dirs[:len(backup_dirs) - keep_backups]:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _resolve_backup_dir(
    backup_root: str,
    target_dir: str,
    backup_id: Optional[str] = None,
    backup_path: Optional[str] = None,
    ensure_baseline: bool = False,
) -> str:
    entries = _list_backup_entries(backup_root, target_dir, ensure_baseline=ensure_baseline)
    if backup_id:
        for entry in entries:
            if entry.get('backup_id') == backup_id:
                return os.path.realpath(str(entry['backup_path']))
        raise FileNotFoundError(f'Backup not found: {backup_id}')
    if backup_path:
        return os.path.realpath(str(backup_path))
    if not entries:
        raise FileNotFoundError('No backup found to rollback')
    return os.path.realpath(str(entries[0]['backup_path']))


def _schedule_server_restart(delay_seconds: int = 2) -> None:
    subprocess.Popen(
        ['bash', '-lc', f'sleep {max(1, delay_seconds)} && sudo systemctl restart vpt-server'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _allowed_storage_roots() -> list:
    """Directories a deploy source path may live under.

    Comma-separated STORAGE_SOURCE_ROOTS env, else the parent of the default source path.
    """
    raw = os.getenv('STORAGE_SOURCE_ROOTS', '')
    roots = [r.strip() for r in raw.split(',') if r.strip()] or [os.path.dirname(DEFAULT_STORAGE_SOURCE_PATH)]
    return [os.path.realpath(r) for r in roots]


def _resolve_storage_path(requested_path: Optional[str]) -> str:
    """Validate a caller-supplied source checkout path.

    The path is handed to `git -C`, `open()` and zip extraction, so it must be absolute
    and resolve (symlinks included) under one of the allowed roots. Raises ValueError.
    """
    candidate = (requested_path or '').strip()
    if not candidate:
        return DEFAULT_STORAGE_SOURCE_PATH
    if '\x00' in candidate or not os.path.isabs(candidate):
        raise ValueError('storage_path must be an absolute path')
    resolved = os.path.realpath(candidate)
    roots = _allowed_storage_roots()
    if any(resolved == root or resolved.startswith(root + os.sep) for root in roots):
        return resolved
    raise ValueError(
        f'storage_path must be under {", ".join(roots)} (set STORAGE_SOURCE_ROOTS to allow more)'
    )


def _frontend_remote_config() -> dict[str, str]:
    return {
        'host': (os.getenv('FRONTEND_DEPLOY_HOST') or DEFAULT_FRONTEND_DEPLOY_HOST).strip(),
        'user': (os.getenv('FRONTEND_DEPLOY_SSH_USER') or DEFAULT_FRONTEND_DEPLOY_USER).strip(),
        'password': (os.getenv('FRONTEND_DEPLOY_SSH_PASSWORD') or '').strip(),
        'target_dir': (os.getenv('FRONTEND_DEPLOY_TARGET_DIR') or '/opt/virtualpytest').strip(),
        'backup_root': (os.getenv('FRONTEND_DEPLOY_BACKUP_ROOT') or SERVER_BACKUP_ROOT).strip(),
        'service_name': (os.getenv('FRONTEND_DEPLOY_SERVICE_NAME') or 'vpt-frontend').strip(),
    }


def _run_frontend_remote(command: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    config = _frontend_remote_config()
    if not config['host'] or not config['user']:
        raise RuntimeError('Frontend remote deploy host/user are not configured')
    if not config['password']:
        raise RuntimeError('FRONTEND_DEPLOY_SSH_PASSWORD is required for frontend remote deploy')
    sshpass = shutil.which('sshpass')
    if not sshpass:
        raise RuntimeError('sshpass is required on backend server for frontend remote deploy')
    ssh_command = [
        sshpass, '-p', config['password'],
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ConnectTimeout=10',
        f"{config['user']}@{config['host']}",
        f"echo {shlex.quote(config['password'])} | sudo -S -u vpt_user bash -lc {shlex.quote(command)}",
    ]
    return subprocess.run(
        ssh_command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _frontend_remote_env_assignments(source_path: str, dry_run: bool, restart_service: bool) -> str:
    config = _frontend_remote_config()
    return (
        f"VPT_SOURCE_DIR={shlex.quote(source_path)} "
        f"VPT_TARGET_DIR={shlex.quote(config['target_dir'])} "
        f"VPT_BACKUP_ROOT={shlex.quote(config['backup_root'])} "
        f"VPT_KEEP_BACKUPS=5 "
        f"VPT_DRY_RUN={'1' if dry_run else '0'} "
        f"VPT_TARGET_KIND=frontend "
        f"VPT_RESTART_ENABLED={'1' if restart_service else '0'}"
    )


def _run_frontend_remote_deploy(source_path: str, dry_run: bool, restart_service: bool) -> subprocess.CompletedProcess:
    config = _frontend_remote_config()
    remote_script = os.path.join(config['target_dir'], 'scripts', 'code-deploy.sh')
    command = f"{_frontend_remote_env_assignments(source_path, dry_run, restart_service)} bash {shlex.quote(remote_script)}"
    return _run_frontend_remote(command, timeout=1800)


def _read_frontend_remote_deploy_state() -> dict:
    now = time.time()
    cached_value = _frontend_deploy_state_cache.get('value')
    if cached_value and _frontend_deploy_state_cache.get('expires_at', 0.0) > now:
        return dict(cached_value)

    config = _frontend_remote_config()
    default = {
        'deployed_version': 'unknown',
    }
    try:
        result = _run_frontend_remote(
            (
                "python3 - <<'PY'\n"
                "import json, os\n"
                f"target_dir = {config['target_dir']!r}\n"
                "version = 'unknown'\n"
                "for candidate in ('version', 'VERSION.txt'):\n"
                "    path = os.path.join(target_dir, candidate)\n"
                "    if os.path.isfile(path):\n"
                "        with open(path, 'r', encoding='utf-8') as file:\n"
                "            value = file.readline().strip()\n"
                "        if value:\n"
                "            version = value\n"
                "            break\n"
                "print(json.dumps({'deployed_version': version}))\n"
                "PY"
            ),
            timeout=30,
        )
        if result.returncode != 0:
            return default
        payload = json.loads((result.stdout or '').strip() or '{}')
        if isinstance(payload, dict):
            resolved = {
                'deployed_version': str(payload.get('deployed_version') or 'unknown'),
            }
            _frontend_deploy_state_cache['value'] = dict(resolved)
            _frontend_deploy_state_cache['expires_at'] = now + FRONTEND_DEPLOY_STATE_CACHE_TTL_SECONDS
            return resolved
    except Exception:
        pass
    _frontend_deploy_state_cache['value'] = dict(default)
    _frontend_deploy_state_cache['expires_at'] = now + FRONTEND_DEPLOY_STATE_CACHE_TTL_SECONDS
    return default


def _run_frontend_remote_rsync_restore(selected_backup: str, restart_service: bool, dry_run: bool) -> subprocess.CompletedProcess:
    config = _frontend_remote_config()
    exclude_flags = ' '.join(f"--exclude={item}" for item in _backup_excludes())
    restart_cmd = (
        f"echo {shlex.quote(config['password'])} | sudo -S systemctl restart {shlex.quote(config['service_name'])}"
        if restart_service else 'true'
    )
    command = (
        f"set -euo pipefail; "
        f"VERSION_BEFORE=$(head -n 1 {shlex.quote(os.path.join(config['target_dir'], 'VERSION.txt'))} 2>/dev/null || echo unknown); "
        f"if [ {'1' if dry_run else '0'} = 1 ]; then "
        f"echo VERSION_BEFORE=$VERSION_BEFORE; echo VERSION_AFTER=$VERSION_BEFORE; exit 0; fi; "
        f"rsync -a --delete {exclude_flags} {shlex.quote(selected_backup)}/ {shlex.quote(config['target_dir'])}/; "
        f"{restart_cmd}; "
        f"VERSION_AFTER=$(head -n 1 {shlex.quote(os.path.join(config['target_dir'], 'VERSION.txt'))} 2>/dev/null || echo unknown); "
        f"echo VERSION_BEFORE=$VERSION_BEFORE; echo VERSION_AFTER=$VERSION_AFTER"
    )
    return _run_frontend_remote(command, timeout=1800)


def _list_frontend_remote_backups() -> tuple[list[dict], Optional[str]]:
    config = _frontend_remote_config()
    python_script = r"""
import json, os
from datetime import datetime
ROOT = os.environ['VPT_BACKUP_ROOT']
TARGET = os.environ['VPT_TARGET_DIR']
META = '.vpt-backup-meta.json'

def read_version(base_dir):
    for candidate in ('version', 'VERSION.txt'):
        path = os.path.join(base_dir, candidate)
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    value = f.readline().strip()
                if value:
                    return value
            except Exception:
                pass
    return 'unknown'

def write_meta(backup_dir, payload):
    with open(os.path.join(backup_dir, META), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)

if os.path.isdir(TARGET):
    os.makedirs(ROOT, exist_ok=True)
    if not any(os.path.isdir(os.path.join(ROOT, entry)) for entry in os.listdir(ROOT)):
        backup_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
        backup_dir = os.path.join(ROOT, backup_id)
        os.makedirs(backup_dir, exist_ok=True)
        os.system('rsync -a --delete --exclude=.env --exclude=venv --exclude=node_modules --exclude=frontend/public/docs --exclude=frontend/dist --exclude=playwright-report* --exclude=playwright-viewport-report* --exclude=security_report --exclude=frontend/vite.config.local.json --exclude=frontend/public/branding.json --exclude=.backups "{}/" "{}/" >/dev/null 2>&1'.format(TARGET, backup_dir))
        write_meta(backup_dir, {
            'backup_id': backup_id,
            'backup_path': backup_dir,
            'created_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
            'version': read_version(TARGET),
            'status': 'stable',
            'reason': 'baseline',
        })

entries = []
if os.path.isdir(ROOT):
    for entry in sorted(os.listdir(ROOT), reverse=True):
        backup_dir = os.path.join(ROOT, entry)
        if not os.path.isdir(backup_dir):
            continue
        meta_path = os.path.join(backup_dir, META)
        payload = None
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            stat = os.stat(backup_dir)
            payload = {
                'backup_id': os.path.basename(backup_dir),
                'backup_path': backup_dir,
                'created_at': datetime.utcfromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat() + 'Z',
                'version': read_version(backup_dir),
                'status': 'stable',
                'reason': 'legacy',
            }
        payload['backup_path'] = backup_dir
        entries.append(payload)
print(json.dumps({'backups': entries, 'default_backup_id': entries[0]['backup_id'] if entries else None}))
"""
    remote_command = (
        f"export VPT_BACKUP_ROOT={shlex.quote(config['backup_root'])} "
        f"VPT_TARGET_DIR={shlex.quote(config['target_dir'])}; "
        f"python3 - <<'PY'\n{python_script}\nPY"
    )
    result = _run_frontend_remote(remote_command, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-400:] or result.stdout[-400:] or 'frontend backup listing failed')
    payload = json.loads((result.stdout or '{}').strip() or '{}')
    return payload.get('backups', []), payload.get('default_backup_id')


def _read_git_head_info(storage_path: str) -> dict:
    result = {
        'is_git_repo': False,
        'branch': None,
        'commit': None,
        'short_commit': None,
        'version': None,
    }
    if not os.path.isdir(storage_path):
        return result
    git_dir = os.path.join(storage_path, '.git')
    if not os.path.isdir(git_dir):
        return result
    result['is_git_repo'] = True
    try:
        branch_proc = subprocess.run(
            ['git', '-C', storage_path, 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if branch_proc.returncode == 0:
            result['branch'] = (branch_proc.stdout or '').strip()
        commit_proc = subprocess.run(
            ['git', '-C', storage_path, 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if commit_proc.returncode == 0:
            commit = (commit_proc.stdout or '').strip()
            result['commit'] = commit
            result['short_commit'] = commit[:8] if commit else None
        version_path = os.path.join(storage_path, 'VERSION.txt')
        if os.path.isfile(version_path):
            with open(version_path, 'r', encoding='utf-8') as file:
                version = file.readline().strip()
            if version:
                result['version'] = version
    except Exception:
        pass
    return result


def _git_source_organization() -> str:
    """Organization from which an admin may configure a deployment source."""
    return (os.getenv('GIT_SOURCE_ALLOWED_ORG') or DEFAULT_GIT_SOURCE_ORGANIZATION).strip()


def _is_allowed_git_source_repository(repository: str) -> bool:
    """Keep source switching to the platform and customer-overlay repository family."""
    normalized = repository.strip().lower()
    return normalized.startswith('virtualpytest') or normalized.startswith('vpt-')


def _parse_allowed_git_remote(remote_url: str) -> Optional[tuple[str, str]]:
    """Return (organization, repository) only for a permitted GitHub origin URL.

    The deployment checkout is operational infrastructure.  Do not accept arbitrary
    remotes here: a typo otherwise silently turns a deployment into a different repo.
    """
    value = remote_url.strip()
    https_prefix = 'https://github.com/'
    ssh_prefix = 'git@github.com:'
    if value.startswith(https_prefix):
        path = value[len(https_prefix):]
    elif value.startswith(ssh_prefix):
        path = value[len(ssh_prefix):]
    else:
        return None
    if path.endswith('.git'):
        path = path[:-4]
    pieces = path.split('/')
    if len(pieces) != 2 or not all(pieces):
        return None
    organization, repository = pieces
    if organization != _git_source_organization() or not _is_allowed_git_source_repository(repository):
        return None
    return organization, repository


def _read_git_origin_url(storage_path: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ['git', '-C', storage_path, 'remote', 'get-url', 'origin'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            value = (proc.stdout or '').strip()
            return value or None
    except Exception:
        pass
    return None


def _list_allowed_git_source_repositories() -> tuple[list[dict], Optional[str]]:
    """List permitted organization repositories using GitHub's API when available."""
    organization = _git_source_organization()
    headers = {'Accept': 'application/vnd.github+json'}
    token = (os.getenv('GITHUB_TOKEN') or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    repositories = []
    try:
        response = requests.get(
            f'https://api.github.com/orgs/{organization}/repos',
            params={'type': 'all', 'per_page': 100, 'sort': 'full_name'},
            headers=headers,
            timeout=15,
        )
        if response.status_code != 200:
            return [], f'GitHub repository listing failed ({response.status_code})'
        payload = response.json()
        if not isinstance(payload, list):
            return [], 'GitHub returned an invalid repository listing'
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('name') or '').strip()
            clone_url = str(entry.get('clone_url') or '').strip()
            if _is_allowed_git_source_repository(name) and _parse_allowed_git_remote(clone_url):
                repositories.append({'name': name, 'url': clone_url})
    except requests.RequestException as exc:
        return [], f'Could not reach GitHub: {exc}'
    return sorted(repositories, key=lambda entry: entry['name'].lower()), None


def _list_git_branches(storage_path: str) -> list[str]:
    if not os.path.isdir(storage_path) or not os.path.isdir(os.path.join(storage_path, '.git')):
        return []
    try:
        proc = subprocess.run(
            ['git', '-C', storage_path, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/remotes/origin'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode != 0:
            return []
        branches: list[str] = []
        seen: set[str] = set()
        for line in (proc.stdout or '').splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith('origin/'):
                candidate = candidate[len('origin/'):]
            if candidate == 'HEAD' or '->' in candidate or candidate in seen:
                continue
            seen.add(candidate)
            branches.append(candidate)
        return sorted(branches)
    except Exception:
        return []


def _read_git_diff_summary(storage_path: str, before_commit: Optional[str], after_commit: Optional[str]) -> list[dict]:
    if not before_commit or not after_commit or before_commit == after_commit:
        return []
    try:
        name_status_proc = subprocess.run(
            ['git', '-C', storage_path, 'diff', '--name-status', f'{before_commit}..{after_commit}'],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        numstat_proc = subprocess.run(
            ['git', '-C', storage_path, 'diff', '--numstat', f'{before_commit}..{after_commit}'],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if name_status_proc.returncode != 0 or numstat_proc.returncode != 0:
            return []

        counts_by_path: dict[str, tuple[str, str]] = {}
        for line in (numstat_proc.stdout or '').splitlines():
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            added, deleted, path = parts[0].strip(), parts[1].strip(), parts[2].strip()
            counts_by_path[path] = (added, deleted)

        diff_entries: list[dict] = []
        for line in (name_status_proc.stdout or '').splitlines():
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            status = parts[0].strip()
            path = parts[-1].strip()
            added, deleted = counts_by_path.get(path, ('0', '0'))
            diff_entries.append({
                'status': status,
                'path': path,
                'added': added,
                'deleted': deleted,
            })
        return diff_entries
    except Exception:
        return []


def _validate_expected_structure(root_dir: str) -> tuple[bool, list[str]]:
    required_paths = [
        'backend_server',
        'backend_host',
        'frontend',
        'shared',
        'setup',
    ]
    missing = []
    for relative_path in required_paths:
        if not os.path.isdir(os.path.join(root_dir, relative_path)):
            missing.append(relative_path)
    if not os.path.isfile(os.path.join(root_dir, 'VERSION.txt')):
        missing.append('VERSION.txt')
    return (len(missing) == 0), missing


def _safe_extract_zip(zip_path: str, destination: str) -> None:
    with zipfile.ZipFile(zip_path, 'r') as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f'Corrupted archive member: {bad}')
        for member in archive.infolist():
            normalized = member.filename.replace('\\', '/')
            if normalized.startswith('/') or '..' in normalized.split('/'):
                raise ValueError(f'Unsafe archive path: {member.filename}')
        archive.extractall(destination)


# Kept in sync with HEATMAP_STATUS_FILE in backend_server/scripts/heatmap_processor.py
HEATMAP_STATUS_FILE = '/tmp/heatmap_status.json'
HEATMAP_STALE_AFTER_SECONDS = 180


def _heatmap_output_status() -> tuple:
    """Report the heatmap processor by the frames it actually produced.

    The unit can sit at 'active' while producing nothing (no hosts, failed uploads),
    which is exactly when the heatmap page reports stale data - so the dashboard
    reads the processor's own per-minute status file instead.
    Returns (status_override, detail); status_override is None when output is fresh.
    """
    try:
        with open(HEATMAP_STATUS_FILE, 'r', encoding='utf-8') as status_file:
            status = json.load(status_file) or {}
    except FileNotFoundError:
        return 'unknown', 'No frame generated since startup'
    except Exception as e:
        return 'unknown', f'Cannot read heatmap status: {e}'

    last_success = status.get('last_success')
    if not last_success:
        return 'stuck', status.get('last_error') or 'No frame generated yet'

    try:
        last_success_dt = datetime.fromisoformat(last_success)
        if last_success_dt.tzinfo is None:
            last_success_dt = last_success_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return 'unknown', f'Unreadable last_success: {last_success}'

    age_seconds = (datetime.now(timezone.utc) - last_success_dt).total_seconds()
    if age_seconds > HEATMAP_STALE_AFTER_SECONDS:
        detail = f'No frame for {int(age_seconds // 60)} min'
        if status.get('last_error'):
            detail = f'{detail} ({status["last_error"]})'
        return 'stuck', detail

    return None, f'Last frame {status.get("last_success_time_key", "?")} ({int(age_seconds)}s ago)'


def _build_server_service_health() -> dict:
    """Build server service status summary for dashboard cards.

    On native systemd installs each vpt-* unit is registered with systemd; on
    the containerized install path (gcloudstandalone and Docker Compose) the
    `vpt-server` container runs supervisord which manages 'flask' and
    'heatmap_processor' programs — there is no systemd unit at all, so a
    pure systemctl check returns 'not_installed' for healthy services.

    The dispatch mirrors the host-side fix (commits f67c5d2074 / 4b309b7296):
    try systemd first and fall back to supervisorctl when systemd reports
    'unknown' / 'not_installed' / 'stopped'. Each definition's candidates
    list also includes the supervisord program alias so the right name is
    tried against the right runtime.
    """
    definitions = [
        {
            'label': 'Server API',
            'critical': True,
            'optional': False,
            # systemd unit on native installs, 'flask' supervisor program inside the
            # vpt-server container, and 'server' (the legacy unit-file basename) as
            # a safety net.
            'candidates': ['vpt-server', 'flask', 'server'],
        },
        {
            'label': 'Discard Incident',
            'critical': False,
            'optional': True,
            # Discard workers are only deployed on native systemd installs — the
            # Docker image does not run them, so on gcloudstandalone these stay
            # 'not_installed' (which is the correct optional / non-critical state).
            'candidates': ['vpt-discard-incidents'],
        },
        {
            'label': 'Discard Scripts',
            'critical': False,
            'optional': True,
            # Same as Discard Incident — native-only deploy.
            'candidates': ['vpt-discard-scripts'],
        },
        {
            'label': 'Heatmap',
            'critical': False,
            'optional': True,
            # 'vpt-heatmap' on native systemd, 'heatmap_processor' supervisor
            # program inside the vpt-server container.
            'candidates': ['vpt-heatmap', 'heatmap_processor'],
        },
    ]

    services = []
    for definition in definitions:
        resolved_name = definition['candidates'][0]
        mapped_status = 'not_installed'
        runtime = 'service'

        status_info = _check_linux_service(definition['candidates'])
        # On the containerized host systemd has no knowledge of vpt-* units;
        # supervisord is the source of truth. Mirror the host-side dispatch
        # in backend_host/src/lib/utils/system_info_utils.py: trust supervisorctl
        # when systemd returns unknown / not_installed / stopped.
        if status_info.get('status') in ('unknown', 'not_installed', 'stopped'):
            sup_info = _check_supervisor_service(definition['candidates'])
            if sup_info.get('status') not in ('unknown', 'not_installed'):
                status_info = sup_info

        mapped_status = status_info.get('status', 'not_installed')
        runtime = status_info.get('runtime', 'service')
        resolved_name = status_info.get('resolved_name') or resolved_name

        detail = ''
        # Only the heatmap has a per-minute output signal to check; an 'active' unit
        # that stopped producing frames must not read as healthy on the dashboard.
        if definition['label'] == 'Heatmap' and mapped_status == 'active':
            override, detail = _heatmap_output_status()
            if override:
                mapped_status = override

        services.append({
            'name': definition['candidates'][0],
            'label': definition['label'],
            'status': mapped_status,
            'detail': detail,
            'critical': definition['critical'],
            'optional': definition['optional'],
            'runtime': runtime,
            'resolved_name': resolved_name,
        })

    non_optional_states = [s['status'] for s in services if not s['optional']]
    if any(state in {'error', 'stopped', 'not_installed'} for state in non_optional_states):
        overall = 'error'
    elif any(state in {'stuck', 'unknown'} for state in non_optional_states):
        overall = 'degraded'
    else:
        overall = 'online'

    return {'overall_status': overall, 'services': services}


@server_system_bp.route('/source/detect', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_detect')
def source_detect():
    """Detect source capabilities for storage path (Git/non-Git)."""
    data = request.get_json() or {}
    storage_path = _resolve_storage_path(data.get('storage_path'))
    exists = os.path.isdir(storage_path)
    git_info = _read_git_head_info(storage_path)
    return jsonify({
        'success': True,
        'storage_path': storage_path,
        'path_exists': exists,
        'branches': _list_git_branches(storage_path) if git_info.get('is_git_repo') else [],
        'origin_url': _read_git_origin_url(storage_path) if git_info.get('is_git_repo') else None,
        'allowed_git_organization': _git_source_organization(),
        **git_info,
    }), 200


@server_system_bp.route('/source/git/repositories', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_git_repositories')
def source_git_repositories():
    """List deployment repositories permitted by the server-side allow-list."""
    repositories, warning = _list_allowed_git_source_repositories()
    return jsonify({
        'success': True,
        'organization': _git_source_organization(),
        'repositories': repositories,
        'warning': warning,
    }), 200


@server_system_bp.route('/source/git/remote', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_git_remote')
def source_git_remote():
    """Reconfigure origin for an existing checkout, then prove it can fetch.

    This deliberately does not clone or replace the source directory.  It only repairs
    an existing checkout's origin, and accepts GitHub URLs in the approved org/repo family.
    """
    data = request.get_json() or {}
    storage_path = _resolve_storage_path(data.get('storage_path'))
    remote_url = str(data.get('remote_url', '')).strip()
    if not os.path.isdir(storage_path):
        return jsonify({'success': False, 'error': f'Storage path not found: {storage_path}'}), 404
    if not _read_git_head_info(storage_path).get('is_git_repo'):
        return jsonify({'success': False, 'error': f'No .git repo found at: {storage_path}'}), 400
    if not _parse_allowed_git_remote(remote_url):
        return jsonify({
            'success': False,
            'error': (
                f'Remote must be github.com/{_git_source_organization()}/virtualpytest* '
                f'or a repository beginning with vpt-'
            ),
        }), 400

    before_url = _read_git_origin_url(storage_path)
    command_log = []
    remote_changed = False
    try:
        for command in (
            (
                ['git', '-C', storage_path, 'remote', 'set-url', 'origin', remote_url]
                if before_url else ['git', '-C', storage_path, 'remote', 'add', 'origin', remote_url]
            ),
            ['git', '-C', storage_path, 'fetch', 'origin', '--prune'],
        ):
            proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=180)
            command_log.append({'cmd': ' '.join(command[:6]), 'returncode': proc.returncode})
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or 'git command failed')[-400:])
            remote_changed = True
    except Exception as exc:
        if remote_changed:
            restore_command = (
                ['git', '-C', storage_path, 'remote', 'set-url', 'origin', before_url]
                if before_url else ['git', '-C', storage_path, 'remote', 'remove', 'origin']
            )
            subprocess.run(restore_command, capture_output=True, text=True, check=False, timeout=30)
        return jsonify({
            'success': False,
            'error': f'Remote update failed: {exc}',
            'storage_path': storage_path,
            'origin_url_before': before_url,
            'origin_url': _read_git_origin_url(storage_path),
            'commands': command_log,
        }), 500

    return jsonify({
        'success': True,
        'storage_path': storage_path,
        'origin_url_before': before_url,
        'origin_url': _read_git_origin_url(storage_path),
        'branches': _list_git_branches(storage_path),
        'message': 'Origin updated and fetched',
    }), 200


@server_system_bp.route('/source/git/branches', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_git_branches')
def source_git_branches():
    """List available git branches for the storage path."""
    data = request.get_json() or {}
    storage_path = _resolve_storage_path(data.get('storage_path'))
    if not os.path.isdir(storage_path):
        return jsonify({'success': False, 'error': f'Storage path not found: {storage_path}'}), 404
    git_info = _read_git_head_info(storage_path)
    if not git_info.get('is_git_repo'):
        return jsonify({'success': False, 'error': f'No .git repo found at: {storage_path}'}), 400
    return jsonify({
        'success': True,
        'storage_path': storage_path,
        'branches': _list_git_branches(storage_path),
        'current_branch': git_info.get('branch'),
    }), 200


@server_system_bp.route('/source/git/prepare', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_git_prepare')
def source_git_prepare():
    """Prepare storage source from Git."""
    data = request.get_json() or {}
    storage_path = _resolve_storage_path(data.get('storage_path'))
    git_ref = str(data.get('git_ref', '')).strip()
    force_reset = _coerce_bool(data.get('force_reset', False), default=False)

    if not os.path.isdir(storage_path):
        return jsonify({'success': False, 'error': f'Storage path not found: {storage_path}'}), 404
    git_info_before = _read_git_head_info(storage_path)
    if not git_info_before.get('is_git_repo'):
        return jsonify({'success': False, 'error': f'No .git repo found at: {storage_path}'}), 400
    if not git_ref:
        return jsonify({'success': False, 'error': 'Select a remote branch before preparing Git source'}), 400

    command_log = []

    def _run(cmd: list[str], timeout: int = 120) -> None:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        command_log.append({
            'cmd': ' '.join(cmd),
            'returncode': proc.returncode,
            'stdout': (proc.stdout or '')[-1000:],
            'stderr': (proc.stderr or '')[-1000:],
        })
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or 'git command failed')[-400:])

    def _fix_permissions():
        """Fix ownership/permissions on shared storage so git can write."""
        chown_result = subprocess.run(['sudo', '-n', 'chown', '-R', 'vpt_user:vpt_shared', storage_path], capture_output=True, text=True, check=False, timeout=60)
        chmod_result = subprocess.run(['sudo', '-n', 'chmod', '-R', 'g+w', storage_path], capture_output=True, text=True, check=False, timeout=60)
        if chown_result.returncode != 0:
            print(f'[@server_system:source_git_prepare] chown failed (rc={chown_result.returncode}): {chown_result.stderr}')
        if chmod_result.returncode != 0:
            print(f'[@server_system:source_git_prepare] chmod failed (rc={chmod_result.returncode}): {chmod_result.stderr}')

    try:
        _fix_permissions()
        _run(['git', '-C', storage_path, 'fetch', 'origin', '--prune'], timeout=180)
        remote_ref = f'origin/{git_ref}'
        available_refs = _list_git_branches(storage_path)
        if git_ref not in available_refs:
            raise RuntimeError(f'Branch is not available from origin: {git_ref}')
        if force_reset:
            # Destructive recovery is opt-in. It is useful after a failed normal pull,
            # but must never silently discard a local edit during ordinary updates.
            _run(['git', '-C', storage_path, 'checkout', '--force', '-B', git_ref, remote_ref], timeout=120)
            _run(['git', '-C', storage_path, 'reset', '--hard', remote_ref], timeout=120)
        else:
            _run(['git', '-C', storage_path, 'checkout', git_ref], timeout=120)
            _run(['git', '-C', storage_path, 'pull', '--ff-only', 'origin', git_ref], timeout=180)
    except Exception as exc:
        print(f'[@server_system:source_git_prepare] failed: {exc}')
        reset_required = any(
            f' {entry.get("cmd", "")} '.find(' checkout ') >= 0
            or f' {entry.get("cmd", "")} '.find(' pull ') >= 0
            for entry in command_log
        )
        return jsonify({
            'success': False,
            'error': 'Git prepare failed (see server log)',
            'storage_path': storage_path,
            'before': git_info_before,
            'reset_required': reset_required,
            'commands': command_log[-5:],
        }), 500

    # VERSION.txt is source-controlled and should arrive from git as-is.
    # Do not rewrite it here, otherwise deploy paths diverge from the committed
    # current:/previous: format shown in the UI.

    git_info_after = _read_git_head_info(storage_path)
    before_commit = git_info_before.get('commit')
    after_commit = git_info_after.get('commit')
    already_up_to_date = bool(before_commit and after_commit and before_commit == after_commit)
    pull_output = ''
    for entry in reversed(command_log):
        if ' pull ' in f" {entry.get('cmd', '')} ":
            pull_output = ((entry.get('stdout') or '') + '\n' + (entry.get('stderr') or '')).strip()
            break
    diff_files = _read_git_diff_summary(storage_path, before_commit, after_commit)
    return jsonify({
        'success': True,
        'storage_path': storage_path,
        'before': git_info_before,
        'after': git_info_after,
        'already_up_to_date': already_up_to_date,
        'pull_output': pull_output or ('Already up to date.' if already_up_to_date else ''),
        'diff_files': diff_files,
        'commands': command_log[-5:],
        'message': (
            'Storage source hard-reset from selected git branch'
            if force_reset else 'Storage source fetched and fast-forwarded from selected git branch'
        ),
    }), 200


@server_system_bp.route('/source/zip/upload', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_zip_upload')
def source_zip_upload():
    """Upload source zip to temporary upload directory."""
    file = request.files.get('file')
    storage_path = _resolve_storage_path(request.form.get('storage_path'))
    if not file:
        return jsonify({'success': False, 'error': 'Missing file form-data field'}), 400
    filename = file.filename or 'source.zip'
    if not filename.lower().endswith('.zip'):
        return jsonify({'success': False, 'error': 'Only .zip files are supported'}), 400

    upload_id = uuid.uuid4().hex
    upload_dir = os.path.join(SOURCE_UPLOAD_ROOT, upload_id)
    os.makedirs(upload_dir, exist_ok=True)
    zip_path = os.path.join(upload_dir, 'source.zip')
    file.save(zip_path)

    return jsonify({
        'success': True,
        'upload_id': upload_id,
        'storage_path': storage_path,
        'zip_path': zip_path,
        'message': 'Zip uploaded',
    }), 200


@server_system_bp.route('/source/zip/validate', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_zip_validate')
def source_zip_validate():
    """Validate uploaded zip archive and expected repository structure."""
    data = request.get_json() or {}
    upload_id = str(data.get('upload_id', '')).strip()
    if not upload_id:
        return jsonify({'success': False, 'error': 'upload_id is required'}), 400
    upload_dir = os.path.join(SOURCE_UPLOAD_ROOT, upload_id)
    zip_path = os.path.join(upload_dir, 'source.zip')
    if not os.path.isfile(zip_path):
        return jsonify({'success': False, 'error': 'Upload not found'}), 404

    extract_dir = os.path.join(upload_dir, 'extract')
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        _safe_extract_zip(zip_path, extract_dir)
    except Exception as exc:
        print(f'[@server_system:source_zip_validate] rejected: {exc}')
        return jsonify({'success': False, 'error': 'Zip integrity/safety validation failed (see server log)'}), 400

    entries = [entry for entry in os.listdir(extract_dir) if entry not in ['__MACOSX']]
    extracted_root = extract_dir
    if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
        extracted_root = os.path.join(extract_dir, entries[0])

    is_valid_structure, missing_paths = _validate_expected_structure(extracted_root)
    if not is_valid_structure:
        return jsonify({
            'success': False,
            'upload_id': upload_id,
            'error': 'Zip missing required repository structure',
            'missing_paths': missing_paths,
        }), 400

    return jsonify({
        'success': True,
        'upload_id': upload_id,
        'extract_root': extracted_root,
        'message': 'Zip validation passed',
    }), 200


@server_system_bp.route('/source/zip/apply', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:source_zip_apply')
def source_zip_apply():
    """Apply validated zip content to storage source path."""
    data = request.get_json() or {}
    upload_id = str(data.get('upload_id', '')).strip()
    storage_path = _resolve_storage_path(data.get('storage_path'))
    if not upload_id:
        return jsonify({'success': False, 'error': 'upload_id is required'}), 400
    upload_dir = os.path.join(SOURCE_UPLOAD_ROOT, upload_id)
    extract_dir = os.path.join(upload_dir, 'extract')
    if not os.path.isdir(extract_dir):
        return jsonify({'success': False, 'error': 'Upload not validated yet'}), 400

    entries = [entry for entry in os.listdir(extract_dir) if entry not in ['__MACOSX']]
    source_root = extract_dir
    if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
        source_root = os.path.join(extract_dir, entries[0])

    is_valid_structure, missing_paths = _validate_expected_structure(source_root)
    if not is_valid_structure:
        return jsonify({
            'success': False,
            'error': 'Extracted zip failed structure validation',
            'missing_paths': missing_paths,
        }), 400

    os.makedirs(storage_path, exist_ok=True)
    rsync = subprocess.run(
        [
            'rsync', '-a', '--delete',
            '--exclude=.env',
            '--exclude=venv',
            '--exclude=node_modules',
            '--exclude=.git',
            f'{source_root}/',
            f'{storage_path}/',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    if rsync.returncode != 0:
        return jsonify({
            'success': False,
            'error': 'Failed to apply zip to storage path',
            'stdout': rsync.stdout[-1500:],
            'stderr': rsync.stderr[-1500:],
        }), 500

    return jsonify({
        'success': True,
        'storage_path': storage_path,
        'message': 'Zip source applied to storage',
    }), 200


@server_system_bp.route('/register', methods=['POST'])
@handle_route_exceptions('server_system:register')
def register_host():
    """Host registers with server"""
    host_info = request.get_json()
    print(f"[@route:register_host] Host registration request received:")
    print(f"   Host info keys: {list(host_info.keys()) if host_info else 'None'}")
    print(f"   Host name: {host_info.get('host_name', 'Not provided')}")
    print(f"   Host URL: {host_info.get('host_url', 'Not provided')}")
    devices_list = host_info.get('devices', [])
    print(f"   Devices: {len(devices_list)} device(s)")
    if len(devices_list) == 0:
        print(f"   ✅ Host with no devices - this is valid")
    required_fields = ['host_url', 'host_name', 'devices']
    missing_fields = []
    for field in required_fields:
        if field not in host_info:
            missing_fields.append(field)
        elif field == 'devices':
            if not isinstance(host_info[field], list):
                missing_fields.append(field)
            else:
                print(f"   ✅ Devices field validation passed (list with {len(host_info[field])} items)")
        elif not host_info[field]:
            missing_fields.append(field)
    if missing_fields:
        error_msg = f'Missing required fields: {", ".join(missing_fields)}'
        print(f"❌ [SERVER] Registration failed: {error_msg}")
        return jsonify({'error': error_msg}), 400
    host_port = host_info.get('host_port', '6109')
    devices = host_info.get('devices', [])
    print(f"[@route:register_host] Host configuration:")
    print(f"   Host URL (browser): {host_info['host_url']}")
    print(f"   Host API URL (server): {host_info.get('host_api_url', 'NOT PROVIDED - will fallback to host_url')}")
    print(f"   Host Port: {host_port}")
    print(f"   Devices: {len(devices)} devices")
    devices_with_controllers = []
    for device in devices:
        device_name = device.get('device_name')
        device_model = device.get('device_model')
        device_capabilities = device.get('device_capabilities', {})
        print(f"[@route:register_host] Processing device: {device_name} ({device_model})")
        print(f"[@route:register_host] Device capabilities: {device_capabilities}")
            
        video_stream_path = device.get('video_stream_path')
        video_capture_path = device.get('video_capture_path')
        video = device.get('video')
        print(f"[@route:register_host] Video paths from host: video_stream_path={video_stream_path}, video_capture_path={video_capture_path}")
        device_verification_types = device.get('device_verification_types', {})
        device_action_types = device.get('device_action_types', {})
        device_with_controllers = {
            'device_id': device.get('device_id'),
            'device_name': device_name,
            'device_model': device_model,
            'device_ip': device.get('device_ip'),
            'device_port': device.get('device_port'),
            'ir_type': device.get('ir_type'),
            'video_stream_path': device.get('video_stream_path'),
            'video_capture_path': device.get('video_capture_path'),
            'video': device.get('video'),
            'preferred_userinterface': device.get('preferred_userinterface'),
            'preferred_variant': device.get('preferred_variant'),
            'device_farm_provider': device.get('device_farm_provider'),
            'device_capabilities': device_capabilities,
            'device_verification_types': device_verification_types,
            'device_action_types': device_action_types
        }
        devices_with_controllers.append(device_with_controllers)
    host_type = host_info.get('host_type', 'host_vnc')
    device_type = host_info.get('device_type', 'host_device')
    host_object: Host = {
        'host_name': host_info['host_name'],
        'description': f"Host: {host_info['host_name']} with {len(devices)} device(s)",
        'host_url': host_info['host_url'],
        'host_api_url': host_info.get('host_api_url'),
        'host_port': int(host_port),
        'host_type': host_type,
        'device_type': device_type,
        'devices': devices_with_controllers,
        'device_count': len(devices),
        'status': 'online',
        'last_seen': time.time(),
        'registered_at': datetime.now().isoformat(),
        'system_stats': host_info.get('system_stats', {}),
        'deployed_version': host_info.get('deployed_version'),
        'isLocked': False,
        'lockedBy': None,
        'lockedAt': None,
    }
    host_manager = get_host_manager()
    success = host_manager.register_host(host_info['host_name'], host_object)
    from routes.server_device_flags_routes import upsert_device_on_registration
    for device in devices_with_controllers:
        upsert_device_on_registration(host_info['host_name'], device['device_id'], device['device_name'])
    if not success:
        return jsonify({'error': f"Failed to register host {host_info['host_name']}"}), 500

    # Reconcile stale server-side execution locks left by this host's previous
    # process (host restarted mid-execution → its completion callback never fired).
    # Locks acquired before the host's current process start are dead and reaped.
    process_start_time = host_info.get('process_start_time')
    if process_start_time:
        try:
            from backend_server.src.lib.utils.lock_utils import reconcile_host_locks
            reaped = reconcile_host_locks(host_info['host_name'], float(process_start_time))
            for lock_info in reaped:
                emit_system_update('lock_changed', {
                    'host_name': lock_info.get('host_name'),
                    'device_id': lock_info.get('device_id'),
                    'is_locked': False,
                    'lock_info': lock_info,
                })
            if reaped:
                print(f"🔓 [register_host] Reconciled {len(reaped)} stale lock(s) for {host_info['host_name']} after restart")
        except Exception as reconcile_err:
            print(f"⚠️ [register_host] Lock reconciliation failed for {host_info['host_name']}: {reconcile_err}")

    emit_system_update('host_registered', {'host_name': host_info['host_name']})
    return jsonify({
        'status': 'success',
        'message': 'Host registered successfully',
        'host_name': host_info['host_name'],
        'host_data': host_object
    }), 200


@server_system_bp.route('/unregister', methods=['POST'])
@handle_route_exceptions('server_system:unregister')
def unregister_host():
    """Host unregisters from server"""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'error': 'Missing host_name'}), 400
    host_manager = get_host_manager()
    success = host_manager.unregister_host(host_name)
    if success:
        print(f"🔌 Host unregistered: {host_name}")
        emit_system_update('host_unregistered', {'host_name': host_name})
        return jsonify({'status': 'success', 'message': 'Host unregistered successfully'}), 200
    return jsonify({'error': f'Host not found with host_name: {host_name}'}), 404


@server_system_bp.route('/health', methods=['GET'])
@handle_route_exceptions('server_system:health_check')
def health_check():
    """Health check endpoint for clients"""
    system_stats = get_server_system_stats(skip_speedtest=True)
    
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'mode': os.getenv('SERVER_MODE', 'server'),
        'system_stats': system_stats
    }), 200


DB_BACKUP_STATUS_FILE = '/tmp/vpt_last_backup_status.json'
DB_BACKUP_MAX_AGE_HOURS = 26  # alert if last backup is older than this


@server_system_bp.route('/backup/report', methods=['POST'])
@handle_route_exceptions('server_system:backup_report')
def backup_report():
    """Called by the backup cron script after each successful backup."""
    data = request.get_json(silent=True) or {}
    data['reported_at'] = datetime.utcnow().isoformat() + 'Z'
    with open(DB_BACKUP_STATUS_FILE, 'w') as f:
        json.dump(data, f)
    return jsonify({'ok': True}), 200


@server_system_bp.route('/backup/status', methods=['GET'])
@handle_route_exceptions('server_system:backup_status')
def backup_status():
    """Return the status of the last database backup."""
    from datetime import timezone
    status_path = Path(DB_BACKUP_STATUS_FILE)
    if not status_path.exists():
        return jsonify({'status': 'error', 'detail': 'No backup status — backup may never have run'}), 200

    try:
        with open(status_path) as f:
            data = json.load(f)
    except Exception as e:
        print(f'[@server_system:backup_status] unreadable status file: {e}')
        return jsonify({'status': 'error', 'detail': 'Could not read backup status file'}), 200

    ts_iso = data.get('timestamp_iso', '')
    age_hours = None
    if ts_iso:
        try:
            ts = datetime.fromisoformat(ts_iso.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        except Exception:
            pass

    status = 'ok'
    detail = f"Last backup: {data.get('filename', '?')} ({data.get('size', '?')})"
    if age_hours is not None and age_hours > DB_BACKUP_MAX_AGE_HOURS:
        status = 'error'
        detail = f"Last backup {age_hours:.0f}h ago — expected daily. File: {data.get('filename', '?')}"

    return jsonify({
        'status': status,
        'detail': detail,
        'filename': data.get('filename'),
        'size': data.get('size'),
        'age_hours': round(age_hours, 1) if age_hours is not None else None,
    }), 200


@server_system_bp.route('/stats', methods=['GET'])
@handle_route_exceptions('server_system:get_stats')
def get_stats():
    """System statistics endpoint"""
    system_stats = get_server_system_stats(skip_speedtest=True)
    
    return jsonify({
        'stats': system_stats,
        'timestamp': time.time(),
        'mode': os.getenv('SERVER_MODE', 'server'),
    }), 200


# A host pings the server every HOST_PING_INTERVAL_SECONDS (60s) and is only
# evicted from the registry after 180s (cleanup_stale_hosts). Between those
# thresholds the registry still holds the last heartbeat's status/stats, so a
# rebooting host would otherwise display as "online" the whole time. Treat a
# host whose heartbeat is older than this as offline for DISPLAY purposes (it
# stays registered until the 180s eviction).
STALE_HOST_DISPLAY_SECONDS = 90


def _host_heartbeat_is_stale(host_info) -> bool:
    try:
        last_seen = float(host_info.get('last_seen') or 0)
    except (TypeError, ValueError):
        return False
    return last_seen > 0 and (time.time() - last_seen) > STALE_HOST_DISPLAY_SECONDS


@server_system_bp.route('/getAllHosts', methods=['GET'])
@handle_route_exceptions('server_system:getAllHosts')
def getAllHosts():
    """
    Return all registered hosts - single REST endpoint for host listing
    
    Query parameters:
        include_actions: boolean (default: false) - Include device_action_types and device_verification_types
                        Set to true only when you need action/verification schemas (for control pages)
        include_system_stats: boolean (default: false) - Include full system stats and device details
                        Set to true when you need system metrics (CPU, RAM, disk) for dashboard/monitoring
    """
    include_actions = request.args.get('include_actions', 'false').lower() == 'true'
    include_system_stats = request.args.get('include_system_stats', 'false').lower() == 'true'
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    cache_key = f"server_system:getAllHosts:{include_actions}:{include_system_stats}"
    if not force_refresh:
        cached_response = get_cached_response(cache_key, CACHE_CONFIG['VERY_SHORT_TTL'])
        if cached_response is not None:
            return jsonify(cached_response), 200
    host_manager = get_host_manager()
    host_manager.validate_restored_hosts()
    # Remove hosts not seen for 3 minutes (e.g. ungraceful shutdown)
    stale_removed = host_manager.cleanup_stale_hosts()
    for removed_name in stale_removed:
        emit_system_update('host_unregistered', {'host_name': removed_name})
    all_hosts = host_manager.get_all_hosts()
    valid_hosts = []
    required_fields = ['host_name', 'host_url']
    server_deploy_state = _read_server_deploy_state()
    frontend_deploy_state = _read_frontend_remote_deploy_state()
    for host_info in all_hosts.values():
        is_valid = True
        for field in required_fields:
            if field not in host_info or not host_info[field]:
                print(f"⚠️ [HOSTS] Host {host_info.get('host_name')} missing required field: {field}")
                is_valid = False
                break
        if is_valid:
            if not include_actions and not include_system_stats and 'devices' in host_info:
                # Use operational_status if available, otherwise fall back to raw status
                system_stats = host_info.get('system_stats', {})
                operational_status = system_stats.get('operational_status') if system_stats else None
                computed_status = operational_status if operational_status else host_info.get('status', 'online')
                if _host_heartbeat_is_stale(host_info):
                    computed_status = 'offline'

                lightweight_host = {
                    'host_name': host_info.get('host_name'),
                    'host_url': host_info.get('host_url'),
                    'host_api_url': host_info.get('host_api_url'),
                    'host_port': host_info.get('host_port'),
                    'host_type': host_info.get('host_type', 'host_vnc'),
                    'device_type': host_info.get('device_type', 'host_device'),
                    'status': computed_status,
                    'deployed_version': host_info.get('deployed_version'),
                    'device_count': host_info.get('device_count', 0),
                    'last_seen': host_info.get('last_seen'),
                    'registered_at': host_info.get('registered_at'),
                    'system_stats': {
                        'platform': host_info.get('system_stats', {}).get('platform', ''),
                        # Carried in the lightweight payload so the modal can gate the HD+
                        # quality button without a full-stats fetch (VAAPI hosts only).
                        'hardware_encode': host_info.get('system_stats', {}).get('hardware_encode', False),
                    } if host_info.get('system_stats') else {},
                    'devices': []
                }
                for device in host_info.get('devices', []):
                    lightweight_host['devices'].append({
                        'device_id': device.get('device_id'),
                        'device_name': device.get('device_name'),
                        'device_model': device.get('device_model'),
                        'ir_type': device.get('ir_type'),
                        'device_capabilities': device.get('device_capabilities'),
                        'video_stream_path': device.get('video_stream_path'),
                        'video_capture_path': device.get('video_capture_path'),
                        'preferred_userinterface': device.get('preferred_userinterface'),
                        'preferred_variant': device.get('preferred_variant'),
                        'device_farm_provider': device.get('device_farm_provider'),
                        'has_running_deployment': device.get('has_running_deployment', False),
                    })
                valid_hosts.append(lightweight_host)
            elif include_system_stats and not include_actions and 'devices' in host_info:
                # Use operational_status if available, otherwise fall back to raw status
                system_stats = host_info.get('system_stats', {})
                operational_status = system_stats.get('operational_status') if system_stats else None
                computed_status = operational_status if operational_status else host_info.get('status', 'online')
                if _host_heartbeat_is_stale(host_info):
                    computed_status = 'offline'
                    if system_stats:
                        # Shallow copy so the override doesn't mutate the registry.
                        system_stats = {**system_stats, 'operational_status': 'offline'}

                dashboard_host = {
                    'host_name': host_info.get('host_name'),
                    'host_url': host_info.get('host_url'),
                    'host_api_url': host_info.get('host_api_url'),
                    'host_port': host_info.get('host_port'),
                    'host_type': host_info.get('host_type', 'host_vnc'),
                    'device_type': host_info.get('device_type', 'host_device'),
                    'status': computed_status,
                    'deployed_version': host_info.get('deployed_version'),
                    'device_count': host_info.get('device_count', 0),
                    'last_seen': host_info.get('last_seen'),
                    'registered_at': host_info.get('registered_at'),
                    'system_stats': system_stats,
                    'devices': []
                }
                for device in host_info.get('devices', []):
                    dashboard_host['devices'].append({
                        'device_id': device.get('device_id'),
                        'device_name': device.get('device_name'),
                        'device_model': device.get('device_model'),
                        'device_ip': device.get('device_ip'),
                        'device_port': device.get('device_port'),
                        'device_capabilities': device.get('device_capabilities'),
                        'video_stream_path': device.get('video_stream_path'),
                        'video_capture_path': device.get('video_capture_path'),
                        'video_fps': device.get('video_fps'),
                        'preferred_userinterface': device.get('preferred_userinterface'),
                        'preferred_variant': device.get('preferred_variant'),
                        'has_running_deployment': device.get('has_running_deployment', False),
                        'ir_type': device.get('ir_type'),
                        'device_farm_provider': device.get('device_farm_provider'),
                    })
                valid_hosts.append(dashboard_host)
            else:
                valid_hosts.append(host_info)
    print(f"🖥️ [HOSTS] Returning {len(valid_hosts)} valid hosts (include_actions={include_actions}, include_system_stats={include_system_stats})")
    for host in valid_hosts:
        device_count = host.get('device_count', 0)
        print(f"   Host: {host['host_name']} ({host['host_url']}) - {device_count} device(s)")

    # Attach latest corrected device info (from get_info scans) onto each device
    # so the frontend tooltip needs no separate fetch. Best-effort — host listing
    # must never break if the device-info views are unavailable.
    try:
        from shared.src.lib.database import device_info_overrides_db
        from shared.src.lib.utils.app_utils import get_team_id
        team_id = get_team_id()
        info_map = device_info_overrides_db.get_corrected_info_map(team_id)
        # Gateway info is the device's network environment — keyed per device too
        # (different devices on a host can sit behind different gateways).
        gateway_map = device_info_overrides_db.get_corrected_gateway_map(team_id)
        if info_map or gateway_map:
            for host in valid_hosts:
                for device in host.get('devices', []) or []:
                    key = (device.get('device_name'), host.get('host_name'))
                    entry = info_map.get(key)
                    if entry and entry.get('info'):
                        device['device_info'] = entry['info']
                        # Link back to the get_info scan these values came from,
                        # plus its captured artifacts (final-state screenshot etc.).
                        device['device_info_report'] = {
                            'report_url': entry.get('report_url'),
                            'scanned_at': entry.get('scanned_at'),
                            'initial_screenshot_url': entry.get('initial_screenshot_url'),
                            'final_screenshot_url': entry.get('final_screenshot_url'),
                            'video_url': entry.get('video_url'),
                        }
                    gw_entry = gateway_map.get(key)
                    if gw_entry and gw_entry.get('info'):
                        device['gateway_info'] = gw_entry['info']
                        device['gateway_info_report'] = {
                            'report_url': gw_entry.get('report_url'),
                            'scanned_at': gw_entry.get('scanned_at'),
                            'initial_screenshot_url': gw_entry.get('initial_screenshot_url'),
                            'final_screenshot_url': gw_entry.get('final_screenshot_url'),
                            'video_url': gw_entry.get('video_url'),
                        }
    except Exception as e:
        print(f"⚠️ [HOSTS] Skipped device_info attach: {e}")
    server_name = os.getenv('SERVER_NAME', 'Unknown Server')
    server_url = os.getenv('SERVER_URL', 'Unknown URL')
    server_port = os.getenv('SERVER_PORT', 'Unknown Port')
    server_info = {
        'server_name': server_name,
        'server_url': server_url,
        'server_port': server_port,
        'deployed_version': server_deploy_state.get('deployed_version'),
        'last_deploy_at': server_deploy_state.get('last_deploy_at'),
        'deploy_state': server_deploy_state.get('deploy_state'),
    }
    if include_system_stats:
        latest_server_stats = get_latest_system_metrics(os.getenv('SERVER_NAME', 'server'))
        if latest_server_stats:
            server_info['system_stats'] = {k: v for k, v in latest_server_stats.items()
                                          if k not in ['id', 'host_name', 'timestamp', 'created_at']}
        server_info['service_health'] = _build_server_service_health()
    response_payload = {
        'success': True,
        'server_info': server_info,
        'frontend_info': frontend_deploy_state,
        'hosts': valid_hosts,
    }
    set_cached_response(cache_key, response_payload)
    return jsonify(response_payload), 200


@server_system_bp.route('/getDeviceActions', methods=['GET'])
@handle_route_exceptions('server_system:getDeviceActions')
def getDeviceActions():
    """
    Return action schemas for a specific device - lightweight endpoint for editing
    
    Query parameters:
    - host_name: Name of the host
    - device_id: ID of the device
    - team_id: Team ID (required for multi-tenancy)
    
    Returns:
    {
        "success": true,
        "device_action_types": {...},
        "device_verification_types": {...}
    }
    """
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id')
    team_id = request.args.get('team_id')
    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'Missing required parameters: host_name and device_id'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    devices = host_data.get('devices', [])
    device_data = next((d for d in devices if d.get('device_id') == device_id), None)
    if not device_data:
        return jsonify({'success': False, 'error': f'Device {device_id} not found on host {host_name}'}), 404
    return jsonify({
        'success': True,
        'host_name': host_name,
        'device_id': device_id,
        'device_model': device_data.get('device_model'),
        'device_action_types': device_data.get('device_action_types', {}),
        'device_verification_types': device_data.get('device_verification_types', {})
    }), 200


def _check_stale_locks_for_host(host_name: str, host_data: dict):
    """Liveness probe: for each script/campaign-locked device on this host,
    ask the host if the job is still running. Release stale locks.

    Runs in a background thread so it doesn't block the ping response.
    """
    from backend_server.src.lib.utils.lock_utils import (
        get_all_locked_devices,
        force_unlock_device,
    )
    from shared.src.lib.utils.build_url_utils import call_host

    now = time.time()
    all_locks = get_all_locked_devices()

    for device_key, lock_info in all_locks.items():
        if not device_key.startswith(f"{host_name}:"):
            continue

        owner_type = lock_info.get('owner_type')
        if owner_type not in ('script_execution', 'deployment_execution'):
            continue

        # Grace period — don't probe locks that are too fresh
        locked_at = float(lock_info.get('locked_at', 0) or 0)
        if now - locked_at < _STALE_LOCK_GRACE_PERIOD_SECONDS:
            continue

        device_id = lock_info.get('device_id') or device_key.split(':', 1)[-1]

        try:
            resp_data, status_code = call_host(
                host_data,
                f'/host/system/device/{device_id}/is_busy',
                method='GET',
                timeout=10,
            )

            if status_code != 200:
                print(f"⚠️ [STALE_LOCK] is_busy check failed for {device_key}: HTTP {status_code}")
                continue

            if resp_data.get('busy'):
                continue  # still running, lock is valid

            # Device is NOT busy but lock exists → stale lock
            lock_age_min = int((now - locked_at) / 60)
            lock_reason = lock_info.get('lock_reason', 'unknown')
            print(f"🧹 [STALE_LOCK] Releasing stale lock on {device_key} "
                  f"(age: {lock_age_min}min, reason: {lock_reason}, owner: {owner_type})")

            force_unlock_device(host_name, device_id)
            emit_system_update('lock_changed', {
                'host_name': host_name,
                'device_id': device_id,
                'is_locked': False,
                'released_reason': 'stale_lock_liveness_probe',
                'lock_info': lock_info,
            })

        except Exception as exc:
            print(f"⚠️ [STALE_LOCK] Error probing {device_key}: {exc}")


@server_system_bp.route('/ping', methods=['POST'])
@handle_route_exceptions('server_system:ping')
def client_ping():
    """Client sends periodic health ping to server"""
    ping_data = request.get_json() or {}
    if not ping_data:
        return jsonify({'error': 'No ping data received'}), 400
    host_name = ping_data.get('host_name')
    if not host_name:
        return jsonify({'error': 'Missing host_name in ping'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        print(f"📍 [PING] Unknown host {host_name} sending registration request")
        return jsonify({'status': 'not_registered', 'message': 'Host not registered, please register first', 'action': 'register'}), 404
    success = host_manager.update_host_ping(host_name, ping_data)
    if not success:
        return jsonify({'error': 'Failed to update host ping'}), 500
    now = time.time()
    last_emitted = _last_ping_emit_by_host.get(host_name, 0)
    if now - last_emitted >= _PING_EMIT_MIN_INTERVAL_SECONDS:
        emit_system_update('host_ping', {'host_name': host_name})
        _last_ping_emit_by_host[host_name] = now

    # Stale lock liveness probe (throttled to once per minute per host)
    last_check = _last_stale_lock_check_by_host.get(host_name, 0)
    if now - last_check >= _STALE_LOCK_CHECK_INTERVAL_SECONDS:
        _last_stale_lock_check_by_host[host_name] = now
        threading.Thread(
            target=_check_stale_locks_for_host,
            args=(host_name, host_data),
            daemon=True,
            name=f"stale-lock-probe-{host_name}",
        ).start()

    per_device_metrics = ping_data.get('per_device_metrics', [])
    device_count = len(per_device_metrics) if per_device_metrics else 0
    print(f"📊 [PING] Host {host_name} reported {device_count} devices")
    print(f"💓 [PING] Host {host_name} ping received - status updated")
    return jsonify({'status': 'success', 'message': 'Ping received successfully', 'server_time': time.time()}), 200


@server_system_bp.route('/executionEvent', methods=['POST'])
@handle_route_exceptions('server_system:executionEvent')
def execution_event():
    """
    Receive host-side async execution lifecycle events and rebroadcast via /system socket.
    """
    data = request.get_json() or {}
    execution_id = data.get('execution_id')
    execution_type = data.get('execution_type')
    status = data.get('status')

    if not execution_id or not execution_type or not status:
        return jsonify({
            'success': False,
            'error': 'execution_id, execution_type, and status are required'
        }), 400

    emit_system_update('execution_update', {
        'domain': 'execution',
        'execution_type': execution_type,
        'execution_id': execution_id,
        'status': status,
        'host_name': data.get('host_name'),
        'device_id': data.get('device_id'),
        'team_id': data.get('team_id'),
        'progress': data.get('progress'),
        'message': data.get('message'),
        'result': data.get('result'),
        'error': data.get('error'),
        'timestamp': data.get('timestamp', time.time()),
    })

    return jsonify({'success': True}), 200


# Define Host type matching Host_Types.ts
class Host(TypedDict):
    # === PRIMARY IDENTIFICATION ===
    host_name: str
    description: Optional[str]
    
    # === NETWORK CONFIGURATION ===
    host_url: str
    host_port: int
    
    # === MULTI-DEVICE CONFIGURATION ===
    devices: List[Any]  # Array of device configurations
    device_count: int
    
    # === STATUS AND METADATA ===
    status: str  # 'online' | 'offline' | 'unreachable' | 'maintenance'
    last_seen: float
    registered_at: str
    system_stats: Any  # SystemStats type
    
    # === DEVICE LOCK MANAGEMENT ===
    isLocked: bool
    lockedBy: Optional[str]
    lockedAt: Optional[float]

# =============================================================================
# SERVER SYSTEM CONTROL ROUTES
# =============================================================================

@server_system_bp.route('/restartServerService', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:restartServerService')
def restart_server_service():
    """Schedule a restart of vpt-server on this machine.

    Detached (see _schedule_server_restart) rather than a synchronous
    `systemctl restart`, which would SIGTERM this very process before the
    HTTP response could go out — the same pattern the rollback flow already
    relies on below.
    """
    _schedule_server_restart()
    return jsonify({'success': True, 'message': 'vpt-server restart scheduled'}), 200


@server_system_bp.route('/rebootServer', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:rebootServer')
def reboot_server():
    """Reboot the server machine"""
    from shared.src.lib.utils.system_utils import reboot_system
    result = reboot_system()
    return jsonify(result), 200 if result['success'] else 500


# =============================================================================
# HOST SYSTEM CONTROL PROXY ROUTES  
# =============================================================================

@server_system_bp.route('/restartHostService', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:restartHostService')
def restart_host_service_proxy():
    """Proxy restart vpt-host service request to specific host"""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, '/host/system/restartHostService', method='POST', data={}, timeout=30)
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/restartHostServices', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:restartHostServices')
def restart_host_services_proxy():
    """Proxy autofix (restart specific down services) to a specific host."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    services = data.get('services') or []
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not isinstance(services, list) or not services:
        return jsonify({'success': False, 'error': 'services (non-empty list) is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_data, '/host/system/restartService', method='POST',
        data={'services': services}, timeout=60,
    )
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/controlHostService', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:controlHostService')
def control_host_service_proxy():
    """Proxy a single-service start/stop/restart to a specific host."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    service = str(data.get('service') or '').strip()
    action = str(data.get('action') or '').strip().lower()
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not service:
        return jsonify({'success': False, 'error': 'service is required'}), 400
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'success': False, 'error': "action must be start, stop or restart"}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_data, '/host/system/controlService', method='POST',
        data={'service': service, 'action': action}, timeout=60,
    )
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/rebootHost', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:rebootHost')
def reboot_host_proxy():
    """Proxy reboot host request to specific host"""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, '/host/system/rebootHost', method='POST', data={}, timeout=10)
    if status_code == 200:
        return jsonify(response_data), 200
    if status_code == 504:
        return jsonify({'success': True, 'message': 'Reboot command sent (timeout expected)'}), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/runCommandOnHost', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:runCommandOnHost')
def run_command_on_host_proxy():
    """Proxy an admin-authored shell command/script to a single host.

    Real server-side admin enforcement (unlike the other host proxies which
    are frontend-only). `require_user_auth` resolves the role from the JWT
    `app_metadata` claim, kept in sync with profiles.role by the
    on_profile_role_sync DB trigger. The frontend issues one call per
    selected host in a sequential loop so results stream in per host and
    one slow/hung host can't hide the others."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    command = str(data.get('command') or '')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not command.strip():
        return jsonify({'success': False, 'error': 'command is required'}), 400
    try:
        timeout = max(1, min(600, int(data.get('timeout', 120))))
    except (TypeError, ValueError):
        timeout = 120

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404

    first_line = command.splitlines()[0][:120] if command.splitlines() else ''
    print(
        f"[@server_system:runCommandOnHost] "
        f"user={getattr(request, 'user_email', '?')} "
        f"role={getattr(request, 'user_role', '?')} host={host_name} "
        f"timeout={timeout} first_line={first_line!r}",
        flush=True,
    )

    from shared.src.lib.utils.build_url_utils import call_host
    # Read timeout must exceed the host's per-command timeout so the host's
    # real result wins instead of the proxy timing out first.
    response_data, status_code = call_host(
        host_data, '/host/system/runCommand', method='POST',
        data={'command': command, 'timeout': timeout}, timeout=timeout + 30,
    )
    if status_code == 200:
        return jsonify(response_data), 200
    # Transport failure (504 timeout / 503 unreachable / 5xx) — distinct from
    # "command ran and failed", which returns 200 with success:false.
    error = (
        response_data.get('error')
        if isinstance(response_data, dict) and response_data.get('error')
        else f'Host returned status {status_code}'
    )
    return jsonify({'success': False, 'error': error, 'transport_error': True}), status_code


@server_system_bp.route('/updateCoreLocal', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:updateCoreLocal')
def update_core_local():
    """Update local server/frontend code on this VM."""
    data = request.get_json() or {}
    target_kind = str(data.get('target_kind', 'server')).strip().lower() or 'server'
    if target_kind not in {'server', 'frontend'}:
        return jsonify({'success': False, 'error': 'target_kind must be server or frontend'}), 400

    dry_run = _coerce_bool(data.get('dry_run', False), default=False)
    restart_service = _coerce_bool(data.get('restart_service', True), default=True)
    source_path = str(data.get('source_path', '/mnt/shared/code/virtualpytest')).strip() or '/mnt/shared/code/virtualpytest'

    if not _acquire_server_update_lock():
        return jsonify({'success': False, 'error': 'Another local update is currently in progress'}), 409

    try:
        if not dry_run:
            _set_server_deploy_state('running')

        script_path = os.path.join('/opt/virtualpytest', 'scripts', 'code-deploy.sh')
        if not os.path.isfile(script_path):
            script_path = os.path.join(_project_root(), 'scripts', 'code-deploy.sh')
        if not os.path.isfile(script_path):
            if not dry_run:
                _set_server_deploy_state('failed', error=f'Missing script: {script_path}')
            return jsonify({'success': False, 'error': f'Code deploy script not found: {script_path}'}), 500

        if target_kind == 'frontend':
            result = _run_frontend_remote_deploy(source_path, dry_run, restart_service)
        else:
            apply_restart_in_script = restart_service and target_kind != 'server'

            env = os.environ.copy()
            env['VPT_SOURCE_DIR'] = source_path
            env['VPT_TARGET_DIR'] = '/opt/virtualpytest'
            env['VPT_BACKUP_ROOT'] = SERVER_BACKUP_ROOT
            env['VPT_KEEP_BACKUPS'] = '5'
            env['VPT_DRY_RUN'] = '1' if dry_run else '0'
            env['VPT_TARGET_KIND'] = target_kind
            env['VPT_RESTART_ENABLED'] = '1' if apply_restart_in_script else '0'

            result = subprocess.run(
                ['bash', script_path],
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=1800,
            )

        if result.returncode != 0:
            if not dry_run:
                _set_server_deploy_state('failed', error=result.stderr[-2000:] or result.stdout[-2000:])
            return jsonify({
                'success': False,
                'dry_run': dry_run,
                'target_kind': target_kind,
                'error': 'Local core update failed',
                'stdout': result.stdout[-2000:],
                'stderr': result.stderr[-2000:],
            }), 500

        deploy_data = _parse_kv_output(result.stdout)
        version_before = deploy_data.get('VERSION_BEFORE', _read_local_deployed_version('/opt/virtualpytest'))
        version_after = deploy_data.get('VERSION_AFTER', version_before)
        backup_path = deploy_data.get('BACKUP_DIR')
        restart_scheduled = False
        backup_id = None

        if backup_path and not dry_run:
            metadata = {
                'backup_id': os.path.basename(backup_path),
                'backup_path': backup_path,
                'created_at': _utc_now_iso(),
                'version': version_before,
                'status': 'stable',
                'reason': 'pre_deploy',
                'source_path': source_path,
                'source_ref': deploy_data.get('SOURCE_REF') or None,
                'rolled_forward_to': version_after,
            }
            git_info = _read_git_head_info(source_path)
            if git_info.get('is_git_repo'):
                metadata['source_branch'] = git_info.get('branch')
                metadata['source_commit'] = git_info.get('short_commit')
            _write_backup_metadata(backup_path, metadata)
            _prune_backup_entries(SERVER_BACKUP_ROOT, 5)
            backup_id = metadata['backup_id']

        if not dry_run:
            if restart_service and target_kind == 'server':
                _schedule_server_restart()
                restart_scheduled = True
            _set_server_deploy_state('success', version=version_after)

        return jsonify({
            'success': True,
            'dry_run': dry_run,
            'target_kind': target_kind,
            'backup_path': backup_path,
            'backup_id': backup_id,
            'version_before': version_before,
            'version_after': version_after,
            'deploy_state': 'idle' if dry_run else 'success',
            'restart_scheduled': restart_scheduled,
            'message': 'Local deploy dry-run checks passed' if dry_run else 'Local core update completed',
            'stdout': result.stdout[-2000:],
        }), 200
    except Exception as exc:
        if not dry_run:
            _set_server_deploy_state('failed', error=str(exc))
        raise
    finally:
        _release_server_update_lock()


@server_system_bp.route('/rollbackCoreLocal', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:rollbackCoreLocal')
def rollback_core_local():
    """Rollback local server/frontend code from backup."""
    data = request.get_json() or {}
    target_kind = str(data.get('target_kind', 'server')).strip().lower() or 'server'
    if target_kind not in {'server', 'frontend'}:
        return jsonify({'success': False, 'error': 'target_kind must be server or frontend'}), 400

    dry_run = _coerce_bool(data.get('dry_run', False), default=False)
    restart_service = _coerce_bool(data.get('restart_service', True), default=True)
    backup_id = data.get('backup_id')
    backup_path = data.get('backup_path')
    if not _acquire_server_update_lock():
        return jsonify({'success': False, 'error': 'Another local update is currently in progress'}), 409

    try:
        if target_kind == 'frontend':
            backups, _ = _list_frontend_remote_backups()
            selected_backup = None
            if backup_id:
                for entry in backups:
                    if entry.get('backup_id') == str(backup_id).strip():
                        selected_backup = str(entry.get('backup_path'))
                        break
                if not selected_backup:
                    return jsonify({'success': False, 'error': f'Backup not found: {backup_id}'}), 404
            elif backup_path:
                selected_backup = str(backup_path)
            elif backups:
                selected_backup = str(backups[0].get('backup_path'))
            else:
                return jsonify({'success': False, 'error': 'No backup found to rollback'}), 404
        else:
            backup_root_real = os.path.realpath(SERVER_BACKUP_ROOT)
            try:
                selected_backup = _resolve_backup_dir(
                    SERVER_BACKUP_ROOT,
                    '/opt/virtualpytest',
                    backup_id=str(backup_id).strip() if backup_id else None,
                    backup_path=backup_path,
                    ensure_baseline=True,
                )
            except FileNotFoundError as exc:
                return jsonify({'success': False, 'error': str(exc)}), 404
            if not selected_backup.startswith(backup_root_real + os.sep):
                return jsonify({'success': False, 'error': 'Invalid backup_path'}), 400
            if not os.path.isdir(selected_backup):
                return jsonify({'success': False, 'error': f'Backup path not found: {selected_backup}'}), 404

        version_before = _read_local_deployed_version('/opt/virtualpytest') if target_kind != 'frontend' else 'unknown'
        if dry_run:
            return jsonify({
                'success': True,
                'dry_run': True,
                'target_kind': target_kind,
                'backup_id': os.path.basename(selected_backup),
                'backup_path': selected_backup,
                'version_before': version_before,
                'version_after': version_before,
                'message': 'Local rollback dry-run checks passed',
            }), 200

        _set_server_deploy_state('running')
        if target_kind == 'frontend':
            remote_snapshot_script = "\n".join([
                "import json, os",
                "from datetime import datetime",
                f"ROOT={json.dumps(_frontend_remote_config()['backup_root'])}",
                f"TARGET={json.dumps(_frontend_remote_config()['target_dir'])}",
                "META='.vpt-backup-meta.json'",
                "backup_id=datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')",
                "backup_dir=os.path.join(ROOT, backup_id)",
                "os.makedirs(ROOT, exist_ok=True)",
                "os.makedirs(backup_dir, exist_ok=True)",
                "os.system('rsync -a --delete --exclude=.env --exclude=venv --exclude=node_modules --exclude=frontend/public/docs --exclude=frontend/dist --exclude=playwright-report* --exclude=playwright-viewport-report* --exclude=security_report --exclude=frontend/vite.config.local.json --exclude=frontend/public/branding.json --exclude=.backups \"{}/\" \"{}/\" >/dev/null 2>&1'.format(TARGET, backup_dir))",
                "version='unknown'",
                "for candidate in ('version','VERSION.txt'):",
                " p=os.path.join(TARGET,candidate)",
                " if os.path.isfile(p):",
                "  version=open(p,encoding='utf-8').readline().strip() or 'unknown'",
                "  break",
                "json.dump({'backup_id': backup_id, 'backup_path': backup_dir, 'created_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z', 'version': version, 'status': 'stable', 'reason': 'pre_rollback'}, open(os.path.join(backup_dir, META), 'w', encoding='utf-8'), ensure_ascii=True, indent=2)",
                "print(json.dumps({'backup_id': backup_id, 'backup_path': backup_dir, 'version': version}))",
            ])
            remote_result = _run_frontend_remote(
                f"python3 - <<'PY'\n{remote_snapshot_script}\nPY",
                timeout=1800,
            )
            if remote_result.returncode != 0:
                _set_server_deploy_state('failed', error=remote_result.stderr[-2000:] or remote_result.stdout[-2000:])
                return jsonify({'success': False, 'error': 'Failed to snapshot current frontend version before rollback'}), 500
            pre_rollback_metadata = json.loads((remote_result.stdout or '{}').strip() or '{}')
            pre_rollback_backup_path = str(pre_rollback_metadata.get('backup_path'))
            sync_result = _run_frontend_remote_rsync_restore(selected_backup, restart_service, False)
        else:
            try:
                pre_rollback_backup_path, pre_rollback_metadata = _create_backup_snapshot(
                    '/opt/virtualpytest',
                    SERVER_BACKUP_ROOT,
                    reason='pre_rollback',
                )
            except Exception as exc:
                _set_server_deploy_state('failed', error=str(exc))
                print(f'[@server_system:rollback_core_local] pre-rollback snapshot failed: {exc}')
                return jsonify({'success': False, 'error': 'Failed to snapshot current version before rollback (see server log / deploy state)'}), 500
            sync_result = subprocess.run(
                [
                    'rsync', '-a', '--delete',
                    '--exclude=.env',
                    '--exclude=venv',
                    '--exclude=node_modules',
                    '--exclude=frontend/public/docs',
                    '--exclude=frontend/dist',
                    '--exclude=playwright-report*',
                    '--exclude=playwright-viewport-report*',
                    '--exclude=security_report',
                    '--exclude=frontend/vite.config.local.json',
                    '--exclude=frontend/public/branding.json',
                    '--exclude=.backups',
                    f'{selected_backup}/', '/opt/virtualpytest/'
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=1800,
            )
        if sync_result.returncode != 0:
            _set_server_deploy_state('failed', error=sync_result.stderr[-2000:] or sync_result.stdout[-2000:])
            return jsonify({
                'success': False,
                'dry_run': False,
                'target_kind': target_kind,
                'backup_path': selected_backup,
                'error': 'Local rollback sync failed',
                'stdout': sync_result.stdout[-2000:],
                'stderr': sync_result.stderr[-2000:],
            }), 500

        restart_scheduled = False
        if restart_service and target_kind == 'server':
            _schedule_server_restart()
            restart_scheduled = True
        elif restart_service and target_kind != 'frontend':
            if target_kind != 'server':
                # Pick the first unit present (vpt-frontend, else
                # vpt-frontend-prod, else fall back to vpt-frontend and let
                # systemctl surface the error). Argv form — no shell, no
                # interpolation; previously passed as a `bash -lc` string
                # which made CodeQL's taint rule fire and was a foot-gun if
                # anyone later added data to the script.
                candidates = ('vpt-frontend', 'vpt-frontend-prod')
                chosen_unit = None
                for candidate in candidates:
                    probe = subprocess.run(
                        ['systemctl', 'list-unit-files', candidate + '.service'],
                        capture_output=True, text=True, check=False, timeout=10,
                    )
                    if probe.returncode == 0 and candidate + '.service' in probe.stdout:
                        chosen_unit = candidate
                        break
                if chosen_unit is None:
                    chosen_unit = 'vpt-frontend'
                restart_result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', chosen_unit],
                    capture_output=True, text=True, check=False, timeout=120,
                )
                if restart_result.returncode != 0:
                    _set_server_deploy_state('failed', error=restart_result.stderr[-2000:] or restart_result.stdout[-2000:])
                    return jsonify({
                        'success': False,
                        'dry_run': False,
                        'target_kind': target_kind,
                        'backup_path': selected_backup,
                        'error': 'Local rollback completed but frontend service restart failed',
                        'stdout': restart_result.stdout[-2000:],
                        'stderr': restart_result.stderr[-2000:],
                    }), 500

        if target_kind == 'frontend':
            restore_data = _parse_kv_output(sync_result.stdout)
            version_before = pre_rollback_metadata.get('version', 'unknown')
            version_after = restore_data.get('VERSION_AFTER', 'unknown')
        else:
            version_after = _read_local_deployed_version('/opt/virtualpytest')
        _set_server_deploy_state('success', version=version_after)
        if target_kind != 'frontend':
            _prune_backup_entries(SERVER_BACKUP_ROOT, 5)
        return jsonify({
            'success': True,
            'dry_run': False,
            'target_kind': target_kind,
            'backup_id': os.path.basename(selected_backup),
            'backup_path': selected_backup,
            'pre_rollback_backup_id': pre_rollback_metadata.get('backup_id'),
            'pre_rollback_backup_path': pre_rollback_backup_path,
            'version_before': version_before,
            'version_after': version_after,
            'restart_scheduled': restart_scheduled,
            'message': 'Local rollback completed',
        }), 200
    finally:
        _release_server_update_lock()


@server_system_bp.route('/listCoreBackups', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:listCoreBackups')
def list_core_backups():
    """List rollback backup options for local server/frontend code."""
    data = request.get_json(silent=True) or {}
    target_kind = str(data.get('target_kind', 'server')).strip().lower() or 'server'
    if target_kind == 'frontend':
        entries, default_backup_id = _list_frontend_remote_backups()
        return jsonify({
            'success': True,
            'backups': entries,
            'default_backup_id': default_backup_id,
        }), 200
    entries = _list_backup_entries(SERVER_BACKUP_ROOT, '/opt/virtualpytest', ensure_baseline=True)
    return jsonify({
        'success': True,
        'backups': entries,
        'default_backup_id': entries[0]['backup_id'] if entries else None,
    }), 200


@server_system_bp.route('/updateHostCore', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:updateHostCore')
def update_host_core_proxy():
    """Proxy host core update request to specific host."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_payload = {
        'dry_run': bool(data.get('dry_run', False)),
        'restart_host_service': bool(data.get('restart_host_service', True)),
        'source_path': data.get('source_path', '/mnt/shared/code/virtualpytest'),
        'target_kind': data.get('target_kind', 'host-linux'),
    }

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404

    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_data,
        '/host/system/updateCore',
        method='POST',
        data=host_payload,
        timeout=1800
    )
    if isinstance(response_data, dict) and host_data:
        if status_code == 200 and response_data.get('success'):
            host_data['deployed_version'] = response_data.get(
                'version_after',
                host_data.get('deployed_version', 'unknown')
            )
            host_data['deploy_state'] = response_data.get('deploy_state', 'success')
        elif status_code >= 400:
            host_data['deploy_state'] = 'failed'
        host_data['last_deploy_at'] = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    return jsonify(response_data), status_code


@server_system_bp.route('/rollbackHostCore', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:rollbackHostCore')
def rollback_host_core_proxy():
    """Proxy host core rollback request to specific host."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400

    host_payload = {
        'dry_run': bool(data.get('dry_run', False)),
        'restart_host_service': bool(data.get('restart_host_service', True)),
    }
    if data.get('backup_id'):
        host_payload['backup_id'] = data.get('backup_id')
    if data.get('backup_path'):
        host_payload['backup_path'] = data.get('backup_path')

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404

    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_data,
        '/host/system/rollbackCore',
        method='POST',
        data=host_payload,
        timeout=1800
    )
    if isinstance(response_data, dict) and host_data:
        if status_code == 200 and response_data.get('success'):
            host_data['deployed_version'] = response_data.get(
                'version_after',
                host_data.get('deployed_version', 'unknown')
            )
            host_data['deploy_state'] = 'success'
        elif status_code >= 400:
            host_data['deploy_state'] = 'failed'
        host_data['last_deploy_at'] = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    return jsonify(response_data), status_code


@server_system_bp.route('/listHostCoreBackups', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:listHostCoreBackups')
def list_host_core_backups_proxy():
    """Proxy host rollback backup listing request to a specific host."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404

    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_data,
        '/host/system/listBackups',
        method='POST',
        data={},
        timeout=120,
    )
    return jsonify(response_data), status_code


@server_system_bp.route('/restartHostStreamService', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_system:restartHostStreamService')
def restart_host_stream_service_proxy():
    """Proxy a REAL vpt-stream service restart to a host. vpt-stream is one
    service per host, so only host_name is needed (device-agnostic)."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, '/host/system/restartHostStreamService', method='POST',
                                           data={}, timeout=60)
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/setStreamQuality', methods=['POST'])
@handle_route_exceptions('server_system:setStreamQuality')
def set_stream_quality_proxy():
    """Proxy a soft per-device quality change to a host (no service restart)."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = data.get('device_id', 'device1')
    quality = data.get('quality', 'sd')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, '/host/system/setStreamQuality', method='POST',
                                           data={'device_id': device_id, 'quality': quality}, timeout=30)
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


@server_system_bp.route('/getStreamQuality', methods=['GET'])
@handle_route_exceptions('server_system:getStreamQuality')
def get_stream_quality_proxy():
    """Proxy: read a device's current stream quality from the host."""
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id', 'device1')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, '/host/system/getStreamQuality', method='GET',
                                           query_params={'device_id': device_id}, timeout=10)
    if status_code == 200:
        return jsonify(response_data), 200
    return jsonify({'success': False, 'error': f'Host returned status {status_code}'}), status_code


# =============================================================================
# HOST MONITORING PROXY ROUTES
# =============================================================================

@server_system_bp.route('/diskUsage', methods=['GET'])
@handle_route_exceptions('server_system:diskUsage')
def disk_usage_diagnostics_proxy():
    """
    Proxy disk usage diagnostics request to specific host.
    Returns comprehensive disk space analysis for all capture directories.
    
    Query params:
        - host_name: Required - which host to query
        - capture_dir: Optional - specific capture (e.g., 'capture1') or 'all' (default)
    """
    host_name = request.args.get('host_name')
    capture_dir = request.args.get('capture_dir', 'all')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name query parameter is required'}), 400
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, f'/host/monitoring/disk-usage?capture_dir={capture_dir}',
                                           method='GET', timeout=30)
    if status_code == 200:
        response_data['host_name'] = host_name
        return jsonify(response_data), 200
    if status_code == 504:
        return jsonify({'success': False, 'error': 'Request timeout - disk analysis taking too long (check host logs)'}), 504
    return jsonify({'success': False, 'error': f'Host returned status {status_code}',
                    'host_response': response_data.get('error', 'Unknown error')}), status_code
