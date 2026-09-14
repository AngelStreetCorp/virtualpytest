"""
Audio Transcription Utilities
Shared utility for Whisper-based transcription - NO controller dependencies
Reused by: AudioAIHelpers, transcript_accumulator, and any script needing transcription
"""
import os
import subprocess
import tempfile
import logging
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime
from shared.src.lib.utils.video_utils import merge_video_files

logger = logging.getLogger(__name__)


# Audio detection threshold (dB). Configurable via AUDIO_THRESHOLD_DB env var for
# per-host tuning. Default -60dB: quiet program content (which can sit around -50dB on
# some STBs) stays "audio present", while genuine silence (≈-90dB) still trips. The old
# -50dB default sat right on the content level and caused audio_loss incidents to flap.
AUDIO_THRESHOLD_DB = float(os.getenv('AUDIO_THRESHOLD_DB', '-60.0'))  # Above this = audio, below = silent


def db_to_percentage(db_value: float) -> float:
    """
    Convert decibel value to percentage.

    Used across audio processing modules for consistent dB to percentage conversion.
    Formula: -60dB = 0%, 0dB = 100%

    Args:
        db_value: Audio level in decibels

    Returns:
        Percentage value (0-100)
    """
    return max(0, min(100, (db_value + 60) * 100 / 60))

def check_audio_level(file_path: str, sample_duration: float = 0.5, threshold_db: float = AUDIO_THRESHOLD_DB, 
                       timeout: int = 10, context: str = "") -> Tuple[bool, float]:
    """
    Check if audio file/segment has actual audio content using ffmpeg volumedetect
    
    NOTE: This checks MEAN volume over the duration - it will NOT detect brief audio dropouts!
    For dropout detection, use check_audio_continuous() instead.
    
    Generic audio detection utility - reused by:
    - transcript_accumulator.py: Check MP3 files before transcription
    
    Args:
        file_path: Path to audio/video file (MP3, TS, MP4, etc.)
        sample_duration: Duration to sample in seconds (default 0.5s for fast check)
        threshold_db: Volume threshold in dB (default -50.0dB)
        timeout: ffmpeg timeout in seconds (default 10s)
        context: Context string for logging (e.g., device name)
    
    Returns:
        Tuple of (has_audio: bool, mean_volume_db: float)
        - has_audio: True if mean_volume > threshold_db
        - mean_volume_db: Actual mean volume in dB (-100.0 if silent or error)
    
    Example:
        >>> has_audio, volume = check_audio_level('/path/to/file.mp3', sample_duration=5.0)
        >>> if has_audio:
        >>>     print(f"Audio detected: {volume:.1f}dB")
    """
    try:
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'info',
            '-i', file_path,
            '-t', str(sample_duration),
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # Parse mean_volume from stderr
        mean_volume = -100.0
        for line in result.stderr.split('\n'):
            if 'mean_volume:' in line:
                try:
                    mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    break
                except Exception as e:
                    if context:
                        logger.warning(f"[{context}] Failed to parse volume from: {line} (error: {e})")
                    else:
                        logger.warning(f"Failed to parse volume from: {line} (error: {e})")
        
        # Determine if audio is present
        has_audio = mean_volume > threshold_db
        
        return has_audio, mean_volume
        
    except subprocess.TimeoutExpired:
        if context:
            logger.warning(f"[{context}] Audio level check timeout for: {file_path}")
        else:
            logger.warning(f"Audio level check timeout for: {file_path}")
        return False, -100.0
    except Exception as e:
        if context:
            logger.warning(f"[{context}] Failed to check audio level: {e}")
        else:
            logger.warning(f"Failed to check audio level: {e}")
        return False, -100.0


