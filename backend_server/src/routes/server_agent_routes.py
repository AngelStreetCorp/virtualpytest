"""
Server Agent Routes - AI Agent Chat System

REST endpoints for session management.
SocketIO handlers for real-time chat with QA Manager and specialist agents.
"""

import os
import logging
import re
import asyncio
import json
import uuid
from datetime import datetime, timezone

import time

import requests
from flask import Blueprint, request, jsonify
from backend_server.src.lib import socket_auth
from backend_server.src.lib.auth_middleware import authorize_socket_connection, require_platform_admin
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

logger = logging.getLogger(__name__)

# =============================================================================
# Execution History Logging
# =============================================================================
def log_execution_history(
    agent_id: str,
    version: str,
    team_id: str,
    task_id: str,
    started_at: datetime,
    completed_at: datetime,
    status: str,
    tool_calls: int = 0,
    error_message: str = None,
    metadata: dict = None,
    token_usage: int = None
):
    """
    Log agent execution to agent_execution_history table for score tracking.
    This enables success_rate calculations in the leaderboard.
    """
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        if not supabase:
            logger.warning("Supabase not available for execution logging")
            return None
        
        duration_seconds = (completed_at - started_at).total_seconds()
        
        data = {
            'instance_id': f'chat-{task_id[:8]}',
            'agent_id': agent_id,
            'version': version,
            'task_id': task_id,
            'event_type': 'chat_task',
            'started_at': started_at.isoformat(),
            'completed_at': completed_at.isoformat(),
            'duration_seconds': duration_seconds,
            'status': status,
            'tool_calls': tool_calls,
            'error_message': error_message,
            'team_id': team_id or 'default',
            'metadata': metadata or {}
        }
        if token_usage:
            data['token_usage'] = int(token_usage)
        
        result = supabase.table('agent_execution_history').insert(data).execute()
        if result.data:
            logger.info(f"✅ Logged execution: {agent_id} - {status} ({duration_seconds:.2f}s)")
            return result.data[0]['id']
        return None
    except Exception as e:
        logger.error(f"Failed to log execution history: {e}")
        return None

# Slack integration hook
try:
    from integrations.agent_slack_hook import on_agent_message_websocket, on_user_message_websocket
    SLACK_HOOK_AVAILABLE = True
except ImportError:
    SLACK_HOOK_AVAILABLE = False
    logger.info("Slack hook not available")

# =============================================================================
# Agent Conversation Logger - Separate file for debugging
# =============================================================================
AGENT_LOG_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'agent_conversations.log')

def ensure_log_dir():
    """Ensure log directory exists"""
    log_dir = os.path.dirname(AGENT_LOG_FILE)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

def log_agent_event(event_type: str, session_id: str, data: dict):
    """
    Log agent conversation events to dedicated file for debugging
    
    Args:
        event_type: Type of event (USER_MESSAGE, AGENT_EVENT, TOOL_CALL, ERROR, etc.)
        session_id: Session ID
        data: Event data
    """
    ensure_log_dir()
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "event_type": event_type,
        "session_id": session_id,
        "data": data
    }
    
    try:
        with open(AGENT_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry, default=str) + '\n')
    except Exception as e:
        logger.error(f"Failed to write agent log: {e}")

# Blueprint for REST endpoints
server_agent_bp = Blueprint('server_agent', __name__, url_prefix='/server/agent')

# One agent conversation processes at a time per worker — and, since 2026-10-04, one asyncio
# loop of any kind (Test Prompt runs, the background queue, route helpers): see
# agent/async_utils.run_in_worker_loop. Parallel conversations are accepted and answered in turn.
from agent.async_utils import run_in_worker_loop
from agent.registry import get_agent_registry


def run_agent_coroutine(coro_factory, socketio=None, session_id=None):
    """Run an agent coroutine under the per-worker processing lock.

    This runs in a detached background greenlet, so anything raised here is
    only printed by gevent: the conversation never receives its error or
    session_ended event and the chat sits on its 'Received...' ack until the
    frontend's stall timeout. asyncio.run() itself raises whenever another
    greenlet in this worker holds a live event loop (one OS thread, so the
    running-loop flag is shared), which is exactly how a chat goes silent.
    Close the turn on the session room whatever happens.
    """
    coro = coro_factory()
    try:
        # Tell the conversation it is queued rather than leaving it on the bare
        # 'Received...' ack: with one worker, a long-running conversation (or a
        # runaway one — see the 26-minute session 39d2c4e2 on 2026-09-27) makes
        # every other chat look dead for minutes, and the user has no way to tell
        # "waiting" from "broken".
        def tell_queued() -> None:
            if socketio is not None and session_id is not None:
                socketio.emit('agent_event', {
                    'type': 'thinking',
                    'agent': 'System',
                    'content': 'Waiting for another conversation to finish...',
                    'timestamp': datetime.now().isoformat(),
                    'session_id': session_id,
                }, room=session_id, namespace='/agent')

        run_in_worker_loop(coro, on_wait=tell_queued)
    except Exception as e:
        logger.error(f"Agent background task crashed: {e}", exc_info=True)
        coro.close()  # nothing awaited it — silences "never awaited"
        if socketio is None or session_id is None:
            return
        timestamp = datetime.now().isoformat()
        for event_type, content in (
            ('error', f'Agent task failed to start: {e}'),
            ('session_ended', 'Session ended'),
        ):
            socketio.emit('agent_event', {
                'type': event_type,
                'agent': 'System',
                'content': content,
                'timestamp': timestamp,
                'session_id': session_id,
            }, room=session_id, namespace='/agent')

# Lazy imports to avoid circular dependencies
_manager = None
_session_manager = None

def get_manager(team_id: str = None, agent_id: str = None, session=None):
    """
    Get or create QA Manager instance (lazy load)

    Args:
        team_id: Team/user identifier for API key retrieval
        agent_id: Selected agent ID (e.g., 'qa-web-manager', 'qa-mobile-manager')
        session: Session object for caching

    Returns:
        QAManagerAgent instance configured for the selected agent
    """
    # Always create a new manager with the team_id to ensure correct API key
    # (In-memory storage means we can't cache the manager globally)
    from agent.core.manager import QAManagerAgent
    logger.info(f"Initializing QA Manager agent for team: {team_id or 'default'}, agent: {agent_id or 'assistant'}...")
    return QAManagerAgent(user_identifier=team_id, agent_id=agent_id, session=session)


