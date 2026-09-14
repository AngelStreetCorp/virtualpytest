"""
Host Restart Video Routes

Restart video system endpoints for video generation and AI analysis.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from  backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id
import os
import threading
import time
import signal
from contextlib import contextmanager
from typing import Dict

host_restart_bp = Blueprint('host_restart', __name__, url_prefix='/host/restart')

# Request deduplication tracking
_active_requests: Dict[str, float] = {}
_request_lock = threading.Lock()

def _get_request_key(endpoint: str, device_id: str, video_id: str) -> str:
    return f"{endpoint}:{device_id}:{video_id}"

def _is_request_active(request_key: str) -> bool:
    with _request_lock:
        if request_key in _active_requests:
            if time.time() - _active_requests[request_key] > 60:
                del _active_requests[request_key]
                return False
            return True
        return False

def _mark_request_active(request_key: str):
    with _request_lock:
        _active_requests[request_key] = time.time()

def _mark_request_complete(request_key: str):
    with _request_lock:
        _active_requests.pop(request_key, None)

@contextmanager
def timeout(duration):
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {duration} seconds")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(duration)
    try:
        yield
    finally:
        signal.alarm(0)

@host_restart_bp.route('/generateRestartVideo', methods=['POST'])
@route_exception_handler()
def generate_restart_video():
    """Generate video only - fast response"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        duration_seconds = data.get('duration_seconds', 10)
        
        print(f"[HOST] 🎬 [@host_restart_routes:generateRestartVideo] Starting video generation for device {device_id}, duration: {duration_seconds}s")
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            error_msg = f'No AV controller found for device {device_id}'
            print(f"[HOST] ❌ [@host_restart_routes:generateRestartVideo] {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 404
        
        print(f"[HOST] 🎥 [@host_restart_routes:generateRestartVideo] AV controller found: {av_controller.__class__.__name__}")
        print(f"[HOST] 🎬 [@host_restart_routes:generateRestartVideo] Calling generateRestartVideo...")
        
        result = av_controller.restart_helpers.generate_restart_video(
            duration_seconds=duration_seconds,
            processing_time=0.0
        )
        
        print(f"[HOST] 📊 [@host_restart_routes:generateRestartVideo] Result received: {result is not None}")
        
        if result and result.get('success'):
            video_url = result.get('video_url')
            video_id = result.get('analysis_data', {}).get('video_id')
            screenshot_count = len(result.get('analysis_data', {}).get('screenshot_urls', []))
            segment_count = result.get('analysis_data', {}).get('segment_count', 0)
            
            segment_files = result.get('analysis_data', {}).get('segment_files', [])
            segment_files_count = len(segment_files) if segment_files else 0
            
            print(f"[HOST] ✅ [@host_restart_routes:generateRestartVideo] Video generation SUCCESS!")
            print(f"[HOST] 📹 [@host_restart_routes:generateRestartVideo] Video URL: {video_url}")
            print(f"[HOST] 🆔 [@host_restart_routes:generateRestartVideo] Video ID: {video_id}")
            print(f"[HOST] 📸 [@host_restart_routes:generateRestartVideo] Screenshots: {screenshot_count}")
            print(f"[HOST] 🎞️ [@host_restart_routes:generateRestartVideo] Segments: {segment_count}")
            print(f"[HOST] 📂 [@host_restart_routes:generateRestartVideo] Segment files: {segment_files_count} files")
            if segment_files_count > 0:
                print(f"[HOST] 📋 [@host_restart_routes:generateRestartVideo] First segment: {segment_files[0] if segment_files else 'None'}")
                print(f"[HOST] 📋 [@host_restart_routes:generateRestartVideo] Last segment: {segment_files[-1] if segment_files else 'None'}")
            
            return jsonify({
                'success': True,
                'video_url': video_url,
                'video_id': video_id,
                'screenshot_urls': result.get('analysis_data', {}).get('screenshot_urls', []),
                'segment_count': segment_count,
                'analysis_data': {
                    'video_id': video_id,
                    'screenshot_urls': result.get('analysis_data', {}).get('screenshot_urls', []),
                    'segment_files': segment_files,
                    'segment_count': segment_count
                }
            })
        else:
            error_msg = 'Video generation failed - no result or success=False'
            print(f"[HOST] ❌ [@host_restart_routes:generateRestartVideo] {error_msg}")
            print(f"[HOST] 🔍 [@host_restart_routes:generateRestartVideo] Result details: {result}")
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except Exception as e:
        error_msg = f"Exception during video generation: {str(e)}"
        print(f"[HOST] 💥 [@host_restart_routes:generateRestartVideo] {error_msg}")
        import traceback
        print(f"[HOST] 🔍 [@host_restart_routes:generateRestartVideo] Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/generateVideoOnly', methods=['POST'])
@route_exception_handler()
def generate_restart_video_only():
    """Generate video only - fast response"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        duration_seconds = data.get('duration_seconds', 10)
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        result = av_controller.generateRestartVideoOnly(duration_seconds)
        return jsonify(result) if result else jsonify({'success': False, 'error': 'Video generation failed'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@host_restart_bp.route('/analyzeAudio', methods=['POST'])
@route_exception_handler()
def analyze_restart_audio():
    """Analyze audio transcript"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        segment_files = data.get('segment_files')
        
        if not video_id:
            return jsonify({'success': False, 'error': 'video_id is required'}), 400
        
        request_key = _get_request_key('analyzeRestartAudio', device_id, video_id)
        if _is_request_active(request_key):
            return jsonify({
                'success': False, 
                'error': 'Audio analysis already in progress for this video',
                'code': 'DUPLICATE_REQUEST'
            }), 409
        
        _mark_request_active(request_key)
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        with timeout(25):
            result = av_controller.analyzeRestartAudio(video_id, segment_files)
            
        if result and result.get('success'):
            return jsonify(result)
        else:
            error_msg = result.get('error', 'Audio analysis failed') if result else 'Audio analysis failed'
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except TimeoutError as e:
        return jsonify({'success': False, 'error': str(e)}), 408
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'request_key' in locals():
            _mark_request_complete(request_key)

@host_restart_bp.route('/analyzeSubtitles', methods=['POST'])
@route_exception_handler()
def analyze_restart_subtitles():
    """Analyze subtitles"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        screenshot_urls = data.get('screenshot_urls', [])
        
        if not video_id:
            return jsonify({'success': False, 'error': 'video_id is required'}), 400
        if not screenshot_urls:
            return jsonify({'success': False, 'error': 'screenshot_urls are required'}), 400
        
        request_key = _get_request_key('analyzeRestartSubtitles', device_id, video_id)
        if _is_request_active(request_key):
            return jsonify({
                'success': False, 
                'error': 'Subtitle analysis already in progress for this video',
                'code': 'DUPLICATE_REQUEST'
            }), 409
        
        _mark_request_active(request_key)
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        with timeout(25):
            result = av_controller.analyzeRestartSubtitles(video_id, screenshot_urls)
            
        if result and result.get('success'):
            return jsonify(result)
        else:
            error_msg = result.get('error', 'Subtitle analysis failed') if result else 'Subtitle analysis failed'
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except TimeoutError as e:
        return jsonify({'success': False, 'error': str(e)}), 408
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'request_key' in locals():
            _mark_request_complete(request_key)

@host_restart_bp.route('/analyzeSummary', methods=['POST'])
@route_exception_handler()
def analyze_restart_summary():
    """Analyze video summary"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        screenshot_urls = data.get('screenshot_urls', [])
        video_url = data.get('video_url')
        previous_analysis_data = data.get('analysis_data', {})
        
        if not video_id:
            return jsonify({'success': False, 'error': 'video_id is required'}), 400
        if not screenshot_urls:
            return jsonify({'success': False, 'error': 'screenshot_urls are required'}), 400
        
        request_key = _get_request_key('analyzeRestartSummary', device_id, video_id)
        if _is_request_active(request_key):
            return jsonify({
                'success': False, 
                'error': 'Summary analysis already in progress for this video',
                'code': 'DUPLICATE_REQUEST'
            }), 409
        
        _mark_request_active(request_key)
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        with timeout(25):
            result = av_controller.analyzeRestartSummary(video_id, screenshot_urls)
            
        if result and result.get('success'):
            try:
                from  backend_host.src.lib.utils.restart_report_generation import generate_and_upload_restart_report
                from  backend_host.src.lib.utils.host_utils import get_host_instance
                
                host = get_host_instance()
                host_info = {'host_name': host.host_name}
                device_info = {
                    'device_name': av_controller.device_name,
                    'device_model': getattr(av_controller, 'device_model', 'Unknown'),
                    'device_id': device_id
                }
                
                if not video_url:
                    video_url = f"{av_controller.video_stream_path}/restart_video.mp4"
                
                local_video_path = os.path.join(av_controller.video_capture_path, "restart_video.mp4")
                
                analysis_data = {
                    'audio_analysis': previous_analysis_data.get('audio_analysis', {}),
                    'subtitle_analysis': previous_analysis_data.get('subtitle_analysis', {}),
                    'video_analysis': result.get('video_analysis', {}),
                }
                
                report_result = generate_and_upload_restart_report(
                    host_info=host_info,
                    device_info=device_info,
                    video_url=video_url,
                    analysis_data=analysis_data,
                    processing_time=0.0,
                    local_video_path=local_video_path if os.path.exists(local_video_path) else None
                )
                
                if report_result.get('success'):
                    result['report_url'] = report_result['report_url']
                    result['report_path'] = report_result['report_path']
                    
            except Exception:
                pass
            
            return jsonify(result)
        else:
            error_msg = result.get('error', 'Summary analysis failed') if result else 'Summary analysis failed'
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except TimeoutError as e:
        return jsonify({'success': False, 'error': str(e)}), 408
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'request_key' in locals():
            _mark_request_complete(request_key)

@host_restart_bp.route('/analyzeComplete', methods=['POST'])
@route_exception_handler()
def analyze_restart_complete():
    """Combined restart analysis: subtitles + summary in single call"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        screenshot_urls = data.get('screenshot_urls', [])
        
        if not video_id:
            return jsonify({'success': False, 'error': 'video_id is required'}), 400
        if not screenshot_urls:
            return jsonify({'success': False, 'error': 'screenshot_urls are required'}), 400
        
        request_key = _get_request_key('analyzeRestartComplete', device_id, video_id)
        if _is_request_active(request_key):
            return jsonify({
                'success': False, 
                'error': 'Combined analysis already in progress for this video',
                'code': 'DUPLICATE_REQUEST'
            }), 409
        
        _mark_request_active(request_key)
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        with timeout(45):
            result = av_controller.analyzeRestartComplete(video_id, screenshot_urls)
            
        if result and result.get('success'):
            return jsonify(result), 200
        else:
            error_msg = result.get('error', 'Combined analysis failed') if result else 'Combined analysis failed'
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except TimeoutError as e:
        return jsonify({'success': False, 'error': str(e)}), 408
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'request_key' in locals():
            _mark_request_complete(request_key)

@host_restart_bp.route('/generateReport', methods=['POST'])
@route_exception_handler()
def generate_restart_report():
    """Generate report with all analysis data collected from frontend"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_url = data.get('video_url')
        analysis_data = data.get('analysis_data', {})
        
        if not video_url:
            return jsonify({'success': False, 'error': 'video_url is required'}), 400
        if not analysis_data:
            return jsonify({'success': False, 'error': 'analysis_data is required'}), 400
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        from  backend_host.src.lib.utils.restart_report_generation import generate_and_upload_restart_report
        from  backend_host.src.lib.utils.host_utils import get_host_instance
        
        host = get_host_instance()
        host_info = {'host_name': host.host_name}
        device_info = {
            'device_name': av_controller.device_name,
            'device_model': getattr(av_controller, 'device_model', 'Unknown'),
            'device_id': device_id
        }
        
        local_video_path = os.path.join(av_controller.video_capture_path, "restart_video.mp4")
        
        report_result = generate_and_upload_restart_report(
            host_info=host_info,
            device_info=device_info,
            video_url=video_url,
            analysis_data=analysis_data,
            processing_time=0.0,
            local_video_path=local_video_path if os.path.exists(local_video_path) else None
        )
        
        if report_result.get('success'):
            return jsonify({
                'success': True,
                'report_url': report_result['report_url'],
                'report_path': report_result['report_path']
            })
        else:
            error_msg = report_result.get('error', 'Report generation failed')
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/analysisStatus/<video_id>', methods=['POST'])
@route_exception_handler()
def get_analysis_status(video_id):
    """Get analysis status for polling"""
    try:
        data = request.get_json()
        device_id = data.get('device_id', 'device1')
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        status = av_controller.restart_helpers.get_status(video_id)
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/analyzeVideo', methods=['POST'])
@route_exception_handler()
def analyze_restart_video():
    """Async AI analysis for restart video - subtitle detection + video descriptions"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        screenshot_urls = data.get('screenshot_urls', [])
        duration_seconds = data.get('duration_seconds', 10)
        segment_count = data.get('segment_count')
        
        if not video_id:
            return jsonify({'success': False, 'error': 'video_id is required'}), 400
        if not screenshot_urls:
            return jsonify({'success': False, 'error': 'screenshot_urls are required'}), 400
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        start_time = time.time()
        result = av_controller.analyzeRestartComplete(
            video_id=video_id, 
            screenshot_urls=screenshot_urls
        )
        
        processing_time = time.time() - start_time
        
        if result:
            result.update({
                'processing_time_seconds': round(processing_time, 2),
                'device_id': device_id,
                'message': f'Successfully completed async AI analysis for video {video_id}'
            })
            
            try:
                from  backend_host.src.lib.utils.restart_report_generation import generate_and_upload_restart_report
                from  backend_host.src.lib.utils.host_utils import get_host_instance
                
                host = get_host_instance()
                host_info = {'host_name': host.host_name}
                device_info = {
                    'device_name': av_controller.device_name,
                    'device_model': getattr(av_controller, 'device_model', 'Unknown'),
                    'device_id': device_id
                }
                
                video_url = result.get('video_url', '')
                if not video_url:
                    video_url = f"{av_controller.video_stream_path}/restart_video.mp4"
                
                local_video_path = os.path.join(av_controller.video_capture_path, "restart_video.mp4")
                
                report_result = generate_and_upload_restart_report(
                    host_info=host_info,
                    device_info=device_info,
                    video_url=video_url,
                    analysis_data=result.get('analysis_data', {}),
                    processing_time=processing_time,
                    local_video_path=local_video_path if os.path.exists(local_video_path) else None
                )
                
                if report_result.get('success'):
                    result['report_url'] = report_result['report_url']
                    result['report_path'] = report_result['report_path']
                    
            except Exception:
                pass
            
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': 'Failed to perform async AI analysis'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# =============================================================================
# 4-Step Dubbing Process Routes
# =============================================================================

@host_restart_bp.route('/prepareDubbingAudio', methods=['POST'])
@route_exception_handler()
def prepare_dubbing_audio():
    """Step 1: Prepare audio for dubbing (extract + separate) ~20-35s"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        print(f"Host[{device_id}]: Step 1 - Preparing audio for dubbing...")
        result = av_controller.prepareDubbingAudio(video_id)
        
        if result and result.get('success'):
            print(f"Host[{device_id}]: Step 1 completed in {result.get('duration_seconds', 0)}s")
            return jsonify(result)
        else:
            return jsonify(result or {'success': False, 'error': 'Audio preparation failed'}), 500
            
    except Exception as e:
        print(f"Host[{device_id}]: Audio preparation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@host_restart_bp.route('/generateEdgeSpeech', methods=['POST'])
@route_exception_handler()
def generate_edge_speech():
    """Step 2: Generate Edge-TTS speech ~3-5s"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        target_language = data.get('target_language', 'es')
        existing_transcript = data.get('existing_transcript', '')
        
        if not existing_transcript:
            return jsonify({'success': False, 'error': 'Transcript required for speech generation'}), 400
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        print(f"Host[{device_id}]: Step 2 - Generating Edge-TTS speech for {target_language}...")
        result = av_controller.generateEdgeSpeech(video_id, target_language, existing_transcript)
        
        if result and result.get('success'):
            print(f"Host[{device_id}]: Step 2 completed in {result.get('duration_seconds', 0)}s")
            return jsonify(result)
        else:
            return jsonify(result or {'success': False, 'error': 'Edge-TTS generation failed'}), 500
            
    except Exception as e:
        print(f"Host[{device_id}]: Edge-TTS generation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/createDubbedVideo', methods=['POST'])
@route_exception_handler()
def create_dubbed_video():
    """Step 3: Create final dubbed video ~5-8s"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        target_language = data.get('target_language', 'es')
        voice_choice = data.get('voice_choice', 'edge')  # Only 'edge' supported
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        print(f"Host[{device_id}]: Step 3 - Creating dubbed video with {voice_choice} voice...")
        result = av_controller.createDubbedVideo(video_id, target_language, voice_choice)
        
        if result and result.get('success'):
            print(f"Host[{device_id}]: Step 3 completed in {result.get('duration_seconds', 0)}s")
            return jsonify(result)
        else:
            return jsonify(result or {'success': False, 'error': 'Video creation failed'}), 500
            
    except Exception as e:
        print(f"Host[{device_id}]: Video creation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/createDubbedVideoFast', methods=['POST'])
@route_exception_handler()
def create_dubbed_video_fast():
    """NEW: Fast 2-step dubbed video creation ~5-8s"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id', 'device1')
        video_id = data.get('video_id')
        target_language = data.get('target_language', 'es')
        existing_transcript = data.get('existing_transcript', '')
        
        if not existing_transcript:
            return jsonify({'success': False, 'error': 'Transcript required for fast dubbing'}), 400
        
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        print(f"Host[{device_id}]: Fast dubbing - Creating dubbed video for {target_language}...")
        result = av_controller.createDubbedVideoFast(video_id, target_language, existing_transcript)
        
        if result and result.get('success'):
            print(f"Host[{device_id}]: Fast dubbing completed in {result.get('duration_seconds', 0)}s")
            return jsonify(result)
        else:
            return jsonify(result or {'success': False, 'error': 'Fast dubbing failed'}), 500
            
    except Exception as e:
        print(f"Host[{device_id}]: Fast dubbing error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@host_restart_bp.route('/adjustAudioTiming', methods=['POST'])
@route_exception_handler()
def adjust_audio_timing():
    """Adjust audio timing for existing restart video."""
    try:
        data = request.get_json()
        device_id = data.get('device_id', 'device1')
        video_url = data.get('video_url')
        timing_offset_ms = data.get('timing_offset_ms', 0)
        language = data.get('language', 'original')
        
        # Optional component paths from frontend
        silent_video_path = data.get('silent_video_path')
        background_audio_path = data.get('background_audio_path')
        vocals_path = data.get('vocals_path')
        
        if not video_url:
            return jsonify({'success': False, 'error': 'video_url is required'}), 400
        
        if timing_offset_ms == 0:
            return jsonify({'success': False, 'error': 'timing_offset_ms cannot be 0'}), 400
        
        # Get AV controller
        av_controller = get_controller(device_id, 'av')
        if not av_controller:
            return jsonify({'success': False, 'error': f'No AV controller for {device_id}'}), 404
        
        print(f"Host[{device_id}]: Adjusting audio timing by {timing_offset_ms:+d}ms for {language}")
        result = av_controller.adjustVideoAudioTiming(video_url, timing_offset_ms, language, 
                                                    silent_video_path, background_audio_path, vocals_path)
        
        if result and result.get('success'):
            print(f"Host[{device_id}]: Audio timing adjustment completed")
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': 'Audio timing adjustment failed'}), 500
            
    except Exception as e:
        print(f"Host[{device_id}]: Audio timing adjustment error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
