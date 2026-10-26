"""
The versions each machine ran when the deploy started (TASK-109).

Captured once, at the start of step 3 (Deploy), and stored in that step's data as ``versions_before``, so the
deploy cards and the close message can say ``from -> to`` after the server restart, a page reload or on another
browser. The first capture wins: a deploy that failed half-way and is re-run must not record the half-updated
versions as the "before".
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .runs import RunStore, DEPLOY_STEP

MAX_VERSION = 80


def _clean(value: Any) -> str:
    text = str(value or '').strip()
    text = text.split(':', 1)[1].strip() if text.lower().startswith('current:') else text
    return text[:MAX_VERSION]


def read_server_version(root: str) -> str:
    for name in ('VERSION.txt', 'version'):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    return _clean(fh.readline()) or 'unknown'
            except OSError:
                pass
    return 'unknown'


def capture(store: RunStore, run_id: str, root: str, hosts: List[dict], frontend_version: Optional[str] = None) -> Dict[str, Any]:
    """Store ``versions_before`` in the deploy step unless it is already there. -> the stored record."""
    existing = store.get(run_id)['steps'][DEPLOY_STEP]['data'].get('versions_before')
    if existing:
        return existing
    record = {
        'server': read_server_version(root),
        'frontend': _clean(frontend_version),
        'hosts': {str(h.get('host_name') or h.get('name') or '?'): _clean(h.get('deployed_version')) for h in hosts},
        'captured_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    store.set_data(run_id, DEPLOY_STEP, {'versions_before': record})
    return record


def capture_for_deploy(store: RunStore, run_id: str, root: str, hosts_fn, frontend_version: Optional[str] = None) -> None:
    """``capture`` for the start of a deploy: a host list that cannot be read must not stop the deploy."""
    try:
        hosts = list(hosts_fn())
    except Exception:
        hosts = []
    capture(store, run_id, root, hosts, frontend_version)
