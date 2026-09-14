"""
Database layer for verifications_references table.
Handles reference assets (reference_image and reference_text) separately from verification actions.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from shared.src.lib.utils.supabase_utils import get_supabase_client


# ---------------------------------------------------------------------------
# Process-local TTL cache for get_references().
#
# Motivation: kpi_executor scans (and the live verifier) call get_references
# multiple times per measurement — typically 6+ identical REST queries per
# scan (settings_text + settings + …, across N frames). Each REST call is
# ~100 ms on a Raspberry Pi 4 talking to the proxy, so a single scan was
# burning ~600 ms on redundant lookups.
#
# References change only when the user saves / updates / deletes one in
# the editor. We invalidate the cache on those writes from this module
# (save_reference, delete_reference, update_references_userinterface_name).
# The 60 s TTL is a backstop: if some other process modifies references
# directly (admin tool, migration), we'll see the new state within a minute.
#
# Cache key = the full filter tuple. Lists are converted to tuples so
# they're hashable. We intentionally cache failures too (`success=False`
# results) — they're cheap to recompute but the failure shape is typically
# transient (transport blip), so we only cache them for 5 s.
# ---------------------------------------------------------------------------
_REFERENCES_CACHE_TTL_SUCCESS = 60.0
_REFERENCES_CACHE_TTL_FAILURE = 5.0
_references_cache: Dict[Tuple, Tuple[float, Dict]] = {}
_references_cache_lock = threading.Lock()


def _references_cache_key(
    team_id: str,
    reference_type: Optional[str],
    userinterface_name: Optional[str],
    userinterface_names: Optional[List[str]],
    name: Optional[str],
    compatible_ui_names: Optional[List[str]],
) -> Tuple:
    return (
        team_id,
        reference_type,
        userinterface_name,
        tuple(userinterface_names) if userinterface_names else None,
        name,
        tuple(compatible_ui_names) if compatible_ui_names else None,
    )


def _invalidate_references_cache() -> None:
    """Drop all cached entries — called on any write to verifications_references."""
    with _references_cache_lock:
        _references_cache.clear()


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def save_reference(name: str, userinterface_name: str, reference_type: str, team_id: str, r2_path: str = None, r2_url: str = None, area: Dict = None, shared: bool = False) -> Dict:
    """
    Save reference asset to verifications_references table.

    Args:
        name: Reference name/identifier
        userinterface_name: Origin userinterface name (e.g., 'example_androidtv'). For
            shared rows this is still recorded as the row's origin.
        reference_type: Reference type ('reference_image' or 'reference_text')
        team_id: Team ID for RLS
        r2_path: Path in R2 storage
        r2_url: Complete R2 URL
        area: Area coordinates and additional data
        shared: When True, the row is visible+editable by any UI sharing a device
            model with userinterface_name. Uniqueness is enforced on
            (team_id, name, reference_type) for shared rows, and on
            (team_id, name, userinterface_name, reference_type) for local rows.

    Returns:
        Dict: {'success': bool, 'reference_id': str, 'error': str}
    """
    try:
        supabase = get_supabase()

        # Validate reference_type
        if reference_type not in ['reference_image', 'reference_text']:
            return {
                'success': False,
                'error': 'reference_type must be "reference_image" or "reference_text"'
            }

        # Round area coordinates to 2 decimal places before saving
        if area:
            rounded_area = {}
            for key, value in area.items():
                if isinstance(value, (int, float)):
                    rounded_area[key] = round(value, 2)
                else:
                    rounded_area[key] = value
            area = rounded_area

        # Resolve the rename-stable userinterface id so the row is keyed by id
        # (lookups filter on this; userinterface_name is denormalized display).
        from shared.src.lib.utils.reference_utils import reference_storage_key
        _ui_key = reference_storage_key(userinterface_name, team_id)
        _ui_id = _ui_key if _ui_key != userinterface_name else None

        # Prepare reference data
        reference_data = {
            'name': name,
            'userinterface_name': userinterface_name,
            'userinterface_id': _ui_id,
            'device_model': userinterface_name,  # Keep device_model in sync for now
            'reference_type': reference_type,
            'team_id': team_id,
            'r2_path': r2_path,
            'r2_url': r2_url,
            'area': area,  # Store as JSONB directly
            'shared': shared,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        print(f"[@db:verifications_references:save_reference] Saving reference: {name} for userinterface: {userinterface_name} (shared={shared})")

        # Partial unique indexes mean ON CONFLICT inference is brittle through
        # PostgREST. Do an explicit select-then-insert-or-update keyed on the
        # right uniqueness rule for shared vs local rows.
        if shared:
            existing_q = (
                supabase.table('verifications_references')
                .select('id')
                .eq('team_id', team_id)
                .eq('name', name)
                .eq('reference_type', reference_type)
                .eq('shared', True)
                .limit(1)
                .execute()
            )
        else:
            existing_q = (
                supabase.table('verifications_references')
                .select('id')
                .eq('team_id', team_id)
                .eq('name', name)
                .eq('userinterface_name', userinterface_name)
                .eq('reference_type', reference_type)
                .eq('shared', False)
                .limit(1)
                .execute()
            )

        if existing_q.data:
            existing_id = existing_q.data[0]['id']
            result = (
                supabase.table('verifications_references')
                .update(reference_data)
                .eq('id', existing_id)
                .execute()
            )
        else:
            result = supabase.table('verifications_references').insert(reference_data).execute()

        if result.data:
            saved_reference = result.data[0]
            print(f"[@db:verifications_references:save_reference] Successfully saved reference: {saved_reference['id']}")
            _invalidate_references_cache()
            return {
                'success': True,
                'reference_id': saved_reference['id'],
                'reference': saved_reference
            }
        else:
            print(f"[@db:verifications_references:save_reference] No data returned from save")
            return {
                'success': False,
                'error': 'No data returned from database'
            }

    except Exception as e:
        print(f"[@db:verifications_references:save_reference] Error saving reference: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

# ---------------------------------------------------------------------------
# Reference versioning (verifications_reference_versions)
#
# Every overwrite of a reference snapshots the PREVIOUS {image + area} so the
# user can restore an earlier capture from the References page (Grafana-style).
# Retention: newest 10 per reference; older rows + their R2 objects are pruned
# on each new snapshot.
#
# IMPORTANT ordering: image bytes live in R2 and the live key is OVERWRITTEN by
# upload_reference_image BEFORE the DB save runs. So snapshot_reference_version
# MUST be called by each save flow BEFORE the overwrite (R2 upload for image
# refs / DB update for text refs) — at which point the OLD bytes/area are still
# live. It is a no-op on first capture (no existing row).
# ---------------------------------------------------------------------------
_REFERENCE_VERSIONS_KEEP = 10


def _strip_jpg(r2_path: str) -> str:
    """Return the path without a trailing .jpg (for building filtered siblings)."""
    return r2_path[:-4] if r2_path.endswith('.jpg') else r2_path


def _find_reference_row(team_id: str, name: str, userinterface_name: str, reference_type: str) -> Optional[Dict]:
    """Resolve the concrete reference row a save flow is about to overwrite.

    Matches the local row (team, name, ui, type) first; falls back to the
    shared row (team, name, type) — mirroring save_reference's uniqueness rules.
    """
    supabase = get_supabase()
    local = (
        supabase.table('verifications_references')
        .select('id, r2_path, r2_url, area, reference_type, userinterface_name')
        .eq('team_id', team_id).eq('name', name)
        .eq('userinterface_name', userinterface_name)
        .eq('reference_type', reference_type).limit(1).execute()
    )
    if local.data:
        return local.data[0]
    shared = (
        supabase.table('verifications_references')
        .select('id, r2_path, r2_url, area, reference_type, userinterface_name')
        .eq('team_id', team_id).eq('name', name)
        .eq('reference_type', reference_type).eq('shared', True).limit(1).execute()
    )
    return shared.data[0] if shared.data else None


def snapshot_reference_version(name: str, userinterface_name: str, reference_type: str, team_id: str) -> None:
    """Snapshot the about-to-be-overwritten reference state into history.

    Best-effort: logs and returns on any error, never raises — a snapshot
    failure must never block a capture. Call BEFORE the overwrite.
    """
    try:
        row = _find_reference_row(team_id, name, userinterface_name, reference_type)
        if not row:
            return  # first capture — nothing to preserve

        reference_id = row['id']
        old_area = row.get('area')
        old_r2_path = row.get('r2_path')
        origin_ui = row.get('userinterface_name') or userinterface_name

        hist_r2_path = None
        hist_r2_url = None

        # Image refs: copy the live R2 object (+ greyscale/binary) to history/
        # while the OLD bytes are still at the live key.
        if reference_type == 'reference_image' and old_r2_path:
            ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]
            from shared.src.lib.utils.reference_utils import reference_storage_key
            ui_key = reference_storage_key(origin_ui, team_id)
            base = f"reference-images/{ui_key}/history/{name}/{ts}"
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            cf = get_cloudflare_utils()
            copy_res = cf.copy_file(old_r2_path, f"{base}.jpg")
            if copy_res.get('success'):
                hist_r2_path = f"{base}.jpg"
                hist_r2_url = copy_res.get('url', '')
                live_base = _strip_jpg(old_r2_path)
                for suffix in ('_greyscale', '_binary'):
                    cf.copy_file(f"{live_base}{suffix}.jpg", f"{base}{suffix}.jpg")
            else:
                print(f"[@db:verifications_references:snapshot_reference_version] "
                      f"image copy failed for {old_r2_path}: {copy_res.get('error')} "
                      f"(recording area-only version)")

        supabase = get_supabase()
        vq = (
            supabase.table('verifications_reference_versions')
            .select('version_number')
            .eq('reference_id', reference_id)
            .order('version_number', desc=True).limit(1).execute()
        )
        next_version = (vq.data[0]['version_number'] + 1) if vq.data else 1

        supabase.table('verifications_reference_versions').insert({
            'reference_id': reference_id,
            'team_id': team_id,
            'version_number': next_version,
            'reference_type': reference_type,
            'r2_path': hist_r2_path,
            'r2_url': hist_r2_url,
            'area': old_area,
        }).execute()

        print(f"[@db:verifications_references:snapshot_reference_version] "
              f"saved v{next_version} of {name} ({reference_type})")
        _prune_reference_versions(reference_id)

    except Exception as e:
        print(f"[@db:verifications_references:snapshot_reference_version] warning: {e}")


def _prune_reference_versions(reference_id: str, keep: int = _REFERENCE_VERSIONS_KEEP) -> None:
    """Keep newest `keep` versions for a reference; delete older rows + R2 objects."""
    try:
        supabase = get_supabase()
        rows = (
            supabase.table('verifications_reference_versions')
            .select('id, r2_path')
            .eq('reference_id', reference_id)
            .order('version_number', desc=True).execute()
        ).data or []
        stale = rows[keep:]
        if not stale:
            return
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        cf = get_cloudflare_utils()
        for r in stale:
            rp = r.get('r2_path')
            if rp:
                base = _strip_jpg(rp)
                cf.delete_file(rp)
                cf.delete_file(f"{base}_greyscale.jpg")
                cf.delete_file(f"{base}_binary.jpg")
            supabase.table('verifications_reference_versions').delete().eq('id', r['id']).execute()
        print(f"[@db:verifications_references:_prune_reference_versions] pruned {len(stale)} old version(s)")
    except Exception as e:
        print(f"[@db:verifications_references:_prune_reference_versions] warning: {e}")


def get_reference_versions(team_id: str, reference_id: str) -> Dict:
    """List version history (newest first) for a reference."""
    try:
        supabase = get_supabase()
        rows = (
            supabase.table('verifications_reference_versions')
            .select('*')
            .eq('team_id', team_id).eq('reference_id', reference_id)
            .order('version_number', desc=True).execute()
        ).data or []
        return {'success': True, 'versions': rows, 'count': len(rows)}
    except Exception as e:
        print(f"[@db:verifications_references:get_reference_versions] Error: {e}")
        return {'success': False, 'error': str(e), 'versions': [], 'count': 0}


def restore_reference_version(team_id: str, reference_id: str, version_id: str) -> Dict:
    """Restore a reference to an earlier version.

    The restore is itself undoable: the CURRENT live state is snapshotted into
    history first (so it becomes the new top version), then the chosen version's
    image is copied back onto the live key and its area is restored.
    """
    try:
        supabase = get_supabase()

        vq = (
            supabase.table('verifications_reference_versions')
            .select('*').eq('id', version_id)
            .eq('team_id', team_id).eq('reference_id', reference_id).limit(1).execute()
        )
        if not vq.data:
            return {'success': False, 'error': 'Version not found'}
        version = vq.data[0]

        rq = (
            supabase.table('verifications_references')
            .select('*').eq('id', reference_id).eq('team_id', team_id).limit(1).execute()
        )
        if not rq.data:
            return {'success': False, 'error': 'Reference not found'}
        ref = rq.data[0]

        name = ref['name']
        ui = ref['userinterface_name']
        rtype = ref['reference_type']

        # 1. Snapshot the CURRENT live state first (makes restore undoable).
        snapshot_reference_version(name, ui, rtype, team_id)

        # 2. Image refs: copy the history image (+ siblings) back onto the live key.
        if rtype == 'reference_image' and version.get('r2_path') and ref.get('r2_path'):
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            cf = get_cloudflare_utils()
            cf.copy_file(version['r2_path'], ref['r2_path'])
            vbase = _strip_jpg(version['r2_path'])
            lbase = _strip_jpg(ref['r2_path'])
            for suffix in ('_greyscale', '_binary'):
                cf.copy_file(f"{vbase}{suffix}.jpg", f"{lbase}{suffix}.jpg")

        # 3. Restore the area (text restore relies entirely on this). Live key is
        #    unchanged so r2_path/r2_url stay the same.
        supabase.table('verifications_references').update({
            'area': version.get('area'),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', reference_id).execute()

        _invalidate_references_cache()
        print(f"[@db:verifications_references:restore_reference_version] "
              f"restored {name} to v{version.get('version_number')}")
        return {
            'success': True,
            'reference_id': reference_id,
            'restored_version': version.get('version_number'),
        }

    except Exception as e:
        print(f"[@db:verifications_references:restore_reference_version] Error: {e}")
        return {'success': False, 'error': str(e)}


def get_references(team_id: str, reference_type: str = None, userinterface_name: str = None, userinterface_names: List[str] = None, name: str = None, compatible_ui_names: List[str] = None, bust_cache: bool = False) -> Dict:
    """
    Get references with optional filtering.

    Args:
        team_id: Team ID for RLS
        reference_type: Filter by type ('reference_image' or 'reference_text')
        userinterface_name: Filter by single userinterface name (deprecated - use userinterface_names)
        userinterface_names: Filter by multiple userinterface names (more efficient than post-filtering)
        name: Filter by name (partial match)
        compatible_ui_names: When provided, the result also includes shared
            references whose origin userinterface_name is in this list. Caller
            is expected to compute this as the set of UIs in the team whose
            models[] intersects with the active UI's models[]. Local
            (shared=false) rows are still scoped by userinterface_names.
        bust_cache: Skip the cache read and query the DB directly. Required for
            reads that must reflect a just-completed write made in ANOTHER
            process. References are written on the backend_host (saveImage /
            saveText), which only invalidates the host's process-local cache —
            the backend_server's cache (which serves getAllReferences to the
            editor dropdown) is never invalidated by those writes and would
            otherwise return a stale list for up to the 60s TTL. The fresh
            result is still written back to the cache.

    Returns:
        Dict: {'success': bool, 'references': List[Dict], 'count': int, 'error': str}
    """
    # Serve from process-local cache when fresh. See module-level comment
    # for invalidation policy.
    cache_key = _references_cache_key(team_id, reference_type, userinterface_name,
                                      userinterface_names, name, compatible_ui_names)
    now = time.time()
    with _references_cache_lock:
        cached = None if bust_cache else _references_cache.get(cache_key)
    if cached:
        cached_ts, cached_value = cached
        ttl = _REFERENCES_CACHE_TTL_SUCCESS if cached_value.get('success') else _REFERENCES_CACHE_TTL_FAILURE
        if now - cached_ts < ttl:
            print(f"[@db:verifications_references:get_references] cache hit "
                  f"(age {now - cached_ts:.1f}s) name={name} ui={userinterface_name} "
                  f"count={cached_value.get('count', 0)}")
            return cached_value

    # Retry the read on transient transport drops. The self-hosted PostgREST
    # intermittently closes a kept-alive connection that the client then
    # reuses, surfacing as "Server disconnected" / connection-reset. A read is
    # idempotent, and a swallowed drop here is read by callers
    # (resolve_reference_area_backend) as "reference not found" — which fails a
    # whole verification/navigation for an asset that actually exists. Retry
    # before giving up.
    last_error = None
    for attempt in range(1, 4):  # up to 3 attempts
        try:
            supabase = get_supabase()

            print(f"[@db:verifications_references:get_references] Getting references with filters: type={reference_type}, userinterface={userinterface_name}, userinterface_names={userinterface_names}, compatible_ui_names={compatible_ui_names}, name={name}")
            print(f"[@db:verifications_references:get_references] Using team_id: {team_id}")

            local_names = userinterface_names if userinterface_names else ([userinterface_name] if userinterface_name else None)

            # Start with base query
            query = supabase.table('verifications_references').select('*').eq('team_id', team_id)

            # Add filters
            if reference_type:
                query = query.eq('reference_type', reference_type)

            if name:
                query = query.ilike('name', f'%{name}%')

            # Userinterface scoping: build (local) OR (shared in compatible set).
            if local_names and compatible_ui_names:
                # PostgREST OR with nested AND. Names contain only [A-Za-z0-9_-]
                # in practice (validated upstream); no escaping needed.
                local_in = ','.join(local_names)
                shared_in = ','.join(compatible_ui_names)
                query = query.or_(
                    f"and(shared.eq.false,userinterface_name.in.({local_in})),"
                    f"and(shared.eq.true,userinterface_name.in.({shared_in}))"
                )
            elif local_names:
                # Rename-safe scoping: key by the stable userinterface id when every
                # local name resolves to one (reference_storage_key returns the id,
                # or the name unchanged if unresolvable). Fall back to name for
                # orphan/legacy UIs so those rows keep resolving.
                from shared.src.lib.utils.reference_utils import reference_storage_key
                pairs = [(n, reference_storage_key(n, team_id)) for n in local_names]
                if pairs and all(key != n for n, key in pairs):
                    query = query.in_('userinterface_id', [key for _, key in pairs])
                else:
                    query = query.in_('userinterface_name', local_names)

            # Execute query with ordering
            result = query.order('created_at', desc=True).execute()

            print(f"[@db:verifications_references:get_references] Found {len(result.data)} references")
            response: Dict = {
                'success': True,
                'references': result.data,
                'count': len(result.data)
            }
            with _references_cache_lock:
                _references_cache[cache_key] = (time.time(), response)
            return response

        except Exception as e:
            last_error = e
            print(f"[@db:verifications_references:get_references] Attempt {attempt}/3 failed: {str(e)}")
            if attempt < 3:
                time.sleep(0.3 * attempt)  # 0.3s, 0.6s backoff
                continue

    # All attempts failed — this is a DB/transport error, NOT "no such
    # reference". Cached only briefly (5s) so a blip doesn't poison lookups.
    print(f"[@db:verifications_references:get_references] Error getting references after retries: {str(last_error)}")
    response = {
        'success': False,
        'error': str(last_error),
        'references': [],
        'count': 0
    }
    with _references_cache_lock:
        _references_cache[cache_key] = (time.time(), response)
    return response

def get_all_references(team_id: str) -> Dict:
    """
    Get all references for a team.
    
    Args:
        team_id: Team ID for RLS
        
    Returns:
        Dict: {'success': bool, 'references': List[Dict], 'count': int, 'error': str}
    """
    try:
        supabase = get_supabase()
        
        print(f"[@db:verifications_references:get_all_references] Getting all references for team: {team_id}")
        
        result = supabase.table('verifications_references').select('*').eq('team_id', team_id).order('created_at', desc=True).execute()
        
        print(f"[@db:verifications_references:get_all_references] Found {len(result.data)} references")
        return {
            'success': True,
            'references': result.data,
            'count': len(result.data)
        }
        
    except Exception as e:
        print(f"[@db:verifications_references:get_all_references] Error getting references: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'references': [],
            'count': 0
        }

def _delete_reference_storage(deleted_rows: list) -> None:
    """Remove R2 objects for reference rows that were just deleted from the DB.

    For each row: the live image (+ its `_greyscale`/`_binary` derivatives) and
    the whole `history/{name}/` version folder. Best-effort — logs and returns
    on any error so a storage hiccup never turns a completed DB delete into a
    failure. Version DB rows are removed by FK cascade; this reclaims the bytes.
    """
    try:
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        cf = get_cloudflare_utils()
        for row in deleted_rows or []:
            rp = row.get('r2_path')
            if not rp:
                continue
            base = _strip_jpg(rp)
            cf.delete_file(rp)
            cf.delete_file(f"{base}_greyscale.jpg")
            cf.delete_file(f"{base}_binary.jpg")
            # history/{name}/ lives next to the live object: reference-images/{ui_key}/history/{name}/
            ui_dir = rp.rsplit('/', 1)[0] if '/' in rp else ''
            name = row.get('name')
            if ui_dir and name:
                cf.delete_prefix(f"{ui_dir}/history/{name}/")
    except Exception as e:
        print(f"[@db:verifications_references:_delete_reference_storage] "
              f"warning (orphaned objects may remain): {e}")


def delete_reference(team_id: str, reference_id: str = None, name: str = None, userinterface_name: str = None, reference_type: str = None) -> Dict:
    """
    Delete reference by ID or by identifiers.
    
    Args:
        team_id: Team ID for RLS
        reference_id: Reference ID (if deleting by ID)
        name: Reference name (if deleting by identifiers)
        userinterface_name: Userinterface name (if deleting by identifiers)
        reference_type: Reference type (if deleting by identifiers)
        
    Returns:
        Dict: {'success': bool, 'error': str}
    """
    try:
        supabase = get_supabase()
        
        if reference_id:
            print(f"[@db:verifications_references:delete_reference] Deleting reference by ID: {reference_id}")
            result = supabase.table('verifications_references').delete().eq('id', reference_id).eq('team_id', team_id).execute()
        elif name and userinterface_name and reference_type:
            print(f"[@db:verifications_references:delete_reference] Deleting reference: {name} ({reference_type}) for userinterface: {userinterface_name}")
            result = supabase.table('verifications_references').delete().eq('name', name).eq('userinterface_name', userinterface_name).eq('reference_type', reference_type).eq('team_id', team_id).execute()
        else:
            return {
                'success': False,
                'error': 'Must provide either reference_id or name/userinterface_name/reference_type'
            }
        
        success = len(result.data) > 0
        if success:
            print(f"[@db:verifications_references:delete_reference] Successfully deleted reference")
            _delete_reference_storage(result.data)
            _invalidate_references_cache()
            return {'success': True}
        else:
            print(f"[@db:verifications_references:delete_reference] Reference not found or already deleted")
            return {
                'success': False,
                'error': 'Reference not found'
            }
        
    except Exception as e:
        print(f"[@db:verifications_references:delete_reference] Error deleting reference: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def update_references_userinterface_name(team_id: str, userinterface_id: str, old_name: str, new_name: str) -> Dict:
    """
    Cascade rename userinterface on all references.
    
    Args:
        team_id: Team ID for RLS
        userinterface_id: ID of the userinterface being renamed (preferred match)
        old_name: Previous userinterface name (fallback match when id is missing)
        new_name: New userinterface name to set
    
    Returns:
        Dict: {'success': bool, 'updated_count': int, 'error': str}
    """
    try:
        supabase = get_supabase()
        total_updated = 0

        # Update by userinterface_id when available
        if userinterface_id:
            result_id = (
                supabase
                .table('verifications_references')
                .update({'userinterface_name': new_name, 'userinterface_id': userinterface_id})
                .eq('team_id', team_id)
                .eq('userinterface_id', userinterface_id)
                .execute()
            )
            total_updated += len(result_id.data or [])

        # Update by old name to catch legacy rows without userinterface_id
        if old_name:
            result_name = (
                supabase
                .table('verifications_references')
                .update({'userinterface_name': new_name, 'userinterface_id': userinterface_id})
                .eq('team_id', team_id)
                .eq('userinterface_name', old_name)
                .execute()
            )
            total_updated += len(result_name.data or [])

        print(f"[@db:verifications_references:update_references_userinterface_name] Renamed references -> {total_updated} rows")
        if total_updated > 0:
            _invalidate_references_cache()
        return {'success': True, 'updated_count': total_updated}

    except Exception as e:
        print(f"[@db:verifications_references:update_references_userinterface_name] Error: {e}")
        return {'success': False, 'error': str(e), 'updated_count': 0}
