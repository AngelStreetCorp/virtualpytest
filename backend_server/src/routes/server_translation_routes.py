"""
Server Translation Routes

Routes for AI-powered text translation - proxies requests to Host for processing.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import sys
import os
from  backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
# All translation work is now handled by host - server just coordinates
from shared.src.lib.utils.build_url_utils import call_host

# Create blueprint
server_translation_bp = Blueprint('server_translation', __name__, url_prefix='/server/translate')

@server_translation_bp.route('/text', methods=['POST'])
@handle_route_exceptions('translation:translate_single_text')
def translate_single_text():
    """Translate a single text string - proxy to Host"""
    data = request.get_json() or {}
    
    if not data:
        return jsonify({
            'success': False,
            'error': 'No JSON data provided'
        }), 400
    
    # Get host URL from request data
    host_data = data.get('host', {})
    if not host_data:
        return jsonify({
            'success': False,
            'error': 'Host information required'
        }), 400
    
    print(f"[SERVER_TRANSLATION] 🌐 Proxying text translation to host via call_host()")
    
    # Use centralized call_host() which automatically adds API key
    response_data, status_code = call_host(
        host_data,
        '/host/translate/text',
        method='POST',
        data=data,
        timeout=30
    )
    
    if status_code == 200:
        print(f"[SERVER_TRANSLATION] ✅ Text translation completed via host")
        return jsonify(response_data)
    else:
        print(f"[SERVER_TRANSLATION] ❌ Host translation failed: {status_code}")
        return jsonify({
            'success': False,
            'error': f'Host translation failed: {status_code}'
        }), status_code
    
@server_translation_bp.route('/batch', methods=['POST'])
@handle_route_exceptions('translation:translate_batch_segments')
def translate_batch_segments():
    """Translate multiple text segments"""
    data = request.get_json() or {}
    segments = data.get('segments', [])
    source_language = data.get('source_language', 'en')
    target_language = data.get('target_language', 'en')
    
    if not segments:
        return jsonify({
            'success': False,
            'error': 'No segments provided'
        }), 400
    
    result = batch_translate_segments(segments, source_language, target_language)
    return jsonify(result)
    
@server_translation_bp.route('/restart-batch', methods=['POST'])
@handle_route_exceptions('translation:translate_restart_batch')
def translate_restart_batch():
    """Translate all restart video content - proxy to Host for processing"""
    import time
    translation_start_time = time.time()
    
    data = request.get_json() or {}
    content_blocks = data.get('content_blocks', {})
    target_language = data.get('target_language', 'en')
    
    print(f"[SERVER_TRANSLATION] 🌐 Starting batch translation to {target_language}...")
    print(f"[SERVER_TRANSLATION] Content blocks keys: {list(content_blocks.keys())}")
    
    if not content_blocks:
        print("[SERVER_TRANSLATION] ERROR: No content blocks provided")
        return jsonify({
            'success': False,
            'error': 'No content blocks provided'
        }), 400
    
    # Get host information using standard pattern
    from  backend_server.src.lib.utils.route_utils import get_host_from_request
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({
            'success': False,
            'error': error or 'Host information required for translation'
        }), 400
    
    print(f"[SERVER_TRANSLATION] 🌐 Proxying batch translation to host via call_host()")
    
    # Use centralized call_host() which automatically adds API key
    response_data, status_code = call_host(
        host_info,
        '/host/translate/restart-batch',
        method='POST',
        data={
            'content_blocks': content_blocks,
            'target_language': target_language
        },
        timeout=60  # Longer timeout for batch processing
    )
    
    translation_duration = time.time() - translation_start_time
    
    if status_code == 200:
        print(f"[SERVER_TRANSLATION] Translation result: success={response_data.get('success', False)}")
        
        if response_data.get('success', False):
            print(f"[SERVER_TRANSLATION] ✅ Batch translation to {target_language} completed in {translation_duration:.1f}s")
        else:
            print(f"[SERVER_TRANSLATION] ❌ Translation failed after {translation_duration:.1f}s")
            print(f"[SERVER_TRANSLATION] Translation error: {response_data.get('error', 'Unknown error')}")
        
        return jsonify(response_data)
    else:
        print(f"[SERVER_TRANSLATION] ❌ Host translation failed: {status_code}")
        return jsonify({
            'success': False,
            'error': f'Host translation failed: {status_code}'
        }), status_code
    
@server_translation_bp.route('/detect', methods=['POST'])
@handle_route_exceptions('translation:detect_text_language')
def detect_text_language():
    """Detect language of text - proxy to Host"""
    data = request.get_json() or {}
    
    if not data:
        return jsonify({
            'success': False,
            'error': 'No JSON data provided'
        }), 400
    
    # Get host URL from request data
    host_name = data.get('host_name')
    if not host_name:
        return jsonify({
            'success': False,
            'error': 'host_name is required'
        }), 400
    
    # Proxy to Host for language detection
    return proxy_to_host_with_params(
        host_name=host_name,
        endpoint='/host/translate/detect',
        method='POST',
        data=data
    )
    