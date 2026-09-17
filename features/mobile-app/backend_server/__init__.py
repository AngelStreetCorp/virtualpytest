"""
mobile-app feature — backend_server part (TASK-17 W2).

Registered by shared/src/lib/utils/features.py when the feature is enabled
(docs/technical/FEATURES.md). Everything lives under /server/mobile-app.

Thin proxy in front of each host's own /host/phone/* blueprint (backend_host owns the
slots/pairings/tokens state — see features/mobile-app/backend_host, TASK-17 W1). This
blueprint only: (a) finds which registered hosts have phone_agent slots, (b) validates
host_name/device_id against the in-memory registry before forwarding, (c) calls the host
via the single sanctioned path `call_host()` (shared/src/lib/utils/build_url_utils.py),
and (d) hands back host_url/host_api_url from the SERVER's own registry, not whatever the
host reports, since those are what the calling browser/phone can actually reach.

Auth: /server/* is never zero-auth (docs/agent/platform/SERVER_AUTH.md §0-1 — the global
before_request guard already requires a service X-API-Key, a user JWT or SERVER_OPEN_MODE).
Pairing/unpairing a device is an admin action, so all three routes add @require_admin_role
on top — NOT @require_role('admin'), which admits only the 'admin' user role and so turned
away the X-API-Key principal ('service') that CI, provisioning and backend->backend callers
use. ADMIN_ROLES in auth_middleware is ('admin', 'service') for exactly this reason: the
service key already drives /host/* device control directly, so locking it out of an admin
route buys no safety. A tester or viewer JWT still gets 403. See BUG-0107 follow-up.
"""
from flask import Blueprint, request, jsonify

from backend_server.src.lib.auth_middleware import require_admin_role
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.server_utils import get_host_manager
from shared.src.lib.utils.build_url_utils import call_host

# features/mobile-app has a hyphen in its folder name, so it cannot be imported with an
# absolute `import features.mobile_app...` statement — relative import is the only option.
from ..lib import protocol

feature_mobile_app_bp = Blueprint('feature_mobile_app', __name__, url_prefix='/server/mobile-app')


def _phone_devices(host_info: dict) -> list:
    """Devices of this host that are phone_agent slots (may be empty)."""
    return [d for d in (host_info.get('devices') or []) if d.get('device_model') == protocol.DEVICE_MODEL]


def _host_call_failed(data, status: int) -> bool:
    return status != 200 or not isinstance(data, dict) or not data.get('success', True)


def _host_error(data, status: int) -> str:
    if isinstance(data, dict) and data.get('error'):
        return str(data['error'])
    return f'host returned HTTP {status}'


def _slots_for_host(host_info: dict, phone_devices: list) -> list:
    """Live slot states from the host, falling back to the registry's device list.

    One unreachable or misbehaving host must never fail the whole /hosts response — every
    failure path here returns the registry fallback with `slots_error` set instead of
    raising or propagating the host's status code.
    """
    fallback = [
        {'device_id': d.get('device_id'), 'device_name': d.get('device_name'), 'state': 'unknown'}
        for d in phone_devices
    ]
    host_name = host_info.get('host_name', 'unknown')
    try:
        data, status = call_host(host_info, '/host/phone/slots', method='GET', timeout=5)
    except Exception as e:  # noqa: BLE001 - call_host already catches network errors; belt for anything else
        print(f"[@route:mobile_app:list_hosts] slots call to {host_name} raised: {e}")
        return [{**s, 'slots_error': str(e)} for s in fallback]

    if _host_call_failed(data, status):
        error = _host_error(data, status)
        print(f"[@route:mobile_app:list_hosts] slots call to {host_name} failed: {error}")
        return [{**s, 'slots_error': error} for s in fallback]

    slots = data.get('slots')
    if not isinstance(slots, list):
        print(f"[@route:mobile_app:list_hosts] slots call to {host_name} returned no slots list")
        return [{**s, 'slots_error': 'malformed /host/phone/slots response'} for s in fallback]
    return slots


