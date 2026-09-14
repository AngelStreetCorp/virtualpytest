"""
User Interface Management Routes

This module contains the user interface management API endpoints for:
- User interfaces management
- Device compatibility management
"""

import time
import threading
from flask import Blueprint, request, jsonify, send_file

# Import database functions from src/lib/supabase (uses absolute import)
import re
from shared.src.lib.database.userinterface_db import (
    get_all_userinterfaces,
    get_userinterface,
    get_userinterface_by_name,
    create_userinterface,
    delete_userinterface,
    update_userinterface,
    check_userinterface_name_exists,
    duplicate_userinterface_with_tree,
    list_variants,
    list_variants_for_team,
    add_variant,
    update_variant,
    delete_variant,
    rename_variant,
    sweep_orphan_hidden_rows,
)
from shared.src.lib.database.verifications_references_db import (
    update_references_userinterface_name,
)
from shared.src.lib.database.navigation_trees_db import (
    get_root_tree_for_interface,
    get_root_trees_for_interfaces,
    get_tree_ids_with_nodes
)

from shared.src.lib.utils.app_utils import check_supabase
from shared.src.lib.utils.cloudflare_utils import delete_userinterface_storage
from shared.src.lib.config.constants import CACHE_CONFIG

# Create blueprint
server_userinterface_bp = Blueprint('server_userinterface', __name__, url_prefix='/server/userinterface')

# ============================================================================
# IN-MEMORY CACHE FOR COMPATIBLE INTERFACES AND ALL INTERFACES
# ============================================================================
_compatible_cache = {}  # {cache_key: {'data': {...}, 'timestamp': time.time()}}
_interfaces_cache = {}  # {team_id: {'data': [...], 'timestamp': time.time()}}
_cache_lock = threading.Lock()

def _invalidate_interfaces_cache(team_id):
    """Invalidate all user interface caches for a specific team"""
    with _cache_lock:
        # Invalidate the main interfaces cache
        if team_id in _interfaces_cache:
            del _interfaces_cache[team_id]
            print(f"[@cache] INVALIDATE: User interfaces for team {team_id}")

        # Invalidate all compatible interfaces cache entries for this team
        keys_to_delete = [key for key in _compatible_cache.keys() if key.startswith(f"{team_id}:")]
        for key in keys_to_delete:
            del _compatible_cache[key]
            print(f"[@cache] INVALIDATE: Compatible interfaces cache key {key}")


def _propagate_variant_cache_invalidation(interface_id, team_id, variant_names):
    """Tell every host to drop cached navigation graph(s) for the given variants.

    Triggered after a `userinterface_variants` mutation (PUT / DELETE / rename)
    so the next variant-scoped run on each host rebuilds the graph from the
    fresh override data. Without this, hosts could serve a stale graph until
    the in-memory cache's 24h TTL expires.

    Async — runs in a background thread/greenlet so the API response isn't
    blocked on N synchronous host HTTP calls.

    Args:
        interface_id: userinterface_id whose root tree the variants overlay.
        team_id: team scope.
        variant_names: iterable of variant names to invalidate. Empty / None
            entries are skipped (use a separate base-wide clear for those).
    """
    names = [n for n in (variant_names or []) if isinstance(n, str) and n]
    if not names:
        return

    tree = get_root_tree_for_interface(interface_id, team_id)
    if not tree:
        print(f"[@cache] INVALIDATE VARIANT: no root tree for interface {interface_id} — skipping host propagation")
        return
    tree_id = tree['id']

    def _propagate():
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from backend_server.src.lib.utils.route_utils import proxy_to_host_direct

            host_manager = get_host_manager()
            hosts = host_manager.get_all_hosts()
            cleared = []
            for host_info in hosts.values():
                for name in names:
                    try:
                        result, _ = proxy_to_host_direct(
                            host_info,
                            f'/host/navigation/cache/clear/{tree_id}?team_id={team_id}&variant={name}',
                            'POST',
                        )
                        if result and result.get('success'):
                            cleared.append(f"{host_info.get('host_name')}:{name}")
                    except Exception:
                        pass  # Per-host failure is non-fatal
            if cleared:
                print(f"[@cache] INVALIDATE VARIANT: tree {tree_id} — cleared {', '.join(cleared)}")
            else:
                print(f"[@cache] INVALIDATE VARIANT: tree {tree_id} — no hosts had cache to clear ({names})")
        except Exception as e:
            print(f"[@cache] INVALIDATE VARIANT: tree {tree_id} — propagation failed: {e}")

    threading.Thread(target=_propagate, daemon=True).start()


