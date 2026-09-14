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
from datetime import datetime

import requests
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_settings_routes import get_env_paths, write_env_file

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
    metadata: dict = None
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

# One agent conversation processes at a time per worker: the manager drives its
# own asyncio loop inside a greenlet, and a second concurrent asyncio.run() in
# the same OS thread dies with "asyncio.run() cannot be called from a running
# event loop" — the second chat thread's message was silently lost. threading
# is gevent-monkeypatched (app.py), so this Lock queues greenlets
# cooperatively: parallel conversations are accepted and answered in turn.
import threading
_agent_processing_lock = threading.Lock()


def run_agent_coroutine(coro_factory):
    """Run an agent coroutine under the per-worker processing lock."""
    with _agent_processing_lock:
        asyncio.run(coro_factory())

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


def _persist_active_provider_config(provider: str, api_key: str, model: str) -> None:
    """Persist provider config to the server environment and current process."""
    from shared.src.lib.ai.config import get_provider_api_env, normalize_provider

    normalized_provider = normalize_provider(provider)
    api_env = get_provider_api_env(normalized_provider)
    env_updates = {
        "AI_AGENT_PROVIDER": normalized_provider,
        "AI_AGENT_MODEL": model,
        api_env: api_key,
    }
    write_env_file(get_env_paths()["server"], env_updates)
    for key, value in env_updates.items():
        os.environ[key] = value


# =============================================================================
# REST Endpoints
# =============================================================================

@server_agent_bp.route('/health', methods=['GET'])
@handle_route_exceptions('server_agent:health')
def health_check():
    """Health check - returns active provider configuration status."""
    team_id = request.args.get('team_id')
    from shared.src.lib.ai.config import get_active_ai_settings

    settings = get_active_ai_settings(team_id)
    return jsonify({
        "success": True,
        "status": "healthy",
        "api_key_configured": settings["api_key_configured"],
        "provider": settings["provider"],
        "model": settings["model"],
        "api_key_env": settings["api_key_env"],
        "supports_prompt_caching": settings["supports_prompt_caching"],
        "manager_initialized": _manager is not None,
    })


@server_agent_bp.route('/models', methods=['GET'])
@handle_route_exceptions('server_agent:models')
def list_models():
    """Return the per-provider × per-task default model matrix and task types.

    Used by the AI settings UI to populate provider/model dropdowns.
    """
    from shared.src.lib.ai.config import SUPPORTED_PROVIDERS, TASK_TYPES, get_provider_models
    return jsonify({
        "success": True,
        "providers": list(SUPPORTED_PROVIDERS),
        "tasks": list(TASK_TYPES),
        "provider_models": get_provider_models(),
    })


@server_agent_bp.route('/api-key', methods=['POST'])
@handle_route_exceptions('server_agent:save_api_key')
def save_api_key():
    """
    Save and validate the active or selected provider API key.

    Body: { "provider": "...", "api_key": "...", "model": "..." }
    """
    data = request.get_json() or {}
    api_key = data.get('api_key', '').strip()
    from shared.src.lib.ai.config import LOCAL_PROVIDER, get_active_model, normalize_provider
    from shared.src.lib.ai.provider_client import validate_provider_credentials

    provider = normalize_provider(data.get('provider') or os.getenv('AI_AGENT_PROVIDER'))
    model = (data.get('model') or "").strip() or get_active_model(provider)

    # A local OpenAI-compatible server usually has no key; the base URL is its config.
    if not api_key and provider != LOCAL_PROVIDER:
        return jsonify({
            "success": False,
            "error": "API key required"
        }), 400

    try:
        validate_provider_credentials(provider, api_key, model)
        _persist_active_provider_config(provider, api_key, model)
        return jsonify({
            "success": True,
            "message": "Provider key validated and saved successfully",
            "provider": provider,
            "model": model,
        })
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 500
        return jsonify({
            "success": False,
            "error": f"Validation failed for {provider}: {e.response.text[:300] if e.response is not None else str(e)}"
        }), 401 if status_code in (401, 403) else status_code
    except Exception as e:
        logger.error(f"API key validation error: {e}")
        return jsonify({
            "success": False,
            "error": f"Validation error: {str(e)}"
        }), 500


