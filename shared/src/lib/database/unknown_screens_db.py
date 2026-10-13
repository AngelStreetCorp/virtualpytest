"""
Unknown-Screen Database Operations

Storage and retrieval for screens a device showed that have no node in its navigation tree.

A scan running on a host clusters its archived frames and writes what it found here; the
unknown-screens page reads it back. Nothing in this module mutates the navigation tree: that is
`navigation_nodes_db.save_node`, called by the accept route once a human has decided.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'userinterface_unknown_screens'

# Returned by retire_screens_not_seen when it raised. Distinct from 0, which is a real answer
# meaning "there was nothing to retire".
RETIRE_FAILED = -1

# Columns the scan is allowed to set, and the ones the page is allowed to change. Kept explicit so
# a caller cannot accidentally write a status or an accepted_node_id.
_SCAN_FIELDS = (
    'userinterface', 'device_model', 'cluster_dhash', 'classification', 'proposed_name',
    'screen_type', 'frame_count', 'signal', 'description', 'image_url', 'example_frames',
    'fingerprint', 'dom', 'last_scan_at',
)
_READ_FIELDS = (
    'id', 'userinterface', 'device_model', 'cluster_dhash', 'classification', 'status',
    'proposed_name', 'screen_type', 'frame_count', 'signal', 'description', 'image_url',
    'example_frames', 'fingerprint', 'dom', 'accepted_node_id', 'first_seen_at',
    'last_scan_at', 'updated_at', 'retired_at',
)


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': row.get('id'),
        'userinterface': row.get('userinterface'),
        'device_model': row.get('device_model'),
        'cluster_dhash': row.get('cluster_dhash'),
        'classification': row.get('classification') or 'unknown',
        'status': row.get('status') or 'pending',
        'proposed_name': row.get('proposed_name'),
        'screen_type': row.get('screen_type'),
        'frame_count': row.get('frame_count') if row.get('frame_count') is not None else 0,
        'signal': row.get('signal'),
        'description': row.get('description'),
        'image_url': row.get('image_url'),
        'example_frames': row.get('example_frames') or [],
        'fingerprint': row.get('fingerprint'),
        'dom': row.get('dom'),
        'accepted_node_id': row.get('accepted_node_id'),
        'first_seen_at': row.get('first_seen_at'),
        'last_scan_at': row.get('last_scan_at'),
        'updated_at': row.get('updated_at'),
        'retired_at': row.get('retired_at'),
    }


def list_unknown_screens(team_id: str,
                         userinterface: Optional[str] = None,
                         include_resolved: bool = False) -> List[Dict[str, Any]]:
    """Rows for the unknown-screens page.

    Content rows are always returned and the page decides what to show. Hiding them here would make
    the filter unauditable -- the whole point of storing them is that an operator can check the
    content test is not eating real UI.

    ``include_resolved`` False returns PENDING rows only. It previously meant "not dismissed", so an
    accepted or merged row still came back and sat under a heading called "Needs a name".
    """
    supabase = get_supabase()
    if supabase is None:
        print('[@db:unknown_screens_db:list] ERROR: Supabase client is None - check environment variables')
        return []
    if not team_id:
        print('[@db:unknown_screens_db:list] ERROR: team_id is required')
        return []

    try:
        query = supabase.table(TABLE).select(','.join(_READ_FIELDS)).eq('team_id', team_id)
        if userinterface:
            query = query.eq('userinterface', userinterface)
        query = query.is_('retired_at', 'null')
        if not include_resolved:
            query = query.eq('status', 'pending')
        result = query.order('frame_count', desc=True).execute()
        rows = [_row_to_dict(r) for r in (result.data or [])]
        print(f'[@db:unknown_screens_db:list] {len(rows)} rows for team={team_id} ui={userinterface or "ALL"}')
        return rows
    except Exception as exc:
        print(f'[@db:unknown_screens_db:list] ERROR querying {TABLE}: {exc}')
        return []


def pending_counts_by_interface(team_id: str) -> Dict[str, int]:
    """Unknown (not content, not resolved) row counts per interface.

    Backs the "N unknown" pill on the interface list. One query rather than one per row -- each
    Supabase call is a WAN hop and the list page already pays for several.
    """
    supabase = get_supabase()
    if supabase is None:
        print('[@db:unknown_screens_db:counts] ERROR: Supabase client is None - check environment variables')
        return {}
    if not team_id:
        return {}
    try:
        result = (supabase.table(TABLE)
                  .select('userinterface')
                  .eq('team_id', team_id)
                  .eq('classification', 'unknown')
                  .eq('status', 'pending')
                  .is_('retired_at', 'null')
                  .execute())
        counts: Dict[str, int] = {}
        for row in (result.data or []):
            name = row.get('userinterface')
            if name:
                counts[name] = counts.get(name, 0) + 1
        return counts
    except Exception as exc:
        print(f'[@db:unknown_screens_db:counts] ERROR: {exc}')
        return {}


def upsert_unknown_screens(team_id: str, userinterface: str,
                          rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write one scan's findings.

    Upserts on (team_id, userinterface, cluster_dhash) so a nightly re-scan updates the existing row
    instead of accumulating a duplicate every night. Returns counts for the caller to log; a partial
    failure is reported rather than raised, because a scan that half-succeeded should still record
    what it found.
    """
    supabase = get_supabase()
    if supabase is None:
        print('[@db:unknown_screens_db:upsert] ERROR: Supabase client is None - check environment variables')
        return {'inserted': 0, 'updated': 0, 'errors': 0}
    if not team_id or not userinterface:
        print('[@db:unknown_screens_db:upsert] ERROR: team_id and userinterface are required')
        return {'inserted': 0, 'updated': 0, 'errors': 0}

    now = datetime.now(timezone.utc).isoformat()
    inserted = updated = errors = 0

    for row in rows or []:
        dhash = (row.get('cluster_dhash') or '').strip()
        if not dhash:
            errors += 1
            continue
        payload = {k: row.get(k) for k in _SCAN_FIELDS if k in row}
        payload.update({
            'team_id': team_id,
            'userinterface': userinterface,
            'cluster_dhash': dhash,
            'classification': row.get('classification') or 'unknown',
            'last_scan_at': now,
            # Seen by this scan, therefore live again if a later one had retired it.
            'retired_at': None,
        })
        try:
            # update-then-insert: PostgREST upsert needs the full unique key and would otherwise
            # clobber first_seen_at on every scan.
            existing = (supabase.table(TABLE)
                        .select('id')
                        .eq('team_id', team_id)
                        .eq('userinterface', userinterface)
                        .eq('cluster_dhash', dhash)
                        .limit(1)
                        .execute())
            if existing.data:
                # On update, never let a None overwrite a stored image_url. A failed upload on
                # this scan must not destroy a still a previous scan already produced — it has
                # already done so twice (Star Trek, Bad Boys). The fix is to leave the field off
                # the update payload; the column keeps the value it had. Inserts (the else branch
                # below) are unaffected: a brand-new row with no thumbnail is a real row, not a
                # missing one, and the next successful scan will fill it in.
                if payload.get('image_url') is None:
                    payload.pop('image_url', None)
                supabase.table(TABLE).update(payload).eq('id', existing.data[0]['id']).execute()
                updated += 1
            else:
                supabase.table(TABLE).insert(payload).execute()
                inserted += 1
        except Exception as exc:
            errors += 1
            print(f'[@db:unknown_screens_db:upsert] ERROR on cluster {dhash[:12]}…: {exc}')

    print(f'[@db:unknown_screens_db:upsert] ui={userinterface}: {inserted} inserted, '
          f'{updated} updated, {errors} errors')
    return {'inserted': inserted, 'updated': updated, 'errors': errors}


