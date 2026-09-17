#!/usr/bin/env python3
"""
VirtualPyTest Backend Host Application

This application runs the hardware interface service for VirtualPyTest.
It provides device control capabilities and hardware abstraction.

Usage:
    python3 app.py

Environment Variables:
    Required:
        HOST_NAME - Logical hostname for this host (e.g., host2)

    Optional (with defaults):
        HOST_PORT - Port where Flask app runs (default: 6109)
        HOST_URL - Base URL path for this host (default: auto-constructed from HOST_NAME)
                   Used by frontend to build API/stream URLs
        DEBUG - Set to 'true' to enable debug mode (default: false)
"""

import sys
import os
import time
import atexit
import threading
from dotenv import load_dotenv

# Windows services often run under a legacy codepage (e.g. cp1252) which will crash
# on non-ASCII output (emojis) during startup. Prefer UTF-8 everywhere.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Setup path for shared library access
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_host_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(backend_host_dir)

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
if backend_host_dir not in sys.path:
    sys.path.insert(0, backend_host_dir)

# Add backend_host/src to path for local imports
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables from .env file
# First try custom ENV_FILE path (for VM-specific configs), then fallback to current directory
# Use utf-8-sig encoding to handle Windows BOM (Byte Order Mark) transparently
env_file = os.getenv('ENV_FILE')
if env_file and os.path.exists(env_file):
    load_dotenv(env_file, encoding='utf-8-sig')
    print(f"[@backend_host:main] Loaded environment from: {env_file}")
else:
    # Fallback to default .env in current directory
    load_dotenv(encoding='utf-8-sig')
    print(f"[@backend_host:main] Loaded environment from default .env file")

# Import from shared library and backend_host (using clear import paths)
try:
    # Import shared components
    from shared.src.lib.utils.app_utils import (
        load_environment_variables,
        kill_process_on_port,
        setup_flask_app,
        validate_core_environment,
        DEFAULT_USER_ID
    )
    # Import backend_host controllers and services
    from controllers import *
    from services import *
except ImportError as e:
    print(f"❌ Failed to import dependencies: {e}")
    print("❌ Please ensure shared library and backend_host are properly installed")
    print("❌ Run: ./setup/local/install_all.sh")
    sys.exit(1)

# Local route imports  
try:
    from  backend_host.src.lib.utils.host_utils import (
        register_host_with_server,
        start_ping_thread,
        start_metrics_thread,
        cleanup_on_exit
    )
except ImportError as e:
    print(f"❌ Failed to import host utilities: {e}")
    print("❌ Please ensure shared library is properly installed")
    sys.exit(1)

class _StreamAccessLogFilter:
    """Transparent stdio wrapper that drops gevent WSGI access-log lines for HLS
    stream requests (segments, playlists, capture frames). Everything else —
    our print() logs, tracebacks, access logs for real routes — passes through
    untouched."""

    _NOISE = ('/stream/', '/segments/', '.m3u8', '.ts ')

    def __init__(self, target):
        self._target = target

    def write(self, s):
        if s and ('"GET ' in s or '"HEAD ' in s) and any(n in s for n in self._NOISE):
            return len(s)  # pretend we wrote it
        return self._target.write(s)

    def __getattr__(self, name):
        # Delegate flush/fileno/isatty/etc. to the wrapped stream.
        return getattr(self._target, name)


def _install_stream_access_log_filter():
    """Wrap sys.stdout/sys.stderr so HLS stream access logs are suppressed."""
    sys.stdout = _StreamAccessLogFilter(sys.stdout)
    sys.stderr = _StreamAccessLogFilter(sys.stderr)
    print("[@backend_host:main] 🔇 HLS stream access logs suppressed")