def check_audio_continuous(file_path: str, sample_duration: float, threshold_db: float = AUDIO_THRESHOLD_DB,
                           min_silence_duration: float = 0.1, timeout: int = 10, context: str = "") -> Tuple[bool, float, float]:
    """
    Check if audio is CONTINUOUS (no dropouts/silence periods) using ffmpeg silencedetect
    
    This detects audio LOSS/dropouts during the segment, not just mean volume.
    Perfect for zapping detection where we need to know if audio drops out during blackscreen.
    
    Args:
        file_path: Path to audio/video file (MP3, TS, MP4, etc.)
        sample_duration: Duration to analyze in seconds (e.g., 1.0 for HDMI, 4.0 for VNC)
        threshold_db: Silence threshold in dB (default -50.0dB)
        min_silence_duration: Minimum silence duration to detect in seconds (default 0.1s)
        timeout: ffmpeg timeout in seconds (default 10s)
        context: Context string for logging (e.g., device name)
    
    Returns:
        Tuple of (has_continuous_audio: bool, total_silence_duration: float, mean_volume_db: float)
        - has_continuous_audio: True if NO silence detected, False if silence/dropout found
        - total_silence_duration: Total duration of silence in seconds
        - mean_volume_db: Mean volume in dB
    
    Example:
        >>> has_audio, silence_dur, volume = check_audio_continuous('/path/to/segment.ts', 1.0)
        >>> if not has_audio:
        >>>     print(f"Audio dropout detected: {silence_dur:.2f}s silence")
    
    Note:
        - Detects ANY silence period >= min_silence_duration
        - Returns False if 200ms dropout in 1s segment (zapping scenario)
        - Returns True only if audio is continuous throughout
    """
    try:
        # Use silencedetect filter to find silence periods
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'info',
            '-i', file_path,
            '-t', str(sample_duration),
            '-af', f'silencedetect=noise={threshold_db}dB:d={min_silence_duration},volumedetect',
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # Parse silence periods from stderr
        silence_periods = []
        silence_start = None
        
        for line in result.stderr.split('\n'):
            if 'silence_start:' in line:
                try:
                    silence_start = float(line.split('silence_start:')[1].strip())
                except:
                    pass
            elif 'silence_end:' in line and silence_start is not None:
                try:
                    # Extract silence_end and duration
                    parts = line.split('|')
                    silence_end = float(parts[0].split('silence_end:')[1].strip())
                    silence_duration = float(parts[1].split('silence_duration:')[1].strip())
                    silence_periods.append({
                        'start': silence_start,
                        'end': silence_end,
                        'duration': silence_duration
                    })
                    silence_start = None
                except:
                    pass

        # Dangling silence_start with no matching silence_end = audio stayed silent through the
        # end of the analyzed window. silencedetect only emits silence_end on a transition back
        # ABOVE the threshold, so constant silence (total audio loss) produces a lone silence_start.
        # Count it to EOF — otherwise total silence is reported as 0.0s and a fully-silent segment
        # is mistaken for "continuous audio" (the audio-loss-not-reported zap bug).
        if silence_start is not None:
            silence_periods.append({
                'start': silence_start,
                'end': sample_duration,
                'duration': max(0.0, sample_duration - silence_start)
            })
            silence_start = None

        # Calculate total silence duration
        total_silence = sum(p['duration'] for p in silence_periods)
        
        # Also get mean volume for logging
        mean_volume = -100.0
        for line in result.stderr.split('\n'):
            if 'mean_volume:' in line:
                try:
                    mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    break
                except:
                    pass
        
        # Has continuous audio = NO silence detected
        has_continuous_audio = len(silence_periods) == 0
        
        if context and silence_periods:
            logger.info(f"[{context}] Detected {len(silence_periods)} silence period(s): total {total_silence:.2f}s")
            for i, period in enumerate(silence_periods):
                logger.info(f"[{context}]   Period {i+1}: {period['start']:.2f}s - {period['end']:.2f}s ({period['duration']:.2f}s)")
        
        return has_continuous_audio, total_silence, mean_volume
        
    except subprocess.TimeoutExpired:
        if context:
            logger.warning(f"[{context}] Audio continuity check timeout for: {file_path}")
        else:
            logger.warning(f"Audio continuity check timeout for: {file_path}")
        return False, 0.0, -100.0
    except Exception as e:
        if context:
            logger.warning(f"[{context}] Failed to check audio continuity: {e}")
        else:
            logger.warning(f"Failed to check audio continuity: {e}")
        return False, 0.0, -100.0


# Global Whisper model cache (singleton pattern)
_whisper_model = None
_whisper_model_name = None


