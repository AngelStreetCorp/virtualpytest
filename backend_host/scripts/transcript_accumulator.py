#!/usr/bin/env python3
"""
Event-driven Transcript Accumulator - MP3 Transcription Only
Event-driven processing: Zero CPU when idle, immediate response to new files

Cross-platform: Uses inotify on Linux, watchdog on macOS

COLD STORAGE ARCHITECTURE:
  - Watches COLD /audio/temp/ for 1min MP3 files (instant transcription)
  - Scans COLD /audio/{hour}/ for 10min MP3 chunks (backfill/recovery)
  - MP3s created by hot_cold_archiver.py (extracted from MP4 segments)

Instant transcription: 1min MP3 → immediate Whisper transcription → merge to JSON
Progressive save: Transcripts saved by minute to chunk_10min_X.json

USAGE:
  --transcript true   Enable MP3 transcription (CPU-intensive Whisper processing)
  --transcript false  Disable transcription (default - audio detection only)
  
Audio detection ALWAYS runs (lightweight, critical for incident system)
"""

# CRITICAL: Limit CPU threads BEFORE importing PyTorch/Whisper
# PyTorch/NumPy/OpenBLAS create 40+ threads by default, killing performance
import os
os.environ['OMP_NUM_THREADS'] = '2'          # OpenMP
os.environ['MKL_NUM_THREADS'] = '2'          # Intel MKL
os.environ['OPENBLAS_NUM_THREADS'] = '2'     # OpenBLAS
os.environ['NUMEXPR_NUM_THREADS'] = '2'      # NumExpr
os.environ['VECLIB_MAXIMUM_THREADS'] = '2'   # macOS Accelerate
# os.environ['TORCH_NUM_THREADS'] = '2'      # PyTorch - REMOVED (torch no longer used)

import sys
import json
import subprocess
import logging
import queue
from queue import LifoQueue
import threading
from collections import defaultdict
from datetime import datetime
import time
from pathlib import Path
import argparse

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_host_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_host_dir)
sys.path.insert(0, project_root)

import platform

# Cross-platform file monitoring: inotify on Linux, watchdog on macOS
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

if IS_LINUX:
    import inotify.adapters
else:
    # macOS/other: use watchdog (cross-platform)
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

from shared.src.lib.utils.storage_path_utils import (
    get_capture_base_directories, 
    get_capture_folder, 
    get_device_info_from_capture_folder, 
    get_device_base_path,
    get_audio_path,
    get_transcript_path,
    get_cold_segments_path,
    get_metadata_path,
    get_segments_path,
    get_captures_path
)

from shared.src.lib.utils.audio_transcription_utils import (
    transcribe_audio,
    clean_transcript_text,
    correct_spelling,
    check_audio_level,
    ENABLE_SPELLCHECK
)

logger = logging.getLogger(__name__)

# Pre-translation target languages
TRANSLATION_LANGUAGES = {
    'fr': 'French',
    'en': 'English',
    'es': 'Spanish',
    'de': 'German',
    'it': 'Italian'
}

# Configuration
CHUNK_DURATION_MINUTES = 10
SEGMENT_DURATION_MINUTES = 1
ENABLE_DUBBED_AUDIO = False  # Set to True to enable automatic dubbed audio generation

_chunk_languages = {}

def cleanup_logs_on_startup():
    """Clean up log file on service restart for fresh debugging"""
    try:
        log_file = '/tmp/transcript_accumulator.log'
        
        print(f"[@transcript_accumulator] Cleaning log on service restart...")
        
        if os.path.exists(log_file):
            with open(log_file, 'w') as f:
                f.write(f"=== LOG CLEANED ON SERVICE RESTART: {datetime.now().isoformat()} ===\n")
            print(f"[@transcript_accumulator] ✓ Cleaned: {log_file}")
        else:
            print(f"[@transcript_accumulator] ○ Not found (will be created): {log_file}")
                
        print(f"[@transcript_accumulator] Log cleanup complete - fresh logs for debugging")
                
    except Exception as e:
        print(f"[@transcript_accumulator] Warning: Could not clean log file: {e}")

def get_chunk_language(capture_folder: str, hour: int, chunk_index: int):
    global _chunk_languages
    chunk_key = f"{capture_folder}_{hour}_{chunk_index}"
    return _chunk_languages.get(chunk_key)

def set_chunk_language(capture_folder: str, hour: int, chunk_index: int, language: str):
    global _chunk_languages
    chunk_key = f"{capture_folder}_{hour}_{chunk_index}"
    _chunk_languages[chunk_key] = language

def check_mp3_has_audio(mp3_path: str, capture_folder: str, sample_duration: float = 5.0) -> tuple[bool, float]:
    """
    Check if MP3 has actual audio content (not silence) using ffmpeg volumedetect
    
    DEPRECATED: This function now wraps the shared check_audio_level() utility.
    Use check_audio_level() directly for new code.
    
    Args:
        mp3_path: Path to MP3 file
        capture_folder: Device identifier (for logging)
        sample_duration: Duration to sample in seconds (default 5.0s)
    
    Returns:
        (has_audio: bool, mean_volume_db: float)
    """
    # Use shared utility (same logic, no duplication)
    has_audio, mean_volume = check_audio_level(
        file_path=mp3_path,
        sample_duration=sample_duration,
        context=capture_folder
    )
    
    # On error (mean_volume = -100.0), assume has audio (safer to transcribe than skip)
    if mean_volume == -100.0 and not has_audio:
        return True, 0.0
    
    return has_audio, mean_volume

