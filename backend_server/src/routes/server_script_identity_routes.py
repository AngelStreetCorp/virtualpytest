"""
Server routes for executable identity — the TCnnn prefix and display name shown
for a script, testcase or virtual script.

Source of truth is the executable_identity table, edited from the Test Cases
page. Replaces hand-editing test_scripts/script_identity_map.json (and its
frontend/public/data/ twin) — see BUG-0066 and
setup/db/schema/047_executable_identity.sql.
"""

from flask import Blueprint, jsonify, request

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.executable_identity_db import (
    VALID_KINDS,
    delete_executable_identity,
    find_prefix_conflict,
    list_executable_identities,
    upsert_executable_identity,
)
from shared.src.lib.utils.script_identity_utils import normalize_script_ref

server_script_identity_bp = Blueprint(
    'server_script_identity',
    __name__,
    url_prefix='/server/script-identity',
)


def _team_id() -> str:
    """team_id comes as a query arg on every call (buildServerUrl appends it),
    with the JSON body as a secondary source for non-browser callers."""
    from_args = request.args.get('team_id')
    if from_args:
        return from_args
    data = request.get_json(silent=True) or {}
    return data.get('team_id') or ''


def _validated_kind(raw_kind):
    """Return (kind, error_response). kind defaults to 'script'."""
    kind = (raw_kind or 'script').strip().lower()
    if kind not in VALID_KINDS:
        return None, (jsonify({
            'success': False,
            'error': f'kind must be one of {sorted(VALID_KINDS)}',
        }), 400)
    return kind, None


@server_script_identity_bp.route('/list', methods=['GET'])
@handle_route_exceptions('script_identity:list')
def list_script_identity():
    team_id = _team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    kind, error = _validated_kind(request.args.get('kind'))
    if error:
        return error

    items = list_executable_identities(team_id, kind)
    return jsonify({
        'success': True,
        'kind': kind,
        'items': [{
            'script_ref': item.get('script_ref'),
            'prefix': item.get('prefix'),
            'display_name': item.get('display_name'),
            'updated_at': item.get('updated_at'),
        } for item in items],
        'count': len(items),
    })


@server_script_identity_bp.route('/set', methods=['POST'])
@handle_route_exceptions('script_identity:set')
def set_script_identity():
    """Upsert prefix / display_name for one script_ref.

    Clearing both fields removes the row (see upsert_executable_identity), which
    is what the popover's Clear button sends. A duplicate prefix is reported as
    a non-blocking `warning`, never rejected.
    """
    team_id = _team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    data = request.get_json() or {}
    kind, error = _validated_kind(data.get('kind'))
    if error:
        return error

    script_ref = normalize_script_ref(data.get('script_ref'))
    if not script_ref:
        return jsonify({'success': False, 'error': 'script_ref is required'}), 400

    prefix = (data.get('prefix') or '').strip() or None
    display_name = (data.get('display_name') or '').strip() or None

    warning = None
    if prefix:
        conflict = find_prefix_conflict(team_id, prefix, script_ref, kind)
        if conflict:
            warning = f"Prefix {prefix} is already used by '{conflict}'"

    row = upsert_executable_identity(
        team_id=team_id,
        script_ref=script_ref,
        prefix=prefix,
        display_name=display_name,
        kind=kind,
        updated_by=data.get('updated_by') or request.headers.get('X-User-ID'),
    )

    # row is None both on failure and after a deliberate clear-both delete.
    if row is None and (prefix or display_name):
        return jsonify({'success': False, 'error': 'Failed to save identity'}), 500

    return jsonify({
        'success': True,
        'item': {
            'script_ref': script_ref,
            'prefix': prefix,
            'display_name': display_name,
        },
        'cleared': row is None,
        'warning': warning,
    })


@server_script_identity_bp.route('/clear', methods=['POST'])
@handle_route_exceptions('script_identity:clear')
def clear_script_identity():
    team_id = _team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    data = request.get_json() or {}
    kind, error = _validated_kind(data.get('kind'))
    if error:
        return error

    script_ref = normalize_script_ref(data.get('script_ref'))
    if not script_ref:
        return jsonify({'success': False, 'error': 'script_ref is required'}), 400

    if not delete_executable_identity(team_id, script_ref, kind):
        return jsonify({'success': False, 'error': 'Failed to clear identity'}), 500

    return jsonify({'success': True})


@server_script_identity_bp.route('/import', methods=['POST'])
@handle_route_exceptions('script_identity:import')
def import_script_identity():
    """Bulk-load a script_identity_map.json `scripts` object.

    Existing rows are skipped unless `overwrite` is set, so re-running is safe.
    Individual failures are collected rather than aborting the batch — a partial
    import is more useful than none, and the response says exactly what landed.
    """
    team_id = _team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    data = request.get_json() or {}
    kind, error = _validated_kind(data.get('kind'))
    if error:
        return error

    entries = data.get('scripts')
    if not isinstance(entries, dict):
        return jsonify({'success': False, 'error': 'scripts must be an object'}), 400

    overwrite = bool(data.get('overwrite'))
    existing = {row.get('script_ref') for row in list_executable_identities(team_id, kind)}

    imported, skipped, failed, conflicts = 0, 0, [], []

    for raw_ref, entry in entries.items():
        script_ref = normalize_script_ref(raw_ref)
        if not script_ref or not isinstance(entry, dict):
            failed.append({'script_ref': raw_ref, 'error': 'invalid entry'})
            continue

        if script_ref in existing and not overwrite:
            skipped += 1
            continue

        prefix = (entry.get('prefix') or '').strip() or None
        display_name = (entry.get('display_name') or '').strip() or None
        if not prefix and not display_name:
            skipped += 1
            continue

        if prefix:
            conflict = find_prefix_conflict(team_id, prefix, script_ref, kind)
            if conflict:
                conflicts.append({'script_ref': script_ref, 'prefix': prefix, 'used_by': conflict})

        row = upsert_executable_identity(
            team_id=team_id, script_ref=script_ref, prefix=prefix,
            display_name=display_name, kind=kind,
            updated_by=data.get('updated_by') or 'identity-map-import',
        )
        if row is None:
            failed.append({'script_ref': script_ref, 'error': 'write failed'})
        else:
            imported += 1

    return jsonify({
        'success': not failed,
        'imported': imported,
        'skipped': skipped,
        'failed': failed,
        'conflicts': conflicts,
    })
