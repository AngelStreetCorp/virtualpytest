"""
Last key sent to a device (TASK-158).

Every action sent through the host (executeCommand route, action executor, triage probe) overwrites
`<capture metadata dir>/last_action.json` with `{command, timestamp, params, source}`
(`frame_metadata_utils.write_action_to_frame_json`). That file is the cheapest honest "last key" source: no
per-frame cost, no new table. The host incident manager reads it once, when it opens an alert, and stamps the
result on `alerts.metadata.last_key`; the triage worker (server) reads it back with `last_key_event`.

Freshness: the value is the key as of the moment the alert opened (30 s after the condition began), not as of
now. A key sent after that is not seen. `seconds_since_last_key` is measured to the alert's `start_time`.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

SOURCES = ('remote', 'executor', 'probe')


def _key_name(command: Optional[str], params: Any) -> Optional[str]:
    if isinstance(params, dict):
        for field in ('key', 'keys'):  # never 'text': typed text can hold anything
            value = params.get(field)
            if isinstance(value, str) and value:
                return value[:40]
    return command[:40] if isinstance(command, str) and command else None


def read_last_key(capture_folder: str) -> Optional[Dict[str, Any]]:
    """Host side: ``{at, source, command, key}`` of the last action sent to this capture folder, or None."""
    try:
        from shared.src.lib.utils.storage_path_utils import get_metadata_path
        with open(os.path.join(get_metadata_path(capture_folder), 'last_action.json')) as f:
            data = json.load(f)
        stamp = float(data['timestamp'])
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return None
    command = data.get('command')
    source = data.get('source')
    return {
        'at': datetime.utcfromtimestamp(stamp).isoformat() + 'Z',
        'source': source if source in SOURCES else 'unknown',
        'command': command if isinstance(command, str) else None,
        'key': _key_name(command, data.get('params')),
    }


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def last_key_event(alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Server side: ``{at, source, actor, key, seconds_before_alert}`` of the key before this alert, or None.

    ``source`` is script / take_control / ai / remote; ``actor`` the owner when a control session was open.
    None when the host did not record one (old alert, no capture folder, or nothing ever sent)."""
    meta = alert.get('metadata') or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return None
    raw = meta.get('last_key') if isinstance(meta, dict) else None
    if not isinstance(raw, dict):
        return None
    at = _parse(raw.get('at'))
    start = _parse(alert.get('start_time'))
    if at is None or start is None:
        return None
    source = {'executor': 'script', 'remote': 'remote', 'probe': 'probe'}.get(raw.get('source'), 'unknown')
    return {
        'at': raw['at'],
        'source': raw.get('control_source') or source,
        'actor': raw.get('actor'),
        'key': raw.get('key'),
        'seconds_before_alert': max(0, int((start - at).total_seconds())),
    }
