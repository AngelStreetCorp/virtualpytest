"""
features/mobile-app/backend_host — host side of TASK-17 phone-as-device (see
docs/tasks/TASK-17-mobile-app-phone-agent.md §1, §3, §5 row W1).

register(app) is called by shared/src/lib/utils/features.py from
backend_host/src/app.py's register_host_routes() (Step 3), which runs *before*
Step 2.5 creates device controllers — so register_remote_implementation() here is
already visible when controller_manager builds a phone_agent device (C1/C2 in the
task doc; controller_registry.py is the core hook).
"""
from flask import Blueprint, jsonify, request

from .bridge import get_bridge
from .controllers.phone_agent import PhoneAgentRemoteController
from .controllers.phone_ui_verification import PhoneAgentAdbVerificationController
from ..lib import protocol

_LOG = '[@mobile-app:backend_host]'

phone_bp = Blueprint('mobile_app_phone', __name__, url_prefix='/host/phone')


def register(app) -> None:
    from backend_host.src.controllers.controller_registry import register_remote_implementation

    bridge = get_bridge(app, getattr(app, 'socketio', None))

    register_remote_implementation(
        protocol.REMOTE_IMPLEMENTATION,
        factory=lambda **params: PhoneAgentRemoteController(**params),
        params_builder=lambda device_config: {
            'device_id': device_config['device_id'],
            'device_name': device_config.get('device_name', device_config['device_id']),
            'bridge': bridge,
        },
    )

    _register_phone_verification(bridge)

    app.register_blueprint(phone_bp)
    # Every route below is under /host/, which backend_host/src/app.py's
    # setup_api_authentication() before_request already gates with X-API-Key for
    # every /host/* path (checked directly - see TASK-17 W1 final report) - no
    # separate auth wiring needed here.
    print(f"{_LOG} REST blueprint registered at /host/phone (protected by the host's global X-API-Key check)")

    socketio = getattr(app, 'socketio', None)
    if socketio is None:
        print(f"{_LOG} app.socketio missing - Socket.IO handlers NOT registered (REST-only; fine for a bare test app)")
        return

    _register_socketio_handlers(socketio, bridge)
    print(f"{_LOG} Socket.IO handlers registered on namespace {protocol.NAMESPACE}")


def register_controllers() -> None:
    """Second registration path, for host processes that have no Flask app.

    Every script runs as its own subprocess (ScriptExecutor._execute_script_subprocess)
    and builds its own controllers, so register(app) above never runs there and a
    phone_agent device used to come up with no remote controller at all. Here the
    controller is wired to RemoteBridgeClient instead, which calls back into vpt-host
    where the phone's socket actually lives.

    Called by shared/src/lib/utils/features.py::register_feature_controllers() from
    controller_manager.create_host_from_environment(). Inside vpt-host that call comes
    *after* register(app), so this bails out rather than replacing the real in-process
    bridge with an HTTP client pointed at ourselves - which would be both pointless and
    a deadlock risk on a host running a single gevent worker.
    """
    from backend_host.src.controllers.controller_registry import (
        get_remote_implementation, register_remote_implementation,
    )
    if get_remote_implementation(protocol.REMOTE_IMPLEMENTATION) is not None:
        return

    from .remote_bridge import RemoteBridgeClient
    bridge = RemoteBridgeClient()

    register_remote_implementation(
        protocol.REMOTE_IMPLEMENTATION,
        factory=lambda **params: PhoneAgentRemoteController(**params),
        params_builder=lambda device_config: {
            'device_id': device_config['device_id'],
            'device_name': device_config.get('device_name', device_config['device_id']),
            'bridge': bridge,
        },
    )
    _register_phone_verification(bridge)
    print(f"{_LOG} phone_agent remote registered against {bridge.base_url} (no app in this process)")



def _register_phone_verification(bridge) -> None:
    """Back the 'adb' verification type with the phone's accessibility tree, for phone_agent
    devices only — android_mobile keeps the real ADB controller. This is what lets a navigation
    tree written for an Android phone (its screen checks are `verification_type: 'adb'`) run
    unchanged against a paired one."""
    from backend_host.src.controllers.controller_registry import register_verification_implementation

    register_verification_implementation(
        protocol.REMOTE_IMPLEMENTATION,
        'adb',
        factory=lambda **params: PhoneAgentAdbVerificationController(bridge=bridge, **params),
    )


