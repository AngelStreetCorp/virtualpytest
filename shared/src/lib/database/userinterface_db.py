"""
User Interface Database Operations

This module provides functions for managing user interfaces in the database.
User interfaces define the different UI contexts for applications being tested.
"""

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def get_all_userinterfaces(team_id: str) -> List[Dict]:
    """Retrieve all user interfaces for a team from Supabase."""
    supabase = get_supabase()

    if supabase is None:
        print(f"[@db:userinterface_db:get_all_userinterfaces] ERROR: Supabase client is None - check environment variables")
        return []

    if not team_id:
        print(f"[@db:userinterface_db:get_all_userinterfaces] ERROR: team_id is required but got: {team_id}")
        return []

    try:
        print(f"[@db:userinterface_db:get_all_userinterfaces] Querying for team_id: {team_id}")
        result = supabase.table('userinterfaces').select(
            'id', 'name', 'models', 'min_version', 'max_version', 'team_id', 'created_at', 'updated_at',
            'mode', 'dev_userinterface_id', 'published_at', 'published_version'
        ).eq('team_id', team_id).order('created_at', desc=False).execute()

        print(f"[@db:userinterface_db:get_all_userinterfaces] Query successful, got {len(result.data) if result.data else 0} results")

        userinterfaces = []
        for ui in result.data:
            userinterfaces.append({
                'id': ui['id'],
                'name': ui['name'],
                'models': ui.get('models', []),
                'min_version': ui.get('min_version', ''),
                'max_version': ui.get('max_version', ''),
                'team_id': ui['team_id'],
                'created_at': ui['created_at'],
                'updated_at': ui['updated_at'],
                'mode': ui.get('mode', 'dev'),
                'dev_userinterface_id': ui.get('dev_userinterface_id'),
                'published_at': ui.get('published_at'),
                'published_version': ui.get('published_version'),
            })

        return userinterfaces
    except Exception as e:
        print(f"[@db:userinterface_db:get_all_userinterfaces] EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_userinterface(interface_id: str, team_id: str) -> Optional[Dict]:
    """Retrieve a user interface by ID and team ID from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('userinterfaces').select(
            'id', 'name', 'models', 'min_version', 'max_version', 'team_id', 'created_at', 'updated_at',
            'mode', 'dev_userinterface_id', 'published_at', 'published_version'
        ).eq('id', interface_id).eq('team_id', team_id).single().execute()

        if result.data:
            ui = result.data
            return {
                'id': ui['id'],
                'name': ui['name'],
                'models': ui.get('models', []),
                'min_version': ui.get('min_version', ''),
                'max_version': ui.get('max_version', ''),
                'team_id': ui['team_id'],
                'created_at': ui['created_at'],
                'updated_at': ui['updated_at'],
                'mode': ui.get('mode', 'dev'),
                'dev_userinterface_id': ui.get('dev_userinterface_id'),
                'published_at': ui.get('published_at'),
                'published_version': ui.get('published_version'),
            }
        return None
    except Exception as e:
        print(f"[@db:userinterface_db:get_userinterface] Error: {e}")
        return None

def get_userinterface_by_name(interface_name: str, team_id: str, mode: str = 'dev') -> Optional[Dict]:
    """Retrieve a user interface by name, team ID and mode from Supabase.

    A published interface exists as TWO rows sharing one name (mode 'dev' and
    'prod'), so name lookups must be mode-scoped — .limit(1), never .single(),
    which throws on multiple matches. mode='prod' with no published row returns
    None (no dev fallback: an explicit prod run must never silently hit dev).
    """
    supabase = get_supabase()
    try:
        result = supabase.table('userinterfaces').select(
            'id', 'name', 'models', 'mode', 'dev_userinterface_id', 'published_version'
        ).eq('name', interface_name).eq('team_id', team_id).eq('mode', mode).limit(1).execute()

        if result.data:
            ui = result.data[0]
            return {
                'id': ui['id'],
                'name': ui['name'],
                'models': ui.get('models', []),
                'mode': ui.get('mode', 'dev'),
                'dev_userinterface_id': ui.get('dev_userinterface_id'),
                'published_version': ui.get('published_version'),
            }
        return None
    except Exception as e:
        print(f"[@db:userinterface_db:get_userinterface_by_name] Error: {e}")
        return None

def create_userinterface(interface_data: Dict, team_id: str, creator_id: str = None) -> Optional[Dict]:
    """Create a new user interface."""
    supabase = get_supabase()
    try:
        insert_data = {
            'name': interface_data['name'],
            'models': interface_data.get('models', []),
            'min_version': interface_data.get('min_version', ''),
            'max_version': interface_data.get('max_version', ''),
            'team_id': team_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        result = supabase.table('userinterfaces').insert(insert_data).execute()

        if result.data and len(result.data) > 0:
            ui = result.data[0]
            return {
                'id': ui['id'],
                'name': ui['name'],
                'models': ui.get('models', []),
                'min_version': ui.get('min_version', ''),
                'max_version': ui.get('max_version', ''),
                'team_id': ui['team_id'],
                'created_at': ui['created_at'],
                'updated_at': ui['updated_at']
            }
        return None
    except Exception as e:
        print(f"[@db:userinterface_db:create_userinterface] Error: {e}")
        return None

def update_userinterface(interface_id: str, interface_data: Dict, team_id: str) -> Optional[Dict]:
    """Update an existing user interface."""
    supabase = get_supabase()
    try:
        update_data = {
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        if 'name' in interface_data:
            update_data['name'] = interface_data['name']
        if 'min_version' in interface_data:
            update_data['min_version'] = interface_data.get('min_version', '')
        if 'max_version' in interface_data:
            update_data['max_version'] = interface_data.get('max_version', '')
        if 'models' in interface_data:
            update_data['models'] = interface_data['models']

        result = supabase.table('userinterfaces').update(update_data).eq('id', interface_id).eq('team_id', team_id).execute()

        if result.data and len(result.data) > 0:
            ui = result.data[0]

            # Same-name invariant: a prod snapshot always carries its dev
            # source's name, so renaming a dev row renames its prod row too.
            if 'name' in update_data and ui.get('mode', 'dev') == 'dev':
                try:
                    supabase.table('userinterfaces').update(
                        {'name': update_data['name'], 'updated_at': update_data['updated_at']}
                    ).eq('dev_userinterface_id', interface_id).eq('team_id', team_id).execute()
                except Exception as rename_err:
                    print(f"[@db:userinterface_db:update_userinterface] Warning: prod rename propagation failed: {rename_err}")

            return {
                'id': ui['id'],
                'name': ui['name'],
                'models': ui.get('models', []),
                'min_version': ui.get('min_version', ''),
                'max_version': ui.get('max_version', ''),
                'team_id': ui['team_id'],
                'created_at': ui['created_at'],
                'updated_at': ui['updated_at']
            }
        return None
    except Exception as e:
        print(f"[@db:userinterface_db:update_userinterface] Error: {e}")
        return None

def delete_userinterface(interface_id: str, team_id: str) -> bool:
    """Delete a user interface."""
    supabase = get_supabase()
    try:
        result = supabase.table('userinterfaces').delete().eq('id', interface_id).eq('team_id', team_id).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[@db:userinterface_db:delete_userinterface] Error: {e}")
        return False

def check_userinterface_name_exists(name: str, team_id: str, exclude_id: str = None) -> bool:
    """Check if a user interface name already exists for a team.

    Scoped to mode='dev': a prod snapshot deliberately shares its dev source's
    name and must not block creates/renames.
    """
    supabase = get_supabase()
    try:
        query = supabase.table('userinterfaces').select('id').eq('name', name).eq('team_id', team_id).eq('mode', 'dev')

        if exclude_id:
            query = query.neq('id', exclude_id)

        result = query.execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[@db:userinterface_db:check_userinterface_name] Error: {e}")
        return False

# ============================================================================
# USERINTERFACE_VARIANTS — registry of named variants per userinterface.
#
# Each variant row carries its own per-row overrides in node_overrides /
# edge_overrides JSONB columns (keyed by node_id / edge_id). Base
# navigation_nodes / navigation_edges rows stay clean. The boolean column
# `hidden_in_base` on those tables marks variant-only rows.
# See docs/agent/ENHANCE_VARIANT.md.
# ============================================================================

def _row_to_variant(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw userinterface_variants row into the API-facing shape."""
    return {
        'id': row.get('id'),  # stable, rename-safe identity (name is a display label)
        'name': row['name'],
        'description': row.get('description', '') or '',
        'node_overrides': row.get('node_overrides') or {},
        'edge_overrides': row.get('edge_overrides') or {},
        'created_at': row.get('created_at'),
        'updated_at': row.get('updated_at'),
    }


def list_variants(team_id: str, userinterface_id: str) -> List[Dict]:
    """List every registered variant for a userinterface.

    Returns a list of dicts {name, description, node_overrides, edge_overrides,
    created_at, updated_at}. Empty list on error or when none exist.
    """
    supabase = get_supabase()
    if supabase is None:
        return []
    try:
        result = supabase.table('userinterface_variants').select(
            'id, name, description, node_overrides, edge_overrides, created_at, updated_at'
        ).eq('team_id', team_id).eq('userinterface_id', userinterface_id).order('name').execute()

        return [_row_to_variant(row) for row in (result.data or [])]
    except Exception as e:
        print(f"[@db:userinterface_db:list_variants] Error: {e}")
        return []


def list_variants_for_team(team_id: str) -> Dict[str, List[Dict]]:
    """Every registered variant for a team, grouped by userinterface_id.

    Batched counterpart of list_variants. The Interface page needs variants for
    every row; asking per interface meant one DB round trip per row (~200ms each
    from a remote host), which is the bulk of that page's load time.

    Returns {userinterface_id: [variant, ...]} using the same per-variant shape
    as list_variants, so callers/caches can be shared. Empty dict on error.
    """
    supabase = get_supabase()
    if supabase is None:
        return {}
    try:
        result = supabase.table('userinterface_variants').select(
            'id, userinterface_id, name, description, node_overrides, edge_overrides, created_at, updated_at'
        ).eq('team_id', team_id).order('name').execute()

        grouped: Dict[str, List[Dict]] = {}
        for row in (result.data or []):
            grouped.setdefault(row['userinterface_id'], []).append(_row_to_variant(row))
        return grouped
    except Exception as e:
        print(f"[@db:userinterface_db:list_variants_for_team] Error: {e}")
        return {}


def get_variant(team_id: str, userinterface_id: str, name: str) -> Optional[Dict[str, Any]]:
    """Fetch a single variant row including its node_overrides and edge_overrides.

    Returns None when the variant doesn't exist (or on transient error). Used by
    the host's tree manager when a script run names a variant.
    """
    supabase = get_supabase()
    if supabase is None:
        return None
    try:
        result = supabase.table('userinterface_variants').select(
            'id, name, description, node_overrides, edge_overrides, created_at, updated_at'
        ).eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', name).execute()
        if not result.data:
            return None
        return _row_to_variant(result.data[0])
    except Exception as e:
        print(f"[@db:userinterface_db:get_variant] Error: {e}")
        return None


def get_variant_by_id(team_id: str, variant_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single variant row by its stable id (rename-safe).

    Mirror of get_variant() but keyed on the UUID instead of (userinterface_id,
    name), so a caller holding a variant id resolves it regardless of any later
    rename. The name on the returned row is a display label.
    """
    supabase = get_supabase()
    if supabase is None:
        return None
    try:
        result = supabase.table('userinterface_variants').select(
            'id, name, description, node_overrides, edge_overrides, created_at, updated_at'
        ).eq('team_id', team_id).eq('id', variant_id).execute()
        if not result.data:
            return None
        return _row_to_variant(result.data[0])
    except Exception as e:
        print(f"[@db:userinterface_db:get_variant_by_id] Error: {e}")
        return None


def list_variant_names(team_id: str, userinterface_name: str) -> List[str]:
    """List variant names for a userinterface keyed by its human name.

    Used at /server/script/execute time to validate the requested --variant
    before the script is spawned. Empty list = no registered variants OR
    userinterface not found.
    """
    supabase = get_supabase()
    if supabase is None:
        return []
    try:
        ui = get_userinterface_by_name(userinterface_name, team_id)
        if not ui:
            return []
        rows = list_variants(team_id, ui['id'])
        return [r['name'] for r in rows]
    except Exception as e:
        print(f"[@db:userinterface_db:list_variant_names] Error: {e}")
        return []


def add_variant(
    team_id: str,
    userinterface_id: str,
    name: str,
    description: str = '',
    source_variant: Optional[str] = None,
) -> Dict:
    """Insert a new variant row.

    Returns {'success': bool, 'variant'?: dict, 'error'?: str, 'conflict'?: bool,
             'hidden_rows'?: {nodes,edges}, 'cloned_rows'?: {nodes,edges}}.

    Behaviour:
      - source_variant is None  → Base-derived. ADDITIVE model: the new variant
        starts with EMPTY override maps. Variant-only (`hidden_in_base`) rows are
        off by default — a variant only sees them if it explicitly enables them —
        so no `{disabled: true}` fan-out is written. (Returns 'hidden_rows':
        {0,0}.) This is what keeps a fresh variant composable: a leftover
        `{disabled: true}` on another variant's row would hard-veto it in a
        composition. See docs/agent/navigation/VARIANT.md "Composition".
      - source_variant is a str → must reference an existing registered variant.
        Deep-copies the source row's node_overrides / edge_overrides into the
        new variant (returns 'cloned_rows' counts — number of override entries
        copied per kind).
    """
    supabase = get_supabase()
    if supabase is None:
        return {'success': False, 'error': 'Supabase client not available'}

    # Validate source_variant (if requested) BEFORE creating the new row.
    source_overrides_node: Dict[str, Any] = {}
    source_overrides_edge: Dict[str, Any] = {}
    if source_variant is not None:
        if not isinstance(source_variant, str) or not source_variant:
            return {'success': False, 'error': 'source_variant must be a non-empty string or null'}
        try:
            available_rows = supabase.table('userinterface_variants').select(
                'name, node_overrides, edge_overrides'
            ).eq('team_id', team_id).eq('userinterface_id', userinterface_id).execute()
            available = {r['name']: r for r in (available_rows.data or [])}
            if source_variant not in available:
                return {
                    'success': False,
                    'error': f"unknown source_variant '{source_variant}'",
                    'available': list(available.keys()),
                }
            src_row = available[source_variant]
            source_overrides_node = copy.deepcopy(src_row.get('node_overrides') or {})
            source_overrides_edge = copy.deepcopy(src_row.get('edge_overrides') or {})
        except Exception as e:
            print(f"[@db:userinterface_db:add_variant] source validation error: {e}")
            return {'success': False, 'error': str(e)}

    try:
        existing = supabase.table('userinterface_variants').select('name')\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', name).execute()
        if existing.data:
            return {'success': False, 'error': f"variant '{name}' already exists", 'conflict': True}

        # Base-derived variant starts EMPTY (additive model — see docstring).
        # Variant-only rows stay hidden by default without any cross-disable
        # fan-out, so the new variant composes cleanly with others.
        node_overrides_payload = source_overrides_node
        edge_overrides_payload = source_overrides_edge
        hidden_counts = {'nodes': 0, 'edges': 0}

        now = datetime.now(timezone.utc).isoformat()
        payload = {
            'team_id': team_id,
            'userinterface_id': userinterface_id,
            'name': name,
            'description': description or '',
            'node_overrides': node_overrides_payload,
            'edge_overrides': edge_overrides_payload,
            'created_at': now,
            'updated_at': now,
        }
        result = supabase.table('userinterface_variants').insert(payload).execute()
        if not result.data:
            return {'success': False, 'error': 'Insert returned no data'}
        variant = _row_to_variant(result.data[0])

        response: Dict[str, Any] = {'success': True, 'variant': variant}
        if source_variant is None:
            response['hidden_rows'] = hidden_counts
        else:
            response['cloned_rows'] = {
                'nodes': len(source_overrides_node),
                'edges': len(source_overrides_edge),
            }
        return response
    except Exception as e:
        msg = str(e)
        # Surface duplicate-PK as conflict
        if 'duplicate key' in msg.lower() or '23505' in msg:
            return {'success': False, 'error': f"variant '{name}' already exists", 'conflict': True}
        # Surface CHECK violations (name regex) as 400
        if 'check constraint' in msg.lower() or '23514' in msg:
            return {'success': False, 'error': f"invalid variant name '{name}': {msg}"}
        print(f"[@db:userinterface_db:add_variant] Error: {e}")
        return {'success': False, 'error': msg}


def update_variant(
    team_id: str,
    userinterface_id: str,
    name: str,
    *,
    description: Optional[str] = None,
    node_overrides: Optional[Dict[str, Any]] = None,
    edge_overrides: Optional[Dict[str, Any]] = None,
) -> Dict:
    """Partial update of a variant row. Pass any subset of:
       - description           (str)            → text column
       - node_overrides        (Dict[node_id, override])  → JSONB column
       - edge_overrides        (Dict[edge_id, override])  → JSONB column
    Fields left as None are not touched. Whole-map replacement on the JSONB
    columns — the caller sends the post-merge map (this function does not
    merge keys server-side). Returns {'success', 'variant'?, 'error'?}.
    """
    supabase = get_supabase()
    if supabase is None:
        return {'success': False, 'error': 'Supabase client not available'}

    if description is None and node_overrides is None and edge_overrides is None:
        existing = get_variant(team_id, userinterface_id, name)
        if existing is None:
            return {'success': False, 'error': f"variant '{name}' not found"}
        return {'success': True, 'variant': existing}

    update_payload: Dict[str, Any] = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    if description is not None:
        update_payload['description'] = description or ''
    if node_overrides is not None:
        if not isinstance(node_overrides, dict):
            return {'success': False, 'error': 'node_overrides must be an object'}
        update_payload['node_overrides'] = node_overrides
    if edge_overrides is not None:
        if not isinstance(edge_overrides, dict):
            return {'success': False, 'error': 'edge_overrides must be an object'}
        update_payload['edge_overrides'] = edge_overrides

    try:
        result = supabase.table('userinterface_variants').update(update_payload)\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', name).execute()
        if not result.data:
            return {'success': False, 'error': f"variant '{name}' not found"}
        return {'success': True, 'variant': _row_to_variant(result.data[0])}
    except Exception as e:
        print(f"[@db:userinterface_db:update_variant] Error: {e}")
        return {'success': False, 'error': str(e)}


def delete_variant(team_id: str, userinterface_id: str, name: str) -> Dict:
    """Delete a variant: drop the registry row. Per-row cascade is automatic
    because every override lives ON the variant row.

    Returns {'success', 'rows_changed': {'nodes': N, 'edges': M}, 'error'?}
    where N/M are the number of override entries that disappeared with the
    row (purely informational — used by the FE to show a confirmation toast).
    """
    supabase = get_supabase()
    if supabase is None:
        return {'success': False, 'error': 'Supabase client not available'}

    try:
        existing = supabase.table('userinterface_variants').select(
            'name, node_overrides, edge_overrides'
        ).eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', name).execute()
        if not existing.data:
            return {'success': False, 'error': f"variant '{name}' not found", 'not_found': True}
        row = existing.data[0]
        node_count = len((row.get('node_overrides') or {}))
        edge_count = len((row.get('edge_overrides') or {}))
    except Exception as e:
        return {'success': False, 'error': str(e)}

    try:
        supabase.table('userinterface_variants').delete()\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', name).execute()
        return {
            'success': True,
            'rows_changed': {'nodes': node_count, 'edges': edge_count},
        }
    except Exception as e:
        print(f"[@db:userinterface_db:delete_variant] Error: {e}")
        return {'success': False, 'error': str(e)}


def rename_variant(team_id: str, userinterface_id: str, old_name: str, new_name: str) -> Dict:
    """Rename a variant: single-row UPDATE on userinterface_variants.

    Returns {'success', 'rows_changed': {'nodes': N, 'edges': M}, 'error'?}
    where N/M are counts of override entries on the renamed row (informational).
    """
    if old_name == new_name:
        return {'success': True, 'rows_changed': {'nodes': 0, 'edges': 0}}

    supabase = get_supabase()
    if supabase is None:
        return {'success': False, 'error': 'Supabase client not available'}

    try:
        # Source must exist
        src = supabase.table('userinterface_variants').select(
            'description, node_overrides, edge_overrides, created_at'
        ).eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', old_name).execute()
        if not src.data:
            return {'success': False, 'error': f"variant '{old_name}' not found", 'not_found': True}

        # Target must NOT exist
        dst = supabase.table('userinterface_variants').select('name')\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', new_name).execute()
        if dst.data:
            return {'success': False, 'error': f"variant '{new_name}' already exists", 'conflict': True}

        src_row = src.data[0]
        node_count = len((src_row.get('node_overrides') or {}))
        edge_count = len((src_row.get('edge_overrides') or {}))

        now = datetime.now(timezone.utc).isoformat()
        # Insert new row carrying the same JSONB; then drop old row.
        supabase.table('userinterface_variants').insert({
            'team_id': team_id,
            'userinterface_id': userinterface_id,
            'name': new_name,
            'description': src_row.get('description') or '',
            'node_overrides': src_row.get('node_overrides') or {},
            'edge_overrides': src_row.get('edge_overrides') or {},
            'created_at': src_row.get('created_at') or now,
            'updated_at': now,
        }).execute()
        supabase.table('userinterface_variants').delete()\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
            .eq('name', old_name).execute()

        return {'success': True, 'rows_changed': {'nodes': node_count, 'edges': edge_count}}
    except Exception as e:
        print(f"[@db:userinterface_db:rename_variant] Error: {e}")
        return {'success': False, 'error': str(e)}


def sweep_orphan_hidden_rows(team_id: str, userinterface_id: str) -> Dict:
    """Delete ORPHAN hidden rows: `hidden_in_base=true` nodes/edges that no
    variant of the UI shows — invisible in Base (flag) AND on every variant
    (no enabler), yet still occupying their node pair and blocking draws.

    Visibility of a hidden row r on variant v (mirrors composeOverrides /
    _compose_overrides):
      - v's entry ENABLES it: not {disabled:true}, and {enabled:true} or a
        non-empty content override (verifications / action_sets), OR
      - legacy fall-through: SOME variant disables r (old cross-disable
        convention) and v has NO entry (absence marks the legacy owner).
    A row visible on no variant is unreachable in every scope → delete the
    row and strip its id from every variant's override maps (stale
    {disabled:true} keys would otherwise linger).

    Run automatically after a variant delete (the cascade the registry-row
    delete alone doesn't provide) and on demand as a repair. Deleting rows
    that render nowhere is always safe for what users can see.

    Returns {'success', 'deleted': {'nodes': N, 'edges': M}, 'error'?}.
    """
    supabase = get_supabase()
    if supabase is None:
        return {'success': False, 'error': 'Supabase client not available'}

    try:
        trees = supabase.table('navigation_trees').select('id')\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id).execute()
        tree_ids = [t['id'] for t in (trees.data or [])]
        if not tree_ids:
            return {'success': True, 'deleted': {'nodes': 0, 'edges': 0}}

        hidden_nodes = supabase.table('navigation_nodes').select('node_id')\
            .in_('tree_id', tree_ids).eq('hidden_in_base', True).execute()
        hidden_edges = supabase.table('navigation_edges').select('edge_id')\
            .in_('tree_id', tree_ids).eq('hidden_in_base', True).execute()
        hidden_node_ids = [r['node_id'] for r in (hidden_nodes.data or [])]
        hidden_edge_ids = [r['edge_id'] for r in (hidden_edges.data or [])]
        if not hidden_node_ids and not hidden_edge_ids:
            return {'success': True, 'deleted': {'nodes': 0, 'edges': 0}}

        variants_res = supabase.table('userinterface_variants')\
            .select('name, node_overrides, edge_overrides')\
            .eq('team_id', team_id).eq('userinterface_id', userinterface_id).execute()
        variants = variants_res.data or []

        def find_orphans(hidden_ids, overrides_key, content_key):
            orphans = []
            for rid in hidden_ids:
                cross_disabled = any(
                    isinstance((v.get(overrides_key) or {}).get(rid), dict)
                    and (v.get(overrides_key) or {}).get(rid, {}).get('disabled')
                    for v in variants
                )
                visible = False
                for v in variants:
                    entry = (v.get(overrides_key) or {}).get(rid)
                    if not isinstance(entry, dict):
                        entry = None
                    if entry is not None and entry.get('disabled'):
                        continue
                    content = entry.get(content_key) if entry else None
                    enables = entry is not None and (
                        entry.get('enabled') is True
                        or (isinstance(content, list) and len(content) > 0)
                    )
                    if enables:
                        visible = True
                        break
                    # entry absent or a no-op → legacy fall-through owner
                    if cross_disabled:
                        visible = True
                        break
                if not visible:
                    orphans.append(rid)
            return orphans

        orphan_nodes = find_orphans(hidden_node_ids, 'node_overrides', 'verifications')
        orphan_edges = find_orphans(hidden_edge_ids, 'edge_overrides', 'action_sets')
        if not orphan_nodes and not orphan_edges:
            return {'success': True, 'deleted': {'nodes': 0, 'edges': 0}}

        # Single statement per table — every navigation_* write fires a full
        # MV refresh, so batching matters.
        if orphan_edges:
            supabase.table('navigation_edges').delete()\
                .in_('tree_id', tree_ids).in_('edge_id', orphan_edges).execute()
        if orphan_nodes:
            supabase.table('navigation_nodes').delete()\
                .in_('tree_id', tree_ids).in_('node_id', orphan_nodes).execute()

        # Strip the deleted ids from every variant's maps.
        orphan_node_set = set(orphan_nodes)
        orphan_edge_set = set(orphan_edges)
        now = datetime.now(timezone.utc).isoformat()
        for v in variants:
            node_map = v.get('node_overrides') or {}
            edge_map = v.get('edge_overrides') or {}
            new_node_map = {k: val for k, val in node_map.items() if k not in orphan_node_set}
            new_edge_map = {k: val for k, val in edge_map.items() if k not in orphan_edge_set}
            if len(new_node_map) != len(node_map) or len(new_edge_map) != len(edge_map):
                supabase.table('userinterface_variants').update({
                    'node_overrides': new_node_map,
                    'edge_overrides': new_edge_map,
                    'updated_at': now,
                }).eq('team_id', team_id).eq('userinterface_id', userinterface_id)\
                    .eq('name', v['name']).execute()

        print(
            f"[@db:userinterface_db:sweep_orphan_hidden_rows] Removed "
            f"{len(orphan_nodes)} orphan node(s) + {len(orphan_edges)} orphan edge(s) "
            f"for userinterface {userinterface_id}"
        )
        return {'success': True, 'deleted': {'nodes': len(orphan_nodes), 'edges': len(orphan_edges)}}
    except Exception as e:
        print(f"[@db:userinterface_db:sweep_orphan_hidden_rows] Error: {e}")
        return {'success': False, 'error': str(e)}


def _duplicate_references_for_ui(source_id: str, source_name: str, new_id: str, new_name: str, team_id: str) -> Dict:
    """Copy a source UI's *local* verification references onto a duplicated UI.

    References + their R2/MinIO objects are keyed by the stable userinterface id
    (`reference-images/<ui_id>/…`). A duplicated UI gets a brand-new id, so without
    this its copied nodes reference names that resolve to an id with no rows/objects.
    For each source row we insert a fresh row keyed to `new_id` and server-side
    `copy_file` its backing object into the new id folder, so the copy is fully
    independent (editing/deleting either UI never touches the other).

    Scope notes:
    - `shared=True` rows are skipped — they already resolve for the copy via model
      compatibility (the duplicate inherits `models[]`), and the shared-uniqueness
      index (team_id,name,reference_type) would reject a duplicate anyway.
    - Source rows are matched id-first with a name fallback for legacy/orphan rows
      whose `userinterface_id` was never backfilled.
    - Best-effort per object: if a copy fails, the new row falls back to pointing at
      the source object (shared) rather than a broken path, so it still renders.
    """
    from concurrent.futures import ThreadPoolExecutor
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
    from shared.src.lib.database.verifications_references_db import _invalidate_references_cache

    supabase = get_supabase()
    timestamp = datetime.now(timezone.utc).isoformat()

    rows = (
        supabase.table('verifications_references')
        .select('*')
        .eq('team_id', team_id)
        .eq('shared', False)
        .or_(f'userinterface_id.eq.{source_id},'
             f'and(userinterface_id.is.null,userinterface_name.eq.{source_name})')
        .execute()
        .data
    ) or []

    if not rows:
        print(f"[@db:userinterface_db:_duplicate_references_for_ui] No local references on source {source_name}")
        return {'references_count': 0, 'objects_copied': 0, 'objects_failed': 0}

    def _swap_folder(r2_path: Optional[str]) -> Optional[str]:
        # reference-images/<old>/<rest…>  ->  reference-images/<new_id>/<rest…>
        if not r2_path:
            return None
        parts = r2_path.split('/')
        if len(parts) < 3 or parts[0] not in ('reference-images', 'text-references'):
            return None
        parts[1] = new_id
        return '/'.join(parts)

    cf = get_cloudflare_utils()
    objects_copied = objects_failed = 0

    # 1. Copy every backing image object in PARALLEL. Each is an independent
    #    server-side S3 CopyObject (one WAN round trip); done sequentially they
    #    dominated duplication time. Results keyed by the source row's index.
    image_tasks = []  # (row_index, new_path)
    for i, r in enumerate(rows):
        if r.get('reference_type') == 'reference_image' and r.get('r2_path'):
            np = _swap_folder(r.get('r2_path'))
            if np:
                image_tasks.append((i, np))

    copy_results = {}  # row_index -> (ok: bool, new_path, new_url)
    if image_tasks:
        def _copy(task):
            idx, np = task
            res = cf.copy_file(rows[idx]['r2_path'], np)
            if res.get('success'):
                return idx, True, np, (res.get('url') or cf.get_public_url(np))
            return idx, False, None, None
        with ThreadPoolExecutor(max_workers=min(10, len(image_tasks))) as ex:
            for idx, ok, np, url in ex.map(_copy, image_tasks):
                copy_results[idx] = (ok, np, url)

    # 2. Build every new row, then INSERT them all in one round trip (was one
    #    insert per reference — N serial WAN hops).
    insert_rows = []
    for i, r in enumerate(rows):
        rtype = r.get('reference_type')
        src_path = r.get('r2_path')
        new_path = _swap_folder(src_path)
        new_url = r.get('r2_url')

        if rtype == 'reference_image' and src_path and new_path:
            ok, copied_path, copied_url = copy_results.get(i, (False, None, None))
            if ok:
                new_path, new_url = copied_path, copied_url
                objects_copied += 1
            else:
                # Degrade to sharing the source object rather than a broken path.
                print(f"[@db:userinterface_db:_duplicate_references_for_ui] copy failed "
                      f"{src_path} -> {new_path} — sharing source object")
                new_path, new_url = src_path, r.get('r2_url')
                objects_failed += 1
        else:
            # Text refs (text lives in `area`, no backing object) and rows with no
            # recognizable path: just relabel the folder when we can.
            new_path = new_path or src_path

        insert_rows.append({
            'name': r['name'],
            'userinterface_name': new_name,
            'userinterface_id': new_id,
            'device_model': new_name,
            'reference_type': rtype,
            'team_id': team_id,
            'r2_path': new_path,
            'r2_url': new_url,
            'area': r.get('area'),
            'shared': False,
            'created_at': timestamp,
            'updated_at': timestamp,
        })

    copied = len(insert_rows)
    if insert_rows:
        supabase.table('verifications_references').insert(insert_rows).execute()

    _invalidate_references_cache()
    print(f"[@db:userinterface_db:_duplicate_references_for_ui] Duplicated {copied} references "
          f"({objects_copied} objects copied, {objects_failed} shared on copy failure)")
    return {'references_count': copied, 'objects_copied': objects_copied, 'objects_failed': objects_failed}


def _drop_default_navigation_trees(userinterface_id: str, team_id: str) -> int:
    """Delete the root tree(s) the after_userinterface_insert trigger auto-created.

    The trigger seeds every new UI with an empty `<name>_navigation` root tree whose
    entry-node/home are system-protected (and entry-node read-only). A BEFORE DELETE
    trigger blocks deleting protected nodes — which a tree delete would cascade into —
    so we first clear `is_read_only`/`is_system_protected` on the trees' nodes/edges
    (a flags-only update doesn't touch any read-only-guarded field), then delete the
    trees. Called during duplication BEFORE the real hierarchy is copied, so the only
    trees present are the trigger's. Returns the number of trees removed.
    """
    supabase = get_supabase()
    trees = (supabase.table('navigation_trees')
             .select('id')
             .eq('userinterface_id', userinterface_id)
             .eq('team_id', team_id)
             .execute().data) or []
    for t in trees:
        tid = t['id']
        supabase.table('navigation_nodes').update(
            {'is_read_only': False, 'is_system_protected': False}).eq('tree_id', tid).execute()
        supabase.table('navigation_edges').update(
            {'is_system_protected': False}).eq('tree_id', tid).execute()
        supabase.table('navigation_trees').delete().eq('id', tid).execute()
    if trees:
        print(f"[@db:userinterface_db:_drop_default_navigation_trees] Removed {len(trees)} "
              f"trigger-created default tree(s) for UI {userinterface_id}")
    return len(trees)


def duplicate_userinterface_with_tree(source_id: str, new_name: str, team_id: str, creator_id: str = None) -> Optional[Dict]:
    """Duplicate a user interface and its entire navigation tree."""
    try:
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface, duplicate_tree

        # Get source and create new UI
        source_ui = get_userinterface(source_id, team_id)
        if not source_ui:
            return None

        new_ui = create_userinterface({
            'name': new_name,
            'models': source_ui.get('models', []),
            'min_version': source_ui.get('min_version', ''),
            'max_version': source_ui.get('max_version', '')
        }, team_id, creator_id)

        if not new_ui:
            return None

        # The `after_userinterface_insert` DB trigger auto-creates an empty default
        # root tree (`<name>_navigation` with protected entry-node + home) for every
        # new UI. For a duplicate we want ONLY the copied hierarchy, so drop that
        # default tree now — otherwise the UI ends up with TWO is_root_tree trees and
        # get_root_tree_for_interface (earliest created) returns the empty one, so the
        # duplicate opens blank ("nodes not the same"). Its entry-node/home are
        # system-protected (a BEFORE DELETE trigger blocks the cascade), so clear the
        # protection flags first. Non-fatal: log and continue on failure.
        try:
            _drop_default_navigation_trees(new_ui['id'], team_id)
        except Exception as tree_err:
            print(f"[@db:userinterface_db:duplicate_userinterface_with_tree] default-tree cleanup failed: {tree_err}")

        # Carry the source's verification references onto the new UI (id-keyed rows
        # + copied R2 objects). Non-fatal: a duplicated tree with missing references
        # is still usable, so a failure here only logs and reports zero refs.
        try:
            ref_stats = _duplicate_references_for_ui(
                source_id, source_ui.get('name'), new_ui['id'], new_ui['name'], team_id)
        except Exception as ref_err:
            print(f"[@db:userinterface_db:duplicate_userinterface_with_tree] reference copy failed: {ref_err}")
            ref_stats = {'references_count': 0, 'objects_copied': 0, 'objects_failed': 0, 'error': str(ref_err)}

        # Get and duplicate tree hierarchy (including all subtrees)
        source_tree = get_root_tree_for_interface(source_id, team_id)
        if not source_tree:
            return {**new_ui, 'duplication_stats': {'tree_duplicated': False, 'trees_count': 0, 'nodes_count': 0, 'edges_count': 0, 'references_count': ref_stats.get('references_count', 0)}}

        dup_result = duplicate_tree(source_tree['id'], new_ui['id'], new_ui['name'], team_id)

        return {
            **new_ui,
            'duplication_stats': {
                'tree_duplicated': dup_result['success'],
                'tree_id': dup_result.get('tree_id'),
                'trees_count': dup_result.get('trees_count', 0),
                'nodes_count': dup_result.get('nodes_count', 0),
                'edges_count': dup_result.get('edges_count', 0),
                'references_count': ref_stats.get('references_count', 0),
                'error': dup_result.get('error')
            } if dup_result['success'] else {
                'tree_duplicated': False,
                'trees_count': 0,
                'nodes_count': 0,
                'edges_count': 0,
                'references_count': ref_stats.get('references_count', 0),
                'error': dup_result.get('error')
            }
        }

    except Exception as e:
        print(f"[@db:userinterface_db:duplicate_userinterface_with_tree] Error: {e}")
        return None