def _propagate_tree_cache_invalidation(tree_id, team_id):
    """Tell every host to drop its cached unified graph for a tree (base + all
    variants — the clear route wipes every variant entry when `variant` is
    omitted). Used after publish so the next prod run rebuilds from fresh data.
    Async, same shape as _propagate_variant_cache_invalidation."""
    if not tree_id:
        return

    def _propagate():
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from backend_server.src.lib.utils.route_utils import proxy_to_host_direct

            host_manager = get_host_manager()
            hosts = host_manager.get_all_hosts()
            cleared = []
            for host_info in hosts.values():
                try:
                    result, _ = proxy_to_host_direct(
                        host_info,
                        f'/host/navigation/cache/clear/{tree_id}?team_id={team_id}',
                        'POST',
                    )
                    if result and result.get('success'):
                        cleared.append(host_info.get('host_name'))
                except Exception:
                    pass  # Per-host failure is non-fatal
            print(f"[@cache] INVALIDATE TREE: {tree_id} — cleared on {', '.join(cleared) if cleared else 'no hosts'}")
        except Exception as e:
            print(f"[@cache] INVALIDATE TREE: {tree_id} — propagation failed: {e}")

    threading.Thread(target=_propagate, daemon=True).start()

# =====================================================
# USER INTERFACES ENDPOINTS
# =====================================================

@server_userinterface_bp.route('/getCompatibleInterfaces', methods=['GET'])
def get_compatible_interfaces():
    """Get user interfaces compatible with a specific device model"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    device_model = request.args.get('device_model')
    
    if not device_model:
        return jsonify({'success': False, 'error': 'device_model parameter required'}), 400
    
    # Create cache key from device_model and team_id
    cache_key = f"{team_id}:{device_model}"
    
    # Check cache first
    with _cache_lock:
        if cache_key in _compatible_cache:
            cached = _compatible_cache[cache_key]
            age = time.time() - cached['timestamp']
            # Use UI_TTL (60 seconds) for compatible interfaces
            if age < CACHE_CONFIG['UI_TTL']:
                print(f"[@cache] HIT: Compatible interfaces for {device_model} (age: {age/60:.1f}m)")
                return jsonify(cached['data'])
            else:
                del _compatible_cache[cache_key]
    
    # Get all interfaces for the team
    all_interfaces = get_all_userinterfaces(team_id)
        
    # Map host_vnc to also be compatible with web and desktop interfaces
    compatible_models = [device_model]
    if device_model == 'host_vnc':
        compatible_models.extend(['web', 'desktop'])
        print(f"[@server_userinterface] host_vnc device - also checking for web and desktop interfaces")
        
    # Filter to compatible ones (where device_model OR mapped models are in the models array)
    compatible_interfaces = [
        interface for interface in all_interfaces
        if any(model in (interface.get('models') or []) for model in compatible_models)
    ]
        
    response_data = {
        'success': True,
        'interfaces': compatible_interfaces,
        'device_model': device_model,
        'count': len(compatible_interfaces)
    }
        
    # Store in cache
    with _cache_lock:
        _compatible_cache[cache_key] = {
            'data': response_data,
            'timestamp': time.time()
        }
        print(f"[@cache] SET: Compatible interfaces for {device_model} ({CACHE_CONFIG['UI_TTL']}s TTL)")
        
    return jsonify(response_data)
@server_userinterface_bp.route('/getAllUserInterfaces', methods=['GET'])
def get_userinterfaces():
    """Get all user interfaces for the team"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    
    print(f"[@userinterface:getAllUserInterfaces] Request for team_id: {team_id}, force_refresh: {force_refresh}")
    
    # Check cache first (unless force_refresh)
    if not force_refresh:
        with _cache_lock:
            if team_id in _interfaces_cache:
                cached = _interfaces_cache[team_id]
                age = time.time() - cached['timestamp']
                # Use MEDIUM_TTL (5 minutes) for user interfaces instead of LONG_TTL (24 hours)
                # User interfaces metadata is relatively stable but can change when trees are modified
                if age < CACHE_CONFIG['MEDIUM_TTL']:
                    print(f"[@cache] HIT: User interfaces for team {team_id} (age: {age/60:.1f}m), returning {len(cached['data'])} interfaces")
                    return jsonify(cached['data'])
                else:
                    del _interfaces_cache[team_id]
                    print(f"[@cache] EXPIRED: User interfaces cache for team {team_id}")
    else:
        print(f"[@cache] BYPASS: Force refresh requested for team {team_id}")
    
    interfaces = get_all_userinterfaces(team_id)
    print(f"[@userinterface] Retrieved {len(interfaces)} interfaces from database")
        
    # Enrich interfaces with root tree information (only if tree has nodes).
    # Batched on purpose: this used to run TWO queries per interface (root tree,
    # then a limit=1 node probe), i.e. ~33 sequential round trips for 16
    # interfaces. Every DB call here is a ~200ms WAN hop, so the cache-miss path
    # took ~8s — the whole cost of a cold Interface page load. Now 2 queries.
    # Enrichment failures are non-fatal: interfaces are returned either way.
    interface_ids = [i['id'] for i in interfaces if i.get('id')]
    root_trees = get_root_trees_for_interfaces(interface_ids, team_id)
    trees_with_nodes = get_tree_ids_with_nodes(
        [t['id'] for t in root_trees.values()], team_id)

    for interface in interfaces:
        root_tree = root_trees.get(interface.get('id'))
        # Only attach a root tree that has actual nodes, not empty metadata
        if root_tree and root_tree['id'] in trees_with_nodes:
            interface['root_tree'] = root_tree

    enriched_interfaces = interfaces
    print(f"[@userinterface] Enriched {len(enriched_interfaces)} interfaces: "
          f"{len(root_trees)} root trees, {len(trees_with_nodes)} with nodes (2 queries)")


    # Store in cache
    with _cache_lock:
        _interfaces_cache[team_id] = {
            'data': enriched_interfaces,
            'timestamp': time.time()
        }
        print(f"[@cache] SET: User interfaces for team {team_id} ({len(enriched_interfaces)} interfaces, 5m TTL)")
        
    print(f"[@userinterface:getAllUserInterfaces] Returning {len(enriched_interfaces)} interfaces")
    return jsonify(enriched_interfaces)