def get_session_manager():
    """Get or create Session Manager instance (lazy load)"""
    global _session_manager
    if _session_manager is None:
        from agent.core.session import SessionManager
        _session_manager = SessionManager()
    return _session_manager


# =============================================================================
# REST Endpoints
# =============================================================================

@server_agent_bp.route('/health', methods=['GET'])
@handle_route_exceptions('server_agent:health')
def health_check():
    """Health check - the model that serves the selected agent for this team (TASK-30 routing)."""
    team_id = request.args.get('team_id')
    agent_id = request.args.get('agent_id')
    from agent.core.manager import QAManagerAgent

    settings = QAManagerAgent(user_identifier=team_id, agent_id=agent_id).ai_settings
    return jsonify({
        "success": True,
        "status": "healthy",
        "usage": settings.get("usage"),
        "api_key_configured": settings["api_key_configured"],
        "provider": settings.get("provider"),
        "model": settings.get("model"),
        "profile": settings.get("profile"),
        "endpoint": settings.get("endpoint"),
        "supports_prompt_caching": settings.get("supports_prompt_caching", False),
        "error": settings.get("error"),
        "manager_initialized": _manager is not None,
    })


@server_agent_bp.route('/api-key', methods=['POST'])
@handle_route_exceptions('server_agent:save_api_key')
@require_platform_admin
def save_api_key():
    """
    Save the API key of the endpoint serving an agent (server default), after a live check.

    Body: { "api_key": "...", "agent_id": "assistant" }
    The key goes to the server-side secrets store under the endpoint's secret name.
    """
    data = request.get_json() or {}
    api_key = (data.get('api_key') or '').strip()
    if not api_key:
        return jsonify({"success": False, "error": "API key required"}), 400

    from agent.core.manager import QAManagerAgent
    from shared.src.lib.ai import router as ai_router, secrets_store
    from shared.src.lib.ai.provider_client import classify_error, connectivity_response, create_client, response_usage
    from shared.src.lib.database import ai_routing_db

    manager = QAManagerAgent(agent_id=data.get('agent_id'))
    try:
        hop = ai_router.resolve(manager.usage_key).primary
    except Exception as e:
        return jsonify({"success": False, "error": f"No AI route for this agent: {e}"}), 400

    # The check is a real (tiny) completion: it is counted like a Settings Test call (test:text).
    test_resolution = ai_router.test_resolution(hop, 'text')
    started = time.time()
    try:
        used = response_usage(connectivity_response(
            create_client(hop.preset, api_key, base_url=hop.endpoint.get('base_url'), timeout=hop.timeout), hop.model))
        ai_router.record(test_resolution, hop, ok=True, ms=int((time.time() - started) * 1000),
                         tokens_in=used.tokens_in, tokens_out=used.tokens_out, usage=used)
    except Exception as e:
        ai_router.record(test_resolution, hop, ok=False, ms=int((time.time() - started) * 1000),
                         error_type=classify_error(e))
        if isinstance(e, requests.HTTPError):
            status_code = e.response.status_code if e.response is not None else 500
            return jsonify({
                "success": False,
                "error": f"Validation failed for {hop.endpoint_name}: {e.response.text[:300] if e.response is not None else str(e)}"
            }), 401 if status_code in (401, 403) else status_code
        logger.error(f"API key validation error: {e}")
        return jsonify({"success": False, "error": f"Validation error: {str(e)}"}), 500

    secret_name = hop.endpoint.get('secret_name') or hop.endpoint_name
    secrets_store.set_secret(secret_name, api_key)
    if not hop.endpoint.get('secret_name'):
        ai_routing_db.update_row('ai_endpoints', hop.endpoint['id'], {'secret_name': secret_name})
    ai_router.invalidate()
    return jsonify({
        "success": True,
        "message": "API key validated and saved",
        "endpoint": hop.endpoint_name,
        "provider": hop.preset,
        "model": hop.model,
    })


@server_agent_bp.route('/sessions', methods=['POST'])
@handle_route_exceptions('server_agent:create_session')
def create_session():
    """Create a new chat session.

    The caller is recorded as the owner so the socket handlers can tell whose conversation a
    session_id names. Sessions are in-memory, so anything created before this — or on a
    deployment with a shared principal, where every caller is the same 'user' — has no owner
    and stays usable by any authenticated caller (see _may_use_session).
    """
    session_mgr = get_session_manager()
    session = session_mgr.create_session()
    owner = getattr(request, 'user_id', None)
    if owner and owner not in SHARED_PRINCIPAL_IDS:
        session.set_context(SESSION_OWNER_KEY, owner)
    
    return jsonify({
        "success": True,
        "session": session.to_dict(),
    })


def _drone_voice_outcome(data: dict):
    """TASK-160: a spoken Tello command, with a Tello held in Take Control, goes to the drone executor (same safety
    checks as the push-to-talk button), not to the model. None = not a drone phrase: the normal voice path runs."""
    text = str(data.get('text') or '').strip()
    host_name, device_id = str(data.get('host_name') or ''), str(data.get('device_id') or '')
    if not (text and host_name and device_id):
        return None
    from backend_server.src.lib.utils import drone_voice
    from backend_server.src.lib.utils.lock_utils import resolve_lock_owner
    from backend_server.src.lib.utils.server_utils import get_host_manager
    from backend_server.src.routes.server_drone_routes import _voice
    from shared.src.lib.drone.voice_grammar import parse
    host_info = get_host_manager().get_host(host_name)
    devices = [{'device_id': d.get('device_id'), 'device_name': d.get('device_name'), 'name': d.get('device_name')}
               for d in ((host_info or {}).get('devices') or []) if str(d.get('device_model') or '').lower() == 'tello']
    if not any(str(d['device_id']) == device_id for d in devices):
        return None
    user_id, user_name = resolve_lock_owner(data)
    executor = _voice()
    ex = executor.settings
    parsed = parse(text, devices, drone_voice.Limits(ex.max_cm, ex.max_deg))
    if not drone_voice.is_drone_phrase(parsed):
        return None
    caller = {'user_id': user_id, 'user_name': user_name,
              'session_ids': [data.get('session_id')] if data.get('session_id') else []}
    out = executor.handle(transcript=text, lang=str(data.get('lang') or 'en')[:2], host_name=host_name,
                          device_id=device_id, devices=devices, caller=caller)
    return {'action': 'drone', 'drone': {k: out.get(k) for k in ('decision', 'reply', 'reason', 'listening')}}


