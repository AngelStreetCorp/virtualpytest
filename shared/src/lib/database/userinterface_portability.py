#!/usr/bin/env python3

"""
Export / import a userinterface and its full navigation tree as a portable .vptree bundle.

A `.vptree` file is a zip:

    manifest.json          — schema-versioned logical tree (see VPTREE_SCHEMA_VERSION)
    references/<r2_path>    — the backing image object for every reference_image row,
                             stored under its *source* R2 key so import can re-key it.

This mirrors `duplicate_userinterface_with_tree` (userinterface_db.py) but is
file-mediated instead of DB->DB, so a tree can travel across databases / object
stores (cross-server transfer, OSS repo split) with its reference images bundled
inside the archive — no dangling references on a fresh store.

This layer works on a DIRECTORY (`dest_dir` / `src_dir`). The HTTP route owns the
zip<->dir packing and streaming. Kept in its own module so the portability concerns
— schema versioning (point 2), enum validation (point 3), object bundling — live in
one place instead of bloating userinterface_db.py.
"""

import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib.database.userinterface_db import (
    get_supabase,
    get_userinterface,
    create_userinterface,
    list_variants,
    _drop_default_navigation_trees,
)
from shared.src.lib.database.navigation_trees_db import (
    get_root_tree_for_interface,
    get_complete_tree_hierarchy,
    save_tree_hierarchy,
)

# ============================================================================
# Format constants + validation (points 2 & 3)
# ============================================================================

VPTREE_SCHEMA_VERSION = "1.0"
VPTREE_KIND = "vptree"
MANIFEST_NAME = "manifest.json"
REFERENCES_DIR = "references"

# Point 3: freeze the presentational / structural vocabulary so a bundle stays
# portable and an old importer degrades predictably. Enum drift is a WARNING, never
# a hard failure — a real export must never become unimportable over a cosmetic value.
VALID_NODE_TYPES = {'entry', 'screen', 'menu', 'action', 'default'}
VALID_EDGE_PRIORITIES = {'p1', 'p2', 'p3'}
VALID_HANDLE_SIDES = {'left', 'right', 'top', 'bottom'}


def _schema_major(schema: str) -> Optional[int]:
    try:
        return int(str(schema).split('.')[0])
    except (ValueError, AttributeError):
        return None