@server_userinterface_bp.route('/createUserInterface', methods=['POST'])
def create_userinterface_route():
    """Create a new user interface"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    interface_data = request.json
        
    # Validate required fields
    if not interface_data.get('name'):
        return jsonify({'error': 'Name is required'}), 400
        
    if not interface_data.get('models') or len(interface_data.get('models', [])) == 0:
        return jsonify({'error': 'At least one model must be selected'}), 400
        
    # Check for duplicate names
    if check_userinterface_name_exists(interface_data['name'], team_id):
        return jsonify({'error': 'A user interface with this name already exists'}), 400
        
    # Create the user interface
    created_interface = create_userinterface(interface_data, team_id)
    if created_interface:
        # Invalidate cache after successful creation
        _invalidate_interfaces_cache(team_id)
        return jsonify({'status': 'success', 'userinterface': created_interface}), 201
    else:
        return jsonify({'error': 'Failed to create user interface'}), 500
@server_userinterface_bp.route('/getUserInterface/<interface_id>', methods=['GET'])
def get_userinterface_route(interface_id):
    """Get a specific user interface by ID"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    interface = get_userinterface(interface_id, team_id)
    if interface:
        # Enrich with root tree information
        root_tree = get_root_tree_for_interface(interface_id, team_id)
        if root_tree:
            interface['root_tree'] = root_tree
        return jsonify(interface)
    else:
        return jsonify({'error': 'User interface not found'}), 404