def _voice_caller(data: dict) -> dict:
    from backend_server.src.lib.utils.lock_utils import resolve_lock_owner
    user_id, user_name = resolve_lock_owner(data)
    return {'user_id': user_id, 'user_name': user_name,
            'session_ids': [data.get('session_id')] if data.get('session_id') else []}


def _voice_holds_lock(host_name, device_id, caller):
    from backend_server.src.lib.utils import drone_voice
    from backend_server.src.lib.utils.lock_utils import get_device_lock_info
    return drone_voice.holds_lock(get_device_lock_info(host_name, device_id), caller)


@server_agent_bp.route('/voice/plan', methods=['POST'])
@handle_route_exceptions('server_agent:voice_plan')
def voice_plan():
    """TASK-160 phase 2: one spoken command for the device the caller HOLDS (Take Control) -> a plan to read back.

    Body: {host_name, device_id, text, lang, session_id, model?}. ``decision``: plan (read ``label`` back, then call
    /voice/run with ``plan_id``) | stop | abort | answered | sent (stop / land / battery are final) | refused.
    Nothing here changes the device except the stop / abort / land / hover of a drone."""
    from agent import voice_command as vc
    from agent import voice_device
    from backend_server.src.lib.utils.server_utils import get_host_manager
    from backend_server.src.routes.server_drone_routes import _voice
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    host_name, device_id = str(data.get('host_name') or ''), str(data.get('device_id') or '')
    if not team_id or not host_name or not device_id:
        return jsonify({"success": False, "error": "team_id, host_name and device_id are required"}), 400
    host_info = get_host_manager().get_host(host_name)
    if not host_info:
        return jsonify({"success": False, "error": f'Host "{host_name}" not found'}), 400

    def classify(**kw):
        command = vc.classify(mode='transcript', model_key=str(data.get('model') or 'voxtral'), **kw)
        finish = command.pop('_finish', None)
        if finish:
            finish({"action": "device_action"})
        return command

    out = voice_device.plan(text=str(data.get('text') or '')[:300], lang=str(data.get('lang') or 'en')[:2],
                            host_name=host_name, device_id=device_id, host_info=host_info,
                            caller=_voice_caller(data), team_id=team_id, holds_lock=_voice_holds_lock,
                            drone=_voice(), classify=classify)
    return jsonify(out), 200


@server_agent_bp.route('/voice/run', methods=['POST'])
@handle_route_exceptions('server_agent:voice_run')
def voice_run():
    """Run a plan made by /voice/plan (by id: the client never sends a command). Body: {plan_id, session_id}."""
    from agent import voice_device
    from backend_server.src.lib.utils.server_utils import get_host_manager
    from backend_server.src.routes.server_drone_routes import _voice
    from shared.src.lib.utils.build_url_utils import call_host
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    if not team_id or not data.get('plan_id'):
        return jsonify({"success": False, "error": "team_id and plan_id are required"}), 400

    def execute(host_name, device_id, action, team):
        host_info = get_host_manager().get_host(host_name)
        if not host_info:
            return {"success": False, "error": f'host "{host_name}" not found'}
        payload = {'actions': [{'command': action['command'], 'params': action['params'],
                                'action_type': action['action_type']}],
                   'device_id': device_id, 'team_id': team}
        res, status = call_host(host_info, '/host/action/executeBatch', 'POST', payload,
                                {'device_id': device_id, 'team_id': team}, timeout=30)
        return res if isinstance(res, dict) else {"success": False, "error": f"host answered {status}"}

    out = voice_device.run(plan_id=str(data['plan_id']), caller=_voice_caller(data), team_id=team_id,
                           holds_lock=_voice_holds_lock, drone=_voice(), execute=execute)
    return jsonify(out), 200


@server_agent_bp.route('/voice/command', methods=['POST'])
@handle_route_exceptions('server_agent:voice_command')
def voice_command():
    """Atlas voice fast path (TASK-140): one spoken command → page / take control / goto / stop.

    Body: {mode: 'transcript'|'audio', model: 'voxtral'|'gemini-lite', text?, audio_b64? (16 kHz WAV),
    lang, devices: [{device_name, host_name, device_id, userinterface_name?}], host_name, device_id,
    userinterface_name}. Anything that is not one simple command comes back as action 'atlas' with the
    words, for the normal Atlas turn.
    """
    from agent import voice_command as vc
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    if not team_id:
        return jsonify({"success": False, "error": "team_id required"}), 400
    devices = [d for d in (data.get('devices') or []) if isinstance(d, dict)][:200]
    current = next((str(d.get('device_name')) for d in devices
                    if d.get('host_name') == data.get('host_name') and d.get('device_id') == data.get('device_id')), '')
    drone = _drone_voice_outcome(data)
    if drone is not None:
        return jsonify({"success": True, "command": {"tool": "drone_command"}, "outcome": drone})
    if data.get('abort_only'):          # a spoken stop on a device that is not a drone: no model call, the client aborts
        return jsonify({"success": True, "command": {"tool": "abort"}, "outcome": {"action": "abort"}})
    command = vc.classify(mode=str(data.get('mode') or 'transcript'), model_key=str(data.get('model') or 'voxtral'),
                          lang=str(data.get('lang') or 'en'), devices=devices, current_device=current, team_id=team_id,
                          text=str(data.get('text') or ''), audio_b64=str(data.get('audio_b64') or ''))
    if command.get('error'):
        return jsonify({"success": False, **command}), 200
    finish = command.pop('_finish', None)
    outcome = vc.to_hint(command, devices=devices, host_name=str(data.get('host_name') or ''),
                         device_id=str(data.get('device_id') or ''),
                         userinterface_name=str(data.get('userinterface_name') or ''))
    if outcome.get('action') == 'atlas':
        outcome['text'] = str((command.get('args') or {}).get('text') or data.get('text') or '')
    if finish:
        finish(outcome)
    return jsonify({"success": True, "command": command, "outcome": outcome, "spent_usd": round(vc.spent_usd(), 4),
                    "cap_usd": vc.SPEND_CAP_USD})


