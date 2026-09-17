"""
App Utilities

Flask application setup and registration utilities.
Focused on app configuration and initialization.
"""

import sys
import os
import time
import subprocess
import psutil
import platform
import logging
from flask import Flask, current_app, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import requests


# =====================================================
# LOGGING FILTER FOR SOCKET.IO POLLING REQUESTS
# =====================================================

class SocketIOPollingFilter(logging.Filter):
    """Filter out noisy socket.io polling/websocket debug logs"""
    
    FILTERED_PATTERNS = [
        '/socket.io/?EIO=',
        'transport=polling',
        'transport=websocket',
    ]
    
    def filter(self, record):
        # Allow the record if it doesn't match any filtered patterns
        message = record.getMessage()
        for pattern in self.FILTERED_PATTERNS:
            if pattern in message:
                return False  # Suppress this log
        return True  # Allow this log

# =====================================================
# ENVIRONMENT AND SETUP FUNCTIONS
# =====================================================

def load_environment_variables(mode='server', calling_script_dir=None):
    """Load environment variables from project-level .env file and service-specific .env"""
    print(f"[@app_utils:load_environment_variables] Loading environment variables (mode={mode})...")
    
    # Find project root (where .env should be)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))  # Go up to project root
    project_env_path = os.path.join(project_root, '.env')
    
    print(f"[@app_utils:load_environment_variables] Current directory: {current_dir}")
    print(f"[@app_utils:load_environment_variables] Project root: {project_root}")
    print(f"[@app_utils:load_environment_variables] Looking for project .env at: {project_env_path}")
    
    # Load project-level .env first (NEVER override OS environment variables from Render)
    if os.path.exists(project_env_path):
        load_dotenv(project_env_path, override=False, encoding='utf-8-sig')  # OS env vars (Render) take priority
        print(f"✅ Loaded project environment from: {project_env_path} (OS env vars take priority)")
        
        # Check for critical variables after loading
        host_name = os.getenv('HOST_NAME')
        print(f"[@app_utils:load_environment_variables] Project .env HOST_NAME: {host_name}")
    else:
        # Check if we're on Render with environment variables already set
        render_env = os.getenv('RENDER', 'false').lower() == 'true'
        server_url = os.getenv('SERVER_URL')
        
        if render_env or server_url:
            print(f"✅ Running with OS environment variables (Render or Docker)")
            print(f"[@app_utils:load_environment_variables] SERVER_URL={server_url}")
        else:
            print(f"⚠️  Project environment file not found: {project_env_path}")
            print(f"⚠️  Create .env in project root for local development: cp env.example .env")
    
    # Load service-specific .env if calling_script_dir is provided (for host)
    if calling_script_dir:
        service_env_path = os.path.join(calling_script_dir, '.env')
        print(f"[@app_utils:load_environment_variables] Looking for service .env at: {service_env_path}")
        
        if os.path.exists(service_env_path):
            load_dotenv(service_env_path, override=False, encoding='utf-8-sig')  # OS env vars still take priority
            print(f"✅ Loaded service environment from: {service_env_path} (OS env vars take priority)")
            
            # Check for critical variables after loading
            host_name = os.getenv('HOST_NAME')
            device1_name = os.getenv('DEVICE1_NAME')
            print(f"[@app_utils:load_environment_variables] Service .env HOST_NAME: {host_name}")
            print(f"[@app_utils:load_environment_variables] Service .env DEVICE1_NAME: {device1_name}")
        else:
            print(f"⚠️  Service environment file not found: {service_env_path}")
    
    # List all environment variables with DEVICE in the name
    print(f"[@app_utils:load_environment_variables] Checking for device configuration...")
    device_vars = [var for var in os.environ.keys() if 'DEVICE' in var]
    for var in device_vars:
        print(f"[@app_utils:load_environment_variables]   {var}={os.environ.get(var)}")
    
    return project_env_path

