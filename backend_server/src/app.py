#!/usr/bin/env python3
"""
VirtualPyTest Backend Server Application

Main API server handling client requests and orchestration.
Provides REST API endpoints, WebSocket handling, and business logic coordination.

Usage: python3 app.py

Environment Variables Required (in .env file):
    SERVER_URL - Base URL of this server (e.g., https://api.virtualpytest.com)
    SERVER_PORT - Port for this server (default: 5109)
    GITHUB_TOKEN - GitHub token for authentication (loaded when needed)
    DEBUG - Set to 'true' to enable debug mode (default: false)
"""

import os
import sys

# Windows services often run under a legacy codepage (e.g. cp1252) which will crash
# on non-ASCII output (emojis) during startup. Prefer UTF-8 everywhere.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# CRITICAL: gevent.monkey.patch_all() must be called BEFORE most other imports.
# On Windows, gevent may not be installed/supported; we fall back to SocketIO threading mode.
if os.name != 'nt':
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        # Allow running without gevent (e.g., dev / Windows-like installs).
        pass

import time
import atexit
import uuid

# Setup path for shared library access
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_server_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(backend_server_dir)

# Add project root to path for clear imports (shared.src.lib.*, backend_host.*)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Apply global typing compatibility early to fix third-party package issues
try:
    from shared.src.lib.utils.typing_compatibility import ensure_typing_compatibility
    ensure_typing_compatibility()
except ImportError:
    print("Warning: Could not apply typing compatibility fix")

# Add backend_server to path for src.lib.* imports
if backend_server_dir not in sys.path:
    sys.path.insert(0, backend_server_dir)

# Add backend_server/src to path for local imports
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import from shared library (using clear import paths)
try:
    from shared.src.lib.utils.app_utils import (
        load_environment_variables,
        kill_process_on_port,
        setup_and_cleanup_app,
        setup_flask_app,
        validate_core_environment,
        DEFAULT_USER_ID
    )
except ImportError as e:
    print(f"❌ CRITICAL: Cannot import app_utils: {e}")
    print("   Make sure shared/lib/utils/app_utils.py exists")
    sys.exit(1)

def validate_startup_requirements():
    """Validate requirements for server startup"""
    print("[@backend_server:validate] Validating startup requirements...")
    
    env_path = load_environment_variables(mode='server')
    
    if not validate_core_environment(mode='server'):
        print("❌ CRITICAL: Environment validation failed. Check .env file")
        sys.exit(1)
    
    # Print database URL for verification
    supabase_url = os.getenv('SUPABASE_URL', 'NOT SET')
    print(f"[@backend_server:validate] 🗄️  Database Configuration:")
    print(f"[@backend_server:validate]    SUPABASE_URL: {supabase_url}")
    
    # Print API_KEY status for verification
    api_key = os.getenv('API_KEY')
    if api_key:
        print(f"[@backend_server:validate] 🔑 API_KEY: SET (length={len(api_key)})")
    else:
        print(f"[@backend_server:validate] ⚠️  API_KEY: NOT SET - host requests will fail!")

    # Print /server/* authentication posture for verification. Closed by default:
    # SERVER_OPEN_MODE=true ⇒ open (explicit opt-in, wins over a configured secret,
    # BUG-0070); else a JWT secret ⇒ JWT enforced; else deny (401).
    from backend_server.src.lib.auth_middleware import (
        has_supabase_jwt_secret_configured,
        is_api_key_configured,
        is_server_open_mode,
    )
    if is_server_open_mode():
        print(
            "[@backend_server:validate] 🚨 /server/* auth: OPEN MODE (SERVER_OPEN_MODE=true) — "
            "browser requests allowed with no login. Dev / trusted network only."
            + (" Direct (non-browser) calls still require X-API-Key."
               if is_api_key_configured()
               else " API_KEY is NOT set, so direct calls are unauthenticated too.")
            + (" NOTE: a SUPABASE_JWT_SECRET is also configured and is IGNORED for /server/* "
               "while open mode is on — remove SERVER_OPEN_MODE to enforce JWT."
               if has_supabase_jwt_secret_configured() else "")
        )
    elif has_supabase_jwt_secret_configured():
        print(
            "[@backend_server:validate] 🔐 /server/* auth: JWT ENFORCED "
            "(SUPABASE_JWT_SECRET configured). Services use X-API-Key; anonymous → 401."
        )
    else:
        print(
            "[@backend_server:validate] 🔒 /server/* auth: CLOSED (no JWT secret, no open mode) — "
            "requests without a valid X-API-Key / auto-sign token → 401."
        )
    
    print("✅ Startup requirements validated")