@server_agent_bp.route('/voice/speak', methods=['POST'])
@handle_route_exceptions('server_agent:voice_speak')
def voice_speak():
    """Atlas's spoken answer (TASK-140): {text, lang, speed} → audio/mpeg (MiniMax, Trustworth Man)."""
    from flask import Response
    from agent import voice_command as vc
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    if not team_id:
        return jsonify({"success": False, "error": "team_id required"}), 400
    audio, error = vc.speak(text=str(data.get('text') or ''), lang=str(data.get('lang') or 'en'),
                            speed=float(data.get('speed') or 1.2), team_id=team_id)
    if audio is None:
        return jsonify({"success": False, "error": error}), 502
    return Response(audio, mimetype='audio/mpeg', headers={'Cache-Control': 'no-store'})


@server_agent_bp.route('/quick/tools', methods=['GET'])
@handle_route_exceptions('server_agent:quick_tools')
def quick_tools():
    """The caller's Atlas quick tools (TASK-140 Q3): base tools + their most used ones, with the counters."""
    from agent import quick_step
    from shared.src.lib.database import atlas_quick_stats_db as stats_db
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({"success": False, "error": "team_id required"}), 400
    user_id = getattr(request, 'user_id', None) or ''
    tools = quick_step.quick_tools(team_id, user_id, list(quick_step.POOL))
    stats = stats_db.load(team_id, user_id) if user_id else {}
    return jsonify({"success": True, "tools": tools, "base": list(quick_step.BASE),
                    "stats": {t: {k: int(v.get(k) or 0) for k in ('uses', 'hits', 'misses')} for t, v in stats.items()}})


@server_agent_bp.route('/memory', methods=['GET'])
@handle_route_exceptions('server_agent:memory_status')
def memory_status():
    """The caller's Atlas memory (TASK-172): available, switched on, how much is kept."""
    from agent import memory
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({"success": False, "error": "team_id required"}), 400
    return jsonify({"success": True, **memory.status(team_id, getattr(request, 'user_id', None))})


@server_agent_bp.route('/memory', methods=['PUT'])
@handle_route_exceptions('server_agent:memory_toggle')
def memory_toggle():
    """Switch the caller's own memory on or off, on demand. Body: {"enabled": bool}."""
    from agent import memory
    team_id = request.args.get('team_id')
    data = request.get_json(silent=True) or {}
    if not team_id or not isinstance(data.get('enabled'), bool):
        return jsonify({"success": False, "error": "team_id and a boolean enabled are required"}), 400
    user_id = getattr(request, 'user_id', None)
    if memory.user_dir(team_id, user_id) is None or not memory.enabled():
        return jsonify({"success": False, "error": "memory not available for this user", **memory.status(team_id, user_id)}), 409
    if not memory.set_enabled(team_id, user_id, data['enabled']):
        return jsonify({"success": False, "error": "could not save the switch"}), 500
    return jsonify({"success": True, **memory.status(team_id, user_id)})


@server_agent_bp.route('/memory', methods=['DELETE'])
@handle_route_exceptions('server_agent:memory_forget')
def memory_forget():
    """Delete the caller's own memory files. Touches only that user's directory."""
    from agent import memory
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({"success": False, "error": "team_id required"}), 400
    user_id = getattr(request, 'user_id', None)
    removed = memory.forget(team_id, user_id)
    return jsonify({"success": True, "removed": removed, **memory.status(team_id, user_id)})


@server_agent_bp.route('/sessions', methods=['GET'])
@handle_route_exceptions('server_agent:list_sessions')
def list_sessions():
    """List all sessions"""
    session_mgr = get_session_manager()
    sessions = session_mgr.list_sessions()
    
    return jsonify({
        "success": True,
        "sessions": sessions,
    })


@server_agent_bp.route('/sessions/<session_id>', methods=['GET'])
@handle_route_exceptions('server_agent:get_session')
def get_session(session_id: str):
    """Get a specific session"""
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    
    if not session:
        return jsonify({
            "success": False,
            "error": "Session not found",
        }), 404
    
    return jsonify({
        "success": True,
        "session": session.to_dict(),
        "messages": session.messages,
    })


@server_agent_bp.route('/sessions/<session_id>', methods=['DELETE'])
@handle_route_exceptions('server_agent:delete_session')
def delete_session(session_id: str):
    """Delete a session"""
    session_mgr = get_session_manager()
    deleted = session_mgr.delete_session(session_id)
    
    return jsonify({
        "success": deleted,
    })


@server_agent_bp.route('/sessions/<session_id>/approve', methods=['POST'])
@handle_route_exceptions('server_agent:approve_action')
def approve_action(session_id: str):
    """
    Approve or reject a pending action
    
    Body: { "approved": true/false, "modifications": {} }
    """
    session_mgr = get_session_manager()
    session = session_mgr.get_session(session_id)
    
    if not session:
        return jsonify({
            "success": False,
            "error": "Session not found",
        }), 404
    
    if not session.pending_approval:
        return jsonify({
            "success": False,
            "error": "No pending approval",
        }), 400
    
    data = request.get_json() or {}
    approved = data.get("approved", False)
    modifications = data.get("modifications", {})
    
    manager = get_manager()
    
    async def run_approval():
        events = []
        async for event in manager.handle_approval(session, approved, modifications):
            events.append(event.to_dict())
        return events
    
    events = run_in_worker_loop(run_approval())
    
    return jsonify({
        "success": True,
        "events": events,
    })


