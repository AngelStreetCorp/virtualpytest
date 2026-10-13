"""Who is connected to the /system socket, per team (TASK-77 presence).

One entry per socket connection (sid). A person with three tabs is one user; the shared
principals (service key, auto-sign, open mode, public key) are not people, so they are
counted apart as `shared_sessions`, deployment-wide.

In-process like `socket_auth`: correct for the single Socket.IO worker the server runs.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Optional, Set

_LOCK = threading.Lock()
# sid -> {'user_id', 'name', 'team_ids': set, 'shared': bool}
_CONNECTIONS: Dict[str, Dict[str, Any]] = {}


def display_name(principal: Optional[dict]) -> str:
    """Full name when the profile has one, else the part of the email before '@'."""
    principal = principal or {}
    meta = principal.get('user_metadata') or {}
    name = meta.get('full_name') or meta.get('name')
    if name:
        return str(name)
    email = principal.get('user_email') or ''
    return email.split('@')[0] if email else 'Unknown'


def add(sid: str, principal: Optional[dict], team_ids: Iterable[str]) -> None:
    principal = principal or {}
    with _LOCK:
        _CONNECTIONS[sid] = {
            'user_id': principal.get('user_id'),
            'name': display_name(principal),
            'team_ids': {str(t) for t in team_ids if t},
            'shared': bool(principal.get('shared')),
        }


def remove(sid: str) -> Optional[Dict[str, Any]]:
    """Forget a connection; returns what it was so the caller knows which teams changed."""
    with _LOCK:
        return _CONNECTIONS.pop(sid, None)


def teams_of(entry: Optional[Dict[str, Any]]) -> Set[str]:
    """Teams whose presence changes when this connection comes or goes (all known teams for a shared one)."""
    if not entry:
        return set()
    if entry['shared']:
        return known_teams()
    return set(entry['team_ids'])


def known_teams() -> Set[str]:
    with _LOCK:
        return {t for c in _CONNECTIONS.values() for t in c['team_ids']}


def snapshot(team_id: str) -> Dict[str, Any]:
    """`{team_id, online, users: [{user_id, name}], shared_sessions}` for one team."""
    team_id = str(team_id)
    with _LOCK:
        users: Dict[str, str] = {}
        shared = 0
        for c in _CONNECTIONS.values():
            if c['shared']:
                shared += 1
            elif team_id in c['team_ids'] and c['user_id']:
                users[c['user_id']] = c['name']
    listed: List[Dict[str, str]] = sorted(
        ({'user_id': uid, 'name': name} for uid, name in users.items()), key=lambda u: u['name'].lower()
    )
    return {'team_id': team_id, 'online': len(listed), 'users': listed, 'shared_sessions': shared}


def reset() -> None:
    """Tests only."""
    with _LOCK:
        _CONNECTIONS.clear()
