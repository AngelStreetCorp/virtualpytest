"""
Video Verification Controller Implementation

Modern video analysis and verification controller built with modular helper architecture:
- VideoAnalysisHelpers: Core OpenCV/FFmpeg analysis and motion detection
- VideoContentHelpers: Content detection (blackscreen, freeze, subtitles)
- VideoAIHelpers: AI-powered analysis using OpenRouter
- VideoVerificationHelpers: Verification workflow orchestration

Clean separation of concerns with specialized helper modules.
"""

import time
import os
from datetime import datetime
from typing import Dict, Any, Optional, Union, Tuple, List
from pathlib import Path
from ..base_controller import VerificationControllerInterface

# Import helper modules
from .video_analysis_helpers import VideoAnalysisHelpers
from .video_content_helpers import VideoContentHelpers
from .video_ai_helpers import VideoAIHelpers
from .video_verification_helpers import VideoVerificationHelpers


class VideoVerificationController(VerificationControllerInterface):
    """Modern video verification controller with specialized helper modules."""
    
    def __init__(self, av_controller, **kwargs):
        """
        Initialize the Video Verification controller.
        
        Args:
            av_controller: AV controller for capturing video/images (dependency injection)
        """
        super().__init__("Video Verification", "video")
        
        # Dependency injection
        self.av_controller = av_controller
        
        # Validate required dependency
        if not self.av_controller:
            raise ValueError("av_controller is required for VideoVerificationController")
            
        # Video analysis settings
        self.motion_threshold = 5.0  # Default motion threshold percentage
        self.frame_comparison_threshold = 10.0  # Default frame change threshold
        
        # Initialized with AV controller
        
        # Controller is always ready
        self.verification_session_id = f"video_verify_{int(time.time())}"
        
        # Initialize helper modules
        self.analysis_helpers = VideoAnalysisHelpers(av_controller, self.device_name)
        self.content_helpers = VideoContentHelpers(av_controller, self.device_name)
        self.ai_helpers = VideoAIHelpers(av_controller, self.device_name)
        self.verification_helpers = VideoVerificationHelpers(self, self.device_name)
        
        print(f"[@controller:VideoVerification] Helper modules initialized")
        
    def connect(self) -> bool:
        """Connect to the video verification system."""
        try:
            print(f"VideoVerify[{self.device_name}]: Connecting to video verification system")
            
            print(f"VideoVerify[{self.device_name}]: Using AV controller: {self.av_controller.device_name}")
            
            # Check AV controller video device - but don't fail if missing
            if not hasattr(self.av_controller, 'video_device') or not self.av_controller.video_device:
                print(f"VideoVerify[{self.device_name}]: WARNING - AV controller missing video device configuration")
                print(f"VideoVerify[{self.device_name}]: Screenshot capture will not be available")
            else:
                print(f"VideoVerify[{self.device_name}]: Video device: {self.av_controller.video_device}")
            
            # Connection successful
            self.verification_session_id = f"video_verify_{int(time.time())}"
            print(f"VideoVerify[{self.device_name}]: Connected - Session: {self.verification_session_id}")
            return True
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Connection error: {e}")
            # Still connected for image analysis even if AV controller has issues
            return True

    def disconnect(self) -> bool:
        """Disconnect from the video verification system."""
        print(f"VideoVerify[{self.device_name}]: Disconnecting")
        self.verification_session_id = None
        print(f"VideoVerify[{self.device_name}]: Disconnected")
        return True


    # =============================================================================
    # Core Analysis Methods (delegated to helpers)
    # =============================================================================

    def analyze_image_content(self, image_path: str, analysis_type: str = "basic") -> Dict[str, Any]:
        """Analyze image content using OpenCV or FFmpeg."""
            
        if not os.path.exists(image_path):
            print(f"VideoVerify[{self.device_name}]: ERROR - Image file not found: {image_path}")
            return {}
        
        try:
            print(f"VideoVerify[{self.device_name}]: Analyzing image content - Type: {analysis_type}")
            
            if analysis_type in ["basic", "color", "brightness"]:
                # Use OpenCV for detailed analysis
                return self.analysis_helpers.analyze_with_opencv(image_path, analysis_type)
            else:
                # Use FFmpeg for basic analysis
                return self.analysis_helpers.analyze_with_ffmpeg(image_path, analysis_type)
                
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Image analysis error: {e}")
            return {"error": str(e)}

    def detect_motion(self, duration: float = 3.0, threshold: float = None, area: Dict[str, int] = None) -> bool:
        """Detect motion by comparing consecutive frames.

        area: optional {x, y, width, height} region to restrict the comparison to
              (e.g. exclude an animated overlay so a frozen channel isn't read as motion).
        """

        threshold = threshold or self.motion_threshold
        print(f"VideoVerify[{self.device_name}]: Detecting motion (duration: {duration}s, threshold: {threshold}%, area: {area})")

        try:
            motion_detected, change_percentage = self.analysis_helpers.detect_motion_between_captures(duration, threshold, area)
            
            result_text = "detected" if motion_detected else "not detected"
            print(f"VideoVerify[{self.device_name}]: Motion {result_text}")
            
            return motion_detected
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Motion detection error: {e}")
            return False

    def wait_for_video_change(self, timeout: float = 10.0, threshold: float = None) -> bool:
        """Wait for video content to change."""
            
        threshold = threshold or self.frame_comparison_threshold
        
        try:
            change_detected, elapsed_time = self.analysis_helpers.wait_for_video_change(timeout, threshold)
            return change_detected
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Video change detection error: {e}")
            return False

    # =============================================================================
    # Content Detection Methods (delegated to helpers)
    # =============================================================================

    def detect_blackscreen(self, image_paths: List[str] = None, threshold: int = 10) -> Dict[str, Any]:
        """Detect if image is mostly black (blackscreen)."""
        try:
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                
                # Use last available capture
                screenshot = self.av_controller.take_screenshot()
                if not screenshot:
                    return {'success': False, 'error': 'Failed to capture screenshot'}
                image_paths = [screenshot]
            
            return self.content_helpers.detect_blackscreen_batch(image_paths, threshold)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Blackscreen detection error: {e}")
            return {
                'success': False,
                'error': f'Blackscreen detection failed: {str(e)}',
                'analysis_type': 'blackscreen_detection'
            }

    def detect_freeze(self, image_paths: List[str] = None, freeze_threshold: float = 1.0) -> Dict[str, Any]:
        """Detect if images are frozen (identical frames)."""
        try:
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                
                # Use multiple recent captures for freeze detection
                screenshots = []
                for i in range(3):  # Get 3 screenshots with delay
                    screenshot = self.av_controller.take_screenshot()
                    if screenshot:
                        screenshots.append(screenshot)
                    if i < 2:  # Don't wait after last screenshot
                        time.sleep(1.0)  # Wait 1 second between captures
                
                if len(screenshots) < 2:
                    return {'success': False, 'error': 'Need at least 2 images for freeze detection'}
                
                image_paths = screenshots
            
            return self.content_helpers.detect_freeze_in_images(image_paths, freeze_threshold)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Freeze detection error: {e}")
            return {
                'success': False,
                'error': f'Freeze detection failed: {str(e)}',
                'analysis_type': 'freeze_detection'
            }

    def detect_subtitles(self, image_paths: List[str] = None, extract_text: bool = True) -> Dict[str, Any]:
        """Detect subtitles and error messages using OCR."""
        try:
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                
                # Use last available capture
                screenshot = self.av_controller.take_screenshot()
                if not screenshot:
                    return {'success': False, 'error': 'Failed to capture screenshot'}
                image_paths = [screenshot]
            
            return self.content_helpers.detect_subtitles_batch(image_paths, extract_text)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Subtitle detection error: {e}")
            return {
                'success': False,
                'error': f'Subtitle detection failed: {str(e)}',
                'analysis_type': 'subtitle_detection'
            }

    def detect_subtitles_ai(self, image_paths: List[str] = None, extract_text: bool = True) -> Dict[str, Any]:
        """AI-powered subtitle detection using OpenRouter."""
        try:
            print(f"VideoVerify[{self.device_name}]: DEBUG: detect_subtitles_ai called with image_paths: {image_paths}")
            
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                print(f"VideoVerify[{self.device_name}]: DEBUG: No image_paths provided, taking fallback screenshot")
                
                # Use last available capture
                screenshot = self.av_controller.take_screenshot()
                if not screenshot:
                    return {'success': False, 'error': 'Failed to capture screenshot'}
                image_paths = [screenshot]
                print(f"VideoVerify[{self.device_name}]: DEBUG: Fallback screenshot taken: {screenshot}")
            else:
                print(f"VideoVerify[{self.device_name}]: DEBUG: Using provided image_paths: {image_paths}")
            
            return self.ai_helpers.detect_subtitles_ai_batch(image_paths, extract_text)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: AI subtitle detection error: {e}")
            return {
                'success': False,
                'error': f'AI subtitle detection failed: {str(e)}',
                'analysis_type': 'ai_subtitle_detection'
            }

    def detect_subtitles_ai_all_frames(self, image_paths: List[str] = None, extract_text: bool = True) -> Dict[str, Any]:
        """AI-powered subtitle detection for ALL frames (restart video analysis)."""
        try:
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                
                # Use last available capture
                screenshot = self.av_controller.take_screenshot()
                if not screenshot:
                    return {'success': False, 'error': 'Failed to capture screenshot'}
                image_paths = [screenshot]
            
            print(f"VideoVerify[{self.device_name}]: Starting AI subtitle analysis for ALL {len(image_paths)} frames")
            return self.ai_helpers.detect_subtitles_ai_all_frames(image_paths, extract_text)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: AI all-frames subtitle detection error: {e}")
            return {
                'success': False,
                'error': f'AI all-frames subtitle detection failed: {str(e)}',
                'analysis_type': 'ai_subtitle_detection_all_frames'
            }

    def detect_macroblocks(self, image_paths: List[str] = None) -> Dict[str, Any]:
        """Detect macroblocks/image quality issues."""
        
        try:
            # Determine which images to analyze
            if image_paths is None or len(image_paths) == 0:
                # Capture current screenshot if no paths provided
                screenshot = self.av_controller.take_screenshot()
                if not screenshot:
                    return {"success": False, "error": "Failed to capture screenshot"}
                image_paths = [screenshot]
            
            print(f"VideoVerify[{self.device_name}]: Analyzing {len(image_paths)} images for macroblocks")
            return self.content_helpers.detect_macroblocks_batch(image_paths)
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Macroblock detection error: {e}")
            return {
                'success': False,
                'error': f'Macroblock detection failed: {str(e)}',
                'analysis_type': 'macroblock_detection'
            }

    def detect_motion_from_json(self, json_count: int = 5, strict_mode: bool = True) -> Dict[str, Any]:
        """Detect motion/activity by analyzing the last N JSON analysis files."""
        
        try:
            print(f"VideoVerify[{self.device_name}]: Analyzing last {json_count} JSON files (strict_mode: {strict_mode})")
            
            # Get analysis files directly from AV controller's capture path
            capture_path = getattr(self.av_controller, 'video_capture_path', None)
            if not capture_path:
                return {
                    'success': False,
                    'video_ok': False,
                    'audio_ok': False,
                    'blackscreen_count': 0,
                    'freeze_count': 0,
                    'audio_loss_count': 0,
                    'total_analyzed': 0,
                    'details': [],
                    'strict_mode': strict_mode,
                    'message': 'No video capture path available from AV controller'
                }
            
            # Use content helpers with direct capture path
            return self.content_helpers.detect_motion_from_json_analysis(capture_path, json_count, strict_mode)
            
        except Exception as e:
            error_msg = f"Motion detection from JSON error: {e}"
            print(f"VideoVerify[{self.device_name}]: {error_msg}")
            return {
                'success': False,
                'video_ok': False,
                'audio_ok': False,
                'blackscreen_count': 0,
                'freeze_count': 0,
                'audio_loss_count': 0,
                'total_analyzed': 0,
                'details': [],
                'strict_mode': strict_mode,
                'message': error_msg
            }

    # =============================================================================
    # AI Analysis Methods (delegated to helpers)
    # =============================================================================

    def analyze_image_with_ai(self, image_path: str, user_question: str) -> str:
        """Analyze full image with AI using user's question."""
        return self.ai_helpers.analyze_full_image_with_ai(image_path, user_question)

    def analyze_image_ai(self, image_path: str, user_query: str) -> Dict[str, Any]:
        """Wrapper method for analyze_image_with_ai to match route expectations."""
        return self.ai_helpers.analyze_image_ai_wrapper(image_path, user_query)
    
    def analyze_image_complete(self, image_path: str, extract_text: bool = True, include_description: bool = True) -> Dict[str, Any]:
        """Combined AI analysis: subtitles + description in single call."""
        return self.ai_helpers.analyze_image_complete(image_path, extract_text, include_description)

    def analyze_image_batch_complete(self, image_paths: list, extract_text: bool = True, include_description: bool = True) -> Dict[str, Any]:
        """Batch AI analysis: subtitles + description for multiple images in single call."""
        return self.ai_helpers.analyze_image_batch_complete(image_paths, extract_text, include_description)

    def analyze_language_menu_ai(self, image_path: str) -> Dict[str, Any]:
        """AI-powered language/subtitle menu analysis using OpenRouter."""
        return self.ai_helpers.analyze_language_menu_ai(image_path)

    # =============================================================================
    # High-Level Verification Methods
    # =============================================================================

    def waitForVideoToAppear(self, motion_threshold: float = 5.0, duration: float = 3.0,
                             timeout: float = 10.0, area: Dict[str, int] = None) -> bool:
        """Wait for video content to appear (motion detected).

        `area` matters wherever the player does not fill the frame. detect_motion defaults to
        the centre 60%, which is right for a TV — video edge to edge, overlays round the
        outside. On a portrait phone it is wrong: YouTube draws its player across the top ~28%
        and fills the centre with the title, Subscribe row and comments, so the default region
        measures a static block while the video plays (measured on a 1080x2400 phone: 0.9-2.9%
        in the centre against 4.1-7.6% over the player).
        """
            
        print(f"VideoVerify[{self.device_name}]: Waiting for video to appear (motion threshold: {motion_threshold}%, duration: {duration}s, timeout: {timeout}s, area: {area})")
        
        start_time = time.time()
        check_interval = 1.0
        
        while time.time() - start_time < timeout:
            motion_detected = self.detect_motion(duration, motion_threshold, area)
            
            if motion_detected:
                elapsed = time.time() - start_time
                print(f"VideoVerify[{self.device_name}]: Video appeared after {elapsed:.1f}s")
                return True
            
            time.sleep(check_interval)
        
        print(f"VideoVerify[{self.device_name}]: Video did not appear within {timeout}s")
        return False

    def waitForVideoToDisappear(self, motion_threshold: float = 5.0, duration: float = 3.0,
                                timeout: float = 10.0, area: Dict[str, int] = None) -> bool:
        """Wait for video content to disappear (no motion detected).

        `area` matters wherever the player does not fill the frame. detect_motion defaults to
        the centre 60%, which is right for a TV — video edge to edge, overlays round the
        outside. On a portrait phone it is wrong: YouTube draws its player across the top ~28%
        and fills the centre with the title, Subscribe row and comments, so the default region
        measures a static block while the video plays (measured on a 1080x2400 phone: 0.9-2.9%
        in the centre against 4.1-7.6% over the player).
        """
            
        print(f"VideoVerify[{self.device_name}]: Waiting for video to disappear (motion threshold: {motion_threshold}%, duration: {duration}s, timeout: {timeout}s, area: {area})")
        
        start_time = time.time()
        check_interval = 1.0
        
        while time.time() - start_time < timeout:
            motion_detected = self.detect_motion(duration, motion_threshold, area)
            
            if not motion_detected:
                elapsed = time.time() - start_time
                print(f"VideoVerify[{self.device_name}]: Video disappeared after {elapsed:.1f}s")
                return True
            
            time.sleep(check_interval)
        
        print(f"VideoVerify[{self.device_name}]: Video still present after {timeout}s")
        return False

    # =============================================================================
    # Core Verification Methods
    # =============================================================================
        
    def verify_color_present(self, color: str, tolerance: float = 10.0) -> bool:
        """Verify that a specific color is present on screen."""
            
        print(f"VideoVerify[{self.device_name}]: Looking for color '{color}' (tolerance: {tolerance}%)")
        
        # Capture screenshot for analysis
        screenshot = self.av_controller.take_screenshot()
        if not screenshot:
            return False
        
        # Analyze color content
        color_analysis = self.analyze_image_content(screenshot, "color")
        
        # Simplified color detection (in a real implementation, this would be more sophisticated)
        color_found = False
        if "dominant_color" in color_analysis:
            dominant = color_analysis["dominant_color"].lower()
            color_found = color.lower() in dominant or dominant in color.lower()
        
        result_text = "found" if color_found else "not found"
        print(f"VideoVerify[{self.device_name}]: Color '{color}' {result_text}")
        
        return color_found
        
    def verify_screen_state(self, expected_state: str, timeout: float = 5.0) -> bool:
        """Verify that the screen is in an expected state based on visual analysis."""
            
        print(f"VideoVerify[{self.device_name}]: Verifying screen state '{expected_state}' (timeout: {timeout}s)")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            screenshot = self.av_controller.take_screenshot()
            if not screenshot:
                time.sleep(0.5)
                continue
            
            # Analyze screenshot for state indicators
            analysis = self.analyze_image_content(screenshot, "brightness")
            
            # Simplified state detection based on brightness and content
            state_detected = False
            if expected_state.lower() == "loading":
                # Loading screens often have lower brightness or specific patterns
                brightness = analysis.get("brightness_percentage", 50)
                state_detected = 20 <= brightness <= 60
            elif expected_state.lower() == "ready":
                # Ready screens often have normal brightness
                brightness = analysis.get("brightness_percentage", 50)
                state_detected = brightness > 40
            elif expected_state.lower() == "error":
                # Error screens might have specific color patterns (simplified)
                state_detected = True  # Simplified for demo
            
            if state_detected:
                elapsed = time.time() - start_time
                print(f"VideoVerify[{self.device_name}]: Screen state '{expected_state}' verified after {elapsed:.1f}s")
                return True
            
            time.sleep(0.5)
        
        print(f"VideoVerify[{self.device_name}]: Screen state '{expected_state}' not detected within {timeout}s")
        return False
        
    def verify_performance_metric(self, metric_name: str, expected_value: float, tolerance: float = 10.0) -> bool:
        """Verify video-related performance metrics."""
        if metric_name.lower() in ['brightness', 'contrast']:
            screenshot = self.av_controller.take_screenshot()
            if not screenshot:
                return False
                
            analysis = self.analyze_image_content(screenshot, "brightness")
            
            if metric_name.lower() == 'brightness':
                current_value = analysis.get("brightness_percentage", 0)
            else:
                current_value = analysis.get("brightness_std", 0)
            
            tolerance_range = expected_value * (tolerance / 100)
            within_tolerance = abs(current_value - expected_value) <= tolerance_range
            
            print(f"VideoVerify[{self.device_name}]: {metric_name} = {current_value:.2f} (expected: {expected_value} ±{tolerance}%)")
            
            return within_tolerance
        else:
            print(f"VideoVerify[{self.device_name}]: Unknown video metric: {metric_name}")
            return False
        
    def wait_and_verify(self, verification_type: str, target: str, timeout: float = 10.0, **kwargs) -> bool:
        """Generic wait and verify method for video verification."""
        if verification_type == "image":
            confidence = kwargs.get("confidence", 0.8)
            return self.verify_image_appears(target, timeout, confidence)
        elif verification_type == "video_playing":
            motion_threshold = kwargs.get("motion_threshold", self.motion_threshold)
            return self.waitForVideoToAppear(motion_threshold, 3.0, timeout)
        elif verification_type == "color":
            tolerance = kwargs.get("tolerance", 10.0)
            return self.verify_color_present(target, tolerance)
        elif verification_type == "state":
            return self.verify_screen_state(target, timeout)
        elif verification_type == "video_change":
            threshold = kwargs.get("threshold", self.frame_comparison_threshold)
            return self.wait_for_video_change(timeout, threshold)
        else:
            print(f"VideoVerify[{self.device_name}]: Unknown video verification type: {verification_type}")
            return False

    # =============================================================================
    # Status and Configuration Methods (delegated to helpers)
    # =============================================================================
            
    def get_status(self) -> Dict[str, Any]:
        """Get controller status information."""
        return self.verification_helpers.get_controller_status()
    
    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for video controller."""
        return self.verification_helpers.get_available_verifications()

    def execute_verification(self, verification_config: Dict[str, Any], image_source_url: str = None) -> Dict[str, Any]:
        """Unified verification execution interface for centralized controller."""
        print(f"VideoVerify[{self.device_name}]: DEBUG: execute_verification called with image_source_url: {image_source_url}")
        print(f"VideoVerify[{self.device_name}]: DEBUG: Command: {verification_config.get('command')}")
        return self.verification_helpers.execute_verification_workflow(verification_config, image_source_url)

    # =============================================================================
    # Zapping Detection Methods
    # =============================================================================

    def detect_zapping(self, folder_path: str, key_release_timestamp: float, 
                      analysis_rectangle: Dict[str, int] = None, banner_region: Dict[str, int] = None, 
                      max_images: int = 10, device_model: str = None) -> Dict[str, Any]:
        """
        Detect channel zapping sequence by analyzing images from folder.
        
        Args:
            folder_path: Path to folder containing captured images
            key_release_timestamp: Timestamp when zapping key was released (Unix timestamp)
            analysis_rectangle: Rectangle to analyze for blackscreen (exclude banner area)
                               Format: {'x': int, 'y': int, 'width': int, 'height': int}
            banner_region: Region where banner appears for AI analysis (optional)
                          Format: {'x': int, 'y': int, 'width': int, 'height': int}
            max_images: Maximum number of images to analyze (default: 10)
            
        Returns:
            Dictionary with comprehensive zapping detection results
        """
        try:
            print(f"VideoVerify[{self.device_name}]: Starting zapping detection")
            print(f"VideoVerify[{self.device_name}]: Folder: {folder_path}")
            
            # Convert Unix timestamp to capture format for display consistency
            try:
                dt = datetime.fromtimestamp(key_release_timestamp)
                capture_format_timestamp = dt.strftime('%Y%m%d%H%M%S')
                print(f"VideoVerify[{self.device_name}]: Key release timestamp: {capture_format_timestamp} (Unix: {key_release_timestamp})")
            except (ValueError, OSError):
                print(f"VideoVerify[{self.device_name}]: Key release timestamp: {key_release_timestamp} (invalid format)")
            
            # Validate inputs
            if not folder_path:
                return {
                    'success': False,
                    'error': 'No folder path provided',
                    'zapping_detected': False,
                    'blackscreen_duration': 0.0
                }
            
            if key_release_timestamp <= 0:
                return {
                    'success': False,
                    'error': 'Invalid key release timestamp',
                    'zapping_detected': False,
                    'blackscreen_duration': 0.0
                }
            
            # Execute core zapping detection with device-specific threshold
            zapping_result = self.content_helpers.detect_zapping_sequence(
                folder_path, key_release_timestamp, analysis_rectangle, max_images, banner_region, device_model
            )
            
            if not zapping_result.get('success', False):
                return {
                    'success': False,
                    'error': f"Zapping detection failed: {zapping_result.get('error', 'Unknown error')}",
                    'zapping_detected': False,
                    'blackscreen_duration': 0.0
                }
            
            # Channel info is already extracted by video_content_helpers during zapping detection
            channel_info = {
                'channel_name': zapping_result.get('channel_name', ''),
                'channel_number': zapping_result.get('channel_number', ''),
                'program_name': zapping_result.get('program_name', ''),
                'start_time': zapping_result.get('program_start_time', ''),
                'end_time': zapping_result.get('program_end_time', ''),
                'confidence': zapping_result.get('channel_confidence', 0.0)
            }
            
            # Compile comprehensive result
            success = zapping_result.get('zapping_detected', False)
            blackscreen_duration = zapping_result.get('blackscreen_duration', 0.0)
            
            # Enhanced result with channel info
            final_result = {
                'success': success,
                'zapping_detected': success,
                'blackscreen_duration': blackscreen_duration,
                'zapping_duration': zapping_result.get('zapping_duration', 0.0),  # Total zapping duration
                'first_image': zapping_result.get('first_image'),
                'blackscreen_start_image': zapping_result.get('blackscreen_start_image'),
                'blackscreen_end_image': zapping_result.get('blackscreen_end_image'),
                'first_content_after_blackscreen': zapping_result.get('first_content_after_blackscreen'),
                'channel_detection_image': zapping_result.get('blackscreen_end_image'),  # Image used for channel detection
                'last_image': zapping_result.get('last_image'),
                'channel_info': channel_info,
                'analyzed_images': zapping_result.get('analyzed_images', 0),
                'total_images_available': zapping_result.get('total_images_available', 0),
                'analysis_stopped_early': zapping_result.get('analysis_stopped_early', False),
                'key_release_timestamp': key_release_timestamp,
                'analysis_rectangle': analysis_rectangle,
                'banner_region': banner_region,
                'details': zapping_result.get('details', {}),
                'analysis_type': 'zapping_detection',
                'timestamp': zapping_result.get('timestamp')
            }
            
            # Log the verification
            folder_name = folder_path.split('/')[-1] if folder_path else 'unknown'
            self._log_verification(
                'DetectZapping', 
                f"folder:{folder_name}", 
                success, 
                final_result
            )
            
            print(f"VideoVerify[{self.device_name}]: Zapping detection complete - detected={success}, duration={blackscreen_duration}s")
            if channel_info.get('channel_name'):
                print(f"VideoVerify[{self.device_name}]: Channel: {channel_info['channel_name']}")
            
            return final_result
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Zapping detection error: {e}")
            return {
                'success': False,
                'error': f'Zapping detection failed: {str(e)}',
                'analysis_type': 'zapping_detection',
                'zapping_detected': False,
                'blackscreen_duration': 0.0
            }

    def detect_freeze_zapping(self, folder_path: str, key_release_timestamp: float, 
                             analysis_rectangle: Dict[str, int] = None, banner_region: Dict[str, int] = None, 
                             max_images: int = 10) -> Dict[str, Any]:
        """
        Detect freeze-based zapping sequence by analyzing consecutive frames.
        
        Similar to detect_zapping() but looks for freeze patterns instead of blackscreen.
        """
        try:
            print(f"VideoVerify[{self.device_name}]: Starting freeze zapping detection")
            
            # Use enhanced content helpers method for freeze detection
            freeze_result = self.content_helpers.detect_freeze_zapping_sequence(
                folder_path, key_release_timestamp, analysis_rectangle, max_images, banner_region
            )
            
            if not freeze_result.get('success', False):
                return {
                    'success': False,
                    'error': f"Freeze zapping detection failed: {freeze_result.get('error', 'Unknown error')}",
                    'freeze_zapping_detected': False,
                    'freeze_duration': 0.0
                }
            
            # Extract channel info if banner region provided (same logic as blackscreen)
            channel_info = freeze_result.get('channel_info', {})
            if banner_region and freeze_result.get('first_content_after_freeze'):
                # Try to extract channel info from first content after freeze
                banner_result = self.ai_helpers.analyze_channel_banner_ai(
                    freeze_result['first_content_after_freeze'], banner_region
                )
                if banner_result.get('success'):
                    channel_info = banner_result.get('channel_info', {})
            
            success = freeze_result.get('freeze_zapping_detected', False)
            freeze_duration = freeze_result.get('freeze_duration', 0.0)
            
            final_result = {
                'success': success,
                'freeze_zapping_detected': success,
                'freeze_duration': freeze_duration,
                'zapping_duration': freeze_result.get('zapping_duration', 0.0),
                'first_image': freeze_result.get('first_image'),
                'freeze_start_image': freeze_result.get('freeze_start_image'),
                'freeze_end_image': freeze_result.get('freeze_end_image'),
                'first_content_after_freeze': freeze_result.get('first_content_after_freeze'),
                'channel_info': channel_info,
                'analyzed_images': freeze_result.get('analyzed_images', 0),
                'analysis_type': 'freeze_zapping_detection',
                'details': freeze_result
            }
            
            print(f"VideoVerify[{self.device_name}]: Freeze zapping detection complete - detected={success}, duration={freeze_duration}s")
            return final_result
            
        except Exception as e:
            print(f"VideoVerify[{self.device_name}]: Freeze zapping detection error: {e}")
            return {
                'success': False,
                'error': f'Freeze zapping detection failed: {str(e)}',
                'freeze_zapping_detected': False,
                'freeze_duration': 0.0
            }

    # =============================================================================
    # Utility Methods
    # =============================================================================

    def _log_verification(self, command: str, target: str, success: bool, details: Dict[str, Any] = None):
        """Log verification for tracking (delegated to helpers)."""
        self.verification_helpers.log_verification(command, target, success, details)