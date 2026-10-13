"""
Agent Activity Routes (TASK-54) — what each AI agent really did.

All under /server/agents, next to agent_registry_routes. Specific paths (/overview, /usage, /feedback,
/<id>/logs, /<id>/turns/<session>) are registered as static or longer rules, so Werkzeug picks them
before the registry's catch-all GET /<agent_id>.

Read-only except POST /feedback. Pure SQL reads, zero LLM calls. Error text reaches admins only.
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

from agent.activity import service
from agent.activity.rows import LEVELS
from agent.activity.sources import AGENT_SOURCES, OTHER
from backend_server.src.lib.auth_middleware import require_permission, require_role, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database import agent_activity_db
from shared.src.lib.utils.app_utils import get_team_id

logger = logging.getLogger(__name__)

server_agent_activity_bp = Blueprint('server_agent_activity', __name__, url_prefix='/server/agents')


def _is_admin() -> bool:
    return getattr(request, 'user_role', None) == 'admin'


def _host_names():
    """Hosts registered on this server (alerts has no team_id: scoped by host)."""
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        return list(get_host_manager().get_all_hosts().keys())
    except Exception as e:
        logger.warning('agent activity: host list unavailable: %s', e)
        return []


def _int_arg(name: str, default: int, low: int, high: int) -> int:
    raw = request.args.get(name)
    if raw in (None, ''):
        return default
    value = int(raw)  # ValueError -> 400 below
    return max(low, min(high, value))


def _bad(message: str):
    return jsonify({'success': False, 'error': message}), 400


def _failed(label: str, exc: Exception):
    logger.error('agent activity %s failed: %s', label, exc, exc_info=True)
    return jsonify({'success': False, 'error': str(exc) if _is_admin() else 'Agent activity is unavailable'}), 500


@server_agent_activity_bp.route('/overview', methods=['GET'])
@require_user_auth
@require_permission('ai_agent:view')
def overview():
    """GET /server/agents/overview?hours=24"""
    try:
        hours = _int_arg('hours', 24, 1, 720)
    except ValueError:
        return _bad('hours must be an integer')
    team_id = get_team_id()
    if not team_id:
        return _bad('team_id is required')
    try:
        return jsonify(service.get_overview(team_id, hours, _is_admin(), _host_names())), 200
    except Exception as e:
        return _failed('overview', e)


@server_agent_activity_bp.route('/usage', methods=['GET'])
@require_user_auth
@require_role('admin')
def usage():
    """GET /server/agents/usage?days=7 (admin): tokens per agent per day, per usage key, decision quality."""
    try:
        days = _int_arg('days', 7, 1, 30)
    except ValueError:
        return _bad('days must be an integer')
    team_id = get_team_id()
    if not team_id:
        return _bad('team_id is required')
    try:
        return jsonify(service.get_usage(team_id, days)), 200
    except Exception as e:
        return _failed('usage', e)


def _parse_before(raw):
    if not raw:
        return None
    datetime.fromisoformat(raw.replace(' ', '+').replace('Z', '+00:00'))  # ValueError -> 400
    return raw.replace(' ', '+')


@server_agent_activity_bp.route('/<agent_id>/logs', methods=['GET'])
@require_user_auth
@require_permission('ai_agent:view')
def agent_logs(agent_id: str):
    """GET /server/agents/<id>/logs?part=&level=&hours=24&q=&limit=50&before=<ISO>"""
    if agent_id not in AGENT_SOURCES:
        return jsonify({'success': False, 'error': f'Unknown agent: {agent_id}'}), 404
    if AGENT_SOURCES[agent_id].get('admin_only') and not _is_admin():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    part = request.args.get('part') or None
    level = request.args.get('level') or None
    if part and part not in {p['key'] for p in AGENT_SOURCES[agent_id]['parts']}:
        return _bad('unknown part')
    if level and level not in LEVELS:
        return _bad('level must be one of ' + ', '.join(LEVELS))
    try:
        hours = _int_arg('hours', 24, 1, 720)
        limit = _int_arg('limit', 50, 1, agent_activity_db.MAX_LIMIT)
        before = _parse_before(request.args.get('before'))
    except ValueError:
        return _bad('hours and limit must be integers and before an ISO timestamp')
    team_id = get_team_id()
    if not team_id:
        return _bad('team_id is required')
    try:
        return jsonify(service.get_logs(
            agent_id, team_id, part=part, level=level, hours=hours, q=(request.args.get('q') or '').strip() or None,
            limit=limit, before=before, is_admin=_is_admin(), host_names=_host_names())), 200
    except Exception as e:
        return _failed('logs', e)


@server_agent_activity_bp.route('/<agent_id>/turns/<session_id>', methods=['GET'])
@require_user_auth
@require_permission('ai_agent:view')
def agent_turns(agent_id: str, session_id: str):
    """GET /server/agents/<id>/turns/<session_id> — the stored transcript of one chat session."""
    spec = AGENT_SOURCES.get(agent_id)
    if not spec or not spec.get('registry_id'):
        return jsonify({'success': False, 'error': f'Unknown agent: {agent_id}'}), 404
    team_id = get_team_id()
    if not team_id:
        return _bad('team_id is required')
    try:
        return jsonify(service.get_turns(agent_id, team_id, session_id)), 200
    except Exception as e:
        return _failed('turns', e)


@server_agent_activity_bp.route('/feedback', methods=['POST'])
@require_user_auth
@require_permission('ai_agent:use')
def submit_feedback():
    """POST /server/agents/feedback {agent_id, rating 1-5 | thumbs 'up'|'down', comment?, task_description?, session_id?, task_id?, message_id?}

    Same body the chat used for the removed /server/benchmarks/feedback. Stored in agent_feedback
    (thumbs up = 5, down = 1). When a message reference (``message_id`` and/or ``session_id``/
    ``task_id``) is present, the route ALWAYS looks up the latest row whose ``comment`` ends
    with the bracketed ``[ref]`` stamp and updates it — rating on a bare re-thumb, comment when
    one is sent (the existing comment text is kept when a bare thumb is re-clicked). One row per
    chat message: a new insert only happens when no row matches yet.
    """
    data = request.get_json(silent=True) or {}
    agent_id = data.get('agent_id')
    rating = service.thumbs_to_rating(data.get('rating', data.get('thumbs')))
    if not agent_id or rating is None:
        return _bad('agent_id and rating (1-5) or thumbs (up/down) required')
    team_id = get_team_id()
    if not team_id:
        return _bad('team_id is required')
    version = data.get('version') or 'unknown'
    try:
        from agent.registry import get_agent_registry
        agent = get_agent_registry().get(agent_id)
        if agent:
            version = agent.metadata.version
    except Exception:
        pass
    note = data.get('task_description')
    user_comment = data.get('comment') or None
    # Build the message reference stamp (session_id / task_id / message_id) used to dedupe one
    # row per chat message when the user later sends a comment or re-clicks a thumb.
    ref_parts = []
    if data.get('message_id'):
        ref_parts.append(f"msg_id={data['message_id']}")
    for key in ('session_id', 'task_id'):
        if data.get(key):
            ref_parts.append(f'{key}={data[key]}')
    ref = ' '.join(ref_parts)
    user_id = getattr(request, 'user_id', None) if _is_uuid(getattr(request, 'user_id', None)) else None
    agent_id_short = str(agent_id)[:100]

    # If we have a message ref, the row already exists for this chat message — update it
    # (rating; the new comment when one is sent, the previous one otherwise). Insert only when
    # no row matches.
    feedback_id = None
    if ref:
        existing_id = agent_activity_db.find_latest_feedback_by_ref(team_id, agent_id_short, ref)
        if existing_id:
            if user_comment:
                stored_comment = f"{str(user_comment)[:2000 - len(ref) - 4]} [{ref}]"
            else:
                # Bare thumb re-click: keep the existing comment, just bump the rating.
                stored_comment = None  # signals update_feedback_comment to leave comment alone
            if agent_activity_db.update_feedback_comment(
                    existing_id, team_id, agent_id_short,
                    comment=stored_comment if stored_comment is not None else '__keep_existing__',
                    rating=rating,
                    keep_existing_comment=stored_comment is None):
                feedback_id = existing_id
    if not feedback_id:
        stored_comment = (str(user_comment) if user_comment else '')
        if ref:
            stored_comment = f"{stored_comment} [{ref}]" if stored_comment else f"[{ref}]"
        try:
            feedback_id = agent_activity_db.insert_feedback(
                team_id, agent_id_short, str(version)[:20], rating,
                comment=(stored_comment or None) and str(stored_comment)[:2000],
                task_description=(note or None) and str(note)[:2000],
                user_id=user_id)
        except Exception as e:
            return _failed('feedback', e)
    if not feedback_id:
        return jsonify({'success': False, 'error': 'Failed to submit feedback'}), 500
    return jsonify({'feedback_id': feedback_id, 'message': 'Feedback submitted successfully'}), 201


def _is_uuid(value) -> bool:
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False