# =============================================================================
# SocketIO Handlers
# =============================================================================

SESSION_OWNER_KEY = 'owner_user_id'

# Principals that are not one person: everybody on such a deployment shares the id, so an
# ownership comparison against them would either pass for everyone or fail for everyone.
SHARED_PRINCIPAL_IDS = frozenset({
    'service_api_key', 'open_mode', 'auto_sign', 'public_key',
})

# Rooms that are broadcasts rather than conversations. Every client joins these.
PUBLIC_ROOMS = frozenset({'background_tasks'})


def _may_use_session(session_id: str) -> bool:
    """May the calling socket read or drive this session?

    Ownership is only meaningful when both sides name a person. A shared principal (service
    key, open mode, auto-sign, public key) and a session with no recorded owner both fall
    back to "any authenticated caller", which is what this namespace has always been — the
    connection itself is now authenticated, which is the part that was missing.
    """
    if session_id in PUBLIC_ROOMS:
        return True
    if socket_auth.is_shared_principal():
        return True

    caller = socket_auth.current_user_id()
    if not caller:
        return False

    session = get_session_manager().get_session(session_id)
    if session is None:
        # An unknown id is not someone else's session. The handlers answer their own
        # "session not found"; refusing here would turn that into a confusing auth error.
        return True

    owner = session.get_context(SESSION_OWNER_KEY)
    return owner is None or owner == caller



from backend_server.src.agent.tools.page_interaction import COMPANION_ECHO as _COMPANION_ECHO
_RECENT_CLIENT_MSGS: dict = {}
_RECENT_CLIENT_MSG_TTL_S = 300


def _seen_client_msg(session_id: str, client_msg_id: str) -> bool:
    """True when this (session, client_msg_id) was already accepted in the last 5 minutes."""
    import time
    now = time.time()
    for key in [k for k, t in _RECENT_CLIENT_MSGS.items() if now - t > _RECENT_CLIENT_MSG_TTL_S]:
        _RECENT_CLIENT_MSGS.pop(key, None)
    key = (session_id, client_msg_id)
    if key in _RECENT_CLIENT_MSGS:
        return True
    _RECENT_CLIENT_MSGS[key] = now
    return False


