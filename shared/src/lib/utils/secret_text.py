"""
Typed text that names a host secret instead of carrying it (TASK-178).

A tree, a script or an AI builder types an app login with `{env:<CODENAME>_APP_LOGIN}` / `{env:<CODENAME>_APP_PASSWORD}`. The
controller on the host swaps the placeholder for the value of that variable in its own environment (the host `.env`)
at the moment it types, so the value is never in a tree, an action row, a prompt to a model or a log line.

Only `<CODENAME>_APP_LOGIN` / `<CODENAME>_APP_PASSWORD` names resolve (the app test account of an operator);
any other `{env:...}` stays literal text. A name that is missing on the host fails the action with the name, never a value.
"""

import os
import re
import subprocess
from typing import Tuple

_PLACEHOLDER = re.compile(r'\{env:([A-Z][A-Z0-9]*_APP_(?:LOGIN|PASSWORD))\}')


def has_secret_placeholder(text: str) -> bool:
    return bool(text) and _PLACEHOLDER.search(text) is not None


def resolve_secret_text(text: str) -> Tuple[str, str]:
    """Return (value to type, text safe to log). Raises KeyError(name) when a named variable is not set on this host."""
    if not has_secret_placeholder(text):
        return text, text

    def _value(match):
        name = match.group(1)
        value = os.environ.get(name)
        if not value:
            raise KeyError(name)
        return value

    return _PLACEHOLDER.sub(_value, text), text


def adb_type_secret(device_id: str, value: str, timeout: int = 10) -> bool:
    """`adb shell input text` for a resolved secret: no command line is logged, spaces become %s."""
    escaped = value.replace(' ', '%s')
    try:
        result = subprocess.run(['adb', '-s', device_id, 'shell', 'input', 'text', escaped],
                                capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False
