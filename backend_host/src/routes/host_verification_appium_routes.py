"""
Host Verification Appium Routes

Host-side appium verification endpoints that execute using instantiated appium verification controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_handlers import get_verification_controller

# Create blueprint
host_verification_appium_bp = Blueprint('host_verification_appium', __name__, url_prefix='/host/verification/appium')

@host_verification_appium_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def execute_appium_verification():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_verification_appium:execute] Executing Appium verification for device: {device_id}")
    
    # Get Appium verification controller
    appium_controller, _, error_response = get_verification_controller(device_id, 'verification_appium')
    if error_response:
        return error_response
    
    verification = data.get('verification')
    if not verification:
        return jsonify({
            'success': False,
            'error': 'verification is required'
        }), 400
    
    # Execute verification using controller abstraction
    result = appium_controller.execute_verification(verification)
    
    # Build clean response with frontend-expected properties
    response = {
        'success': result.get('success', False),
        'message': result.get('message', 'Unknown result'),
        'verification_type': 'appium',
        'resultType': 'PASS' if result.get('success') else 'FAIL',
        'matchingResult': result.get('matching_result', 0.0),
        'userThreshold': result.get('user_threshold', 0.8),
        'imageFilter': result.get('image_filter', 'none'),
        'extractedText': result.get('extractedText', ''),
        'searchedText': result.get('searchedText', ''),
        'platform': result.get('platform', '')
    }
    
    return jsonify(response)
    