def kill_process_on_port(port):
    """Simple port cleanup - kill any process using the specified port"""
    try:
        print(f"🔍 Checking for processes using port {port}...")
        
        # Skip if running under Flask reloader to avoid conflicts
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            print(f"🔄 Flask reloader detected, skipping port cleanup")
            return
        
        # Find and kill processes using the port
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections():
                    if hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == port:
                        pid = proc.info['pid']
                        if pid != os.getpid():  # Don't kill ourselves
                            print(f"🎯 Killing process PID {pid} using port {port}")
                            try:
                                psutil.Process(pid).kill()  # Force kill instead of terminate
                            except psutil.AccessDenied:
                                # Try with system command as fallback
                                print(f"🔐 Access denied for PID {pid}, trying system kill...")
                                import subprocess
                                try:
                                    subprocess.run(['sudo', 'kill', '-9', str(pid)], 
                                                 check=True, capture_output=True)
                                    print(f"✅ Successfully killed PID {pid} with sudo")
                                except subprocess.CalledProcessError:
                                    print(f"❌ Failed to kill PID {pid} even with sudo")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
        print(f"✅ Port {port} cleanup completed")

    except Exception as e:
        print(f"❌ Error during port cleanup: {e}")

def test_port_binding(port, host='0.0.0.0'):
    """Test if we can bind to a specific port without actually starting a server"""
    import socket
    try:
        # Try to bind to the port briefly
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_socket:
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_socket.bind((host, port))
            return True  # Port is available
    except OSError as e:
        if e.errno == 98:  # Address already in use
            return False  # Port is in use
        else:
            # Some other error (permission, etc)
            print(f"⚠️ Unexpected error testing port {port}: {e}")
            return False

def cleanup_port_smart(port_getter_func, app_type="application"):
    """Smart port cleanup - only clean up if binding would fail"""
    port = port_getter_func()

    # First test if we can bind to the port
    if test_port_binding(port):
        print(f"✅ Port {port} is available, no cleanup needed for {app_type}")
        return

    # Port is in use, try to clean it up
    print(f"⚠️ Port {port} is in use, attempting cleanup for {app_type}...")
    kill_process_on_port(port)

    # Test again after cleanup
    if not test_port_binding(port):
        print(f"❌ Port {port} still in use after cleanup - {app_type} may fail to bind")
    else:
        print(f"✅ Port {port} cleaned up successfully for {app_type}")

def setup_and_cleanup_app(app_name, port_getter_func, app_type="application", server_specific_init=None):
    """Shared setup and cleanup function for Flask applications"""
    print(f"[@{app_type}:setup] Setting up Flask application...")

    # Clean up port (only if needed)
    cleanup_port_smart(port_getter_func, app_type)
    time.sleep(1)

    # Create Flask app
    app = setup_flask_app(app_name)

    # Initialize app context with server-specific settings if provided
    if server_specific_init:
        with app.app_context():
            server_specific_init(app)

    print("✅ Flask application setup completed")
    return app

# Default allowlist when CORS_ALLOWED_ORIGINS is unset: the deployments already known (from
# code comments and docs/get-started/cloud-setup.md §4.1) to call this API cross-origin, so
# fixing BUG-0092 doesn't silently break them. Anything else — a customer overlay's own
# frontend domain, a self-hoster's split frontend/backend hosts — must set the env var.
DEFAULT_CORS_ALLOWED_ORIGINS = (
    'https://virtualpytest.angelstreet.io,'
    'https://rpitest.angelstreet.io,'
    'https://virtualpytest.com,'
    'https://www.virtualpytest.com,'
    'https://virtualpytest.vercel.app,'
    'http://localhost:5073,'
    # The mobile app (features/mobile-app). Capacitor serves the bundled build from its own
    # local server, so every call the APK makes is cross-origin from `https://localhost` —
    # without this the app reaches its server for nothing: the Dashboard shows "No servers
    # connected" and the Socket.IO handshake just times out. It belongs in the default rather
    # than each deployment's .env because one APK is meant to serve any deployment, and its
    # origin is fixed by Capacitor, not by the deployment. `capacitor://localhost` is the
    # same build on iOS, harmless until that ships.
    'https://localhost,'
    'capacitor://localhost'
)


def _cors_allowed_origins():
    """CORS_ALLOWED_ORIGINS, comma-separated (same convention as PUBLIC_ASK_ALLOWED_ORIGINS in
    server_public_ask_routes.py), else DEFAULT_CORS_ALLOWED_ORIGINS above. Never '*' — BUG-0092."""
    raw = os.getenv('CORS_ALLOWED_ORIGINS', DEFAULT_CORS_ALLOWED_ORIGINS)
    origins = [o.strip().rstrip('/') for o in raw.split(',') if o.strip()]
    return origins or None