@server_agent_bp.route('/sessions', methods=['POST'])
@handle_route_exceptions('server_agent:create_session')
def create_session():
    """Create a new chat session"""
    session_mgr = get_session_manager()
    session = session_mgr.create_session()
    
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
    
    events = asyncio.run(run_approval())
    
    return jsonify({
        "success": True,
        "events": events,
    })


# =============================================================================
# SocketIO Handlers
# =============================================================================

def register_agent_socketio_handlers(socketio):
    """
    Register SocketIO event handlers for /agent namespace
    
    Call this from app.py after creating the socketio instance.
    """
    
    @socketio.on('connect', namespace='/agent')
    def handle_connect():
        logger.info("Client connected to /agent namespace")
        socketio.emit('connected', {'status': 'ok'}, namespace='/agent')
    
    @socketio.on('disconnect', namespace='/agent')
    def handle_disconnect():
        logger.info("Client disconnected from /agent namespace")
    
    @socketio.on('join_session', namespace='/agent')
    def handle_join_session(data):
        """Join a session room"""
        session_id = data.get('session_id')
        if session_id:
            from flask_socketio import join_room
            join_room(session_id)
            logger.info(f"Client joined session: {session_id}")
            socketio.emit('joined', {'session_id': session_id}, namespace='/agent')
    
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
        available_devices = data.get('available_devices', [])
        available_userinterfaces = data.get('available_userinterfaces', [])
        
        if not session_id or not message:
            socketio.emit('error', {
                'error': 'session_id and message required'
            }, namespace='/agent')
            return

        # Sending a message IS an implicit room join: put the sender in the
        # session room synchronously, before any agent_event is emitted.
        # Otherwise a join_session race (page load, or a reconnect after a
        # server restart wiped the previous socket's room membership) makes
        # every event go to an empty room and the frontend shows "No response
        # from agent within 30s" while the agent actually answered.
        from flask_socketio import join_room
        join_room(session_id)

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

        # Pre-flight: reject wrong-family provider/model combos (e.g.
        # minimax + sonnet) before the blocking LLM call. Without this check
        # the request sits in the provider SDK until it times out or returns
        # a cryptic HTTP error, and the user only sees the 30s front-end
        # watchdog — not the actual cause.
        from shared.src.lib.ai.config import validate_provider_model
        model_error = validate_provider_model(manager.provider, manager.model)
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
            started_at = datetime.now()
            tool_call_count = 0
            execution_status = 'completed'
            error_msg = None
            
            try:
                event_counter = 0
                async for event in manager.process_message(message, session):
                    event_counter += 1
                    event_dict = event.to_dict()
                    
                    # Count tool calls for metrics
                    if event.type == 'tool_call':
                        tool_call_count += 1
                    
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
                log_execution_history(
                    agent_id=agent_id,
                    version='1.0.0',
                    team_id=team_id,
                    task_id=task_id,
                    started_at=started_at,
                    completed_at=datetime.now(),
                    status=execution_status,
                    tool_calls=tool_call_count,
                    error_message=error_msg,
                    metadata={'prompt': message[:200], 'session_id': session_id}
                )
                
                # Ensure Langfuse data is flushed even on errors
                try:
                    from agent.observability import flush
                    flush()
                except Exception:
                    pass  # Ignore flush errors
        
        socketio.start_background_task(
            lambda: run_agent_coroutine(process_and_stream)
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
            lambda: run_agent_coroutine(process_approval)
        )
        
    @socketio.on('stop_generation', namespace='/agent')
    def handle_stop(data):
        """Handle stop request"""
        session_id = data.get('session_id')
        print(f"[SOCKET DEBUG] ⛔ stop_generation received for session: {session_id}")
        
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
        if session_id:
            session_mgr = get_session_manager()
            session = session_mgr.get_session(session_id)
            if session:
                session.messages = []  # Clear AI history only
                # Keep session.context (host, device, tree_id) for tool optimization
                logger.info(f"Cleared messages for session: {session_id}")
    
    logger.info("SocketIO handlers registered for /agent namespace")
