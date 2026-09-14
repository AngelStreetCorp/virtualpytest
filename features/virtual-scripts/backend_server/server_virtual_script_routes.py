"""
Server Virtual Script Routes — CRUD + syntax validation for DB-stored Python
test scripts (the "Virtual Scripts" editor).

Execution is NOT here: virtual scripts run through the normal
/server/script/execute path with a `virtual_script_id` field — the host fetches
the source from the DB and materializes it to a temp file before launch.
See docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.folder_tag_db import list_all_folders
from shared.src.lib.database.virtual_scripts_db import (
    list_virtual_scripts,
    get_virtual_script,
    get_virtual_script_by_name,
    create_virtual_script,
    update_virtual_script,
    delete_virtual_script,
    get_virtual_script_versions,
    restore_virtual_script_version,
    promote_virtual_script,
    upsert_virtual_script_dev,
)
from shared.src.lib.utils.script_conversion import (
    ERR_NAME_COLLISION,
    ERR_NOT_FOUND,
    ROOT_FOLDER,
    plan_conversion,
)
from ..lib.virtual_script_utils import (
    validate_virtual_script,
    extract_virtual_script_metadata,
)
from backend_server.src.routes.server_script_routes import (
    analyze_script_source,
    invalidate_script_list_cache,
)
from backend_server.src.routes.server_executable_routes import invalidate_executable_list_cache
from backend_server.src.lib.utils.script_utils import is_discoverable_script_ref


def _invalidate_lists() -> None:
    invalidate_script_list_cache()
    invalidate_executable_list_cache()

server_virtual_script_bp = Blueprint('server_virtual_script', __name__, url_prefix='/server/virtual-script')


def _require_team_id():
    team_id = request.args.get('team_id')
    if not team_id:
        return None, (jsonify({'success': False, 'error': 'team_id is required'}), 400)
    return team_id, None


@server_virtual_script_bp.route('/list', methods=['GET'])
@handle_route_exceptions('virtual_script:list')
def vs_list():
    """Every virtual script for the team, libraries included.

    Unlike /server/executable/list (the run picker, which drops them), this keeps
    utils_/lib_/common_ scripts so they stay editable — they are real sources that
    other scripts pull in through _script_libs. Each entry carries `is_library` so
    a caller that is offering things to RUN can filter them out.
    """
    team_id, err = _require_team_id()
    if err:
        return err
    scripts = list_virtual_scripts(team_id)
    for script in scripts:
        script['is_library'] = not is_discoverable_script_ref(script.get('name') or '')
    return jsonify({
        'success': True,
        'scripts': scripts,
        'count': len(scripts),
        'folders': list_all_folders(),
    })


@server_virtual_script_bp.route('/validate', methods=['POST'])
@handle_route_exceptions('virtual_script:validate')
def vs_validate():
    """Syntax + structure check only (used by the editor, no persistence)."""
    data = request.get_json() or {}
    source = data.get('source', '')
    result = validate_virtual_script(source)
    return jsonify({'success': True, 'validation': result})


@server_virtual_script_bp.route('/analyze', methods=['POST'])
@handle_route_exceptions('virtual_script:analyze')
def vs_analyze():
    """Parse parameters (_script_args / argparse) from source text."""
    data = request.get_json() or {}
    source = data.get('source', '')
    name = data.get('name') or 'virtual_script'
    analysis = analyze_script_source(source, name)
    return jsonify(analysis)


@server_virtual_script_bp.route('/save', methods=['POST'])
@handle_route_exceptions('virtual_script:save')
def vs_save():
    """Create or update a virtual script. Validates syntax (blocks on error)."""
    team_id, err = _require_team_id()
    if err:
        return err

    data = request.get_json() or {}
    script_id = data.get('id')
    name = (data.get('name') or '').strip()
    source = data.get('source', '')
    description = data.get('description')
    doc = data.get('doc')
    folder = data.get('folder')

    if not name:
        return jsonify({'success': False, 'error': 'name is required'}), 400
    if not source.strip():
        return jsonify({'success': False, 'error': 'source is required'}), 400

    # Hard gate on syntax — never persist a script that won't compile.
    validation = validate_virtual_script(source)
    if not validation.get('valid'):
        return jsonify({'success': False, 'error': 'syntax_error', 'validation': validation}), 400

    # Derive metadata from the source (description falls back to _script_description).
    meta = extract_virtual_script_metadata(source)
    if not description:
        description = meta.get('description')
    target_rules = meta.get('target_rules')

    # Reject duplicate names (other than this row).
    existing_by_name = get_virtual_script_by_name(name, team_id)
    if existing_by_name and existing_by_name.get('id') != script_id:
        return jsonify({'success': False, 'error': f"A virtual script named '{name}' already exists"}), 409

    if script_id:
        row = update_virtual_script(
            script_id, team_id=team_id, name=name, source=source,
            description=description, doc=doc, target_rules=target_rules, folder=folder,
        )
        if not row:
            return jsonify({'success': False, 'error': 'Virtual script not found'}), 404
    else:
        created_by = data.get('created_by') or request.headers.get('X-User-ID')
        row = create_virtual_script(
            name=name, source=source, team_id=team_id, description=description,
            doc=doc, target_rules=target_rules, created_by=created_by, folder=folder,
        )

    _invalidate_lists()

    analysis = analyze_script_source(source, name)
    return jsonify({
        'success': True,
        'id': row.get('id'),
        'script': {k: v for k, v in row.items() if k != 'source'},
        'validation': validation,
        'parameters': analysis.get('parameters', []),
    })


@server_virtual_script_bp.route('/<script_id>', methods=['GET'])
@handle_route_exceptions('virtual_script:get')
def vs_get(script_id):
    team_id, err = _require_team_id()
    if err:
        return err
    row = get_virtual_script(script_id, team_id)
    if not row:
        return jsonify({'success': False, 'error': 'Virtual script not found'}), 404
    analysis = analyze_script_source(row.get('source', ''), row.get('name'))
    return jsonify({'success': True, 'script': row, 'parameters': analysis.get('parameters', [])})


@server_virtual_script_bp.route('/<script_id>', methods=['DELETE'])
@handle_route_exceptions('virtual_script:delete')
def vs_delete(script_id):
    team_id, err = _require_team_id()
    if err:
        return err
    ok = delete_virtual_script(script_id, team_id)
    if ok:
        _invalidate_lists()
    return jsonify({'success': ok})


@server_virtual_script_bp.route('/<script_id>/versions', methods=['GET'])
@handle_route_exceptions('virtual_script:versions')
def vs_versions(script_id):
    team_id, err = _require_team_id()
    if err:
        return err
    versions = get_virtual_script_versions(script_id, team_id)
    return jsonify({'success': True, 'versions': versions})


@server_virtual_script_bp.route('/<script_id>/restore/<int:version_number>', methods=['POST'])
@handle_route_exceptions('virtual_script:restore')
def vs_restore(script_id, version_number):
    team_id, err = _require_team_id()
    if err:
        return err
    row = restore_virtual_script_version(script_id, version_number, team_id)
    if not row:
        return jsonify({'success': False, 'error': 'Version not found'}), 404
    _invalidate_lists()
    return jsonify({'success': True, 'script': row})


@server_virtual_script_bp.route('/<script_id>/promote', methods=['POST'])
@handle_route_exceptions('virtual_script:promote')
def vs_promote(script_id):
    """Promote a virtual script one lifecycle step (dev->test or test->prod).

    Body: {"target_env": "test"|"prod"}. Copies the lower env's source into the
    target row; on promote-to-prod the previous prod snapshot is kept as N-1 for
    rollback and prod_version increments. script_id identifies the script (any of
    its env rows); promotion resolves by name, so the dev/base id is fine.
    """
    team_id, err = _require_team_id()
    if err:
        return err
    row = get_virtual_script(script_id, team_id)
    if not row:
        return jsonify({'success': False, 'error': 'Virtual script not found'}), 404

    target_env = (request.get_json() or {}).get('target_env')
    if target_env not in ('test', 'prod'):
        return jsonify({'success': False, 'error': "target_env must be 'test' or 'prod'"}), 400

    result = promote_virtual_script(row['name'], team_id, target_env)
    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('error', 'Promote failed')}), 400
    _invalidate_lists()
    return jsonify({
        'success': True,
        'script': {k: v for k, v in (result.get('script') or {}).items() if k != 'source'},
        'target_env': target_env,
        'prod_version': result.get('prod_version'),
    })


# --- Convert disk scripts to virtual scripts ---------------------------------
#
# Conversion is not a copy: a virtual script materializes at the test_scripts/
# ROOT, so folder-relative imports break and the name must lose its folder. The
# rewrite rules live in shared/src/lib/utils/script_conversion.py; these routes
# are the plan-then-write wrapper around them.


def _write_units(units, team_id, created_by):
    """Persist conversion units in order — helpers first, because a half-converted
    state fails at import time with a confusing error: resolve_virtual_script_libs
    only logs and skips a lib it cannot find.

    Returns (written_rows, None) or (None, failed_unit)."""
    written = []
    for unit in units:
        meta = extract_virtual_script_metadata(unit.source)
        result = upsert_virtual_script_dev(
            name=unit.vs_name,
            source=unit.source,
            team_id=team_id,
            description=meta.get('description'),
            doc=unit.doc,
            target_rules=meta.get('target_rules'),
            created_by=created_by,
            folder=None if unit.folder == ROOT_FOLDER else unit.folder,
        )
        if not result.get('success'):
            return None, unit
        row = result.get('script') or {}
        written.append({
            'name': unit.vs_name,
            'folder': unit.folder,
            'disk_ref': unit.disk_ref,
            'id': row.get('id'),
            'action': result.get('action'),
            'libs': unit.libs,
            'has_doc': bool(unit.doc),
            'is_helper': unit.is_helper,
            'warnings': unit.warnings,
        })
    return written, None


def _warning_block(units, allow_warnings):
    """Refuse to write units whose paths will break after materialization.

    These compile fine — the failure is at run time, when a path built from
    __file__ resolves to the test_scripts/ root instead of the script's folder
    (a sibling *_profiles.json is simply not found). Writing them anyway would
    produce a virtual script that looks converted and silently misbehaves.
    """
    if allow_warnings:
        return None
    warned = [u for u in units if u.warnings]
    if not warned:
        return None
    return jsonify({
        'success': False,
        'error': 'conversion_warnings',
        'units': [{'name': u.vs_name, 'disk_ref': u.disk_ref, 'warnings': u.warnings}
                  for u in warned],
    }), 400


def _plan_refs(refs, scripts_dir, include_helpers, strip_bootstrap):
    """Plan several scripts as one batch, with a batch-wide basename collision
    check — two folders producing the same virtual-script name would shadow each
    other, since _script_libs resolves by bare name."""
    plans, errors, claimed = [], [], {}
    for ref in refs:
        plan = plan_conversion(
            ref, scripts_dir,
            include_helpers=include_helpers,
            strip_syspath_bootstrap=strip_bootstrap,
        )
        errors.extend(plan.errors)
        for unit in plan.units:
            owner = claimed.setdefault(unit.vs_name, unit.disk_ref)
            if owner != unit.disk_ref:
                errors.append({
                    'ref': unit.disk_ref, 'code': ERR_NAME_COLLISION,
                    'message': f"'{unit.disk_ref}' and '{owner}' both become virtual "
                               f"script '{unit.vs_name}' — rename one first",
                })
        plans.append(plan)
    return plans, errors


def _dedupe_units(plans):
    """Flatten plans, keeping the first unit per disk_ref (a helper shared by two
    entry scripts is converted once)."""
    seen, units = set(), []
    for plan in plans:
        for unit in plan.units:
            if unit.disk_ref in seen:
                continue
            seen.add(unit.disk_ref)
            units.append(unit)
    return units


@server_virtual_script_bp.route('/convert', methods=['POST'])
@handle_route_exceptions('virtual_script:convert')
def vs_convert():
    """Convert an on-disk Python script into virtual scripts.

    Body: {"script_name": "gw/superping", "dry_run": false,
           "include_helpers": true, "strip_bootstrap": true}

    Reads the source from the server's test_scripts/ directory, follows
    `from test_scripts.<pkg>.<mod> import ...` helper imports, rewrites them to
    the bare form, declares them in `_script_libs`, and writes one dev row per
    unit — helpers first. The script is named by its BASENAME and filed under its
    disk subfolder: a slashed virtual-script name would crash lib materialization
    (script_executor writes `<vslib_dir>/<name>.py` with no mkdir).

    Idempotent: re-converting overwrites the same dev rows, and the history
    trigger only fires when the source actually changed.
    """
    import os
    from backend_server.src.lib.utils.script_utils import get_scripts_directory

    team_id, err = _require_team_id()
    if err:
        return err

    data = request.get_json() or {}
    raw_name = (data.get('script_name') or '').strip()
    if not raw_name:
        return jsonify({'success': False, 'error': 'script_name is required'}), 400

    # Virtual-script names carry no .py; disk files do.
    base_ref = raw_name[:-3] if raw_name.endswith('.py') else raw_name
    scripts_dir = os.path.abspath(get_scripts_directory())

    # Path-traversal guard (same shape as _get_script_path in the executor).
    candidate = os.path.abspath(os.path.join(scripts_dir, f'{base_ref}.py'))
    if not candidate.startswith(f'{scripts_dir}{os.sep}'):
        return jsonify({'success': False, 'error': 'Invalid script name'}), 400

    plans, errors = _plan_refs(
        [base_ref], scripts_dir,
        include_helpers=data.get('include_helpers', True),
        strip_bootstrap=data.get('strip_bootstrap', True),
    )
    units = _dedupe_units(plans)
    preview = [{
        'name': u.vs_name, 'folder': u.folder, 'disk_ref': u.disk_ref,
        'libs': u.libs, 'has_doc': bool(u.doc), 'is_helper': u.is_helper,
        'warnings': u.warnings,
    } for u in units]

    if errors:
        code = 404 if any(e['code'] == ERR_NOT_FOUND for e in errors) else 400
        return jsonify({'success': False, 'error': 'conversion_failed',
                        'errors': errors, 'units': preview}), code

    # Never persist a script that won't compile — same gate as vs_save, applied
    # to the REWRITTEN source of every unit.
    for unit in units:
        validation = validate_virtual_script(unit.source)
        if not validation.get('valid'):
            return jsonify({'success': False, 'error': 'syntax_error',
                            'script_name': unit.disk_ref,
                            'validation': validation}), 400

    blocked = _warning_block(units, data.get('allow_warnings', False))
    if blocked:
        return blocked

    if data.get('dry_run'):
        return jsonify({'success': True, 'dry_run': True,
                        'root': base_ref, 'units': preview, 'errors': []})

    created_by = data.get('created_by') or request.headers.get('X-User-ID')
    written, failed_unit = _write_units(units, team_id, created_by)
    if written is None:
        return jsonify({'success': False,
                        'error': f"Convert failed while writing '{failed_unit.vs_name}'"}), 500

    _invalidate_lists()
    root = next((w for w in written if w['disk_ref'] == base_ref), None)
    return jsonify({
        'success': True,
        'root': base_ref,
        'name': root['name'] if root else None,
        'id': root['id'] if root else None,
        'action': root['action'] if root else None,
        'units': written,
        'errors': [],
    })


@server_virtual_script_bp.route('/convert-batch', methods=['POST'])
@handle_route_exceptions('virtual_script:convert_batch')
def vs_convert_batch():
    """Convert many disk scripts in one operation.

    Body: {"script_names": [...]} | {"folder": "gw"} | {"all": true},
    plus optional "dry_run", "include_helpers", "strip_bootstrap".

    Plans everything first and writes nothing if any script fails, so a batch
    never leaves half-converted state. Helpers shared by several scripts are
    converted once.
    """
    import os
    from backend_server.src.lib.utils.script_utils import (
        get_scripts_directory, list_available_scripts,
    )

    team_id, err = _require_team_id()
    if err:
        return err

    data = request.get_json() or {}
    scripts_dir = os.path.abspath(get_scripts_directory())

    refs = [str(n).strip() for n in (data.get('script_names') or []) if str(n).strip()]
    folder = (data.get('folder') or '').strip()
    if data.get('all') or folder:
        # list_available_scripts() also reports test_campaign/* entries, which live
        # outside test_scripts/ and are campaign runners, not convertible scripts.
        discovered = [s[:-3] if s.endswith('.py') else s
                      for s in list_available_scripts()
                      if not s.startswith('test_campaign/')]
        refs = [r for r in discovered if not folder or r.startswith(f'{folder}/')]
    refs = [r[:-3] if r.endswith('.py') else r for r in refs]
    if not refs:
        return jsonify({'success': False,
                        'error': 'script_names, folder or all is required'}), 400

    for ref in refs:
        candidate = os.path.abspath(os.path.join(scripts_dir, f'{ref}.py'))
        if not candidate.startswith(f'{scripts_dir}{os.sep}'):
            return jsonify({'success': False, 'error': f"Invalid script name '{ref}'"}), 400

    plans, errors = _plan_refs(
        refs, scripts_dir,
        include_helpers=data.get('include_helpers', True),
        strip_bootstrap=data.get('strip_bootstrap', True),
    )
    units = _dedupe_units(plans)
    preview = [{
        'name': u.vs_name, 'folder': u.folder, 'disk_ref': u.disk_ref,
        'libs': u.libs, 'has_doc': bool(u.doc), 'is_helper': u.is_helper,
        'warnings': u.warnings,
    } for u in units]

    if errors:
        return jsonify({'success': False, 'error': 'conversion_failed',
                        'requested': refs, 'errors': errors, 'units': preview}), 400

    for unit in units:
        validation = validate_virtual_script(unit.source)
        if not validation.get('valid'):
            return jsonify({'success': False, 'error': 'syntax_error',
                            'script_name': unit.disk_ref,
                            'validation': validation}), 400

    blocked = _warning_block(units, data.get('allow_warnings', False))
    if blocked:
        return blocked

    if data.get('dry_run'):
        return jsonify({'success': True, 'dry_run': True,
                        'requested': refs, 'units': preview, 'errors': []})

    created_by = data.get('created_by') or request.headers.get('X-User-ID')
    written, failed_unit = _write_units(units, team_id, created_by)
    if written is None:
        return jsonify({'success': False,
                        'error': f"Convert failed while writing '{failed_unit.vs_name}'"}), 500

    _invalidate_lists()
    return jsonify({'success': True, 'requested': refs,
                    'units': written, 'errors': []})
