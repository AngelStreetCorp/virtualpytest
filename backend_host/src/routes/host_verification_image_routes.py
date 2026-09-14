"""
Host Verification Image Routes

Host-side image verification endpoints that execute using instantiated image verification controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from shared.src.lib.utils.build_url_utils import buildHostImageUrl
from backend_host.src.lib.utils.host_utils import get_host
from backend_host.src.lib.utils.route_handlers import get_verification_controller
import os

# Create blueprint
host_verification_image_bp = Blueprint('host_verification_image', __name__, url_prefix='/host/verification/image')

@host_verification_image_bp.route('/cropImage', methods=['POST'])
@route_exception_handler()
def crop_area():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_crop_area] Host cropping request for device: {device_id}")
    
    # Get image verification controller and device info
    image_controller, device, error_response = get_verification_controller(device_id, 'verification_image', check_device=True)
    if error_response:
        return error_response
    
    # Controller handles everything
    result = image_controller.crop_image(data)
    
    # Build image URL for frontend preview using host instance
    if result.get('success') and result.get('image_cropped_path'):
        host = get_host()
        result['image_cropped_url'] = buildHostImageUrl(host.to_dict(), result['image_cropped_path'])
        print(f"[@route:host_crop_area] Built image cropped URL: {result['image_cropped_url']}")
    
    return jsonify(result)
    
@host_verification_image_bp.route('/processImage', methods=['POST'])
@route_exception_handler()
def process_area():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_process_area] Host processing request for device: {device_id}")
    
    # Get image verification controller and device info
    image_controller, device, error_response = get_verification_controller(device_id, 'verification_image', check_device=True)
    if error_response:
        return error_response
    
    result = image_controller.process_image(data)
    
    # Build image URL for frontend preview using host instance
    if result.get('success') and result.get('image_filtered_path'):
        host = get_host()
        result['image_filtered_url'] = buildHostImageUrl(host.to_dict(), result['image_filtered_path'])
        print(f"[@route:host_process_area] Built image filtered URL: {result['image_filtered_url']}")
    
    return jsonify(result)
    
@host_verification_image_bp.route('/saveImage', methods=['POST'])
@route_exception_handler()
def save_resource():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    
    print(f"[@route:host_save_resource] Save image reference request for device: {device_id}, team: {team_id}")
    
    # Validate team_id
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id query parameter is required'
        }), 400
    
    # Add team_id to data
    data['team_id'] = team_id
    
    # Get image verification controller and device info
    image_controller, device, error_response = get_verification_controller(device_id, 'verification_image', check_device=True)
    if error_response:
        return error_response
    
    result = image_controller.save_image(data)
    
    return jsonify(result)
    
@host_verification_image_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def execute_image_verification():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_verification_image:execute] Executing image verification for device: {device_id}")
    
    # Get image verification controller
    image_controller, _, error_response = get_verification_controller(device_id, 'verification_image')
    if error_response:
        return error_response
    
    verification = data.get('verification')
    image_source_url = data.get('image_source_url')  # Get source image URL if provided
    
    # Convert image_source_url to local file path if provided
    source_image_path = None
    if image_source_url:
        print(f"[@route:host_verification_image:execute] Image source URL provided: {image_source_url}")
        try:
            # Use centralized URL conversion function
            from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
            source_image_path = convertHostUrlToLocalPath(image_source_url)
            
            print(f"[@route:host_verification_image:execute] Converted to local path: {source_image_path}")
            
            # Verify the file exists - if not, FAIL immediately (no fallback)
            if os.path.exists(source_image_path):
                print(f"[@route:host_verification_image:execute] Source image file exists, using provided image")
            else:
                error_msg = f"Source image file not found: {source_image_path}. No fallback allowed."
                print(f"[@route:host_verification_image:execute] ERROR: {error_msg}")
                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'verification_type': 'image',
                    'resultType': 'ERROR'
                }), 400
                
        except Exception as e:
            print(f"[@route:host_verification_image:execute] ERROR: Error processing image_source_url: {e}")
            error_msg = "Error processing image_source_url (see host log)"
            return jsonify({
                'success': False,
                'error': error_msg,
                'verification_type': 'image',
                'resultType': 'ERROR'
            }), 400
    
    # Prepare verification config
    verification_config = {
        'command': verification.get('command', 'waitForImageToAppear'),
        'params': {
            'image_path': verification.get('params', {}).get('image_path', ''),
            'threshold': verification.get('params', {}).get('threshold', 0.8),
            'timeout': verification.get('params', {}).get('timeout', 10.0),
            'area': verification.get('params', {}).get('area'),
            'image_filter': verification.get('params', {}).get('image_filter', 'none'),
            'check_focus': verification.get('params', {}).get('check_focus', False)
            # Removed 'model': model - let controller use its built-in device_model
        }
    }
    
    # Add source image path if available
    if source_image_path:
        verification_config['source_image_path'] = source_image_path
    
    # Execute verification using controller
    verification_result = image_controller.execute_verification(verification_config)
    
    print(f"[@route:host_verification_image:execute] Verification result: {verification_result}")
    
    # Build URLs from file paths if verification generated images
    if 'source_image_path' in verification_result.get('details', {}):
        from shared.src.lib.utils.build_url_utils import buildVerificationResultUrl
        import time
        
        # Get host info for URL building
        host = get_host()
        host_info = host.to_dict() if host else None
        
        details = verification_result.get('details', {})
        
        # Generate timestamp for cache-busting (milliseconds since epoch)
        cache_buster = int(time.time() * 1000)
        
        # Build URLs for the generated images using frontend-expected property names
        if details.get('source_image_path'):
            filename = os.path.basename(details['source_image_path'])
            base_url = buildVerificationResultUrl(host_info, filename, device_id)
            verification_result['sourceUrl'] = f"{base_url}?cache={cache_buster}"
        
        # Use original R2 URL for reference image (no local copy created)
        if details.get('reference_image_url'):
            # Add cache buster to R2 URL too
            verification_result['referenceUrl'] = f"{details['reference_image_url']}?cache={cache_buster}"
            print(f"[@route:host_verification_image:execute] Using R2 reference URL: {details['reference_image_url']}")
        elif details.get('reference_image_path'):
            # Fallback for legacy code - should not happen with new implementation
            filename = os.path.basename(details['reference_image_path'])
            base_url = buildVerificationResultUrl(host_info, filename, device_id)
            verification_result['referenceUrl'] = f"{base_url}?cache={cache_buster}"
            print(f"[@route:host_verification_image:execute] Using legacy reference path: {details['reference_image_path']}")
            
        if details.get('result_overlay_path'):
            filename = os.path.basename(details['result_overlay_path'])
            base_url = buildVerificationResultUrl(host_info, filename, device_id)
            verification_result['overlayUrl'] = f"{base_url}?cache={cache_buster}"
        
        print(f"[@route:host_verification_image:execute] Built URLs with cache-buster={cache_buster}:")
        print(f"  Source: {verification_result.get('sourceUrl')}")
        print(f"  Reference: {verification_result.get('referenceUrl')}")
        print(f"  Overlay: {verification_result.get('overlayUrl')}")
    
    # Build clean response with frontend-expected properties
    _details = verification_result.get('details', {})
    result = {
        'success': verification_result.get('success', False),
        'message': verification_result.get('message', 'Unknown result'),
        'verification_type': 'image',
        'resultType': 'PASS' if verification_result.get('success') else 'FAIL',
        'matchingResult': verification_result.get('matching_result', 0.0),  # Actual confidence
        'userThreshold': verification_result.get('user_threshold', 0.8),    # User's threshold
        'imageFilter': verification_result.get('image_filter', 'none'),     # Applied filter
        'sourceUrl': verification_result.get('sourceUrl'),                  # Frontend-expected names
        'referenceUrl': verification_result.get('referenceUrl'),
        'overlayUrl': verification_result.get('overlayUrl'),
        # Focus detection (present only when the reference was captured with Focus)
        'focusScore': _details.get('focus_score'),
        'focusThreshold': _details.get('focus_threshold'),
    }
    
    print(f"[@route:host_verification_image:execute] Final result: {result}")
    
    return jsonify(result)
    