def validate_manifest(manifest: Any) -> Tuple[bool, List[str], List[str]]:
    """Validate a .vptree manifest. Returns (ok, errors, warnings).

    Point 2 — schema gate: a manifest without a `schema`, with a non-1 major, or with
    the wrong `kind` is rejected (forward-incompatible). A future 1.x minor is accepted
    (additive). Point 3 — enum drift on node_type / edge priority is reported as a
    warning so a cosmetic mismatch never blocks an import.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(manifest, dict):
        return False, ["manifest is not a JSON object"], warnings

    schema = manifest.get('schema')
    major = _schema_major(schema)
    if schema is None:
        errors.append("missing 'schema' — not a .vptree manifest")
    elif major is None:
        errors.append(f"unparseable schema '{schema}'")
    elif major != _schema_major(VPTREE_SCHEMA_VERSION):
        errors.append(
            f"unsupported schema major '{schema}' (this build reads {VPTREE_SCHEMA_VERSION})")

    if manifest.get('kind') != VPTREE_KIND:
        errors.append(f"unexpected kind '{manifest.get('kind')}' (expected '{VPTREE_KIND}')")

    if not isinstance(manifest.get('source'), dict):
        errors.append("missing 'source' block")

    trees = manifest.get('trees')
    if not isinstance(trees, list):
        errors.append("missing or invalid 'trees' array")
        return len(errors) == 0, errors, warnings

    for t in trees:
        for n in (t.get('nodes') or []):
            nt = n.get('node_type')
            if nt is not None and nt not in VALID_NODE_TYPES:
                warnings.append(f"node '{n.get('node_id')}' has unknown node_type '{nt}'")
        for e in (t.get('edges') or []):
            pr = (e.get('data') or {}).get('priority')
            if pr is not None and pr not in VALID_EDGE_PRIORITIES:
                warnings.append(f"edge '{e.get('edge_id')}' has unknown priority '{pr}'")

    return len(errors) == 0, errors, warnings


# ============================================================================
# Reference helpers (shared shape with _duplicate_references_for_ui)
# ============================================================================

def _fetch_local_references(source_id: str, source_name: str, team_id: str) -> List[Dict]:
    """Local (non-shared) verification reference rows for a UI, id-first w/ name fallback.

    Matches _duplicate_references_for_ui's selection: `shared=True` rows are skipped
    (they resolve for any model-compatible UI), and legacy rows whose userinterface_id
    was never backfilled are caught by the name fallback.
    """
    supabase = get_supabase()
    return (
        supabase.table('verifications_references')
        .select('*')
        .eq('team_id', team_id)
        .eq('shared', False)
        .or_(f'userinterface_id.eq.{source_id},'
             f'and(userinterface_id.is.null,userinterface_name.eq.{source_name})')
        .execute()
        .data
    ) or []


def _swap_folder(r2_path: Optional[str], new_id: str) -> Optional[str]:
    """reference-images/<old>/<rest…> -> reference-images/<new_id>/<rest…> (also text-references)."""
    if not r2_path:
        return None
    parts = r2_path.split('/')
    if len(parts) < 3 or parts[0] not in ('reference-images', 'text-references'):
        return None
    parts[1] = new_id
    return '/'.join(parts)


def _safe_bundle_path(src_dir: str, rel_path: str) -> Optional[str]:
    """Resolve `rel_path` (an object key from an untrusted manifest) under
    `src_dir/references/`, returning the absolute local path only if it stays inside
    that directory. Guards against a crafted .vptree whose reference r2_path is
    absolute ('/etc/passwd') or traverses ('../../secret') — os.path.join would
    otherwise escape the bundle and let import read an arbitrary server file into
    object storage. Returns None on any escape or empty input."""
    if not rel_path:
        return None
    refs_root = os.path.abspath(os.path.join(src_dir, REFERENCES_DIR))
    # normpath collapses '..'; an absolute rel_path makes join return rel_path itself.
    candidate = os.path.abspath(os.path.join(refs_root, rel_path))
    if candidate == refs_root or candidate.startswith(refs_root + os.sep):
        return candidate
    return None


# ============================================================================
# EXPORT
# ============================================================================

def export_userinterface_bundle(ui_id: str, team_id: str, dest_dir: str) -> Dict:
    """Write a .vptree bundle (manifest.json + references/) into `dest_dir`.

    Returns {success, name, stats:{trees,nodes,edges,variants,references,objects_bundled,
    objects_failed}} or {success: False, error}. The HTTP route zips `dest_dir`.
    """
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils

    ui = get_userinterface(ui_id, team_id)
    if not ui:
        return {'success': False, 'error': f'userinterface {ui_id} not found'}

    # Tree hierarchy (root + all subtrees). A UI with no tree still exports (empty trees).
    all_trees_data: List[Dict] = []
    root = get_root_tree_for_interface(ui_id, team_id)
    if root:
        hierarchy = get_complete_tree_hierarchy(root['id'], team_id)
        if hierarchy.get('success'):
            all_trees_data = hierarchy['all_trees_data']
        else:
            return {'success': False, 'error': f"failed to read tree hierarchy: {hierarchy.get('error')}"}

    variants = list_variants(team_id, ui_id)
    references = _fetch_local_references(ui_id, ui.get('name'), team_id)

    # Download every reference_image object into references/<r2_path> so it travels
    # inside the bundle. Text references carry their content in `area`, no object.
    cf = get_cloudflare_utils()
    refs_root = os.path.join(dest_dir, REFERENCES_DIR)
    objects_bundled = objects_failed = 0
    for r in references:
        if r.get('reference_type') != 'reference_image':
            continue
        r2_path = r.get('r2_path')
        if not r2_path:
            continue
        local_path = os.path.join(refs_root, r2_path)
        res = cf.download_file(r2_path, local_path)
        if res.get('success'):
            objects_bundled += 1
        else:
            print(f"[@db:userinterface_portability:export] download failed {r2_path}: {res.get('error')}")
            objects_failed += 1

    manifest = {
        'schema': VPTREE_SCHEMA_VERSION,
        'kind': VPTREE_KIND,
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'source': {
            'userinterface_id': ui['id'],
            'name': ui.get('name'),
            'models': ui.get('models', []),
            'min_version': ui.get('min_version', ''),
            'max_version': ui.get('max_version', ''),
        },
        'trees': all_trees_data,
        'variants': variants,
        'references': references,
    }

    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    total_nodes = sum(len(t.get('nodes', [])) for t in all_trees_data)
    total_edges = sum(len(t.get('edges', [])) for t in all_trees_data)
    stats = {
        'trees': len(all_trees_data),
        'nodes': total_nodes,
        'edges': total_edges,
        'variants': len(variants),
        'references': len(references),
        'objects_bundled': objects_bundled,
        'objects_failed': objects_failed,
    }
    print(f"[@db:userinterface_portability:export] {ui.get('name')} -> {stats}")
    return {'success': True, 'name': ui.get('name'), 'stats': stats}


# ============================================================================
# IMPORT
# ============================================================================

def _restore_variants(new_ui_id: str, team_id: str, variants: List[Dict]) -> int:
    """Insert bundled variant rows under the new UI. Mirrors add_variant's insert
    shape (no explicit id — the DB default supplies it). Node/edge override keys are
    stable node_id/edge_id, so they line up with the freshly-saved hierarchy."""
    if not variants:
        return 0
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    restored = 0
    for v in variants:
        try:
            supabase.table('userinterface_variants').insert({
                'team_id': team_id,
                'userinterface_id': new_ui_id,
                'name': v['name'],
                'description': v.get('description', '') or '',
                'node_overrides': v.get('node_overrides') or {},
                'edge_overrides': v.get('edge_overrides') or {},
                'created_at': now,
                'updated_at': now,
            }).execute()
            restored += 1
        except Exception as e:
            print(f"[@db:userinterface_portability:import] variant '{v.get('name')}' restore failed: {e}")
    return restored


def _restore_references(new_id: str, new_name: str, team_id: str,
                        references: List[Dict], src_dir: str) -> Dict:
    """Re-key bundled references onto the new UI: upload each object under the new id
    folder and insert a fresh verifications_references row. Mirrors
    _duplicate_references_for_ui but the object bytes come from the bundle, not a
    live-to-live copy_file."""
    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
    from shared.src.lib.database.verifications_references_db import _invalidate_references_cache

    if not references:
        return {'references': 0, 'objects_uploaded': 0, 'objects_failed': 0}

    supabase = get_supabase()
    cf = get_cloudflare_utils()
    now = datetime.now(timezone.utc).isoformat()
    inserted = objects_uploaded = objects_failed = 0

    for r in references:
        rtype = r.get('reference_type')
        src_path = r.get('r2_path')
        # Re-key the object folder to the new UI id. _swap_folder returns None unless
        # src_path is a well-formed reference key, so a malformed/absolute/foreign path
        # is never trusted as either a local read path or a remote upload key.
        new_path = _swap_folder(src_path, new_id)
        new_url = r.get('r2_url')

        if rtype == 'reference_image':
            if not new_path:
                print(f"[@db:userinterface_portability:import] skipping image ref with "
                      f"non-standard r2_path: {src_path!r}")
                objects_failed += 1
            else:
                bundled = _safe_bundle_path(src_dir, src_path)
                if bundled and os.path.exists(bundled):
                    res = cf.upload_files([{'local_path': bundled, 'remote_path': new_path}])
                    ok = res.get('uploaded_files') and res['uploaded_files'][0].get('success')
                    if ok:
                        new_url = res['uploaded_files'][0].get('url') or cf.get_public_url(new_path)
                        objects_uploaded += 1
                    else:
                        print(f"[@db:userinterface_portability:import] upload failed {new_path}: {res}")
                        objects_failed += 1
                else:
                    # Object missing from the bundle: keep the row so the reference still
                    # resolves by name, pointing at the re-keyed (possibly empty) path.
                    print(f"[@db:userinterface_portability:import] bundle missing object for {src_path!r}")
                    objects_failed += 1
                    new_url = cf.get_public_url(new_path)

        supabase.table('verifications_references').insert({
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
            'created_at': now,
            'updated_at': now,
        }).execute()
        inserted += 1

    _invalidate_references_cache()
    return {'references': inserted, 'objects_uploaded': objects_uploaded, 'objects_failed': objects_failed}


def import_userinterface_bundle(src_dir: str, new_name: str, team_id: str,
                                creator_id: Optional[str] = None) -> Dict:
    """Import a .vptree bundle (already unzipped into `src_dir`) as a new userinterface.

    Sequence mirrors duplicate_userinterface_with_tree: create UI -> drop the trigger's
    default tree (avoid double-root) -> re-key references from the bundle -> save the
    tree hierarchy -> restore variants. Returns {success, userinterface, stats} or
    {success: False, error, warnings?}.
    """
    manifest_path = os.path.join(src_dir, MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        return {'success': False, 'error': f'{MANIFEST_NAME} not found in bundle'}
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception as e:
        return {'success': False, 'error': f'invalid manifest JSON: {e}'}

    ok, errors, warnings = validate_manifest(manifest)
    if not ok:
        return {'success': False, 'error': 'invalid .vptree bundle: ' + '; '.join(errors)}

    source = manifest['source']
    new_ui = create_userinterface({
        'name': new_name,
        'models': source.get('models', []),
        'min_version': source.get('min_version', ''),
        'max_version': source.get('max_version', ''),
    }, team_id, creator_id)
    if not new_ui:
        return {'success': False, 'error': 'failed to create userinterface'}

    new_ui_id = new_ui['id']

    # The after_userinterface_insert trigger seeds an empty default root tree; drop it
    # so the imported hierarchy is the only root (else two is_root_tree trees).
    try:
        _drop_default_navigation_trees(new_ui_id, team_id)
    except Exception as e:
        print(f"[@db:userinterface_portability:import] default-tree cleanup failed: {e}")

    # References first (non-fatal): a tree with missing refs is still usable.
    try:
        ref_stats = _restore_references(
            new_ui_id, new_name, team_id, manifest.get('references', []), src_dir)
    except Exception as e:
        print(f"[@db:userinterface_portability:import] reference restore failed: {e}")
        ref_stats = {'references': 0, 'objects_uploaded': 0, 'objects_failed': 0, 'error': str(e)}

    tree_result = save_tree_hierarchy(manifest.get('trees', []), new_ui_id, new_name, team_id)
    if not tree_result.get('success'):
        return {'success': False, 'error': f"failed to save tree: {tree_result.get('error')}",
                'userinterface': new_ui}

    variants_restored = _restore_variants(new_ui_id, team_id, manifest.get('variants', []))

    stats = {
        'trees': tree_result.get('trees_count', 0),
        'nodes': tree_result.get('nodes_count', 0),
        'edges': tree_result.get('edges_count', 0),
        'variants': variants_restored,
        'references': ref_stats.get('references', 0),
        'objects_uploaded': ref_stats.get('objects_uploaded', 0),
        'objects_failed': ref_stats.get('objects_failed', 0),
    }
    print(f"[@db:userinterface_portability:import] {new_name} <- {stats}")
    result = {'success': True, 'userinterface': new_ui, 'stats': stats}
    if warnings:
        result['warnings'] = warnings
    return result