def get_server_port():
    """Get the server port from environment"""
    return int(os.getenv('SERVER_PORT', '5109'))

def server_app_init(app):
    """Initialize server-specific app context"""
    app.default_user_id = DEFAULT_USER_ID
    app.unique_server_id = str(uuid.uuid4())[:8]

def setup_and_cleanup():
    """Setup Flask app and cleanup ports using shared function"""
    return setup_and_cleanup_app("VirtualPyTest-backend_server", get_server_port, "backend_server", server_app_init)


# Paths under /server/ that the global auth guard lets through without a principal.
#
# Every entry is either data-free (a health probe, the pre-login auth status check) or
# authenticates itself inside the route with a credential of its own — an MCP bearer, the
# CICD ingest token, the host-session cookie, an Origin allowlist. Nothing here is simply
# "trusted because it is internal": the four host completion callbacks used to be, and any
# machine that could reach the server could forge a task completion, release a device lock
# and make the server call an attacker-supplied external_callback_url. Hosts now present the
# shared X-API-Key on those (server_auth_headers()), so they are gated like everything else.
#
# Adding an entry here opens it to the internet. Add one only when the route authenticates
# itself, and say in a comment which credential it checks.
UNAUTHENTICATED_SERVER_PREFIXES: tuple = (
    '/server/health',
    '/server/action/health',   # health check for action execution service — no auth required
    '/server/storage/health',   # liveness probe (status page / monitors), returns no data beyond "r2_configured"
    # The exact path, NOT the '/server/frontend' prefix: the guard matches
    # `path == prefix or path.startswith(prefix + '/')`, so exempting the prefix would
    # take POST /server/frontend/navigate with it. /navigate stays closed.
    '/server/frontend/health',
    '/server/auth/check',
    '/server/mcp',
    # Anonymous visitors of virtualpytest.com; guarded inside the route by an
    # Origin allowlist, per-IP rate limit and a docs-only tool surface.
    '/server/public/ask',
    '/server/integrations/slack/events',
    # Called only by nginx `auth_request` as an internal subrequest — an
    # iframe/HLS navigation carries no user JWT, so this route validates its
    # own short-lived host-session cookie instead (see
    # server_host_session_routes.py). /server/host-session/session (minting
    # that cookie) is NOT here — it requires the normal user JWT.
    '/server/host-session/authorize',
    # Carries its own bearer (CICD_INGEST_TOKEN, checked inside the route). It exists
    # for GitHub-hosted runners, which cannot reach the LAN database — and which have
    # no user JWT either. Without this the global guard rejected their token as a
    # malformed JWT before the route ever saw it, so the endpoint was unreachable by
    # its only caller.
    '/server/cicd/ingest',
)


def configure_global_frontend_auth_guard(app):
    """Apply JWT auth globally for /server/* routes with explicit callback/public exceptions."""
    from flask import request
    from backend_server.src.lib.auth_middleware import (
        enforce_user_auth_if_enabled_for_request,
        enforce_team_scope,
        enforce_viewer_read_only,
        is_frontend_jwt_required,
    )

    unauthenticated_prefixes = UNAUTHENTICATED_SERVER_PREFIXES
    print(
        "[@backend_server:auth] Global frontend auth guard active for /server/* "
        f"(enforce_jwt={is_frontend_jwt_required()}, unauthenticated exceptions={len(unauthenticated_prefixes)})"
    )

    @app.before_request
    def _global_frontend_auth_guard():
        path = request.path or ''

        if request.method == 'OPTIONS':
            return None
        if not path.startswith('/server/'):
            return None

        if any(path == prefix or path.startswith(f'{prefix}/') for prefix in unauthenticated_prefixes):
            return None

        denied = enforce_user_auth_if_enabled_for_request()
        if denied is not None:
            return denied

        # Read-only floor for the viewer role. Must run here rather than per-route:
        # only 38 of the 272 write routes carry a permission decorator, so a viewer
        # JWT otherwise reaches the other 234 unchallenged (TASK-22).
        denied = enforce_viewer_read_only()
        if denied is not None:
            return denied

        # Multi-tenancy. 140 routes take team_id from request.args and none validated
        # it, so any logged-in user could read another team's data by editing the query
        # string (TASK-22).
        return enforce_team_scope()


