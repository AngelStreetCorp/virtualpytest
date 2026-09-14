"""
VirtualPyTest Controller Base Classes

to bMinimal base controller with only basic connection state.
Controllers implement their own specific functionality.
"""

from typing import Dict, Any, Optional, List, Tuple
import time

class BaseController:
    """
    Minimal base controller with just connection state.
    Controllers implement their own specific methods as needed.
    """
    
    def __init__(self, controller_type: str, device_name: str = "Unknown Device"):
        self.controller_type = controller_type
        self.device_name = device_name
        self.is_connected = False
    
    def connect(self) -> bool:
        """Connect to the device/service. Optional - override if needed."""
        self.is_connected = True
        return True
    
    def disconnect(self) -> bool:
        """Disconnect from the device/service. Optional - override if needed."""
        self.is_connected = False
        return True


# Simplified interfaces for type hints only
# Controllers implement their own methods without forced inheritance

class RemoteControllerInterface(BaseController):
    """Type hint interface for remote controllers."""
    
    def __init__(self, device_name: str = "Unknown Device", device_type: str = "generic"):
        super().__init__("remote", device_name)
        self.device_type = device_type
    
    def execute_sequence(self, commands: List[Dict[str, Any]], retry_actions: List[Dict[str, Any]], failure_actions: List[Dict[str, Any]] = None) -> bool:
        """
        Execute a sequence of commands with optional retry actions.
        
        Args:
            commands: List of command dictionaries with 'command', 'params', and optional 'delay'
            retry_actions: Retry actions to execute if main commands fail (can be empty/None)
        """
        if not self.is_connected:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        print(f"Remote[{self.device_type.upper()}]: Executing sequence of {len(commands)} commands")
        
        # Execute main commands
        main_success = True
        for i, cmd in enumerate(commands):
            command = cmd.get('command')
            params = cmd.get('params', {})
            delay = cmd.get('delay', 0)
            
            print(f"Remote[{self.device_type.upper()}]: Command {i+1}/{len(commands)}: {command}")
            
            # Execute command
            result = self.execute_command(command, params)
            success = result.get('success', False)

            if not success:
                print(f"Remote[{self.device_type.upper()}]: Command {i+1} failed: {command}")
                main_success = False
                break
                
            # Apply delay if specified
            if delay > 0:
                delay_seconds = delay / 1000.0
                print(f"Remote[{self.device_type.upper()}]: Waiting {delay_seconds}s after command {i+1}")
                time.sleep(delay_seconds)
        
        failure_actions = failure_actions or []
        
        # If main commands failed and retry actions provided, execute retry actions
        if not main_success and retry_actions:
            print(f"Remote[{self.device_type.upper()}]: Main commands failed, executing {len(retry_actions)} retry actions")
            
            # Stop on first retry failure
            retry_success = True  # Assume success until a retry fails
            for i, retry_cmd in enumerate(retry_actions):
                command = retry_cmd.get('command')
                params = retry_cmd.get('params', {})
                delay = retry_cmd.get('delay', 0)
                
                print(f"Remote[{self.device_type.upper()}]: Retry {i+1}/{len(retry_actions)}: {command}")
                
                # Execute retry command
                result = self.execute_command(command, params)
                success = result.get('success', False)

                if success:
                    print(f"Remote[{self.device_type.upper()}]: Retry {i+1} succeeded: {command}")
                else:
                    print(f"Remote[{self.device_type.upper()}]: Retry {i+1} failed: {command}")
                    retry_success = False
                    # Stop on first retry failure (default strict behavior)
                    break
                    
                # Apply delay if specified
                if delay > 0:
                    delay_seconds = delay / 1000.0
                    print(f"Remote[{self.device_type.upper()}]: Waiting {delay_seconds}s after retry {i+1}")
                    time.sleep(delay_seconds)
            
            # If retry actions also failed and failure actions provided, execute failure actions
            if not retry_success and failure_actions:
                print(f"Remote[{self.device_type.upper()}]: Retry actions failed, executing {len(failure_actions)} failure actions")
                
                failure_success = True  # Assume success until a failure action fails
                for i, failure_cmd in enumerate(failure_actions):
                    command = failure_cmd.get('command')
                    params = failure_cmd.get('params', {})
                    delay = failure_cmd.get('delay', 0)
                    
                    print(f"Remote[{self.device_type.upper()}]: Failure {i+1}/{len(failure_actions)}: {command}")
                    
                    # Execute failure command
                    result = self.execute_command(command, params)
                    success = result.get('success', False)
                    
                    if success:
                        print(f"Remote[{self.device_type.upper()}]: Failure {i+1} succeeded: {command}")
                    else:
                        print(f"Remote[{self.device_type.upper()}]: Failure {i+1} failed: {command}")
                        failure_success = False
                        # Stop on first failure action failure
                        break
                        
                    # Apply delay if specified
                    if delay > 0:
                        delay_seconds = delay / 1000.0
                        print(f"Remote[{self.device_type.upper()}]: Waiting {delay_seconds}s after failure {i+1}")
                        time.sleep(delay_seconds)
                
                # Return True only if ALL failure actions succeeded
                return failure_success
            
            # Return True only if ALL retry actions succeeded
            return retry_success
        
        return main_success