def get_whisper_model(model_name: str = "tiny"):
    """Get cached faster-whisper model (singleton pattern for performance)"""
    global _whisper_model, _whisper_model_name
    
    # Reload if model name changed
    if _whisper_model is None or _whisper_model_name != model_name:
        try:
            # Disable GPU discovery in ONNX Runtime (avoids warning on CPU-only systems)
            os.environ['ORT_DISABLE_ALL_PROVIDERS'] = '1'
            os.environ['ONNXRUNTIME_PROVIDERS'] = 'CPUExecutionProvider'
            
            from faster_whisper import WhisperModel
            print(f"[AudioTranscriptionUtils] Loading faster-whisper model '{model_name}' (one-time load)...")
            # Use CPU with 4 threads for Raspberry Pi 4 optimization
            _whisper_model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1
            )
            _whisper_model_name = model_name
            print(f"[AudioTranscriptionUtils] ✓ faster-whisper model '{model_name}' loaded and cached (4-5x faster than openai-whisper)")
        except ImportError:
            print(f"[AudioTranscriptionUtils] ❌ faster-whisper not installed - run 'pip install faster-whisper'")
            return None
        except Exception as e:
            print(f"[AudioTranscriptionUtils] ❌ Error loading faster-whisper: {e}")
            return None
    
    return _whisper_model


def merge_ts_files(ts_file_paths: List[str], output_path: Optional[str] = None, device_id: str = "") -> Optional[str]:
    """
    Legacy function for transcript accumulator - merges TS to temp TS file
    """
    if not ts_file_paths:
        return None
    
    if len(ts_file_paths) == 1:
        return ts_file_paths[0]
    
    if output_path is None:
        temp_dir = tempfile.gettempdir()
        device_suffix = f"_{device_id}" if device_id else ""
        output_path = os.path.join(temp_dir, f"merged_ts{device_suffix}.ts")
    
    return merge_video_files(ts_file_paths, output_path, 'ts', False, 60)


def extract_audio_from_ts(ts_file_path: str, output_path: Optional[str] = None, device_id: str = "") -> Optional[str]:
    """
    Extract audio from TS file as WAV (16kHz mono for Whisper)
    
    Args:
        ts_file_path: Path to TS file
        output_path: Optional output path (if None, creates temp file in /tmp - REUSED)
        device_id: Device identifier for device-specific temp file (e.g., "capture1")
    
    Returns:
        Path to extracted WAV file or None on failure
    """
    try:
        # Create output path if not provided - use FIXED name per device, overwrite each time
        if output_path is None:
            temp_dir = tempfile.gettempdir()  # /tmp/
            # Use device-specific fixed filename (no timestamp) - will be overwritten on next extraction
            device_suffix = f"_{device_id}" if device_id else ""
            audio_filename = f"audio_temp_whisper{device_suffix}.wav"
            output_path = os.path.join(temp_dir, audio_filename)
        
        # Extract audio with Whisper-optimized settings (16kHz mono)
        cmd = [
            'ffmpeg', '-y', '-i', ts_file_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',  # Mono
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        else:
            print(f"[AudioTranscriptionUtils] ❌ Failed to extract audio from {os.path.basename(ts_file_path)}")
            return None
            
    except Exception as e:
        print(f"[AudioTranscriptionUtils] ❌ Error extracting audio: {e}")
        return None


def detect_audio_level(file_path: str, device_id: str = "") -> tuple:
    """
    Detect audio level using ffmpeg volumedetect - REUSES detector.py logic
    
    Args:
        file_path: Path to audio/video file (TS, WAV, MP4, etc.)
        device_id: Device identifier for logging (e.g., "capture1")
    
    Returns:
        Tuple of (has_audio: bool, volume_percentage: int, mean_volume_db: float)
    """
    import re
    
    prefix = f"[{device_id}] " if device_id else ""
    try:
        # Use ffmpeg volumedetect - same as detector.py
        cmd = [
            'ffmpeg', '-i', file_path,
            '-af', 'volumedetect',
            '-vn', '-f', 'null', '-'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        # Parse mean_volume from stderr - same as detector.py
        mean_volume = -100.0
        for line in result.stderr.split('\n'):
            if 'mean_volume:' in line:
                match = re.search(r'mean_volume:\s*([-\d.]+)\s*dB', line)
                if match:
                    mean_volume = float(match.group(1))
                    break
        
        # Convert dB to 0-100% scale using shared utility
        volume_percentage = db_to_percentage(mean_volume)
        has_audio = volume_percentage > 5  # 5% threshold - same as detector.py
        
        print(f"{prefix}[AudioTranscriptionUtils] Audio level: {mean_volume:.1f}dB ({volume_percentage}% - {'sound' if has_audio else 'silent'})")
        
        return has_audio, int(volume_percentage), mean_volume
        
    except Exception as e:
        print(f"{prefix}[AudioTranscriptionUtils] Audio check error: {e}, assuming sound present")
        return True, 0, -100.0


# Global flag to enable/disable spell checking (disabled by default for CPU efficiency)
ENABLE_SPELLCHECK = False

# Initialize spellchecker globally if enabled (loads dictionary once)
if ENABLE_SPELLCHECK:
    from spellchecker import SpellChecker
    spell = SpellChecker(language='en')  # Default to English; will adjust dynamically

def clean_transcript_text(text: str) -> str:
    """Regex-based text cleaning for OCR/transcript noise (shared utility)"""
    import re
    if not text:
        return ''

    # Common OCR/transcript fixes
    corrections = {
        '1': 'l', '0': 'o', '5': 'S', '8': 'B',
        '|': 'l', '!': 'l', '(': 'C', ')': 'D'
    }
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)

    # Remove noise: repeated chars, isolated symbols
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)
    text = re.sub(r'(?<!\w)[^a-zA-Z\s]{1,2}(?!\w)', '', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text.strip())

    # Remove short non-words (e.g., isolated numbers/symbols)
    text = re.sub(r'\b(?:\d{1,3}|[^a-zA-Z\d\s]{1,3})\b', '', text)

    # Filter junk lines
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if len(line) < 10:
            continue
        letter_ratio = len(re.sub(r'[^a-zA-Z]', '', line)) / len(line)
        if letter_ratio < 0.6:
            continue
        cleaned.append(line)

    return ' '.join(cleaned).strip()