def setup_flask_app(app_name="VirtualPyTest"):
    """Setup and configure Flask application with CORS and WebSocket support"""
    app = Flask(app_name)

    # Both services are JSON APIs, but Flask's default error page for an
    # uncaught HTTPException (400/404/405/...) is HTML. Without this handler,
    # handle_route_exceptions()'s HTTPException passthrough (see
    # backend_server/src/lib/utils/route_handlers.py) would correctly return
    # the right status code but with an HTML body that callers expecting JSON
    # can't parse (discovered 2026-09-07 backfilling non-regression tests).
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def _json_http_exception(e):
        return jsonify({'error': e.description}), e.code

    # Suppress noisy socket.io polling/websocket logs from werkzeug
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addFilter(SocketIOPollingFilter())

    # Configure Flask secret key for session management
    # Use environment variable or generate a default for development
    secret_key = os.getenv('FLASK_SECRET_KEY')
    if not secret_key:
        # Generate a default secret key for development
        import secrets
        secret_key = secrets.token_hex(32)
        print(f"⚠️ Using generated secret key for development. Set FLASK_SECRET_KEY environment variable for production.")
    
    app.secret_key = secret_key

    # CORS: an explicit origin allowlist, NOT nginx. nginx's /server/ and /host/ locations
    # have no IP or origin restriction of their own (verified: neither production-https.conf
    # nor any other shipped template gates them) — this is the only origin-based control that
    # exists in front of the API. It used to be `origins="*", supports_credentials=True`, which
    # Flask-CORS turns into "reflect whatever Origin the caller sends, and allow credentials for
    # it" (confirmed live 2026-09-15: a request with `Origin: https://evil.example.com` got that
    # exact value back with `Access-Control-Allow-Credentials: true`) — i.e. every browser tab
    # anywhere could make a fully-credentialed cross-origin call and read the response. Auth here
    # is a bearer token / `X-Server-Key` header the frontend attaches itself, not a cookie, so
    # this did not enable classic session-riding CSRF — but `SERVER_PUBLIC_KEY` (the no-login
    # admin key shipped in every frontend bundle, "weak by design" per auth_middleware.py) is
    # exactly the kind of value a malicious *page* — not just a malicious *script* — could now
    # read the response for, on behalf of any visitor, with zero further access of its own.
    # Fix (BUG-0092): an explicit allowlist. `CORS_ALLOWED_ORIGINS` (comma-separated, same
    # convention as `PUBLIC_ASK_ALLOWED_ORIGINS` in server_public_ask_routes.py) overrides the
    # default, which covers the deployments already known to call cross-origin: the main
    # frontend calling a different server (virtualpytest.angelstreet.io -> rpitest.angelstreet.io
    # and back), the marketing site, the documented Vercel/Render split (cloud-setup.md §4.1),
    # and local dev. Anyone with a different split — a customer overlay's own domain, a
    # self-hoster's separate frontend host — MUST set `CORS_ALLOWED_ORIGINS` in their `.env` or
    # their frontend simply won't be able to call this server; there is no wildcard fallback any
    # more, on purpose (see docs/get-started/production-checklist.md).
    #
    # max_age caches the OPTIONS preflight response in the browser so cross-origin XHRs don't
    # double up with a per-request preflight. Chrome caps at 7200s (2 h), Firefox at 86400s
    # (24 h); set 86400 and let each browser apply its cap. Without this, every cross-origin
    # fetch fires its own OPTIONS round-trip and all those OPTIONS calls queue on the single
    # Gunicorn worker — turning ~30 page-load XHRs into ~60 server hits.
    cors_origins = _cors_allowed_origins()
    CORS(app, origins=cors_origins, supports_credentials=True, max_age=86400)

    # SocketIO: same allowlist as the HTTP CORS above (BUG-0092) — not a separate wildcard.
    # async_mode MUST match the gunicorn worker class. On Linux backend services
    # run with `worker_class='gevent'` (see gunicorn_app.py) and
    # gevent.monkey.patch_all() is called at import time, so use 'gevent' — that
    # is the mode that can actually serve RFC 6455 WebSocket frames. Fall back to
    # 'threading' on Windows where gevent isn't available; clients there
    # transparently use long-polling.
    #
    # Using async_mode='threading' under monkey-patched gevent silently breaks
    # ping/pong: Flask-SocketIO's "background thread" for heartbeats becomes a
    # non-cooperative greenlet that never gets scheduled while a long handler
    # (e.g. an LLM round-trip) is running, the client hits ping_timeout (~20s
    # default), disconnects, the server purges its room membership, and any
    # events emitted in the meantime are dropped. Under 'gevent', ping/pong is a
    # normal greenlet that yields cooperatively whenever any other greenlet does
    # I/O; ping_timeout is bumped well above any plausible LLM call so a slow
    # response can't masquerade as a dead connection.
    from flask_socketio import SocketIO
    if os.name == 'nt':
        socketio = SocketIO(app, cors_allowed_origins=cors_origins, async_mode='threading')
    else:
        socketio = SocketIO(
            app,
            cors_allowed_origins=cors_origins,
            async_mode='gevent',
            ping_interval=25,
            ping_timeout=120,
        )
    app.socketio = socketio

    return app

