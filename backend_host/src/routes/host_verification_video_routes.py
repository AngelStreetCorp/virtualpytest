"""
Host Video Verification Routes

This module contains host-side video verification endpoints that:
- Handle video analysis requests (blackscreen, freeze, subtitle detection)
- Execute video verification using the VideoVerificationController
- Return detailed analysis results with same level of detail as analyze_frame.py
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_host
from backend_host.src.lib.utils.route_handlers import get_verification_controller
import time
import traceback
from shared.src.lib.utils.build_url_utils import resolveImageSourceToLocalPath

# Create blueprint
host_verification_video_bp = Blueprint('host_verification_video', __name__, url_prefix='/host/verification/video')

@host_verification_video_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def verification_video_execute():
    print("[@route:host_verification_video:execute] Processing video verification request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    command = data.get('command', 'DetectBlackscreen')
    
    print(f"[@route:host_verification_video:execute] Device: {device_id}, Command: {command}")
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute verification
    start_time = time.time()
    result = video_controller.execute_command(command, data)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:execute] Result: success={result.get('success')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/detectBlackscreen', methods=['POST'])
@route_exception_handler()
def detect_blackscreen():
    print("[@route:host_verification_video:detectBlackscreen] Processing blackscreen detection request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_paths = data.get('image_paths')  # Array of image paths
    image_source_url = data.get('image_source_url')  # Single image or comma-separated
    threshold = data.get('threshold', 10)
    
    # Parse image sources
    final_image_paths = None
    if image_paths:
        final_image_paths = image_paths
    elif image_source_url:
        if isinstance(image_source_url, str):
            if ',' in image_source_url:
                final_image_paths = [path.strip() for path in image_source_url.split(',')]
            else:
                final_image_paths = [image_source_url]
        elif isinstance(image_source_url, list):
            final_image_paths = image_source_url
    
    print(f"[@route:host_verification_video:detectBlackscreen] Image paths: {final_image_paths}")
    print(f"[@route:host_verification_video:detectBlackscreen] Threshold: {threshold}")
    
    # Convert URLs to local paths if needed
    if final_image_paths and any(path.startswith(('http://', 'https://')) for path in final_image_paths):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_paths = [convertHostUrlToLocalPath(path) if path.startswith(('http://', 'https://')) else path for path in final_image_paths]
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute blackscreen detection
    start_time = time.time()
    result = video_controller.detect_blackscreen(final_image_paths, threshold)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:detectBlackscreen] Result: success={result.get('success')}, blackscreen={result.get('blackscreen_detected')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/detectFreeze', methods=['POST'])
@route_exception_handler()
def detect_freeze():
    print("[@route:host_verification_video:detectFreeze] Processing freeze detection request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_paths = data.get('image_paths')  # Array of image paths
    image_source_url = data.get('image_source_url')  # Single image or comma-separated
    threshold = data.get('threshold', 0.95)
    
    # Parse image sources
    final_image_paths = None
    if image_paths:
        final_image_paths = image_paths
    elif image_source_url:
        if isinstance(image_source_url, str):
            if ',' in image_source_url:
                final_image_paths = [path.strip() for path in image_source_url.split(',')]
            else:
                final_image_paths = [image_source_url]
        elif isinstance(image_source_url, list):
            final_image_paths = image_source_url
    
    print(f"[@route:host_verification_video:detectFreeze] Image paths: {final_image_paths}")
    print(f"[@route:host_verification_video:detectFreeze] Threshold: {threshold}")
    
    # Convert URLs to local paths if needed
    if final_image_paths and any(path.startswith(('http://', 'https://')) for path in final_image_paths):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_paths = [convertHostUrlToLocalPath(path) if path.startswith(('http://', 'https://')) else path for path in final_image_paths]
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute freeze detection
    start_time = time.time()
    result = video_controller.detect_freeze(final_image_paths, threshold)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:detectFreeze] Result: success={result.get('success')}, freeze={result.get('freeze_detected')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/detectSubtitles', methods=['POST'])
@route_exception_handler()
def detect_subtitles():
    print("[@route:host_verification_video:detectSubtitles] Processing subtitle detection request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_paths = data.get('image_paths')  # Array of image paths
    image_source_url = data.get('image_source_url')  # Single image or comma-separated
    extract_text = data.get('extract_text', True)
    
    # Parse image sources
    final_image_paths = None
    if image_paths:
        final_image_paths = image_paths
    elif image_source_url:
        if isinstance(image_source_url, str):
            if ',' in image_source_url:
                final_image_paths = [path.strip() for path in image_source_url.split(',')]
            else:
                final_image_paths = [image_source_url]
        elif isinstance(image_source_url, list):
            final_image_paths = image_source_url
    
    print(f"[@route:host_verification_video:detectSubtitles] Image paths: {final_image_paths}")
    print(f"[@route:host_verification_video:detectSubtitles] Extract text: {extract_text}")
    
    # Convert URLs to local paths if needed
    if final_image_paths and any(path.startswith(('http://', 'https://')) for path in final_image_paths):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_paths = [convertHostUrlToLocalPath(path) if path.startswith(('http://', 'https://')) else path for path in final_image_paths]
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute subtitle detection
    start_time = time.time()
    result = video_controller.detect_subtitles(final_image_paths, extract_text)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:detectSubtitles] Result: success={result.get('success')}, subtitles={result.get('subtitles_detected')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/detectSubtitlesAI', methods=['POST'])
@route_exception_handler()
def detect_subtitles_ai():
    print("[@route:host_verification_video:detectSubtitlesAI] Processing AI subtitle detection request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_paths = data.get('image_paths')  # Array of image paths
    image_source_url = data.get('image_source_url')  # Single image or comma-separated
    extract_text = data.get('extract_text', True)
    
    # Parse image sources
    final_image_paths = None
    if image_paths:
        final_image_paths = image_paths
    elif image_source_url:
        if isinstance(image_source_url, str):
            if ',' in image_source_url:
                final_image_paths = [path.strip() for path in image_source_url.split(',')]
            else:
                final_image_paths = [image_source_url]
        elif isinstance(image_source_url, list):
            final_image_paths = image_source_url
    
    print(f"[@route:host_verification_video:detectSubtitlesAI] Image paths: {final_image_paths}")
    print(f"[@route:host_verification_video:detectSubtitlesAI] Extract text: {extract_text}")
    
    # Convert URLs to local paths if needed
    if final_image_paths and any(path.startswith(('http://', 'https://')) for path in final_image_paths):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_paths = [convertHostUrlToLocalPath(path) if path.startswith(('http://', 'https://')) else path for path in final_image_paths]
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute AI subtitle detection
    start_time = time.time()
    result = video_controller.detect_subtitles_ai(final_image_paths, extract_text)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:detectSubtitlesAI] Result: success={result.get('success')}, subtitles={result.get('subtitles_detected')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/analyzeImageAI', methods=['POST'])
@route_exception_handler()
def analyze_image_ai():
    print("[@route:host_verification_video:analyzeImageAI] Processing AI image analysis request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_source_url = data.get('image_source_url')  # Single image URL
    user_query = data.get('query', '')
    
    print(f"[@route:host_verification_video:analyzeImageAI] Image source: {image_source_url}")
    print(f"[@route:host_verification_video:analyzeImageAI] User query: {user_query}")
    
    if not image_source_url:
        return jsonify({
            'success': False,
            'error': 'image_source_url is required'
        }), 400
    
    if not user_query.strip():
        return jsonify({
            'success': False,
            'error': 'query is required'
        }), 400
    
    # Resolve image source to local path (supports URL, nginx path, absolute path, filename)
    final_image_path = resolveImageSourceToLocalPath(image_source_url)
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute AI image analysis
    start_time = time.time()
    result = video_controller.analyze_image_ai(final_image_path, user_query)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:analyzeImageAI] Result: success={result.get('success')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/analyzeImageComplete', methods=['POST'])
@route_exception_handler()
def analyze_image_complete():
    print("[@route:host_verification_video:analyzeImageComplete] Processing combined AI analysis request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_source_url = data.get('image_source_url')
    extract_text = data.get('extract_text', True)
    include_description = data.get('include_description', True)
    
    print(f"[@route:host_verification_video:analyzeImageComplete] Image: {image_source_url}")
    print(f"[@route:host_verification_video:analyzeImageComplete] Extract text: {extract_text}, Include description: {include_description}")
    
    if not image_source_url:
        return jsonify({'success': False, 'error': 'image_source_url is required'}), 400
    
    # Convert URL to local path if needed
    final_image_path = image_source_url
    if image_source_url.startswith(('http://', 'https://')):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_path = convertHostUrlToLocalPath(image_source_url)
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute combined AI analysis
    start_time = time.time()
    result = video_controller.analyze_image_complete(final_image_path, extract_text, include_description)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:analyzeImageComplete] Result: success={result.get('success')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/analyzeLanguageMenu', methods=['POST'])
@route_exception_handler()
def analyze_language_menu():
    print("[@route:host_verification_video:analyzeLanguageMenu] Processing AI language menu analysis request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_source_url = data.get('image_source_url')  # Single image URL
    
    print(f"[@route:host_verification_video:analyzeLanguageMenu] Image source: {image_source_url}")
    
    if not image_source_url:
        return jsonify({
            'success': False,
            'error': 'image_source_url is required'
        }), 400
    
    # Convert URL to local path if needed
    final_image_path = image_source_url
    if image_source_url.startswith(('http://', 'https://')):
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        final_image_path = convertHostUrlToLocalPath(image_source_url)
    
    # Get video verification controller
    video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
    if error_response:
        return error_response
    
    # Execute AI language menu analysis
    start_time = time.time()
    result = video_controller.analyze_language_menu_ai(final_image_path)
    execution_time = int((time.time() - start_time) * 1000)
    
    # Add execution time to result
    result['execution_time_ms'] = execution_time
    
    print(f"[@route:host_verification_video:analyzeLanguageMenu] Result: success={result.get('success')}, menu_detected={result.get('menu_detected')}, time={execution_time}ms")
    
    return jsonify(result)
    
@host_verification_video_bp.route('/debugSubtitlesAI', methods=['POST'])
@route_exception_handler()
def debug_subtitles_ai():
    print("[@route:host_verification_video:debugSubtitlesAI] Processing debug AI subtitle detection request")
    
    # Get request data
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    image_url = data.get('image_url')  # Public URL to download
    extract_text = data.get('extract_text', True)
    
    print(f"[@route:host_verification_video:debugSubtitlesAI] Image URL: {image_url}")
    print(f"[@route:host_verification_video:debugSubtitlesAI] Extract text: {extract_text}")
    
    if not image_url:
        return jsonify({
            'success': False,
            'error': 'image_url is required'
        }), 400
    
    # Download image to temporary location
    import requests
    import tempfile
    import os
    from urllib.parse import urlparse
    
    try:
        print(f"[@route:host_verification_video:debugSubtitlesAI] Downloading image from: {image_url}")
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        # Create temporary file with proper extension
        parsed_url = urlparse(image_url)
        file_extension = os.path.splitext(parsed_url.path)[1] or '.jpg'
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file.write(response.content)
            temp_image_path = temp_file.name
        
        print(f"[@route:host_verification_video:debugSubtitlesAI] Image downloaded to: {temp_image_path}")
        
    except Exception as download_error:
        print(f"[@route:host_verification_video:debugSubtitlesAI] Download error: {str(download_error)}")
        return jsonify({
            'success': False,
            'error': f'Failed to download image: {str(download_error)}'
        }), 400
    
    try:
        # Get video verification controller
        video_controller, device, error_response = get_verification_controller(device_id, 'verification_video')
        if error_response:
            return error_response
        
        # Execute AI subtitle detection
        start_time = time.time()
        result = video_controller.detect_subtitles_ai([temp_image_path], extract_text)
        execution_time = int((time.time() - start_time) * 1000)
        
        # Add execution time and debug info to result
        result['execution_time_ms'] = execution_time
        result['debug_info'] = {
            'original_url': image_url,
            'temp_file_path': temp_image_path,
            'downloaded_size': len(response.content)
        }
        
        print(f"[@route:host_verification_video:debugSubtitlesAI] Result: success={result.get('success')}, subtitles={result.get('subtitles_detected')}, time={execution_time}ms")
        
        return jsonify(result)
        
    finally:
        # Clean up temporary file
        try:
            if os.path.exists(temp_image_path):
                os.unlink(temp_image_path)
                print(f"[@route:host_verification_video:debugSubtitlesAI] Cleaned up temp file: {temp_image_path}")
        except Exception as cleanup_error:
            print(f"[@route:host_verification_video:debugSubtitlesAI] Cleanup error: {str(cleanup_error)}")
    
