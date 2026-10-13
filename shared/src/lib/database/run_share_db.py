"""Run share snapshots (TASK-42).

A snapshot stores an already-sanitized payload plus the SHA-256 of a random
bearer token; the plaintext token is returned once by the creating route and
never stored. A token read must present BOTH the snapshot id and a token whose
hash matches that row — a valid token for one snapshot cannot select another.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.database.run_rpc import get_supabase, normalize_row

_UUID_KEYS = ('id', 'team_id', 'run_id')
_LIST_COLUMNS = 'id, team_id, creator_id, run_kind, run_id, expires_at, revoked_at, revoked_by, created_at'


def hash_share_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def insert_snapshot(*, team_id: str, creator_id: str, run_kind: str, run_id: str,
                    payload: Dict[str, Any], token_hash: str, created_at: datetime,
                    expires_at: datetime) -> Dict[str, Any]:
    row = {
        'team_id': team_id,
        'creator_id': creator_id,
        'run_kind': run_kind,
        'run_id': run_id,
        'sanitized_payload': payload,
        'token_hash': token_hash,
        'created_at': created_at.isoformat(),
        'expires_at': expires_at.isoformat(),
    }
    result = get_supabase().table('run_share_snapshots').insert(row).execute()
    created = normalize_row(result.data[0], _UUID_KEYS)
    created.pop('token_hash', None)
    return created


def list_snapshots(team_id: str, run_kind: str, run_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    result = (get_supabase().table('run_share_snapshots').select(_LIST_COLUMNS)
              .eq('team_id', team_id).eq('run_kind', run_kind).eq('run_id', run_id)
              .order('created_at', desc=True).limit(limit).execute())
    return [normalize_row(r, _UUID_KEYS) for r in (result.data or [])]


def get_snapshot(team_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
    """Team-scoped read for management/export (never exposes the token hash)."""
    result = (get_supabase().table('run_share_snapshots')
              .select(_LIST_COLUMNS + ', sanitized_payload')
              .eq('team_id', team_id).eq('id', snapshot_id).limit(1).execute())
    rows = result.data or []
    return normalize_row(rows[0], _UUID_KEYS, ('sanitized_payload',)) if rows else None


def revoke_snapshot(team_id: str, snapshot_id: str, revoked_by: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table('run_share_snapshots')
              .update({'revoked_at': datetime.now(timezone.utc).isoformat(), 'revoked_by': revoked_by})
              .eq('team_id', team_id).eq('id', snapshot_id).is_('revoked_at', 'null')
              .execute())
    rows = result.data or []
    if not rows:
        return None
    row = normalize_row(rows[0], _UUID_KEYS)
    row.pop('token_hash', None)
    row.pop('sanitized_payload', None)
    return row


def read_snapshot_with_token(snapshot_id: str, token: str,
                             now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Token-only read. Returns None unless id + token hash match, unexpired, unrevoked.

    The query filters on both the id and the hash, and the hash is compared
    again in constant time before anything is returned.
    """
    if not snapshot_id or not token:
        return None
    token_hash = hash_share_token(token)
    result = (get_supabase().table('run_share_snapshots')
              .select('id, run_kind, sanitized_payload, token_hash, expires_at, revoked_at, created_at')
              .eq('id', snapshot_id).eq('token_hash', token_hash).limit(1).execute())
    rows = result.data or []
    if not rows:
        return None
    row = rows[0]
    if not hmac.compare_digest(str(row.get('token_hash') or ''), token_hash):
        return None
    if row.get('revoked_at'):
        return None
    expires_at = _parse_ts(row.get('expires_at'))
    if expires_at is None or (now or datetime.now(timezone.utc)) >= expires_at:
        return None
    row = normalize_row(dict(row), ('id',), ('sanitized_payload',))
    row.pop('token_hash', None)
    row.pop('revoked_at', None)
    return row