def correct_spelling(text: str, detected_language: str = None) -> str:
    """Optional spell correction (shared utility) - requires ENABLE_SPELLCHECK=True"""
    if not ENABLE_SPELLCHECK or not text:
        return text
    
    # Adjust language
    lang = 'en'
    if detected_language in ['fra', 'fr']:
        lang = 'fr'
    elif detected_language in ['deu', 'de']:
        lang = 'de'
    spell.language = lang  # Dynamically switch
    
    words = text.split()
    corrected = [spell.correction(word) if len(word) >= 3 and spell.unknown([word]) else word for word in words]
    return ' '.join(corrected).strip()

def transcribe_audio(audio_file_path: str, model_name: str = "tiny", skip_silence_check: bool = False, device_id: str = "", language: Optional[str] = None) -> Dict[str, Any]:
    """
    Transcribe audio file using Whisper (with model caching)
    
    Args:
        audio_file_path: Path to audio file (WAV recommended)
        model_name: Whisper model name (tiny, base, small, medium, large)
        skip_silence_check: If True, skip audio level check (default False)
        device_id: Device identifier for logging (e.g., "capture1")
    
    Returns:
        Dict with 'transcript', 'language', 'confidence', 'success'
    """
    prefix = f"[{device_id}] " if device_id else ""
    try:
        # Quick pre-check: Skip Whisper if audio is silent (saves CPU)
        # Reuses same audio detection logic as detector.py
        if not skip_silence_check:
            has_audio, volume_percentage, mean_volume_db = detect_audio_level(audio_file_path, device_id=device_id)
            if not has_audio:
                print(f"{prefix}[AudioTranscriptionUtils] Skipping Whisper - audio is silent")
                return {
                    'success': True,
                    'transcript': '',
                    'language': 'unknown',
                    'confidence': 0.0,
                    'skipped': True,
                    'reason': 'silent_audio',
                    'volume_percentage': volume_percentage,
                    'mean_volume_db': mean_volume_db
                }
        
        model = get_whisper_model(model_name)
        
        if model is None:
            return {
                'success': False,
                'transcript': '',
                'language': 'unknown',
                'confidence': 0.0,
                'error': 'Whisper model not available'
            }
        
        # Transcribe with faster-whisper (4-5x faster than openai-whisper)
        # faster-whisper uses a different API that returns segments as a generator
        segments_list, info = model.transcribe(
            audio_file_path,
            beam_size=1,
            vad_filter=True,  # Voice Activity Detection - skip silence automatically
            vad_parameters=dict(min_silence_duration_ms=500),
            language=language,
            word_timestamps=False,  # Sentence-level timestamps (30-40% faster, still perfect for subtitles)
            condition_on_previous_text=False,
            temperature=0
        )
        
        # Collect all segments and build transcript with timing info
        segments = list(segments_list)
        transcript = " ".join([segment.text for segment in segments]).strip()
        language = info.language
        
        # Convert language code to name
        lang_map = {
            'en': 'English', 'fr': 'French', 'de': 'German', 'es': 'Spanish',
            'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'pl': 'Polish',
            'ru': 'Russian', 'zh': 'Chinese', 'ja': 'Japanese', 'ko': 'Korean'
        }
        language_name = lang_map.get(language, language)
        
        # Use language probability as confidence
        confidence = info.language_probability if hasattr(info, 'language_probability') else 0.5
        
        # Build timed segments (group words into 2-line segments for subtitle display)
        timed_segments = []
        total_duration = 0.0
        if segments:
            for seg in segments:
                # Each segment from Whisper has start/end time and words
                # Add confidence from segment's avg_logprob (faster-whisper provides this)
                segment_confidence = 0.0
                if hasattr(seg, 'avg_logprob'):
                    # Convert avg_logprob to confidence (0-1 range)
                    # avg_logprob is typically between -1 and 0, we convert to 0-1 scale
                    segment_confidence = max(0.0, min(1.0, (seg.avg_logprob + 1.0)))
                
                segment_duration = seg.end - seg.start
                total_duration = max(total_duration, seg.end)  # Track total audio duration
                
                timed_segments.append({
                    'start': seg.start,
                    'end': seg.end,
                    'text': seg.text.strip(),
                    'confidence': segment_confidence,
                    'duration': segment_duration
                })
        
        # New: Apply shared cleaning (regex + optional spellcheck)
        transcript = clean_transcript_text(transcript)
        if ENABLE_SPELLCHECK:
            transcript = correct_spelling(transcript, language)
        
        return {
            'success': True,
            'transcript': transcript,
            'language': language_name,
            'language_code': language if language else info.language,
            'confidence': confidence,
            'segments': timed_segments,  # Add timed segments for subtitle display
            'duration': total_duration  # Total audio duration in seconds
        }
        
    except Exception as e:
        print(f"[AudioTranscriptionUtils] ❌ Transcription error: {e}")
        return {
            'success': False,
            'transcript': '',
            'language': 'unknown',
            'confidence': 0.0,
            'error': str(e)
        }


