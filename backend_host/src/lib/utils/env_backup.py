"""
Host side of the Platform update backup (TASK-109): the host's ``.env`` files, handed to the server that conducts
the update. The server stores them 0600 and never offers them for download.

Only a fixed list of files relative to the project root is ever read, so the endpoint cannot be asked for any
other path. The content travels in the reply of an authenticated call (``X-API-Key``, the same credential every
server -> host call uses) and is never logged.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List

from shared.src.lib.utils.atomic_replace import replace_keeping_mode

MAX_RESTORE_BYTES = 256 * 1024

# name returned to the server -> path under the project root
ENV_FILES = {
    '.env': '.env',
    'backend_host/src/.env': os.path.join('backend_host', 'src', '.env'),
}


def collect(project_root: str) -> List[Dict[str, str]]:
    """Every existing env file of this host as ``{name, content}``."""
    found = []
    for name, rel in ENV_FILES.items():
        path = os.path.join(project_root, rel)
        if os.path.isfile(path):
            try:
                with open(path, 'rb') as fh:
                    found.append({'name': name, 'content': fh.read().decode('utf-8', errors='replace')})
            except OSError:
                continue
    return found


class RestoreError(ValueError):
    """The restore request is refused; the message is safe to return to the caller."""


def restore(project_root: str, name: object, content: object) -> Dict[str, str]:
    """TASK-128 G7: write one of the fixed env files back (atomically, the current file copied to ``.bak-<ts>`` first).

    ``name`` must be a key of ``ENV_FILES``; no other path can be named. -> ``{name, backup}`` (``backup`` is '' when there
    was no file before).
    """
    if not isinstance(name, str) or name not in ENV_FILES:
        raise RestoreError('unknown file name')
    if not isinstance(content, str) or '\x00' in content:
        raise RestoreError('content must be text')
    data = content.encode('utf-8')
    if len(data) > MAX_RESTORE_BYTES:
        raise RestoreError('content is too large for an env file')
    path = os.path.join(project_root, ENV_FILES[name])
    if not os.path.isdir(os.path.dirname(path)):
        raise RestoreError('the folder of this file does not exist on this host')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    try:
        backup = replace_keeping_mode(path, data, stamp)
    except OSError as exc:
        raise RestoreError(f'cannot write {name}: {type(exc).__name__}')
    return {'name': name, 'backup': os.path.basename(backup) if backup else ''}
