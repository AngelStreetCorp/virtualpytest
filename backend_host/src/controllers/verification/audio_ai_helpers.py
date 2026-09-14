"""
Audio AI Analysis Helpers

AI-powered audio analysis functionality for speech-to-text transcription:
1. Audio segment retrieval and processing
2. Speech-to-text transcription using local Whisper (optimized for speed)
3. Language detection from transcribed text
4. Audio analysis logging similar to subtitle detection
5. Integration with ZapController for comprehensive analysis

This helper handles all AI-powered audio analysis operations using
local Whisper models for fast, offline speech recognition and language detection.
Performance optimized with tiny model (~39MB) for real-time zap testing.
"""

import os
import base64
import requests
import tempfile
import json
import time
import wave
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

# Optional imports for fallback language detection
try:
    from langdetect import detect, LangDetectException
    LANG_DETECT_AVAILABLE = True
except ImportError:
    LANG_DETECT_AVAILABLE = False


class AudioAIHelpers:
    """AI-powered audio analysis operations using local Whisper for fast speech recognition."""
    
    def __init__(self, av_controller, device_name: str = "AudioAI"):
        """
        Initialize audio AI helpers.
        
        Args:
            av_controller: AV controller for capturing audio/video and device context
            device_name: Name for logging purposes
        """
        self.av_controller = av_controller
        self.device_name = device_name
    
    # =============================================================================
    # Audio Segment Retrieval
    # =============================================================================
    
    def get_recent_audio_segments(self, segment_count: int = 3, segment_duration: int = None) -> List[str]:
        """
        Retrieve the last N audio segments from video capture.
        
        Args:
            segment_count: Number of recent segments to retrieve (default: 3)
            segment_duration: Duration of each segment in seconds (default: uses HLS_SEGMENT_DURATION from AVControllerInterface)
            
        Returns:
            List of audio file paths (WAV format) ready for AI analysis
        """
        merged_ts = None  # Track for cleanup - declare outside try block
        try:
            # Use global HLS segment duration if not specified
            if segment_duration is None:
                from backend_host.src.controllers.base_controller import AVControllerInterface
                segment_duration = AVControllerInterface.HLS_SEGMENT_DURATION
            
            print(f"AudioAI[{self.device_name}]: Retrieving last {segment_count} audio segments ({segment_duration}s each)...")
            
            # Get video capture path from AV controller
            if not hasattr(self.av_controller, 'video_capture_path'):
                print(f"AudioAI[{self.device_name}]: No video capture path available")
                return []
            
            capture_folder = self.av_controller.video_capture_path
            if not os.path.exists(capture_folder):
                print(f"AudioAI[{self.device_name}]: Capture folder does not exist: {capture_folder}")
                return []
            
            # Use centralized storage path utilities for hot/cold architecture
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            
            # Get segments folder using centralized path resolution (handles hot/cold storage)
            segments_folder = get_capture_storage_path(capture_folder, 'segments')
            if not os.path.exists(segments_folder):
                print(f"AudioAI[{self.device_name}]: Segments folder does not exist: {segments_folder}")
                return []
            
            # Find recent HLS segment files from hot storage (last 30 seconds)
            cutoff_time = time.time() - 30  # 30 seconds ago
            ts_files = []
            
            # Check hot storage (segments/ root) only - last 10 files
            for filename in os.listdir(segments_folder):
                if filename.startswith('segment_') and filename.endswith('.ts'):
                    filepath = os.path.join(segments_folder, filename)
                    # Only include files, not subdirectories (hour folders)
                    if os.path.isfile(filepath) and os.path.getmtime(filepath) >= cutoff_time:
                        ts_files.append({
                            'path': filepath,
                            'filename': filename,
                            'mtime': os.path.getmtime(filepath)
                        })
            
            # Sort by modification time (newest first)
            ts_files.sort(key=lambda x: x['mtime'], reverse=True)
            
            # Take the most recent files (up to segment_count)
            recent_files = ts_files[:segment_count]
            
            if not recent_files:
                # Check if we have image captures but no TS files (device compatibility check)
                # Use centralized storage path utilities for hot/cold architecture
                from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
                captures_folder = get_capture_storage_path(capture_folder, 'captures')
                jpg_files = []
                if os.path.exists(captures_folder):
                    for filename in os.listdir(captures_folder):
                        if filename.startswith('capture_') and filename.endswith('.jpg'):
                            jpg_files.append(filename)
                
                if jpg_files:
                    print(f"AudioAI[{self.device_name}]: Device uses image-only capture, audio analysis not available")
                    print(f"AudioAI[{self.device_name}]: Found {len(jpg_files)} image captures but no HLS segments")
                    return []
                else:
                    print(f"AudioAI[{self.device_name}]: No recent HLS segments found for audio extraction")
                    print(f"AudioAI[{self.device_name}]: Checked folder: {capture_folder}")
                    return []
            
            # NEW: Merge TS files first if more than one
            if len(recent_files) > 1:
                print(f"AudioAI[{self.device_name}]: Merging {len(recent_files)} TS segments into one file...")
                merged_ts = self._merge_ts_files([f['path'] for f in recent_files])
                if merged_ts:
                    # Replace recent_files with single merged file
                    recent_files = [{'path': merged_ts, 'filename': 'merged.ts', 'mtime': time.time()}]
                    print(f"AudioAI[{self.device_name}]: Merged successfully into: {os.path.basename(merged_ts)}")
                else:
                    print(f"AudioAI[{self.device_name}]: Failed to merge TS segments, proceeding with individual files")
            
            # Extract audio from (merged) TS file(s)
            audio_files = []
            temp_dir = tempfile.gettempdir()
            
            print(f"AudioAI[{self.device_name}]: Found {len(recent_files)} recent HLS segments for audio extraction")
            
            for i, ts_file in enumerate(recent_files):
                try:
                    # Create temporary audio file - use FIXED name, overwrite each time
                    audio_filename = f"audio_segment_{i}_{self.device_name}.wav"
                    audio_path = os.path.join(temp_dir, audio_filename)
                    
                    # Extract audio using ffmpeg from HLS segment
                    # TS files are already 2-second segments, so no duration needed
                    cmd = [
                        'ffmpeg', '-y',  # -y to overwrite existing files
                        '-i', ts_file['path'],
                        '-vn',  # No video
                        '-acodec', 'pcm_s16le',  # WAV format
                        '-ar', '16000',  # 16kHz sample rate (good for speech)
                        '-ac', '1',  # Mono
                        audio_path
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0 and os.path.exists(audio_path):
                        # Verify the audio file has content
                        if os.path.getsize(audio_path) > 1024:  # At least 1KB
                            audio_files.append(audio_path)
                            print(f"AudioAI[{self.device_name}]: Extracted audio segment {i+1}: {os.path.basename(audio_path)}")
                        else:
                            print(f"AudioAI[{self.device_name}]: Audio segment {i+1} is too small, skipping")
                            if os.path.exists(audio_path):
                                os.unlink(audio_path)
                    else:
                        print(f"AudioAI[{self.device_name}]: Failed to extract audio from segment {i+1}: {result.stderr}")
                        
                except Exception as e:
                    print(f"AudioAI[{self.device_name}]: Error processing segment {i+1}: {e}")
                    continue
            
            # NEW: Cleanup temporary merged TS if it was created
            if merged_ts and os.path.exists(merged_ts):
                try:
                    os.unlink(merged_ts)
                    print(f"AudioAI[{self.device_name}]: Cleaned up temporary merged TS: {os.path.basename(merged_ts)}")
                except Exception as e:
                    print(f"AudioAI[{self.device_name}]: Failed to clean up merged TS: {e}")
            
            if not audio_files:
                print(f"AudioAI[{self.device_name}]: No audio files extracted from HLS segments")
                return []
            
            print(f"AudioAI[{self.device_name}]: Successfully extracted {len(audio_files)} audio segments")
            return audio_files
            
        except Exception as e:
            print(f"AudioAI[{self.device_name}]: Error retrieving audio segments: {e}")
            # Cleanup on error too
            if merged_ts and os.path.exists(merged_ts):
                os.unlink(merged_ts)
            return []
    
    def extract_audio_from_segments(self, segment_files: List[Tuple[str, str]], segment_count: int = 3) -> List[str]:
        """Extract audio from specific HLS segments - delegates to shared utility"""
        from shared.src.lib.utils.audio_transcription_utils import merge_ts_files, extract_audio_from_ts
        
        try:
            selected_segments = segment_files[-segment_count:] if len(segment_files) > segment_count else segment_files
            
            if not selected_segments:
                return []
            
            # Extract paths for merging
            ts_paths = [segment_path for _, segment_path in selected_segments]
            
            # For multiple segments, merge them first (better quality)
            if len(ts_paths) > 1:
                print(f"AudioAI[{self.device_name}]: Merging {len(ts_paths)} TS segments into one file...")
                merged_ts = merge_ts_files(ts_paths, device_id=self.device_name)
                
                if merged_ts:
                    # Extract audio from merged file using utility
                    audio_path = extract_audio_from_ts(merged_ts, device_id=self.device_name)
                    
                    # Cleanup merged TS file
                    try:
                        os.remove(merged_ts)
                        print(f"AudioAI[{self.device_name}]: Cleaned up temporary merged TS: {os.path.basename(merged_ts)}")
                    except:
                        pass
                    
                    if audio_path:
                        print(f"AudioAI[{self.device_name}]: Successfully extracted merged audio: {os.path.basename(audio_path)}")
                        return [audio_path]
                    else:
                        print(f"AudioAI[{self.device_name}]: Failed to extract audio from merged file")
            
            # Fallback: single segment or merge failed
            print(f"AudioAI[{self.device_name}]: Processing single segment...")
            audio_path = extract_audio_from_ts(ts_paths[0], device_id=self.device_name)
            return [audio_path] if audio_path else []
            
        except Exception as e:
            print(f"AudioAI[{self.device_name}]: Audio extraction error: {e}")
            return []
    
    # Reuse utility function instead of duplicating
    def _merge_ts_files(self, ts_files: List[str]) -> Optional[str]:
        """Merge multiple TS files - delegates to shared utility"""
        from shared.src.lib.utils.audio_transcription_utils import merge_ts_files
        return merge_ts_files(ts_files, device_id=self.device_name)
    
    # =============================================================================
    # AI-Powered Speech-to-Text Analysis
    # =============================================================================
    
    def analyze_audio_segments_ai(self, audio_files: List[str], upload_to_r2: bool = True, early_stop: bool = True) -> Dict[str, Any]:
        """
        AI-powered speech-to-text analysis for multiple audio segments.
        
        Args:
            audio_files: List of audio file paths to analyze
            upload_to_r2: Whether to upload audio files to R2 for traceability (default: True)
            early_stop: Whether to stop processing after first successful speech detection (default: True)
            
        Returns:
            Dictionary with detailed AI audio analysis results including R2 URLs
        """
        try:
            print(f"AudioAI[{self.device_name}]: Starting AI analysis of {len(audio_files)} audio segments...")
            
            if not audio_files:
                return {
                    'success': True,
                    'segments_analyzed': 0,
                    'combined_transcript': '',
                    'detected_language': 'unknown',
                    'confidence': 0.0,
                    'segments': [],
                    'analysis_type': 'ai_audio_transcription'
                }
            
            # Check faster-whisper availability (no API key needed for local processing)
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                print(f"AudioAI[{self.device_name}]: faster-whisper not installed - run 'pip install faster-whisper'")
                return {
                    'success': False,
                    'error': 'faster-whisper not available - please install faster-whisper',
                    'analysis_type': 'local_whisper_transcription'
                }
            
            segment_results = []
            all_transcripts = []
            early_stopped = False
            
            for i, audio_file in enumerate(audio_files):
                try:
                    print(f"AudioAI[{self.device_name}]: Analyzing audio segment {i+1}/{len(audio_files)}...")
                    
                    # Transcribe audio segment
                    transcript, language, confidence = self.transcribe_audio_with_ai(audio_file)
                    
                    # Upload audio file to R2 for traceability (before cleanup)
                    r2_url = None
                    if upload_to_r2 and os.path.exists(audio_file):
                        r2_url = self._upload_audio_to_r2(audio_file, i + 1)
                    
                    segment_result = {
                        'segment_number': i + 1,
                        'audio_file': os.path.basename(audio_file),
                        'audio_url': r2_url,  # NEW: R2 URL for traceability
                        'transcript': transcript,
                        'detected_language': language,
                        'confidence': confidence,
                        'has_speech': bool(transcript and len(transcript.strip()) > 0),
                        'file_size': os.path.getsize(audio_file) if os.path.exists(audio_file) else 0
                    }
                    
                    segment_results.append(segment_result)
                    
                    if transcript:
                        all_transcripts.append(transcript)
                        print(f"AudioAI[{self.device_name}]: Segment {i+1} transcript: '{transcript[:50]}{'...' if len(transcript) > 50 else ''}' (lang: {language}, conf: {confidence:.2f})")
                        
                        # Early stop optimization: if we found speech and language, no need to process more segments
                        if early_stop and language != 'unknown' and confidence > 0.5:
                            remaining_segments = len(audio_files) - (i + 1)
                            if remaining_segments > 0:
                                print(f"AudioAI[{self.device_name}]: ⚡ Early stop: Speech detected with language '{language}' (confidence: {confidence:.2f}), skipping {remaining_segments} remaining segment(s)")
                                early_stopped = True
                                break
                    else:
                        print(f"AudioAI[{self.device_name}]: Segment {i+1}: No speech detected")
                        
                except Exception as e:
                    print(f"AudioAI[{self.device_name}]: Error analyzing segment {i+1}: {e}")
                    segment_results.append({
                        'segment_number': i + 1,
                        'audio_file': os.path.basename(audio_file) if audio_file else 'unknown',
                        'transcript': '',
                        'detected_language': 'unknown',
                        'confidence': 0.0,
                        'has_speech': False,
                        'error': str(e)
                    })
            
            # Combine results
            combined_transcript = ' '.join(all_transcripts).strip()
            
            # Determine overall language (most confident detection)
            detected_language = 'unknown'
            max_confidence = 0.0
            
            for result in segment_results:
                if result.get('confidence', 0) > max_confidence and result.get('detected_language') != 'unknown':
                    detected_language = result.get('detected_language')
                    max_confidence = result.get('confidence', 0)
            
            # Calculate overall confidence
            confidences = [r.get('confidence', 0) for r in segment_results if r.get('has_speech')]
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            # Count successful segments
            successful_segments = len([r for r in segment_results if r.get('has_speech')])
            
            # Create detection message
            if combined_transcript:
                early_stop_info = " (early stopped)" if early_stopped else ""
                detection_message = f"Speech detected in {successful_segments}/{len(segment_results)} segments{early_stop_info}: '{combined_transcript[:100]}{'...' if len(combined_transcript) > 100 else ''}'"
            else:
                detection_message = f"No speech detected in any of the {len(segment_results)} audio segments"
            
            # Collect R2 URLs for traceability
            audio_urls = [result.get('audio_url') for result in segment_results if result.get('audio_url')]
            uploaded_count = len(audio_urls)
            
            overall_result = {
                'success': True,
                'segments_analyzed': len(segment_results),  # Use actual processed segments, not total files
                'total_segments_available': len(audio_files),  # Track total segments available
                'successful_segments': successful_segments,
                'combined_transcript': combined_transcript,
                'detected_language': detected_language,
                'confidence': overall_confidence,
                'detection_message': detection_message,
                'segments': segment_results,
                'audio_urls': audio_urls,  # NEW: List of R2 URLs for traceability
                'uploaded_segments': uploaded_count,  # NEW: Count of uploaded segments
                'early_stopped': early_stopped,  # NEW: Track if processing was stopped early
                'analysis_type': 'local_whisper_transcription',
                'timestamp': datetime.now().isoformat()
            }
            
            # Log R2 upload summary
            if upload_to_r2:
                processed_info = f"{len(segment_results)}/{len(audio_files)}" if early_stopped else f"{len(audio_files)}"
                print(f"AudioAI[{self.device_name}]: R2 Upload Summary: {uploaded_count} audio segments uploaded (processed {processed_info} segments)")
                if audio_urls:
                    print(f"AudioAI[{self.device_name}]: Audio files available at: audio-analysis/{self.device_name.replace(' ', '_').lower()}/")
            
            # Clean up temporary audio files
            self._cleanup_audio_files(audio_files)
            
            return overall_result
            
        except Exception as e:
            print(f"AudioAI[{self.device_name}]: AI audio analysis error: {e}")
            # Clean up on error too
            self._cleanup_audio_files(audio_files)
            return {
                'success': False,
                'error': f'Local Whisper analysis failed: {str(e)}',
                'analysis_type': 'local_whisper_transcription'
            }
    
    def transcribe_audio_with_ai(self, audio_file: str) -> Tuple[str, str, float]:
        """
        Transcribe a single audio file using local Whisper - delegates to shared utility
        
        Args:
            audio_file: Path to audio file (WAV format)
            
        Returns:
            Tuple of (transcript, detected_language, confidence)
        """
        from shared.src.lib.utils.audio_transcription_utils import transcribe_audio
        
        result = transcribe_audio(audio_file, model_name='tiny', device_id=self.device_name)
        
        if result['success']:
            print(f"AudioAI[{self.device_name}]: Whisper detected speech: '{result['transcript'][:50]}...' (Language: {result['language']})")
        else:
            print(f"AudioAI[{self.device_name}]: Whisper found no speech in audio")
        
        return result['transcript'], result['language'], result['confidence']
    
    # =============================================================================
    # Utility Methods
    # =============================================================================
    
    def _upload_audio_to_r2(self, audio_file: str, segment_number: int) -> Optional[str]:
        """
        Upload audio file to R2 storage for traceability.
        
        Args:
            audio_file: Local path to audio file
            segment_number: Segment number for naming
            
        Returns:
            R2 URL if successful, None if failed
        """
        try:
            if not os.path.exists(audio_file):
                print(f"AudioAI[{self.device_name}]: Audio file not found for upload: {audio_file}")
                return None
            
            # Import CloudflareUtils
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            uploader = get_cloudflare_utils()
            
            # Generate R2 path with timestamp and device context
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # Include milliseconds
            device_context = self.device_name.replace(' ', '_').lower()
            filename = f"audio_segment_{segment_number}_{timestamp}.wav"
            
            # Use audio-analysis folder structure
            remote_path = f"audio-analysis/{device_context}/{filename}"
            
            # Prepare file mapping with correct content type for WAV files
            file_mappings = [{
                'local_path': audio_file,
                'remote_path': remote_path,
                'content_type': 'audio/wav'  # Explicit content type for audio files
            }]
            
            print(f"AudioAI[{self.device_name}]: Uploading audio segment {segment_number} to R2...")
            
            # Upload to R2
            upload_result = uploader.upload_files(file_mappings)
            
            if upload_result['uploaded_files']:
                r2_url = upload_result['uploaded_files'][0]['url']
                file_size = upload_result['uploaded_files'][0]['size']
                print(f"AudioAI[{self.device_name}]: Audio segment {segment_number} uploaded successfully ({file_size} bytes)")
                print(f"AudioAI[{self.device_name}]: R2 URL: {r2_url}")
                return r2_url
            else:
                error_msg = upload_result['failed_uploads'][0]['error'] if upload_result['failed_uploads'] else 'Unknown upload error'
                print(f"AudioAI[{self.device_name}]: Failed to upload audio segment {segment_number}: {error_msg}")
                return None
                
        except Exception as e:
            print(f"AudioAI[{self.device_name}]: Error uploading audio segment {segment_number} to R2: {e}")
            return None
    
    def _cleanup_audio_files(self, audio_files: List[str]):
        """No cleanup needed - files use fixed names and are overwritten on next run."""
        # This saves disk I/O and prevents accumulation of temp files
        pass
    
    def get_audio_analysis_summary(self, audio_result: Dict[str, Any]) -> str:
        """
        Generate a summary string for audio analysis results.
        
        Args:
            audio_result: Audio analysis result dictionary
            
        Returns:
            Formatted summary string for logging
        """
        if not audio_result.get('success'):
            return f"Audio analysis failed: {audio_result.get('error', 'Unknown error')}"
        
        segments_analyzed = audio_result.get('segments_analyzed', 0)
        successful_segments = audio_result.get('successful_segments', 0)
        combined_transcript = audio_result.get('combined_transcript', '')
        detected_language = audio_result.get('detected_language', 'unknown')
        confidence = audio_result.get('confidence', 0.0)
        
        if combined_transcript:
            transcript_preview = combined_transcript[:100] + "..." if len(combined_transcript) > 100 else combined_transcript
            return f"Speech detected in {successful_segments}/{segments_analyzed} segments: '{transcript_preview}' (Language: {detected_language}, Confidence: {confidence:.2f})"
        else:
            return f"No speech detected in {segments_analyzed} audio segments"
