"""
Gunicorn Runtime Setup

Extracted from app.py - handles Gunicorn/SocketIO server startup, worker init,
metrics collection, and signal handling. Keeps app.py focused on orchestration.
"""

import os
import sys
import time
import signal
import threading

from backend_server.src.lib.utils.server_utils import get_server_system_stats
from shared.src.lib.database.system_metrics_db import store_system_metrics


def _resolve_ssl_context():
    """Resolve SSL certificate paths for local HTTPS development."""
    ssl_context = None
    user_home = os.path.expanduser('~')
    certificate_paths = [
        {'cert': f'{user_home}/vite-certs/fullchain.pem', 'key': f'{user_home}/vite-certs/privkey.pem'},
        {'cert': f'{user_home}/.ssl/cert.pem', 'key': f'{user_home}/.ssl/key.pem'},
        {'cert': '/usr/local/etc/ssl/certs/websockify.pem', 'key': '/usr/local/etc/ssl/certs/websockify.pem'},
        {'cert': '/etc/ssl/certs/websockify.pem', 'key': '/etc/ssl/certs/websockify.pem'},
        {'cert': os.getenv('SSL_CERT_PATH', ''), 'key': os.getenv('SSL_KEY_PATH', '')},
    ]
    ssl_enabled = os.getenv('SERVER_SSL_ENABLED', 'false').lower()
    if ssl_enabled == 'false':
        return None
    for paths in certificate_paths:
        if not paths['cert'] or not paths['key']:
            continue
        if os.path.exists(paths['cert']) and os.path.exists(paths['key']):
            try:
                with open(paths['cert'], 'r') as f:
                    f.read(1)
                with open(paths['key'], 'r') as f:
                    f.read(1)
                return (paths['cert'], paths['key'])
            except (IOError, PermissionError):
                continue
    return None


def _monitor_health():
    """Background thread for Render health monitoring."""
    time.sleep(10)
    while True:
        try:
            print("[@backend_server:monitor] ❤️ Health check - app still running")
            time.sleep(30)
        except Exception as e:
            print(f"[@backend_server:monitor] ❌ Health check failed: {e}")
            break


def _collect_server_metrics():
    """Background thread for server metrics collection (runs in worker)."""
    time.sleep(15)
    first_run = True
    while True:
        try:
            server_stats = get_server_system_stats(skip_speedtest=first_run)
            first_run = False
            try:
                success = store_system_metrics('server', server_stats)
                if success:
                    print("[@backend_server:metrics] 📊 Server metrics collected and stored")
                else:
                    print("[@backend_server:metrics] ❌ Server metrics storage returned False")
            except Exception as store_error:
                print(f"[@backend_server:metrics] ❌ Metrics storage exception: {store_error}")
                import traceback
                traceback.print_exc()
                raise
            current_time = time.time()
            next_minute = (int(current_time / 60) + 1) * 60
            time.sleep(next_minute - current_time)
        except Exception as e:
            print(f"[@backend_server:metrics] ❌ Metrics collection error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)


def run_server(app, on_signal, post_worker_init_callback=None):
    """
    Run the backend server with Gunicorn (or socketio.run fallback).

    Args:
        app: Flask app with socketio
        on_signal: Callback for graceful shutdown (SIGTERM/SIGINT)
        post_worker_init_callback: Called after worker init (e.g. start_agent_background_workers)
    """
    # Render injects PORT; local Docker/native installs use SERVER_PORT.
    server_port = int(os.getenv('PORT') or os.getenv('SERVER_PORT', '5109'))
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    ssl_context = _resolve_ssl_context()

    if not hasattr(app, 'socketio'):
        print("[@backend_server:start] ❌ SocketIO not initialized on app")
        sys.exit(1)

    socketio = app.socketio
    shutdown_attempts = {'count': 0}

    def signal_handler(signum, frame):
        shutdown_attempts['count'] += 1
        attempt = shutdown_attempts['count']
        if attempt == 1:
            print(f"[@backend_server:start] 🛑 Received signal {signum}, shutting down gracefully... (attempt {attempt}/3)")
            try:
                on_signal()
            except Exception as e:
                print(f"[@backend_server:cleanup] ⚠️ Cleanup error: {e}")
        elif attempt == 2:
            print(f"[@backend_server:start] 🛑 Still shutting down... (attempt {attempt}/3)")
        else:
            print(f"[@backend_server:start] ☠️ Force killing process (attempt {attempt}/3)")
            os._exit(1)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    def post_worker_init(worker):
        print(f"[@backend_server:worker] 🚀 Worker {worker.pid} initialized")
        metrics_thread = threading.Thread(target=_collect_server_metrics, daemon=True)
        metrics_thread.start()
        if post_worker_init_callback:
            post_worker_init_callback()
            print(f"[@backend_server:worker] 🤖 Agent background workers started in worker {worker.pid}")

    run_kwargs = {
        'host': '0.0.0.0',
        'port': server_port,
        'debug': debug_mode,
        'allow_unsafe_werkzeug': True,
        'log_output': True,
        'use_reloader': False,
    }
    if ssl_context:
        run_kwargs['ssl_context'] = ssl_context

    worker_class = 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker'

    try:
        import gunicorn.app.base
        from gunicorn.util import load_class

        # Pre-flight: gunicorn's Arbiter catches a bad/missing worker class as a
        # RuntimeError and calls sys.exit(1) itself, bypassing our handlers and
        # the start_server() except block — so the failure shows up only as a
        # bare gunicorn traceback. Validate the worker class up front so the
        # error is actionable.
        try:
            load_class(worker_class)
        except Exception as e:
            print(f"[@backend_server:start] ❌ Cannot load gunicorn worker class '{worker_class}': {e}")
            print("[@backend_server:start] 👉 Fix: reinstall server deps into the venv — "
                  "pip install -r backend_server/requirements.txt "
                  "(missing 'gevent-websocket')")
            sys.exit(1)

        class StandaloneApplication(gunicorn.app.base.BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                config = {k: v for k, v in self.options.items()
                         if k in self.cfg.settings and v is not None}
                for key, value in config.items():
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        options = {
            'bind': f'0.0.0.0:{server_port}',
            'workers': 1,
            'threads': 1,
            'timeout': 3600,
            'worker_class': worker_class,
            'loglevel': 'info',
            'accesslog': '-',
            'errorlog': '-',
            'capture_output': False,
            'preload_app': True,
            'post_worker_init': post_worker_init,
        }

        if os.getenv('RENDER', 'false').lower() == 'true':
            monitor_thread = threading.Thread(target=_monitor_health, daemon=True)
            monitor_thread.start()

        StandaloneApplication(app, options).run()

    except ImportError:
        print("[@backend_server:start] ⚠️ Gunicorn/gevent unavailable. Falling back to socketio.run()")
        socketio.run(app, **run_kwargs)