def register_all_server_routes(app):
    """Register all server routes - Client-facing API endpoints"""
    
    try:
        # Import all route modules
        from routes import (
            server_system_routes,
            server_web_routes,
            server_core_routes,
            auto_proxy,
            server_control_routes,
            server_actions_routes,
            server_device_routes,
            server_navigation_routes,
            server_navigation_trees_routes,
            server_pathfinding_routes,
            server_alerts_routes,
            server_analytics_routes,
            server_verification_routes,
            server_navigation_execution_routes,
            server_devicemodel_routes,
            server_ai_routes,
            server_testcase_routes,
            server_stream_proxy_routes,
            server_validation_routes,
            server_campaign_routes,
            server_library_visibility_routes,
            server_script_identity_routes,
            server_requirements_routes,
            server_executable_routes,
            server_userinterface_routes,
            server_ai_userinterface_routes,
            server_execution_results_routes,
            server_script_routes,
            server_script_results_routes,
            server_metrics_routes,
            server_heatmap_routes,
            server_campaign_results_routes,
            server_campaign_execution_routes,
            server_frontend_routes,
            server_ai_queue_routes,
            server_api_testing_routes,
            server_device_flags_routes,
            server_restart_routes,
            server_deployment_routes,
            server_builder_routes,
            server_settings_routes,
            mcp_routes,
            server_mcp_proxy_routes,
            server_public_ask_routes,
            logs_routes,
            server_monitoring_routes,
            server_openapi_routes,
            server_postman_routes,
            server_integrations_routes,
            server_auth_routes,
            server_storage_routes,
            server_teams_routes,
            server_tenants_routes,
            server_user_tenants_routes,
            server_branding_tenant_routes,
            server_users_routes,
            server_grafana_routes,
            server_workspaces_routes,
            server_device_info_overrides_routes,
            server_agent_routes,
            agent_registry_routes,
            agent_runtime_routes,
            event_routes,
            agent_benchmark_routes,
            agent_skill_routes,
            server_branding_routes,
            server_permissions_routes,
            server_security_routes,
            server_host_session_routes,
        )
        # Import via absolute package path to avoid module alias split with emit callers
        # that import backend_server.src.routes.server_system_socket_routes.
        from backend_server.src.routes import server_system_socket_routes
        
        # Register all server blueprints
        blueprints = [
            # Core system routes (keep these - have server logic)
            (server_system_routes.server_system_bp, 'System management'),
            (server_web_routes.server_web_bp, 'Web interface'),
            (server_core_routes.server_core_bp, 'Server core API'),
            (server_control_routes.server_control_bp, 'Device control operations'),
            (server_actions_routes.server_actions_bp, 'Action operations'),
            (server_device_routes.server_device_bp, 'Device management'),
            (server_navigation_routes.server_navigation_bp, 'Navigation operations'),
            (server_navigation_trees_routes.server_navigation_trees_bp, 'Navigation trees'),
            (server_pathfinding_routes.server_pathfinding_bp, 'Navigation pathfinding'),
            (server_alerts_routes.server_alerts_bp, 'Alert management'),
            (server_analytics_routes.server_analytics_bp, 'Monitoring > Analytics aggregates (before auto_proxy: it would proxy an unknown section to a host)'),
            (server_verification_routes.server_verification_bp, 'Verification operations'),
            (server_devicemodel_routes.server_devicemodel_bp, 'Device model management'),
            (server_ai_routes.server_ai_bp, 'AI operations'),
            # server_ai_testcase_routes DELETED - replaced by unified /server/testcase/execute-from-prompt
            (server_stream_proxy_routes.server_stream_proxy_bp, 'Stream proxy'),
            (server_validation_routes.server_validation_bp, 'Validation operations'),
            (server_campaign_routes.server_campaign_bp, 'Campaign management'),
            (server_library_visibility_routes.server_library_visibility_bp, 'Library visibility'),
            (server_script_identity_routes.server_script_identity_bp, 'Script identity (TC prefix / display name)'),
            (server_campaign_execution_routes.server_campaign_execution_bp, 'Campaign execution'),
            (server_testcase_routes.server_testcase_bp, 'Test case management'),
            (server_requirements_routes.server_requirements_bp, 'Requirements management'),
            (server_executable_routes.server_executable_bp, 'Unified executable listing (scripts + testcases)'),
            (server_userinterface_routes.server_userinterface_bp, 'User interface management'),
            (server_ai_userinterface_routes.server_ai_userinterface_bp, 'AI-learned UI knowledge base (DB-backed; see docs/agent/navigation/AI_USERINTERFACE.md)'),
            (server_execution_results_routes.server_execution_results_bp, 'Execution results'),
            (server_script_routes.server_script_bp, 'Script management'),
            (server_script_results_routes.server_script_results_bp, 'Script results'),
            (server_metrics_routes.server_metrics_bp, 'Metrics API'),
            (server_heatmap_routes.server_heatmap_bp, 'Heatmap API'),
            (server_campaign_results_routes.server_campaign_results_bp, 'Campaign results'),
            (server_frontend_routes.server_frontend_bp, 'Frontend control'),
            (server_ai_queue_routes.server_ai_queue_bp, 'AI queue monitoring'),
            (server_api_testing_routes.server_api_testing_bp, 'API testing system'),
            (server_device_flags_routes.device_flags_bp, 'Device flags management'),
            (server_restart_routes.server_restart_bp, 'Restart operations'),
            (server_deployment_routes.server_deployment_bp, 'Deployment management'),
            (server_navigation_execution_routes.server_navigation_execution_bp, 'Navigation execution with cache population'),
            (server_builder_routes.server_builder_bp, 'Standard block execution'),
            (server_settings_routes.server_settings_bp, 'Settings management'),
            (mcp_routes.mcp_bp, 'MCP (Model Context Protocol) HTTP endpoint'),
            (server_mcp_proxy_routes.server_mcp_proxy_bp, 'MCP Proxy - OpenRouter Function Calling'),
            (server_public_ask_routes.server_public_ask_bp, 'Public docs Q&A for the marketing website (origin + rate limited)'),
            (logs_routes.logs_bp, 'System logs and service monitoring'),
            (server_monitoring_routes.server_monitoring_bp, 'Monitoring system (registered before auto_proxy for precedence)'),
            (server_openapi_routes.server_openapi_bp, 'OpenAPI documentation serving'),
            (server_postman_routes.server_postman_bp, 'User Postman workspace API testing'),
            (server_integrations_routes.server_integrations_bp, 'Third-party integrations (JIRA, etc.)'),
            (server_auth_routes.server_auth_bp, 'User authentication and authorization'),
            (server_storage_routes.server_storage_bp, 'R2 storage pre-signed URLs (authenticated)'),
            (server_teams_routes.server_teams_bp, 'Teams management'),
            (server_tenants_routes.server_tenants_bp, 'Tenants management (platform admin only)'),
            (server_user_tenants_routes.server_user_tenants_bp, 'User-tenant grants (platform admin only)'),
            (server_branding_tenant_routes.server_branding_tenant_bp, 'Per-tenant branding read (authenticated)'),
            (server_users_routes.server_users_bp, 'Users management'),
            (server_grafana_routes.server_grafana_bp, 'Grafana user provisioning integration'),
            (server_workspaces_routes.server_workspaces_bp, 'Workspace management'),
            (server_device_info_overrides_routes.server_device_info_overrides_bp, 'Device info value corrections (OCR overrides)'),

            # Auto proxy (replaces 11 pure proxy route files + 18 verification proxy routes - navigation-execution now handled separately)
            (auto_proxy.auto_proxy_bp, 'Auto proxy (replaces actions, ai-execution, ai-tools, av, desktop-bash, desktop-pyautogui, monitoring, power, remote, translation + 18 verification routes)'),
            
            # AI Agent chat system
            (server_agent_routes.server_agent_bp, 'AI Agent chat (QA Manager + specialist agents)'),
            
            # Multi-Agent Platform (Event-Driven)
            (agent_registry_routes.server_agent_registry_bp, 'Agent Registry (versioning, import/export)'),
            (agent_runtime_routes.server_agent_runtime_bp, 'Agent Runtime (instance management)'),
            (agent_skill_routes.server_agent_skill_bp, 'Agent Skills (reload, testing, management)'),
            (event_routes.server_event_bp, 'Event System (manual triggers, stats)'),
            (agent_benchmark_routes.server_agent_benchmark_bp, 'Agent Benchmarks & Feedback'),
            (server_branding_routes.server_branding_bp, 'Runtime branding (name, logo, favicon)'),
            (server_permissions_routes.server_permissions_bp, 'Fine-grained permissions (matrix, user effective)'),
            (server_security_routes.server_security_bp, 'Security scan reports (admin-only; Bandit/Snyk/npm-audit)'),
            (server_host_session_routes.server_host_session_bp, 'Host session gate for proxied VNC/HLS/phone-link paths (BUG-0107 step 2)'),
        ]
        
        registered_count = 0
        for blueprint, description in blueprints:
            try:
                app.register_blueprint(blueprint)
                registered_count += 1
            except Exception as e:
                print(f"❌ Failed to register {description}: {e}")
                return False
        
        # Optional features (features/<name>/backend_server/register(app)); see docs/technical/FEATURES.md.
        # No features/ folder or DISABLED_FEATURES covering them all = nothing happens here.
        from shared.src.lib.utils.features import register_feature_blueprints
        registered_count += register_feature_blueprints(app, 'backend_server')

        # Register AI Agent SocketIO handlers
        if hasattr(app, 'socketio'):
            from agent.socket_manager import socket_manager
            socket_manager.init_app(app.socketio)
            server_agent_routes.register_agent_socketio_handlers(app.socketio)
            server_system_socket_routes.init_system_socketio(app.socketio)
            server_system_socket_routes.register_system_socketio_handlers(app.socketio)
            # The default ('/') namespace has no handlers of its own but is not idle —
            # task_complete is emitted there — and with no connect handler socket.io
            # accepts everyone. Guard it too (BUG-0156).
            server_system_socket_routes.register_default_namespace_guard(app.socketio)
        
        # Keep the Analytics sections warm from boot so the first person to open the
        # page after a deploy gets a dict lookup, not a cold query. Never fatal: a
        # pre-warm that cannot reach the DB just means the first request computes.
        try:
            server_analytics_routes.start_analytics_prewarm()
        except Exception as e:
            print(f"⚠️  Analytics pre-warm not started (page still works, first hit is cold): {e}")

        print(f"✅ Registered {registered_count} route blueprints")
        return True
        
    except Exception as e:
        print(f"❌ CRITICAL: Cannot load routes: {e}")
        return False