def retire_screens_not_seen(team_id: str, userinterface: str,
                            seen_dhashes: List[str]) -> int:
    """Retire this interface's rows the scan did not see.

    Called ONCE at the end of a scan, with the whole scan's hashes. Without it a scan that samples
    a slightly different time window leaves the previous run's rows live forever, and the operator
    sees the same screen listed again and again.

    Only rows that HAVE been seen by some scan are retired. A row never seen is left alone, so a
    half-applied migration or a failed first scan cannot empty the table.

    NOT `builder.not_(...)`. In supabase-py 2.x `.not_` is a property returning a fresh filter
    builder, not a chainable method -- calling it as one raised
    "'SyncFilterRequestBuilder' object is not callable", the except below swallowed it, and this
    function returned 0 without retiring anything. Retirement had therefore never run once, which
    is why 308 rows stayed live across four scans while every scan reported "retired: 0".
    Negations hang off `.not_.` and each takes plain arguments: `.not_.is_(col, 'null')` and
    `.not_.in_(col, values)`.
    """
    supabase = get_supabase()
    if supabase is None or not team_id or not userinterface:
        return 0
    try:
        # Count first. A PostgREST PATCH returns no body unless asked, so counting the response
        # would report 0 for a successful update and hide exactly the regression above.
        counter = (supabase.table(TABLE)
                   .select('id', count='exact')
                   .eq('team_id', team_id)
                   .eq('userinterface', userinterface)
                   .not_.is_('last_scan_at', 'null'))
        if seen_dhashes:
            counter = counter.not_.in_('cluster_dhash', [str(h) for h in seen_dhashes])
        # Prefer the Content-Range count: len(data) would be capped by PostgREST's max-rows and
        # under-report a very stale table.
        counted = counter.execute()
        count = counted.count if counted.count is not None else len(counted.data or [])

        builder = (supabase.table(TABLE)
                   .update({'retired_at': datetime.now(timezone.utc).isoformat()})
                   .eq('team_id', team_id)
                   .eq('userinterface', userinterface)
                   .not_.is_('last_scan_at', 'null'))
        if seen_dhashes:
            builder = builder.not_.in_('cluster_dhash', [str(h) for h in seen_dhashes])
        builder.execute()

        if count:
            print(f'[@db:unknown_screens_db:retire] retired {count} row(s) for '
                  f'{userinterface} not seen in this scan')
        return count
    except Exception as exc:
        # Deliberately swallowed, because the upsert in the same request has already committed and
        # a raise here would 500 a POST whose rows really were written -- reporting a successful
        # scan as failed. RETIRE_FAILED is returned instead of 0 so the caller can tell "nothing
        # needed retiring" from "retiring blew up". Swallowing into 0 is what hid this for four
        # scans: every run reported retired: 0 and looked healthy.
        print(f'[@db:unknown_screens_db:retire] ERROR: {exc}')
        return RETIRE_FAILED


