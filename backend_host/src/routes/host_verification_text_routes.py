"""
Host Verification Text Routes

Host-side text verification endpoints that execute using instantiated text verification controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from shared.src.lib.utils.build_url_utils import buildHostImageUrl
from backend_host.src.lib.utils.host_utils import get_host
from backend_host.src.lib.utils.route_handlers import get_verification_controller
import os

# Create blueprint
host_verification_text_bp = Blueprint('host_verification_text', __name__, url_prefix='/host/verification/text')

@host_verification_text_bp.route('/detectText', methods=['POST'])
@route_exception_handler()
def detect_text():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_detect_text] Text detection request for device: {device_id}")
    
    # Get text verification controller using helper
    text_controller, _, error_response = get_verification_controller(device_id, 'verification_text')
    if error_response:
        return error_response
    
    # Get text detection result
    result = text_controller.detect_text(data)
    
    # Build URL for text detected image using host instance
    # Always build URL if image path exists, regardless of success (for "no text detected" cases)
    if result.get('image_textdetected_path'):
        host = get_host()
        result['image_textdetected_url'] = buildHostImageUrl(host.to_dict(), result['image_textdetected_path'])
        print(f"[@route:host_detect_text] Built text detected image URL: {result['image_textdetected_url']}")
    
    return jsonify(result)
    
@host_verification_text_bp.route('/saveText', methods=['POST'])
@route_exception_handler()
def save_text():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    
    print(f"[@route:host_save_text] Save text request for device: {device_id}, team: {team_id}")
    
    # Validate team_id
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id query parameter is required'
        }), 400
    
    # Add team_id to data
    data['team_id'] = team_id
    
    # Get text verification controller using helper
    text_controller, _, error_response = get_verification_controller(device_id, 'verification_text')
    if error_response:
        return error_response
    
    result = text_controller.save_text(data)
    
    return jsonify(result)
    
@host_verification_text_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def execute_text_verification():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_verification_text:execute] Executing text verification for device: {device_id}")
    
    # Get text verification controller using helper
    text_controller, _, error_response = get_verification_controller(device_id, 'verification_text')
    if error_response:
        return error_response
    
    verification = data.get('verification')
    image_source_url = data.get('image_source_url')  # Get source image URL if provided
    
    # Convert image_source_url to local file path if provided
    source_image_path = None
    if image_source_url:
        print(f"[@route:host_verification_text:execute] Image source URL provided: {image_source_url}")
        try:
            # Use centralized URL conversion function
            from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
            source_image_path = convertHostUrlToLocalPath(image_source_url)
            
            print(f"[@route:host_verification_text:execute] Converted to local path: {source_image_path}")
            
            # Verify the file exists - if not, FAIL immediately (no fallback)
            if os.path.exists(source_image_path):
                print(f"[@route:host_verification_text:execute] Source image file exists, using provided image")
            else:
                error_msg = f"Source image file not found: {source_image_path}. No fallback allowed."
                print(f"[@route:host_verification_text:execute] ERROR: {error_msg}")
                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'verification_type': 'text',
                    'resultType': 'ERROR'
                }), 400
                
        except Exception as e:
            print(f"[@route:host_verification_text:execute] ERROR: Error processing image_source_url: {e}")
            error_msg = "Error processing image_source_url (see host log)"
            return jsonify({
                'success': False,
                'error': error_msg,
                'verification_type': 'text',
                'resultType': 'ERROR'
            }), 400
    
    # Prepare verification config
    verification_config = verification.copy() if verification else {}
    
    # Add source image path if available
    if source_image_path:
        verification_config['source_image_path'] = source_image_path
    
    # Execute verification using controller
    result = text_controller.execute_verification(verification_config)
    
    # Get host instance for URL building
    host = get_host()
    
    # Build URLs from file paths if verification generated images
    if result.get('success') and 'source_image_path' in result.get('details', {}):
        from shared.src.lib.utils.build_url_utils import buildVerificationResultUrl
        
        # Get host info for URL building
        host = get_host()
        host_info = host.to_dict() if host else None
        
        details = result.get('details', {})
        
        # Build URL for the source image
        if details.get('source_image_path'):
            filename = os.path.basename(details['source_image_path'])
            result['sourceUrl'] = buildVerificationResultUrl(host_info, filename, device_id)
            print(f"[@route:host_verification_text:execute] Built source URL: {result['sourceUrl']}")
    
    # Build clean response with frontend-expected properties
    response = {
        'success': result.get('success', False),
        'message': result.get('message', 'Unknown result'),
        'verification_type': 'text',
        'resultType': 'PASS' if result.get('success') else 'FAIL',
        'matchingResult': result.get('matching_result', 0.0),  # OCR confidence
        'userThreshold': result.get('user_threshold', 0.8),    # User's threshold
        'imageFilter': result.get('image_filter', 'none'),     # Applied filter
        'extractedText': result.get('extractedText', ''),      # Frontend-expected property name
        'searchedText': result.get('searchedText', ''),        # Frontend-expected property name
        'sourceUrl': result.get('sourceUrl'),                  # Frontend-expected property name
        'focusScore': result.get('focus_score'),               # accent coverage (None if no focus gate)
        'focusThreshold': result.get('focus_threshold'),       # required accent coverage
    }
    
    return jsonify(response)
    
