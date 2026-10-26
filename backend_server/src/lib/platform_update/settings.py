"""
Platform update settings (TASK-128 G1/G2/G9): the values an admin used to type into the server ``.env``, kept in one store.

Storage, in order of preference:
  ``db``    table ``public.platform_update_settings``, one row per (SERVER_NAME, key). Per server, not per team (it configures
            this install; see shared/src/lib/database/platform_update_settings_db.py). Used as soon as migration
            20261018g is applied.
  ``file``  a 0600 JSON file at ``state_path('platform-update/settings.json')`` (outside the project tree). Used while the
            table is missing, so deploying before the migration is safe. On the first write once the table exists, the
            file's values are imported once and the file is renamed ``settings.json.imported``.
The app never writes any ``.env``. One resolver, ``get(key)``, is the only way a consumer reads these values:

  the store value when it is set, else the matching environment variable (the ``.env`` stays a read-only fallback).

  key                       env fallback
  frontend_deploy_host      FRONTEND_DEPLOY_HOST          host / IP, ``local`` or ``none``
  frontend_deploy_ssh_user  FRONTEND_DEPLOY_SSH_USER
  frontend_deploy_ssh_key   FRONTEND_DEPLOY_SSH_KEY       absolute path of the private key on the server
  db_dsn  (secret)          PLATFORM_UPDATE_DB_URI | SUPABASE_DB_URI | DATABASE_URL
  vm_agent_action_token (s) VM_AGENT_ACTION_TOKEN
  github_token  (secret)    VPT_GITHUB_TOKEN | GITHUB_TOKEN   (also read by shared git_auth.github_token)
  database_agent            ``database`` entry of INFRA_VM_AGENTS   (host:port)

GitLab keeps its own per-server instance store (features/gitlab); it is not duplicated here.
Secrets are never returned by ``view()`` (only ``set`` / ``not set``) and never logged.
"""

import json
import os
import re
import secrets as _secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.src.lib.database import platform_update_settings_db as db
from shared.src.lib.utils import git_auth

from .runs import PlatformUpdateError

KEYS = ('frontend_deploy_host', 'frontend_deploy_ssh_user', 'frontend_deploy_ssh_key', 'db_dsn',
        'vm_agent_action_token', 'database_agent', 'github_token')
SECRET_KEYS = frozenset({'db_dsn', 'vm_agent_action_token', 'github_token'})
ENV_VARS = {
    'frontend_deploy_host': ('FRONTEND_DEPLOY_HOST',),
    'frontend_deploy_ssh_user': ('FRONTEND_DEPLOY_SSH_USER',),
    'frontend_deploy_ssh_key': ('FRONTEND_DEPLOY_SSH_KEY',),
    'db_dsn': ('PLATFORM_UPDATE_DB_URI', 'SUPABASE_DB_URI', 'DATABASE_URL'),
    'vm_agent_action_token': ('VM_AGENT_ACTION_TOKEN',),
    'github_token': ('VPT_GITHUB_TOKEN', 'GITHUB_TOKEN'),
    'database_agent': (),   # parsed from INFRA_VM_AGENTS
}
FILE_MODE = 0o600
DIR_MODE = 0o700
DB_CACHE_SECONDS = 5        # the resolver is called by every check: do not query the table each time
DB_RETRY_SECONDS = 30       # table missing / database down: look again later, serve the file meanwhile
TOKEN_BYTES = 32            # 64 hex characters; install.sh needs >= 32 of [A-Za-z0-9._~+=-]

_HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^[0-9A-Fa-f:]+$')
_AGENT_RE = re.compile(r'^[A-Za-z0-9.-]+:\d{1,5}$')
_USER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]{0,63}$')
_GITHUB_RE = re.compile(r'^[A-Za-z0-9_-]{20,255}$')


def store_path() -> Path:
    from backend_server.src.lib.utils.integration_state import state_path
    return state_path('platform-update/settings.json')


def server_name() -> str:
    """This server's identity: ``SERVER_NAME`` (the same value workspaces and system metrics use), ``default`` when unset."""
    return (os.getenv('SERVER_NAME') or '').strip() or 'default'


def _clean(data: Any) -> Dict[str, str]:
    return {k: str(v).strip() for k, v in data.items() if k in KEYS and isinstance(v, str) and str(v).strip()} \
        if isinstance(data, dict) else {}


