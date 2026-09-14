"""
Audio Dubbing Helpers - Fast implementation for voice dubbing and sync without audio separation
"""

import os
import tempfile
import subprocess
from typing import Dict, Any, Optional


class AudioDubbingHelpers:
    """Fast audio dubbing and sync helpers - no audio separations."""
    
    def __init__(self, av_controller, device_name: str = "DubbingHelper"):
        self.av_controller = av_controller
        self.device_name = device_name.replace(" ", "_")  # Clean device name for filenames
        self.temp_dir = "/tmp"
        
    def get_file_paths(self, language: str, original_video_dir: str = "/tmp") -> Dict[str, str]:
        """Simple file paths - no audio separation, just clean dubbing/sync"""
        
        return {
            'original_audio': f"{original_video_dir}/restart_original_audio.wav",
            'dubbed_voice_edge': f"{original_video_dir}/restart_{language}_dubbed_voice_edge.wav",
            'dubbed_voice_edge_mp3': f"{original_video_dir}/restart_{language}_dubbed_voice_edge.mp3",
            'final_video': f"{original_video_dir}/restart_{language}_dubbed_video.mp4"
        }
        
    
    
    # =============================================================================
    # Dubbing Process Methods
    # =============================================================================
    
    def prepare_dubbing_audio(self, video_file: str, original_video_dir: str) -> Dict[str, Any]:
        """Step 1: Audio extraction only - no separation needed (~2-3s)"""
        import time
        start_time = time.time()
        
        try:
            # Extract audio from video (only step needed for dubbing)
            paths = self.get_file_paths('temp', original_video_dir)
            audio_file = paths['original_audio']
            
            print(f"Dubbing[{self.device_name}]: Step 1 - Extracting audio from video...")
            subprocess.run(['ffmpeg', '-i', video_file, '-vn', '-acodec', 'pcm_s16le', 
                          '-ar', '44100', '-ac', '2', audio_file, '-y'], 
                          capture_output=True, check=True)
            
            print(f"Dubbing[{self.device_name}]: Audio extraction completed - no separation needed")
            
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Step 1 completed in {duration:.1f}s")
            
            return {
                'success': True,
                'step': 'audio_prepared',
                'duration_seconds': round(duration, 1),
                'message': f'Audio extracted in {duration:.1f}s (no separation)',
                'method': 'simple'
            }
            
        except Exception as e:
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Step 1 failed after {duration:.1f}s: {e}")
            return {
                'success': False,
                'error': f'Audio extraction failed: {str(e)}',
                'duration_seconds': round(duration, 1)
            }
    
    
    def generate_edge_speech(self, text: str, language: str, original_video_dir: str) -> Dict[str, Any]:
        """Generate Edge-TTS speech (~3-5s)"""
        import time
        start_time = time.time()
        
        try:
            paths = self.get_file_paths(language, original_video_dir)
            
            print(f"Dubbing[{self.device_name}]: Step 3 - Generating Edge-TTS speech for {language}...")
            
            # Use shared utility (single source of truth)
            from backend_host.src.lib.utils.audio_utils import generate_edge_tts_audio
            
            # Generate MP3 using shared utility
            temp_mp3 = f"/tmp/{self.device_name}_{language}_edge_temp.mp3"
            success = generate_edge_tts_audio(text, language, temp_mp3)
            
            if not success:
                raise Exception("Edge-TTS generation failed")
            
            # Convert to WAV and copy MP3
            subprocess.run(['ffmpeg', '-i', temp_mp3, '-ar', '44100', '-ac', '2', paths['dubbed_voice_edge'], '-y'], 
                          capture_output=True, check=True)
            subprocess.run(['cp', temp_mp3, paths['dubbed_voice_edge_mp3']], check=True)
            os.remove(temp_mp3)
            
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Step 3 completed in {duration:.1f}s")
            
            # Build URLs for preview
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from  backend_host.src.lib.utils.host_utils import get_host_instance
            
            try:
                host = get_host_instance()
                edge_mp3_url = buildHostImageUrl(host.to_dict(), paths['dubbed_voice_edge_mp3'])
            except:
                # Fallback URL construction
                edge_mp3_url = f"/host/stream/{os.path.basename(paths['dubbed_voice_edge_mp3'])}"
            
            return {
                'success': True,
                'duration_seconds': round(duration, 1),
                'edge_audio_url': edge_mp3_url,
                'edge_wav_path': paths['dubbed_voice_edge']
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def create_dubbed_video(self, video_file: str, language: str, voice_choice: str = 'edge') -> Dict[str, Any]:
        """Step 3: Create final dubbed video (~3-5s)"""
        import time
        start_time = time.time()
        
        try:
            original_video_dir = os.path.dirname(video_file)
            
            print(f"Dubbing[{self.device_name}]: Step 3 - Creating dubbed video...")
            
            # Replace original audio with Edge-TTS audio
            paths = self.get_file_paths(language, original_video_dir)
            
            # Simple FFmpeg: replace original audio with new dubbed audio
            subprocess.run([
                'ffmpeg', '-i', video_file, '-i', paths['dubbed_voice_edge'],
                '-c:v', 'copy',      # Copy video unchanged
                '-c:a', 'aac',       # Encode new audio
                '-map', '0:v:0',     # Video from input 0 (original video)
                '-map', '1:a:0',     # Audio from input 1 (Edge-TTS audio)
                '-shortest',         # Match shortest stream duration
                paths['final_video'], '-y'
            ], capture_output=True, check=True)
            
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Step 3 completed in {duration:.1f}s")
            
            # Build URLs for final video and audio preview
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from  backend_host.src.lib.utils.host_utils import get_host_instance
            
            try:
                host = get_host_instance()
                host_dict = host.to_dict()
                dubbed_video_url = buildHostImageUrl(host_dict, paths['final_video'])
                edge_audio_url = buildHostImageUrl(host_dict, paths['dubbed_voice_edge_mp3'])
            except:
                # Alternative URL construction
                dubbed_video_url = f"/host/stream/{os.path.basename(paths['final_video'])}"
                edge_audio_url = f"/host/stream/{os.path.basename(paths['dubbed_voice_edge_mp3'])}"
            
            return {
                'success': True,
                'dubbed_video_url': dubbed_video_url,
                'edge_audio_url': edge_audio_url,
                'duration_seconds': round(duration, 1),
                'method': 'audio_replacement'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    
    def create_dubbed_video_complete(self, text: str, language: str, video_file: str, original_video_dir: str) -> Dict[str, Any]:
        """Complete dubbing process: generate speech + create video (~5-8s total)"""
        import time
        start_time = time.time()
        
        try:
            print(f"Dubbing[{self.device_name}]: Complete dubbing - generating Edge-TTS + creating video for {language}...")
            
            # Step 1: Generate Edge-TTS audio
            edge_result = self.generate_edge_speech(text, language, original_video_dir)
            if not edge_result.get('success'):
                return edge_result
            
            # Step 2: Replace original audio with Edge-TTS audio
            paths = self.get_file_paths(language, original_video_dir)
            
            print(f"Dubbing[{self.device_name}]: Complete dubbing - replacing original audio with Edge-TTS...")
            
            # Simple FFmpeg: replace original audio with new dubbed audio
            subprocess.run([
                'ffmpeg', '-i', video_file, '-i', paths['dubbed_voice_edge'],
                '-c:v', 'copy',      # Copy video unchanged
                '-c:a', 'aac',       # Encode new audio
                '-map', '0:v:0',     # Video from input 0 (original video)
                '-map', '1:a:0',     # Audio from input 1 (Edge-TTS audio)
                '-shortest',         # Match shortest stream duration
                paths['final_video'], '-y'
            ], capture_output=True, check=True)
            
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Complete dubbing finished in {duration:.1f}s")
            
            # Build URLs for final video and audio preview
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from  backend_host.src.lib.utils.host_utils import get_host_instance
            
            try:
                host = get_host_instance()
                host_dict = host.to_dict()
                dubbed_video_url = buildHostImageUrl(host_dict, paths['final_video'])
                edge_audio_url = buildHostImageUrl(host_dict, paths['dubbed_voice_edge_mp3'])
            except:
                # Alternative URL construction
                dubbed_video_url = f"/host/stream/{os.path.basename(paths['final_video'])}"
                edge_audio_url = f"/host/stream/{os.path.basename(paths['dubbed_voice_edge_mp3'])}"
            
            return {
                'success': True,
                'dubbed_video_url': dubbed_video_url,
                'edge_audio_url': edge_audio_url,
                'duration_seconds': round(duration, 1),
                'method': 'audio_replacement'
            }
            
        except Exception as e:
            print(f"Dubbing[{self.device_name}]: Complete dubbing failed: {e}")
            return {'success': False, 'error': str(e)}
    
    
    # =============================================================================
    # Audio Sync Methods
    # =============================================================================
    
    def sync_dubbed_video(self, language: str, timing_offset_ms: int, original_video_dir: str) -> Dict[str, Any]:
        """
        Sync video by applying timing to audio and combining with video.
        
        Args:
            language: Language code (e.g., 'fr', 'es') or 'original'
            timing_offset_ms: Timing offset in milliseconds (+delay, -advance)
            original_video_dir: Directory containing cached components
            
        Returns:
            Dictionary with sync result
        """
        import time
        start_time = time.time()
        
        try:
            print(f"Dubbing[{self.device_name}]: Syncing {language} video with {timing_offset_ms:+d}ms timing")
            
            paths = self.get_file_paths(language, original_video_dir)
            
            # Step 1: Get cached silent video (create if needed)
            silent_video_path = os.path.join(original_video_dir, "restart_video_no_audio.mp4")
            if not os.path.exists(silent_video_path):
                # Create silent video from any available video
                source_video = self._find_source_video(original_video_dir, language)
                if not source_video:
                    return {'success': False, 'error': 'No source video found for silent video creation'}
                
                print(f"Dubbing[{self.device_name}]: Creating cached silent video...")
                subprocess.run([
                    'ffmpeg', '-i', source_video,
                    '-c:v', 'copy', '-an',
                    silent_video_path, '-y'
                ], capture_output=True, check=True)
                print(f"Dubbing[{self.device_name}]: Silent video cached")
            
            # Step 2: Smart audio selection (priority: dubbed > original > extract)
            dubbed_audio_path = paths['dubbed_voice_edge']
            original_audio_path = paths['original_audio']
            
            # Option 1: Use cached dubbed audio (from previous dubbing)
            if os.path.exists(dubbed_audio_path):
                audio_to_sync = dubbed_audio_path
                print(f"Dubbing[{self.device_name}]: Using cached dubbed audio: {dubbed_audio_path}")
            
            # Option 2: Use cached original audio (from previous extraction)
            elif os.path.exists(original_audio_path):
                audio_to_sync = original_audio_path
                print(f"Dubbing[{self.device_name}]: Using cached original audio: {original_audio_path}")
            
            # Option 3: No cache - extract from video
            else:
                # Find source video to extract from
                source_video = self._find_source_video(original_video_dir, language)
                if not source_video:
                    return {'success': False, 'error': 'No source video found for audio extraction'}
                
                print(f"Dubbing[{self.device_name}]: No cached audio found, extracting from {source_video}...")
                subprocess.run([
                    'ffmpeg', '-i', source_video,
                    '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                    original_audio_path, '-y'
                ], capture_output=True, check=True)
                
                audio_to_sync = original_audio_path
                print(f"Dubbing[{self.device_name}]: Audio extracted and cached: {original_audio_path}")
            
            # Step 3: Apply timing to audio
            sync_suffix = f"_sync{timing_offset_ms:+d}" if timing_offset_ms != 0 else ""
            timed_audio_path = os.path.join(original_video_dir, f"restart_{language}_audio{sync_suffix}.wav")
            
            if timing_offset_ms == 0:
                # No timing needed, use original audio
                timed_audio_path = audio_to_sync
            else:
                print(f"Dubbing[{self.device_name}]: Applying {timing_offset_ms:+d}ms timing to audio...")
                
                if timing_offset_ms > 0:
                    # Positive offset: trim and delay audio with channel sync
                    audio_filter = f"atrim=0:5,adelay={timing_offset_ms}|{timing_offset_ms}"
                else:
                    # Negative offset: advance audio (trim from start)
                    trim_seconds = abs(timing_offset_ms) / 1000.0
                    audio_filter = f"atrim=start={trim_seconds}"
                
                subprocess.run([
                    'ffmpeg', '-i', audio_to_sync,
                    '-af', audio_filter,
                    timed_audio_path, '-y'
                ], capture_output=True, check=True)
                print(f"Dubbing[{self.device_name}]: Audio timing applied")
            
            # Step 4: Combine silent video + timed audio (reuse dubbing logic)
            sync_video_path = os.path.join(original_video_dir, f"restart_{language}_video{sync_suffix}.mp4")
            
            print(f"Dubbing[{self.device_name}]: Combining silent video with timed audio...")
            subprocess.run([
                'ffmpeg', '-i', silent_video_path, '-i', timed_audio_path,
                '-c:v', 'copy',      # Copy video unchanged
                '-c:a', 'aac',       # Encode audio
                '-map', '0:v:0',     # Video from silent video
                '-map', '1:a:0',     # Audio from timed audio
                '-shortest',         # Match shortest stream duration
                sync_video_path, '-y'
            ], capture_output=True, check=True)
            
            duration = time.time() - start_time
            print(f"Dubbing[{self.device_name}]: Sync completed in {duration:.1f}s")
            
            # Build URLs for synced video
            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            from  backend_host.src.lib.utils.host_utils import get_host_instance
            
            try:
                host = get_host_instance()
                host_dict = host.to_dict()
                synced_video_url = buildHostImageUrl(host_dict, sync_video_path)
            except:
                # Fallback URL construction
                synced_video_url = f"/host/stream/{os.path.basename(sync_video_path)}"
            
            return {
                'success': True,
                'synced_video_url': synced_video_url,
                'timing_offset_ms': timing_offset_ms,
                'language': language,
                'duration_seconds': round(duration, 1),
                'method': 'audio_sync'
            }
            
        except Exception as e:
            print(f"Dubbing[{self.device_name}]: Sync failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _find_source_video(self, original_video_dir: str, language: str) -> Optional[str]:
        """Find best source video for creating silent video"""
        # Priority order: dubbed video for language > original video > any video
        candidates = [
            os.path.join(original_video_dir, f"restart_{language}_dubbed_video.mp4"),
            os.path.join(original_video_dir, "restart_original_video.mp4"),
        ]
        
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        
        # Look for any restart video using find (consistent with other files)
        try:
            result = subprocess.run([
                'find', original_video_dir, '-maxdepth', '1',
                '-name', 'restart_*.mp4', '-type', 'f'
            ], capture_output=True, text=True, timeout=5)
            
            videos = [f for f in result.stdout.strip().split('\n') if f] if result.returncode == 0 else []
            return videos[0] if videos else None
        except Exception:
            return None
    