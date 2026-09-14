"""Host Transcript Routes - On-demand translation and dubbing"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
import os
import json
import time
from pathlib import Path
from datetime import datetime

host_transcript_bp = Blueprint('host_transcript', __name__, url_prefix='/host/transcript')


@host_transcript_bp.route('/translate-chunk', methods=['POST'])
@route_exception_handler()
def translate_chunk():
    data = request.get_json() or {}
    chunk_url = data.get('chunk_url')
    target_language = data.get('language')
    
    if not chunk_url or not target_language:
        return jsonify({'success': False, 'error': 'Missing chunk_url or language'}), 400
    
    from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
    original_file = convertHostUrlToLocalPath(chunk_url) if chunk_url.startswith(('http://', 'https://')) else None
    
    if not original_file or not os.path.exists(original_file):
        return jsonify({'success': False, 'error': 'Transcript not found'}), 404
    
    base_path, ext = os.path.splitext(original_file)
    translated_file = f"{base_path}_{target_language}{ext}"
    
    if os.path.exists(translated_file):
        with open(translated_file, 'r') as f:
            return jsonify({'success': True, 'cached': True, 'language': target_language})
    
    with open(original_file, 'r') as f:
        original_data = json.load(f)
    
    segments = original_data.get('segments', [])
    if not segments:
        return jsonify({'success': False, 'error': 'No segments found'}), 400
    
    from backend_host.src.lib.utils.ai_transcript_utils import translate_segments
    
    ai_result = translate_segments(
        segments=segments,
        source_language=original_data.get('language', 'unknown'),
        target_language=target_language
    )
    
    if not ai_result['success']:
        return jsonify({'success': False, 'error': f"AI: {ai_result.get('error')}"}), 500
    
    translated_data = original_data.copy()
    translated_data['segments'] = ai_result['segments']
    translated_data['transcript'] = ' '.join([seg['text'] for seg in ai_result['segments']])
    translated_data['translated_to'] = target_language
    translated_data['translation_timestamp'] = datetime.now().isoformat()
    
    os.makedirs(os.path.dirname(translated_file), exist_ok=True)
    with open(translated_file + '.tmp', 'w') as f:
        json.dump(translated_data, f, indent=2)
    # Windows-safe atomic overwrite (os.rename fails if destination exists)
    os.replace(translated_file + '.tmp', translated_file)
    
    print(f"[@host_transcript] ✅ Translated to {target_language} in {ai_result['processing_time']:.2f}s")
    
    return jsonify({'success': True, 'cached': False, 'language': target_language, 'processing_time': ai_result['processing_time']})
    
@host_transcript_bp.route('/generate-dubbed-audio', methods=['POST'])
@route_exception_handler()
def generate_dubbed_audio():
    data = request.get_json() or {}
    device_id = data.get('device_id')
    hour = data.get('hour')
    chunk_index = data.get('chunk_index')
    language = data.get('language')
    
    print(f"[@host_transcript] Dubbed audio request: {device_id}/{hour}/{chunk_index} → {language}")
    
    if not all([device_id, hour is not None, chunk_index is not None, language]):
        return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
    
    # Get av_controller to access video_capture_path (same pattern as host_av_routes.py)
    from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id
    
    av_controller = get_controller(device_id, 'av')
    if not av_controller:
        device = get_device_by_id(device_id)
        if not device:
            return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
        return jsonify({'success': False, 'error': f'No AV controller found for device {device_id}'}), 404
    
    # Get capture folder from controller's video_capture_path
    from shared.src.lib.utils.storage_path_utils import (
        get_capture_folder,
        get_transcript_chunk_path,
        get_audio_chunk_path
    )
    
    capture_folder = get_capture_folder(av_controller.video_capture_path)
    if not capture_folder:
        return jsonify({'success': False, 'error': f'Could not determine capture folder for device {device_id}'}), 404
    
    # Check if audio already exists using CENTRALIZED function
    audio_file = get_audio_chunk_path(capture_folder, hour, chunk_index, language)
    
    if os.path.exists(audio_file):
        return jsonify({
            'success': True,
            'url': f'host/stream/{capture_folder}/audio/{hour}/chunk_10min_{chunk_index}_{language}.mp3',
            'status': 'ready',
            'cached': True
        })
    
    # Load translated transcript using CENTRALIZED function
    transcript_file = get_transcript_chunk_path(capture_folder, hour, chunk_index, language)
    
    print(f"[@host_transcript] Looking for transcript: {transcript_file}")
    
    if not os.path.exists(transcript_file):
        print(f"[@host_transcript] ❌ Translated transcript not found: {transcript_file}")
        return jsonify({'success': False, 'error': f'Translation not available for {language}'}), 404
    
    # Generate dubbed audio from translated transcript
    from backend_host.src.lib.utils.audio_utils import generate_edge_tts_audio, EDGE_TTS_VOICE_MAP
    
    with open(transcript_file, 'r') as f:
        data = json.load(f)
    
    translated_text = data.get('transcript', '')
    print(f"[@host_transcript] Loaded transcript ({len(translated_text)} chars)")
    
    if not translated_text:
        print(f"[@host_transcript] ❌ Transcript file exists but contains no text")
        return jsonify({'success': False, 'error': 'No transcript text found'}), 404
    
    voice_name = EDGE_TTS_VOICE_MAP.get(language)
    if not voice_name:
        return jsonify({
            'success': False,
            'error': f'Voice not available for {language}'
        }), 400
    
    # Create audio directory (from centralized path)
    audio_hour_dir = os.path.dirname(audio_file)
    os.makedirs(audio_hour_dir, exist_ok=True)
    
    # Generate dubbed audio using Edge TTS
    print(f"[@host_transcript] Generating TTS audio with voice: {voice_name}")
    success = generate_edge_tts_audio(
        text=translated_text,
        language_code=language,
        output_path=audio_file,
        voice_name=voice_name
    )
    
    if not success or not os.path.exists(audio_file):
        return jsonify({
            'success': False,
            'error': 'Failed to generate dubbed audio'
        }), 500
    
    audio_url = f'host/stream/{capture_folder}/audio/{hour}/chunk_10min_{chunk_index}_{language}.mp3'
    print(f"[@host_transcript] ✅ Generated dubbed audio: {audio_url}")
    
    return jsonify({
        'success': True,
        'url': audio_url,
        'status': 'ready',
        'cached': False,
        'size': os.path.getsize(audio_file)
    })
    