def validate_core_environment(mode='server'):
    """Validate only essential environment variables for startup"""
    print(f"🔍 Validating core {mode.upper()} environment variables...")
    
    if mode == 'server':
        required_vars = {
            'SERVER_URL': 'Server base URL',
            'SERVER_PORT': 'Server port number'
        }
    elif mode == 'host':
        required_vars = {
            'SERVER_URL': 'Server base URL',
            'HOST_NAME': 'Host identifier name'
        }
        # Note: HOST_PORT defaults to 6109 and HOST_URL is optional - auto-constructed from HOST_NAME if not provided
    else:
        print(f"⚠️ Unknown mode: {mode}")
        return False
    
    missing_vars = []
    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        if not value:
            missing_vars.append(f"{var_name} ({description})")
        else:
            display_value = '***' if 'TOKEN' in var_name else value
            print(f"  ✅ {var_name}: {display_value}")
    
    if missing_vars:
        print(f"❌ Missing required core variables:")
        for var in missing_vars:
            print(f"   - {var}")
        return False
    
    print(f"✅ Core {mode} environment variables validated")
    
    # Validate Supabase connectivity
    print(f"🔍 Validating Supabase connectivity...")
    
    # Log current Supabase configuration
    supabase_url = os.getenv('SUPABASE_URL', 'NOT SET')
    supabase_anon_key = os.getenv('SUPABASE_ANON_KEY', 'NOT SET')
    print(f"[@validate_env] 🔍 Supabase Configuration:")
    print(f"[@validate_env]    SUPABASE_URL: {supabase_url}")
    print(f"[@validate_env]    SUPABASE_ANON_KEY: {'SET (length=' + str(len(supabase_anon_key)) + ')' if supabase_anon_key != 'NOT SET' else 'NOT SET'}")
    
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        
        print(f"[@validate_env] 🔄 Initializing Supabase client...")
        supabase_client = get_supabase_client()
        
        if supabase_client is None:
            print(f"❌ Supabase client initialization failed")
            print(f"   Check SUPABASE_URL and SUPABASE_ANON_KEY environment variables")
            return False

        print(f"[@validate_env] ✅ Supabase client initialized")
        print(f"[@validate_env] 🔄 Testing database connectivity with 'teams' table query...")

        # Network may not be fully up immediately after boot — on Windows
        # the vpt-host Scheduled Task fires on auto-login before DHCP/DNS/
        # routing stabilise, and httpx's ConnectTimeout there bottoms out
        # at the OS's full SYN timeout (~21s on Windows), which would burn
        # the entire startup budget on a single attempt. Gate the real
        # Supabase round-trip behind a fast TCP probe and retry the probe
        # for up to ~30s before letting the actual query run. Once the
        # probe succeeds we proceed normally; if it never succeeds we let
        # the query below produce the canonical error/traceback and exit.
        import socket
        from urllib.parse import urlparse

        parsed_probe = urlparse(supabase_url)
        probe_host = parsed_probe.hostname or ''
        probe_port = parsed_probe.port or (443 if parsed_probe.scheme == 'https' else 80)
        probe_attempts = 6
        probe_delay = 5
        for attempt in range(1, probe_attempts + 1):
            try:
                with socket.create_connection((probe_host, probe_port), timeout=5):
                    if attempt > 1:
                        print(f"[@validate_env] ✅ Supabase TCP reachable on attempt {attempt}")
                    break  # network up — fall through to the real query
            except (OSError, socket.timeout) as probe_err:
                if attempt >= probe_attempts:
                    print(f"[@validate_env] ❌ Supabase TCP unreachable after "
                          f"{probe_attempts} attempts (~{probe_attempts * probe_delay}s budget): "
                          f"{type(probe_err).__name__}: {probe_err}")
                    break  # exit loop; the real query below will surface the error
                print(f"[@validate_env] ⏳ Supabase TCP not yet reachable "
                      f"(attempt {attempt}/{probe_attempts}, {probe_host}:{probe_port}): "
                      f"{probe_err}. Waiting {probe_delay}s for network to stabilise...")
                time.sleep(probe_delay)

        # Test database connectivity with a simple query
        try:
            # Try to query a system table that should always exist
            result = supabase_client.table('teams').select('id').limit(1).execute()
            print(f"[@validate_env] ✅ Query successful - received {len(result.data) if result.data else 0} rows")
            print(f"✅ Supabase database connectivity confirmed")
        except Exception as db_error:
            import traceback
            print(f"❌ Supabase database connection failed: {db_error}")
            print(f"[@validate_env] 🔍 Error Type: {type(db_error).__name__}")
            print(f"[@validate_env] 🔍 Error Details:")

            # Check for common error patterns
            error_str = str(db_error)
            if "Cannot assign requested address" in error_str or "Errno 99" in error_str:
                print(f"[@validate_env]    ⚠️ Network Error: Cannot assign requested address")
                print(f"[@validate_env]    This typically indicates:")
                print(f"[@validate_env]    1. Invalid SUPABASE_URL (wrong format or unreachable)")
                print(f"[@validate_env]    2. DNS resolution failure for: {supabase_url}")
                print(f"[@validate_env]    3. Network configuration preventing outbound connections")
                print(f"[@validate_env]    4. Firewall blocking HTTPS/443 to Supabase")

                # Try to parse the URL to help diagnose
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(supabase_url)
                    print(f"[@validate_env]    Parsed URL components:")
                    print(f"[@validate_env]       - Scheme: {parsed.scheme}")
                    print(f"[@validate_env]       - Hostname: {parsed.hostname}")
                    print(f"[@validate_env]       - Port: {parsed.port or 'default'}")

                    # Try DNS resolution
                    if parsed.hostname:
                        import socket
                        print(f"[@validate_env]    Attempting DNS resolution for: {parsed.hostname}")
                        try:
                            ip_address = socket.gethostbyname(parsed.hostname)
                            print(f"[@validate_env]       ✅ DNS resolved to: {ip_address}")
                        except socket.gaierror as dns_error:
                            print(f"[@validate_env]       ❌ DNS resolution failed: {dns_error}")
                except Exception as parse_error:
                    print(f"[@validate_env]    Could not parse URL: {parse_error}")

            # Print full traceback for debugging
            print(f"[@validate_env] 🔍 Full traceback:")
            traceback.print_exc()

            print(f"   Database may be unreachable or RLS policies may be blocking access")
            return False
            
    except Exception as e:
        import traceback
        print(f"❌ Supabase validation failed: {e}")
        print(f"[@validate_env] 🔍 Error Type: {type(e).__name__}")
        print(f"[@validate_env] 🔍 Full traceback:")
        traceback.print_exc()
        print(f"   Ensure Supabase client dependencies are installed")
        return False
    
    return True



# =====================================================
# LAZY LOADING FUNCTIONS
# =====================================================


# =====================================================
# FLASK-SPECIFIC HELPER FUNCTIONS
# =====================================================

def check_supabase():
    """Helper function to check if Supabase is available"""
    try:
        from flask import jsonify
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase_client = get_supabase_client()
        if supabase_client is None:
            return jsonify({'error': 'Supabase not available'}), 503
        return None
    except Exception:
        from flask import jsonify
        return jsonify({'error': 'Supabase not available'}), 503


def get_team_id():
    """Get team_id from request headers or use default for demo"""
    default_team_id = getattr(current_app, 'default_team_id', DEFAULT_TEAM_ID)
    return request.headers.get('X-Team-ID', default_team_id)

def get_user_id():
    """Get user_id from request headers - FAIL FAST if not provided"""
    user_id = request.headers.get('X-User-ID')
    if not user_id:
        raise ValueError('X-User-ID header is required but not provided')
    return user_id

# =====================================================
# CONSTANTS
# =====================================================

DEFAULT_TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
DEFAULT_USER_ID = "eb6cfd93-44ab-4783-bd0c-129b734640f3"