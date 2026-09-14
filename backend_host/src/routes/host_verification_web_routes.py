"""
Host Verification Web Routes

Host-side web verification endpoints (Playwright web element-based verifications).
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_handlers import get_verification_controller

# Create blueprint
host_verification_web_bp = Blueprint('host_verification_web', __name__, url_prefix='/host/verification/web')


def _run_async(coro):
    """Run async coroutine using asyncio.run() — same pattern as host_web_routes."""
    import asyncio
    return asyncio.run(coro)


@host_verification_web_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def web_verification_execute():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    verification = data.get('verification', {})

    command = verification.get('command')
    params = verification.get('params', {})

    print(f"[@route:host_verification_web:execute] Web verification request: {command}, device: {device_id}")

    # Get web controller using helper
    web_controller, _, error_response = get_verification_controller(device_id, 'web')
    if error_response:
        return error_response

    # Check if controller has execute_verification method
    if not hasattr(web_controller, 'execute_verification'):
        return jsonify({
            'success': False,
            'error': 'Web controller does not support verification execution'
        }), 500

    # Build verification config
    verification_config = {
        'command': command,
        'params': params,
        'context': None  # Context will be added by executor if needed
    }

    # Execute verification — web controller is async (Playwright)
    result = _run_async(web_controller.execute_verification(verification_config))

    print(f"[@route:host_verification_web:execute] Result: success={result.get('success')}")

    return jsonify(result)
    
