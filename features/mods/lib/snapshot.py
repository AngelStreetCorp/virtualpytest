"""The current state, as the `system_update` events that would have described it.

A mod only sees changes; a page opened mid-run would show nothing until the next one. The
snapshot replays the state that matters (running scripts, device locks, who is online) in
the exact shape of the live /system updates, so the browser maps it with the same code.
"""

import time
from typing import Any, Dict, Iterable, List


def run_events(tasks: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One `execution_update` (running) per running script task, with its latest progress."""
    events = []
    for task in tasks:
        params = task.get('params') or {}
        progress = task.get('progress') or {}
        events.append({
            'type': 'execution_update',
            'domain': 'execution',
            'execution_type': 'script',
            'execution_id': task['id'],
            'status': 'running',
            'team_id': params.get('team_id'),
            'host_name': params.get('host_name'),
            'device_id': params.get('device_id'),
            'progress': progress.get('progress'),
            'message': progress.get('message') or params.get('script_name'),
            'result': {
                'step': progress.get('step'),
                'step_number': progress.get('step_number'),
                'total_steps': progress.get('total_steps'),
            },
            'timestamp': task.get('created_at') or time.time(),
        })
    return events


def lock_events(locks: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One `lock_changed` (locked) per held device lock."""
    return [
        {
            'type': 'lock_changed',
            'host_name': lock.get('host_name'),
            'device_id': lock.get('device_id'),
            'is_locked': True,
            'lock_info': lock,
        }
        for lock in locks.values()
        if lock.get('host_name') and lock.get('device_id')
    ]


def presence_event(presence: Dict[str, Any]) -> Dict[str, Any]:
    return {'type': 'presence_changed', **presence}


def build_snapshot(tasks, locks, presence) -> List[Dict[str, Any]]:
    return run_events(tasks) + lock_events(locks) + [presence_event(presence)]