def get_unknown_screen(team_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    """A single row, for the accept/dismiss routes."""
    supabase = get_supabase()
    if supabase is None or not team_id or not row_id:
        return None
    try:
        result = (supabase.table(TABLE)
                  .select(','.join(_READ_FIELDS))
                  .eq('team_id', team_id)
                  .eq('id', row_id)
                  .limit(1)
                  .execute())
        if not result.data:
            return None
        return _row_to_dict(result.data[0])
    except Exception as exc:
        print(f'[@db:unknown_screens_db:get] ERROR: {exc}')
        return None


def resolve_unknown_screen(team_id: str, row_id: str, status: str,
                           accepted_node_id: Optional[str] = None,
                           label: Optional[str] = None) -> bool:
    """Record a human decision: 'accepted', 'merged' or 'dismissed'.

    Guarded on status='pending' so a double-click on Accept cannot create two nodes -- the route
    reads the row first and bails if it is already resolved, and this WHERE clause is the backstop
    for the race.
    """
    supabase = get_supabase()
    if supabase is None or not team_id or not row_id:
        return False
    payload: Dict[str, Any] = {'status': status}
    if accepted_node_id:
        payload['accepted_node_id'] = accepted_node_id
    if label:
        payload['proposed_name'] = label
    try:
        result = (supabase.table(TABLE)
                  .update(payload)
                  .eq('team_id', team_id)
                  .eq('id', row_id)
                  .eq('status', 'pending')
                  .execute())
        ok = bool(result.data)
        if not ok:
            print(f'[@db:unknown_screens_db:resolve] row {row_id} was not pending — refusing '
                  f'(double accept, or already dismissed)')
        return ok
    except Exception as exc:
        print(f'[@db:unknown_screens_db:resolve] ERROR: {exc}')
        return False