@server_userinterface_bp.route('/getUserInterfaceByName/<interface_name>', methods=['GET'])
def get_userinterface_by_name_route(interface_name):
    """Get a specific user interface by name (for navigation editor)"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    mode = request.args.get('mode', 'dev')
    if mode not in ('dev', 'prod'):
        return jsonify({'error': "mode must be 'dev' or 'prod'"}), 400

    interface = get_userinterface_by_name(interface_name, team_id, mode=mode)
    if interface:
        return jsonify(interface)
    else:
        return jsonify({'error': 'User interface not found'}), 404
@server_userinterface_bp.route('/updateUserInterface/<interface_id>', methods=['PUT'])
def update_userinterface_route(interface_id):
    """Update a specific user interface"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    interface_data = request.json
    if not interface_data:
        return jsonify({'error': 'Request body is required'}), 400
        
    # Fetch current interface to detect name changes
    current_interface = get_userinterface(interface_id, team_id)
    if not current_interface:
        return jsonify({'error': 'User interface not found'}), 404
    old_name = current_interface.get('name')
        
    # Validate required fields
    if not interface_data.get('name'):
        return jsonify({'error': 'Name is required'}), 400
        
    if not interface_data.get('models') or len(interface_data.get('models', [])) == 0:
        return jsonify({'error': 'At least one model must be selected'}), 400
        
    # Check for duplicate names (excluding current interface)
    if check_userinterface_name_exists(interface_data['name'], team_id, interface_id):
        return jsonify({'error': 'A user interface with this name already exists'}), 400
        
    # Update the user interface
    updated_interface = update_userinterface(interface_id, interface_data, team_id)
    if not updated_interface:
        return jsonify({'error': 'User interface not found or failed to update'}), 404

    # Cascade rename for references when name changed
    new_name = updated_interface.get('name')
    if new_name and old_name and new_name != old_name:
        cascade_result = update_references_userinterface_name(
            team_id=team_id,
            userinterface_id=interface_id,
            old_name=old_name,
            new_name=new_name,
        )
        if not cascade_result.get('success'):
            print(f"[@userinterface:update] ⚠️ Failed to cascade rename references: {cascade_result.get('error')}")
        else:
            print(f"[@userinterface:update] ✅ Cascaded rename to references: {cascade_result.get('updated_count')} rows")
        
    # Invalidate cache after successful update
    _invalidate_interfaces_cache(team_id)
    return jsonify({'status': 'success', 'userinterface': updated_interface})
@server_userinterface_bp.route('/deleteUserInterface/<interface_id>', methods=['DELETE'])
def delete_userinterface_route(interface_id):
    """Delete a specific user interface"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')

    # Capture the name BEFORE the row is gone — navigation screenshots are keyed
    # by userinterface_name, so we can't resolve their folder after the delete.
    ui = get_userinterface(interface_id, team_id)
    ui_name = ui.get('name') if ui else None

    # Always invalidate cache first to ensure fresh data on next request
    # This handles edge cases like direct SQL deletes or partial failures
    _invalidate_interfaces_cache(team_id)

    success = delete_userinterface(interface_id, team_id)
    if not success:
        return jsonify({'error': 'User interface not found or failed to delete'}), 404

    # Bucket cleanup (list + delete every reference/navigation object) scales with
    # object count and hits R2/MinIO over WAN — the user shouldn't wait for it. The
    # DB row is already gone (source of truth), so reclaim the bytes in the
    # background and return immediately. Under gevent, threading.Thread runs as a
    # greenlet; the S3 calls yield on I/O so this won't block the worker.
    def _cleanup_storage():
        try:
            storage = delete_userinterface_storage(interface_id, ui_name)
            print(f"[@userinterface:delete] storage cleanup for '{ui_name}' ({interface_id}): "
                  f"removed {storage.get('deleted')} object(s) — {storage.get('details')}")
        except Exception as e:
            print(f"[@userinterface:delete] storage cleanup failed (orphaned objects remain): {e}")

    threading.Thread(target=_cleanup_storage, daemon=True).start()

    return jsonify({'status': 'success'})
@server_userinterface_bp.route('/duplicateUserInterface/<interface_id>', methods=['POST'])
def duplicate_userinterface_route(interface_id):
    """Duplicate a user interface with its navigation tree"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    new_name = (request.json or {}).get('name')
    
    if not new_name:
        return jsonify({'error': 'Name is required'}), 400
    
    if check_userinterface_name_exists(new_name, team_id):
        return jsonify({'error': 'A user interface with this name already exists'}), 400
    
    result = duplicate_userinterface_with_tree(interface_id, new_name, team_id)
    if result:
        _invalidate_interfaces_cache(team_id)
        stats = result.get('duplication_stats', {})
        print(f"[@userinterface:duplicate] {interface_id} -> {result['id']} ({stats.get('nodes_count', 0)} nodes, {stats.get('edges_count', 0)} edges, {stats.get('references_count', 0)} references)")
        return jsonify({'status': 'success', 'userinterface': result}), 201
    return jsonify({'error': 'Failed to duplicate user interface'}), 500


# =====================================================
# DEV -> PROD PUBLISH
# =====================================================

