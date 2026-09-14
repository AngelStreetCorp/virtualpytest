"""
ZapStatistics - Container for zap execution statistics

Handles collection, calculation, and display of zap execution metrics.
"""

from typing import Dict, Any, List
from datetime import datetime, timezone


class ZapStatistics:
    """Container for zap execution statistics"""
    
    def __init__(self):
        self.total_iterations = 0
        self.successful_iterations = 0
        self.motion_detected_count = 0
        self.subtitles_detected_count = 0
        self.zapping_detected_count = 0
        self.detected_languages = []
        self.total_execution_time = 0
        self.analysis_results = []
        self.audio_speech_detected_count = 0
        self.audio_languages = []
        self.zapping_durations = []
        self.blackscreen_durations = []
        self.detected_channels = []
        self.channel_info_results = []
        self.freeze_detected_count = 0
        self.detection_methods_used = []
    
    @property
    def success_rate(self) -> float:
        return (self.successful_iterations / self.total_iterations * 100) if self.total_iterations > 0 else 0
    
    @property
    def motion_success_rate(self) -> float:
        return (self.motion_detected_count / self.total_iterations * 100) if self.total_iterations > 0 else 0
    
    @property
    def subtitle_success_rate(self) -> float:
        return (self.subtitles_detected_count / self.total_iterations * 100) if self.total_iterations > 0 else 0
    
    @property
    def zapping_success_rate(self) -> float:
        return (self.zapping_detected_count / self.total_iterations * 100) if self.total_iterations > 0 else 0
    
    @property
    def audio_speech_success_rate(self) -> float:
        return (self.audio_speech_detected_count / self.total_iterations * 100) if self.total_iterations > 0 else 0
    
    @property
    def average_execution_time(self) -> float:
        return self.total_execution_time / self.total_iterations if self.total_iterations > 0 else 0
    
    def add_language(self, language: str):
        """Add a detected language if not already present"""
        if language and language not in self.detected_languages:
            self.detected_languages.append(language)
    
    def add_audio_language(self, language: str):
        """Add a detected audio language if not already present"""
        if language and language not in self.audio_languages:
            self.audio_languages.append(language)
    
    def add_zapping_result(self, zapping_details: Dict[str, Any]):
        """Add enhanced zapping analysis results"""
        if zapping_details.get('success', False):
            zapping_duration = zapping_details.get('zapping_duration', 0.0)
            blackscreen_duration = zapping_details.get('blackscreen_duration', 0.0)
            
            if zapping_duration > 0:
                self.zapping_durations.append(zapping_duration)
            if blackscreen_duration > 0:
                self.blackscreen_durations.append(blackscreen_duration)
            
            channel_name = zapping_details.get('channel_name', '').strip()
            if channel_name and channel_name not in self.detected_channels:
                self.detected_channels.append(channel_name)
            
            channel_info = {
                'channel_name': zapping_details.get('channel_name', ''),
                'channel_number': zapping_details.get('channel_number', ''),
                'program_name': zapping_details.get('program_name', ''),
                'program_start_time': zapping_details.get('program_start_time', ''),
                'program_end_time': zapping_details.get('program_end_time', ''),
                'channel_confidence': zapping_details.get('channel_confidence', 0.0),
                'zapping_duration': zapping_duration,
                'blackscreen_duration': blackscreen_duration
            }
            self.channel_info_results.append(channel_info)
    
    @property
    def average_zapping_duration(self) -> float:
        """Average zapping duration in seconds"""
        return sum(self.zapping_durations) / len(self.zapping_durations) if self.zapping_durations else 0.0
    
    @property
    def average_blackscreen_duration(self) -> float:
        """Average blackscreen duration in seconds"""
        return sum(self.blackscreen_durations) / len(self.blackscreen_durations) if self.blackscreen_durations else 0.0
    
    def print_summary(self, action_command: str):
        """Print formatted statistics summary with enhanced zapping information"""
        print(f"📊 [ZapExecutor] Action execution summary:")
        print(f"   • Total iterations: {self.total_iterations}")
        print(f"   • Successful: {self.successful_iterations}")
        print(f"   • Success rate: {self.success_rate:.1f}%")
        print(f"   • Average time per iteration: {self.average_execution_time:.0f}ms")
        print(f"   • Total action time: {self.total_execution_time}ms")
        print(f"   • Motion detected: {self.motion_detected_count}/{self.total_iterations} ({self.motion_success_rate:.1f}%)")
        print(f"   • Subtitles detected: {self.subtitles_detected_count}/{self.total_iterations} ({self.subtitle_success_rate:.1f}%)")
        print(f"   • Audio speech detected: {self.audio_speech_detected_count}/{self.total_iterations} ({self.audio_speech_success_rate:.1f}%)")
        print(f"   • Zapping detected: {self.zapping_detected_count}/{self.total_iterations} ({self.zapping_success_rate:.1f}%)")
        
        if self.zapping_durations:
            print(f"   ⚡ Average zapping duration: {self.average_zapping_duration:.2f}s")
            print(f"   ⬛ Average blackscreen duration: {self.average_blackscreen_duration:.2f}s")
            min_zap = min(self.zapping_durations)
            max_zap = max(self.zapping_durations)
            print(f"   📊 Zapping duration range: {min_zap:.2f}s - {max_zap:.2f}s")
        
        if self.detected_channels:
            print(f"   📺 Channels detected: {', '.join(self.detected_channels)}")
            
            successful_channel_info = [info for info in self.channel_info_results if info.get('channel_name')]
            if successful_channel_info:
                print(f"   🎬 Channel details:")
                for i, info in enumerate(successful_channel_info, 1):
                    channel_display = info['channel_name']
                    if info.get('channel_number'):
                        channel_display += f" ({info['channel_number']})"
                    if info.get('program_name'):
                        channel_display += f" - {info['program_name']}"
                    if info.get('program_start_time') and info.get('program_end_time'):
                        channel_display += f" [{info['program_start_time']}-{info['program_end_time']}]"
                    
                    print(f"      {i}. {channel_display} (zap: {info['zapping_duration']:.2f}s, confidence: {info['channel_confidence']:.1f})")
        
        if self.detected_languages:
            print(f"   🌐 Subtitle languages detected: {', '.join(self.detected_languages)}")
        
        if self.audio_languages:
            print(f"   🎤 Audio languages detected: {', '.join(self.audio_languages)}")
        
        if self.detection_methods_used:
            blackscreen_count = self.detection_methods_used.count('blackscreen')
            freeze_count = self.detection_methods_used.count('freeze')
            
            if blackscreen_count > 0 and freeze_count > 0:
                print(f"   🔍 Learning: ⬛ Blackscreen: {blackscreen_count}, 🧊 Freeze: {freeze_count}")
            elif blackscreen_count > 0:
                print(f"   ⬛ Detection method: Blackscreen/Freeze ({blackscreen_count}/{self.total_iterations})")
            elif freeze_count > 0:
                print(f"   🧊 Detection method: Blackscreen/Freeze ({freeze_count}/{self.total_iterations})")
        
        no_motion_count = self.total_iterations - self.motion_detected_count
        if no_motion_count > 0:
            print(f"   ⚠️  {no_motion_count} zap(s) did not show content change")
    
    def store_in_context(self, context, action_command: str):
        """Store statistics in context for reporting"""
        context.custom_data.update({
            'action_command': action_command,
            'max_iteration': self.total_iterations,
            'successful_iterations': self.successful_iterations,
            'motion_detected_count': self.motion_detected_count,
            'subtitles_detected_count': self.subtitles_detected_count,
            'audio_speech_detected_count': self.audio_speech_detected_count,
            'zapping_detected_count': self.zapping_detected_count,
            'detected_languages': self.detected_languages,
            'audio_languages': self.audio_languages,
            'motion_results': [r.to_dict() for r in self.analysis_results],
            'total_action_time': self.total_execution_time,
            
            # Enhanced zapping statistics
            'zapping_durations': self.zapping_durations,
            'blackscreen_durations': self.blackscreen_durations,
            'detected_channels': self.detected_channels,
            'channel_info_results': self.channel_info_results
        })
    
    def record_iteration_to_db(self, context, iteration: int, analysis_result, start_time: float, end_time: float):
        """Record individual zap iteration to database"""
        if not context.script_result_id:
            return  # Skip if no script result ID
        
        try:
            from shared.src.lib.database.zap_results_db import record_zap_iteration
            
            # Extract channel info from zapping analysis
            zapping_details = analysis_result.zapping_details or {}
            channel_info = zapping_details.get('channel_info', {})
            
            # Debug logging for channel info extraction
            print(f"[ZapStatistics] Channel info debug:")
            print(f"  - zapping_details keys: {list(zapping_details.keys())}")
            print(f"  - channel_info extracted: {channel_info}")
            print(f"  - zapping_details success: {zapping_details.get('success')}")
            print(f"  - zapping_detected: {zapping_details.get('zapping_detected')}")
            
            # ✅ FIX: Only record to DB if zapping was detected AND we have channel information
            if not analysis_result.zapping_detected:
                print(f"⏭️  [ZapStatistics] Skipping DB recording - zapping not detected")
                return
            
            channel_name = getattr(analysis_result, 'channel_name', None)
            if not channel_name or not channel_name.strip():
                print(f"⏭️  [ZapStatistics] Skipping DB recording - no valid channel name")
                return
            
            # Calculate duration
            duration_seconds = end_time - start_time
            
            # Extract blackscreen/freeze details and timing info
            blackscreen_freeze_duration = None
            detection_method = None
            transition_type = None
            time_since_action_ms = None
            total_zap_duration_ms = None
            if analysis_result.zapping_detected:
                # Get duration from analysis_result object directly (now that we added the field)
                blackscreen_freeze_duration = getattr(analysis_result, 'blackscreen_duration', 0.0)
                # Get detection method and timing info from zapping_details
                if zapping_details:
                    detection_method = zapping_details.get('detection_method', 'blackscreen')
                    transition_type = zapping_details.get('transition_type', 'blackscreen')  # 'freeze' | 'blackscreen'
                    time_since_action_ms = zapping_details.get('time_since_action_ms')
                    total_zap_duration_ms = zapping_details.get('total_zap_duration_ms')
            
            # Record to database
            record_zap_iteration(
                script_result_id=context.script_result_id,
                team_id=context.team_id,
                host_name=context.host.host_name,
                device_name=context.selected_device.device_name,
                device_model=context.selected_device.device_model,
                userinterface_name=getattr(context, 'userinterface_name', 'unknown'),
                iteration_index=iteration,
                action_command=context.custom_data.get('action_command', 'unknown'),
                started_at=datetime.fromtimestamp(start_time, tz=timezone.utc),
                completed_at=datetime.fromtimestamp(end_time, tz=timezone.utc),
                duration_seconds=duration_seconds,
                motion_detected=analysis_result.motion_detected,
                subtitles_detected=analysis_result.subtitles_detected,
                audio_speech_detected=analysis_result.audio_speech_detected,
                blackscreen_freeze_detected=analysis_result.zapping_detected,
                subtitle_language=analysis_result.detected_language,
                subtitle_text=analysis_result.extracted_text[:500] if analysis_result.extracted_text else None,  # Limit text length
                audio_language=analysis_result.audio_language if analysis_result.audio_language != 'unknown' else None,
                audio_transcript=analysis_result.audio_transcript[:500] if analysis_result.audio_transcript else None,  # Limit text length
                blackscreen_freeze_duration_seconds=blackscreen_freeze_duration,
                transition_type=transition_type,  # 'freeze' | 'blackscreen'
                detection_method=detection_method,
                channel_name=getattr(analysis_result, 'channel_name', None) or None,
                channel_number=getattr(analysis_result, 'channel_number', None) or None,
                program_name=getattr(analysis_result, 'program_name', None) or None,
                program_start_time=getattr(analysis_result, 'program_start_time', None) or None,
                program_end_time=getattr(analysis_result, 'program_end_time', None) or None,
                audio_silence_duration=getattr(analysis_result, 'audio_silence_duration', None) or None,  # ✅ Audio silence tracking
                action_params=context.custom_data.get('action_params', None),  # ✅ Action parameters (e.g., {"key": "CHANNEL_UP"})
                time_since_action_ms=time_since_action_ms,  # ✅ NEW: Time from action to blackscreen end
                total_zap_duration_ms=total_zap_duration_ms  # ✅ NEW: Total zap duration
            )
        except Exception as e:
            print(f"⚠️ [ZapStatistics] Failed to record zap iteration to database: {e}")