def register_host_routes(app):
    """Register all host routes - Hardware interface endpoints"""
    print("[@backend_host:routes] Loading host routes...")
    
    try:
        from routes.registry import blueprint_registry
        print("[@backend_host:routes] ✅ All route imports completed successfully!")
    except ImportError as e:
        print(f"[@backend_host:routes] ❌ CRITICAL: Cannot import host routes: {e}")
        print("[@backend_host:routes] ❌ This indicates missing dependencies or import path issues")
        import traceback
        traceback.print_exc()
        return False

    # Register all host blueprints
    for blueprint, description in blueprint_registry:
        try:
            app.register_blueprint(blueprint)
            print(f"✅ Registered {description}")
        except Exception as e:
            print(f"❌ Failed to register {description}: {e}")
            return False

    # Optional features (features/<name>/backend_host/register(app)); see docs/technical/FEATURES.md.
    from shared.src.lib.utils.features import register_feature_blueprints
    register_feature_blueprints(app, 'backend_host')

    return True

def setup_host_cleanup():
    """Setup cleanup handlers for host"""
    def cleanup():
        print("[@host:main:cleanup] Cleaning up host resources...")
        cleanup_on_exit()
    
    atexit.register(cleanup)

_background_services_lock = threading.Lock()
_background_services_started_pid: int | None = None

def start_background_services():
    """Start background services for host communication"""
    global _background_services_started_pid
    current_pid = os.getpid()
    with _background_services_lock:
        if _background_services_started_pid == current_pid:
            print(f"[@backend_host:main] Background services already started in PID {current_pid}, skipping")
            return
        _background_services_started_pid = current_pid

    def start_services():
        print(f"[@backend_host:main] Starting background services in PID {current_pid}")
        try:
            time.sleep(2)  # Wait for Flask to start
            initial_registration_ok = register_host_with_server()
            if not initial_registration_ok:
                print(
                    "⚠️ [HOST] Initial registration failed. "
                    "Background ping/reconnect loop will keep retrying."
                )
        except Exception as e:
            print(f"❌ [HOST] Registration error: {e}")
        
        # ALWAYS start ping thread - even if registration failed
        # This ensures auto-reconnect when server comes back up
        try:
            start_ping_thread()
        except Exception as e:
            print(f"❌ [HOST] Failed to start ping thread: {e}")

        # Metrics collection runs on its own thread so its database round-trips
        # can never delay a ping and get this host evicted (BUG-0093).
        try:
            start_metrics_thread()
        except Exception as e:
            print(f"❌ [HOST] Failed to start metrics thread: {e}")
        
        # Start deployment scheduler
        try:
            from backend_host.src.services.deployment_scheduler import get_deployment_scheduler
            print("[@backend_host:main] Starting deployment scheduler...")
            scheduler = get_deployment_scheduler()
            print("[@backend_host:main] ✓ Deployment scheduler started")
        except Exception as e:
            print(f"[@backend_host:main] ⚠️  Deployment scheduler not available: {e}")
        
        # Note: KPI measurement service is started in main() at Step 4.1
    
    thread = threading.Thread(target=start_services, daemon=True)
    thread.start()

def cleanup_host_ports():
    """Clean up any processes using host ports"""
    host_port = get_host_port()
    kill_process_on_port(host_port)

def setup_api_authentication(app):
    """Setup global API key authentication for all /host/* routes"""
    from flask import request, jsonify
    from shared.src.lib.utils.auth_utils import validate_api_key
    
    # Endpoints exempt from authentication
    HEALTH_CHECK_ENDPOINTS = [
        '/health',
        '/host/system/health',
        '/host/actions/health',
        '/host/navigation/health',
    ]
    
    # Public media paths that don't require authentication
    PUBLIC_MEDIA_PATHS = [
        '/stream/',           # Direct stream access (no nginx)
        '/host/stream/',      # Stream access via nginx proxy
    ]
    
    @app.before_request
    def check_api_key():
        """Global API key check for all /host/* routes"""
        # Only check /host/* routes (not health checks or other endpoints)
        if not request.path.startswith('/host/'):
            return None
        
        # Exempt health check endpoints from authentication
        if request.path in HEALTH_CHECK_ENDPOINTS:
            return None
        
        # Exempt public media files from authentication
        for public_path in PUBLIC_MEDIA_PATHS:
            if request.path.startswith(public_path):
                return None
        
        # Validate API key
        is_valid, error_response = validate_api_key()
        
        if not is_valid:
            print(f"[@backend_host:auth] ❌ API key validation failed for {request.path}")
            print(f"[@backend_host:auth]    From: {request.remote_addr}")
            print(f"[@backend_host:auth]    Reason: {error_response.get('message')}")
            return jsonify(error_response), 401
        
        # Valid API key - allow request to proceed
        return None

