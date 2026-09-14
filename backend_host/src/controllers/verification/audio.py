"""
Audio Verification Controller Implementation

This controller provides audio analysis and verification functionality.
It can work with various audio sources including HDMI stream controllers,
audio files, or direct audio capture devices.
"""

import subprocess
import threading
import time
import os
import wave
import numpy as np
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
from ..base_controller import VerificationControllerInterface

# Import helper modules
from .audio_verification_helpers import AudioVerificationHelpers


class AudioVerificationController(VerificationControllerInterface):
    """Audio verification controller that analyzes audio from various sources."""
    
    def __init__(self, av_controller, **kwargs):
        """
        Initialize the Audio Verification controller.

        Args:
            av_controller: AV controller for capturing audio (dependency injection)
        """
        super().__init__("Audio Verification", "audio")

        # Dependency injection
        self.av_controller = av_controller

        # Validate required dependency
        if not self.av_controller:
            raise ValueError("av_controller is required for AudioVerificationController")

        # Audio analysis settings
        self.analysis_duration = 2.0  # Default analysis duration
        self.silence_threshold = 5.0  # Default silence threshold percentage

        # Temporary files for analysis
        self.temp_audio_path = Path("/tmp/audio_verification")
        self.temp_audio_path.mkdir(exist_ok=True)

        # Initialize helper modules
        self.verification_helpers = AudioVerificationHelpers(self, self.device_name)

        # Controller is always ready
        self.verification_session_id = f"audio_verify_{int(time.time())}"

        # Initialized with AV controller

    def connect(self) -> bool:
        """Connect to the audio verification system."""
        try:
            print(f"AudioVerify[{self.device_name}]: Connecting to audio verification system")
            
            print(f"AudioVerify[{self.device_name}]: Using AV controller: {self.av_controller.device_name}")
            
            # Require AV controller to have video device for audio capture
            if not hasattr(self.av_controller, 'video_device'):
                print(f"AudioVerify[{self.device_name}]: ERROR - AV controller has no video_device")
                print(f"AudioVerify[{self.device_name}]: Audio verification requires AV controller with video_device")
                return False
                
            print(f"AudioVerify[{self.device_name}]: Will capture audio from video device: {self.av_controller.video_device}")
            
            # Test FFmpeg availability for audio processing
            try:
                result = subprocess.run(['/usr/bin/ffmpeg', '-version'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    print(f"AudioVerify[{self.device_name}]: ERROR - FFmpeg not available")
                    return False
            except (subprocess.TimeoutExpired, FileNotFoundError):
                print(f"AudioVerify[{self.device_name}]: ERROR - FFmpeg not found")
                return False
            
            self.verification_session_id = f"audio_verify_{int(time.time())}"
            print(f"AudioVerify[{self.device_name}]: Connected - Session: {self.verification_session_id}")
            return True
            
        except Exception as e:
            print(f"AudioVerify[{self.device_name}]: Connection failed: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect from the audio verification system."""
        print(f"AudioVerify[{self.device_name}]: Disconnecting")
        self.verification_session_id = None
        
        # Clean up temporary files
        try:
            for temp_file in self.temp_audio_path.glob("*.wav"):
                temp_file.unlink()
        except Exception as e:
            print(f"AudioVerify[{self.device_name}]: Warning - cleanup failed: {e}")
            
        print(f"AudioVerify[{self.device_name}]: Disconnected")
        return True

    def _log_verification(self, command: str, target: str, success: bool, details: Dict[str, Any] = None):
        """Log verification for tracking (delegated to helpers)."""
        self.verification_helpers.log_verification(command, target, success, details)

    def capture_audio_sample(self, duration: float = None, source: str = "av_controller") -> str:
        """
        Capture an audio sample for analysis using the AV controller.
        
        Args:
            duration: Duration in seconds (default: self.analysis_duration)
            source: Audio source ("av_controller" or file path)
            
        Returns:
            Path to the captured audio file
        """
            
        duration = duration or self.analysis_duration
        timestamp = int(time.time())
        audio_file = self.temp_audio_path / f"audio_sample_{timestamp}.wav"
        
        try:
            if source == "av_controller":
                # Capture from AV controller (e.g., HDMI stream)
                print(f"AudioVerify[{self.device_name}]: Capturing audio from {self.av_controller.device_name}")
                # Use FFmpeg to capture audio from video device
                cmd = [
                    '/usr/bin/ffmpeg',
                    '-f', 'v4l2',
                    '-i', self.av_controller.video_device,
                    '-vn',  # No video
                    '-acodec', 'pcm_s16le',
                    '-ar', '44100',
                    '-ac', '2',
                    '-t', str(duration),
                    '-y',
                    str(audio_file)
                ]
                
            elif os.path.exists(source):
                # Use existing audio file
                print(f"AudioVerify[{self.device_name}]: Using existing audio file: {source}")
                return source
                
            else:
                print(f"AudioVerify[{self.device_name}]: ERROR - Unknown audio source: {source}")
                return None
            
            print(f"AudioVerify[{self.device_name}]: Capturing audio sample ({duration}s)")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
            
            if result.returncode == 0 and audio_file.exists():
                print(f"AudioVerify[{self.device_name}]: Audio sample captured: {audio_file}")
                return str(audio_file)
            else:
                print(f"AudioVerify[{self.device_name}]: Audio capture failed: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"AudioVerify[{self.device_name}]: Audio capture error: {e}")
            return None

    def analyze_audio_level(self, audio_file: str = None, duration: float = None) -> float:
        """
        Analyze audio level from a file or live capture.
        
        Args:
            audio_file: Path to audio file (if None, captures new sample)
            duration: Duration for live capture
            
        Returns:
            Audio level as percentage (0-100)
        """
            
        # Capture audio if no file provided
        if not audio_file:
            audio_file = self.capture_audio_sample(duration)
            if not audio_file:
                return 0.0
        
        try:
            print(f"AudioVerify[{self.device_name}]: Analyzing audio level from: {audio_file}")
            
            # Use FFmpeg to analyze audio level
            cmd = [
                '/usr/bin/ffmpeg',
                '-i', audio_file,
                '-af', 'volumedetect',
                '-vn',
                '-sn',
                '-dn',
                '-f', 'null',
                '/dev/null'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            # Parse FFmpeg output for volume information
            max_volume = -100.0  # Default very low volume
            mean_volume = -100.0
            
            for line in result.stderr.split('\n'):
                if 'max_volume:' in line:
                    try:
                        max_volume = float(line.split('max_volume:')[1].split('dB')[0].strip())
                    except:
                        pass
                elif 'mean_volume:' in line:
                    try:
                        mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    except:
                        pass
            
            # Convert dB to percentage using shared utility
            from shared.src.lib.utils.audio_transcription_utils import db_to_percentage
            level_percentage = db_to_percentage(mean_volume)
            
            print(f"AudioVerify[{self.device_name}]: Audio level: {level_percentage:.1f}% (mean: {mean_volume:.1f}dB, max: {max_volume:.1f}dB)")
            return level_percentage
            
        except Exception as e:
            print(f"AudioVerify[{self.device_name}]: Audio level analysis error: {e}")
            return 0.0

    def detect_silence(self, threshold: float = None, duration: float = None, audio_file: str = None) -> bool:
        """
        Detect if audio is silent.
        
        Args:
            threshold: Silence threshold as percentage (default: self.silence_threshold)
            duration: Duration to analyze (default: self.analysis_duration)
            audio_file: Path to audio file (if None, captures new sample)
            
        Returns:
            True if audio is silent, False otherwise
        """
        threshold = threshold or self.silence_threshold
        duration = duration or self.analysis_duration
        
        print(f"AudioVerify[{self.device_name}]: Detecting silence (threshold: {threshold}%, duration: {duration}s)")
        
        audio_level = self.analyze_audio_level(audio_file, duration)
        is_silent = audio_level < threshold
        
        result_text = "detected" if is_silent else "not detected"
        print(f"AudioVerify[{self.device_name}]: Silence {result_text} (level: {audio_level:.1f}%)")
        
        self._log_verification("silence_detection", f"threshold_{threshold}", is_silent, {
            "threshold": threshold,
            "duration": duration,
            "audio_level": audio_level
        })
        
        return is_silent

    def verify_audio_playing(self, min_level: float = 10.0, duration: float = 2.0) -> bool:
        """
        Verify that audio is playing above a minimum level.

        Uses existing audio detection from captured video frames.
        Reuses the same logic as capture_monitor.py and incident_manager.py.

        Args:
            min_level: Minimum audio level to consider as "playing" (percentage)
            duration: Duration to check audio in seconds (maps to json_count for frame analysis)
        """
        print(f"AudioVerify[{self.device_name}]: Verifying audio playback using existing frame analysis (min level: {min_level}%, duration: {duration}s)")

        # Convert duration to json_count (roughly 5 frames per second)
        json_count = max(3, int(duration * 5))  # At least 3 frames, roughly 5fps

        # Use existing audio detection from JSON files (same as capture_monitor/incident_manager)
        audio_result = self.detect_motion_from_json(json_count=json_count, strict_mode=False)

        # Check if average volume meets minimum level
        details = audio_result.get('details', [])
        if details:
            # Calculate average volume percentage across recent frames
            # Use mean_volume_db and convert to percentage (same as FFmpeg analysis)
            from shared.src.lib.utils.audio_transcription_utils import db_to_percentage
            volumes = []
            for d in details:
                if d.get('audio', False):
                    # Convert dB to percentage using shared utility
                    mean_volume_db = d.get('mean_volume_db', -100.0)
                    volume_pct = db_to_percentage(mean_volume_db)
                    volumes.append(volume_pct)

            if volumes:
                avg_volume = sum(volumes) / len(volumes)
                audio_playing = avg_volume >= min_level

                print(f"AudioVerify[{self.device_name}]: Audio {'playing' if audio_playing else 'not playing'} (avg: {avg_volume:.1f}%, min: {min_level}%, frames: {len(details)})")

                self._log_verification("audio_playing", f"min_level_{min_level}", audio_playing, {
                    "min_level": min_level,
                    "duration": duration,
                    "json_count": json_count,
                    "avg_volume": avg_volume,
                    "frames_analyzed": len(details),
                    "audio_frames": len(volumes)
                })

                return audio_playing

        # No audio data available - return False (no fallback, consistent behavior)
        print(f"AudioVerify[{self.device_name}]: No recent audio data available (checked {json_count} frames)")
        self._log_verification("audio_playing", f"min_level_{min_level}", False, {
            "min_level": min_level,
            "duration": duration,
            "json_count": json_count,
            "audio_result": audio_result  # Include full result for debugging
        })

        return False

    def analyze_audio_frequency(self, audio_file: str = None, duration: float = None) -> Dict[str, Any]:
        """
        Analyze audio frequency content.
        
        Args:
            audio_file: Path to audio file (if None, captures new sample)
            duration: Duration for live capture
            
        Returns:
            Dictionary with frequency analysis results
        """
        # Capture audio if no file provided
        if not audio_file:
            audio_file = self.capture_audio_sample(duration)
            if not audio_file:
                return {}
        
        try:
            print(f"AudioVerify[{self.device_name}]: Analyzing audio frequency content")
            
            # Use FFmpeg to extract frequency information
            cmd = [
                '/usr/bin/ffmpeg',
                '-i', audio_file,
                '-af', 'showfreqs=mode=line:fscale=log',
                '-f', 'null',
                '/dev/null'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            # Basic frequency analysis (simplified)
            analysis_result = {
                "has_low_freq": "low frequency" in result.stderr.lower(),
                "has_mid_freq": "mid frequency" in result.stderr.lower(),
                "has_high_freq": "high frequency" in result.stderr.lower(),
                "analysis_file": audio_file,
                "timestamp": time.time()
            }
            
            print(f"AudioVerify[{self.device_name}]: Frequency analysis completed")
            return analysis_result
            
        except Exception as e:
            print(f"AudioVerify[{self.device_name}]: Frequency analysis error: {e}")
            return {"error": str(e)}

    def verify_audio_contains_frequency(self, target_freq: float, tolerance: float = 50.0, 
                                      duration: float = None) -> bool:
        """
        Verify that audio contains a specific frequency.
        
        Args:
            target_freq: Target frequency in Hz
            tolerance: Frequency tolerance in Hz
            duration: Duration to analyze
            
        Returns:
            True if frequency is detected, False otherwise
        """
        print(f"AudioVerify[{self.device_name}]: Checking for frequency {target_freq}Hz (±{tolerance}Hz)")
        
        # Simplified frequency detection (in a real implementation, this would use FFT analysis)
        audio_file = self.capture_audio_sample(duration)
        if not audio_file:
            return False
            
        # For now, return a basic analysis result
        # In a real implementation, this would perform FFT analysis
        freq_analysis = self.analyze_audio_frequency(audio_file)
        
        # Simplified logic based on frequency ranges
        if target_freq < 250:  # Low frequency
            freq_detected = freq_analysis.get("has_low_freq", False)
        elif target_freq < 4000:  # Mid frequency
            freq_detected = freq_analysis.get("has_mid_freq", False)
        else:  # High frequency
            freq_detected = freq_analysis.get("has_high_freq", False)
        
        result_text = "detected" if freq_detected else "not detected"
        print(f"AudioVerify[{self.device_name}]: Frequency {target_freq}Hz {result_text}")
        
        self._log_verification("frequency_detection", f"freq_{target_freq}", freq_detected, {
            "target_frequency": target_freq,
            "tolerance": tolerance,
            "duration": duration or self.analysis_duration
        })
        
        return freq_detected

    # Implementation of required abstract methods from VerificationControllerInterface
    
    def verify_image_appears(self, image_name: str, timeout: float = 10.0, confidence: float = 0.8) -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Image verification not supported by audio controller")
        return False
        
    def verify_text_appears(self, text: str, timeout: float = 10.0, case_sensitive: bool = False) -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Text verification not supported by audio controller")
        return False
        
    def verify_element_exists(self, element_id: str, element_type: str = "any") -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Element verification not supported by audio controller")
        return False
        
    def verify_video_playing(self, motion_threshold: float = 5.0, duration: float = 3.0) -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Video verification not supported by audio controller")
        return False
        
    def verify_color_present(self, color: str, tolerance: float = 10.0) -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Color verification not supported by audio controller")
        return False
        
    def verify_screen_state(self, expected_state: str, timeout: float = 5.0) -> bool:
        """Not applicable for audio verification."""
        print(f"AudioVerify[{self.device_name}]: Screen state verification not supported by audio controller")
        return False
        
    def verify_performance_metric(self, metric_name: str, expected_value: float, tolerance: float = 10.0) -> bool:
        """Verify audio-related performance metrics."""
        if metric_name.lower() in ['audio_level', 'volume', 'loudness']:
            current_level = self.analyze_audio_level()
            tolerance_range = expected_value * (tolerance / 100)
            within_tolerance = abs(current_level - expected_value) <= tolerance_range
            
            print(f"AudioVerify[{self.device_name}]: {metric_name} = {current_level:.2f}% (expected: {expected_value}% ±{tolerance}%)")
            
            self._log_verification("performance_metric", metric_name, within_tolerance, {
                "expected": expected_value,
                "measured": current_level,
                "tolerance": tolerance
            })
            
            return within_tolerance
        else:
            print(f"AudioVerify[{self.device_name}]: Unknown audio metric: {metric_name}")
            return False
        
    def wait_and_verify(self, verification_type: str, target: str, timeout: float = 10.0, **kwargs) -> bool:
        """Generic wait and verify method for audio verification."""
        if verification_type == "waitForAudioToAppear":
            min_level = kwargs.get("min_level", 10.0)
            return self.verify_audio_playing(min_level, timeout)
        elif verification_type == "waitForAudioToDisappear":
            max_level = kwargs.get("max_level", 5.0)
            # Inverse of waitForAudioToAppear - use same logic but invert result
            return not self.verify_audio_playing(max_level, timeout)
        else:
            print(f"AudioVerify[{self.device_name}]: Unknown audio verification type: {verification_type}")
            return False
            
    def get_status(self) -> Dict[str, Any]:
        """Get controller status information."""
        return self.verification_helpers.get_controller_status()
    
    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for audio controller with typed parameters."""
        return self.verification_helpers.get_available_verifications()

    def detect_motion_from_json(self, json_count: int = 5, strict_mode: bool = True) -> Dict[str, Any]:
        """
        Detect audio activity by analyzing the last N JSON analysis files.
        Uses shared analysis utility to avoid code duplication with heatmap.
        
        Args:
            json_count: Number of recent JSON files to analyze (default: 5)
            strict_mode: If True, ALL files must show no errors. If False, majority must show no errors (default: True)
            
        Returns:
            Dict with audio-focused analysis results
        """
        try:
            print(f"AudioVerify[{self.device_name}]: Analyzing last {json_count} JSON files (strict_mode: {strict_mode})")
            
            # Extract device_id from AV controller (should be 'device1', 'device2', etc.)
            device_id = getattr(self.av_controller, 'device_id', 'device1')
            
            # Import shared analysis utility
            from  backend_host.src.lib.utils.analysis_utils import load_recent_analysis_data, analyze_motion_from_loaded_data
            
            # Load recent analysis data using shared utility (5 minutes timeframe)
            data_result = load_recent_analysis_data(device_id, timeframe_minutes=5, max_count=json_count)
            
            if not data_result['success']:
                return {
                    'success': False,
                    'audio_ok': False,
                    'audio_loss_count': 0,
                    'total_analyzed': 0,
                    'details': [],
                    'strict_mode': strict_mode,
                    'message': data_result.get('error', 'Failed to load analysis data')
                }
            
            # Analyze motion from loaded data using shared utility
            result = analyze_motion_from_loaded_data(data_result['analysis_data'], json_count, strict_mode)
            
            # Extract audio-specific results for audio controller
            audio_result = {
                'success': result['audio_ok'],  # For audio controller, success = audio_ok
                'audio_ok': result['audio_ok'],
                'audio_loss_count': result['audio_loss_count'],
                'total_analyzed': result['total_analyzed'],
                'details': [
                    {
                        'filename': detail['filename'],
                        'timestamp': detail['timestamp'],
                        'audio': detail['audio'],
                        'volume_percentage': detail['volume_percentage'],
                        'mean_volume_db': detail['mean_volume_db'],
                        'audio_ok': detail['audio_ok'],
                        'has_audio_incident': not detail['audio']
                    }
                    for detail in result['details']
                ],
                'strict_mode': result['strict_mode'],
                'message': result['message'].replace('Motion/activity', 'Audio activity').replace('motion/activity', 'audio activity')
            }
            
            print(f"AudioVerify[{self.device_name}]: Audio detection result: {audio_result.get('message', 'Unknown')}")
            
            # Log verification for tracking
            self._log_verification("audio_from_json", f"count_{json_count}_strict_{strict_mode}", audio_result['success'], {
                "json_count": json_count,
                "strict_mode": strict_mode,
                "total_analyzed": audio_result['total_analyzed'],
                "audio_loss_count": audio_result['audio_loss_count']
            })
            
            return audio_result
            
        except Exception as e:
            error_msg = f"Audio detection from JSON error: {e}"
            print(f"AudioVerify[{self.device_name}]: {error_msg}")
            return {
                'success': False,
                'audio_ok': False,
                'audio_loss_count': 0,
                'total_analyzed': 0,
                'details': [],
                'strict_mode': strict_mode,
                'message': error_msg
            }

    def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unified verification execution interface for centralized controller.
        
        Args:
            verification_config: {
                'verification_type': 'audio',
                'command': 'verify_audio_playing',
                'params': {
                    'min_level': 10.0,
                    'duration': 2.0
                }
            }
            
        Returns:
            {
                'success': bool,
                'message': str,
                'confidence': float,
                'details': dict
            }
        """
        try:
            # Extract parameters
            params = verification_config.get('params', {})
            command = verification_config.get('command', 'waitForAudioToAppear')
            
            print(f"[@controller:AudioVerification] Executing {command}")
            print(f"[@controller:AudioVerification] Parameters: {params}")
            
            # Execute verification based on command
            if command == 'waitForAudioToAppear':
                min_level = params.get('min_level', 10.0)
                duration = params.get('duration', 2.0)

                success = self.verify_audio_playing(min_level, duration)
                message = f"Audio {'playing' if success else 'not playing'} above {min_level}% level"
                details = {
                    'min_level': min_level,
                    'duration': duration
                }

            elif command == 'waitForAudioToDisappear':
                max_level = params.get('max_level', 5.0)
                duration = params.get('duration', 2.0)

                # Inverse of waitForAudioToAppear - use same logic but invert result
                # Audio has "disappeared" if it's NOT playing above max_level
                audio_is_playing = self.verify_audio_playing(max_level, duration)
                success = not audio_is_playing  # Invert the result
                message = f"Audio {'stopped' if success else 'still playing'} below {max_level}% level"
                details = {
                    'max_level': max_level,
                    'duration': duration
                }

            elif command == 'DetectAudioSpeech':
                # Use AudioAIHelpers for actual speech detection with Whisper.
                # Restored: the handler was dropped in f7808ca74 but ZapExecutor
                # still issues this command for per-zap audio analysis.
                try:
                    from backend_host.src.controllers.verification.audio_ai_helpers import AudioAIHelpers
                    audio_ai = AudioAIHelpers(self.av_controller, self.device_name)

                    # Get recent audio segments and analyze with AI
                    segment_count = int(params.get('json_count', 4))  # Use json_count param for consistency
                    audio_files = audio_ai.get_recent_audio_segments(segment_count=segment_count)
                    if audio_files:
                        analysis = audio_ai.analyze_audio_segments_ai(audio_files, upload_to_r2=True)
                        success = analysis.get('success', False) and bool(analysis.get('combined_transcript', '').strip())
                        transcript = analysis.get('combined_transcript', '')
                        language = analysis.get('detected_language', 'unknown')
                        message = f"Speech {'detected' if success else 'not detected'}: '{transcript[:50]}...' ({language})" if success else "No speech detected"
                        details = analysis
                    else:
                        success = False
                        message = "No audio segments available for speech detection"
                        details = {'error': 'No audio segments'}

                except ImportError:
                    success = False
                    message = "AudioAI not available for speech detection"
                    details = {'error': 'AudioAI not available'}

            else:
                return {
                    'success': False,
                    'message': f'Unknown audio verification command: {command}',
                    'confidence': 0.0,
                    'details': {'error': f'Unsupported command: {command}'}
                }
            
            # Return unified format
            return {
                'success': success,
                'message': message,
                'confidence': 1.0 if success else 0.0,
                'details': details
            }
            
        except Exception as e:
            print(f"[@controller:AudioVerification] Execution error: {e}")
            return {
                'success': False,
                'message': f'Audio verification execution error: {str(e)}',
                'confidence': 0.0,
                'details': {'error': str(e)}
            }
