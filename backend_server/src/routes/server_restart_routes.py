"""
Server Restart Routes

Server-side restart video proxy endpoints that forward requests to host restart controllers.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from  backend_server.src.lib.utils.route_utils import proxy_to_host_with_params

server_restart_bp = Blueprint('server_restart', __name__, url_prefix='/server/restart')

@server_restart_bp.route('/generateRestartVideo', methods=['POST'])
@handle_route_exceptions('restart:generate_restart_video')
def generate_restart_video():
    """Generate video only - fast response"""
    request_data = request.get_json() or {}
    device_id = request_data.get('device_id', 'device1')
    duration_seconds = request_data.get('duration_seconds', 10)

    print(f"[SERVER] 🎬 [@server_restart_routes:generateRestartVideo] Received request for device: {device_id}, duration: {duration_seconds}s")

    # Let proxy_to_host_with_params handle host lookup via get_host_from_request()
    print(f"[SERVER] 🔄 [@server_restart_routes:generateRestartVideo] Proxying to host endpoint: /host/restart/generateRestartVideo")

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/generateRestartVideo',
        'POST',
        request_data,
        {'device_id': device_id},
        timeout=300  # 5 minutes for video generation
    )
    
    print(f"[SERVER] 📊 [@server_restart_routes:generateRestartVideo] Host response: status={status_code}, success={response_data.get('success', 'unknown')}")
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:generateRestartVideo] Video generation successful")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:generateRestartVideo] Video generation failed: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code
    
@server_restart_bp.route('/analysisStatus/<video_id>', methods=['POST'])
@handle_route_exceptions('restart:get_analysis_status')
def get_analysis_status(video_id):
    """Get analysis status for polling"""
    data = request.get_json()
    device_id = data.get('device_id', 'device1')
    host_name = data.get('host_name')
    
    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400
    
    response_data, status_code = proxy_to_host_with_params(
        f'/host/restart/analysisStatus/{video_id}',
        'POST',
        {'device_id': device_id},
        {}
    )
    
    return jsonify(response_data), status_code
    
@server_restart_bp.route('/analyzeRestartAudio', methods=['POST'])
@handle_route_exceptions('restart:analyze_restart_audio')
def analyze_restart_audio():
    """Analyze audio transcript"""
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/analyzeAudio',
        'POST',
        request_data,
        {'device_id': device_id},
        timeout=300  # 5 minutes for audio analysis (AI processing can be slow)
    )
    return jsonify(response_data), status_code
    
@server_restart_bp.route('/generateRestartReport', methods=['POST'])
@handle_route_exceptions('restart:generate_restart_report')
def generate_restart_report():
    """Generate restart report"""
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')

    if not host_name:
        return jsonify({'success': False, 'error': 'host_name required in request body'}), 400

    # Let proxy_to_host_with_params handle host lookup via get_host_from_request()
    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/generateReport',
        'POST',
        request_data,
        {'device_id': device_id},
        timeout=300  # 5 minutes for report generation
    )
    return jsonify(response_data), status_code
    
@server_restart_bp.route('/analyzeRestartComplete', methods=['POST'])
@handle_route_exceptions('restart:analyze_restart_complete')
def analyze_restart_complete():
    """Combined restart analysis: subtitles + summary in single call"""
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/analyzeComplete',
        'POST',
        request_data,
        {'device_id': device_id},
        timeout=600  # 10 minutes for combined analysis (AI processing can be slow)
    )
    return jsonify(response_data), status_code
    
@server_restart_bp.route('/analyzeRestartVideo', methods=['POST'])
@handle_route_exceptions('restart:analyze_restart_video')
def analyze_restart_video():
    """Proxy async AI analysis request to selected host with device_id"""
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/analyzeVideo',
        'POST',
        request_data,
        {'device_id': device_id},
        timeout=120
    )
    return jsonify(response_data), status_code
    
# =============================================================================
# 4-Step Dubbing Process Routes
# =============================================================================

@server_restart_bp.route('/prepareDubbingAudio', methods=['POST'])
@handle_route_exceptions('restart:prepare_dubbing_audio')
def prepare_dubbing_audio():
    """Step 1: Prepare audio for dubbing (extract + separate) ~20-35s"""
    import time
    step_start_time = time.time()
    
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')
    video_id = request_data.get('video_id')

    print(f"[SERVER] 🎵 [@server_restart_routes:prepareDubbingAudio] 🔍 OLD ENDPOINT CALLED - Step 1 starting for video_id: {video_id}")

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/prepareDubbingAudio',
        'POST',
        request_data,
        {'device_id': device_id, 'video_id': video_id},
        timeout=120  # 2 minutes for audio separation
    )
    
    step_duration = time.time() - step_start_time
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:prepareDubbingAudio] Step 1 completed in {step_duration:.1f}s")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:prepareDubbingAudio] Step 1 failed after {step_duration:.1f}s: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code

@server_restart_bp.route('/generateEdgeSpeech', methods=['POST'])
@handle_route_exceptions('restart:generate_edge_speech')
def generate_edge_speech():
    """Step 2: Generate Edge-TTS speech ~3-5s"""
    import time
    step_start_time = time.time()
    
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')
    video_id = request_data.get('video_id')
    target_language = request_data.get('target_language', 'es')
    existing_transcript = request_data.get('existing_transcript', '')

    print(f"[SERVER] 🤖 [@server_restart_routes:generateEdgeSpeech] Step 2 starting for {target_language}")

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400
    if not existing_transcript:
        return jsonify({'success': False, 'error': 'Transcript required for speech generation'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/generateEdgeSpeech',
        'POST',
        request_data,
        {'device_id': device_id, 'video_id': video_id, 'target_language': target_language, 'existing_transcript': existing_transcript},
        timeout=60  # 1 minute for Edge-TTS generation
    )
    
    step_duration = time.time() - step_start_time
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:generateEdgeSpeech] Step 2 completed in {step_duration:.1f}s")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:generateEdgeSpeech] Step 2 failed after {step_duration:.1f}s: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code

@server_restart_bp.route('/createDubbedVideo', methods=['POST'])
@handle_route_exceptions('restart:create_dubbed_video')
def create_dubbed_video():
    """Step 3: Create final dubbed video ~5-8s"""
    import time
    step_start_time = time.time()
    
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')
    video_id = request_data.get('video_id')
    target_language = request_data.get('target_language', 'es')
    voice_choice = request_data.get('voice_choice', 'edge')

    print(f"[SERVER] 🎬 [@server_restart_routes:createDubbedVideo] Step 3 starting with {voice_choice} voice")

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/createDubbedVideo',
        'POST',
        request_data,
        {'device_id': device_id, 'video_id': video_id, 'target_language': target_language, 'voice_choice': voice_choice},
        timeout=60  # 1 minute for video creation
    )
    
    step_duration = time.time() - step_start_time
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:createDubbedVideo] Step 3 completed in {step_duration:.1f}s")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:createDubbedVideo] Step 3 failed after {step_duration:.1f}s: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code

@server_restart_bp.route('/createDubbedVideoFast', methods=['POST'])
@handle_route_exceptions('restart:create_dubbed_video_fast')
def create_dubbed_video_fast():
    """NEW: Fast 2-step dubbed video creation ~5-8s"""
    import time
    step_start_time = time.time()
    
    request_data = request.get_json() or {}
    host_name = request_data.get('host_name')
    device_id = request_data.get('device_id', 'device1')
    video_id = request_data.get('video_id')
    target_language = request_data.get('target_language', 'es')
    existing_transcript = request_data.get('existing_transcript', '')

    print(f"[SERVER] ⚡ [@server_restart_routes:createDubbedVideoFast] 🔍 FAST ENDPOINT CALLED - Fast dubbing starting for {target_language}")

    if not host_name:
        return jsonify({'success': False, 'error': 'Host required'}), 400
    if not existing_transcript:
        return jsonify({'success': False, 'error': 'Transcript required for fast dubbing'}), 400

    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/createDubbedVideoFast',
        'POST',
        request_data,
        {'device_id': device_id, 'video_id': video_id, 'target_language': target_language, 'existing_transcript': existing_transcript},
        timeout=30  # 30 seconds for fast dubbing
    )
    
    step_duration = time.time() - step_start_time
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:createDubbedVideoFast] Fast dubbing completed in {step_duration:.1f}s")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:createDubbedVideoFast] Fast dubbing failed after {step_duration:.1f}s: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code

@server_restart_bp.route('/adjustAudioTiming', methods=['POST'])
@handle_route_exceptions('restart:adjust_audio_timing')
def adjust_audio_timing():
    """Adjust audio timing for existing restart video"""
    import time
    timing_start_time = time.time()
    
    request_data = request.get_json() or {}
    device_id = request_data.get('device_id', 'device1')
    video_url = request_data.get('video_url')
    timing_offset_ms = request_data.get('timing_offset_ms', 0)
    language = request_data.get('language', 'original')
    
    # Optional component paths from frontend
    silent_video_path = request_data.get('silent_video_path')
    background_audio_path = request_data.get('background_audio_path')
    vocals_path = request_data.get('vocals_path')

    print(f"[SERVER] 🎵 [@server_restart_routes:adjustAudioTiming] Starting timing adjustment: {timing_offset_ms:+d}ms for {language}")

    if not video_url:
        return jsonify({'success': False, 'error': 'Video URL required'}), 400
    if timing_offset_ms == 0:
        return jsonify({'success': False, 'error': 'Timing offset cannot be 0'}), 400

    # Let proxy_to_host_with_params handle host lookup via get_host_from_request()
    print(f"[SERVER] 🔄 [@server_restart_routes:adjustAudioTiming] Proxying to host endpoint: /host/restart/adjustAudioTiming")

    # Include component paths in proxy data
    proxy_params = {
        'device_id': device_id, 
        'video_url': video_url, 
        'timing_offset_ms': timing_offset_ms, 
        'language': language
    }
    
    # Add component paths if provided
    if silent_video_path:
        proxy_params['silent_video_path'] = silent_video_path
    if background_audio_path:
        proxy_params['background_audio_path'] = background_audio_path
    if vocals_path:
        proxy_params['vocals_path'] = vocals_path
    
    response_data, status_code = proxy_to_host_with_params(
        '/host/restart/adjustAudioTiming',
        'POST',
        request_data,
        proxy_params,
        timeout=60  # 1 minute for timing adjustment
    )
    
    timing_duration = time.time() - timing_start_time
    
    if response_data.get('success'):
        print(f"[SERVER] ✅ [@server_restart_routes:adjustAudioTiming] Audio timing adjustment ({timing_offset_ms:+d}ms) completed in {timing_duration:.1f}s")
    else:
        print(f"[SERVER] ❌ [@server_restart_routes:adjustAudioTiming] Timing adjustment failed after {timing_duration:.1f}s: {response_data.get('error', 'unknown error')}")
    
    return jsonify(response_data), status_code
