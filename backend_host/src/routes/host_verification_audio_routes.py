"""
Host Verification Audio Routes

Host-side audio verification endpoints that execute using instantiated audio verification controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_handlers import get_verification_controller

# Create blueprint
host_verification_audio_bp = Blueprint('host_verification_audio', __name__, url_prefix='/host/verification/audio')

@host_verification_audio_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def execute_audio_verification():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_verification_audio:execute] Executing audio verification for device: {device_id}")
    
    # Get audio verification controller
    audio_controller, _, error_response = get_verification_controller(device_id, 'verification_audio')
    if error_response:
        return error_response
    
    verification = data.get('verification')
    if not verification:
        return jsonify({
            'success': False,
            'error': 'verification is required'
        }), 400
    
    # Execute verification using controller abstraction
    result = audio_controller.execute_verification(verification)
    
    # Build clean response with frontend-expected properties
    response = {
        'success': result.get('success', False),
        'message': result.get('message', 'Unknown result'),
        'verification_type': 'audio',
        'resultType': 'PASS' if result.get('success') else 'FAIL',
        'matchingResult': result.get('matching_result', 0.0),
        'userThreshold': result.get('user_threshold', 0.8),
        'imageFilter': result.get('image_filter', 'none'),
        'extractedText': result.get('extractedText', ''),
        'searchedText': result.get('searchedText', ''),
        'audio_level': result.get('audio_level', 0.0),
        'duration': result.get('duration', 0.0),
        'frequency': result.get('frequency', 0.0)
    }
    
    return jsonify(response)
    
