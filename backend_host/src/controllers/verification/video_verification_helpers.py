"""
Video Verification Logic Helpers

High-level verification workflow helpers for the VideoVerificationController:
1. Verification execution and orchestration
2. Configuration management and validation
3. Verification result formatting
4. Logging and tracking utilities
5. Status and capability reporting

This helper handles the business logic and workflow orchestration
for video verification operations.
"""

import time
import os
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple


class VideoVerificationHelpers:
    """High-level verification logic and workflow orchestration."""
    
    def __init__(self, controller_instance, device_name: str = "VideoVerification"):
        """
        Initialize video verification helpers.
        
        Args:
            controller_instance: Reference to the main VideoVerificationController
            device_name: Name for logging purposes
        """
        self.controller = controller_instance
        self.device_name = device_name
        self.verification_logs = []
    
    # =============================================================================
    # Verification Execution Orchestration
    # =============================================================================
    
    def execute_verification_workflow(self, verification_config: Dict[str, Any], image_source_url: str = None) -> Dict[str, Any]:
        """
        Execute a verification workflow with proper error handling and logging.
        
        Args:
            verification_config: Verification configuration dictionary
            image_source_url: Optional source image path or array of paths
            
        Returns:
            Standardized verification result dictionary
        """
        try:
            # Extract and validate parameters
            params = verification_config.get('params', {})
            command = verification_config.get('command', 'WaitForVideoToAppear')
            
            print(f"VideoVerification[{self.device_name}]: Executing {command}")
            print(f"VideoVerification[{self.device_name}]: Parameters: {params}")
            print(f"VideoVerification[{self.device_name}]: DEBUG: Received image_source_url: {image_source_url}")
            
            # Parse image source for frame analysis commands
            image_paths = self._parse_image_source(image_source_url)
            print(f"VideoVerification[{self.device_name}]: DEBUG: Parsed image_paths: {image_paths}")
            
            # Route to appropriate verification method
            if command in ['WaitForVideoToAppear', 'WaitForVideoToDisappear']:
                return self._execute_video_playback_verification(command, params)
            elif command == 'DetectMotion':
                return self._execute_motion_detection(params)
            elif command == 'WaitForVideoChange':
                return self._execute_video_change_detection(params)
            elif command == 'VerifyColorPresent':
                return self._execute_color_verification(params)
            elif command == 'VerifyScreenState':
                return self._execute_screen_state_verification(params)
            elif command in ['DetectBlackscreen', 'DetectFreeze', 'DetectSubtitles', 'DetectSubtitlesAI']:
                print(f"VideoVerification[{self.device_name}]: DEBUG: Calling _execute_content_analysis with image_paths: {image_paths}")
                return self._execute_content_analysis(command, params, image_paths)
            elif command == 'DetectMotionFromJson':
                return self._execute_json_motion_analysis(params)
            elif command == 'DetectZapping':
                # Get capture folder same as main branch (don't use image_source_url)
                folder_path = getattr(self.controller.av_controller, 'video_capture_path', None)
                return self._execute_zapping_detection(params, folder_path)
            else:
                return self._create_error_result(f'Unknown verification command: {command}')
            
        except Exception as e:
            print(f"VideoVerification[{self.device_name}]: Execution error: {e}")
            return self._create_error_result(f'Verification execution error: {str(e)}')

    def _execute_video_playback_verification(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute video playback verification (appear/disappear)."""
        try:
            motion_threshold = float(params.get('motion_threshold', 5.0))
            duration = int(params.get('duration', 3))
            timeout = int(params.get('timeout', 10))
            # Without this the check always measured the centre 60% of the frame,
            # which is the wrong place on any screen where the player does not fill
            # it — a portrait phone puts the video across the top and static page
            # furniture in the middle.
            area = params.get('area') or None
            
            if command == 'WaitForVideoToAppear':
                success = self.controller.waitForVideoToAppear(motion_threshold, duration, timeout, area)
                message = f"Video {'appeared' if success else 'did not appear'} (motion threshold: {motion_threshold}%)"
            else:  # WaitForVideoToDisappear
                success = self.controller.waitForVideoToDisappear(motion_threshold, duration, timeout, area)
                message = f"Video {'disappeared' if success else 'still present'} (motion threshold: {motion_threshold}%)"
            
            details = {
                'motion_threshold': motion_threshold,
                'duration': duration,
                'timeout': timeout,
                'area': area
            }
            
            return self._create_success_result(success, message, details)
            
        except Exception as e:
            return self._create_error_result(f'Video playback verification error: {str(e)}')

    def _execute_motion_detection(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute motion detection verification."""
        try:
            duration = int(params.get('duration', 3))
            threshold = float(params.get('threshold', 5.0))
            area = params.get('area')  # Optional {x,y,width,height} to exclude animated overlays

            success = self.controller.detect_motion(duration, threshold, area)
            message = f"Motion {'detected' if success else 'not detected'}"
            details = {
                'duration': duration,
                'threshold': threshold,
                'area': area
            }
            # Surface the exact cropped frames that were compared (for the report thumbnails).
            crops = getattr(getattr(self.controller, 'analysis_helpers', None), 'last_motion_crops', None)
            if crops:
                details['motion_images'] = crops.get('images', [])
                details['change_percentage'] = crops.get('change_percentage')
                details['area'] = crops.get('area', area)
            
            return self._create_success_result(success, message, details)
            
        except Exception as e:
            return self._create_error_result(f'Motion detection error: {str(e)}')

    def _execute_video_change_detection(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute video change detection verification."""
        try:
            timeout = int(params.get('timeout', 10))
            threshold = float(params.get('threshold', 10.0))
            
            success = self.controller.wait_for_video_change(timeout, threshold)
            message = f"Video change {'detected' if success else 'not detected'}"
            details = {
                'timeout': timeout,
                'threshold': threshold
            }
            
            return self._create_success_result(success, message, details)
            
        except Exception as e:
            return self._create_error_result(f'Video change detection error: {str(e)}')

    def _execute_color_verification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute color presence verification."""
        try:
            color = params.get('color')
            if not color:
                return self._create_error_result('No color specified for color verification')
            
            tolerance = params.get('tolerance', 10.0)
            
            success = self.controller.verify_color_present(color, tolerance)
            message = f"Color '{color}' {'found' if success else 'not found'}"
            details = {
                'color': color,
                'tolerance': tolerance
            }
            
            return self._create_success_result(success, message, details)
            
        except Exception as e:
            return self._create_error_result(f'Color verification error: {str(e)}')

    def _execute_screen_state_verification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute screen state verification."""
        try:
            expected_state = params.get('expected_state')
            if not expected_state:
                return self._create_error_result('No expected state specified for screen state verification')
            
            timeout = int(params.get('timeout', 5))
            
            success = self.controller.verify_screen_state(expected_state, timeout)
            message = f"Screen state '{expected_state}' {'verified' if success else 'not verified'}"
            details = {
                'expected_state': expected_state,
                'timeout': timeout
            }
            
            return self._create_success_result(success, message, details)
            
        except Exception as e:
            return self._create_error_result(f'Screen state verification error: {str(e)}')

    def _execute_content_analysis(self, command: str, params: Dict[str, Any], image_paths: List[str]) -> Dict[str, Any]:
        """Execute content analysis verification (blackscreen, freeze, subtitles)."""
        try:
            if command == 'DetectBlackscreen':
                threshold = params.get('threshold', 10)
                result = self.controller.detect_blackscreen(image_paths, threshold)
                success = result.get('success', False) and result.get('blackscreen_detected', False)
                message = f"Blackscreen {'detected' if success else 'not detected'}"
                
            elif command == 'DetectFreeze':
                freeze_threshold = params.get('freeze_threshold', 1.0)
                result = self.controller.detect_freeze(image_paths, freeze_threshold)
                success = result.get('success', False) and result.get('freeze_detected', False)
                message = f"Freeze {'detected' if success else 'not detected'}"
                
            elif command == 'DetectSubtitles':
                extract_text = params.get('extract_text', True)
                result = self.controller.detect_subtitles(image_paths, extract_text)
                success = result.get('success', False) and result.get('subtitles_detected', False)
                message = f"Subtitles {'detected' if success else 'not detected'}"
                
            elif command == 'DetectSubtitlesAI':
                extract_text = params.get('extract_text', True)
                print(f"VideoVerification[{self.device_name}]: DEBUG: Calling detect_subtitles_ai with image_paths: {image_paths}")
                result = self.controller.detect_subtitles_ai(image_paths, extract_text)
                success = result.get('success', False) and result.get('subtitles_detected', False)
                message = f"AI Subtitles {'detected' if success else 'not detected'}"
            
            return {
                'success': success,
                'message': message,
                'confidence': result.get('confidence', 1.0 if success else 0.0),
                'details': result
            }
            
        except Exception as e:
            return self._create_error_result(f'Content analysis error: {str(e)}')

    def _execute_json_motion_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute JSON motion analysis verification with enhanced audio-aware detection."""
        try:
            json_count = int(params.get('json_count', 5))
            strict_mode = params.get('strict_mode', True)
            
            result = self.controller.detect_motion_from_json(json_count, strict_mode)
            success = result.get('success', False)
            
            # Enhanced messaging to show what triggered the detection
            if success:
                video_ok = result.get('video_ok', False)
                audio_ok = result.get('audio_ok', False)
                
                if video_ok and audio_ok:
                    message = "Motion detected - both video and audio content present"
                elif video_ok:
                    message = "Motion detected - video motion detected"
                elif audio_ok:
                    message = "Motion detected - audio content present (video motion minimal)"
                else:
                    message = result.get('message', "Motion detected from JSON analysis")
            else:
                message = result.get('message', "Motion not detected from JSON analysis")
            
            # Add source image URL for thumbnail display (like subtitle verification)
            source_image_url = None
            if success and result.get('details'):
                # Get the most recent analyzed image for thumbnail
                details = result.get('details', [])
                if details and len(details) > 0:
                    most_recent_detail = details[0]  # Most recent is first in the list
                    if 'filename' in most_recent_detail:
                        # Build thumbnail URL from filename (use thumbnail for performance)
                        filename = most_recent_detail['filename']
                        thumbnail_filename = filename.replace('.jpg', '_thumbnail.jpg')
                        source_image_url = f"/host/stream/capture1/captures/{thumbnail_filename}"
            
            # Create motion_analysis_images array for report display (matching ZapExecutor behavior)
            motion_analysis_images = []
            details = result.get('details', [])
            if details and isinstance(details, list):
                print(f"🔍 [VideoVerificationHelpers] DEBUG: Processing {len(details)} motion details for thumbnails")
                from shared.src.lib.utils.device_utils import add_existing_image_to_context
                
                # Get context from controller's device (if available)
                context = getattr(self.controller, '_current_context', None)
                if context:
                    # Reverse details to show chronologically (oldest first) in report
                    chronological_details = list(reversed(details[:3]))  # Take first 3, then reverse
                    
                    for i, detail in enumerate(chronological_details):
                        print(f"🔍 [VideoVerificationHelpers] DEBUG: Processing detail[{i}] (chronological): {detail}")
                        if isinstance(detail, dict):
                            filename = detail.get('filename', '')
                            
                            # Use centralized function - handles hot/cold, fails fast if missing
                            device = getattr(self.controller, 'device', None)
                            if device:
                                image_path = add_existing_image_to_context(device, filename, context)
                                
                                if image_path:
                                    # Image found and added to context
                                    print(f"🔍 [VideoVerificationHelpers] DEBUG: Motion image found: {filename} -> {image_path}")
                                    motion_analysis_images.append({
                                        'path': image_path,
                                        'filename': filename,
                                        'timestamp': detail.get('timestamp', ''),
                                        'analysis_data': {
                                            'freeze': detail.get('freeze', False),
                                            'blackscreen': detail.get('blackscreen', False),
                                            'audio': detail.get('audio', True)
                                        }
                                    })
                                else:
                                    # Image not found - fail fast, skip
                                    print(f"⚠️ [VideoVerificationHelpers] Motion image missing, skipping: {filename}")
                    
                    print(f"🔍 [VideoVerificationHelpers] DEBUG: Created {len(motion_analysis_images)} motion_analysis_images (from {len(chronological_details)} analyzed)")
                else:
                    print(f"⚠️ [VideoVerificationHelpers] No context available for motion image collection")
            
            return {
                'success': success,
                'message': message,
                'confidence': result.get('confidence', 1.0 if success else 0.0),
                'sourceImageUrl': source_image_url,  # Add thumbnail URL for frontend
                'details': result,
                'motion_analysis_images': motion_analysis_images  # Add images array for report display
            }
            
        except Exception as e:
            return self._create_error_result(f'JSON motion analysis error: {str(e)}')

    def _execute_zapping_detection(self, params: Dict[str, Any], folder_path: str) -> Dict[str, Any]:
        """Execute zapping detection verification with smart dual-method approach (same as main branch)."""
        try:
            key_release_timestamp = float(params.get('key_release_timestamp', 0.0))
            analysis_rectangle = params.get('analysis_rectangle')
            banner_region = params.get('banner_region')
            max_images = int(params.get('max_images', 10))
            
            if key_release_timestamp <= 0:
                return self._create_error_result('Invalid key release timestamp')
            
            if not folder_path:
                return self._create_error_result('No folder path provided for zapping detection')
            
            # Smart dual-method zapping detection (same as main branch)
            print(f"VideoVerification[{self.device_name}]: Smart zapping detection - trying blackscreen first...")
            
            # Try blackscreen detection first
            zapping_result = self.controller.content_helpers.detect_zapping_sequence(
                folder_path, key_release_timestamp, analysis_rectangle, max_images, banner_region
            )
            
            # If blackscreen succeeds, use it
            if zapping_result.get('success', False) and zapping_result.get('zapping_detected', False):
                print(f"VideoVerification[{self.device_name}]: ✅ Blackscreen detection successful")
                zapping_result['detection_method'] = 'blackscreen'
            else:
                # Blackscreen failed, try freeze detection as fallback
                print(f"VideoVerification[{self.device_name}]: Blackscreen failed, trying freeze detection...")
                
                try:
                    # Try freeze detection using existing freeze detection logic
                    freeze_result = self.controller.content_helpers.detect_freeze_zapping_sequence(
                        folder_path, key_release_timestamp, 
                        analysis_rectangle=params.get('analysis_rectangle'),
                        max_images=max_images,
                        banner_region=params.get('banner_region')
                    )
                    
                    if freeze_result.get('success', False) and freeze_result.get('freeze_zapping_detected', False):
                        print(f"VideoVerification[{self.device_name}]: ✅ Freeze detection successful")
                        # Convert freeze result to zapping result format
                        zapping_result = {
                            'success': True,
                            'zapping_detected': True,
                            'detection_method': 'freeze',
                            'freeze_sequence': freeze_result.get('freeze_sequence', {}),
                            'first_content_after_blackscreen': freeze_result.get('first_content_after_freeze'),
                            'analyzed_images': freeze_result.get('analyzed_images', []),
                            'message': 'Zapping detected via freeze detection'
                        }
                    else:
                        print(f"VideoVerification[{self.device_name}]: ❌ Both blackscreen and freeze detection failed")
                        return {
                            'success': False,
                            'message': 'Zapping not detected - both blackscreen and freeze methods failed',
                            'confidence': 0.0,
                            'details': {
                                'blackscreen_result': zapping_result,
                                'freeze_result': freeze_result,
                                'detection_method': 'dual_method_failed'
                            }
                        }
                        
                except Exception as freeze_error:
                    print(f"VideoVerification[{self.device_name}]: Freeze detection error: {freeze_error}")
                    # Return original blackscreen failure
                    return {
                        'success': False,
                        'message': f"Zapping detection failed: {zapping_result.get('error', 'Blackscreen failed, freeze errored')}",
                        'confidence': 0.0,
                        'details': zapping_result
                    }
            
            # If zapping was detected and we have banner region, try to extract channel info
            channel_info = {}
            if (zapping_result.get('zapping_detected', False) and 
                banner_region and 
                zapping_result.get('first_content_after_blackscreen')):
                
                try:
                    # Find the image where blackscreen ended (first content after zapping)
                    end_image_name = zapping_result.get('first_content_after_blackscreen', '')
                    if end_image_name:
                        # Reconstruct full path to the end image (use centralized storage for hot/cold)
                        import os
                        from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
                        captures_folder = get_capture_storage_path(folder_path, 'captures')
                        end_image_path = os.path.join(captures_folder, end_image_name)
                        
                        # Check if banner is present before expensive AI call
                        if self.controller.ai_helpers.detect_banner_presence(end_image_path, banner_region):
                            print(f"VideoVerification[{self.device_name}]: Banner detected, analyzing with AI")
                            banner_result = self.controller.ai_helpers.analyze_channel_banner_ai(end_image_path, banner_region)
                            
                            if banner_result.get('success', False):
                                # Extract channel info regardless of banner_detected flag (preserve partial info)
                                extracted_info = banner_result.get('channel_info', {})
                                
                                # Check if we have any useful information
                                has_useful_info = any([
                                    extracted_info.get('channel_name'),
                                    extracted_info.get('channel_number'),
                                    extracted_info.get('program_name'),
                                    extracted_info.get('start_time'),
                                    extracted_info.get('end_time')
                                ])
                                
                                if has_useful_info:
                                    channel_info = extracted_info
                                    banner_status = "detected" if banner_result.get('banner_detected', False) else "partial info found"
                                    print(f"VideoVerification[{self.device_name}]: Channel info {banner_status}: {channel_info}")
                                else:
                                    print(f"VideoVerification[{self.device_name}]: No useful channel information found")
                            else:
                                print(f"VideoVerification[{self.device_name}]: Banner analysis failed")
                        else:
                            print(f"VideoVerification[{self.device_name}]: No banner presence detected, skipping AI analysis")
                            
                except Exception as e:
                    print(f"VideoVerification[{self.device_name}]: Banner analysis error (OpenCV/image processing): {e}")
                    print(f"VideoVerification[{self.device_name}]: Continuing with zapping detection without banner info")
                    # channel_info remains empty dict - zapping detection will still work
            
            # Compile comprehensive result
            success = zapping_result.get('zapping_detected', False)
            blackscreen_duration = zapping_result.get('blackscreen_duration', 0.0)
            
            message_parts = []
            if success:
                message_parts.append(f"Zapping detected (duration: {blackscreen_duration}s)")
                if channel_info.get('channel_name'):
                    message_parts.append(f"Channel: {channel_info['channel_name']}")
                if channel_info.get('program_name'):
                    message_parts.append(f"Program: {channel_info['program_name']}")
            else:
                message_parts.append("No zapping detected")
            
            message = ", ".join(message_parts)
            
            # Enhanced result with channel info
            enhanced_result = zapping_result.copy()
            enhanced_result['channel_info'] = channel_info
            
            return {
                'success': success,
                'message': message,
                'confidence': zapping_result.get('confidence', 1.0 if success else 0.0),
                'details': enhanced_result
            }
            
        except Exception as e:
            return self._create_error_result(f'Zapping detection error: {str(e)}')

    # =============================================================================
    # Verification Configuration and Validation
    # =============================================================================
    
    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for video controller with typed parameters."""
        from shared.src.lib.schemas.param_types import create_param, ParamType
        
        return [
            {
                'command': 'WaitForVideoToAppear',
                'params': {
                    'area': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Region to restrict motion to; defaults to centre 60% - set it wherever the player does not fill the frame (a portrait phone draws it across the top)"
                    ),
                    'motion_threshold': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=5.0,
                        description="Motion threshold for detection",
                        min=0.0,
                        max=100.0
                    ),
                    'duration': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=3.0,
                        description="Duration to check (seconds)",
                        min=0.1,
                        max=30.0
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Maximum time to wait (seconds)"
                    )
                },
                'verification_type': 'video',
                'description': 'Wait for video to appear'
            },
            {
                'command': 'WaitForVideoToDisappear',
                'params': {
                    'area': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Region to restrict motion to; defaults to centre 60% - set it wherever the player does not fill the frame (a portrait phone draws it across the top)"
                    ),
                    'motion_threshold': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=5.0,
                        description="Motion threshold for detection",
                        min=0.0,
                        max=100.0
                    ),
                    'duration': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=3.0,
                        description="Duration to check (seconds)",
                        min=0.1,
                        max=30.0
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Maximum time to wait (seconds)"
                    )
                },
                'verification_type': 'video',
                'description': 'Wait for video to disappear'
            },
            {
                'command': 'DetectMotion',
                'params': {
                    'duration': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=3.0,
                        description="Duration to analyze (seconds)",
                        min=0.1,
                        max=30.0
                    ),
                    'threshold': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=5.0,
                        description="Motion detection threshold",
                        min=0.0,
                        max=100.0
                    ),
                    'area': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Region to restrict motion to; defaults to centre 60% (excludes header/footer/side overlays)"
                    )
                },
                'verification_type': 'video',
                'description': 'Detect motion'
            },
            {
                'command': 'DetectMotionFromJson',
                'params': {
                    'json_count': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=5,
                        description="Number of JSON files to analyze",
                        min=1,
                        max=100
                    ),
                    'strict_mode': create_param(
                        ParamType.BOOLEAN,
                        required=False,
                        default=False,
                        description="Use strict mode for detection"
                    )
                },
                'verification_type': 'video',
                'description': 'Detect motion from JSON'
            },
            {
                'command': 'DetectFreeze',
                'params': {
                    'freeze_threshold': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=1.0,
                        description="Freeze detection threshold",
                        min=0.0,
                        max=100.0
                    )
                },
                'verification_type': 'video',
                'description': 'Detect freeze'
            },
            {
                'command': 'DetectSubtitles',
                'params': {
                    'extract_text': create_param(
                        ParamType.BOOLEAN,
                        required=False,
                        default=True,
                        description="Extract subtitle text via OCR"
                    )
                },
                'verification_type': 'video',
                'description': 'Detect subtitles OCR'
            },
            {
                'command': 'DetectSubtitlesAI',
                'params': {
                    'extract_text': create_param(
                        ParamType.BOOLEAN,
                        required=False,
                        default=True,
                        description="Extract subtitle text via AI"
                    )
                },
                'verification_type': 'video',
                'description': 'Detect subtitles AI'
            },
            {
                'command': 'DetectZapping',
                'params': {
                    'key_release_timestamp': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0.0,
                        description="Timestamp when zapping key was released",
                        min=0.0
                    ),
                    'analysis_rectangle': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Rectangle for blackscreen analysis (exclude banner)"
                    ),
                    'banner_region': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Region where banner appears for AI analysis"
                    ),
                    'max_images': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10,
                        description="Maximum images to analyze",
                        min=1,
                        max=100
                    )
                },
                'verification_type': 'video',
                'description': 'Detect zapping'
            }
        ]

    def validate_verification_config(self, verification_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate verification configuration.
        
        Args:
            verification_config: Configuration to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            if not isinstance(verification_config, dict):
                return False, "Configuration must be a dictionary"
            
            command = verification_config.get('command')
            if not command:
                return False, "Missing 'command' field in configuration"
            
            params = verification_config.get('params', {})
            if not isinstance(params, dict):
                return False, "Parameters must be a dictionary"
            
            # Validate specific command requirements
            if command in ['VerifyColorPresent'] and not params.get('color'):
                return False, f"Command '{command}' requires 'color' parameter"
            
            if command in ['VerifyScreenState'] and not params.get('expected_state'):
                return False, f"Command '{command}' requires 'expected_state' parameter"
            
            # Validate numeric parameters
            numeric_params = {
                'motion_threshold': (0.0, 100.0),
                'duration': (0.1, 60.0),
                'timeout': (1.0, 300.0),
                'threshold': (0.0, 100.0),
                'tolerance': (0.0, 100.0),
                'freeze_threshold': (0.0, 10.0),
                'json_count': (1, 20)
            }
            
            for param_name, (min_val, max_val) in numeric_params.items():
                if param_name in params:
                    try:
                        value = float(params[param_name])
                        if not (min_val <= value <= max_val):
                            return False, f"Parameter '{param_name}' must be between {min_val} and {max_val}"
                    except (ValueError, TypeError):
                        return False, f"Parameter '{param_name}' must be a number"
            
            return True, ""
            
        except Exception as e:
            return False, f"Configuration validation error: {str(e)}"

    # =============================================================================
    # Status and Capability Reporting
    # =============================================================================
    
    def get_controller_status(self) -> Dict[str, Any]:
        """Get comprehensive controller status information."""
        return {
            'controller_type': self.controller.controller_type,
            'device_name': self.controller.device_name,
            'connected': True,
            'session_id': self.controller.verification_session_id,
            'acquisition_source': self.controller.av_controller.device_name if self.controller.av_controller else None,
            'capabilities': [
                'motion_detection', 'video_playback_verification',
                'color_verification', 'screen_state_verification',
                'video_change_detection', 'performance_metrics',
                'blackscreen_detection', 'freeze_detection',
                'subtitle_detection', 'ai_analysis', 'json_motion_analysis'
            ],
            'helper_modules': [
                'video_analysis_helpers', 'video_content_helpers',
                'video_ai_helpers', 'video_verification_helpers'
            ],
            'verification_logs_count': len(self.verification_logs)
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for the controller."""
        try:
            recent_logs = self.verification_logs[-10:] if self.verification_logs else []
            
            if not recent_logs:
                return {
                    'total_verifications': 0,
                    'success_rate': 0.0,
                    'average_duration': 0.0,
                    'most_common_commands': []
                }
            
            successful = sum(1 for log in recent_logs if log.get('success', False))
            total = len(recent_logs)
            success_rate = (successful / total) * 100 if total > 0 else 0.0
            
            # Calculate average duration for logs that have it
            durations = [log.get('duration', 0) for log in recent_logs if log.get('duration')]
            average_duration = sum(durations) / len(durations) if durations else 0.0
            
            # Count command usage
            commands = [log.get('command', 'unknown') for log in recent_logs]
            command_counts = {}
            for cmd in commands:
                command_counts[cmd] = command_counts.get(cmd, 0) + 1
            
            most_common = sorted(command_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            
            return {
                'total_verifications': total,
                'success_rate': round(success_rate, 1),
                'average_duration': round(average_duration, 2),
                'most_common_commands': most_common
            }
            
        except Exception as e:
            print(f"VideoVerification[{self.device_name}]: Performance metrics error: {e}")
            return {
                'total_verifications': 0,
                'success_rate': 0.0,
                'average_duration': 0.0,
                'most_common_commands': [],
                'error': str(e)
            }

    # =============================================================================
    # Utility Methods
    # =============================================================================
    
    def _parse_image_source(self, image_source_url: str) -> Optional[List[str]]:
        """Parse image source URL into list of image paths."""
        if not image_source_url:
            return None
        
        if isinstance(image_source_url, str):
            # Single image or comma-separated list
            if ',' in image_source_url:
                return [path.strip() for path in image_source_url.split(',')]
            else:
                return [image_source_url]
        elif isinstance(image_source_url, list):
            return image_source_url
        
        return None

    def _create_success_result(self, success: bool, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """Create a standardized success result."""
        return {
            'success': success,
            'message': message,
            'confidence': 1.0 if success else 0.0,
            'details': details
        }

    def _create_error_result(self, error_message: str) -> Dict[str, Any]:
        """Create a standardized error result."""
        return {
            'success': False,
            'message': error_message,
            'confidence': 0.0,
            'details': {'error': error_message}
        }

    def log_verification(self, command: str, target: str, success: bool, details: Dict[str, Any] = None, duration: float = None):
        """
        Log a verification operation for tracking and analysis.
        
        Args:
            command: Verification command executed
            target: Target of the verification (e.g., color name, state name)
            success: Whether the verification succeeded
            details: Additional details about the verification
            duration: Duration of the verification in seconds
        """
        try:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'command': command,
                'target': target,
                'success': success,
                'details': details or {},
                'duration': duration
            }
            
            self.verification_logs.append(log_entry)
            
            # Keep only the last 100 logs to prevent memory issues
            if len(self.verification_logs) > 100:
                self.verification_logs = self.verification_logs[-100:]
            
        except Exception as e:
            print(f"VideoVerification[{self.device_name}]: Logging error: {e}")

    def get_verification_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent verification history.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of recent verification log entries
        """
        return self.verification_logs[-limit:] if self.verification_logs else []

    def clear_verification_history(self):
        """Clear verification history logs."""
        self.verification_logs.clear()
        print(f"VideoVerification[{self.device_name}]: Verification history cleared")