@server_userinterface_bp.route('/publish/<interface_id>', methods=['POST'])
def publish_userinterface_route(interface_id):
    """Publish a dev userinterface to prod (create or in-place-update its prod snapshot)."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    from shared.src.lib.database.userinterface_publish import publish_userinterface

    result = publish_userinterface(interface_id, team_id)
    if result.get('success'):
        _invalidate_interfaces_cache(team_id)
        _propagate_tree_cache_invalidation(result.get('prod_root_tree_id'), team_id)
        counts = result.get('counts', {})
        print(f"[@userinterface:publish] {interface_id} -> prod {result['prod_userinterface_id']} "
              f"v{result['version']} ({counts.get('nodes')} nodes, {counts.get('edges')} edges)")
        return jsonify(result), 200
    return jsonify(result), 500


@server_userinterface_bp.route('/<interface_id>/publishes', methods=['GET'])
def list_publishes_route(interface_id):
    """Publish history for a dev userinterface (newest first)."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    from shared.src.lib.database.userinterface_publish import list_publishes

    return jsonify({'publishes': list_publishes(interface_id, team_id)})


# =====================================================
# EXPORT / IMPORT — portable .vptree bundle (zip: manifest.json + references/)
# See shared/.../userinterface_portability.py for the format + schema versioning.
# =====================================================

def _safe_extract(zf, dest_dir):
    """Extract a zip while rejecting path-traversal ('zip slip') members."""
    import os
    dest_abs = os.path.abspath(dest_dir)
    for member in zf.namelist():
        target = os.path.abspath(os.path.join(dest_dir, member))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise ValueError(f"unsafe path in bundle: {member}")
    zf.extractall(dest_dir)


@server_userinterface_bp.route('/<interface_id>/export', methods=['GET'])
def export_userinterface_route(interface_id):
    """Export a user interface + its full navigation tree as a downloadable .vptree bundle."""
    error = check_supabase()
    if error:
        return error

    import io
    import os
    import zipfile
    import shutil
    import tempfile
    from shared.src.lib.database.userinterface_portability import export_userinterface_bundle

    team_id = request.args.get('team_id')
    tmp = tempfile.mkdtemp(prefix='vptree_export_')
    try:
        bundle_dir = os.path.join(tmp, 'bundle')
        result = export_userinterface_bundle(interface_id, team_id, bundle_dir)
        if not result.get('success'):
            return jsonify({'error': result.get('error', 'Export failed')}), 404

        # Zip into memory so the temp dir can be reclaimed before the response streams.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(bundle_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    zf.write(fp, os.path.relpath(fp, bundle_dir))
        buf.seek(0)

        name = result.get('name') or 'userinterface'
        print(f"[@userinterface:export] {interface_id} -> {name}.vptree {result.get('stats')}")
        return send_file(buf, as_attachment=True, download_name=f"{name}.vptree",
                         mimetype='application/zip')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@server_userinterface_bp.route('/import', methods=['POST'])
def import_userinterface_route():
    """Import a .vptree bundle as a new user interface. multipart: file=<.vptree>, name=<new name>."""
    error = check_supabase()
    if error:
        return error

    import os
    import zipfile
    import shutil
    import tempfile
    from shared.src.lib.database.userinterface_portability import import_userinterface_bundle

    team_id = request.args.get('team_id')
    new_name = request.form.get('name')
    upload = request.files.get('file')

    if not upload:
        return jsonify({'error': 'file is required'}), 400
    if not new_name:
        return jsonify({'error': 'Name is required'}), 400
    if check_userinterface_name_exists(new_name, team_id):
        return jsonify({'error': 'A user interface with this name already exists'}), 400

    tmp = tempfile.mkdtemp(prefix='vptree_import_')
    try:
        zip_path = os.path.join(tmp, 'in.vptree')
        upload.save(zip_path)
        if not zipfile.is_zipfile(zip_path):
            return jsonify({'error': 'not a valid .vptree bundle (expected a zip)'}), 400

        src_dir = os.path.join(tmp, 'bundle')
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, src_dir)

        result = import_userinterface_bundle(src_dir, new_name, team_id, None)
        if not result.get('success'):
            return jsonify({'error': result.get('error', 'Import failed')}), 400

        _invalidate_interfaces_cache(team_id)
        print(f"[@userinterface:import] {new_name} <- {result.get('stats')}")
        return jsonify({
            'status': 'success',
            'userinterface': result['userinterface'],
            'stats': result.get('stats'),
            'warnings': result.get('warnings', []),
        }), 201
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# =====================================================
# VARIANT REGISTRY ENDPOINTS (see docs/agent/ENHANCE_VARIANT.md §6)
# =====================================================

# Allowed variant name pattern; mirrors the SQL CHECK constraint on
# userinterface_variants.name. Names are lowercase only — capitals are
# silently lowercased before the regex check so callers (CLI, MCP, frontend
# pre-normalization gaps) never see a "must be lowercase" error.
_VARIANT_NAME_RE = re.compile(r'^[a-z0-9._-]{1,64}$')