# Global registry for persistent agents with background workers
_background_agents = {}


def start_agent_background_workers():
    """Auto-start background workers for agents with background_queues configured AND enabled=true"""
    global _background_agents
    
    try:
        from agent.registry import get_agent_registry
        from agent.core.manager import QAManagerAgent
        
        registry = get_agent_registry()
        agents = registry.list_agents()
        
        for agent_def in agents:
            agent_id = agent_def.metadata.id
            config = agent_def.config
            
            # Check if agent has background_queues configured AND is enabled
            if config and hasattr(config, 'background_queues') and config.background_queues:
                # CRITICAL: Respect enabled flag - skip disabled agents
                if hasattr(config, 'enabled') and not config.enabled:
                    print(f"[@backend_server:background] ⏭️ Skipping {agent_id} (enabled=false)")
                    continue
                    
                queues = config.background_queues
                print(f"[@backend_server:background] Starting background for {agent_id}, queues: {queues}")
                
                try:
                    agent = QAManagerAgent(agent_id=agent_id, is_background=True)
                    started = agent.start_background()
                    
                    if started:
                        _background_agents[agent_id] = agent
                        print(f"[@backend_server:background] ✅ {agent_id} background started")
                    else:
                        print(f"[@backend_server:background] ⚠️ {agent_id} background failed to start")
                        
                except Exception as e:
                    print(f"[@backend_server:background] ❌ {agent_id} error: {e}")
        
        if _background_agents:
            print(f"[@backend_server:background] 🚀 {len(_background_agents)} agent(s) with background workers")
        else:
            print("[@backend_server:background] ℹ️ No agents with background_queues configured")
            
    except Exception as e:
        print(f"[@backend_server:background] ⚠️ Failed to start background workers: {e}")
        import traceback
        traceback.print_exc()