def transcribe_mp3_chunk_progressive(mp3_path: str, capture_folder: str, hour: int, chunk_index: int) -> list:
    """
    Transcribe 10-minute MP3 once, return results grouped by minute for progressive merging
    
    Returns:
        List of minute_data dicts (one per minute 0-9)
    """
    try:
        import psutil
        
        process = psutil.Process()
        cpu_before = process.cpu_percent(interval=None)  # Initialize CPU monitoring
        
        GREEN = '\033[92m'
        RESET = '\033[0m'
        logger.info(f"{GREEN}[WHISPER:{capture_folder}] 🎬 Processing: {mp3_path} (transcribe once, save progressively){RESET}")

        has_audio, mean_volume_db = check_mp3_has_audio(mp3_path, capture_folder, sample_duration=5.0)
        
        if not has_audio:
            logger.info(f"[{capture_folder}] ⏭️  SKIPPED: chunk silent ({mean_volume_db:.1f}dB)")
            # Return silent minute data to trigger rolling 24h cleanup
            return [{
                'minute_offset': i,
                'language': 'unknown',
                'transcript': '',
                'segments': [],
                'skip_reason': f'silent_audio_{mean_volume_db:.1f}dB'
            } for i in range(10)]
        
        # Log CPU before Whisper execution
        time.sleep(0.1)  # Small delay to get accurate baseline
        cpu_before = process.cpu_percent(interval=None)
        
        total_start = time.time()
        result = transcribe_audio(mp3_path, model_name='tiny', skip_silence_check=True, device_id=capture_folder)
        elapsed = time.time() - total_start
        cpu_after = process.cpu_percent(interval=None)
        
        segments = result.get('segments', [])
        language = result.get('language', 'unknown')
        language_code = result.get('language_code', 'unknown')
        confidence = result.get('confidence', 0.0)
        audio_duration = result.get('duration', 0.0)
        
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RESET = '\033[0m'
        
        # Get text preview from first segment (if any)
        text_preview = ""
        if segments:
            first_text = segments[0].get('text', '').strip()
            text_preview = f' | Text: "{first_text[:60]}..."' if first_text else ""
        
        # Duration 0.0s = Whisper detected silence/no speech (normal for silent sources)
        duration_note = " (silent audio)" if audio_duration == 0 else ""
        
        # Calculate Real-Time Factor (RTF): how fast Whisper processes vs real-time
        # RTF < 1.0 = faster than real-time (good!)
        # RTF = 1.0 = real-time speed
        # RTF > 1.0 = slower than real-time (problematic)
        rtf = elapsed / audio_duration if audio_duration > 0 else 0.0
        rtf_note = f" (RTF={rtf:.2f}x)"
        
        logger.info(f"{GREEN}[WHISPER:{capture_folder}] ✅ TRANSCRIPTION COMPLETE:{RESET}")
        logger.info(f"{GREEN}  • Whisper processing time: {elapsed:.1f}s for {audio_duration:.1f}s audio{rtf_note}{duration_note}{RESET}")
        logger.info(f"{GREEN}  • Language: {language} ({language_code}), Confidence: {confidence:.2f}{RESET}")
        logger.info(f"{GREEN}  • Segments: {len(segments)}, CPU: {cpu_before:.1f}%→{cpu_after:.1f}%{text_preview}{RESET}")
        
        minute_groups = {}
        for i in range(10):
            minute_groups[i] = []
        
        for segment in segments:
            start_time = segment.get('start', 0)
            minute_offset = int(start_time // 60)
            if minute_offset < 10:
                minute_groups[minute_offset].append(segment)
        
        minute_results = []
        for minute_offset in range(10):
            minute_segments = minute_groups[minute_offset]
            
            if not minute_segments:
                continue
            
            minute_transcript = ' '.join([s.get('text', '').strip() for s in minute_segments])
            minute_transcript = clean_transcript_text(minute_transcript)
            if ENABLE_SPELLCHECK:
                minute_transcript = correct_spelling(minute_transcript, result.get('language_code'))
            
            GREEN = '\033[92m'
            RESET = '\033[0m'
            logger.info(f"{GREEN}[{capture_folder}] 📝 Minute {minute_offset}: {len(minute_segments)} segments, {len(minute_transcript)} chars - \"{minute_transcript[:50]}...\"{RESET}")
            
            minute_results.append({
                'minute_offset': minute_offset,
                'language': language,
                'transcript': minute_transcript,
                'segments': minute_segments
            })
        
        return minute_results
        
    except Exception as e:
        logger.error(f"[{capture_folder}] ❌ Error: {e}")
        return []

def merge_minute_to_chunk(capture_folder: str, hour: int, chunk_index: int, minute_data: dict, has_mp3: bool = True):
    """
    Progressively append segments to 10-minute chunk (same format as before)
    
    Args:
        capture_folder: Device folder name (e.g., 'capture1')
        hour: Hour (0-23)
        chunk_index: Chunk index (0-5)
        minute_data: Minute transcription data with segments to append
        has_mp3: Whether corresponding MP3 exists
    """
    from shared.src.lib.utils.file_lock_utils import lock_file, unlock_file
    
    transcript_base = get_transcript_path(capture_folder)
    transcript_dir = os.path.join(transcript_base, str(hour))
    os.makedirs(transcript_dir, exist_ok=True)
    
    chunk_path = os.path.join(transcript_dir, f'chunk_10min_{chunk_index}.json')
    
    lock_path = chunk_path + '.lock'
    with open(lock_path, 'w') as lock_fh:
        lock_file(lock_fh, exclusive=True)
        
        try:
            if os.path.exists(chunk_path):
                with open(chunk_path, 'r') as f:
                    chunk_data = json.load(f)
                if 'segments' not in chunk_data:
                    chunk_data['segments'] = []
                if 'minute_statuses' not in chunk_data:
                    chunk_data['minute_statuses'] = {}
            else:
                chunk_data = {
                    'capture_folder': capture_folder,
                    'hour': hour,
                    'chunk_index': chunk_index,
                    'chunk_duration_minutes': CHUNK_DURATION_MINUTES,
                    'language': None,  # Will be set when first segment is added
                    'transcript': '',
                    'confidence': 0.0,
                    'transcription_time_seconds': 0.0,
                    'timestamp': datetime.now().isoformat(),
                    'mp3_file': f'chunk_10min_{chunk_index}.mp3' if has_mp3 else None,
                    'segments': [],
                    'minute_statuses': {}  # Track processing status per minute
                }
            
            minute_segments = minute_data.get('segments', [])
            minute_offset = minute_data.get('minute_offset')
            
            # Mark minute as processed (even if no segments - could be silent or skipped)
            processed_day = datetime.now().strftime('%Y-%m-%d')
            has_audio = len(minute_segments) > 0
            skip_reason = minute_data.get('skip_reason')
            
            # ROLLING 24H: Check if existing chunk is from previous day - if so, clear it
            should_clear_old_data = False
            if chunk_data['minute_statuses']:
                # Check if any existing minute is from a different day
                existing_days = {status.get('processed_day') for status in chunk_data['minute_statuses'].values() if status.get('processed_day')}
                if existing_days and processed_day not in existing_days:
                    logger.info(f"[{capture_folder}] 🔄 New day detected for {hour}h/chunk_{chunk_index} (old: {existing_days}, new: {processed_day}) - clearing old segments")
                    should_clear_old_data = True
            else:
                # Fallback: If no minute_statuses data (empty or old format), check file age
                # This prevents mixing transcripts from different days when minute_statuses is missing
                if os.path.exists(chunk_path):
                    file_age_seconds = time.time() - os.path.getmtime(chunk_path)
                    # If file is older than 10 minutes, it's from a previous window - clear it
                    if file_age_seconds > 600:  # 10 minutes (same as hot_cold_archiver logic)
                        file_age_hours = file_age_seconds / 3600
                        logger.info(f"[{capture_folder}] 🔄 Old transcript detected (age: {file_age_hours:.1f}h, no minute_statuses) for {hour}h/chunk_{chunk_index} - clearing old data")
                        should_clear_old_data = True
            
            if should_clear_old_data:
                # Clear old day's data completely
                was_silent = skip_reason and 'silent_audio' in skip_reason
                old_transcript_length = len(chunk_data.get('transcript', ''))
                chunk_data['segments'] = []
                chunk_data['minute_statuses'] = {}
                chunk_data['transcript'] = ''
                chunk_data['confidence'] = 0.0
                chunk_data['timestamp'] = datetime.now().isoformat()
                
                # Log cleanup with context (especially important for silent periods)
                if was_silent and old_transcript_length > 0:
                    logger.info(f"[{capture_folder}] 🧹 CLEANUP: Cleared old transcript ({old_transcript_length} chars) due to silent audio - prevents showing yesterday's transcript")
            
            chunk_data['minute_statuses'][str(minute_offset)] = {
                'processed': True,
                'processed_day': processed_day,
                'has_audio': has_audio,
                'skip_reason': skip_reason
            }
            
            # Apply timestamp offset to convert minute-relative times (0-60s) to chunk-relative times
            # Example: minute 3 segments at 0-60s become 180-240s in the chunk
            time_offset_seconds = minute_offset * 60
            offset_segments = []
            for seg in minute_segments:
                offset_seg = seg.copy()
                offset_seg['start'] = seg.get('start', 0) + time_offset_seconds
                offset_seg['end'] = seg.get('end', 0) + time_offset_seconds
                offset_segments.append(offset_seg)
            
            existing_starts = {s.get('start') for s in chunk_data['segments']}
            new_segments = [s for s in offset_segments if s.get('start') not in existing_starts]
            
            if new_segments:
                chunk_data['segments'].extend(new_segments)
                chunk_data['segments'].sort(key=lambda x: x.get('start', 0))
                
                full_transcript = ' '.join([s.get('text', '').strip() for s in chunk_data['segments']])
                chunk_data['transcript'] = full_transcript
                
                # Only update language if we have a valid detected language (not 'unknown')
                detected_lang = minute_data.get('language')
                if detected_lang and detected_lang != 'unknown':
                    chunk_data['language'] = detected_lang
                elif not chunk_data.get('language'):
                    chunk_data['language'] = None  # Keep as None if still unknown
                
                if chunk_data['segments']:
                    confidences = [s.get('confidence', 0) for s in chunk_data['segments'] if 'confidence' in s]
                    chunk_data['confidence'] = sum(confidences) / len(confidences) if confidences else 0.0
                
                chunk_data['timestamp'] = datetime.now().isoformat()
                
                # Calculate total audio duration from segments
                if chunk_data['segments']:
                    last_segment = max(chunk_data['segments'], key=lambda s: s.get('end', 0))
                    chunk_duration_seconds = last_segment.get('end', 0)
                    chunk_data['chunk_duration_seconds'] = chunk_duration_seconds
                else:
                    chunk_data['chunk_duration_seconds'] = 0.0
            
            with open(chunk_path + '.tmp', 'w') as f:
                json.dump(chunk_data, f, indent=2)
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(chunk_path + '.tmp', chunk_path)
            
            # Log ONLY if actual audio data was merged (not status updates)
            if new_segments:
                # Real audio data merged - show detailed log
                GREEN = '\033[92m'
                RESET = '\033[0m'
                
                # Build full MP3 path for logging
                mp3_filename = chunk_data.get('mp3_file')
                if mp3_filename:
                    from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
                    audio_cold = get_cold_storage_path(capture_folder, 'audio')
                    mp3_full_path = os.path.join(audio_cold, str(hour), mp3_filename)
                else:
                    mp3_full_path = "None"
                
                logger.info(f"{GREEN}[{capture_folder}] 💾 Merged transcript to→ {hour}h/chunk_{chunk_index}: {len(chunk_data['segments'])} total segments, {len(chunk_data['transcript'])} chars{RESET}")
                logger.info(f"{GREEN}[{capture_folder}] 📄 language={chunk_data.get('language')}, confidence={chunk_data.get('confidence', 0):.2f}, audio_duration={chunk_data.get('chunk_duration_seconds', 0):.1f}s{RESET}")
                logger.info(f"{GREEN}[{capture_folder}] 🎵 mp3_file={mp3_full_path}{RESET}")
                
                # Show newly added minute's transcript (full text for this minute)
                minute_transcript = ' '.join([s.get('text', '').strip() for s in new_segments])
                if len(minute_transcript) > 500:
                    logger.info(f"{GREEN}[{capture_folder}] 📋 (minute {minute_offset}) Transcript: \"{minute_transcript[:500]}...\" (truncated, {len(minute_transcript)} chars total){RESET}")
                else:
                    logger.info(f"{GREEN}[{capture_folder}] 📋 (minute {minute_offset}) Transcript: \"{minute_transcript}\"{RESET}")
                
                # Show segment statistics
                sample_seg = new_segments[0]
                seg_duration = sample_seg.get('duration', sample_seg.get('end', 0) - sample_seg.get('start', 0))
                logger.info(f"{GREEN}[{capture_folder}] 📊 Added {len(new_segments)} segments: first segment at {sample_seg.get('start', 0):.2f}s, duration={seg_duration:.2f}s, confidence={sample_seg.get('confidence', 0):.2f}{RESET}")
                
                # Show full chunk transcript if it's substantial (e.g., > 200 chars)
                full_transcript = chunk_data['transcript']
                if len(full_transcript) >= 200:
                    if len(full_transcript) > 1000:
                        logger.info(f"{GREEN}[{capture_folder}] 📝 FULL CHUNK TRANSCRIPT: \"{full_transcript[:1000]}...\" (truncated, {len(full_transcript)} chars total){RESET}")
                    else:
                        logger.info(f"{GREEN}[{capture_folder}] 📝 FULL CHUNK TRANSCRIPT: \"{full_transcript}\"{RESET}")
            else:
                # No audio merged - just status tracking (silent minute)
                logger.debug(f"[{capture_folder}] ✓ Updated chunk {hour}h/chunk_{chunk_index} status: minute {minute_offset} processed (skip_reason: {skip_reason or 'no_audio'})")
    
        finally:
            unlock_file(lock_fh)
    
    try:
        os.remove(lock_path)
    except:
        pass
    
    try:
        device_base_path = get_device_base_path(capture_folder)
        from backend_host.scripts.hot_cold_archiver import update_transcript_manifest
        update_transcript_manifest(device_base_path, hour, chunk_index, chunk_path, has_mp3=has_mp3)
        
        # NOTE: AI translation now on-demand via /host/transcript/translate-chunk endpoint
        # No automatic 10-minute translation to reduce CPU load
        # if new_segments and len(chunk_data.get('transcript', '')) > 20:
        #     translate_chunk_to_languages(capture_folder, hour, chunk_index, chunk_path, device_base_path)
    except Exception as e:
        logger.warning(f"Failed to update transcript manifest: {e}")

def translate_chunk_to_languages(capture_folder: str, hour: int, chunk_index: int, chunk_path: str, device_base_path: str):
    """Merge 1-minute translations OR translate 10-minute chunk directly (backlog fallback)"""
    try:
        with open(chunk_path, 'r') as f:
            original_data = json.load(f)
        
        full_transcript = original_data.get('transcript', '')
        if not full_transcript or len(full_transcript) < 20:
            return
        
        GREEN = '\033[92m'
        CYAN = '\033[96m'
        RESET = '\033[0m'
        
        transcript_dir = os.path.dirname(chunk_path)
        
        has_any_1min = False
        for slot in range(10):
            if os.path.exists(os.path.join(transcript_dir, f'1min_{slot}_en.json')):
                has_any_1min = True
                break
        
        if not has_any_1min:
            logger.info(f"{CYAN}[10MIN-AI:{capture_folder}] No 1min files, translating 10min chunk directly...{RESET}")
            from backend_host.src.lib.utils.ai_transcript_utils import enhance_and_translate_transcript
            
            ai_result = enhance_and_translate_transcript(
                full_transcript,
                original_data.get('language', 'unknown'),
                list(TRANSLATION_LANGUAGES.keys())
            )
            
            if ai_result['success']:
                translations_dict = ai_result.get('translations', {})
                for lang_code, translated_text in translations_dict.items():
                    if not translated_text:
                        continue
                    
                    translated_data = original_data.copy()
                    translated_data['transcript'] = translated_text
                    translated_data['source_language'] = original_data.get('language')
                    translated_data['translated_to'] = lang_code
                    translated_data['translation_timestamp'] = datetime.now().isoformat()
                    
                    lang_file_path = os.path.join(transcript_dir, f'chunk_10min_{chunk_index}_{lang_code}.json')
                    with open(lang_file_path + '.tmp', 'w') as f:
                        json.dump(translated_data, f, indent=2)
                    # Windows-safe atomic overwrite (os.rename fails if destination exists)
                    os.replace(lang_file_path + '.tmp', lang_file_path)
                    
                    logger.info(f"{GREEN}[10MIN-AI:{capture_folder}] ✅ {lang_code}: {len(translated_text)} chars{RESET}")
            else:
                logger.warning(f"[10MIN-AI:{capture_folder}] AI translation failed: {ai_result.get('error')}")
        else:
            merge_start = time.time()
            merged_count = 0
            
            for lang_code, lang_name in TRANSLATION_LANGUAGES.items():
                translations = []
                
                for slot in range(10):
                    slot_file = os.path.join(transcript_dir, f'1min_{slot}_{lang_code}.json')
                    if os.path.exists(slot_file):
                        with open(slot_file, 'r') as f:
                            data = json.load(f)
                            translations.append(data.get('transcript', ''))
                
                if not translations:
                    continue
                
                merged_text = ' '.join(translations)
                
                translated_data = original_data.copy()
                translated_data['transcript'] = merged_text
                translated_data['source_language'] = original_data.get('language')
                translated_data['translated_to'] = lang_code
                translated_data['translation_timestamp'] = datetime.now().isoformat()
                
                lang_file_path = os.path.join(transcript_dir, f'chunk_10min_{chunk_index}_{lang_code}.json')
                with open(lang_file_path + '.tmp', 'w') as f:
                    json.dump(translated_data, f, indent=2)
                # Windows-safe atomic overwrite (os.rename fails if destination exists)
                os.replace(lang_file_path + '.tmp', lang_file_path)
                
                merged_count += 1
                logger.info(f"{GREEN}[10MIN-MERGE:{capture_folder}] ✅ {lang_code}: {len(translations)}/10 min, {len(merged_text)} chars{RESET}")
            
            merge_elapsed = time.time() - merge_start
            logger.info(f"{GREEN}[10MIN-MERGE:{capture_folder}] 🎉 Merged {merged_count} languages in {merge_elapsed:.2f}s (from 1min AI translations){RESET}")
        
        if ENABLE_DUBBED_AUDIO:
            generate_dubbed_audio_for_chunk(capture_folder, hour, chunk_index, transcript_dir, device_base_path)
        
        from backend_host.scripts.hot_cold_archiver import update_transcript_manifest
        update_transcript_manifest(device_base_path, hour, chunk_index, chunk_path, has_mp3=original_data.get('mp3_file') is not None)
        
    except Exception as e:
        logger.error(f"[10MIN-MERGE:{capture_folder}] ❌ Error: {e}")

def enhance_and_dub_1min(device_folder: str, hour: int, chunk_index: int, slot: int, transcript_text: str, detected_language: str):
    """Single AI call to enhance + translate + dub 1-minute segment"""
    try:
        from backend_host.src.lib.utils.ai_transcript_utils import enhance_and_translate_transcript
        from backend_host.src.lib.utils.audio_utils import generate_edge_tts_audio, EDGE_TTS_VOICE_MAP
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, get_transcript_path
        
        GREEN = '\033[92m'
        CYAN = '\033[96m'
        RESET = '\033[0m'
        
        logger.info(f"{CYAN}[AI-1MIN:{device_folder}] 🤖 Enhancing + translating slot {slot}...{RESET}")
        
        ai_result = enhance_and_translate_transcript(
            transcript_text,
            detected_language,
            list(TRANSLATION_LANGUAGES.keys())
        )
        
        if not ai_result['success']:
            logger.warning(f"[AI-1MIN:{device_folder}] AI failed: {ai_result.get('error')}, skipping 1min translations")
            return
        
        logger.info(f"{GREEN}[AI-1MIN:{device_folder}] ✅ AI processed in {ai_result['processing_time']:.2f}s{RESET}")
        
        transcript_base = get_transcript_path(device_folder)
        transcript_dir = os.path.join(transcript_base, str(hour))
        os.makedirs(transcript_dir, exist_ok=True)
        
        audio_cold = get_cold_storage_path(device_folder, 'audio')
        audio_temp_dir = os.path.join(audio_cold, 'temp')
        os.makedirs(audio_temp_dir, exist_ok=True)
        
        translations = ai_result.get('translations', {})
        
        # Filter to only requested languages (AI sometimes adds extras like pl, pt, ru, zh)
        translations = {k: v for k, v in translations.items() if k in TRANSLATION_LANGUAGES}
        
        for lang_code, translated_text in translations.items():
            if not translated_text or len(translated_text) < 10:
                continue
            
            lang_file = os.path.join(transcript_dir, f'1min_{slot}_{lang_code}.json')
            with open(lang_file, 'w') as f:
                json.dump({
                    'slot': slot,
                    'hour': hour,
                    'chunk_index': chunk_index,
                    'language': lang_code,
                    'transcript': translated_text,
                    'timestamp': datetime.now().isoformat()
                }, f)
            
            file_size = os.path.getsize(lang_file)
            logger.info(f"{GREEN}[AI-1MIN:{device_folder}] ✅ {TRANSLATION_LANGUAGES[lang_code]} subtitle: {file_size/1024:.1f}KB, {len(translated_text)} chars{RESET}")
            
            if ENABLE_DUBBED_AUDIO:
                voice_name = EDGE_TTS_VOICE_MAP.get(lang_code)
                if voice_name:
                    output_mp3 = os.path.join(audio_temp_dir, f'1min_{slot}_{lang_code}.mp3')
                    if os.path.exists(output_mp3):
                        os.remove(output_mp3)
                    
                    tts_start = time.time()
                    success = generate_edge_tts_audio(translated_text, lang_code, output_mp3, voice_name)
                    tts_elapsed = time.time() - tts_start
                    
                    if success and os.path.exists(output_mp3):
                        audio_size = os.path.getsize(output_mp3)
                        logger.info(f"{GREEN}[AI-1MIN:{device_folder}] ✅ {TRANSLATION_LANGUAGES[lang_code]} dub: {audio_size/1024:.1f}KB, {tts_elapsed:.2f}s{RESET}")
        
        status = "translations + dubs" if ENABLE_DUBBED_AUDIO else "subtitles only"
        logger.info(f"{GREEN}[AI-1MIN:{device_folder}] 🎉 Completed {len(translations)} {status} in {ai_result['processing_time']:.2f}s{RESET}")
        
    except Exception as e:
        logger.error(f"[AI-1MIN:{device_folder}] ❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())


def generate_dubbed_audio_for_chunk(capture_folder: str, hour: int, chunk_index: int, transcript_dir: str, device_base_path: str):
    """
    Generate dubbed audio for all translated languages (reuses restart Edge-TTS pipeline!)
    Creates language-specific MP3 files for instant playback.
    
    Args:
        capture_folder: Device folder (e.g., 'capture1')
        hour: Hour (0-23)
        chunk_index: Chunk index (0-5)
        transcript_dir: Directory containing transcript JSONs
        device_base_path: Base path for device
    """
    try:
        # Import required utilities
        try:
            from backend_host.src.lib.utils.audio_utils import generate_edge_tts_audio
        except ImportError as e:
            logger.error(f"[10MIN-DUB:{capture_folder}] ❌ Failed to import audio_utils: {e}")
            logger.error(f"[10MIN-DUB:{capture_folder}] Make sure edge-tts is installed: pip install edge-tts")
            return
        
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
        
        MAGENTA = '\033[95m'
        GREEN = '\033[92m'
        RESET = '\033[0m'
        
        logger.info(f"{MAGENTA}[DUBBING:{capture_folder}] 🎤 Starting dubbed audio generation for {hour}h/chunk_{chunk_index}...{RESET}")
        dubbing_start = time.time()
        dubbed_count = 0
        
        # Get audio output directory (COLD storage)
        audio_cold = get_cold_storage_path(capture_folder, 'audio')
        audio_hour_dir = os.path.join(audio_cold, str(hour))
        os.makedirs(audio_hour_dir, exist_ok=True)
        
        # Import centralized voice mapping (single source of truth)
        from backend_host.src.lib.utils.audio_utils import EDGE_TTS_VOICE_MAP
        voice_map = EDGE_TTS_VOICE_MAP
        
        for lang_code, voice_name in voice_map.items():
            lang_transcript_file = os.path.join(transcript_dir, f'chunk_10min_{chunk_index}_{lang_code}.json')
            
            # Skip if translation doesn't exist
            if not os.path.exists(lang_transcript_file):
                logger.debug(f"[DUBBING:{capture_folder}] Skipping {lang_code} (no translation file)")
                continue
            
            try:
                # Load translated transcript
                with open(lang_transcript_file, 'r') as f:
                    translated_data = json.load(f)
                
                translated_text = translated_data.get('transcript', '')
                if not translated_text or len(translated_text) < 20:
                    logger.debug(f"[DUBBING:{capture_folder}] Skipping {lang_code} (transcript too short)")
                    continue
                
                # Generate dubbed audio using Edge-TTS (SAME as restart!)
                output_mp3 = os.path.join(audio_hour_dir, f'chunk_10min_{chunk_index}_{lang_code}.mp3')
                
                lang_start = time.time()
                success = generate_edge_tts_audio(
                    text=translated_text,
                    language_code=lang_code,
                    output_path=output_mp3,
                    voice_name=voice_name
                )
                lang_elapsed = time.time() - lang_start
                
                if success and os.path.exists(output_mp3):
                    audio_size = os.path.getsize(output_mp3)
                    dubbed_count += 1
                    
                    # Detailed 10min dubbed audio log
                    logger.info(f"{GREEN}[10MIN-DUB:{capture_folder}] ✅ Created 10-minute dubbed audio:{RESET}")
                    logger.info(f"{GREEN}  • Language: {TRANSLATION_LANGUAGES[lang_code]} ({lang_code}){RESET}")
                    logger.info(f"{GREEN}  • File: {output_mp3}{RESET}")
                    logger.info(f"{GREEN}  • Size: {audio_size/1024:.1f}KB, Duration: ~10min, Time: {lang_elapsed:.2f}s{RESET}")
                    logger.info(f"{GREEN}  • Hour: {hour}, Chunk: {chunk_index}{RESET}")
                    
                    # Show preview of dubbed text
                    preview = translated_text[:100] + '...' if len(translated_text) > 100 else translated_text
                    logger.info(f"{GREEN}  • Text: \"{preview}\"{RESET}")
                else:
                    logger.warning(f"[10MIN-DUB:{capture_folder}] ⚠️  Failed to generate {lang_code} audio")
                
            except Exception as e:
                logger.error(f"[DUBBING:{capture_folder}] ❌ Error generating {lang_code} audio: {e}")
                continue
        
        total_elapsed = time.time() - dubbing_start
        logger.info(f"{GREEN}[10MIN-DUB-BATCH:{capture_folder}] 🎉 Completed {dubbed_count}/{len(voice_map)} 10-minute dubbed audio files in {total_elapsed:.2f}s{RESET}")
        
        if dubbed_count > 0:
            avg_time = total_elapsed / dubbed_count
            logger.info(f"{GREEN}[10MIN-DUB-BATCH:{capture_folder}] 📊 Average time per dubbed audio: {avg_time:.2f}s{RESET}")
        
    except Exception as e:
        logger.error(f"[DUBBING:{capture_folder}] ❌ Dubbing error: {e}")
        import traceback
        logger.error(f"[DUBBING:{capture_folder}] Traceback: {traceback.format_exc()}")

def should_skip_minute_by_metadata(capture_folder: str, hour: int, minute_in_hour: int) -> tuple[bool, str]:
    """
    Check metadata JSONs for a 1-minute period to determine if transcription should be skipped
    
    Args:
        capture_folder: Device folder (e.g., 'capture1')
        hour: Hour (0-23)
        minute_in_hour: Minute within hour (0-59)
    
    Returns:
        (should_skip: bool, reason: str)
    """
    try:
        metadata_path = get_metadata_path(capture_folder)
        
        # Calculate sequence range for this minute (5 fps = ~300 frames per minute)
        # But we only check sampled frames (every 5th frame = 1fps in metadata)
        # So ~60 frames per minute to check
        
        # Heuristic: Check 10 sample frames across the minute (every 6 seconds)
        has_good_frames = 0
        has_incidents = 0
        has_no_audio = 0
        checked = 0
        
        # We need to map hour+minute to sequence numbers
        # Sequences are continuous, but we don't know the start sequence for this device
        # Better approach: scan metadata dir for JSONs with matching timestamps
        
        # Get all JSONs from metadata directory
        if not os.path.exists(metadata_path):
            return False, None
        
        target_hour = hour
        target_minute = minute_in_hour
        
        # Sample up to 10 files from this minute
        sample_count = 0
        max_samples = 10
        
        try:
            # Get all capture JSONs sorted by name (sequence order)
            json_files = sorted([f for f in os.listdir(metadata_path) if f.startswith('capture_') and f.endswith('.json')])
            
            for json_file in json_files:
                if sample_count >= max_samples:
                    break
                
                json_path = os.path.join(metadata_path, json_file)
                
                try:
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                    
                    # Check timestamp
                    timestamp = data.get('timestamp')
                    if not timestamp:
                        continue
                    
                    # Parse timestamp to get hour and minute
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    if dt.hour != target_hour or dt.minute != target_minute:
                        continue
                    
                    # This frame is in our target minute
                    checked += 1
                    sample_count += 1
                    
                    # Check for incidents
                    freeze = data.get('freeze', False)
                    blackscreen = data.get('blackscreen', False)
                    has_audio = data.get('audio', True)
                    
                    if freeze or blackscreen:
                        has_incidents += 1
                    
                    if not has_audio:
                        has_no_audio += 1
                    
                    if not freeze and not blackscreen and has_audio:
                        has_good_frames += 1
                
                except Exception as e:
                    continue
        
        except Exception as e:
            logger.debug(f"[{capture_folder}] Metadata check failed: {e}")
            return False, None
        
        if checked == 0:
            # No metadata found for this minute - don't skip (might be legitimate audio)
            return False, None
        
        # Decision logic:
        # - If ALL checked frames have incidents or no audio → skip
        # - If MAJORITY (>80%) have issues → skip
        # - Otherwise → process
        
        incident_ratio = (has_incidents + has_no_audio) / checked if checked > 0 else 0
        
        if incident_ratio >= 0.8:
            # Skip this minute
            if has_no_audio >= checked * 0.8:
                return True, "no_audio"
            elif has_incidents >= checked * 0.8:
                return True, "incidents"
            else:
                return True, "mixed_issues"
        
        return False, None
        
    except Exception as e:
        logger.warning(f"[{capture_folder}] Error checking metadata: {e}")
        return False, None


def check_minute_already_processed(capture_folder: str, hour: int, chunk_index: int, minute_offset: int) -> bool:
    """Check if minute was already processed today"""
    try:
        transcript_base = get_transcript_path(capture_folder)
        chunk_path = os.path.join(transcript_base, str(hour), f'chunk_10min_{chunk_index}.json')
        
        if not os.path.exists(chunk_path):
            return False
        
        with open(chunk_path, 'r') as f:
            chunk_data = json.load(f)
        
        minute_statuses = chunk_data.get('minute_statuses', {})
        minute_status = minute_statuses.get(str(minute_offset))
        
        if not minute_status:
            return False
        
        processed_day = minute_status.get('processed_day')
        today = datetime.now().strftime('%Y-%m-%d')
        
        return processed_day == today
        
    except Exception as e:
        return False

class TranscriptMonitor:
    """Simple MP3 transcription monitor
    
    Cross-platform: Uses inotify on Linux, watchdog on macOS
    """
    
    def __init__(
        self,
        monitored_devices,
        enable_transcription=False,
        transcription_workers=1,
        max_inflight_per_device=1
    ):
        self.monitored_devices = monitored_devices
        self.enable_transcription = enable_transcription
        self.transcription_workers = max(1, int(transcription_workers))
        self.max_inflight_per_device = max(1, int(max_inflight_per_device))
        
        # Platform-specific file watcher initialization
        if IS_LINUX:
            self.inotify = inotify.adapters.Inotify()
            self._watcher_type = 'inotify'
        else:
            # macOS: use watchdog
            self.observer = Observer()
            self._watcher_type = 'watchdog'
        
        self.audio_path_to_device = {}
        # Two separate queues: file events (real-time) and scan (backlog)
        self.file_event_queue = LifoQueue(maxsize=500)  # Real-time events (priority)
        self.scan_queue = queue.Queue(maxsize=10)    # Backlog/history (max 10)
        self.audio_workers = {}
        self.transcription_workers_threads = []
        self.incident_manager = None
        self.device_inflight = defaultdict(int)
        self.device_inflight_lock = threading.Lock()
        self.pending_item_keys = set()
        self.pending_item_keys_lock = threading.Lock()
        self.latest_segment_cache = {}
        self.latest_segment_cache_time = {}
        self.last_audio_probe_segment = {}
        self.last_audio_status_write = {}
        self.last_capture_json_write = {}
        self.latest_capture_json_cache = {}
        self.latest_capture_json_cache_time = {}
        
        # Audio detection ALWAYS runs (critical for incident system)
        self._start_audio_workers()
        
        # Transcription components - ONLY if enabled
        if self.enable_transcription:
            logger.info("=" * 80)
            logger.info("🎤 TRANSCRIPTION ENABLED - Starting Whisper components")
            logger.info(
                f"⚙️ Transcription workers={self.transcription_workers}, "
                f"max_inflight_per_device={self.max_inflight_per_device}"
            )
            logger.info("=" * 80)
            self._setup_watches()
            self._scan_existing_mp3s()
            self._start_transcription_workers()
        else:
            logger.info("=" * 80)
            logger.info("🔇 TRANSCRIPTION DISABLED - Audio detection only (lightweight mode)")
            logger.info("=" * 80)
    
    def _setup_watches(self):
        """Setup file watches for 1min MP3 files in temp/"""
        logger.info(f"Setting up 1min MP3 {self._watcher_type} watches...")
        
        for device_info in self.monitored_devices:
            device_folder = device_info['device_folder']
            
            # Watch COLD temp directory for 1min MP3 files (same location as segments/temp)
            from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
            audio_cold = get_cold_storage_path(device_folder, 'audio')
            audio_temp_dir = os.path.join(audio_cold, 'temp')
            os.makedirs(audio_temp_dir, exist_ok=True)
            
            if IS_LINUX:
                self.inotify.add_watch(audio_temp_dir)
            # macOS watchdog scheduling happens in run() after all dirs are registered
            
            self.audio_path_to_device[audio_temp_dir] = device_folder
            
            logger.info(f"[{device_folder}] ✓ Watching {audio_temp_dir}")
        
        logger.info(f"Total: {len(self.audio_path_to_device)} temp dir watches")
        
        # Validate file watcher is working
        self._validate_watcher_setup()
    
    def _validate_watcher_setup(self):
        """Test that file watches are working correctly"""
        logger.info(f"Validating {self._watcher_type} setup...")
        
        test_results = []
        for device_info in self.monitored_devices:
            device_folder = device_info['device_folder']
            
            # Use COLD temp directory (same as setup)
            from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
            audio_cold = get_cold_storage_path(device_folder, 'audio')
            audio_temp_dir = os.path.join(audio_cold, 'temp')
            
            # Create test file to verify inotify
            test_file = os.path.join(audio_temp_dir, '_inotify_test.mp3')
            try:
                # Write test file with atomic rename (same as production)
                logger.info(f"[{device_folder}] Testing inotify on: {audio_temp_dir}")
                with open(test_file + '.tmp', 'w') as f:
                    f.write('test')
                # Windows-safe atomic overwrite (os.rename fails if destination exists)
                os.replace(test_file + '.tmp', test_file)
                
                # Clean up
                time.sleep(0.1)
                if os.path.exists(test_file):
                    os.remove(test_file)
                
                test_results.append(f"✓ {device_folder}")
                logger.info(f"[{device_folder}] ✓ inotify watch validated: {audio_temp_dir}")
            except Exception as e:
                test_results.append(f"✗ {device_folder}: {e}")
                logger.error(f"[{device_folder}] ✗ inotify validation failed on {audio_temp_dir}: {e}")
        
        logger.info(f"inotify validation: {', '.join(test_results)}")
    
    def _scan_existing_mp3s(self):
        """Scan existing MP3s and queue missing transcripts (max 10 total)"""
        CYAN = '\033[96m'
        RESET = '\033[0m'
        
        logger.info(f"{CYAN}{'=' * 80}{RESET}")
        logger.info(f"{CYAN}[SCAN] 📋 Scanning for backlog MP3s (history files)...{RESET}")
        logger.info(f"{CYAN}{'=' * 80}{RESET}")
        
        all_pending = []  # Collect all pending items across devices
        
        for device_info in self.monitored_devices:
            device_folder = device_info['device_folder']
            
            from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, calculate_chunk_location
            audio_cold = get_cold_storage_path(device_folder, 'audio')
            transcript_base = get_transcript_path(device_folder)
            
            device_1min_count = 0
            device_10min_count = 0
            device_pending = []
            
            # Scan 1min MP3s in temp/
            # NOTE: 1min MP3s now use rotating slots (1min_0.mp3 - 1min_9.mp3) without timestamps
            # Skip scanning 1min files - they're ephemeral and handled via inotify in real-time
            # Backlog recovery uses 10min chunks instead
            
            # Scan 10min MP3s in hour folders
            for hour in range(24):
                audio_dir = os.path.join(audio_cold, str(hour))
                if not os.path.exists(audio_dir):
                    continue
                
                for mp3_file in os.listdir(audio_dir):
                    if mp3_file.startswith('chunk_10min_') and mp3_file.endswith('.mp3'):
                        # Skip language-specific dubbed audio files (chunk_10min_0_fr.mp3, etc.)
                        # Only process base audio files (chunk_10min_0.mp3)
                        stem = mp3_file.replace('chunk_10min_', '').replace('.mp3', '')
                        if '_' in stem:
                            # This is a dubbed audio file (e.g., "3_en"), skip it
                            continue
                        
                        chunk_index = int(stem)
                        transcript_path = os.path.join(transcript_base, str(hour), f'chunk_10min_{chunk_index}.json')
                        
                        if not os.path.exists(transcript_path):
                            mp3_path = os.path.join(audio_dir, mp3_file)
                            mtime = os.path.getmtime(mp3_path)
                            device_pending.append((mtime, '10min', device_folder, mp3_path, hour, chunk_index, mp3_file))
                            device_10min_count += 1
            
            # Log scan results per device
            if device_pending:
                logger.info(f"{CYAN}[SCAN] 📁 [{device_folder}] Found {device_1min_count} x 1min + {device_10min_count} x 10min = {len(device_pending)} backlog items{RESET}")
            else:
                logger.info(f"{CYAN}[SCAN] ✓ [{device_folder}] No backlog - all transcripts up to date{RESET}")
            
            all_pending.extend(device_pending)
        
        # Sort by modification time (oldest first) and limit to 10
        all_pending.sort(key=lambda x: x[0])
        limited_pending = all_pending[:10]
        
        if limited_pending:
            logger.info(f"{CYAN}[SCAN] {'─' * 80}{RESET}")
            logger.info(f"{CYAN}[SCAN] 📦 Total {len(all_pending)} backlog items found, queuing oldest 10:{RESET}")
            for idx, (mtime, type_label, device_folder, mp3_path, hour, chunk_index, mp3_file) in enumerate(limited_pending, 1):
                age_minutes = int((time.time() - mtime) / 60)
                logger.info(f"{CYAN}[SCAN]   {idx:2d}. [{device_folder}] {type_label:5s} {mp3_file} (age: {age_minutes}min){RESET}")
                
                # Add to scan queue
                if type_label == '1min':
                    self._queue_item(self.scan_queue, (device_folder, mp3_path, hour, chunk_index))
                else:  # 10min
                    self._queue_item(self.scan_queue, (device_folder, hour, chunk_index))
            
            logger.info(f"{CYAN}[SCAN] ✓ Queued {len(limited_pending)} items to scan_queue (FIFO order){RESET}")
        else:
            logger.info(f"{CYAN}[SCAN] ✓ No backlog across all devices - system fully up to date{RESET}")
        
        logger.info(f"{CYAN}{'=' * 80}{RESET}")
    
    def _start_transcription_workers(self):
        """Start transcription worker pool"""
        for worker_index in range(self.transcription_workers):
            worker = threading.Thread(
                target=self._transcription_worker,
                daemon=True,
                name=f"transcription-worker-{worker_index + 1}"
            )
            worker.start()
            self.transcription_workers_threads.append(worker)
        logger.info(f"Transcription worker pool started ({len(self.transcription_workers_threads)} workers)")

    def _extract_device_from_item(self, item):
        if len(item) in (3, 4):
            return item[0]
        return None

    def _item_key(self, item):
        if len(item) == 3:
            device_folder, hour, chunk_index = item
            return ('10min', device_folder, int(hour), int(chunk_index))
        if len(item) == 4:
            device_folder, mp3_path, hour, chunk_index = item
            slot = Path(mp3_path).stem
            return ('1min', device_folder, int(hour), int(chunk_index), slot)
        return ('unknown', str(item))

    def _queue_item(self, target_queue, item):
        """Queue item with dedupe key guard."""
        key = self._item_key(item)
        with self.pending_item_keys_lock:
            if key in self.pending_item_keys:
                return False
            self.pending_item_keys.add(key)
        try:
            target_queue.put(item)
            return True
        except Exception:
            with self.pending_item_keys_lock:
                self.pending_item_keys.discard(key)
            raise

    def _release_item_key(self, item):
        key = self._item_key(item)
        with self.pending_item_keys_lock:
            self.pending_item_keys.discard(key)

    def _try_acquire_device_slot(self, device_folder):
        with self.device_inflight_lock:
            current = self.device_inflight[device_folder]
            if current >= self.max_inflight_per_device:
                return False
            self.device_inflight[device_folder] = current + 1
            return True

    def _release_device_slot(self, device_folder):
        with self.device_inflight_lock:
            current = self.device_inflight.get(device_folder, 0)
            if current <= 1:
                self.device_inflight[device_folder] = 0
            else:
                self.device_inflight[device_folder] = current - 1
    
    def _transcription_worker(self):
        """Process MP3 transcription with dual-queue priority (inotify > scan)"""
        last_heartbeat = time.time()
        heartbeat_interval = 60
        
        while True:
            item = None
            source_queue = None
            device_folder = None
            try:
                # Priority 1: Check inotify queue (real-time events)
                try:
                    item = self.file_event_queue.get_nowait()
                    source_queue = 'inotify'
                except queue.Empty:
                    # Priority 2: If inotify empty, check scan queue (backlog)
                    try:
                        item = self.scan_queue.get(timeout=5)
                        source_queue = 'scan'
                    except queue.Empty:
                        # Both queues empty - heartbeat check
                        if time.time() - last_heartbeat > heartbeat_interval:
                            inotify_size = self.file_event_queue.qsize()
                            scan_size = self.scan_queue.qsize()
                            with self.device_inflight_lock:
                                active_devices = [k for k, v in self.device_inflight.items() if v > 0]
                                inflight_total = sum(self.device_inflight.values())
                            logger.info(
                                f"[TRANSCRIPTION] ❤️  Heartbeat: "
                                f"queues[inotify={inotify_size}, scan={scan_size}], "
                                f"inflight={inflight_total} on {len(active_devices)} device(s) - Idle, waiting for MP3s..."
                            )
                            last_heartbeat = time.time()
                        continue
                
                if item is None:
                    continue
                
                last_heartbeat = time.time()
                
                # Get current queue sizes for logging
                inotify_size = self.file_event_queue.qsize()
                scan_size = self.scan_queue.qsize()
                queue_status = f"queues[inotify={inotify_size}, scan={scan_size}]"
                
                # Debug: log what item we picked up
                logger.debug(f"[TRANSCRIPTION] Picked up item (len={len(item)}) from {source_queue}: {item}")

                device_folder = self._extract_device_from_item(item)
                if device_folder and not self._try_acquire_device_slot(device_folder):
                    # Device already has an in-flight task; re-queue and let another worker progress.
                    if source_queue == 'inotify':
                        self.file_event_queue.put(item)
                        self.file_event_queue.task_done()
                    elif source_queue == 'scan':
                        self.scan_queue.put(item)
                        self.scan_queue.task_done()
                    time.sleep(0.05)
                    continue
                
                if len(item) == 3:
                    # 10min MP3 chunk
                    device_folder, hour, chunk_index = item
                    
                    from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
                    audio_cold = get_cold_storage_path(device_folder, 'audio')
                    mp3_path = os.path.join(audio_cold, str(hour), f'chunk_10min_{chunk_index}.mp3')
                    
                    if os.path.exists(mp3_path):
                        # Process 10min chunk (includes silence check before Whisper to avoid wasting CPU)
                        logger.info(f"[{device_folder}] 🎵 Processing 10min: {hour}h/chunk_{chunk_index} (source={source_queue}, {queue_status})")
                        minute_results = transcribe_mp3_chunk_progressive(mp3_path, device_folder, hour, chunk_index)
                        # CRITICAL: Process ALL minute_data (including silent) to trigger rolling 24h cleanup
                        # Without this, old transcripts persist indefinitely during silent periods
                        for minute_data in minute_results:
                            merge_minute_to_chunk(device_folder, hour, chunk_index, minute_data, has_mp3=True)
                    else:
                        logger.warning(f"[{device_folder}] ⚠️  10min MP3 not found: {mp3_path}")
                
                elif len(item) == 4:
                    # 1min MP3 segment (only created when audio detected, so no silence check needed)
                    device_folder, mp3_path, hour, chunk_index = item
                    
                    logger.info(f"[{device_folder}] 📋 Processing 1min MP3: {mp3_path}")
                    
                    if os.path.exists(mp3_path):
                        # Extract slot number from filename (1min_0.mp3 → slot 0)
                        slot = int(Path(mp3_path).stem.replace('1min_', ''))
                        minute_offset = slot  # Slot number IS the minute offset within the 10min chunk
                        logger.info(f"[{device_folder}] 🎵 Transcribing 1min: {hour}h/chunk_{chunk_index}/minute_{minute_offset} (source={source_queue}, {queue_status})")
                        
                        result = transcribe_audio(mp3_path, model_name='tiny', skip_silence_check=True, device_id=device_folder)
                        segments = result.get('segments', [])
                        
                        if segments:
                            transcript = ' '.join([s.get('text', '').strip() for s in segments])
                            transcript = clean_transcript_text(transcript)
                            if ENABLE_SPELLCHECK:
                                transcript = correct_spelling(transcript, result.get('language_code'))
                            
                            minute_data = {
                                'minute_offset': minute_offset,
                                'language': result.get('language', 'unknown'),
                                'transcript': transcript,
                                'segments': segments
                            }
                            merge_minute_to_chunk(device_folder, hour, chunk_index, minute_data, has_mp3=False)
                            
                            # NOTE: AI translation now on-demand via /host/transcript/translate-chunk endpoint
                            # No automatic 1-minute translation to reduce CPU load
                            # if len(transcript) > 20:
                            #     enhance_and_dub_1min(device_folder, hour, chunk_index, slot, transcript, result.get('language', 'unknown'))
                        else:
                            logger.info(f"[{device_folder}] ⏭️  1min MP3 returned no segments (Whisper detected silence)")
                    else:
                        logger.warning(f"[{device_folder}] ⚠️  1min MP3 not found (may have been archived): {mp3_path}")
                
                # Mark task done on appropriate queue
                if source_queue == 'inotify':
                    self.file_event_queue.task_done()
                elif source_queue == 'scan':
                    self.scan_queue.task_done()
                
                if item is not None:
                    self._release_item_key(item)
                if device_folder:
                    self._release_device_slot(device_folder)
                
            except Exception as e:
                import traceback
                logger.error(f"Transcription error: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                if source_queue == 'inotify':
                    self.file_event_queue.task_done()
                elif source_queue == 'scan':
                    self.scan_queue.task_done()
                if item is not None:
                    self._release_item_key(item)
                if device_folder:
                    self._release_device_slot(device_folder)
    
    
    
    def _start_audio_workers(self):
        """Start audio detection workers (5s interval per device)"""
        logger.info("Starting audio detection workers...")
        
        try:
            from backend_host.scripts.incident_manager import IncidentManager
            # Don't resolve stale incidents - that's capture_monitor's job
            # We only report audio detection results, not manage incident lifecycle
            self.incident_manager = IncidentManager(skip_startup_cleanup=True)
            logger.info("✓ IncidentManager initialized (audio reporting only)")
        except Exception as e:
            logger.warning(f"⚠️  Failed to initialize IncidentManager: {e} (audio detection will continue without incident tracking)")
            self.incident_manager = None
        
        for device_info in self.monitored_devices:
            device_folder = device_info['device_folder']
            
            try:
                audio_worker = threading.Thread(
                    target=self._audio_detection_worker,
                    args=(device_folder,),
                    daemon=True,
                    name=f"audio-{device_folder}"
                )
                audio_worker.start()
                self.audio_workers[device_folder] = audio_worker
                logger.info(f"✓ [{device_folder}] Started adaptive audio detection worker (5-10s intervals based on load)")
            except Exception as e:
                logger.error(f"✗ [{device_folder}] Failed to start audio detection worker: {e}")

    def _scan_latest_segment(self, segments_dir):
        latest_segment = None
        latest_mtime = 0
        with os.scandir(segments_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.startswith('segment_') and (entry.name.endswith('.ts') or entry.name.endswith('.mp4')):
                    mtime = entry.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_segment = entry.path
                        latest_mtime = mtime
        return latest_segment, latest_mtime

    def _get_latest_segment_cached(self, device_folder, segments_dir, now_ts, force_refresh=False):
        cache_ttl = 2.0
        last_scan = self.latest_segment_cache_time.get(device_folder, 0.0)
        cached_path = self.latest_segment_cache.get(device_folder)
        cached_mtime = 0.0

        if cached_path and os.path.exists(cached_path):
            try:
                cached_mtime = os.path.getmtime(cached_path)
            except Exception:
                cached_mtime = 0.0

        should_scan = (
            force_refresh
            or not cached_path
            or not os.path.exists(cached_path)
            or (now_ts - last_scan) > cache_ttl
        )

        if should_scan:
            try:
                latest_segment, latest_mtime = self._scan_latest_segment(segments_dir)
                self.latest_segment_cache[device_folder] = latest_segment
                self.latest_segment_cache_time[device_folder] = now_ts
                return latest_segment, latest_mtime
            except Exception:
                pass

        return cached_path, cached_mtime

    def _get_latest_capture_json_cached(self, device_folder, metadata_path, now_ts):
        cache_ttl = 1.0
        current_path = self.latest_capture_json_cache.get(device_folder)
        current_scan_ts = self.latest_capture_json_cache_time.get(device_folder, 0.0)

        if current_path and os.path.exists(current_path):
            if now_ts - current_scan_ts <= cache_ttl:
                return current_path

        latest_json = None
        latest_mtime = 0.0
        try:
            with os.scandir(metadata_path) as it:
                for entry in it:
                    if entry.is_file() and entry.name.startswith('capture_') and entry.name.endswith('.json'):
                        mtime = entry.stat().st_mtime
                        if mtime > latest_mtime:
                            latest_json = entry.path
                            latest_mtime = mtime
        except Exception:
            latest_json = None

        self.latest_capture_json_cache[device_folder] = latest_json
        self.latest_capture_json_cache_time[device_folder] = now_ts
        return latest_json

    def _update_audio_loss_frame_state(self, device_folder: str, latest_json_filename: str, has_audio: bool):
        """
        Persist audio_loss start/end frame references in device_state so IncidentManager
        can upload start/closure captures using the same lifecycle as visual incidents.
        """
        if not self.incident_manager or not latest_json_filename:
            return

        from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, copy_to_cold_storage

        thumbnail_filename = latest_json_filename.replace('.jpg', '_thumbnail.jpg')
        thumbnail_path = os.path.join(get_thumbnails_path(device_folder), thumbnail_filename)
        if not os.path.exists(thumbnail_path):
            logger.warning(f"[AUDIO:{device_folder}] Thumbnail not found for audio_loss: {thumbnail_path}")
            return

        device_state = self.incident_manager.get_device_state(device_folder)
        active_incidents = device_state.get('active_incidents', {})
        pending_incidents = device_state.get('pending_incidents', {})
        has_audio_loss_context = (
            'audio_loss' in active_incidents
            or 'audio_loss' in pending_incidents
            or bool(device_state.get('audio_loss_start_thumbnail_cold'))
        )

        if not has_audio:
            # Store the first frame once per audio-loss window.
            if not device_state.get('audio_loss_start_thumbnail_cold'):
                start_thumbnail_cold = copy_to_cold_storage(thumbnail_path)
                if start_thumbnail_cold:
                    device_state['audio_loss_start_thumbnail_cold'] = start_thumbnail_cold
                    device_state['audio_loss_start_filename'] = latest_json_filename
                    logger.info(f"[AUDIO:{device_folder}] Stored audio_loss START thumbnail: {start_thumbnail_cold}")
        else:
            # When audio returns, prepare closure frame for IncidentManager resolve flow.
            if has_audio_loss_context:
                closure_thumbnail_cold = copy_to_cold_storage(thumbnail_path)
                if closure_thumbnail_cold:
                    device_state['audio_loss_closure_frame'] = closure_thumbnail_cold
                    device_state['audio_loss_closure_filename'] = latest_json_filename
                    logger.info(f"[AUDIO:{device_folder}] Stored audio_loss END thumbnail: {closure_thumbnail_cold}")
    
    def _audio_detection_worker(self, device_folder):
        """Worker thread: Check audio every 5s by scanning segments directory with dynamic load adjustment"""
        BLUE = '\033[94m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RESET = '\033[0m'
        
        logger.info(f"{BLUE}[AUDIO:{device_folder}] Worker thread started - adaptive 5-10s intervals based on load{RESET}")
        
        # Resolve segments path once (hot/cold aware)
        segments_dir = get_segments_path(device_folder)
        logger.info(f"{BLUE}[AUDIO:{device_folder}] 📂 Watching: {segments_dir}{RESET}")
        
        # Dynamic interval management
        base_interval = 5.0          # Start with 5s
        current_interval = base_interval
        max_interval = 10.0          # Max 10s under load
        processing_times = []        # Track recent processing times
        consecutive_timeouts = 0     # Track timeout streak
        consecutive_successes = 0    # Track success streak
        
        check_count = 0
        while True:
            check_count += 1
            cycle_start_time = time.time()
            
            try:
                # Resolve latest segment with short-lived cache (avoid full directory scan every cycle).
                if not os.path.exists(segments_dir):
                    if check_count % 12 == 0:
                        logger.info(f"{BLUE}[AUDIO:{device_folder}] ⏸️  Segments directory not found (check #{check_count}): {segments_dir}{RESET}")
                    time.sleep(current_interval)
                    continue
                
                latest_segment, latest_mtime = self._get_latest_segment_cached(
                    device_folder=device_folder,
                    segments_dir=segments_dir,
                    now_ts=time.time(),
                    force_refresh=(check_count % 12 == 0)
                )
                
                if not latest_segment:
                    if check_count % 12 == 0:
                        logger.info(f"{BLUE}[AUDIO:{device_folder}] ⏸️  No segments found in {segments_dir} (check #{check_count}){RESET}")
                    time.sleep(current_interval)
                    continue
                
                # Check if segment is recent (within last 5 minutes)
                age_seconds = time.time() - latest_mtime
                segment_filename = os.path.basename(latest_segment)
                
                # Only log segment found occasionally (every 60 checks = 5 minutes)
                if check_count % 60 == 0:
                    logger.info(f"{BLUE}[AUDIO:{device_folder}] 📁 Found segment: {segment_filename} (age: {age_seconds:.1f}s){RESET}")
                
                if age_seconds > 300:
                    if check_count % 60 == 0:
                        logger.warning(f"{BLUE}[AUDIO:{device_folder}] ⏸️  Segment too old (check #{check_count}): {age_seconds:.0f}s{RESET}")
                    time.sleep(current_interval)
                    continue
                
                segment_path = latest_segment
                
                # Measure audio detection performance with adaptive timeout
                processing_start = time.time()
                
                # Adaptive timeout: increase under load
                adaptive_timeout = 2.0 if current_interval <= 5.0 else 4.0

                # Skip expensive probe if we already measured this exact segment version.
                last_probe = self.last_audio_probe_segment.get(device_folder)
                if last_probe and last_probe[0] == segment_path and abs(last_probe[1] - latest_mtime) < 0.0001:
                    has_audio = last_probe[2]
                    mean_volume = last_probe[3]
                    processing_time = 0.01
                else:
                    # Use faster audio detection with timeout handling
                    try:
                        cmd = [
                            'ionice', '-c3',
                            'nice', '-n', '19',
                            'ffmpeg',
                            '-hide_banner',
                            '-loglevel', 'info',  # Need 'info' level for volumedetect output (NOT 'error'!)
                            '-i', segment_path,
                            '-t', '0.5',
                            '-vn',  # Skip video decode — only need audio for volumedetect
                            '-af', 'volumedetect',
                            '-f', 'null',
                            '-'
                        ]

                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=adaptive_timeout)
                        
                        mean_volume = None
                        for line in result.stderr.split('\n'):
                            if 'mean_volume:' in line:
                                try:
                                    mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                                    break
                                except Exception as e:
                                    logger.error(f"{BLUE}[AUDIO:{device_folder}] Failed to parse volume: {line} (error: {e}){RESET}")

                        if mean_volume is None:
                            # volumedetect produced no reading: the segment has no audio
                            # stream at all (e.g. VNC/host video-only capture). This device
                            # does not capture audio, so report N/A (None) instead of a bogus
                            # audio-loss (False) — the UI shows "N/A", not red "No".
                            has_audio = None
                        else:
                            has_audio = mean_volume > -50.0
                        processing_time = time.time() - processing_start
                        self.last_audio_probe_segment[device_folder] = (segment_path, latest_mtime, has_audio, mean_volume)
                        
                        # Record successful processing
                        processing_times.append(processing_time)
                        if len(processing_times) > 10:  # Keep last 10 measurements
                            processing_times.pop(0)
                        
                        consecutive_timeouts = 0
                        consecutive_successes += 1
                        
                    except subprocess.TimeoutExpired:
                        # Handle timeout - system is overloaded
                        processing_time = adaptive_timeout
                        has_audio = False
                        mean_volume = -100.0
                        
                        consecutive_timeouts += 1
                        consecutive_successes = 0
                        
                        logger.warning(f"{YELLOW}[AUDIO:{device_folder}] ⏰ ffmpeg timeout ({adaptive_timeout}s) on {segment_filename} - system overloaded{RESET}")
                        
                    except Exception as e:
                        # Handle other ffmpeg errors gracefully
                        processing_time = 1.0  # Assume moderate processing time on errors
                        has_audio = False
                        mean_volume = -100.0
                        
                        logger.warning(f"{BLUE}[AUDIO:{device_folder}] ⚠️  ffmpeg error on {segment_filename}: {e} (assuming silent){RESET}")
                
                # Dynamic interval adjustment based on performance
                old_interval = current_interval
                
                # Calculate average processing time
                avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0.5
                
                # Decide on interval adjustment
                should_increase = (
                    consecutive_timeouts >= 2 or  # 2+ consecutive timeouts
                    avg_processing_time > 1.5 or  # Average processing > 1.5s
                    (processing_times and max(processing_times) > 2.0)  # Any recent processing > 2s
                )
                
                should_decrease = (
                    consecutive_successes >= 5 and  # 5+ consecutive successes
                    avg_processing_time < 0.8 and   # Average processing < 0.8s
                    consecutive_timeouts == 0        # No recent timeouts
                )
                
                if should_increase and current_interval < max_interval:
                    current_interval = max_interval  # Jump to 10s under load
                elif should_decrease and current_interval > base_interval:
                    current_interval = base_interval  # Back to 5s when stable
                
                # Log interval changes
                if old_interval != current_interval:
                    reason = "overload detected" if should_increase else "load reduced"
                    logger.info(f"{YELLOW}[AUDIO:{device_folder}] 🔄 Interval adjusted: {old_interval:.1f}s → {current_interval:.1f}s ({reason}){RESET}")
                    logger.info(f"{YELLOW}[AUDIO:{device_folder}] 📊 Stats: avg_proc={avg_processing_time:.2f}s, timeouts={consecutive_timeouts}, successes={consecutive_successes}{RESET}")
                # has_audio is one of: True (audio present), False (audio lost),
                # None (no audio stream — device does not capture audio).
                status_icon = '➖' if has_audio is None else ('🔊' if has_audio else '🔇')
                mean_volume_str = 'N/A' if mean_volume is None else f"{mean_volume:.1f}dB"

                # Only log audio status occasionally or when audio is detected
                if has_audio or check_count % 60 == 0:
                    logger.info(f"{BLUE}[AUDIO:{device_folder}] {status_icon} {mean_volume_str} from {segment_filename} (check #{check_count}){RESET}")
                
                detection_result = {
                    'audio': has_audio,
                    'mean_volume_db': mean_volume,
                    'segment_path': segment_path,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Write to shared audio_status.json (capture_monitor reads this directly)
                # This ensures audio status is always current (max 5-10s lag)
                latest_json_filename = None
                try:
                    metadata_path = get_metadata_path(device_folder)
                    os.makedirs(metadata_path, mode=0o777, exist_ok=True)
                    now_ts = time.time()
                    
                    # Write shared audio status file (single source of truth)
                    audio_status_path = os.path.join(metadata_path, 'audio_status.json')
                    mean_volume_sig = None if mean_volume is None else round(mean_volume, 1)
                    audio_sig = (has_audio, mean_volume_sig, segment_filename)
                    prev_audio_state = self.last_audio_status_write.get(device_folder)
                    should_write_audio_status = (
                        prev_audio_state is None
                        or prev_audio_state[0] != audio_sig
                        or (now_ts - prev_audio_state[1]) > 30.0
                    )
                    if should_write_audio_status:
                        audio_status_data = {
                            'audio': has_audio,
                            'mean_volume_db': mean_volume,
                            'timestamp': detection_result['timestamp'],
                            'segment_file': segment_filename
                        }
                        with open(audio_status_path + '.tmp', 'w') as f:
                            json.dump(audio_status_data, f, separators=(',', ':'))
                        # Windows-safe atomic overwrite (os.rename fails if destination exists)
                        os.replace(audio_status_path + '.tmp', audio_status_path)
                        self.last_audio_status_write[device_folder] = (audio_sig, now_ts)
                    
                    # Find most recent capture JSON
                    from shared.src.lib.utils.file_lock_utils import lock_file, unlock_file
                    latest_json = self._get_latest_capture_json_cached(device_folder, metadata_path, now_ts)
                    
                    if latest_json and os.path.exists(latest_json):
                        latest_json_filename = os.path.basename(latest_json).replace('.json', '.jpg')
                        
                        # Update ONE JSON with audio data (capture_monitor will propagate via cache)
                        with open(latest_json, 'r') as f:
                            existing_data = json.load(f)
                        
                        existing_data['audio'] = has_audio
                        existing_data['mean_volume_db'] = mean_volume
                        existing_data['audio_check_timestamp'] = detection_result['timestamp']
                        existing_data['audio_segment_file'] = segment_filename
                        capture_sig = (has_audio, mean_volume_sig, segment_filename, os.path.basename(latest_json))
                        prev_capture_state = self.last_capture_json_write.get(device_folder)
                        should_write_capture_json = (
                            prev_capture_state is None
                            or prev_capture_state[0] != capture_sig
                            or (now_ts - prev_capture_state[1]) > 30.0
                        )

                        if should_write_capture_json:
                            # Write atomically
                            lock_path = latest_json + '.lock'
                            with open(lock_path, 'w') as lock_fh:
                                lock_file(lock_fh, exclusive=True)
                                try:
                                    with open(latest_json + '.tmp', 'w') as f:
                                        json.dump(existing_data, f, separators=(',', ':'))
                                    # Windows-safe atomic overwrite (os.rename fails if destination exists)
                                    os.replace(latest_json + '.tmp', latest_json)
                                    
                                    # Log audio write
                                    audio_status = "➖ N/A" if has_audio is None else ("✅ YES" if has_audio else "❌ NO")
                                    logger.info(f"{BLUE}[AUDIO:{device_folder}] 💾 WROTE → {os.path.basename(latest_json)}: audio={audio_status}, volume={mean_volume_str} (will propagate via cache){RESET}")
                                    self.last_capture_json_write[device_folder] = (capture_sig, now_ts)
                                finally:
                                    unlock_file(lock_fh)
                            
                            try:
                                os.remove(lock_path)
                            except:
                                pass
                        
                except Exception as e:
                    logger.warning(f"{BLUE}[AUDIO:{device_folder}] Failed to write audio to JSON: {e}{RESET}")
                
                # Add frame filename to detection_result (for unified image handling in capture_monitor)
                if latest_json_filename:
                    detection_result['filename'] = latest_json_filename

                # Audio-loss incidents only apply to devices that actually capture audio.
                # When has_audio is None (no audio stream), skip incident tracking entirely
                # so a video-only capture never raises a bogus audio_loss.
                if has_audio is not None:
                    # Track start/end audio_loss frame references for IncidentManager uploads.
                    self._update_audio_loss_frame_state(device_folder, latest_json_filename, has_audio)

                    # Report to incident manager for tracking only (no lifecycle management)
                    if self.incident_manager:
                        host_name = os.getenv('HOST_NAME', 'unknown')
                        self.incident_manager.process_detection(device_folder, detection_result, host_name)
                
            except Exception as e:
                import traceback
                logger.error(f"{BLUE}[AUDIO:{device_folder}] Error: {e}{RESET}")
                logger.error(f"{BLUE}[AUDIO:{device_folder}] Traceback: {traceback.format_exc()}{RESET}")
            
            # Enhanced logging with performance metrics
            cycle_duration = time.time() - cycle_start_time
            
            # Log performance metrics occasionally
            if check_count % 60 == 0:
                logger.info(f"{GREEN}[AUDIO:{device_folder}] 📈 Performance: interval={current_interval:.1f}s, cycle={cycle_duration:.2f}s, avg_proc={avg_processing_time:.2f}s{RESET}")
            
            time.sleep(current_interval)  # Use dynamic interval
    
    def _handle_mp3_event(self, path, filename):
        """Handle MP3 file event from either inotify or watchdog"""
        if filename.endswith('.mp3') and filename.startswith('1min_'):
            device_folder = self.audio_path_to_device.get(path)
            if device_folder:
                mp3_path = os.path.join(path, filename)
                
                # Slot-based naming (1min_0.mp3 through 1min_9.mp3) - use current time for chunk location
                from shared.src.lib.utils.storage_path_utils import calculate_chunk_location
                now = datetime.now()
                hour, chunk_index = calculate_chunk_location(now)
                
                queued = self._queue_item(self.file_event_queue, (device_folder, mp3_path, hour, chunk_index))
                if queued:
                    queue_size = self.file_event_queue.qsize()
                    scan_size = self.scan_queue.qsize()
                    logger.info(f"[{self._watcher_type.upper()}] 🆕 1min MP3 detected: {device_folder}/{filename} → queues[events={queue_size}, scan={scan_size}]")
                return True
        return False
    
    def run(self):
        """Main event loop - watch for 1min MP3 files in temp/ (only if transcription enabled)"""
        if not self.enable_transcription:
            logger.info("=" * 80)
            logger.info(f"🔇 Transcription disabled - {self._watcher_type} loop skipped")
            logger.info("✅ Audio detection workers running in background")
            logger.info("=" * 80)
            
            # Keep main thread alive while audio workers run
            try:
                while True:
                    time.sleep(60)
                    logger.info("[AUDIO-ONLY] ❤️  Heartbeat: Audio detection active, transcription disabled")
            except KeyboardInterrupt:
                logger.info("Shutting down...")
            return
        
        logger.info("=" * 80)
        logger.info(f"Starting 1min MP3 {self._watcher_type} event loop...")
        logger.info(f"Watching {len(self.audio_path_to_device)} directories for file events")
        logger.info("Ready to process 1min MP3 files (real-time priority)")
        logger.info("=" * 80)
        
        if IS_LINUX:
            self._run_inotify()
        else:
            self._run_watchdog()
    
    def _run_inotify(self):
        """Linux inotify event loop"""
        event_count = 0
        mp3_count = 0
        last_heartbeat = time.time()
        heartbeat_interval = 60
        
        try:
            for event in self.inotify.event_gen(yield_nones=True):
                if time.time() - last_heartbeat > heartbeat_interval:
                    queue_size = self.file_event_queue.qsize()
                    scan_size = self.scan_queue.qsize()
                    logger.info(f"[INOTIFY] ❤️  Heartbeat: events={event_count}, MP3s={mp3_count}, queues[events={queue_size}, scan={scan_size}]")
                    last_heartbeat = time.time()
                
                if event is None:
                    continue
                
                event_count += 1
                (_, type_names, path, filename) = event
                
                if 'IN_MOVED_TO' in type_names:
                    if self._handle_mp3_event(path, filename):
                        mp3_count += 1
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            for path in self.audio_path_to_device.keys():
                try:
                    self.inotify.remove_watch(path)
                except:
                    pass
    
    def _run_watchdog(self):
        """macOS/cross-platform watchdog event loop"""
        monitor = self  # Reference for event handler
        
        class MP3EventHandler(FileSystemEventHandler):
            """Handle MP3 file events"""
            
            def on_moved(self, event):
                """Called when a file is moved/renamed (atomic write)"""
                if event.is_directory:
                    return
                
                dest_path = event.dest_path
                path = os.path.dirname(dest_path)
                filename = os.path.basename(dest_path)
                
                monitor._handle_mp3_event(path, filename)
            
            def on_created(self, event):
                """Fallback for non-atomic writes"""
                if event.is_directory:
                    return
                
                path = os.path.dirname(event.src_path)
                filename = os.path.basename(event.src_path)
                
                # Skip temp files
                if not filename.startswith('.'):
                    time.sleep(0.1)  # Brief delay for file completion
                    monitor._handle_mp3_event(path, filename)
        
        event_handler = MP3EventHandler()
        
        # Schedule watches for all audio directories
        for path in self.audio_path_to_device.keys():
            if os.path.exists(path):
                self.observer.schedule(event_handler, path, recursive=False)
                logger.info(f"Watchdog watching: {path}")
        
        try:
            self.observer.start()
            logger.info("Watchdog observer started")
            
            last_heartbeat = time.time()
            heartbeat_interval = 60
            
            while True:
                if time.time() - last_heartbeat > heartbeat_interval:
                    queue_size = self.file_event_queue.qsize()
                    scan_size = self.scan_queue.qsize()
                    logger.info(f"[WATCHDOG] ❤️  Heartbeat: queues[events={queue_size}, scan={scan_size}]")
                    last_heartbeat = time.time()
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.observer.stop()
            self.observer.join()

def main():
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    def _env_bool(name: str, default: bool) -> bool:
        return os.getenv(name, str(default)).strip().lower() in ('true', '1', 'yes')

    env_transcription_workers = _env_int('TRANSCRIPTION_WORKERS', 2)
    env_max_inflight_per_device = _env_int('MAX_INFLIGHT_PER_DEVICE', 1)
    # Transcription is opt-in per host (CPU-intensive Whisper). The service template
    # ships ENABLE_TRANSCRIPTION=false; enable on a specific host with a systemd
    # drop-in rather than flipping ExecStart fleet-wide.
    env_enable_transcription = _env_bool('ENABLE_TRANSCRIPTION', False)

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Transcript Accumulator - Audio Detection & MP3 Transcription Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python transcript_accumulator.py                    # Audio detection only (default)
  python transcript_accumulator.py --transcript false # Audio detection only (explicit)
  python transcript_accumulator.py --transcript true  # Audio detection + transcription (CPU-intensive)
        """
    )
    parser.add_argument(
        '--transcript',
        type=lambda x: x.lower() == 'true',
        default=env_enable_transcription,
        help='Enable MP3 transcription (default: env ENABLE_TRANSCRIPTION or false - audio detection only)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=env_transcription_workers,
        help='Number of transcription workers (default: env TRANSCRIPTION_WORKERS or 2)'
    )
    parser.add_argument(
        '--max-inflight-per-device',
        type=int,
        default=env_max_inflight_per_device,
        help='Max concurrent transcription tasks per device (default: env MAX_INFLIGHT_PER_DEVICE or 1)'
    )
    args = parser.parse_args()
    
    enable_transcription = args.transcript
    transcription_workers = max(1, int(args.workers))
    max_inflight_per_device = max(1, int(args.max_inflight_per_device))
    
    # Clean log file first
    cleanup_logs_on_startup()
    
    # Kill any existing transcript_accumulator instances before starting
    from shared.src.lib.utils.system_utils import kill_existing_script_instances
    import time
    
    killed = kill_existing_script_instances('transcript_accumulator.py')
    if killed:
        print(f"[@transcript_accumulator] Killed existing instances: {killed}")
        time.sleep(1)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler()],
        force=True
    )
    
    # Disable noisy faster-whisper internal logs (they don't show capture folder)
    # Our own logs are more informative and show device context
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)

    # Quiet by default; raise verbosity on demand with
    # `sudo pkill -USR1 -f transcript_accumulator.py` (SIGUSR2 to restore).
    from shared.src.lib.utils.log_control import install_runtime_log_control
    install_runtime_log_control('TRANSCRIPT_LOG_LEVEL')

    logger.info("=" * 80)
    logger.info("Transcript Accumulator - Audio Detection & Transcription Service")
    logger.info("=" * 80)
    logger.info(f"Mode: {'🎤 TRANSCRIPTION ENABLED' if enable_transcription else '🔇 AUDIO DETECTION ONLY (lightweight)'}")
    logger.info(
        f"Worker config: workers={transcription_workers}, "
        f"max_inflight_per_device={max_inflight_per_device}"
    )
    logger.info("=" * 80)
    logger.info("Architecture: inotify event-driven (zero CPU when idle)")
    if enable_transcription:
        logger.info("Watches: 1min MP3 files in COLD /audio/temp/ (instant transcription)")
        logger.info("Scans: 1min /audio/temp/ + 10min /audio/{hour}/ (backfill/recovery)")
        logger.info("Processing: MP3 → JSON transcript (Whisper tiny model)")
    else:
        logger.info("Audio Detection: Checks segments every 5-10s for audio presence")
        logger.info("Transcription: DISABLED (Whisper not loaded, saves CPU)")
    logger.info("=" * 80)
    
    try:
        # Get base directories and resolve paths
        base_dirs = get_capture_base_directories()
        logger.info(f"Found {len(base_dirs)} capture base directories from active_captures.conf")
        
        # Build monitored devices list (all devices now support audio with PulseAudio)
        monitored_devices = []
        
        for base_dir in base_dirs:
            device_folder = os.path.basename(base_dir)
            
            # Map capture folder to device_id via .env
            device_info = get_device_info_from_capture_folder(device_folder)
            device_id = device_info.get('device_id', device_folder)
            
            # All devices now support audio (including host/VNC with PulseAudio)
            logger.info(f"  [{device_folder}] device_id={device_id}")
            
            logger.info(f"  ✓ Monitoring: {device_folder}")
            
            monitored_devices.append({
                'device_folder': device_folder
            })
        
        if not monitored_devices:
            logger.error("No devices to monitor!")
            return
        
        logger.info(f"Monitoring {len(monitored_devices)} devices")
        if enable_transcription:
            logger.info("Whisper model will be loaded on first transcription (global singleton)")
        else:
            logger.info("Whisper model will NOT be loaded (transcription disabled)")
        
        monitor = TranscriptMonitor(
            monitored_devices,
            enable_transcription=enable_transcription,
            transcription_workers=transcription_workers,
            max_inflight_per_device=max_inflight_per_device
        )
        monitor.run()
        
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}")
        raise

if __name__ == '__main__':
    main()