def transcribe_ts_segments(ts_file_paths: List[str], merge: bool = True, model_name: str = "tiny", device_id: str = "") -> Dict[str, Any]:
    """
    Transcribe multiple TS segments (with optional merging for better context)
    
    Args:
        ts_file_paths: List of TS file paths
        merge: If True, merge all segments before transcription (better quality)
        model_name: Whisper model name
        device_id: Device identifier for logging (e.g., "capture1")
    
    Returns:
        Dict with 'transcript', 'language', 'confidence', 'success', 'segments_processed'
    """
    prefix = f"[{device_id}] " if device_id else ""
    try:
        if not ts_file_paths:
            return {
                'success': False,
                'transcript': '',
                'language': 'unknown',
                'confidence': 0.0,
                'segments_processed': 0,
                'error': 'No TS files provided'
            }
        
        # Merge segments if requested and multiple files
        if merge and len(ts_file_paths) > 1:
            merged_ts = merge_ts_files(ts_file_paths, device_id=device_id)
            
            if merged_ts:
                # Extract audio from merged file
                audio_file = extract_audio_from_ts(merged_ts, device_id=device_id)
                
                if audio_file:
                    # Transcribe merged audio
                    result = transcribe_audio(audio_file, model_name, device_id=device_id)
                    result['segments_processed'] = len(ts_file_paths)
                    result['merged'] = True
                    # No cleanup needed - files are overwritten on next run
                    return result
        
        # Fallback: process first segment only (or single segment)
        ts_file = ts_file_paths[0]
        audio_file = extract_audio_from_ts(ts_file, device_id=device_id)
        
        if audio_file:
            result = transcribe_audio(audio_file, model_name, device_id=device_id)
            result['segments_processed'] = 1
            result['merged'] = False
            # No cleanup needed - file is overwritten on next run
            return result
        
        return {
            'success': False,
            'transcript': '',
            'language': 'unknown',
            'confidence': 0.0,
            'segments_processed': 0,
            'error': 'Failed to extract audio from TS files'
        }
        
    except Exception as e:
        print(f"[AudioTranscriptionUtils] ❌ Error in transcribe_ts_segments: {e}")
        return {
            'success': False,
            'transcript': '',
            'language': 'unknown',
            'confidence': 0.0,
            'segments_processed': 0,
            'error': str(e)
        }

