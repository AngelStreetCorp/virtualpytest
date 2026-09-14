"""
AI User Interface Routes (DB-backed agent knowledge base)

HTTP wrapper around shared.src.lib.database.ai_userinterface_db.
See docs/agent/navigation/AI_USERINTERFACE.md for the agent workflow this exposes.

Convention: every endpoint takes team_id as a query string OR JSON field;
write endpoints additionally require an `actor` field (audit trail). Schema
constraints (verified_against NOT NULL, category-required fields) are
enforced by the lib and surfaced as 400s.
"""

from flask import Blueprint, jsonify, request

from shared.src.lib.database.ai_userinterface_db import (
    list_ai_userinterfaces,
    get_ai_userinterface,
    resolve_ai_userinterface_verbose,
    get_ai_userinterface_history,
    create_ai_userinterface,
    update_ai_userinterface,
    revert_ai_userinterface,
    add_ai_userinterface_screen,
    add_ai_userinterface_transition,
    add_ai_userinterface_verification,
    add_ai_userinterface_task,
    add_ai_userinterface_quirk,
    add_ai_userinterface_known_hardware,
    add_ai_userinterface_fingerprint,
    supersede_ai_userinterface_row,
)
from shared.src.lib.utils.app_utils import check_supabase

server_ai_userinterface_bp = Blueprint(
    'server_ai_userinterface', __name__, url_prefix='/server/ai_userinterface'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _team_from_request(payload: dict = None) -> str:
    return (
        request.args.get('team_id')
        or (payload or {}).get('team_id')
        or ''
    )


def _bad_request(msg: str):
    return jsonify({'success': False, 'error': msg}), 400


def _server_error(msg: str):
    return jsonify({'success': False, 'error': msg}), 500


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

@server_ai_userinterface_bp.route('/list', methods=['GET'])
def list_route():
    err = check_supabase()
    if err:
        return err
    team_id = _team_from_request()
    if not team_id:
        return _bad_request('team_id required')
    rows = list_ai_userinterfaces(team_id, request.args.get('category'))
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


@server_ai_userinterface_bp.route('/get/<ui_id>', methods=['GET'])
def get_route(ui_id):
    err = check_supabase()
    if err:
        return err
    team_id = _team_from_request()
    if not team_id:
        return _bad_request('team_id required')
    include_superseded = request.args.get('include_superseded', 'false').lower() == 'true'
    variant_id = request.args.get('variant_id') or None
    bundle = get_ai_userinterface(
        ui_id, team_id,
        include_superseded=include_superseded,
        variant_id=variant_id,
    )
    if bundle is None:
        return jsonify({'success': False, 'error': f'ui_id {ui_id!r} not found'}), 404
    return jsonify({'success': True, 'bundle': bundle})


@server_ai_userinterface_bp.route('/resolve', methods=['POST'])
def resolve_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    team_id = _team_from_request(payload)
    fingerprint_type = payload.get('fingerprint_type')
    value = payload.get('value')
    if not (team_id and fingerprint_type and value):
        return _bad_request('team_id, fingerprint_type, value required')
    res = resolve_ai_userinterface_verbose(team_id, fingerprint_type, value)
    parent = res['matched']
    if parent is None:
        # near_misses: up to 3 closest registered patterns so the caller can
        # see WHY nothing matched (see resolve_ai_userinterface_verbose).
        return jsonify({'success': True, 'matched': False, 'parent': None,
                        'near_misses': res['near_misses']})
    return jsonify({'success': True, 'matched': True, 'parent': parent})


@server_ai_userinterface_bp.route('/history/<ai_userinterface_id>', methods=['GET'])
def history_route(ai_userinterface_id):
    err = check_supabase()
    if err:
        return err
    team_id = _team_from_request()
    if not team_id:
        return _bad_request('team_id required')
    rows = get_ai_userinterface_history(ai_userinterface_id, team_id)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


# ---------------------------------------------------------------------------
# PARENT CRUD
# ---------------------------------------------------------------------------

@server_ai_userinterface_bp.route('/create', methods=['POST'])
def create_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    team_id = _team_from_request(payload)
    actor = payload.get('actor')
    data = payload.get('data')
    if not (team_id and actor and isinstance(data, dict)):
        return _bad_request('team_id, actor, data (dict) required')
    try:
        parent = create_ai_userinterface(data, team_id, actor)
    except ValueError as e:
        return _bad_request(str(e))
    if parent is None:
        return _server_error('create_ai_userinterface returned None')
    return jsonify({'success': True, 'parent': parent}), 201


@server_ai_userinterface_bp.route('/update/<ui_id>', methods=['POST'])
def update_route(ui_id):
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    team_id = _team_from_request(payload)
    actor = payload.get('actor')
    fields = payload.get('fields') or {}
    changes_summary = payload.get('changes_summary')
    if not (team_id and actor and changes_summary):
        return _bad_request('team_id, actor, changes_summary required')
    if not isinstance(fields, dict) or not fields:
        return _bad_request('fields (non-empty dict) required')
    try:
        parent = update_ai_userinterface(ui_id, fields, team_id, actor, changes_summary)
    except ValueError as e:
        return _bad_request(str(e))
    if parent is None:
        return jsonify({'success': False, 'error': f'ui_id {ui_id!r} not found'}), 404
    return jsonify({'success': True, 'parent': parent})


@server_ai_userinterface_bp.route('/revert/<ui_id>', methods=['POST'])
def revert_route(ui_id):
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    team_id = _team_from_request(payload)
    actor = payload.get('actor')
    to_version = payload.get('to_version')
    reason = payload.get('reason')
    if not (team_id and actor and reason):
        return _bad_request('team_id, actor, reason required')
    if not isinstance(to_version, int) or to_version < 1:
        return _bad_request('to_version (positive int) required')
    try:
        parent = revert_ai_userinterface(ui_id, to_version, team_id, actor, reason)
    except ValueError as e:
        return _bad_request(str(e))
    if parent is None:
        return jsonify({'success': False, 'error': f'no history v{to_version} for {ui_id!r}'}), 404
    return jsonify({'success': True, 'parent': parent})


# ---------------------------------------------------------------------------
# APPEND (sub-rows)
# ---------------------------------------------------------------------------

def _append_helper(adder, payload, required_keys):
    team_id = _team_from_request(payload)
    actor = payload.get('actor')
    if not (team_id and actor):
        return _bad_request('team_id, actor required')
    missing = [k for k in required_keys if not payload.get(k)]
    if missing:
        return _bad_request(f'missing fields: {missing}')
    try:
        kwargs = {k: payload.get(k) for k in required_keys if payload.get(k) is not None}
        kwargs['team_id'] = team_id
        kwargs['added_by'] = actor
        # Allow optional keys to flow through (union across all adders)
        for opt in ('identifying_cues', 'exits', 'from_screen', 'to_screen',
                    'hw_rev', 'verified_at',
                    # transitions
                    'verification_status',
                    # verifications
                    'expected', 'severity',
                    # tasks
                    'description', 'verify_assertions', 'returns'):
            if opt in payload and opt not in kwargs:
                kwargs[opt] = payload[opt]
        row = adder(**kwargs)
    except ValueError as e:
        return _bad_request(str(e))
    if row is None:
        return _server_error('insert returned None')
    return jsonify({'success': True, 'row': row}), 201


@server_ai_userinterface_bp.route('/screen/add', methods=['POST'])
def add_screen_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_screen, payload,
        required_keys=['ui_id', 'name', 'verified_against'],
    )