def _client_ip() -> str:
    """Real client IP for the hello-lockout counter (TASK-19 P0 #2).

    nginx's phone socket.io location already sets X-Forwarded-For (infra/proxy/nginx/config/
    production-https.conf) - trust its first hop over request.remote_addr, which behind the
    proxy would otherwise be nginx's own address and merge every caller into one bucket.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


def _register_socketio_handlers(socketio, bridge) -> None:
    def _delayed_disconnect(sid):
        # Disconnecting synchronously inside the hello handler races the ack packet
        # flask_socketio sends right after the handler returns: python-socketio's
        # Server.disconnect() marks the sid gone before that ack is flushed, so the
        # client never sees {ok:false, error} — only a bare transport drop. A short
        # background delay lets the ack land first; the client still ends up
        # disconnected, per spec.
        import time
        time.sleep(0.2)
        socketio.server.disconnect(sid, namespace=protocol.NAMESPACE)

    @socketio.on(protocol.EV_HELLO, namespace=protocol.NAMESPACE)
    def _on_hello(payload):
        ack = bridge.handle_hello(request.sid, payload or {}, client_ip=_client_ip())
        if not ack.get('ok'):
            print(f"{_LOG} hello rejected: {ack.get('error')}")
            socketio.start_background_task(_delayed_disconnect, request.sid)
        return ack

    @socketio.on(protocol.EV_FRAME, namespace=protocol.NAMESPACE)
    def _on_frame(meta, jpeg_bytes):
        bridge.handle_frame(request.sid, meta or {}, jpeg_bytes)

    @socketio.on(protocol.EV_STATUS, namespace=protocol.NAMESPACE)
    def _on_status(payload):
        bridge.handle_status(request.sid, payload or {})

    @socketio.on('disconnect', namespace=protocol.NAMESPACE)
    def _on_disconnect():
        bridge.handle_disconnect(request.sid)


# ---- REST: /host/phone/* ---------------------------------------------------

def _connect_info() -> dict:
    import os
    return {
        'host_name': os.getenv('HOST_NAME', 'unknown-host'),
        'host_api_url': os.getenv('HOST_API_URL', ''),
        'host_url': os.getenv('HOST_URL', ''),
    }


@phone_bp.route('/pairings', methods=['POST'])
def create_pairing():
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400

    pairing = get_bridge().create_pairing(device_id)
    if pairing is None:
        return jsonify({'success': False, 'error': f'no phone_agent slot {device_id}'}), 404

    return jsonify({
        'success': True,
        'token': pairing['token'],
        'expires_at': pairing['expires_at'],
        'device_id': device_id,
        'connect': _connect_info(),
    })


@phone_bp.route('/rpc', methods=['POST'])
def phone_rpc():
    """Run one phone command for a caller that is not this process.

    The Socket.IO session to the phone belongs to this app, so a script subprocess
    cannot command the phone directly; RemoteBridgeClient posts here and gets the
    bridge's ack back verbatim. A refused command is still HTTP 200 - callers read
    `ok`, exactly as they would from PhoneBridge.rpc().
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id')
    name = data.get('name')
    if not device_id or not name:
        return jsonify({'ok': False, 'error': 'device_id and name are required'}), 400
    timeout = data.get('timeout')
    ack = get_bridge().rpc(device_id, name, data.get('params') or {},
                           float(timeout) if timeout else None)
    return jsonify(ack)


@phone_bp.route('/slots', methods=['GET'])
def list_slots():
    return jsonify({'success': True, 'slots': get_bridge().list_slots()})


@phone_bp.route('/slots/<device_id>', methods=['GET'])
def get_slot(device_id):
    slot = get_bridge().get_slot(device_id)
    if not slot:
        return jsonify({'success': False, 'error': f'no phone_agent slot {device_id}'}), 404
    return jsonify({'success': True, 'slot': slot.summary()})


@phone_bp.route('/slots/<device_id>', methods=['DELETE'])
def unpair_slot(device_id):
    if not get_bridge().unpair(device_id):
        return jsonify({'success': False, 'error': f'no phone_agent slot {device_id}'}), 404
    return jsonify({'success': True, 'device_id': device_id})