def _validate_variant_name(name):
    """Return (ok: bool, normalized_name_or_None, error_response_or_None).

    Normalization: trims whitespace and lowercases. Callers should use the
    returned normalized form for any DB or downstream calls.
    """
    if not isinstance(name, str) or not name.strip():
        return False, None, (jsonify({'error': "'name' is required"}), 400)
    normalized = name.strip().lower()
    if not _VARIANT_NAME_RE.match(normalized):
        return False, None, (jsonify({
            'error': f"invalid name '{name}'; must match {_VARIANT_NAME_RE.pattern}"
        }), 400)
    return True, normalized, None


@server_userinterface_bp.route('/variants', methods=['GET'])
def list_all_variants_route():
    """Every variant for the team, grouped by userinterface id.

    Batched form of /<interface_id>/variants: the Interface page renders a
    variants cell per row, so asking per interface cost one round trip per row.
    Same per-variant shape as the single-interface route, so both can share a
    frontend cache.
    """
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    return jsonify({'success': True, 'variants_by_interface': list_variants_for_team(team_id)})


@server_userinterface_bp.route('/<interface_id>/variants', methods=['GET'])
def list_variants_route(interface_id):
    """List every registered variant for the userinterface."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    # No existence check — list_variants already filters by (team_id, interface_id);
    # an unknown id simply returns []. The frontend treats empty and 404 the same way,
    # and skipping the validation cuts a Supabase round-trip in half.
    variants = list_variants(team_id, interface_id)
    return jsonify({'success': True, 'variants': variants})


@server_userinterface_bp.route('/<interface_id>/variants', methods=['POST'])
def create_variant_route(interface_id):
    """Register a new variant. Body: {name, description?, source_variant?: string|null}.

    `source_variant` semantics:
      - omitted / null → Base-derived. Auto-hides every variant-only row for the
        new variant. Response includes `hidden_rows: {nodes, edges}`.
      - string         → must reference an existing registered variant for this
        userinterface. Deep-copies every entry of the source onto the new
        variant. Response includes `cloned_rows: {nodes, edges}`.

    The deprecated `hide_in_new_variant` body key is silently ignored.
    """
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    ui = get_userinterface(interface_id, team_id)
    if not ui:
        return jsonify({'error': 'User interface not found'}), 404

    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    description = body.get('description', '') or ''
    source_variant = body.get('source_variant', None)
    if isinstance(source_variant, str):
        source_variant = source_variant.strip().lower() or None

    ok, normalized_name, err_resp = _validate_variant_name(name)
    if not ok:
        return err_resp

    result = add_variant(
        team_id,
        interface_id,
        normalized_name,
        description,
        source_variant=source_variant,
    )
    if not result.get('success'):
        if result.get('conflict'):
            return jsonify({'error': result.get('error')}), 409
        # Surface unknown source_variant as a 400 with the available list so
        # the FE can refresh its dropdown.
        if 'unknown source_variant' in (result.get('error') or '').lower():
            return jsonify({
                'error': result['error'],
                'available': result.get('available', []),
            }), 400
        return jsonify({'error': result.get('error', 'Failed to create variant')}), 400

    response = {'success': True, 'variant': result['variant']}
    if source_variant is None:
        response['hidden_rows'] = result.get('hidden_rows', {'nodes': 0, 'edges': 0})
    else:
        response['cloned_rows'] = result.get('cloned_rows', {'nodes': 0, 'edges': 0})
    return jsonify(response), 201


@server_userinterface_bp.route('/<interface_id>/variants/<name>', methods=['PUT'])
def update_variant_route(interface_id, name):
    """Partial update of a variant.

    Body fields (all optional, but at least one must be present):
      - description:    update the textual description.
      - node_overrides: REPLACE the variant's node_overrides JSONB map.
                        Keyed by node_id; entries
                        `{disabled?, verifications?, position?: {x, y}}`.
                        `position` is the per-variant canvas layout override
                        (nodes only; see docs/agent/navigation/VARIANT.md
                        "Per-variant node position").
      - edge_overrides: REPLACE the variant's edge_overrides JSONB map.
                        Keyed by edge_id; entries `{disabled?, action_sets?}`.

    Validation:
      - For each entry, `disabled: true` is mutually exclusive with the full
        override field (`verifications` for nodes, `action_sets` for edges).
      - The legacy `patches` field is rejected.
    """
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    ui = get_userinterface(interface_id, team_id)
    if not ui:
        return jsonify({'error': 'User interface not found'}), 404

    body = request.get_json() or {}
    description = body.get('description', None)
    node_overrides = body.get('node_overrides', None)
    edge_overrides = body.get('edge_overrides', None)

    # Validate the override map shapes if either was supplied.
    for label, value, kind in (
        ('node_overrides', node_overrides, 'node'),
        ('edge_overrides', edge_overrides, 'edge'),
    ):
        if value is None:
            continue
        ok, err = _validate_overrides_map(value, kind, label)
        if not ok:
            return jsonify({'error': err}), 400

    if description is None and node_overrides is None and edge_overrides is None:
        return jsonify({'error': 'No update fields provided'}), 400

    result = update_variant(
        team_id,
        interface_id,
        name,
        description=description,
        node_overrides=node_overrides,
        edge_overrides=edge_overrides,
    )
    if not result.get('success'):
        if 'not found' in (result.get('error') or '').lower():
            return jsonify({'error': result['error']}), 404
        return jsonify({'error': result.get('error', 'Failed to update variant')}), 400

    # Variant override JSONB changed → drop this variant's cached graph on
    # every host (cache key includes variant; pre-2026-05-12 this was missing
    # and runs served stale graphs until the 24h TTL).
    if node_overrides is not None or edge_overrides is not None:
        _propagate_variant_cache_invalidation(interface_id, team_id, [name])
        # Same variant scope on the RunTests picker caches (node/edge
        # dropdowns are variant-filtered) — drop the matching entries so
        # the next read recomputes against the fresh overrides.
        from backend_server.src.routes.server_navigation_trees_routes import (
            invalidate_picker_caches_for_variant,
        )
        invalidate_picker_caches_for_variant(team_id, ui['name'], name)

    return jsonify({'success': True, 'variant': result['variant']})


def _validate_overrides_map(value, kind: str, label: str):
    """Validate a node_overrides / edge_overrides map sent on the PUT body.

    Each entry shape:
      `{ disabled?: bool, enabled?: bool, verifications?: list | action_sets?: list,
         position?: {x: number, y: number} (nodes only) }`.
    The legacy `patches` field is rejected. `disabled: true` is mutually
    exclusive with the full-override field AND with `enabled: true`. `enabled`
    is the additive marker for a variant-only (`hidden_in_base`) row — it turns
    the row ON for this variant without other variants needing to disable it.
    See docs/agent/navigation/VARIANT.md "Composition".

    `position` is the per-variant CANVAS layout override (nodes only): the one
    topology field that legitimately differs per variant. It is purely cosmetic
    (the runtime graph never reads position) and may coexist with
    `verifications`, but is contradictory alongside `disabled` (a hidden row has
    no canvas position). See VARIANT.md "Per-variant node position".

    Returns (ok: bool, error_message_or_None). `kind` is 'node' or 'edge'.
    """
    if not isinstance(value, dict):
        return False, f"{label} must be an object keyed by {kind}_id"
    override_field = 'verifications' if kind == 'node' else 'action_sets'
    for row_id, entry in value.items():
        if not isinstance(row_id, str) or not row_id:
            return False, f"{label} keys must be non-empty strings"
        if not isinstance(entry, dict):
            return False, f"{label}['{row_id}'] must be an object"
        if 'patches' in entry:
            return False, (
                f"{label}['{row_id}'].patches is no longer supported; use "
                f"'{override_field}' to supply the variant's full content"
            )
        disabled = entry.get('disabled', False)
        if not isinstance(disabled, bool):
            return False, f"{label}['{row_id}'].disabled must be a boolean"
        enabled = entry.get('enabled', False)
        if not isinstance(enabled, bool):
            return False, f"{label}['{row_id}'].enabled must be a boolean"
        if disabled is True and enabled is True:
            return False, (
                f"{label}['{row_id}']: disabled=true and enabled=true are "
                f"mutually exclusive"
            )
        override_value = entry.get(override_field)
        if disabled is True and override_value is not None:
            return False, (
                f"{label}['{row_id}']: disabled=true and {override_field} are "
                f"mutually exclusive"
            )
        if override_value is not None and not isinstance(override_value, list):
            return False, f"{label}['{row_id}'].{override_field} must be a list"
        position = entry.get('position')
        if position is not None:
            if kind != 'node':
                return False, f"{label}['{row_id}'].position is only valid for nodes"
            if disabled is True:
                return False, (
                    f"{label}['{row_id}']: disabled=true and position are "
                    f"mutually exclusive"
                )
            if (
                not isinstance(position, dict)
                or not isinstance(position.get('x'), (int, float))
                or not isinstance(position.get('y'), (int, float))
                or isinstance(position.get('x'), bool)
                or isinstance(position.get('y'), bool)
            ):
                return False, (
                    f"{label}['{row_id}'].position must be {{x: number, y: number}}"
                )
    return True, None


@server_userinterface_bp.route('/<interface_id>/variants/<name>', methods=['DELETE'])
def delete_variant_route(interface_id, name):
    """Delete a variant: drop the registry row (its override maps go with it),
    then CASCADE: sweep hidden_in_base rows that no remaining variant shows —
    without this, rows only this variant enabled become orphans (invisible in
    Base and on every variant, yet still blocking their node pair)."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    ui = get_userinterface(interface_id, team_id)
    if not ui:
        return jsonify({'error': 'User interface not found'}), 404

    result = delete_variant(team_id, interface_id, name)
    if not result.get('success'):
        if result.get('not_found'):
            return jsonify({'error': result['error']}), 404
        return jsonify({'error': result.get('error', 'Failed to delete variant')}), 400

    sweep = sweep_orphan_hidden_rows(team_id, interface_id)
    if not sweep.get('success'):
        print(f"[@route:delete_variant] Orphan sweep failed (variant deleted): {sweep.get('error')}")

    _propagate_variant_cache_invalidation(interface_id, team_id, [name])
    from backend_server.src.routes.server_navigation_trees_routes import (
        invalidate_picker_caches_for_variant,
    )
    invalidate_picker_caches_for_variant(team_id, ui['name'], name)

    return jsonify({
        'success': True,
        'rows_changed': result.get('rows_changed', {'nodes': 0, 'edges': 0}),
        'orphans_removed': sweep.get('deleted', {'nodes': 0, 'edges': 0}),
    })