def register_agent_socketio_handlers(socketio):
    """
    Register SocketIO event handlers for /agent namespace
    
    Call this from app.py after creating the socketio instance.
    """
    
    @socketio.on('connect', namespace='/agent')
    def handle_connect(auth=None):
        """Authenticate the handshake, or refuse the connection.

        The socket.io handshake never passes through the global /server/* guard, so before
        this every event on this namespace — send_message, approve, clear_session — was
        reachable by anyone who could open a socket to the server.

        Returning False refuses the connection; the client sees a connect_error.
        """
        principal = authorize_socket_connection(auth)
        if principal is None:
            logger.warning("Refused unauthenticated connection to /agent namespace")
            return False

        socket_auth.remember(request.sid, principal)
        logger.info(
            "Client connected to /agent namespace as %s (role: %s)",
            principal.get('user_email'), principal.get('user_role'),
        )
        socketio.emit('connected', {'status': 'ok'}, namespace='/agent', to=request.sid)
        return None

    @socketio.on('disconnect', namespace='/agent')
    def handle_disconnect():
        socket_auth.forget(request.sid)
        logger.info("Client disconnected from /agent namespace")
    
    @socketio.on('join_session', namespace='/agent')
    def handle_join_session(data):
        """Join a session room.

        The room is the delivery channel for a conversation, so joining someone else's is
        reading their chat. session_id came straight off the wire and was joined unchecked.
        """
        session_id = data.get('session_id')
        if not session_id:
            return

        if not _may_use_session(session_id):
            logger.warning("Refused join_session for %s: not the caller's session", session_id)
            socketio.emit(
                'error',
                {'message': 'Not your session'},
                namespace='/agent', to=request.sid,
            )
            return

        from flask_socketio import join_room
        join_room(session_id)
        logger.info(f"Client joined session: {session_id}")
        socketio.emit('joined', {'session_id': session_id}, namespace='/agent', to=request.sid)
    
    @socketio.on('leave_session', namespace='/agent')
    def handle_leave_session(data):
        """Leave a session room"""
        session_id = data.get('session_id')
        if session_id:
            from flask_socketio import leave_room
            leave_room(session_id)
            logger.info(f"Client left session: {session_id}")
    
    @socketio.on('send_message', namespace='/agent')
    def handle_message(data):
        """
        Handle user message

        Data: {
            "session_id": "...",
            "message": "...",
            "team_id": "...",
            "agent_id": "...",
            "allow_auto_navigation": true/false,
            "current_page": "/path/to/page",
            "host_name": "...",
            "device_id": "...",
            "userinterface_name": "...",
            "quick_hint": {"tool": "...", "args": {...}}   # optional, from the voice audio path (TASK-140 Q5)
        }
        """
        session_id = data.get('session_id')
        message = data.get('message')
        team_id = data.get('team_id')
        agent_id = data.get('agent_id', 'assistant')  # Default to assistant agent
        allow_auto_navigation = data.get('allow_auto_navigation', False)
        current_page = data.get('current_page', '/')
        host_name = data.get('host_name', '')
        device_id = data.get('device_id', '')
        userinterface_name = data.get('userinterface_name', '')
        testcase_id = data.get('testcase_id', '')
        campaign_id = data.get('campaign_id', '')
        workspace_id = data.get('workspace_id', '')
        selected_server = data.get('selected_server', '')
        selected_server_name = data.get('selected_server_name', '')
        selected_server_hosts = data.get('selected_server_hosts', [])
        grafana_base_url = data.get('grafana_base_url', '')
        available_devices = data.get('available_devices', [])
        available_userinterfaces = data.get('available_userinterfaces', [])
        
        if not session_id or not message:
            socketio.emit('error', {
                'error': 'session_id and message required'
            }, namespace='/agent')
            return

        # team_id is authorization input.  It may arrive from the SPA for routing,
        # but a signed-in user may only select a team present in the trusted JWT/DB
        # ceiling.  Never persist an unchecked wire value into Atlas context.
        principal = socket_auth.principal() or {}
        if not socket_auth.is_shared_principal():
            from backend_server.src.lib.auth_middleware import team_ids_for_principal
            allowed_team_ids = team_ids_for_principal(principal)
            if not team_id or str(team_id) not in allowed_team_ids:
                logger.warning("Refused agent team scope outside caller ceiling: %s", team_id)
                socketio.emit('error', {'message': 'Team scope is not authorized'}, namespace='/agent', to=request.sid)
                return

        if not _may_use_session(session_id):
            logger.warning("Refused send_message for session %s: not the caller's session", session_id)
            socketio.emit('error', {'message': 'Not your session'}, namespace='/agent', to=request.sid)
            return

        # Sending a message IS an implicit room join: put the sender in the
        # session room synchronously, before any agent_event is emitted.
        # Otherwise a join_session race (page load, or a reconnect after a
        # server restart wiped the previous socket's room membership) makes
        # every event go to an empty room and the frontend shows "No response
        # from agent within 30s" while the agent actually answered.
        from flask_socketio import join_room
        join_room(session_id)

        # BUG-0401: the SPA's ack watchdog re-sends the same message (same client_msg_id) when the first
        # copy's ack was lost; process each id once per session, but still ack so the SPA stops waiting.
        client_msg_id = data.get('client_msg_id')
        if client_msg_id and _seen_client_msg(session_id, str(client_msg_id)):
            logger.info("Ignored duplicate send_message %s for session %s", client_msg_id, session_id)
            socketio.emit('agent_event', {
                'type': 'thinking',
                'agent': (agent_id or 'assistant').capitalize(),
                'content': 'Received...',
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
            }, room=session_id, namespace='/agent')
            return

        # Immediate ack: flip the frontend's first-answer watchdog before we
        # block on session lookup, manager init, prompt build, or the provider
        # call. Without this, a slow first LLM hop (e.g. router mode on
        # OpenRouter with no prompt cache) trips the 30s "No response from
        # agent" timeout even though the request is in flight.
        socketio.emit('agent_event', {
            'type': 'thinking',
            'agent': (agent_id or 'assistant').capitalize(),
            'content': 'Received...',
            'timestamp': datetime.now().isoformat(),
            'session_id': session_id,
        }, room=session_id, namespace='/agent')

        # Log user message with agent_id
        log_agent_event('USER_MESSAGE', session_id, {
            'message': message,
            'team_id': team_id,
            'agent_id': agent_id,
            'allow_auto_navigation': allow_auto_navigation,
            'current_page': current_page,
            'host_name': host_name,
            'device_id': device_id,
            'userinterface_name': userinterface_name,
            'testcase_id': testcase_id,
            'campaign_id': campaign_id,
            'available_devices_count': len(available_devices),
            'available_userinterfaces_count': len(available_userinterfaces)
        })
        
        # Post user message to Slack
        if SLACK_HOOK_AVAILABLE:
            on_user_message_websocket(session_id, 'User', message)
        
        session_mgr = get_session_manager()
        session = session_mgr.get_session(session_id)
        
        if not session:
            socketio.emit('error', {
                'error': 'Session not found'
            }, namespace='/agent')
            return
        
        # TASK-175: Forge owns creating and changing scripts, testcases and virtual scripts. An Atlas
        # message that asks for it is handed to Forge here, before Atlas spends a token; the event tells
        # the chat to switch to Forge so the follow-ups go there too.
        if agent_id == 'assistant':
            from agent import agent_routing_rules
            if agent_routing_rules.forge_handoff(message):
                agent_id = agent_routing_rules.FORGE
                socketio.emit('agent_event', {
                    'type': 'agent_delegated',
                    'agent': 'Atlas',
                    'content': 'Script and testcase work is Forge\'s: handing this to Forge.',
                    'metrics': {'handoff_to': agent_id, 'handoff_name': agent_routing_rules.AGENT_NAMES[agent_id]},
                    'timestamp': datetime.now().isoformat(),
                    'session_id': session_id,
                }, room=session_id, namespace='/agent')

        # Store context in session for 2-step workflow
        if team_id:
            session.set_context('team_id', team_id)
        session.set_context('agent_id', agent_id)
        session.set_context('allow_auto_navigation', allow_auto_navigation)
        session.set_context('current_page', current_page)
        session.set_context('host_name', host_name)
        session.set_context('device_id', device_id)
        session.set_context('userinterface_name', userinterface_name)
        session.set_context('testcase_id', testcase_id)
        session.set_context('campaign_id', campaign_id)
        session.set_context('workspace_id', workspace_id)
        session.set_context('selected_server', selected_server)
        session.set_context('selected_server_name', selected_server_name)
        session.set_context('selected_server_hosts', selected_server_hosts if isinstance(selected_server_hosts, list) else [])
        # Link text only: the web app's own Grafana base, accepted when it is a plain http(s) URL.
        from backend_server.src.lib.analytics.grafana_push import clean_grafana_base
        session.set_context('grafana_base_url', clean_grafana_base(grafana_base_url))
        session.set_context('user_id', principal.get('user_id'))
        # Device-lock identity for the MCP device tools (BUG-0402): the browser tab's Take Control
        # session, and whether user_id is shared (auto-sign/open mode) and so names nobody.
        session.set_context('browser_session_id', data.get('browser_session_id') or '')
        session.set_context('user_shared', socket_auth.is_shared_principal())
        session.set_context('user_email', principal.get('user_email'))
        session.set_context('user_role', principal.get('user_role'))
        session.set_context('available_devices', available_devices)
        session.set_context('available_userinterfaces', available_userinterfaces)

        # Voice (TASK-140 Q5): a speech model already picked a command from the audio. The quick step validates it
        # and, when valid, runs it without a model call; the manager takes it from the context once per turn.
        quick_hint = data.get('quick_hint')
        if isinstance(quick_hint, dict) and isinstance(quick_hint.get('tool'), str) and isinstance(quick_hint.get('args') or {}, dict):
            session.set_context('quick_hint', {'tool': quick_hint['tool'], 'args': quick_hint.get('args') or {}})
        else:
            session.context.pop('quick_hint', None)

        # Atlas model picker: pin this session to one profile from the chain (UI: fallback
        # dropdown). Empty / missing value clears any earlier pin and reverts to the chain.
        # Validate before storing: a tampered id must not be able to swap in a disabled
        # profile or one whose endpoint is not allowed for this team.
        pinned_profile_id = (data.get('pinned_profile_id') or '').strip()
        if pinned_profile_id:
            from shared.src.lib.database import ai_routing_db
            profile = ai_routing_db.get_row('ai_profiles', pinned_profile_id)
            if not profile or not profile.get('enabled', True):
                socketio.emit('error', {
                    'message': f"Pinned model '{pinned_profile_id}' is not available",
                }, namespace='/agent', to=request.sid)
                return
            endpoint = ai_routing_db.get_row('ai_endpoints', profile.get('endpoint_id'))
            allowed = (endpoint or {}).get('allowed_team_ids') or []
            if team_id and allowed and team_id not in allowed:
                socketio.emit('error', {
                    'message': f"Pinned model '{profile.get('name', pinned_profile_id)}' is not available to this team",
                }, namespace='/agent', to=request.sid)
                return
        session.set_context('pinned_profile_id', pinned_profile_id)

        # Atlas Companion (TASK-126): what the companion shows rides with the message, so a
        # follow-up ("only failed") edits the same page. Plain text, one line, length-capped.
        companion = ' '.join(str(data.get('companion') or '').split())[:400]
        session.set_context('companion', companion[len('Companion: '):] if companion.startswith('Companion: ') else '')

        # Reset cancellation flag for new message (ensures clean start)
        session.reset_cancellation()

        # Try to get manager - handle API key not configured
        try:
            manager = get_manager(team_id=team_id, agent_id=agent_id, session=session)
        except Exception as e:
            logger.warning(f"Failed to initialize manager: {e}")
            # Emit friendly error asking for API key (use generic System agent)
            socketio.emit('agent_event', {
                'type': 'error',
                'agent': 'System',
                'content': '⚠️ AI provider is not configured. Please add your active provider API key to continue.',
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
            }, room=session_id, namespace='/agent')
            socketio.emit('agent_event', {
                'type': 'session_ended',
                'agent': 'System',
                'content': 'Session ended - API key required',
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
            }, room=session_id, namespace='/agent')
            return

        # Pre-flight: fail fast when the agent's AI route is missing or its endpoint
        # has no key, instead of letting the request sit until the 30s front-end
        # watchdog with no visible cause.
        ai_settings = manager.ai_settings
        model_error = ai_settings.get('error') or (
            None if ai_settings.get('api_key_configured')
            else f"No API key for the '{ai_settings.get('endpoint')}' AI endpoint (Settings → AI)."
        )
        if model_error:
            socketio.emit('agent_event', {
                'type': 'error',
                'agent': 'System',
                'content': f'⚠️ {model_error}',
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
            }, room=session_id, namespace='/agent')
            socketio.emit('agent_event', {
                'type': 'session_ended',
                'agent': 'System',
                'content': 'Session ended - invalid model',
                'timestamp': datetime.now().isoformat(),
                'session_id': session_id,
            }, room=session_id, namespace='/agent')
            return
        
        async def process_and_stream():
            # Track execution for leaderboard
            task_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc)
            tool_call_count = 0
            execution_status = 'completed'
            error_msg = None
            # TASK-54: what the turn said and did, stored in agent_turns after the turn
            final_answer = None
            error_event_text = None
            tool_calls_log = []
            
            try:
                event_counter = 0
                async for event in manager.process_message(message, session):
                    event_counter += 1
                    if event.type in ('message', 'result') and isinstance(event.content, str):
                        # the model sometimes echoes the companion context line: never show it
                        event.content = _COMPANION_ECHO.sub('', event.content).rstrip()
                    event_dict = event.to_dict()
                    
                    # Count tool calls for metrics
                    if event.type == 'tool_call':
                        tool_call_count += 1
                        tool_calls_log.append({'name': event.tool_name, 'params': event.tool_params, 'success': None})
                    elif event.type == 'tool_result' and tool_calls_log:
                        tool_calls_log[-1]['success'] = event.success
                    elif event.type in ('message', 'result') and isinstance(event.content, str) and event.content:
                        final_answer = event.content
                    elif event.type == 'error' and event.content:
                        error_event_text = str(event.content)
                    
                    # Debug: Print every event being emitted (include session + tool for traceability)
                    print(
                        f"[SOCKET DEBUG] #{event_counter} session={session_id} "
                        f"type={event_dict.get('type')} agent={event_dict.get('agent')} "
                        f"tool={event_dict.get('tool_name') or event_dict.get('tool') or '-'}"
                    )
                    
                    # Log every agent event for debugging
                    log_agent_event('AGENT_EVENT', session_id, event_dict)

                    # Stamp the session so multi-conversation clients can route
                    # events to the right chat thread.
                    event_dict['session_id'] = session_id

                    socketio.emit('agent_event',
                        event_dict,
                        room=session_id,
                        namespace='/agent'
                    )
                    
                    # Post agent message to Slack (only final messages, not tool calls/thinking)
                    if SLACK_HOOK_AVAILABLE and event.type in ['message', 'result']:
                        on_agent_message_websocket(
                            session_id, 
                            event.agent or 'AI Agent',
                            event.content or '',
                            event.type
                        )
                    
                    await asyncio.sleep(0.05)
                
                print(f"[SOCKET DEBUG] Finished emitting {event_counter} events")
            except Exception as e:
                print(f"[SOCKET DEBUG] ERROR during event loop: {e}")
                logger.error(f"Error processing message: {e}", exc_info=True)
                log_agent_event('ERROR', session_id, {
                    'error': str(e),
                    'type': type(e).__name__
                })
                # Emit error as agent_event so frontend handler receives it
                socketio.emit('agent_event', {
                    'type': 'error',
                    'agent': 'System',
                    'content': str(e),
                    'timestamp': datetime.now().isoformat(),
                    'session_id': session_id,
                }, room=session_id, namespace='/agent')
                # Always emit session_ended so frontend can finalize the conversation
                socketio.emit('agent_event', {
                    'type': 'session_ended',
                    'agent': 'System',
                    'content': 'Session ended',
                    'timestamp': datetime.now().isoformat(),
                    'session_id': session_id,
                }, room=session_id, namespace='/agent')
                execution_status = 'failed'
                error_msg = str(e)
            finally:
                # Log execution to database for leaderboard tracking
                registry = get_agent_registry()
                agent = registry.get(agent_id)
                agent_version = agent.metadata.version if agent else 'unknown'
                # An error event with no answer is a failed turn (it used to count as completed)
                if execution_status == 'completed' and error_event_text and not final_answer:
                    execution_status = 'failed'
                    error_msg = error_event_text[:500]
                completed_at = datetime.now(timezone.utc)
                tokens_in = getattr(manager, 'turn_tokens_in', 0)
                tokens_out = getattr(manager, 'turn_tokens_out', 0)
                trace_id = getattr(manager, 'last_trace_id', None)
                history_id = log_execution_history(
                    agent_id=agent_id,
                    version=agent_version,
                    team_id=team_id,
                    task_id=task_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status=execution_status,
                    tool_calls=tool_call_count,
                    error_message=error_msg,
                    metadata={'prompt': message[:200], 'session_id': session_id, 'trace_id': trace_id},
                    token_usage=(tokens_in or 0) + (tokens_out or 0)
                )
                # Transcript + live tail for the Agent Dashboard (never breaks the chat)
                try:
                    from agent.activity import service as agent_activity
                    agent_activity.record_chat_turn(
                        team_id=team_id, agent_id=agent_id, session_id=session_id, task_id=task_id,
                        message=message, answer=final_answer,
                        tool_calls=agent_activity.compact_tool_calls(tool_calls_log),
                        tokens_in=tokens_in, tokens_out=tokens_out, trace_id=trace_id,
                        started_at=started_at, completed_at=completed_at, status=execution_status,
                        history_id=history_id)
                except Exception as activity_error:
                    logger.warning(f"Agent activity capture failed: {activity_error}")
                
                # Ensure Langfuse data is flushed even on errors
                try:
                    from agent.observability import flush
                    flush()
                except Exception:
                    pass  # Ignore flush errors
        
        socketio.start_background_task(
            lambda: run_agent_coroutine(process_and_stream, socketio, session_id)
        )
    
    @socketio.on('approve', namespace='/agent')
    def handle_approve(data):
        """
        Handle approval response
        
        Data: { "session_id": "...", "approved": true/false, "modifications": {} }
        """
        session_id = data.get('session_id')
        approved = data.get('approved', False)
        modifications = data.get('modifications', {})

        if session_id and not _may_use_session(session_id):
            logger.warning("Refused approve for session %s: not the caller's session", session_id)
            socketio.emit('error', {'message': 'Not your session'}, namespace='/agent', to=request.sid)
            return
        
        session_mgr = get_session_manager()
        session = session_mgr.get_session(session_id)
        
        if not session:
            socketio.emit('error', {
                'error': 'Session not found'
            }, namespace='/agent')
            return
        
        manager = get_manager()
        
        async def process_approval():
            try:
                async for event in manager.handle_approval(session, approved, modifications):
                    socketio.emit('agent_event',
                        event.to_dict(),
                        room=session_id,
                        namespace='/agent'
                    )
                    
                    # Post agent message to Slack
                    if SLACK_HOOK_AVAILABLE and event.type in ['message', 'result']:
                        on_agent_message_websocket(
                            session_id,
                            event.agent or 'AI Agent',
                            event.content or '',
                            event.type
                        )
                    
                    await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Error processing approval: {e}", exc_info=True)
                socketio.emit('error', {
                    'error': str(e),
                    'type': type(e).__name__
                }, room=session_id, namespace='/agent')
        
        socketio.start_background_task(
            lambda: run_agent_coroutine(process_approval, socketio, session_id)
        )
        
    @socketio.on('stop_generation', namespace='/agent')
    def handle_stop(data):
        """Handle stop request"""
        session_id = data.get('session_id')
        print(f"[SOCKET DEBUG] ⛔ stop_generation received for session: {session_id}")

        if session_id and not _may_use_session(session_id):
            logger.warning("Refused stop_generation for session %s: not the caller's session", session_id)
            socketio.emit('error', {'message': 'Not your session'}, namespace='/agent', to=request.sid)
            return

        if session_id:
            session_mgr = get_session_manager()
            session = session_mgr.get_session(session_id)
            if session:
                print(f"[SOCKET DEBUG] ⛔ Cancelling session {session_id}")
                session.cancel()
                logger.info(f"Session {session_id} cancelled by user")
                # Emit cancelled event immediately so UI updates
                socketio.emit('agent_event', {
                    'type': 'error',
                    'agent': 'System',
                    'content': '🛑 Stopping...'
                }, room=session_id, namespace='/agent')
    
    @socketio.on('clear_session', namespace='/agent')
    def handle_clear_session(data):
        """Clear session messages for conversation isolation (preserves tool context)"""
        session_id = data.get('session_id')
        if session_id and not _may_use_session(session_id):
            logger.warning("Refused clear_session for session %s: not the caller's session", session_id)
            socketio.emit('error', {'message': 'Not your session'}, namespace='/agent', to=request.sid)
            return
        if session_id:
            session_mgr = get_session_manager()
            session = session_mgr.get_session(session_id)
            if session:
                session.messages = []  # Clear AI history only
                # Keep session.context (host, device, tree_id) for tool optimization
                logger.info(f"Cleared messages for session: {session_id}")
    
    logger.info("SocketIO handlers registered for /agent namespace")