@feature_mobile_app_bp.route('/hosts', methods=['GET'], strict_slashes=False)
@require_admin_role
@handle_route_exceptions('mobile_app:list_hosts')
def list_hosts():
    """Hosts that have at least one phone_agent slot, with live slot states.

    ?team_id is accepted and ignored, same as the other /server/system routes — the host
    registry is not team-scoped today (see TASK-17 W2 instructions); do not add a filter.
    """
    request.args.get('team_id')  # accepted, intentionally unused — see docstring

    host_manager = get_host_manager()
    hosts_out = []
    for host_info in host_manager.get_all_hosts().values():
        phone_devices = _phone_devices(host_info)
        if not phone_devices:
            continue
        hosts_out.append({
            'host_name': host_info.get('host_name'),
            'host_url': host_info.get('host_url'),
            'host_api_url': host_info.get('host_api_url'),
            'status': host_info.get('status', 'online'),
            'slots': _slots_for_host(host_info, phone_devices),
        })

    return jsonify({'success': True, 'hosts': hosts_out})


@feature_mobile_app_bp.route('/pairings', methods=['POST'], strict_slashes=False)
@require_admin_role
@handle_route_exceptions('mobile_app:create_pairing')
def create_pairing():
    """Mint a one-time pairing token for one phone_agent slot.

    Body: {host_name, device_id}. Validates both against the registry before ever
    touching the network — 404 means "the server has never heard of that", which is a
    different failure than the host being unreachable.
    """
    payload = request.get_json(silent=True) or {}
    host_name = payload.get('host_name')
    device_id = payload.get('device_id')
    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'host_name and device_id are required'}), 400

    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if host_info is None:
        return jsonify({'success': False, 'error': f'host {host_name} not found'}), 404

    device = next((d for d in host_info.get('devices') or [] if d.get('device_id') == device_id), None)
    if device is None or device.get('device_model') != protocol.DEVICE_MODEL:
        return jsonify({
            'success': False,
            'error': f'{device_id} is not a {protocol.DEVICE_MODEL} device of {host_name}',
        }), 404

    data, status = call_host(host_info, '/host/phone/pairings', method='POST', data={'device_id': device_id})
    if _host_call_failed(data, status):
        error = _host_error(data, status)
        print(f"[@route:mobile_app:create_pairing] host {host_name} refused pairing of {device_id}: {error}")
        return jsonify({'success': False, 'error': error}), status or 502

    return jsonify({
        'success': True,
        'host_name': host_name,
        'device_id': device_id,
        'token': data.get('token'),
        'expires_at': data.get('expires_at'),
        # From the registry, not the host's own report — these are what the browser/phone
        # that will render the QR can actually reach (per TASK-17 W2 instructions).
        'host_url': host_info.get('host_url'),
        'host_api_url': host_info.get('host_api_url'),
    })


@feature_mobile_app_bp.route('/pairings/<host_name>/<device_id>', methods=['DELETE'], strict_slashes=False)
@require_admin_role
@handle_route_exceptions('mobile_app:delete_pairing')
def delete_pairing(host_name: str, device_id: str):
    """Revoke a slot's pairing (unpair). The host restores the placeholder frame."""
    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if host_info is None:
        return jsonify({'success': False, 'error': f'host {host_name} not found'}), 404

    data, status = call_host(host_info, f'/host/phone/slots/{device_id}', method='DELETE')
    if _host_call_failed(data, status):
        error = _host_error(data, status)
        print(f"[@route:mobile_app:delete_pairing] host {host_name} refused unpair of {device_id}: {error}")
        return jsonify({'success': False, 'error': error}), status or 502

    return jsonify({'success': True, 'host_name': host_name, 'device_id': device_id})


def register(app):
    app.register_blueprint(feature_mobile_app_bp)