def get_host_port():
    """Get the host port, prioritizing explicit environment settings"""
    import os

    # Check if HOST_PORT is explicitly set in environment (highest priority)
    host_port_str = os.getenv('HOST_PORT')
    if host_port_str and host_port_str.strip():
        try:
            host_port = int(host_port_str)
            print(f"[@get_host_port] Using HOST_PORT from environment: {host_port}")
            return host_port
        except ValueError:
            print(f"[@get_host_port] Invalid HOST_PORT value '{host_port_str}', using default 6109")
    else:
        print(f"[@get_host_port] HOST_PORT not set, using default: 6109")

    return 6109

def parse_host_api_url():
    """Parse HOST_API_URL to extract IP and port for binding"""
    import os
    from urllib.parse import urlparse

    # Check if HOST_API_URL is set
    host_api_url = os.getenv('HOST_API_URL')
    if host_api_url and host_api_url.strip():
        try:
            parsed = urlparse(host_api_url)

            # Extract hostname (IP or domain)
            hostname = parsed.hostname
            if hostname and hostname != '0.0.0.0':
                # Extract port if present
                port = parsed.port
                print(f"[@parse_host_api_url] Parsed from HOST_API_URL: {hostname}:{port if port else 'default'}")
                return hostname, port
        except Exception as e:
            print(f"[@parse_host_api_url] Failed to parse HOST_API_URL '{host_api_url}': {e}")

    return None, None