def _load_file() -> Dict[str, str]:
    try:
        return _clean(json.loads(store_path().read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return {}


_cache: Dict[str, Any] = {'rows': None, 'until': 0.0}   # rows None = table unavailable


def _db_rows() -> Optional[Dict[str, str]]:
    """The stored rows of this server, or None when the table is not there (or the database does not answer)."""
    now = time.monotonic()
    if now < _cache['until']:
        return _cache['rows']
    try:
        rows: Optional[Dict[str, str]] = _clean(db.load(server_name()))
        _cache.update(rows=rows, until=now + DB_CACHE_SECONDS)
    except Exception:
        _cache.update(rows=None, until=now + DB_RETRY_SECONDS)
    return _cache['rows']


def _forget() -> None:
    _cache.update(rows=None, until=0.0)


def storage() -> str:
    """``db`` when the settings table is in use, ``file`` while it is not (migration not applied)."""
    return 'db' if _db_rows() is not None else 'file'


def _load() -> Dict[str, str]:
    rows = _db_rows()
    return rows if rows is not None else _load_file()


def _write(changes: Dict[str, str]) -> None:
    """Persist ``changes`` (empty value = delete)."""
    if _db_rows() is not None:
        try:
            _write_db(changes)
            return
        except db.TableMissing:
            _forget()
    merged = dict(_load_file())
    for key, value in changes.items():
        if value:
            merged[key] = value
        else:
            merged.pop(key, None)
    _save(merged)


def _write_db(changes: Dict[str, str]) -> None:
    """First DB write: import the JSON file's values once (the DB wins on a clash), then rename the file."""
    legacy = _load_file()
    current = _db_rows() or {}
    payload = {k: v for k, v in legacy.items() if k not in current}
    payload.update(changes)
    db.save(server_name(), payload, SECRET_KEYS)
    _forget()
    path = store_path()
    if legacy and path.exists():
        try:
            os.replace(path, path.with_name(path.name + '.imported'))
        except OSError:
            pass


def _save(values: Dict[str, str]) -> None:
    path = store_path()
    path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.settings-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(values, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)   # atomic: a reader sees the old or the new file, never half of it
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def agent_address_from_env(env: Dict[str, str]) -> str:
    """host:port of the ``database`` entry of INFRA_VM_AGENTS, '' when there is none."""
    for item in (env.get('INFRA_VM_AGENTS') or '').split(','):
        if '=' in item:
            name, address = item.split('=', 1)
            if name.strip() == 'database':
                return address.strip()
    return ''


def _from_env(key: str, env: Dict[str, str]) -> str:
    if key == 'database_agent':
        return agent_address_from_env(env)
    for name in ENV_VARS[key]:
        value = (env.get(name) or '').strip()
        if value:
            return value
    return ''


def source(key: str, env: Optional[Dict[str, str]] = None) -> str:
    """Where ``get(key)`` comes from: ``store``, ``env`` or ``none``."""
    if key not in KEYS:
        raise KeyError(key)
    if _load().get(key):
        return 'store'
    return 'env' if _from_env(key, os.environ if env is None else env) else 'none'


def get(key: str, env: Optional[Dict[str, str]] = None) -> str:
    """The resolver: the store value when set, else the environment (``env`` or ``os.environ``). '' when neither."""
    if key not in KEYS:
        raise KeyError(key)
    return _load().get(key) or _from_env(key, os.environ if env is None else env)


# -- validation ---------------------------------------------------------------------------------------------
def _check(key: str, value: str) -> str:
    if key == 'frontend_deploy_host':
        if value.lower() in ('local', 'none'):
            return value.lower()
        if not _HOST_RE.match(value):
            raise PlatformUpdateError('Frontend host must be a host name, an IP address, "local" or "none".')
    elif key == 'frontend_deploy_ssh_user':
        if not _USER_RE.match(value):
            raise PlatformUpdateError('SSH user is not a valid account name.')
    elif key == 'frontend_deploy_ssh_key':
        if not value.startswith('/') or '\n' in value or '\x00' in value:
            raise PlatformUpdateError('SSH key must be an absolute file path on the server.')
    elif key == 'db_dsn':
        if not re.match(r'^postgres(ql)?://', value) or '\n' in value or '\x00' in value:
            raise PlatformUpdateError('Database connection string must start with postgres:// or postgresql://.')
    elif key == 'vm_agent_action_token':
        if not re.match(r'^[A-Za-z0-9._~+=-]{32,}$', value):
            raise PlatformUpdateError('Agent token must be at least 32 characters of letters, digits and . _ ~ + = -.')
    elif key == 'github_token':
        if not _GITHUB_RE.match(value):
            raise PlatformUpdateError('GitHub token must be 20+ characters of letters, digits, _ and - (no spaces).')
    elif key == 'database_agent':
        if not _AGENT_RE.match(value):
            raise PlatformUpdateError('Database agent must look like host:port.')
    return value


def update(changes: Dict[str, Any]) -> List[str]:
    """Apply ``{key: value}``. An empty string clears the key (back to the env fallback). -> the keys changed."""
    if not isinstance(changes, dict):
        raise PlatformUpdateError('settings must be an object')
    unknown = [k for k in changes if k not in KEYS]
    if unknown:
        raise PlatformUpdateError(f'unknown setting: {unknown[0]}')
    cleaned: Dict[str, str] = {}
    for key, raw in changes.items():
        if raw is not None and not isinstance(raw, str):
            raise PlatformUpdateError(f'{key} must be text')
        cleaned[key] = _check(key, (raw or '').strip()) if (raw or '').strip() else ''
    _write(cleaned)
    return sorted(cleaned)


def view(env: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
    """What the page may show. Secrets: ``set`` only. -> ``{key: {secret, set, source, value?}}``."""
    env = os.environ if env is None else env
    out: Dict[str, Dict[str, Any]] = {}
    for key in KEYS:
        src = source(key, env)
        item: Dict[str, Any] = {'secret': key in SECRET_KEYS, 'set': src != 'none', 'source': src}
        if key not in SECRET_KEYS:
            item['value'] = get(key, env)
        out[key] = item
    return out


def generate_agent_token() -> str:
    """A new 64-hex agent token, saved in the store. The caller shows it once; ``view()`` never returns it."""
    token = _secrets.token_hex(TOKEN_BYTES)
    _write({'vm_agent_action_token': token})
    return token


git_auth.set_token_provider(lambda: _load().get('github_token', ''))   # the saved token wins over VPT_GITHUB_TOKEN / GITHUB_TOKEN
