"""
Postman connection settings — storage for the page's "set it up" form.

Same shape as the GitLab instance list (`features/gitlab/lib/instances.py`) and the JIRA
instance list: runtime state in a JSON file under `state_path()`, i.e. OUTSIDE the deploy
tree, so `update_core.sh`'s `rsync --delete` can never disconnect a server an operator just
configured, and the key never has to be baked into an `.env` that the next deploy rewrites.

    {"api_key": "PMAK-…", "workspace_id": "4e7a465c-…"}

The API key is a credential: the file is chmod 600, and nothing in `public()` ever carries it
— the browser is told `has_key`, never the key.

Precedence in `effective_api_key()`: this file first, then `POSTMAN_API_KEY` from the
environment. A deployment that has always used env vars keeps working with nothing configured,
and an operator can move off the env var from the page without breaking anything.
"""

import json
import os
import threading
from typing import Any, Dict, Optional

from backend_server.src.lib.utils.integration_state import state_path

CONFIG_PATH = state_path('postman_settings.json')

_LOCK = threading.RLock()

#: Keys an operator may set. Anything else in the file is ignored on write, so a hand-edited
#: file cannot smuggle unexpected keys into the runtime dict.
_FIELDS = ('api_key', 'workspace_id')


def _clean(raw: Dict[str, Any]) -> Dict[str, str]:
    return {
        'api_key': str(raw.get('api_key') or '').strip(),
        'workspace_id': str(raw.get('workspace_id') or '').strip(),
    }


def load() -> Dict[str, str]:
    """Stored settings. Never raises — a broken file must not take the page down."""
    try:
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        if isinstance(data, list):          # tolerate a hand-written {"api_key": ...} vs list
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return {}
        return _clean(data)
    except Exception as e:
        print(f"[@postman_settings] Could not read {CONFIG_PATH}: {e}")
        return {}


def save(data: Dict[str, str]) -> bool:
    with _LOCK:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump(_clean(data), f, indent=2)
            try:
                os.chmod(CONFIG_PATH, 0o600)      # it holds a Postman API key
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[@postman_settings] Could not write {CONFIG_PATH}: {e}")
            return False


def runtime_api_key() -> str:
    """The key saved from the page, if any."""
    return load().get('api_key', '')


def effective_api_key() -> str:
    """What the routes should call Postman with: the saved key, else POSTMAN_API_KEY."""
    return runtime_api_key() or (os.environ.get('POSTMAN_API_KEY') or '').strip()


def source() -> str:
    """Where the key came from: 'settings', 'environment', or '' when there is none."""
    if runtime_api_key():
        return 'settings'
    return 'environment' if (os.environ.get('POSTMAN_API_KEY') or '').strip() else ''


def upsert(fields: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Save the submitted settings and return what was stored, or None when the write failed.

    An empty `api_key` means "keep the stored one": the form never sends the key back, so
    saving just a workspace id would otherwise wipe the credential.
    """
    with _LOCK:
        current = load()
        merged = _clean({**current, **fields})
        if not merged.get('api_key') and current.get('api_key'):
            merged['api_key'] = current['api_key']
        return merged if save(merged) else None


def clear() -> bool:
    with _LOCK:
        try:
            if CONFIG_PATH.exists():
                CONFIG_PATH.unlink()
            return True
        except Exception as e:
            print(f"[@postman_settings] Could not clear {CONFIG_PATH}: {e}")
            return False


def public() -> Dict[str, Any]:
    """Settings for the frontend — the API key is never sent to the browser."""
    stored = load()
    return {
        'configured': bool(effective_api_key()),
        'has_key': bool(effective_api_key()),
        'source': source(),
        'workspace_id': stored.get('workspace_id', ''),
    }