class DesktopControllerInterface(BaseController):
    """Type hint interface for desktop controllers (bash, powershell, etc.)."""
    
    def __init__(self, device_name: str = "Unknown Device", desktop_type: str = "generic"):
        super().__init__("desktop", device_name)
        self.desktop_type = desktop_type
    
    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a desktop command and return the result.
        
        Args:
            command: Command to execute
            params: Command parameters
            
        Returns:
            Dict with success, output, error, and exit_code
        """
        raise NotImplementedError("Desktop controllers must implement execute_command")


class WebControllerInterface(BaseController):
    """Type hint interface for web controllers (playwright, selenium, etc.)."""
    
    def __init__(self, device_name: str = "Unknown Device", web_type: str = "generic"):
        super().__init__("web", device_name)
        self.web_type = web_type
    
    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a web automation command.
        
        Args:
            command: Command to execute
            params: Command parameters
            
        Returns:
            bool: True if command executed successfully
        """
        raise NotImplementedError("Web controllers must implement execute_command")


class AVControllerInterface(BaseController):
    """Type hint interface for AV controllers."""
    
    # Global configuration for video segments
    HLS_SEGMENT_DURATION = 1  # seconds per segment
    
    def __init__(self, device_name: str = "Unknown Device", capture_source: str = "HDMI"):
        super().__init__("av", device_name)
        self.capture_source = capture_source
    
    def take_video(self, duration_seconds: float = None, test_start_time: float = None) -> Optional[str]:
        """
        Upload HLS stream directly to R2 (no MP4 conversion).
        Fast upload with no processing time.
        
        Args:
            duration_seconds: How many seconds of video to capture (default: 10s)
            test_start_time: Unix timestamp when test started (for time sync)
            
        Returns:
            R2 URL of HLS playlist (m3u8), or None if failed
        """
        # Default implementation - override in concrete classes
        raise NotImplementedError("AV controllers must implement take_video")
    
    def start_video_capture(self, duration: float = 60.0, filename: str = None, 
                           resolution: str = None, fps: int = None) -> bool:
        """
        Start video capture by recording start time and duration.
        
        Args:
            duration: Duration in seconds (default: 60s)
            filename: Optional filename
            resolution: Video resolution
            fps: Video FPS
            
        Returns:
            bool: True if capture started successfully
        """
        # Default implementation - override in concrete classes
        raise NotImplementedError("AV controllers must implement start_video_capture")
    
    def stop_video_capture(self) -> bool:
        """Stop video capture session."""
        # Default implementation - override in concrete classes
        raise NotImplementedError("AV controllers must implement stop_video_capture")
    
    def take_screenshot(self, filename: str = None) -> Optional[str]:
        """
        Take screenshot and return local file path.
        
        Args:
            filename: Optional filename
            
        Returns:
            Local file path if successful, None if failed
        """
        # Default implementation - override in concrete classes
        raise NotImplementedError("AV controllers must implement take_screenshot")
    
    def save_screenshot(self, filename: str) -> Optional[str]:
        """
        Take screenshot and return local path for permanent storage.
        
        Args:
            filename: The filename to use for the screenshot
            
        Returns:
            Local file path if successful, None if failed
        """
        # Default implementation - override in concrete classes  
        raise NotImplementedError("AV controllers must implement save_screenshot")