def setup_server_cleanup():
    """Setup cleanup handlers for server. Returns cleanup callback for signal handling."""
    def cleanup():
        print("[@backend_server:cleanup] Cleaning up server resources...")
        for agent_id, agent in _background_agents.items():
            try:
                if agent.background_running:
                    agent.stop_background()
                    print(f"[@backend_server:cleanup] ✅ Stopped {agent_id} background")
            except Exception:
                pass
    atexit.register(cleanup)
    return cleanup


def start_server(app):
    """Start the backend_server with proper configuration (delegates to gunicorn_app)."""
    cleanup = setup_server_cleanup()

    # Render injects PORT; local Docker/native installs use SERVER_PORT.
    server_port = int(os.getenv('PORT') or os.getenv('SERVER_PORT', '5109'))
    server_url = os.getenv('SERVER_URL', f'http://localhost:{server_port}')
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'

    print("[@backend_server:start] 🎉 backend_server ready!")
    print(f"[@backend_server:start] 🚀 Starting API server on port {server_port} with SocketIO support")
    print(f"[@backend_server:start]    Server URL: {server_url}")
    print(f"[@backend_server:start]    Debug Mode: {debug_mode}")
    print(f"[@backend_server:start]    Available routes: {len(app.url_map._rules) if hasattr(app, 'url_map') else 'unknown'}")

    try:
        from backend_server.src.lib.server.gunicorn_app import run_server
        run_server(app, on_signal=cleanup, post_worker_init_callback=start_agent_background_workers)
    except ImportError as e:
        print(f"[@backend_server:start] ❌ Import error: {e}")
        print("[@backend_server:start] Flask-SocketIO required. Install: pip install flask-socketio")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except KeyboardInterrupt:
        print("[@backend_server:start] 🛑 backend_server shutting down...")
    except Exception as e:
        print(f"[@backend_server:start] ❌ Error starting backend_server: {e}")
        import traceback
        traceback.print_exc()
        if os.getenv('RENDER', 'false').lower() == 'true':
            time.sleep(5)
        sys.exit(1)
    finally:
        print("[@backend_server:start] 👋 backend_server application stopped")


def main():
    """Main function"""
    print("🖥️ VIRTUALPYTEST backend_server")
    print("Starting VirtualPyTest API Server")
    
    # STEP 1: Validate requirements
    validate_startup_requirements()
    
    # STEP 2: Setup Flask app and cleanup
    app = setup_and_cleanup()

    # STEP 2.1: Apply global frontend auth guard for /server/* API surface
    configure_global_frontend_auth_guard(app)
    
    # STEP 3: Register ALL routes
    if not register_all_server_routes(app):
        print("❌ CRITICAL: Cannot start server without all routes")
        sys.exit(1)
    
    # STEP 4: Agent background workers are started via Gunicorn post_worker_init hook
    # This ensures they only run in worker processes, not the main arbiter
    print("[@backend_server:start] 🤖 Agent background workers will start in Gunicorn worker")
    
    # STEP 5: Start server
    start_server(app)

if __name__ == '__main__':
    main() 
