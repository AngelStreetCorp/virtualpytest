"""
Server Remote Routes

Server-side remote control proxy endpoints that forward requests to host remote controllers.
"""

from flask import Blueprint, request, jsonify, session
from backend_server.src.lib.utils.group_remote_utils import (
    fan_out,
    lock_blocker,
    per_target_mismatches,
    resolve_per_target_profiles,
    resolve_targets,
    skew_ms,
    validate_group,
)
from backend_server.src.lib.utils.lock_utils import get_device_lock_info, resolve_lock_owner
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.server_utils import get_host_manager
from shared.src.lib.config.remote_profiles import GROUP_MAX_SIZE
from shared.src.lib.utils.build_url_utils import call_host
from  backend_server.src.lib.utils.route_utils import proxy_to_host_with_params, get_host_from_request
import requests

# Create blueprint
server_remote_bp = Blueprint('server_remote', __name__, url_prefix='/server/remote')

# =====================================================
# REMOTE CONTROLLER ENDPOINTS
# =====================================================

@server_remote_bp.route('/takeScreenshot', methods=['POST'])
@handle_route_exceptions('remote:take_screenshot')
def take_screenshot():
    """Proxy take screenshot request to selected host"""
    print("[@route:server_remote:take_screenshot] Proxying take screenshot request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/takeScreenshot', 'POST', request_data, {})
    
    return jsonify(response_data), status_code
    
@server_remote_bp.route('/screenshotAndDump', methods=['POST'])
@handle_route_exceptions('remote:screenshot_and_dump')
def screenshot_and_dump():
    """Proxy screenshot and dump request to selected host"""
    print("[@route:server_remote:screenshot_and_dump] Proxying screenshot and dump request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/screenshotAndDump', 'POST', request_data, {})
    
    return jsonify(response_data), status_code
    
@server_remote_bp.route('/getApps', methods=['POST'])
@handle_route_exceptions('remote:get_apps')
def get_apps():
    """Proxy get apps request to selected host"""
    print("[@route:server_remote:get_apps] Proxying get apps request")

    # Get request data
    request_data = request.get_json() or {}

    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/getApps', 'POST', request_data, {})

    return jsonify(response_data), status_code

@server_remote_bp.route('/getOrientation', methods=['POST'])
@handle_route_exceptions('remote:get_orientation')
def get_orientation():
    """Proxy get orientation request to selected host"""

    # Get request data
    request_data = request.get_json() or {}

    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/getOrientation', 'POST', request_data, {})

    return jsonify(response_data), status_code
    
@server_remote_bp.route('/clickElement', methods=['POST'])
@handle_route_exceptions('remote:click_element')
def click_element():
    """Proxy click element request to selected host (for Appium controllers)"""
    print("[@route:server_remote:click_element] Proxying click element request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Extract host info and remove it from the data to be sent to host
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({
            'success': False,
            'error': error or 'Host information required'
        }), 400
    
    # Remove host from request data before sending to host (host doesn't need its own info)
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    
    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/clickElement', 'POST', host_request_data, {})
    
    return jsonify(response_data), status_code
    
@server_remote_bp.route('/tapCoordinates', methods=['POST'])
@handle_route_exceptions('remote:tap_coordinates')
def tap_coordinates():
    """Handle tap coordinates for mobile devices - centralized mobile control"""
    print("[@route:server_remote:tap_coordinates] Proxying tap coordinates request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Extract host info and remove it from the data to be sent to host
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({
            'success': False,
            'error': error or 'Host information required'
        }), 400
    
    # Remove host from request data before sending to host (host doesn't need its own info)
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    
    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/tapCoordinates', 'POST', host_request_data, {})
    
    return jsonify(response_data), status_code
    
@server_remote_bp.route('/streamTap', methods=['POST'])
@handle_route_exceptions('remote:stream_tap')
def stream_tap():
    """Handle stream tap with device coordinate conversion - mobile control integration"""
    data = request.get_json() or {}
    stream_x = data.get('stream_x')
    stream_y = data.get('stream_y')
    stream_width = data.get('stream_width')
    stream_height = data.get('stream_height')
    device_width = data.get('device_width')
    device_height = data.get('device_height')

    if not all([stream_x is not None, stream_y is not None,
               stream_width, stream_height, device_width, device_height]):
        return jsonify({
            'success': False,
            'error': 'Missing required parameters for stream tap conversion'
        }), 400

    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({
            'success': False,
            'error': error or 'Host information required'
        }), 400

    # Convert stream coordinates to device coordinates
    device_x = int((stream_x / stream_width) * device_width)
    device_y = int((stream_y / stream_height) * device_height)

    print(f"[@route:server_remote] Converting stream tap ({stream_x}, {stream_y}) to device coordinates ({device_x}, {device_y})")

    # Use the centralized tap coordinates handler
    return tap_coordinates_internal(host_info, device_x, device_y)
    
def tap_coordinates_internal(host, x, y):
    """Internal helper for tap coordinate handling"""
    # Use the centralized call_host() which automatically adds API key
    from shared.src.lib.utils.build_url_utils import call_host
    
    print(f"[@route:server_remote] Internal tap proxying via call_host(): ({x}, {y})")
    
    response_data, status_code = call_host(
        host,
        '/host/remote/tapCoordinates',
        method='POST',
        data={'x': x, 'y': y},
        timeout=30
    )
    
    return jsonify(response_data), status_code
        
def _describe_caller() -> str:
    """One-line identity of the requester for audit logs."""
    ip = ((request.headers.get('X-Real-IP') or '').strip()
          or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
          or request.remote_addr or '?')
    who = (getattr(request, 'user_email', None)
           or getattr(request, 'user_id', None) or 'anonymous')
    role = getattr(request, 'user_role', None) or '?'
    agent = (request.headers.get('User-Agent') or '?')[:80]
    return f"user={who} role={role} ip={ip} ua='{agent}' via=server"


@server_remote_bp.route('/executeCommand', methods=['POST'])
@handle_route_exceptions('remote:execute_command')
def execute_command():
    """Proxy execute command request to selected host"""
    print("[@route:server_remote:execute_command] Proxying execute command request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Extract host info and remove it from the data to be sent to host
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({
            'success': False,
            'error': error or 'Host information required'
        }), 400
    
    # Remove host from request data before sending to host (host doesn't need its own info)
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}

    # Destructive BLE re-pair: stamp who asked, from the server's own auth
    # state (never the client's payload), so the host audit log can name them.
    if host_request_data.get('command') == 'start_pairing':
        params = dict(host_request_data.get('params') or {})
        params['caller'] = _describe_caller()
        host_request_data['params'] = params
        print(f"[@route:server_remote:execute_command] start_pairing on "
              f"{request_data.get('host_name')}/{host_request_data.get('device_id')} "
              f"by {params['caller']}")

    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/executeCommand', 'POST', host_request_data, {})
    
    return jsonify(response_data), status_code
    
@server_remote_bp.route('/executeCommandGroup', methods=['POST'])
@handle_route_exceptions('remote:execute_command_group')
def execute_command_group():
    """Send one remote command to every device of a group.

    Body (TASK-76 + TASK-80):
      targets:      [{host_name, device_id, remote_profile?}, ...]   required
      remote_profile:  str  (optional, default for every target that has no
                            per-target override; required when no target carries
                            its own)
      command:      str                                              required
      params:       dict
      device_model: str  (optional; when set, all targets must share it;
                          skip the check by leaving it out for family groups)
      session_id / session_ids: see lock_blocker()

    Every target is validated against the profile it carries (or the default).
    Mismatched model / missing profile → 400 with one reason per offender. A
    device held by another session and user is skipped, never taken over. Sends
    run in parallel; `skew_ms` is the spread between devices. Each per-target
    result carries the `remote_profile` it used, so the frontend can render the
    per-cell chip and the audit log knows which transport was driven.
    """
    data = request.get_json() or {}
    targets = data.get('targets') or []
    command = data.get('command')
    params = data.get('params') or {}
    default_profile = data.get('remote_profile')

    if not targets or not command:
        return jsonify({'success': False, 'error': 'targets and command are required'}), 400
    if not default_profile and not any(t.get('remote_profile') for t in targets):
        return jsonify({'success': False, 'error': 'remote_profile is required (top-level or per target)'}), 400
    if len(targets) > GROUP_MAX_SIZE:
        return jsonify({'success': False, 'error': f'at most {GROUP_MAX_SIZE} devices per group'}), 400

    resolved, missing = resolve_targets(targets, get_host_manager().get_host)
    if missing:
        return jsonify({
            'success': False,
            'error': 'one or more targets not found in the host registry',
            'mismatches': missing,
        }), 400

    # Per-target profile + per-target validation. device_model is enforced only
    # when the caller sent it (TASK-76 single-profile behavior); the multi-profile
    # family-alias path leaves it None and enforces compatibility via
    # modelsAreCompatible at selection time (TASK-80 B).
    profiles = resolve_per_target_profiles(resolved, targets, default_profile)
    device_model = data.get('device_model')
    mismatches = per_target_mismatches(resolved, profiles, device_model)
    if mismatches:
        return jsonify({
            'success': False,
            'error': 'one or more targets do not match their profile',
            'mismatches': mismatches,
        }), 400

    # MCP auto-locks each device under its own session, so it sends them all in session_ids.
    session_ids = [data.get('session_id'), session.get('session_id'), *(data.get('session_ids') or [])]
    user_id, _ = resolve_lock_owner(data)
    jobs, skipped = [], []
    for (host, device), profile in zip(resolved, profiles):
        reason = lock_blocker(get_device_lock_info(device['host_name'], device['device_id']), session_ids, user_id)
        if reason:
            skipped.append({'host_name': device['host_name'], 'device_id': device['device_id'],
                            'remote_profile': profile,
                            'success': False, 'skipped': True, 'error': reason, 'ms': 0})
        else:
            jobs.append((host, device, profile))

    results = fan_out(
        jobs, command, params,
        lambda host, body: call_host(host, '/host/remote/executeCommand', method='POST', data=body),
    )
    print(f"[@route:server_remote:execute_command_group] {command} → "
          f"{len(profiles)} targets ({', '.join(sorted({p or '?' for p in profiles}))}): "
          f"{sum(r['success'] for r in results)}/{len(results)} ok, {len(skipped)} skipped, skew {skew_ms(results)}ms")
    return jsonify({
        'success': bool(results) and all(r['success'] for r in results) and not skipped,
        'device_model': device_model,
        'remote_profile': default_profile,
        'remote_profiles': sorted({p for p in profiles if p}),
        'results': results + skipped,
        'skew_ms': skew_ms(results),
    })


@server_remote_bp.route('/dumpUi', methods=['POST'])
@handle_route_exceptions('remote:dump_ui')
def dump_ui():
    """Dump UI elements without screenshot - for HDMI stream usage"""
    print("[@route:server_remote:dump_ui] Proxying dump UI request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Proxy to host
    response_data, status_code = proxy_to_host_with_params('/host/remote/dumpUi', 'POST', request_data, {})
    
    return jsonify(response_data), status_code
    