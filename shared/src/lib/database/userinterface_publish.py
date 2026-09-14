"""
UserInterface Publish — dev -> prod lifecycle.

A userinterface's prod version is a full snapshot of its dev graph (trees,
nodes, edges, variants, references) living under a SEPARATE userinterface row
(mode='prod', dev_userinterface_id -> dev row, same name).

Publish semantics:
- First publish: deep copy via the existing duplicate machinery
  (duplicate_tree_hierarchy + _duplicate_references_for_ui), with
  published_from_tree_id stamped on every prod tree at insert time.
- Republish: sync dev content INTO the existing prod trees IN PLACE. Prod
  keeps its userinterface_id and tree ids, and nodes/edges keep their semantic
  TEXT ids — so everything keyed by (tree_id, node_id/edge_id): edge_metrics,
  node_metrics, KPI trends, execution_results, continues across publishes.
  Modeled statement-for-statement on _restore_tree_from_history_impl (the
  proven in-place writer): every statement on the navigation tables fires a
  full mv_full_navigation_trees refresh, so all writes are batched — chunk
  sizes are the restore-proven ceilings.

root_node_id on prod trees is deliberately left NULL (same as the duplicate
path): it points at node surrogate ids, and nothing in the executor paths
resolves through it (resolution is is_root_tree + node_id text).
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    return get_supabase_client()


_publish_lock = threading.Lock()
_publishes_in_progress = set()


def publish_userinterface(dev_ui_id: str, team_id: str, published_by: Optional[str] = None) -> Dict:
    """Publish a dev userinterface to prod (create or update its prod snapshot).

    Returns {success, prod_userinterface_id, prod_root_tree_id, version,
    first_publish, counts:{trees,nodes,edges,variants,references,
    trees_created,trees_deleted}} or {success: False, error}.
    """
    with _publish_lock:
        if dev_ui_id in _publishes_in_progress:
            return {'success': False, 'error': 'A publish is already in progress for this userinterface'}
        _publishes_in_progress.add(dev_ui_id)
    try:
        return _publish_impl(dev_ui_id, team_id, published_by)
    finally:
        with _publish_lock:
            _publishes_in_progress.discard(dev_ui_id)


def _publish_impl(dev_ui_id: str, team_id: str, published_by: Optional[str]) -> Dict:
    from shared.src.lib.database.userinterface_db import get_userinterface

    try:
        dev_ui = get_userinterface(dev_ui_id, team_id)
        if not dev_ui:
            return {'success': False, 'error': 'Userinterface not found'}
        if dev_ui.get('mode', 'dev') != 'dev':
            return {'success': False, 'error': 'Only dev userinterfaces can be published'}

        supabase = get_supabase()
        prod_rows = supabase.table('userinterfaces').select('*')\
            .eq('dev_userinterface_id', dev_ui_id).eq('mode', 'prod')\
            .eq('team_id', team_id).limit(1).execute().data

        if prod_rows:
            return _republish(dev_ui, prod_rows[0], team_id, published_by)
        return _first_publish(dev_ui, team_id, published_by)
    except Exception as e:
        print(f"[@db:userinterface_publish:publish] Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def _first_publish(dev_ui: Dict, team_id: str, published_by: Optional[str]) -> Dict:
    from shared.src.lib.database.userinterface_db import (
        _drop_default_navigation_trees,
        _duplicate_references_for_ui,
    )
    from shared.src.lib.database.navigation_trees_db import (
        duplicate_tree_hierarchy,
        get_root_tree_for_interface,
    )

    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    # 1) Prod UI row: same name as dev (mode disambiguates), linked + versioned.
    #    Inserted directly (create_userinterface doesn't know the mode columns).
    prod_id = str(uuid4())
    supabase.table('userinterfaces').insert({
        'id': prod_id,
        'name': dev_ui['name'],
        'models': dev_ui.get('models', []),
        'min_version': dev_ui.get('min_version', ''),
        'max_version': dev_ui.get('max_version', ''),
        'team_id': team_id,
        'mode': 'prod',
        'dev_userinterface_id': dev_ui['id'],
        'published_at': now,
        'published_version': 1,
        'created_at': now,
        'updated_at': now,
    }).execute()

    # 2) Kill the after_userinterface_insert trigger's default `<name>_navigation`
    #    tree — the prod UI must contain ONLY the published hierarchy.
    _drop_default_navigation_trees(prod_id, team_id)

    # 3) References: rows + R2 objects copied into reference-images/{prod_id}/.
    #    Same name is fine — references are id-keyed (rename-stable).
    try:
        ref_stats = _duplicate_references_for_ui(
            dev_ui['id'], dev_ui['name'], prod_id, dev_ui['name'], team_id)
    except Exception as ref_err:
        print(f"[@db:userinterface_publish:_first_publish] reference copy failed: {ref_err}")
        ref_stats = {'references_count': 0}

    # 4) Trees: deep copy with published_from_tree_id stamped at insert time.
    dev_root = get_root_tree_for_interface(dev_ui['id'], team_id)
    if not dev_root:
        # An empty dev UI publishes to an empty prod UI — valid, if unusual.
        tree_result = {'success': True, 'tree_id': None, 'trees_count': 0, 'nodes_count': 0, 'edges_count': 0}
    else:
        tree_result = duplicate_tree_hierarchy(
            dev_root['id'], prod_id, dev_ui['name'], team_id, record_source_ids=True)
        if not tree_result.get('success'):
            return {'success': False, 'error': f"Tree copy failed: {tree_result.get('error')}"}

    # 5) Variants: override keys are stable node_id/edge_id texts, so rows copy verbatim.
    variants_count = _sync_variants(dev_ui['id'], prod_id, team_id)

    counts = {
        'trees': tree_result.get('trees_count', 0),
        'nodes': tree_result.get('nodes_count', 0),
        'edges': tree_result.get('edges_count', 0),
        'variants': variants_count,
        'references': ref_stats.get('references_count', 0),
        'trees_created': tree_result.get('trees_count', 0),
        'trees_deleted': 0,
    }
    _record_publish(team_id, dev_ui['id'], prod_id, 1, published_by, counts)

    print(f"[@db:userinterface_publish:_first_publish] {dev_ui['name']}: prod v1 created "
          f"({counts['trees']} trees, {counts['nodes']} nodes, {counts['edges']} edges, "
          f"{counts['variants']} variants, {counts['references']} references)")
    return {
        'success': True,
        'prod_userinterface_id': prod_id,
        'prod_root_tree_id': tree_result.get('tree_id'),
        'version': 1,
        'first_publish': True,
        'counts': counts,
    }


def _republish(dev_ui: Dict, prod_ui: Dict, team_id: str, published_by: Optional[str]) -> Dict:
    from shared.src.lib.database.navigation_trees_db import (
        _live_columns,
        _restore_row,
        _save_tree_to_history,
        get_complete_tree_hierarchy,
        get_root_tree_for_interface,
        invalidate_navigation_cache_for_tree,
    )

    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    dev_root = get_root_tree_for_interface(dev_ui['id'], team_id)
    if not dev_root:
        return {'success': False, 'error': 'Dev userinterface has no root tree'}
    prod_root = get_root_tree_for_interface(prod_ui['id'], team_id)
    if not prod_root:
        # Prod row exists but its trees are gone (partial delete?) — degrade to
        # a fresh tree copy under the existing prod row would need first-publish
        # semantics; simplest correct path: treat as error and let the user
        # delete + republish.
        return {'success': False, 'error': 'Prod userinterface has no root tree — delete the prod version and publish again'}

    # 0) Prod's own undo point. Abort on failure: never overwrite a state that
    #    has no snapshot (same rule as restore).
    if not _save_tree_to_history(prod_root['id'], team_id, 'update', published_by):
        return {'success': False, 'error': 'Failed to snapshot current prod state before publish'}

    hierarchy = get_complete_tree_hierarchy(dev_root['id'], team_id)
    if not hierarchy.get('success'):
        return {'success': False, 'error': f"Failed to load dev hierarchy: {hierarchy.get('error')}"}
    dev_trees = sorted(hierarchy['all_trees_data'], key=lambda t: t['tree_info']['tree_depth'])

    prod_trees = supabase.table('navigation_trees')\
        .select('id,published_from_tree_id,tree_depth')\
        .eq('userinterface_id', prod_ui['id']).eq('team_id', team_id)\
        .execute().data or []

    dev_to_prod = {t['published_from_tree_id']: t['id']
                   for t in prod_trees if t.get('published_from_tree_id')}
    dev_ids = {t['tree_id'] for t in dev_trees}

    # 1) Diff trees. New dev subtrees get fresh prod UUIDs — mapping extended
    #    BEFORE row building so parent_tree_id remaps resolve. Prod trees whose
    #    source is gone from dev (or was never stamped) are removals.
    trees_created = 0
    for t in dev_trees:
        if t['tree_id'] not in dev_to_prod:
            dev_to_prod[t['tree_id']] = str(uuid4())
            trees_created += 1
    removed = [t for t in prod_trees
               if not t.get('published_from_tree_id') or t['published_from_tree_id'] not in dev_ids]
    removed_id_set = {t['id'] for t in removed}

    # 2) Build ALL rows up front (restore precedent: batch everything).
    #    MV rows don't carry the protection flags, so live prod flags survive
    #    the upserts — exactly the restore semantics.
    node_cols = _live_columns(supabase, 'navigation_nodes')
    edge_cols = _live_columns(supabase, 'navigation_edges')

    tree_rows_by_depth = {}
    node_rows = []
    edge_rows = []
    for t in dev_trees:
        pid = dev_to_prod[t['tree_id']]
        info = t['tree_info']
        tree_row = t.get('tree') or {}
        depth = info.get('tree_depth', 0)
        tree_rows_by_depth.setdefault(depth, []).append({
            'id': pid,
            'name': info['name'],
            'userinterface_id': prod_ui['id'],
            'is_root_tree': info.get('is_root_tree', False),
            'tree_depth': depth,
            'parent_tree_id': dev_to_prod.get(info.get('parent_tree_id')),
            'parent_node_id': info.get('parent_node_id'),
            'viewport_x': tree_row.get('viewport_x', 0),
            'viewport_y': tree_row.get('viewport_y', 0),
            'viewport_zoom': tree_row.get('viewport_zoom', 1),
            'published_from_tree_id': t['tree_id'],
            'team_id': team_id,
            'updated_at': now,
        })
        for node in t.get('nodes') or []:
            node_rows.append(_restore_row(node, node_cols, pid, team_id, now))
        for edge in t.get('edges') or []:
            edge_rows.append(_restore_row(edge, edge_cols, pid, team_id, now))

    # 3) Wipe surviving prod trees' content — protected / has_subtree /
    #    entry-node/home rows excluded (trigger-guarded or cascade-dangerous),
    #    they're refreshed by the upsert instead. 5 trees per statement.
    surviving = [t['id'] for t in prod_trees if t['id'] not in removed_id_set]
    WIPE_CHUNK = 5
    for i in range(0, len(surviving), WIPE_CHUNK):
        chunk = surviving[i:i + WIPE_CHUNK]
        supabase.table('navigation_edges').delete().eq('team_id', team_id)\
            .in_('tree_id', chunk).eq('is_system_protected', False).execute()
        supabase.table('navigation_nodes').delete().eq('team_id', team_id)\
            .in_('tree_id', chunk).eq('is_system_protected', False)\
            .eq('has_subtree', False)\
            .not_.in_('node_id', ['entry-node', 'home']).execute()

    # 4) Upsert tree rows level by level (parent_tree_id FK ordering): creates
    #    new prod subtrees, refreshes name/parent/viewport on existing ones.
    for depth in sorted(tree_rows_by_depth):
        supabase.table('navigation_trees').upsert(tree_rows_by_depth[depth]).execute()

    # 5) Bulk upsert nodes/edges with their semantic TEXT ids preserved —
    #    edge_metrics/node_metrics (keyed on tree_id + those ids, FK tree-level
    #    only) are untouched.
    CHUNK = 200
    for i in range(0, len(node_rows), CHUNK):
        supabase.table('navigation_nodes').upsert(
            node_rows[i:i + CHUNK], on_conflict='tree_id,node_id').execute()
    for i in range(0, len(edge_rows), CHUNK):
        supabase.table('navigation_edges').upsert(
            edge_rows[i:i + CHUNK], on_conflict='tree_id,edge_id').execute()

    # 6) Leftover sweep: rows that survived the wipe (protected / has_subtree /
    #    entry/home) but no longer exist in dev. Skip protected ones — they
    #    can't be deleted while their tree lives; better a stale system row
    #    than a failed publish. Deleting a has_subtree node cascades its
    #    subtrees — correct: a subtree of a node absent from dev is itself extra.
    sync_node_keys = {(r['tree_id'], r['node_id']) for r in node_rows}
    sync_edge_keys = {(r['tree_id'], r['edge_id']) for r in edge_rows}
    surviving_sorted = sorted(surviving)
    leftover_node_ids = []
    leftover_edge_ids = []
    for i in range(0, len(surviving_sorted), 20):
        chunk = surviving_sorted[i:i + 20]
        live_nodes = supabase.table('navigation_nodes').select('id,tree_id,node_id,is_system_protected')\
            .eq('team_id', team_id).in_('tree_id', chunk).execute()
        leftover_node_ids += [
            n['id'] for n in live_nodes.data
            if (n['tree_id'], n['node_id']) not in sync_node_keys
            and not n.get('is_system_protected') and n['node_id'] not in ('entry-node', 'home')]
        live_edges = supabase.table('navigation_edges').select('id,tree_id,edge_id,is_system_protected')\
            .eq('team_id', team_id).in_('tree_id', chunk).execute()
        leftover_edge_ids += [
            e['id'] for e in live_edges.data
            if (e['tree_id'], e['edge_id']) not in sync_edge_keys and not e.get('is_system_protected')]
    for i in range(0, len(leftover_edge_ids), 25):
        supabase.table('navigation_edges').delete().eq('team_id', team_id)\
            .in_('id', leftover_edge_ids[i:i + 25]).execute()
    for i in range(0, len(leftover_node_ids), 25):
        supabase.table('navigation_nodes').delete().eq('team_id', team_id)\
            .in_('id', leftover_node_ids[i:i + 25]).execute()

    # 7) Delete prod trees removed from dev: deepest-first, small chunks.
    #    Their metrics cascade away — intended: the feature no longer exists.
    removed_ids = [t['id'] for t in sorted(removed, key=lambda t: -(t['tree_depth'] or 0))]
    DELETE_CHUNK = 5
    for i in range(0, len(removed_ids), DELETE_CHUNK):
        supabase.table('navigation_trees').delete().eq('team_id', team_id)\
            .in_('id', removed_ids[i:i + DELETE_CHUNK]).execute()

    # 8) Variants + references + bookkeeping.
    variants_count = _sync_variants(dev_ui['id'], prod_ui['id'], team_id)
    ref_stats = _sync_references(dev_ui, prod_ui, team_id)

    version = (prod_ui.get('published_version') or 0) + 1
    supabase.table('userinterfaces').update({
        'published_at': now,
        'published_version': version,
        'models': dev_ui.get('models', []),
        'min_version': dev_ui.get('min_version', ''),
        'max_version': dev_ui.get('max_version', ''),
        'updated_at': now,
    }).eq('id', prod_ui['id']).eq('team_id', team_id).execute()

    counts = {
        'trees': len(dev_trees),
        'nodes': len(node_rows),
        'edges': len(edge_rows),
        'variants': variants_count,
        'references': ref_stats.get('references_count', 0),
        'trees_created': trees_created,
        'trees_deleted': len(removed_ids),
    }
    _record_publish(team_id, dev_ui['id'], prod_ui['id'], version, published_by, counts)

    # 9) Server-side nav cache for every prod tree (host caches are cleared by
    #    the route's fan-out).
    for pid in dev_to_prod.values():
        invalidate_navigation_cache_for_tree(pid, team_id)

    print(f"[@db:userinterface_publish:_republish] {dev_ui['name']}: prod v{version} synced in place "
          f"({counts['trees']} trees [+{trees_created}/-{len(removed_ids)}], {counts['nodes']} nodes, "
          f"{counts['edges']} edges, {counts['variants']} variants, {counts['references']} references)")
    return {
        'success': True,
        'prod_userinterface_id': prod_ui['id'],
        'prod_root_tree_id': prod_root['id'],
        'version': version,
        'first_publish': False,
        'counts': counts,
    }


def _sync_variants(dev_ui_id: str, prod_ui_id: str, team_id: str) -> int:
    """Mirror the dev variant registry onto the prod UI.

    Override keys are stable node_id/edge_id texts, so rows copy verbatim; one
    upsert on the (team_id, userinterface_id, name) PK + one delete of prod
    variant names no longer present in dev.
    """
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    dev_variants = supabase.table('userinterface_variants').select('*')\
        .eq('team_id', team_id).eq('userinterface_id', dev_ui_id).execute().data or []

    if dev_variants:
        rows = [{
            'team_id': team_id,
            'userinterface_id': prod_ui_id,
            'name': v['name'],
            'description': v.get('description', '') or '',
            'node_overrides': v.get('node_overrides') or {},
            'edge_overrides': v.get('edge_overrides') or {},
            'updated_at': now,
        } for v in dev_variants]
        supabase.table('userinterface_variants').upsert(
            rows, on_conflict='team_id,userinterface_id,name').execute()

    dev_names = [v['name'] for v in dev_variants]
    stale_q = supabase.table('userinterface_variants').delete()\
        .eq('team_id', team_id).eq('userinterface_id', prod_ui_id)
    if dev_names:
        stale_q = stale_q.not_.in_('name', dev_names)
    stale_q.execute()

    return len(dev_variants)


def _sync_references(dev_ui: Dict, prod_ui: Dict, team_id: str) -> Dict:
    """Replace the prod UI's references with a fresh copy of dev's.

    Delete + re-copy (rows are cheap, no FK-dependent metrics). The R2 folder
    reference-images/{prod_id}/ is purged first, best-effort — do NOT touch
    navigation/{name}/, which prod SHARES with dev (same name).
    """
    from shared.src.lib.database.userinterface_db import _duplicate_references_for_ui

    supabase = get_supabase()

    try:
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        get_cloudflare_utils().delete_prefix(f"reference-images/{prod_ui['id']}/")
    except Exception as purge_err:
        print(f"[@db:userinterface_publish:_sync_references] R2 purge failed (stale objects remain): {purge_err}")

    supabase.table('verifications_references').delete()\
        .eq('team_id', team_id).eq('userinterface_id', prod_ui['id']).execute()

    try:
        return _duplicate_references_for_ui(
            dev_ui['id'], dev_ui['name'], prod_ui['id'], prod_ui['name'], team_id)
    except Exception as ref_err:
        print(f"[@db:userinterface_publish:_sync_references] reference copy failed: {ref_err}")
        return {'references_count': 0, 'objects_copied': 0, 'objects_failed': 0, 'error': str(ref_err)}


def _record_publish(team_id: str, dev_id: str, prod_id: str, version: int,
                    published_by: Optional[str], counts: Dict) -> None:
    """Append the publish-log row (prod's own history). Non-fatal on failure —
    the publish itself already happened."""
    try:
        if published_by:
            from uuid import UUID
            try:
                UUID(str(published_by))
            except ValueError:
                published_by = None
        get_supabase().table('userinterface_publishes').insert({
            'team_id': team_id,
            'dev_userinterface_id': dev_id,
            'prod_userinterface_id': prod_id,
            'version': version,
            'published_by': published_by,
            'trees_count': counts.get('trees'),
            'nodes_count': counts.get('nodes'),
            'edges_count': counts.get('edges'),
            'variants_count': counts.get('variants'),
            'references_count': counts.get('references'),
            'trees_created': counts.get('trees_created', 0),
            'trees_deleted': counts.get('trees_deleted', 0),
        }).execute()
    except Exception as e:
        print(f"[@db:userinterface_publish:_record_publish] Warning: publish log insert failed: {e}")


def list_publishes(dev_ui_id: str, team_id: str, limit: int = 20) -> List[Dict]:
    """Publish history for a dev userinterface, newest first."""
    try:
        result = get_supabase().table('userinterface_publishes').select('*')\
            .eq('team_id', team_id).eq('dev_userinterface_id', dev_ui_id)\
            .order('version', desc=True).limit(limit).execute()
        return result.data or []
    except Exception as e:
        print(f"[@db:userinterface_publish:list_publishes] Error: {e}")
        return []