@server_userinterface_bp.route('/<interface_id>/variants/sweep-orphans', methods=['POST'])
def sweep_orphans_route(interface_id):
    """Repair endpoint: delete hidden_in_base rows that NO variant of this UI
    shows (orphans — see sweep_orphan_hidden_rows). Idempotent; safe to run
    any time since orphans render nowhere by definition."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    ui = get_userinterface(interface_id, team_id)
    if not ui:
        return jsonify({'error': 'User interface not found'}), 404

    result = sweep_orphan_hidden_rows(team_id, interface_id)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Sweep failed')}), 500

    # No cache invalidation needed: orphans render in NO scope, so no cached
    # resolved graph or picker list ever contained them.
    return jsonify({'success': True, 'deleted': result.get('deleted', {'nodes': 0, 'edges': 0})})


@server_userinterface_bp.route('/<interface_id>/variants/<name>/rename', methods=['POST'])
def rename_variant_route(interface_id, name):
    """Rename a variant. Body: {new_name}."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400

    ui = get_userinterface(interface_id, team_id)
    if not ui:
        return jsonify({'error': 'User interface not found'}), 404

    body = request.get_json() or {}
    new_name = (body.get('new_name') or '').strip()
    ok, normalized_new_name, err_resp = _validate_variant_name(new_name)
    if not ok:
        return err_resp

    # Path param `name` is the existing variant name; lowercase for the lookup
    # too so the rename works regardless of how the caller cased it.
    result = rename_variant(team_id, interface_id, name.strip().lower(), normalized_new_name)
    if not result.get('success'):
        if result.get('conflict'):
            return jsonify({'error': result['error']}), 409
        if result.get('not_found'):
            return jsonify({'error': result['error']}), 404
        return jsonify({'error': result.get('error', 'Failed to rename variant')}), 400

    # Rename: clear both the old and new cache keys. Old must die (no longer
    # the right name); new shouldn't have an entry yet but better safe.
    old_name = name.strip().lower()
    _propagate_variant_cache_invalidation(
        interface_id, team_id, [old_name, normalized_new_name]
    )
    from backend_server.src.routes.server_navigation_trees_routes import (
        invalidate_picker_caches_for_variant,
    )
    invalidate_picker_caches_for_variant(team_id, ui['name'], old_name)
    invalidate_picker_caches_for_variant(team_id, ui['name'], normalized_new_name)

    return jsonify({
        'success': True,
        'rows_changed': result.get('rows_changed', {'nodes': 0, 'edges': 0}),
    })