def detect_host_ip():
    """Detect the host machine's primary network IP address"""
    import os
    import subprocess

    # Priority 1: Parse from HOST_API_URL (if set)
    parsed_ip, _ = parse_host_api_url()
    if parsed_ip:
        print(f"[@detect_host_ip] Using IP from HOST_API_URL: {parsed_ip}")
        return parsed_ip

    # Priority 2: Check if HOST_IP is explicitly set in environment
    host_ip = os.getenv('HOST_IP')
    if host_ip and host_ip != '0.0.0.0' and host_ip.strip():
        print(f"[@detect_host_ip] Using HOST_IP from environment: {host_ip}")
        return host_ip

    # Try hostname -I (most reliable for primary IP)
    try:
        result = subprocess.run(['hostname', '-I'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            # hostname -I returns space-separated IPs, take the first one
            ips = result.stdout.strip().split()
            if ips:
                ip = ips[0]
                if not ip.startswith('127.'):
                    return ip
    except:
        pass

    # Fallback: try ip route
    try:
        result = subprocess.run(['ip', 'route', 'get', '8.8.8.8'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            import re
            ip_match = re.search(r'src (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if ip_match:
                ip = ip_match.group(1)
                if not ip.startswith('127.'):
                    return ip
    except:
        pass

    # Try macOS-specific detection (en0, en1, etc.)
    try:
        result = subprocess.run(['/sbin/ifconfig'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            import re
            # Look for active en0-en9 interfaces with inet addresses
            for interface_num in range(10):  # Check en0 through en9
                interface_name = f"en{interface_num}"
                # Match interface name followed by inet IP
                pattern = f'{interface_name}:.*?inet (\\d+\\.\\d+\\.\\d+\\.\\d+)'
                ip_match = re.search(pattern, result.stdout, re.DOTALL)
                if ip_match:
                    ip = ip_match.group(1)
                    if not ip.startswith('127.'):
                        return ip
    except:
        pass

    # Last fallback
    print("[@backend_host:main] ⚠️  Could not detect host IP, using localhost")
    return "127.0.0.1"

def main():
    """Main function for backend_host application"""
    print("🏠 VIRTUALPYTEST backend_host")
    print("Starting VirtualPyTest Hardware Interface Service")

    # STEP 1: Validate Environment
    print("[@backend_host:main] Step 1: Validating environment...")
    calling_script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = load_environment_variables(mode='host', calling_script_dir=calling_script_dir)
    
    if not validate_core_environment(mode='host'):
        print("[@backend_host:main] ❌ Core environment validation failed")
        sys.exit(1)

    # STEP 1.5: Detect Host IP
    print("[@backend_host:main] Step 1.5: Detecting host IP...")
    detected_host_ip = detect_host_ip()
    print(f"[@backend_host:main] 📡 Detected host IP: {detected_host_ip}")

    # Print database URL for verification
    supabase_url = os.getenv('SUPABASE_URL', 'NOT SET')
    print(f"[@backend_host:main] 🗄️  Database Configuration:")
    print(f"[@backend_host:main]    SUPABASE_URL: {supabase_url}")
    print("[@backend_host:main] ✅ Environment validated")
    
    # STEP 2: Setup Flask App
    print("[@backend_host:main] Step 2: Setting up Flask application...")
    cleanup_host_ports()
    time.sleep(1)
    
    # STEP 2.1: Clear navigation file cache on startup
    print("[@backend_host:main] Step 2.1: Clearing navigation file cache...")
    try:
        from shared.src.lib.utils.navigation_cache import clear_unified_cache
        clear_unified_cache()  # Clear all file caches
        print("[@backend_host:main] ✅ Navigation file cache cleared")
    except Exception as e:
        print(f"[@backend_host:main] ⚠️  Failed to clear navigation cache: {e}")
    
    app = setup_flask_app("VirtualPyTest-backend_host")

    # Store detected host info in app context for use by controllers
    app.host_ip = detected_host_ip
    app.host_port = get_host_port()
    app.host_name = os.getenv('HOST_NAME', 'unknown-host')

    # STEP 3: Register Routes
    # Add /health alias route for consistency with server
    def health_alias():
        """Health check alias at root level for consistency with server"""
        from flask import jsonify, current_app
        import time
        return jsonify({
            'status': 'ok',
            'timestamp': time.time(),
            'mode': 'host',
            'host_name': current_app.host_name,
            'supabase': 'test'
        }), 200

    app.add_url_rule('/health', 'health_alias', health_alias, methods=['GET'])
    print("[@backend_host:main] Step 3: Registering hardware interface routes...")
    if not register_host_routes(app):
        print("[@backend_host:main] ❌ CRITICAL: Failed to register host routes")
        print("[@backend_host:main] ❌ Cannot start host without all routes properly loaded")
        sys.exit(1)

    with app.app_context():
        app.default_user_id = DEFAULT_USER_ID

        # STEP 2.5: Initialize host devices with executors
        print("[@backend_host:main] Step 2.5: Initializing host devices with executors...")
        try:
            from backend_host.src.controllers.controller_manager import get_host

            host = get_host()

            # Create device registry for routes to access
            app.host_devices = {}
            for device in host.get_devices():
                app.host_devices[device.device_id] = device
                print(f"[@backend_host:main] ✓ Registered device: {device.device_id} ({device.device_model})")

                # Verify executors were created
                if hasattr(device, 'action_executor') and device.action_executor:
                    print(f"[@backend_host:main]   ✓ ActionExecutor ready")
                if hasattr(device, 'navigation_executor') and device.navigation_executor:
                    print(f"[@backend_host:main]   ✓ NavigationExecutor ready")
                if hasattr(device, 'verification_executor') and device.verification_executor:
                    print(f"[@backend_host:main]   ✓ VerificationExecutor ready")
                if hasattr(device, 'standard_block_executor') and device.standard_block_executor:
                    print(f"[@backend_host:main]   ✓ StandardBlockExecutor ready")
                if hasattr(device, 'ai_executor') and device.ai_executor:
                    print(f"[@backend_host:main]   ✓ AIExecutor ready")

            print(f"[@backend_host:main] ✅ Initialized {len(app.host_devices)} devices with executors")

        except Exception as e:
            print(f"[@backend_host:main] ⚠️  Failed to initialize host devices: {e}")
            print(f"[@backend_host:main]    Continuing with limited functionality...")
            import traceback
            traceback.print_exc()

            # Initialize empty device registry to prevent route errors
            app.host_devices = {}
            print(f"[@backend_host:main] ⚠️  Host initialized with 0 devices - some routes may not work")
    
    # STEP 3.5: Setup Global API Key Authentication
    print("[@backend_host:main] Step 3.5: Setting up API key authentication...")
    setup_api_authentication(app)
    print("[@backend_host:main] ✅ API key authentication enabled for all /host/* routes")
    
    # STEP 4: Start Host Services
    print("[@backend_host:main] Step 4: Starting host services...")
    setup_host_cleanup()
    
    # STEP 4.1: KPI Executor runs as separate systemd service (kpi-executor.service)
    print("[@backend_host:main] Step 4.1: KPI Executor")
    print("[@backend_host:main]   Note: KPI Executor runs as separate service (backend_host/scripts/kpi_executor.py)")
    print("[@backend_host:main]   Queue: JSON files in /tmp/kpi_queue/")
    
    # Get configuration
    host_port = get_host_port()
    debug_mode = os.getenv('DEBUG', 0) == 1
    host_name = os.getenv('HOST_NAME', 'unknown-host')
    
    # Auto-construct HOST_URL from HOST_NAME (or allow override)
    host_url = os.getenv('HOST_URL')
    if not host_url:
        host_url = f"/host/{host_name}"
        print(f"[@backend_host:main] Auto-constructed HOST_URL: {host_url}")
    
    print(f"[@backend_host:main] Host Information:")
    print(f"[@backend_host:main]    Host Name: {host_name}")
    print(f"[@backend_host:main]    Host URL: {host_url}")
    print(f"[@backend_host:main]    Host Port: {host_port}")

    # Start Flask application
    print("[@backend_host:main] 🎉 backend_host ready!")
    print(f"[@backend_host:main] 🚀 Starting hardware interface on port {host_port}")
    
    # Drop HLS access-log noise. gevent's WSGI server logs every HTTP request to
    # the stdio stream; the HLS player polls segments/playlists many times per
    # second per device, so these lines bury everything else in journalctl and
    # carry no diagnostic value. Filter them out at the stream level. Must run
    # before socketio.run() so gevent captures the wrapped stream.
    _install_stream_access_log_filter()

    try:
        # HOST_BIND_IP overrides the detected address (containers bind 0.0.0.0 so that
        # the healthcheck on localhost and the published port both reach the app while
        # HOST_API_URL keeps naming the address other services use).
        bind_ip = (os.getenv('HOST_BIND_IP') or '').strip() or detect_host_ip()
        print(f"[@backend_host:main] 🔌 Binding to: {bind_ip}:{host_port}")
        print("[@backend_host:main] Using single-process SocketIO server to keep host scheduler singleton")
        try:
            socketio = getattr(app, 'socketio', None)
            if socketio is None:
                raise RuntimeError("SocketIO not initialized on app (app.socketio missing)")
            start_background_services()
            socketio.run(
                app,
                host=bind_ip,
                port=host_port,
                debug=debug_mode,
                allow_unsafe_werkzeug=True,
                use_reloader=False,
                log_output=True,
            )
        except Exception as e:
            print(f"[@backend_host:main] ❌ Error starting host server: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    except KeyboardInterrupt:
        print(f"[@backend_host:main] 🛑 backend_host shutting down...")
    except Exception as e:
        print(f"[@backend_host:main] ❌ Error starting backend_host: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print(f"[@backend_host:main] 👋 backend_host application stopped")

if __name__ == '__main__':
    main()
