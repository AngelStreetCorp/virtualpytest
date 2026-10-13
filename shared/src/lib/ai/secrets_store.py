"""
Server-side store for AI provider API keys (TASK-30 §3.5).

A ``0600`` JSON file, replaced atomically. Keys are never written to the DB, never
returned to the browser (callers only ever get ``has_secret``) and never logged. Hosts
do not read this file — their AI calls go through the server gateway.

File: ``~/.config/virtualpytest/ai_secrets.json`` of the user the server runs as
(``vpt_user``) → ``{"secrets": {name: value}}``. It lives OUTSIDE the project tree on
purpose: deploys ``rsync --delete`` the project directory, which would wipe it.
``VPT_CONFIG_DIR`` overrides the directory (e.g. a mounted volume in Docker) — the same
rule as the integration state files (``backend_server/src/lib/utils/integration_state.py``).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

_DEFAULT_DIR = Path("~/.config/virtualpytest")
_LOCK = threading.RLock()


def _path() -> Path:
    return Path(os.getenv("VPT_CONFIG_DIR", "").strip() or _DEFAULT_DIR).expanduser() / "ai_secrets.json"


def _read() -> dict[str, str]:
    try:
        stored = json.loads(_path().read_text())
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise ValueError("AI secrets file is unreadable.") from exc
    secrets = stored.get("secrets", {}) if isinstance(stored, dict) else {}
    return {str(k): str(v) for k, v in secrets.items()} if isinstance(secrets, dict) else {}


def _write(secrets: dict[str, str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"secrets": secrets}))
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)


def get_secret(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    with _LOCK:
        value = _read().get(name, "").strip()
    return value or None


def has_secret(name: Optional[str]) -> bool:
    return get_secret(name) is not None


def set_secret(name: str, value: str) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("secret name is required")
    value = (value or "").strip()
    if not value:
        raise ValueError("secret value is required")
    with _LOCK:
        secrets = _read()
        secrets[name] = value
        _write(secrets)


def delete_secret(name: str) -> bool:
    with _LOCK:
        secrets = _read()
        if name not in secrets:
            return False
        del secrets[name]
        _write(secrets)
        return True


def secret_names() -> list[str]:
    with _LOCK:
        return sorted(_read())
