"""
Zammad instance config - storage for the page's "set it up" form.

Same shape as features/gitlab/lib/instances.py: runtime state in a JSON file under state_path(),
outside the deploy tree, so a deploy never overwrites what an operator configured and the token
never has to live in a redeployed env file. One Zammad per VPT server, so the file holds a list
with a single record:

    {"id": "main", "name": "Support", "base_url": "https://support.example.com",
     "token": "...", "public_url": "https://support.example.com", "enabled": true}

`public_url` is what the BROWSER opens for "view in Zammad" (agent URL `<public_url>/#ticket/zoom/<id>`);
`base_url` is what the VPT server calls and may be an internal address. Neither is hardcoded.

Env: ZAMMAD_URL + ZAMMAD_API_TOKEN (+ ZAMMAD_PUBLIC_URL) work with no UI at all. The file overrides
them field by field: an empty field in the file falls back to the env value, so the Enabled switch can
be stored alone ({"enabled": false}) without copying the env token into a file.

`enabled` is the runtime switch (default true). When false the report entry is hidden and creating a
ticket answers 409. Deploy-level removal is DISABLED_FEATURES=zammad.
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional

from backend_server.src.lib.utils.integration_state import state_path

CONFIG_PATH = state_path('zammad_instances.json')

#: RLock, not Lock: upsert() holds it and calls save(), which takes it again.
_LOCK = threading.RLock()

_FIELDS = ('id', 'name', 'base_url', 'token', 'public_url', 'enabled')
INSTANCE_ID = 'main'


def _clean(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: raw.get(k) for k in _FIELDS if k in raw}
    out['id'] = out.get('id') or INSTANCE_ID
    out['name'] = out.get('name') or ''
    out['base_url'] = (out.get('base_url') or '').strip().rstrip('/')
    out['token'] = (out.get('token') or '').strip()
    out['public_url'] = (out.get('public_url') or '').strip().rstrip('/')
    out['enabled'] = out['enabled'] if isinstance(out.get('enabled'), bool) else True
    return out


def load() -> List[Dict[str, Any]]:
    """Stored records. Never raises - a broken file must not take the page down."""
    try:
        if not CONFIG_PATH.exists():
            return []
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get('instances', [])
        return [_clean(row) for row in data if isinstance(row, dict)]
    except Exception as e:
        print(f"[@zammad] Could not read {CONFIG_PATH}: {e}")
        return []


def save(records: List[Dict[str, Any]]) -> bool:
    with _LOCK:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump([_clean(r) for r in records], f, indent=2)
            try:
                os.chmod(CONFIG_PATH, 0o600)      # it holds an API token
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[@zammad] Could not write {CONFIG_PATH}: {e}")
            return False


def _env() -> Dict[str, str]:
    return {
        'base_url': os.environ.get('ZAMMAD_URL', ''),
        'token': os.environ.get('ZAMMAD_API_TOKEN', ''),
        'public_url': os.environ.get('ZAMMAD_PUBLIC_URL', ''),
    }


def effective() -> Dict[str, Any]:
    """The config in force: file fields over env fields. `source` says where the URL came from."""
    records = load()
    stored = records[0] if records else {}
    env = _env()
    merged = {k: (stored.get(k) or env[k]) for k in ('base_url', 'token', 'public_url')}
    merged['name'] = stored.get('name') or ''
    merged['enabled'] = stored['enabled'] if 'enabled' in stored else True
    cfg = _clean(merged)
    cfg['source'] = 'file' if stored.get('base_url') else ('env' if env['base_url'] else 'none')
    return cfg


def is_configured(cfg: Optional[Dict[str, Any]] = None) -> bool:
    cfg = cfg or effective()
    return bool(cfg['base_url'] and cfg['token'])


def is_enabled() -> bool:
    """Switch on AND connection details present: the only state in which a ticket can be created."""
    cfg = effective()
    return cfg['enabled'] and is_configured(cfg)


def upsert(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge `fields` into the stored record and return it. None when the write failed.

    An empty/absent token keeps the stored one: the form never sends it back, so saving a renamed
    instance must not wipe its credential.
    """
    with _LOCK:
        records = load()
        current = records[0] if records else _clean({})
        merged = {**current, **{k: v for k, v in fields.items() if k in _FIELDS and v is not None}}
        if not (fields.get('token') or '').strip():
            merged['token'] = current.get('token', '')
        cleaned = _clean(merged)
        return cleaned if save([cleaned]) else None


def public(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Config for the frontend - the token is never sent to the browser."""
    return {
        'name': cfg.get('name'),
        'base_url': cfg.get('base_url'),
        'public_url': cfg.get('public_url'),
        'enabled': cfg.get('enabled', True),
        'has_token': bool(cfg.get('token')),
        'configured': is_configured(cfg),
        'source': cfg.get('source', 'none'),
    }


def ticket_url(cfg: Dict[str, Any], external_id: str) -> Optional[str]:
    """Agent-side link to a ticket, or None when no URL is configured."""
    base = cfg.get('public_url') or cfg.get('base_url')
    return f'{base}/#ticket/zoom/{external_id}' if base else None


def provider():
    """ZammadProvider for the config in force (raises SupportNotConfigured on first use if empty)."""
    from features.zammad.lib.zammad import ZammadProvider
    cfg = effective()
    return ZammadProvider(cfg['base_url'], cfg['token'])