class FFmpegCaptureController(AVControllerInterface):
    """
    Shared FFmpeg-based capture functionality for both HDMI and VNC controllers.
    Handles screenshot and video capture using the same host-side FFmpeg capture system.
    """
    
    def __init__(self, device_name: str, capture_source: str, video_stream_path: str, video_capture_path: str, **kwargs):
        """
        Initialize the FFmpeg capture controller.

        Args:
            device_name: Name of the device/controller
            capture_source: Source type (HDMI, VNC, etc.)
            video_stream_path: Stream path for URLs (e.g., "/host/stream/capture1")
            video_capture_path: Local capture path (e.g., "/var/www/html/stream/capture1")
        """
        super().__init__(device_name, capture_source)

        # Store real device name and device_id if provided
        self.real_device_name = kwargs.get('real_device_name', device_name)
        self.device_id = kwargs.get('device_id', 'unknown')

        # Store video device path for audio capture
        self.video_device = kwargs.get('video_device', '/dev/video0')
        
        # Stream and capture paths
        self.video_stream_path = video_stream_path
        self.video_capture_path = video_capture_path
        
        # Screenshot FPS based on capture source type
        if 'vnc' in capture_source.lower() or 'x11grab' in str(kwargs):
            self.screenshot_fps = 2
        else:
            self.screenshot_fps = 5  # Default for HDMI/hardware
        
        # Video capture state (timestamp-based, no FFmpeg)
        self.is_capturing_video = False
        self.capture_start_time = None
        self.capture_duration = 0
        self.capture_session_id = None
        
        # Initialize helper classes
        self._restart_helpers = None
        self._monitoring_helpers = None
        
        print(f"{capture_source}[{self.capture_source}]: Initialized - Stream: {self.video_stream_path}, Capture: {self.video_capture_path}, FPS: {self.screenshot_fps}")
    
    @property
    def restart_helpers(self):
        """Lazy initialization of restart helpers"""
        if self._restart_helpers is None:
            from .verification.video_restart_helpers import VideoRestartHelpers
            self._restart_helpers = VideoRestartHelpers(self, self.real_device_name)
        return self._restart_helpers
    
    @property
    def monitoring_helpers(self):
        """Lazy initialization of monitoring helpers"""
        if self._monitoring_helpers is None:
            from .verification.video_monitoring_helpers import VideoMonitoringHelpers
            self._monitoring_helpers = VideoMonitoringHelpers(self, self.real_device_name)
        return self._monitoring_helpers

    def get_quality(self) -> str:
        """Return this device's current stream quality from active_captures.conf.

        This is the inverse of set_quality (defined per-subclass): it reads the
        CSV (capture_dir,PID,quality) and matches this controller's capture
        directory using the same normalized-path comparison. Falls back to 'sd'
        (the ffmpeg default) when the device has no line yet."""
        try:
            import os
            from shared.src.lib.utils.storage_path_utils import get_active_captures_conf_path

            config_file = get_active_captures_conf_path()
            if not os.path.exists(config_file):
                return 'sd'

            target = os.path.normcase(os.path.normpath(self.video_capture_path))
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(',') if ',' in line else line.split('|')
                    if len(parts) == 3 and os.path.normcase(os.path.normpath(parts[0])) == target:
                        quality = parts[2].strip().lower()
                        return quality if quality in ('low', 'sd', 'hd', 'hd_plus') else 'sd'

            return 'sd'
        except Exception as e:
            print(f"[{self.capture_source}] Error reading stream quality: {e}")
            return 'sd'

    def take_screenshot(self, filename: str = None) -> Optional[str]:
        """
        Take screenshot using mtime-based lookup for sequential files.
        Auto-copies to cold storage and returns cold path.
        """
        try:
            import time
            import os
            import shutil
            import platform
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            
            # Use centralized path resolution (handles hot/cold storage automatically)
            captures_path = get_capture_storage_path(self.video_capture_path, 'captures')
            print(f"[{self.capture_source}]: Capture folder: {captures_path}")
                
            if not os.path.exists(captures_path):
                print(f"[{self.capture_source}]: ERROR - Capture directory does not exist")
                return None
            
            # Only check the 15 most recent files (FAST - avoids scanning entire directory)
            # With 2 FPS capture rate, 15 files = ~7.5 seconds of history (more than enough)
            import re
            now = time.time()
            is_windows = platform.system() == 'Windows'
            recent_cutoff_seconds = 30 if is_windows else 3
            max_age_seconds = 20 if is_windows else 2
            cutoff_time = now - recent_cutoff_seconds
            
            recent_files = []
            files_checked = 0
            try:
                # Cross-platform: use os.scandir() instead of ls (works on both Linux and Windows)
                capture_re = re.compile(r'^capture_.*\.jpg$')
                thumb_re = re.compile(r'_thumbnail\.jpg$')
                
                all_entries = []
                with os.scandir(captures_path) as entries:
                    for entry in entries:
                        if entry.is_file() and capture_re.match(entry.name) and not thumb_re.search(entry.name):
                            try:
                                all_entries.append((entry.stat().st_mtime, entry.name))
                            except OSError:
                                continue
                
                # Sort by mtime descending and take 15 newest
                all_entries.sort(reverse=True)
                
                for _, filename in all_entries[:15]:
                    files_checked += 1
                    path = os.path.join(captures_path, filename)
                    try:
                        mtime = os.path.getmtime(path)
                        age = now - mtime
                        if mtime >= cutoff_time:
                            recent_files.append((age, path))
                    except OSError as e:
                        print(f"[{self.capture_source}]: OSError for {filename}: {e}")
                        continue
                
                if not all_entries:
                    print(f"[{self.capture_source}]: No capture files found in directory")
            except Exception as e:
                print(f"[{self.capture_source}]: WARNING - Error scanning directory: {e}")
            
            if not recent_files:
                if all_entries:
                    newest_mtime, newest_name = all_entries[0]
                    newest_age = now - newest_mtime
                    print(f"[{self.capture_source}]: WARNING - No recent files within {recent_cutoff_seconds}s. Newest file age: {newest_age:.2f}s ({newest_name})")
                    # Windows fallback: allow older captures if FFmpeg is slower
                    if is_windows and newest_age <= 60:
                        closest_path = os.path.join(captures_path, newest_name)
                        closest_age = newest_age
                        print(f"[{self.capture_source}]: Windows fallback - using newest file ({newest_age:.2f}s old)")
                        # Skip strict age check below
                        max_age_seconds = max(max_age_seconds, newest_age)
                    else:
                        print(f"[{self.capture_source}]: ERROR - No recent files found (within {recent_cutoff_seconds}s)")
                        return None
                else:
                    print(f"[{self.capture_source}]: ERROR - No recent files found (within {recent_cutoff_seconds}s)")
                    return None
            
            # Sort by age and get the newest file within threshold
            if recent_files:
                recent_files.sort()
                closest_age, closest_path = recent_files[0]
            
            if closest_age > max_age_seconds:
                print(f"[{self.capture_source}]: ERROR - Newest file too old: {closest_age:.2f}s")
                return None
            
            print(f"[{self.capture_source}]: File selected - checked: {files_checked}, recent: {len(recent_files)}, using age: {closest_age:.2f}s")
            
            # Auto-copy to cold storage (capture + thumbnail)
            from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path, is_hot_storage_path
            if is_hot_storage_path(closest_path):
                cold_path = convert_hot_to_cold_path(closest_path)
                # Directory MUST exist (pre-created by setup_ram_hot_storage.sh)
                if not os.path.exists(os.path.dirname(cold_path)):
                    print(f"[{self.capture_source}]: ERROR - Cold storage directory not found: {os.path.dirname(cold_path)}")
                    print(f"[{self.capture_source}]: Run setup_ram_hot_storage.sh to create cold storage directories")
                    return None
                    
                if not os.path.exists(cold_path):
                    # Use shutil.copy() instead of copy2() to avoid permission issues with different owners
                    shutil.copy(closest_path, cold_path)
                
                # Also copy thumbnail if exists
                from shared.src.lib.utils.storage_path_utils import get_thumbnail_path_from_capture
                hot_thumb = get_thumbnail_path_from_capture(closest_path)
                if os.path.exists(hot_thumb):
                    cold_thumb = convert_hot_to_cold_path(hot_thumb)
                    if os.path.exists(os.path.dirname(cold_thumb)):
                        if not os.path.exists(cold_thumb):
                            # Use shutil.copy() instead of copy2() to avoid permission issues with different owners
                            shutil.copy(hot_thumb, cold_thumb)
                    else:
                        print(f"[{self.capture_source}]: WARNING - Cold thumbnail directory not found: {os.path.dirname(cold_thumb)}")
                
                return cold_path
            
            return closest_path
                
        except Exception as e:
            print(f'[{self.capture_source}]: ERROR taking screenshot: {e}')
            import traceback
            print(f'[{self.capture_source}]: Traceback: {traceback.format_exc()}')
            return None
    
    def save_screenshot(self, filename: str) -> Optional[str]:
        """
        Take screenshot and return local path.
        Used for permanent storage in navigation nodes.
        The route should handle the R2 upload, not the controller.
        
        Args:
            filename: The filename to use for the screenshot (e.g., node name)
            
        Returns:
            Local file path if successful, None if failed
        """
        try:
            # First take a temporary screenshot to get the image
            temp_screenshot_path = self.take_screenshot()
            if not temp_screenshot_path:
                print(f'[{self.capture_source}]: Failed to take temporary screenshot')
                return None
            
            # The temp_screenshot_path is already the local file path we need (sequential naming)
            local_screenshot_path = temp_screenshot_path
            
            # Check if local file exists with retry for timing issues
            import os
            import time
            
            # First attempt
            if not os.path.exists(local_screenshot_path):
                time.sleep(1.0)
                # Retry once
                if not os.path.exists(local_screenshot_path):
                    print(f'[{self.capture_source}]: Local screenshot file not found after retry: {local_screenshot_path}')
                    return None
            
            # Return the local file path for the route to handle the upload
            return local_screenshot_path
            
        except Exception as e:
            print(f'[{self.capture_source}]: Error saving screenshot: {e}')
            return None

    def generateRestartVideoOnly(self, duration_seconds: float = 10.0) -> Optional[Dict[str, Any]]:
        """Generate video only - fast response"""
        return self.restart_helpers.generate_restart_video_only(duration_seconds)

    def analyzeRestartAudio(self, video_id: str, segment_files: List[tuple] = None) -> Optional[Dict[str, Any]]:
        """Analyze audio transcript using provided segment files from video generation"""
        return self.restart_helpers.analyze_restart_audio(video_id, segment_files)



    def analyzeRestartComplete(self, video_id: str, screenshot_urls: list) -> Optional[Dict[str, Any]]:
        """Combined restart analysis: subtitles + summary in single optimized call"""
        return self.restart_helpers.analyze_restart_complete(video_id, screenshot_urls)
    
    # =============================================================================
    # 4-Step Dubbing Process Methods
    # =============================================================================
    
    def prepareDubbingAudio(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Step 1: Prepare audio for dubbing (extract + separate)"""
        return self.restart_helpers.prepare_dubbing_audio(video_id)
    
    
    def generateEdgeSpeech(self, video_id: str, target_language: str, existing_transcript: str) -> Optional[Dict[str, Any]]:
        """Step 2: Generate Edge-TTS speech"""
        return self.restart_helpers.generate_edge_speech(video_id, target_language, existing_transcript)
    
    def createDubbedVideo(self, video_id: str, target_language: str, voice_choice: str = 'edge') -> Optional[Dict[str, Any]]:
        """Step 3: Create final dubbed video"""
        return self.restart_helpers.create_dubbed_video(video_id, target_language, voice_choice)
    
    def createDubbedVideoFast(self, video_id: str, target_language: str, existing_transcript: str) -> Optional[Dict[str, Any]]:
        """NEW: Fast 2-step dubbed video creation"""
        return self.restart_helpers.create_dubbed_video_fast(video_id, target_language, existing_transcript)
    
    def adjustVideoAudioTiming(self, video_url: str, timing_offset_ms: int, language: str = "original",
                              silent_video_path: str = None, background_audio_path: str = None, 
                              vocals_path: str = None) -> Optional[Dict[str, Any]]:
        """Adjust audio timing for existing restart video"""
        return self.restart_helpers.adjust_video_audio_timing(video_url, timing_offset_ms, language,
                                                             silent_video_path, background_audio_path, vocals_path)

    
    
    def take_video(self, duration_seconds: float = None, test_start_time: float = None) -> Optional[str]:
        """
        Simple video capture without analysis (for script framework and other use cases).
        
        Args:
            duration_seconds: How many seconds of video to capture (default: 10s)
            test_start_time: Unix timestamp when test started (for time sync)
            
        Returns:
            R2 URL of compressed MP4 video, or None if failed
        """
        try:
            import time
            import os
            import tempfile
            
            if duration_seconds is None:
                duration_seconds = 10.0  # Fixed 10 seconds for fast restart videos
                
            print(f"[{self.capture_source}]: Compressing {duration_seconds}s HLS video to MP4")
            
            # Use configured segment duration consistently
            print(f"[{self.capture_source}]: Using configured segment duration: {self.HLS_SEGMENT_DURATION}s")
            
            # Get recent HLS segments for compression using restart helpers
            segment_files = self.restart_helpers._get_recent_segments(duration_seconds)
            if not segment_files:
                print(f"[{self.capture_source}]: No HLS segments found for compression")
                return None
            
            # Compress segments to MP4 using VideoCompressionUtils directly
            from backend_host.src.lib.utils.video_compression_utils import VideoCompressionUtils
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, is_ram_mode
            
            compressor = VideoCompressionUtils()
            
            video_filename = "test_video.mp4"
            # Write to correct location based on hot/cold storage architecture
            if is_ram_mode(self.video_capture_path):
                local_video_path = os.path.join(self.video_capture_path, 'hot', video_filename)
            else:
                local_video_path = os.path.join(self.video_capture_path, video_filename)
            
            # Get M3U8 path using centralized storage utilities (handles hot/cold)
            segments_folder = get_capture_storage_path(self.video_capture_path, 'segments')
            m3u8_path = os.path.join(segments_folder, "output.m3u8")
            
            compression_result = compressor.compress_hls_to_mp4(
                m3u8_path=m3u8_path,
                segment_files=segment_files,
                output_path=local_video_path,
                compression_level="medium"
            )
            
            if not compression_result.get('success', False):
                print(f"[{self.capture_source}]: Video compression failed")
                return None
            
            # Return local file path for upload to R2 (not stream URL)
            print(f"[{self.capture_source}]: Video created at local path: {local_video_path}")
            return local_video_path
            
        except Exception as e:
            print(f"[{self.capture_source}]: Error creating video: {e}")
            return None
    
    def take_video_for_report(self, duration_seconds: float, test_start_time: float) -> Optional[str]:
        """
        Capture test execution video for report using HYBRID approach (HOT + COLD).
        
        This method intelligently combines:
        - Recent segments from HOT storage (last ~90s)
        - Missing history from COLD MP4 chunks (if needed)
        
        This solves the problem where archiver has already moved old segments to COLD,
        leaving only recent segments in HOT storage.
        
        Args:
            duration_seconds: Total video duration needed (e.g., 154s for full test)
            test_start_time: Unix timestamp when test started
            
        Returns:
            Local path to created MP4 video, or None if failed
        """
        try:
            import os
            from datetime import datetime
            from shared.src.lib.utils.storage_path_utils import (
                extract_test_video_hybrid, 
                get_capture_folder, 
                is_ram_mode
            )
            
            # Get device folder from capture path
            device_folder = get_capture_folder(self.video_capture_path)

            print(f"📹 [{self.capture_source}] Capturing test video for report...")
            print(f"   Duration needed: {duration_seconds:.1f}s")
            print(f"   Test start: {datetime.fromtimestamp(test_start_time).strftime('%H:%M:%S')}")
            print(f"   Device folder: {device_folder} | capture_path: {self.video_capture_path} | ram_mode: {is_ram_mode(self.video_capture_path)}")
            
            # Determine output path.
            # NOTE: a report video can be a full test duration (tens of minutes →
            # hundreds of MB). It must NOT land on the HOT RAM disk (a ~200 MB
            # tmpfs) even in RAM mode — the final faststart muxing overflows it
            # ("No space left on device"). Write to the COLD capture root, which
            # is on the big NVMe volume (same filesystem as the COLD chunks). The
            # file is transient (uploaded to R2, then disposable).
            video_filename = "test_video.mp4"
            output_path = os.path.join(self.video_capture_path, video_filename)

            # Convert timestamp to datetime
            start_datetime = datetime.fromtimestamp(test_start_time)
            
            # Use hybrid extraction (HOT + COLD backfill)
            video_path = extract_test_video_hybrid(
                device_folder=device_folder,
                start_time=start_datetime,
                duration_seconds=int(duration_seconds),
                output_path=output_path
            )
            
            if video_path and os.path.exists(video_path):
                video_size_mb = os.path.getsize(video_path) / 1024 / 1024
                print(f"✅ [{self.capture_source}] Test video created: {video_path} ({video_size_mb:.1f}MB)")
                return video_path
            else:
                print(f"❌ [{self.capture_source}] Hybrid video extraction failed for '{device_folder}' "
                      f"(needed {duration_seconds:.0f}s from {datetime.fromtimestamp(test_start_time):%H:%M:%S}) "
                      f"— see [VideoExtract:{device_folder}] lines above for the reason")
                return None
                
        except Exception as e:
            print(f"❌ [{self.capture_source}] Error capturing test video for report: {e}")
            import traceback
            traceback.print_exc()
            return None
        
    def take_control(self) -> Dict[str, Any]:
        """
        Take control of stream and verify it's working.
        
        Returns:
            Dictionary with success status and stream information
        """
        try:
            # Check stream status
            status = self.get_status()
            is_streaming = status.get('is_streaming', False)
            
            # For FFmpeg-based capture, we just need the service to be running
            # The host continuously captures screenshots regardless
            return {
                'success': True,
                'status': 'stream_ready',
                'controller_type': 'av',
                'stream_info': status,
                'capabilities': ['video_capture', 'screenshot', 'streaming']
            }
                
        except Exception as e:
            print(f"[{self.capture_source}]: Take control error: {e}")
            return {
                'success': False,
                'status': 'error',
                'error': f'{self.capture_source} controller error: {str(e)}',
                'controller_type': 'av'
            }
        
    def start_video_capture(self, duration: float = 60.0, filename: str = None, 
                           resolution: str = None, fps: int = None) -> bool:
        """
        Start video capture by recording start time and duration.
        No FFmpeg usage - just tracks timing for timestamp-based screenshot references.
        
        Args:
            duration: Duration in seconds (default: 60s)
            filename: Optional filename (ignored - uses timestamps)
            resolution: Video resolution (ignored - uses host stream resolution)
            fps: Video FPS (ignored - uses 1 frame per second from screenshots)
        """
        if self.is_capturing_video:
            return True
            
        try:
            import time
            import threading
            from datetime import datetime
            
            # Record capture session details
            self.capture_start_time = datetime.now()
            self.capture_duration = duration
            self.capture_session_id = f"capture_{int(time.time())}"
            self.is_capturing_video = True
            
            print(f"[{self.capture_source}]: Starting video capture - Session: {self.capture_session_id}, Duration: {duration}s")
            
            # Start monitoring thread to automatically stop after duration
            monitoring_thread = threading.Thread(
                target=self._monitor_capture_duration,
                args=(duration,),
                daemon=True
            )
            monitoring_thread.start()
            
            return True
            
        except Exception as e:
            print(f"[{self.capture_source}]: Failed to start video capture: {e}")
            return False
        
    def stop_video_capture(self) -> bool:
        """Stop video capture session."""
        if not self.is_capturing_video:
            return False
            
        try:
            from datetime import datetime
            
            # Calculate actual capture duration
            if self.capture_start_time:
                actual_duration = (datetime.now() - self.capture_start_time).total_seconds()
                print(f"[{self.capture_source}]: Video capture stopped - Duration: {actual_duration:.1f}s")
            
            self.is_capturing_video = False
            self.capture_session_id = None
            
            return True
            
        except Exception as e:
            print(f"[{self.capture_source}]: Error stopping video capture: {e}")
            return False
        
    def _monitor_capture_duration(self, duration: float):
        """Monitor capture duration and automatically stop after specified time."""
        import time
        
        time.sleep(duration)
        
        if self.is_capturing_video:
            print(f"[{self.capture_source}]: Capture duration ({duration}s) reached, stopping automatically")
            self.stop_video_capture()


class VerificationControllerInterface(BaseController):
    """Type hint interface for verification controllers."""
    
    def __init__(self, device_name: str = "Unknown Device", verification_type: str = "verification"):
        super().__init__("verification", device_name)
        self.verification_type = verification_type


class PowerControllerInterface(BaseController):
    """Type hint interface for power controllers."""
    
    def __init__(self, device_name: str = "Unknown Device"):
        super().__init__("power", device_name)