@server_ai_userinterface_bp.route('/transition/add', methods=['POST'])
def add_transition_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_transition, payload,
        required_keys=['ui_id', 'from_screen', 'item_label', 'actions'],
    )


@server_ai_userinterface_bp.route('/verification/add', methods=['POST'])
def add_verification_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_verification, payload,
        required_keys=['ui_id', 'screen_name', 'kind', 'selector'],
    )


@server_ai_userinterface_bp.route('/task/add', methods=['POST'])
def add_task_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_task, payload,
        required_keys=['ui_id', 'task_name', 'steps_md'],
    )


@server_ai_userinterface_bp.route('/quirk/add', methods=['POST'])
def add_quirk_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_quirk, payload,
        required_keys=['ui_id', 'description', 'verified_against'],
    )


@server_ai_userinterface_bp.route('/hardware/add', methods=['POST'])
def add_hardware_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_known_hardware, payload,
        required_keys=['ui_id', 'model', 'verified_at'],
    )


@server_ai_userinterface_bp.route('/fingerprint/add', methods=['POST'])
def add_fingerprint_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    return _append_helper(
        add_ai_userinterface_fingerprint, payload,
        required_keys=['ui_id', 'fingerprint_type', 'pattern', 'verified_against'],
    )


# ---------------------------------------------------------------------------
# SOFT-DELETE
# ---------------------------------------------------------------------------

@server_ai_userinterface_bp.route('/supersede', methods=['POST'])
def supersede_route():
    err = check_supabase()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    team_id = _team_from_request(payload)
    actor = payload.get('actor')
    table_short = payload.get('table_short')
    row_id = payload.get('row_id')
    reason = payload.get('reason')
    if not (team_id and actor and table_short and row_id and reason):
        return _bad_request('team_id, actor, table_short, row_id, reason required')
    try:
        ok = supersede_ai_userinterface_row(table_short, row_id, team_id, actor, reason)
    except ValueError as e:
        return _bad_request(str(e))
    if not ok:
        return jsonify({'success': False, 'error': f'no row {row_id!r} in {table_short!r}'}), 404
    return jsonify({'success': True})
