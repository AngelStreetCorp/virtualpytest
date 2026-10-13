"""
Server Agent Routes - AI Agent Chat System

REST endpoints for session management.
SocketIO handlers for real-time chat with QA Manager and specialist agents.
"""

import os
import logging
import asyncio
import json
import uuid
from datetime import datetime, timezone

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
    from shared.src.lib.ai.provider_client import check_connectivity, create_client
    from shared.src.lib.database import ai_routing_db

    manager = QAManagerAgent(agent_id=data.get('agent_id'))
    try:
        hop = ai_router.resolve(manager.usage_key).primary
    except Exception as e:
        return jsonify({"success": False, "error": f"No AI route for this agent: {e}"}), 400

    try:
        check_connectivity(create_client(hop.preset, api_key, base_url=hop.endpoint.get('base_url'),
                                         timeout=hop.timeout), hop.model)
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 500
        return jsonify({
            "success": False,
            "error": f"Validation failed for {hop.endpoint_name}: {e.response.text[:300] if e.response is not None else str(e)}"
        }), 401 if status_code in (401, 403) else status_code
    except Exception as e:
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
            "userinterface_name": "..."
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
