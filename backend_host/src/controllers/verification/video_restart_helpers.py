"""
Video Restart Helpers

Dedicated helper functions for restart video generation and analysis.
Extracted from FFmpegCaptureController to maintain clean separation of concerns.
"""

import os
import time
import uuid
import re
import subprocess
import threading
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from backend_host.src.lib.utils.system_info_utils import get_files_by_pattern


class VideoRestartHelpers:
    """Helper class for restart video functionality."""
    
    def __init__(self, av_controller, device_name: str = "RestartVideo"):
        """
        Initialize restart video helpers.
        
        Args:
            av_controller: AV controller instance
            device_name: Name for logging purposes
        """
        self.av_controller = av_controller
        self.device_name = device_name
        self.capture_source = getattr(av_controller, 'capture_source', 'AV')
        
        # Get paths from controller
        self.video_stream_path = getattr(av_controller, 'video_stream_path', '')
        self.video_capture_path = getattr(av_controller, 'video_capture_path', '')
        
        # HLS configuration
        self.HLS_SEGMENT_DURATION = getattr(av_controller, 'HLS_SEGMENT_DURATION', 1)
        
        # Dubbing helpers (lazy initialization)
        self._dubbing_helpers = None
        
        # Translation cache: {video_id: {language: {frame_data: {...}}}}
        self._translation_cache = {}
        
        # Status cache directory (use hot storage for temporary status files)
        from shared.src.lib.utils.storage_path_utils import is_ram_mode
        if is_ram_mode(self.video_capture_path):
            # RAM mode: status files in /hot/ subdirectory
            self._status_dir = os.path.join(self.video_capture_path, 'hot', 'status')
        else:
            # SD mode: status files in root directory
            self._status_dir = os.path.join(self.video_capture_path, 'status')
        os.makedirs(self._status_dir, exist_ok=True)
    
    def _get_restart_video_path(self, filename: str = "restart_original_video.mp4") -> str:
        """
        Get the correct path for restart video files based on hot/cold storage architecture.
        
        Args:
            filename: Name of the restart video file
            
        Returns:
            Full path to the video file in the correct storage location
        """
        from shared.src.lib.utils.storage_path_utils import is_ram_mode
        
        if is_ram_mode(self.video_capture_path):
            # RAM mode: write to /hot/ subdirectory
            return os.path.join(self.video_capture_path, 'hot', filename)
        else:
            # SD mode: write to root directory
            return os.path.join(self.video_capture_path, filename)
    
    def _get_storage_aware_base_dir(self) -> str:
        """
        Get the base directory for restart files, considering hot/cold storage.
        This should be passed to dubbing helpers so they can find restart files.
        
        Returns:
            Base directory path (includes /hot/ if in RAM mode)
        """
        from shared.src.lib.utils.storage_path_utils import is_ram_mode
        
        if is_ram_mode(self.video_capture_path):
            # RAM mode: files are in /hot/ subdirectory
            return os.path.join(self.video_capture_path, 'hot')
        else:
            # SD mode: files are in root directory
            return self.video_capture_path
    
    def generate_restart_video_only(self, duration_seconds: float = 10.0) -> Optional[Dict[str, Any]]:
        """Generate video only - fast response"""
        try:
            print(f"RestartHelpers[{self.device_name}]: Generating restart video ({duration_seconds}s)")
            
            # Use centralized storage path utilities for hot/cold architecture
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, is_ram_mode
            
            # Determine if we're in hot (RAM) mode
            ram_mode = is_ram_mode(self.video_capture_path)
            mode_str = "RAM (hot)" if ram_mode else "SD (cold)"
            print(f"RestartHelpers[{self.device_name}]: Storage mode: {mode_str}")
            
            # Video generation logic
            # Get segments folder using centralized path resolution
            segments_folder = get_capture_storage_path(self.video_capture_path, 'segments')
            m3u8_path = os.path.join(segments_folder, "output.m3u8")
            
            if not os.path.exists(m3u8_path):
                print(f"RestartHelpers[{self.device_name}]: M3U8 not found at {m3u8_path}")
                return None
            
            # Get segments using fast os.scandir (no subprocess overhead)
            try:
                all_segment_paths = get_files_by_pattern(segments_folder, r'^segment_.*\.ts$')
                all_segment_paths.sort(key=lambda path: os.path.getmtime(path))
            except Exception as e:
                print(f"RestartHelpers[{self.device_name}]: Error finding segments: {e}")
                all_segment_paths = []
            
            segments_needed = int(duration_seconds / self.HLS_SEGMENT_DURATION) + 2
            segment_files = [(os.path.basename(p), p) for p in all_segment_paths[-segments_needed:]]
            
            if not segment_files:
                return None
            
            # Compress to MP4
            from  backend_host.src.lib.utils.video_compression_utils import VideoCompressionUtils
            compressor = VideoCompressionUtils()
            
            # Get correct path for video file (handles hot/cold storage)
            video_filename = "restart_original_video.mp4"
            local_video_path = self._get_restart_video_path(video_filename)
            print(f"RestartHelpers[{self.device_name}]: Writing video to: {local_video_path} (mode: {mode_str})")
            
            compression_result = compressor.compress_hls_to_mp4(
                m3u8_path=m3u8_path,
                segment_files=segment_files,
                output_path=local_video_path,
                compression_level="medium"
            )
            
            if not compression_result['success']:
                return None
            
            # Build URL
            video_url = self._build_video_url(video_filename)
            
            # Get screenshots for later analysis
            screenshot_urls = self._get_aligned_screenshots(segment_files)
            
            video_id = f"restart_{int(time.time())}_{str(uuid.uuid4())[:8]}"
            
            return {
                'success': True,
                'video_url': video_url,
                'video_id': video_id,
                'screenshot_urls': screenshot_urls,
                'segment_count': len(segment_files)
            }
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Video generation error: {e}")
            return None
    
    def analyze_restart_audio(self, video_id: str, segment_files: List[tuple] = None) -> Optional[Dict[str, Any]]:
        """Analyze audio transcript using provided segment files from video generation"""
        try:
            from backend_host.src.controllers.verification.audio_ai_helpers import AudioAIHelpers
            
            # Use provided segment files if available, otherwise scan directory
            if segment_files is None:
                print(f"RestartHelpers[{self.device_name}]: No segment files provided, scanning directory")
                try:
                    # Use centralized storage path utilities for hot/cold architecture
                    from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
                    
                    # Get segments folder using centralized path resolution (handles hot/cold storage)
                    segments_folder = get_capture_storage_path(self.video_capture_path, 'segments')
                    all_segment_paths = get_files_by_pattern(segments_folder, r'^segment_.*\.ts$')
                    all_segment_paths.sort(key=lambda path: os.path.getmtime(path))
                except Exception as e:
                    print(f"RestartHelpers[{self.device_name}]: Error finding segments: {e}")
                    all_segment_paths = []
                
                segments_needed = int(10.0 / self.HLS_SEGMENT_DURATION) + 2
                segment_files = [(os.path.basename(p), p) for p in all_segment_paths[-segments_needed:]]
            else:
                print(f"RestartHelpers[{self.device_name}]: Using provided segment files ({len(segment_files)} segments)")
            
            audio_ai = AudioAIHelpers(self.av_controller, f"RestartVideo-{self.device_name}")
            audio_files = audio_ai.extract_audio_from_segments(segment_files, segment_count=len(segment_files))
            
            if not audio_files:
                return {
                    'success': True,
                    'audio_analysis': {
                        'success': True,
                        'speech_detected': False,
                        'combined_transcript': '',
                        'detected_language': 'unknown',
                        'confidence': 0.0
                    }
                }
            
            audio_analysis = audio_ai.analyze_audio_segments_ai(audio_files, upload_to_r2=True, early_stop=True)
            
            return {
                'success': True,
                'audio_analysis': {
                    'success': audio_analysis.get('success', False),
                    'speech_detected': audio_analysis.get('speech_detected', False),
                    'combined_transcript': audio_analysis.get('combined_transcript', ''),
                    'detected_language': audio_analysis.get('detected_language', 'unknown'),
                    'confidence': audio_analysis.get('confidence', 0.0)
                }
            }
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Audio analysis error: {e}")
            return {'success': False, 'error': str(e)}
    
    def analyze_restart_complete(self, video_id: str, screenshot_urls: list) -> Optional[Dict[str, Any]]:
        """
        Combined restart analysis: subtitles + summary in single optimized call
        
        Raises:
            ValueError: If screenshot_urls is empty or invalid
            FileNotFoundError: If screenshot files don't exist
            Exception: If analysis fails
        """
        print(f"[HOST] RestartHelpers[{self.device_name}]: 📊 analyze_restart_complete CALLED for {video_id}")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Screenshot URLs: {len(screenshot_urls)}")
        
        try:
            # Validate inputs
            if not screenshot_urls:
                error_msg = f"No screenshot URLs provided for visual analysis (video_id: {video_id})"
                print(f"[HOST] RestartHelpers[{self.device_name}]: ❌ ERROR: {error_msg}")
                raise ValueError(error_msg)
            
            print(f"[HOST] RestartHelpers[{self.device_name}]: Starting visual analysis with {len(screenshot_urls)} screenshots")
            
            from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
            from backend_host.src.controllers.verification.video import VideoVerificationController
            
            local_paths = [convertHostUrlToLocalPath(url) if url.startswith(('http://', 'https://')) else url for url in screenshot_urls]
            
            # Verify files exist
            missing_files = []
            for i, path in enumerate(local_paths):
                if not os.path.exists(path):
                    missing_files.append((i, path))
            
            if missing_files:
                error_msg = f"Missing {len(missing_files)}/{len(local_paths)} screenshot files for visual analysis"
                print(f"RestartHelpers[{self.device_name}]: ❌ ERROR: {error_msg}")
                for idx, path in missing_files[:3]:  # Show first 3 missing files
                    print(f"RestartHelpers[{self.device_name}]:   - Missing file {idx+1}: {path}")
                if len(missing_files) > 3:
                    print(f"RestartHelpers[{self.device_name}]:   - ... and {len(missing_files)-3} more missing files")
                raise FileNotFoundError(error_msg)
            
            print(f"RestartHelpers[{self.device_name}]: ✓ All {len(local_paths)} screenshot files exist")
            
            video_controller = VideoVerificationController(self.device_name)
            
            # Use the optimized combined analysis for each frame
            frame_subtitles = []
            frame_descriptions = []
            detected_language = 'unknown'
            
            # Process images in batches using global config
            from shared.src.lib.utils.ai_utils import AI_BATCH_CONFIG
            batch_size = AI_BATCH_CONFIG['batch_size']
            for batch_start in range(0, len(local_paths), batch_size):
                batch_end = min(batch_start + batch_size, len(local_paths))
                batch_paths = local_paths[batch_start:batch_end]
                batch_indices = list(range(batch_start, batch_end))
                
                import time
                from datetime import datetime
                batch_start_time = time.time()
                batch_num = batch_start//batch_size + 1
                readable_time = datetime.fromtimestamp(batch_start_time).strftime('%H:%M:%S')
                
                print(f"RestartHelpers[{self.device_name}]: 🚀 BATCH_{batch_num}_START: time={readable_time} frames={batch_start+1}-{batch_end} images={len(batch_paths)}")
                
                # Batch AI call for multiple images
                batch_result = video_controller.analyze_image_batch_complete(batch_paths, extract_text=True, include_description=True)
                
                batch_duration = time.time() - batch_start_time
                if batch_result and batch_result.get('success'):
                    print(f"RestartHelpers[{self.device_name}]: ✅ BATCH_{batch_num}_SUCCESS: duration={batch_duration:.2f}s frames={batch_start+1}-{batch_end} processed={len(batch_result.get('frame_results', []))}")
                else:
                    print(f"RestartHelpers[{self.device_name}]: ❌ BATCH_{batch_num}_FAILED: duration={batch_duration:.2f}s frames={batch_start+1}-{batch_end} error={batch_result.get('error', 'unknown')}")
                
                if batch_result and batch_result.get('success'):
                    # Process each frame result from the batch
                    frame_results = batch_result.get('frame_results', [])
                    
                    for idx, (i, frame_result) in enumerate(zip(batch_indices, frame_results)):
                        if frame_result and frame_result.get('success'):
                            # Extract subtitle data
                            subtitle_data = frame_result.get('subtitle_analysis', {})
                            text = subtitle_data.get('combined_extracted_text', '').strip()
                            frame_text = text if text and text != 'No subtitles detected' else 'No subtitles detected'
                            frame_subtitles.append(f"Frame {i+1}: {frame_text}")
                            
                            # Update detected language from first successful detection
                            if detected_language == 'unknown' and subtitle_data.get('detected_language'):
                                detected_language = subtitle_data.get('detected_language')
                            
                            # Extract description data
                            description_data = frame_result.get('description_analysis', {})
                            description = description_data.get('response', '').strip()
                            if description and description != 'No description available':
                                frame_descriptions.append(f"Frame {i+1}: {description}")
                            else:
                                frame_descriptions.append(f"Frame {i+1}: No description available")
                        else:
                            frame_subtitles.append(f"Frame {i+1}: No subtitles detected")
                            frame_descriptions.append(f"Frame {i+1}: No description available")
                else:
                    # Batch failed - add empty results for all frames in batch
                    for i in batch_indices:
                        frame_subtitles.append(f"Frame {i+1}: No subtitles detected")
                        frame_descriptions.append(f"Frame {i+1}: No description available")
            
            # Generate video summary from frame descriptions
            if frame_descriptions:
                summary_query = f"Based on the {len(frame_descriptions)} frame descriptions, provide a concise summary of what happened in this video sequence."
                video_summary = video_controller.analyze_image_with_ai(local_paths[0], summary_query) if local_paths else "No video description available"
                if not video_summary or not video_summary.strip():
                    video_summary = f"Video sequence showing {len(frame_descriptions)} frames of activity"
            else:
                video_summary = "No video description available"
            
            # Combine subtitle analysis results
            subtitle_analysis = {
                'success': True,
                'subtitles_detected': any('No subtitles detected' not in fs for fs in frame_subtitles),
                'extracted_text': ' '.join([fs.split(': ', 1)[1] for fs in frame_subtitles if 'No subtitles detected' not in fs]),
                'detected_language': detected_language,
                'frame_subtitles': frame_subtitles
            }
            
            # Combine video analysis results
            video_analysis = {
                'success': True,
                'frame_descriptions': frame_descriptions,
                'video_summary': video_summary.strip(),
                'frames_analyzed': len(local_paths)
            }
            
            print(f"RestartHelpers[{self.device_name}]: ✅ Visual analysis completed successfully")
            print(f"RestartHelpers[{self.device_name}]:   - Frames analyzed: {len(local_paths)}")
            print(f"RestartHelpers[{self.device_name}]:   - Subtitles detected: {subtitle_analysis['subtitles_detected']}")
            print(f"RestartHelpers[{self.device_name}]:   - Language: {detected_language}")
            
            return {
                'success': True,
                'subtitle_analysis': subtitle_analysis,
                'video_analysis': video_analysis
            }
            
        except (ValueError, FileNotFoundError) as e:
            # Re-raise validation errors so they bubble up with proper context
            print(f"RestartHelpers[{self.device_name}]: ❌ VALIDATION ERROR: {e}")
            raise
        except Exception as e:
            error_msg = f"Visual analysis failed unexpectedly: {str(e)}"
            print(f"RestartHelpers[{self.device_name}]: ❌ FATAL ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            raise Exception(error_msg) from e
    
    def generate_restart_video(self, duration_seconds: float = None, test_start_time: float = None, processing_time: float = None) -> Optional[Dict[str, Any]]:
        """
        Generate restart video - returns video URL + audio analysis only.
        Shows player immediately while AI analysis runs in background.
        """
        try:
            if duration_seconds is None:
                duration_seconds = 10.0
                
            print(f"RestartHelpers[{self.device_name}]: Compressing {duration_seconds}s HLS video to MP4")
            
            # Use centralized storage path utilities for hot/cold architecture
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            
            # Find the M3U8 file using centralized path resolution
            segments_folder = get_capture_storage_path(self.video_capture_path, 'segments')
            m3u8_path = os.path.join(segments_folder, "output.m3u8")
            
            if not os.path.exists(m3u8_path):
                print(f"RestartHelpers[{self.device_name}]: No M3U8 file found at {m3u8_path}")
                return None
            
            # Wait for encoder to finish
            if test_start_time:
                print(f"RestartHelpers[{self.device_name}]: Waiting 5s for final segments to complete...")
                time.sleep(5)
            
            # Get segment files
            segment_files = self._get_recent_segments(duration_seconds)
            if not segment_files:
                print(f"RestartHelpers[{self.device_name}]: No video segments found")
                return None
            
            # Compress HLS segments to MP4
            from  backend_host.src.lib.utils.video_compression_utils import VideoCompressionUtils
            compressor = VideoCompressionUtils()
            
            # Get correct path for video file (handles hot/cold storage)
            video_filename = "restart_original_video.mp4"
            local_video_path = self._get_restart_video_path(video_filename)
            
            compression_result = compressor.compress_hls_to_mp4(
                m3u8_path=m3u8_path,
                segment_files=segment_files,
                output_path=local_video_path,
                compression_level="low"
            )
            
            if not compression_result['success']:
                print(f"RestartHelpers[{self.device_name}]: Video compression failed: {compression_result['error']}")
                return None
            
            print(f"RestartHelpers[{self.device_name}]: Compression complete - {compression_result['compression_ratio']:.1f}% size reduction")
            
            # Build video URL
            video_url = self._build_video_url(video_filename)
            
            # Get screenshot URLs aligned with video segments
            screenshot_urls = self._get_video_screenshots(segment_files)
            
            # Generate unique video ID
            video_id = f"restart_{int(time.time())}_{str(uuid.uuid4())[:8]}"
            
            analysis_data = {
                'audio_analysis': {
                    'success': False,
                    'pending': True,
                    'message': 'Audio analysis will be performed asynchronously'
                },
                'screenshot_urls': screenshot_urls,
                'video_analysis': {
                    'success': False,
                    'pending': True,
                    'message': 'Video analysis will be performed asynchronously'
                },
                'subtitle_analysis': {
                    'success': False,
                    'pending': True,
                    'message': 'Subtitle analysis will be performed asynchronously'
                },
                'video_id': video_id,
                'segment_count': len(segment_files),
                'segment_files': segment_files,
                'analysis_complete': False,
                'timestamp': time.time(),
                'created_at': datetime.now().isoformat()
            }
            
            print(f"RestartHelpers[{self.device_name}]: Fast generation complete - Video ID: {video_id}")
            
            # Start background processing
            threading.Thread(target=self._bg_process, args=(video_id, segment_files, screenshot_urls, duration_seconds), daemon=True).start()
            
            return {
                'success': True,
                'video_url': video_url,
                'analysis_data': analysis_data
            }
                
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Error generating fast restart video: {e}")
            return None
    
    def _get_recent_segments(self, duration_seconds: float) -> List[Tuple[str, str]]:
        """Get recent HLS segments for the specified duration"""
        try:
            # Use centralized storage path utilities for hot/cold architecture
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            
            # Get segments folder using centralized path resolution (handles hot/cold storage)
            segments_folder = get_capture_storage_path(self.video_capture_path, 'segments')
            
            # Get segments using fast os.scandir (no subprocess overhead)
            all_segment_paths = get_files_by_pattern(segments_folder, r'^segment_.*\.ts$')
            
            # Sort by file modification time
            all_segment_paths.sort(key=lambda path: os.path.getmtime(path))
            
            # Convert to (filename, filepath) tuples
            all_segments = []
            for segment_path in all_segment_paths:
                if os.path.exists(segment_path):
                    filename = os.path.basename(segment_path)
                    all_segments.append((filename, segment_path))
            
            # Calculate segments needed
            segments_needed = int(duration_seconds / self.HLS_SEGMENT_DURATION) + 2
            
            if len(all_segments) < segments_needed:
                segment_files = all_segments
                actual_duration = len(all_segments) * self.HLS_SEGMENT_DURATION
                print(f"RestartHelpers[{self.device_name}]: Only {len(all_segments)} segments available ({actual_duration}s), using all")
            else:
                segment_files = all_segments[-segments_needed:]
                print(f"RestartHelpers[{self.device_name}]: Taking last {segments_needed} segments ({duration_seconds}s)")
            
            return segment_files
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Error getting recent segments: {e}")
            return []
    
    def _build_video_url(self, video_filename: str) -> str:
        """
        Build proper video URL using host URL building utilities.
        Handles hot/cold storage architecture automatically.
        
        Args:
            video_filename: Name of the video file (used for fallback URL only)
        """
        try:
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from  backend_host.src.lib.utils.host_utils import get_host_instance
            
            # Get correct path considering hot/cold storage
            local_video_path = self._get_restart_video_path(video_filename)
            host = get_host_instance()
            video_url = buildHostImageUrl(host.to_dict(), local_video_path)
            return video_url
        except Exception:
            # Fallback to stream path
            return self.video_stream_path + "/" + video_filename
    
    def _get_aligned_screenshots(self, segment_files: List[Tuple[str, str]]) -> List[str]:
        """
        Get screenshots aligned with video segments using simple timestamp-based approach.
        
        Logic:
        1. Get start/end time from first/last segment
        2. Filter screenshots by timestamp (only those in time window)
        3. Sort by timestamp (chronological order)
        4. Pick every Nth frame (1 per second) based on FPS
        """
        try:
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            
            if not segment_files:
                print(f"RestartHelpers[{self.device_name}]: ❌ No segment files provided")
                return []
            
            # Get time window from segments
            video_start_time = os.path.getmtime(segment_files[0][1])
            video_end_time = os.path.getmtime(segment_files[-1][1])
            video_duration = video_end_time - video_start_time
            
            print(f"RestartHelpers[{self.device_name}]: 🔍 Getting screenshots for {len(segment_files)}s video")
            print(f"RestartHelpers[{self.device_name}]:   - Start: {datetime.fromtimestamp(video_start_time).strftime('%H:%M:%S')}")
            print(f"RestartHelpers[{self.device_name}]:   - End: {datetime.fromtimestamp(video_end_time).strftime('%H:%M:%S')}")
            print(f"RestartHelpers[{self.device_name}]:   - Duration: {video_duration:.1f}s")
            
            # Get captures folder using centralized path resolution
            capture_folder = get_capture_storage_path(self.video_capture_path, 'captures')
            print(f"RestartHelpers[{self.device_name}]:   - Scanning: {capture_folder}")
            
            # Get all screenshots in hot storage
            all_screenshots = get_files_by_pattern(capture_folder, r'^capture_.*\.jpg$', exclude_pattern=r'_thumbnail\.jpg$')
            
            if not all_screenshots:
                print(f"RestartHelpers[{self.device_name}]: ❌ No screenshots found in hot storage")
                return []
            
            print(f"RestartHelpers[{self.device_name}]: 📸 Found {len(all_screenshots)} total screenshots in hot storage")
            
            # Filter: Only screenshots within video time window
            screenshots_in_window = []
            for screenshot_path in all_screenshots:
                screenshot_time = os.path.getmtime(screenshot_path)
                if video_start_time <= screenshot_time <= video_end_time:
                    screenshots_in_window.append(screenshot_path)
            
            if not screenshots_in_window:
                print(f"RestartHelpers[{self.device_name}]: ❌ No screenshots found in time window")
                print(f"RestartHelpers[{self.device_name}]:   - This shouldn't happen - screenshots may have been archived")
                return []
            
            # Sort by timestamp (chronological order)
            screenshots_in_window.sort(key=lambda p: os.path.getmtime(p))
            
            print(f"RestartHelpers[{self.device_name}]: ✅ Found {len(screenshots_in_window)} screenshots in time window")
            print(f"RestartHelpers[{self.device_name}]:   - First: {os.path.basename(screenshots_in_window[0])}")
            print(f"RestartHelpers[{self.device_name}]:   - Last: {os.path.basename(screenshots_in_window[-1])}")
            
            # Sample: 1 screenshot per second (every FPS frames)
            fps = getattr(self.av_controller, 'screenshot_fps', 5)
            selected_screenshots = screenshots_in_window[::fps]  # Every 5th frame
            
            # Ensure we don't exceed the number of segments
            screenshots_needed = len(segment_files)
            if len(selected_screenshots) > screenshots_needed:
                selected_screenshots = selected_screenshots[:screenshots_needed]
            
            print(f"RestartHelpers[{self.device_name}]: 🎯 Selected {len(selected_screenshots)} screenshots (1 per second, FPS={fps})")
            
            if len(selected_screenshots) < screenshots_needed:
                print(f"RestartHelpers[{self.device_name}]: ⚠️  Only {len(selected_screenshots)}/{screenshots_needed} screenshots available")
            
            # Convert to URLs
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from backend_host.src.lib.utils.host_utils import get_host_instance
            
            screenshot_urls = []
            try:
                host = get_host_instance()
                host_dict = host.to_dict()
                
                for screenshot_path in selected_screenshots:
                    screenshot_url = buildHostImageUrl(host_dict, screenshot_path)
                    screenshot_urls.append(screenshot_url)
                    
                print(f"RestartHelpers[{self.device_name}]: ✅ Generated {len(screenshot_urls)} screenshot URLs")
                
            except Exception as e:
                print(f"RestartHelpers[{self.device_name}]: ❌ URL generation failed: {e}")
                return []
            
            return screenshot_urls
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: ❌ Screenshot collection EXCEPTION: {e}")
            import traceback
            print(f"RestartHelpers[{self.device_name}]: 🔍 Full traceback:")
            print(traceback.format_exc())
            return []
    
    def _get_audio_transcript_locally(self, segment_files: List[Tuple[str, str]], duration_seconds: float) -> Dict[str, Any]:
        """Get audio transcript locally by extracting from the already-created MP4 video (no double merging)"""
        try:
            from backend_host.src.controllers.verification.audio_ai_helpers import AudioAIHelpers
            import subprocess
            import tempfile
            
            audio_ai = AudioAIHelpers(self.av_controller, f"RestartVideo-{self.device_name}")
            
            print(f"RestartHelpers[{self.device_name}]: Extracting audio from existing MP4 video (avoiding double merge)")
            
            # Extract audio directly from the already-created MP4 video (use correct path)
            video_file = self._get_restart_video_path("restart_original_video.mp4")
            
            if not os.path.exists(video_file):
                print(f"RestartHelpers[{self.device_name}]: MP4 video not found, falling back to segment merging")
                audio_files = audio_ai.extract_audio_from_segments(segment_files, segment_count=len(segment_files))
            else:
                # Extract audio from MP4 (much faster than merging TS segments again)
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_audio:
                    temp_audio_path = temp_audio.name
                
                print(f"RestartHelpers[{self.device_name}]: Extracting audio from MP4: {video_file}")
                subprocess.run([
                    'ffmpeg', '-i', video_file, 
                    '-vn', '-acodec', 'pcm_s16le', 
                    '-ar', '16000', '-ac', '1',  # 16kHz mono for faster Whisper processing
                    temp_audio_path, '-y'
                ], capture_output=True, check=True)
                
                audio_files = [temp_audio_path]
            
            if not audio_files:
                return {
                    'success': True,
                    'speech_detected': False,
                    'combined_transcript': '',
                    'detected_language': 'unknown',
                    'confidence': 0.0,
                    'segments_analyzed': 0
                }
            
            # Analyze with AI (AudioAIHelpers handles cleanup automatically)
            audio_analysis = audio_ai.analyze_audio_segments_ai(audio_files, upload_to_r2=True, early_stop=True)
            
            if not audio_analysis.get('success'):
                return {
                    'success': False,
                    'speech_detected': False,
                    'combined_transcript': '',
                    'detected_language': 'unknown',
                    'confidence': 0.0,
                    'segments_analyzed': 0
                }
            
            return {
                'success': True,
                'speech_detected': audio_analysis.get('successful_segments', 0) > 0,
                'combined_transcript': audio_analysis.get('combined_transcript', ''),
                'detected_language': audio_analysis.get('detected_language', 'unknown'),
                'confidence': audio_analysis.get('confidence', 0.0),
                'segments_analyzed': audio_analysis.get('segments_analyzed', 0)
            }
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Audio analysis error: {e}")
            return {
                'success': False,
                'speech_detected': False,
                'combined_transcript': '',
                'detected_language': 'unknown',
                'confidence': 0.0,
                'segments_analyzed': 0,
                'error': str(e)
            }
    
    def _get_video_screenshots(self, segment_files: List[Tuple[str, str]]) -> List[str]:
        """Get screenshot URLs aligned with video segments"""
        return self._get_aligned_screenshots(segment_files)
    
    @property
    def dubbing_helpers(self):
        """Lazy initialization of dubbing helpers"""
        if self._dubbing_helpers is None:
            from .audio_dubbing_helpers import AudioDubbingHelpers
            self._dubbing_helpers = AudioDubbingHelpers(self.av_controller, self.device_name)
        return self._dubbing_helpers
    
    
    def _clean_translated_text(self, translated_text: str) -> str:
        """Clean translated text by removing AI prompt artifacts."""
        if not translated_text:
            return ""
        
        # Remove common AI prompt prefixes
        prefixes_to_remove = [
            "FRAME_STRUCTURE_TRANSLATION:",
            "FRAME_STRUCTURE_TRANSLATION",
            "Translated content:",
            "Translation:",
            "Here is the translation:",
            "The translation is:",
        ]
        
        cleaned_text = translated_text.strip()
        
        # Remove prefixes
        for prefix in prefixes_to_remove:
            if cleaned_text.startswith(prefix):
                cleaned_text = cleaned_text[len(prefix):].strip()
                break
        
        # Remove any leading/trailing quotes or formatting
        cleaned_text = cleaned_text.strip('"\'`')
        
        return cleaned_text
    
    # =============================================================================
    # 4-Step Dubbing Process Methods
    # =============================================================================
    
    def prepare_dubbing_audio(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Step 1: Prepare audio for dubbing (extract + separate)"""
        try:
            # Get correct path for video file (handles hot/cold storage)
            video_file = self._get_restart_video_path("restart_original_video.mp4")
            
            if not os.path.exists(video_file):
                return {
                    'success': False,
                    'error': f'Video file not found: {video_file}',
                    'duration_seconds': 0.0
                }
            
            # Pass storage-aware base directory to dubbing helpers (includes /hot/ if RAM mode)
            return self.dubbing_helpers.prepare_dubbing_audio(video_file, self._get_storage_aware_base_dir())
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Audio preparation error: {e}")
            return {
                'success': False,
                'error': f'Audio preparation failed: {str(e)}',
                'duration_seconds': 0.0
            }
    
    
    def generate_edge_speech(self, video_id: str, target_language: str, existing_transcript: str) -> Optional[Dict[str, Any]]:
        """Step 2: Generate Edge-TTS speech"""
        try:
            # Get translation (cached if available)
            cache_key = video_id
            if cache_key in self._translation_cache and target_language in self._translation_cache[cache_key]:
                translation_result = self._translation_cache[cache_key][target_language]
            else:
                # For audio dubbing, translate the clean transcript directly (no frame structure)
                # Use the same Google Translate approach as batch translation (which works)
                # Use AI translation for audio transcript (more accurate than Google Translate)
                from  backend_host.src.lib.utils.translation_utils import translate_text
                # Auto-detect source language for translation
                detected_language = 'auto'
                translation_result = translate_text(existing_transcript, detected_language, target_language, method='ai')
                print(f"RestartHelpers[{self.device_name}]: AI translation completed for audio transcript ({detected_language} → {target_language})")
                
                if not translation_result['success']:
                    return {
                        'success': False,
                        'error': 'Translation failed',
                        'duration_seconds': 0.0
                    }
                
                # Cache the translation
                if cache_key not in self._translation_cache:
                    self._translation_cache[cache_key] = {}
                self._translation_cache[cache_key][target_language] = translation_result
            
            # Clean translated text before TTS (remove AI prompt artifacts)
            translated_text = self._clean_translated_text(translation_result['translated_text'])
            
            # Pass storage-aware base directory to dubbing helpers (includes /hot/ if RAM mode)
            return self.dubbing_helpers.generate_edge_speech(translated_text, target_language, self._get_storage_aware_base_dir())
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Edge-TTS generation error: {e}")
            return {
                'success': False,
                'error': f'Edge-TTS generation failed: {str(e)}',
                'duration_seconds': 0.0
            }
    
    def create_dubbed_video(self, video_id: str, target_language: str, voice_choice: str = 'edge') -> Optional[Dict[str, Any]]:
        """Step 3: Create final dubbed video"""
        try:
            # Get correct path for video file (handles hot/cold storage)
            video_file = self._get_restart_video_path("restart_original_video.mp4")
            
            if not os.path.exists(video_file):
                return {
                    'success': False,
                    'error': f'Video file not found: {video_file}',
                    'duration_seconds': 0.0
                }
            
            return self.dubbing_helpers.create_dubbed_video(video_file, target_language, voice_choice)
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Video creation error: {e}")
            return {
                'success': False,
                'error': f'Video creation failed: {str(e)}',
                'duration_seconds': 0.0
            }
    
    def create_dubbed_video_fast(self, video_id: str, target_language: str, existing_transcript: str) -> Optional[Dict[str, Any]]:
        """NEW: Fast 2-step dubbing process"""
        try:
            # Get correct path for video file (handles hot/cold storage)
            video_file = self._get_restart_video_path("restart_original_video.mp4")
            
            if not os.path.exists(video_file):
                return {
                    'success': False,
                    'error': f'Video file not found: {video_file}',
                    'duration_seconds': 0.0
                }
            
            print(f"RestartHelpers[{self.device_name}]: Starting fast dubbing for {target_language}")
            
            # existing_transcript should already be translated by frontend
            # Clean the text before TTS (remove AI prompt artifacts)
            translated_text = self._clean_translated_text(existing_transcript)
            print(f"RestartHelpers[{self.device_name}]: Using provided translated transcript for {target_language}")
            
            # Call complete dubbing method (combines Edge-TTS generation + video creation)
            # Pass storage-aware base directory to dubbing helpers (includes /hot/ if RAM mode)
            return self.dubbing_helpers.create_dubbed_video_complete(
                translated_text, target_language, video_file, self._get_storage_aware_base_dir()
            )
            
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Complete dubbing error: {e}")
            return {
                'success': False,
                'error': f'Complete dubbing failed: {str(e)}',
                'duration_seconds': 0.0
            }
    
    def adjust_video_audio_timing(self, video_url: str, timing_offset_ms: int, language: str = "original", 
                                 silent_video_path: str = None, background_audio_path: str = None, 
                                 vocals_path: str = None) -> Optional[Dict[str, Any]]:
        """
        Adjust audio timing for existing restart video using FFmpeg with smart caching.
        
        Args:
            video_url: URL or path to existing video
            timing_offset_ms: Timing offset in milliseconds (+delay, -advance)
            language: Language identifier ("original" or language code like "es", "fr")
            
        Returns:
            Dictionary with adjusted video information
        """
        try:
            
            # Convert URL to local path if needed
            from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
            if video_url.startswith(('http://', 'https://')):
                video_file = convertHostUrlToLocalPath(video_url)
            else:
                video_file = video_url
            
            if not os.path.exists(video_file):
                print(f"RestartHelpers[{self.device_name}]: Video file not found: {video_file}")
                return None
            
            # Parse current filename to extract base name and current timing offset
            original_dir = os.path.dirname(video_file)
            original_filename = os.path.basename(video_file)
            original_name, original_ext = os.path.splitext(original_filename)
            
            # Extract base name and current timing from filename
            base_name, current_timing_ms = self._parse_timing_filename(original_name)
            
            # Calculate target timing (absolute timing relative to original)
            target_timing_ms = current_timing_ms + timing_offset_ms
            
            print(f"RestartHelpers[{self.device_name}]: Current timing: {current_timing_ms:+d}ms, Requested: {timing_offset_ms:+d}ms, Target: {target_timing_ms:+d}ms")
            
            # Special handling for 0ms - always return original video without processing
            if target_timing_ms == 0:
                # Check what original video exists (could be any language)
                original_base_filename = f"{base_name}{original_ext}"  # restart_original_video.mp4
                original_base_path = os.path.join(original_dir, original_base_filename)
                
                # Check for dubbed video for this language
                dubbed_filename = f"restart_{language}_dubbed_video{original_ext}"  # restart_fr_dubbed_video.mp4
                dubbed_path = os.path.join(original_dir, dubbed_filename)
                
                # Priority: Use dubbed video if it exists for this language, otherwise use original
                if os.path.exists(dubbed_path):
                    output_filename = dubbed_filename
                    output_path = dubbed_path
                    print(f"RestartHelpers[{self.device_name}]: Target timing is 0ms - using original {language} dubbed video")
                elif os.path.exists(original_base_path):
                    output_filename = original_base_filename
                    output_path = original_base_path
                    print(f"RestartHelpers[{self.device_name}]: Target timing is 0ms - using original base video (first generated)")
                else:
                    print(f"RestartHelpers[{self.device_name}]: 0ms video not found - neither {dubbed_filename} nor {original_base_filename} exist")
                    return {
                        'success': False,
                        'error': f'No original video found for {language}',
                        'timing_offset_ms': 0
                    }
                
                # Return immediately - no processing needed for 0ms
                adjusted_video_url = self._build_video_url(output_filename)
                return {
                    'success': True,
                    'adjusted_video_url': adjusted_video_url,
                    'timing_offset_ms': 0,
                    'language': language,
                    'video_id': f"restart_{int(time.time())}_{language}_original",
                    'original_video_url': video_url
                }
            
            # For non-zero timing: generate sync-adjusted filename
            if target_timing_ms > 0:
                sync_suffix = f"_syncp{target_timing_ms}"
            else:
                sync_suffix = f"_syncm{abs(target_timing_ms)}"
            
            # Check what base video to use for sync adjustment
            dubbed_filename = f"restart_{language}_dubbed_video{original_ext}"
            dubbed_path = os.path.join(original_dir, dubbed_filename)
            
            if os.path.exists(dubbed_path):
                # Use dubbed video as base for sync adjustment
                output_filename = f"restart_{language}_dubbed_video{sync_suffix}{original_ext}"  # restart_fr_dubbed_video_syncp200.mp4
            else:
                # Use original base video for sync adjustment
                output_filename = f"{base_name}{sync_suffix}{original_ext}"  # restart_original_video_syncp200.mp4
            
            output_path = os.path.join(original_dir, output_filename)
            
            
            # Use component-based timing adjustment
            return self._adjust_timing_with_components(
                original_dir, base_name, original_ext, target_timing_ms, language, output_path, output_filename, video_url,
                silent_video_path, background_audio_path, vocals_path
            )
            
        except subprocess.CalledProcessError as e:
            print(f"RestartHelpers[{self.device_name}]: FFmpeg timing adjustment failed: {e.stderr}")
            return None
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Audio timing adjustment error: {e}")
            return None
    
    def _adjust_timing_with_components(self, original_dir: str, base_name: str, original_ext: str, 
                                     target_timing_ms: int, language: str, output_path: str, 
                                     output_filename: str, video_url: str,
                                     silent_video_path: str = None, background_audio_path: str = None, 
                                     vocals_path: str = None) -> Optional[Dict[str, Any]]:
        """
        Simple timing adjustment.
        """
        print(f"RestartHelpers[{self.device_name}]: Using simplified sync - delegating to dubbing helpers")
        return self._sync_using_dubbing_helpers(target_timing_ms, language, original_dir, video_url)
    
    def _sync_using_dubbing_helpers(self, target_timing_ms: int, language: str, original_dir: str, video_url: str) -> Optional[Dict[str, Any]]:
        """
        Use dubbing helpers sync method - no duplicate code.
        """
        try:
            # Use the dubbing helpers sync method
            sync_result = self.dubbing_helpers.sync_dubbed_video(language, target_timing_ms, original_dir)
            
            if sync_result.get('success'):
                # Convert dubbing helpers response to video restart helpers format
                video_id = f"restart_{int(time.time())}_{language}_timing_{target_timing_ms:+d}ms"
                
                return {
                    'success': True,
                    'adjusted_video_url': sync_result['synced_video_url'],
                    'timing_offset_ms': target_timing_ms,
                    'language': language,
                    'video_id': video_id,
                    'original_video_url': video_url,
                    'method': 'dubbing_helpers_sync'
                }
            else:
                return {
                    'success': False,
                    'error': sync_result.get('error', 'Sync failed'),
                    'timing_offset_ms': target_timing_ms,
                    'language': language
                }
                
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Dubbing helpers sync failed: {e}")
            return None
    
    def _create_components_from_source(self, source_video_path: str, original_dir: str) -> bool:
        """
        Create only silent video, no audio separation.
        All audio processing is handled by AudioDubbingHelpers.
        """
        try:
            if not os.path.exists(source_video_path):
                print(f"RestartHelpers[{self.device_name}]: Source video not found: {source_video_path}")
                return False
            
            print(f"RestartHelpers[{self.device_name}]: Creating silent video component from: {source_video_path}")
            
            # Only create silent video - no audio processing
            silent_video_path = os.path.join(original_dir, "restart_video_no_audio.mp4")
            
            if not os.path.exists(silent_video_path):
                print(f"RestartHelpers[{self.device_name}]: Extracting silent video...")
                silent_cmd = [
                    'ffmpeg', '-i', source_video_path,
                    '-c:v', 'copy',  # Copy video unchanged
                    '-an',           # Remove audio track
                    silent_video_path, '-y'
                ]
                subprocess.run(silent_cmd, capture_output=True, text=True, check=True)
                print(f"RestartHelpers[{self.device_name}]: Silent video created: {silent_video_path}")
            else:
                print(f"RestartHelpers[{self.device_name}]: Silent video already exists")
            
            return True
                
        except Exception as e:
            print(f"RestartHelpers[{self.device_name}]: Error creating silent video: {e}")
            return False
    
    def _parse_timing_filename(self, filename: str) -> Tuple[str, int]:
        """
        Parse filename to extract base name and current timing offset.
        
        Each file represents absolute timing relative to original:
        - "restart_fr_dubbed_video" → ("restart_fr_dubbed_video", 0)
        - "restart_fr_dubbed_video_syncp200" → ("restart_fr_dubbed_video", 200)
        - "restart_fr_dubbed_video_syncm100" → ("restart_fr_dubbed_video", -100)
        
        Args:
            filename: Filename without extension
            
        Returns:
            Tuple of (base_name, current_timing_ms)
        """
        import re
        
        # Look for single timing suffix (should only be one per file)
        timing_pattern = r'_sync([pm])(\d+)$'
        match = re.search(timing_pattern, filename)
        
        if not match:
            # No timing suffix found - this is the original file
            return filename, 0
        
        # Extract timing from the single suffix
        sign, value = match.groups()
        timing_ms = int(value)
        if sign == 'm':  # negative
            timing_ms = -timing_ms
        
        # Extract base name by removing the timing suffix
        base_name = re.sub(timing_pattern, '', filename)
        
        return base_name, timing_ms
    
    # =============================================================================
    # Background Processing Methods
    # =============================================================================
    
    def _bg_process(self, video_id: str, segment_files: List[tuple], screenshot_urls: List[str], duration_seconds: float) -> None:
        """Start 3 parallel threads"""
        print(f"[HOST] RestartHelpers[{self.device_name}]: 🚀 BACKGROUND PROCESS STARTING for {video_id}")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Segment files: {len(segment_files) if segment_files else 0}")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Screenshot URLs: {len(screenshot_urls) if screenshot_urls else 0}")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Duration: {duration_seconds}s")
        
        if screenshot_urls:
            print(f"[HOST] RestartHelpers[{self.device_name}]:   - First screenshot URL: {screenshot_urls[0]}")
            print(f"[HOST] RestartHelpers[{self.device_name}]:   - Last screenshot URL: {screenshot_urls[-1]}")
        else:
            print(f"[HOST] RestartHelpers[{self.device_name}]:   - ❌ WARNING: No screenshot URLs provided!")
        
        self._save_status(video_id, {'audio': 'loading', 'visual': 'loading', 'heavy': 'loading'})
        
        print(f"[HOST] RestartHelpers[{self.device_name}]: 🧵 Starting audio thread...")
        threading.Thread(target=self._t1_audio, args=(video_id, segment_files, duration_seconds), daemon=True).start()
        
        print(f"[HOST] RestartHelpers[{self.device_name}]: 🧵 Starting visual thread...")
        threading.Thread(target=self._t2_visual, args=(video_id, screenshot_urls), daemon=True).start()
        
        print(f"[HOST] RestartHelpers[{self.device_name}]: 🧵 Starting heavy thread...")
        threading.Thread(target=self._t3_heavy, args=(video_id,), daemon=True).start()
        
        print(f"[HOST] RestartHelpers[{self.device_name}]: ✅ All background threads launched for {video_id}")
    
    def _t1_audio(self, video_id: str, segment_files: List[tuple], duration_seconds: float) -> None:
        """Thread 1: Audio analysis"""
        try:
            audio_result = self._get_audio_transcript_locally(segment_files, duration_seconds)
            self._save_status(video_id, {'audio': 'completed', 'audio_data': audio_result})
        except Exception as e:
            self._save_status(video_id, {'audio': 'error', 'audio_error': str(e)})
    
    def _t2_visual(self, video_id: str, screenshot_urls: List[str]) -> None:
        """
        Thread 2: Visual analysis
        
        Catches exceptions and saves error status for polling to detect
        """
        print(f"[HOST] RestartHelpers[{self.device_name}]: 🎬 _t2_visual THREAD STARTED for {video_id}")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Thread is running")
        print(f"[HOST] RestartHelpers[{self.device_name}]:   - Screenshot URLs received: {len(screenshot_urls) if screenshot_urls else 0}")
        
        try:
            print(f"[HOST] RestartHelpers[{self.device_name}]: 🎬 Starting visual analysis for {video_id}")
            print(f"[HOST] RestartHelpers[{self.device_name}]:   - Screenshot URLs: {len(screenshot_urls)}")
            
            # Validate inputs before starting
            if not screenshot_urls:
                raise ValueError(f"No screenshot URLs provided for visual analysis")
            
            # Run analysis (this will raise exceptions on failure)
            result = self.analyze_restart_complete(video_id, screenshot_urls)
            
            # Check if result is valid
            if not result:
                raise Exception("analyze_restart_complete returned None")
            
            if not result.get('success'):
                error = result.get('error', 'Unknown error')
                raise Exception(f"Visual analysis returned failure: {error}")
            
            # Success - save results
            print(f"RestartHelpers[{self.device_name}]: ✅ Visual analysis completed successfully for {video_id}")
            self._save_status(video_id, {
                'visual': 'completed',
                'subtitle_analysis': result.get('subtitle_analysis'),
                'video_analysis': result.get('video_analysis')
            })
            
        except ValueError as e:
            # Input validation error
            error_msg = f"Visual analysis validation failed: {str(e)}"
            print(f"RestartHelpers[{self.device_name}]: ❌ VALIDATION ERROR for {video_id}: {error_msg}")
            self._save_status(video_id, {
                'visual': 'error',
                'visual_error': error_msg,
                'error_type': 'validation_error'
            })
            
        except FileNotFoundError as e:
            # Screenshot files missing
            error_msg = f"Screenshot files not found: {str(e)}"
            print(f"RestartHelpers[{self.device_name}]: ❌ FILE ERROR for {video_id}: {error_msg}")
            self._save_status(video_id, {
                'visual': 'error',
                'visual_error': error_msg,
                'error_type': 'file_not_found'
            })
            
        except Exception as e:
            # Unexpected error
            error_msg = f"Visual analysis failed: {str(e)}"
            print(f"RestartHelpers[{self.device_name}]: ❌ FATAL ERROR for {video_id}: {error_msg}")
            import traceback
            traceback.print_exc()
            self._save_status(video_id, {
                'visual': 'error',
                'visual_error': error_msg,
                'error_type': 'unexpected_error'
            })
    
    def _t3_heavy(self, video_id: str) -> None:
        """Thread 3: Audio preparation only (dubbing/sync on-demand)"""
        try:
            # Audio prep - prepare for future dubbing operations
            self._save_status(video_id, {'heavy': 'audio_prep'})
            result = self.prepare_dubbing_audio(video_id)
            
            if result.get('success'):
                self._save_status(video_id, {'heavy': 'completed', 'message': 'Audio prepared for dubbing'})
            else:
                raise Exception("Audio prep failed")
                
        except Exception as e:
            self._save_status(video_id, {'heavy': 'error', 'heavy_error': str(e)})
    
    def _save_status(self, video_id: str, update: Dict) -> None:
        """Save status for polling"""
        file_path = os.path.join(self._status_dir, f"{video_id}.json")
        status = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    status = json.load(f)
            except:
                pass
        status.update(update)
        status['updated'] = time.time()
        with open(file_path, 'w') as f:
            json.dump(status, f)
    
    def get_status(self, video_id: str) -> Dict:
        """Get status for polling"""
        file_path = os.path.join(self._status_dir, f"{video_id}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {'error': 'not_found'}