"""
HDMI Stream Controller Implementation

This controller handles HDMI stream acquisition by referencing continuously captured screenshots.
The host continuously takes screenshots using FFmpeg, and this controller references them by timestamp.
Uses shared FFmpeg-based capture functionality.
"""

import subprocess
from typing import Dict, Any, Optional
from ..base_controller import FFmpegCaptureController


class HDMIStreamController(FFmpegCaptureController):
    """HDMI Stream controller that references continuously captured screenshots by timestamp."""
    
    def __init__(self, video_stream_path: str, video_capture_path: str, **kwargs):
        """
        Initialize the HDMI Stream controller.
        
        Args:
            video_stream_path: Stream path for URLs (e.g., "/host/stream/capture1")
            video_capture_path: Local capture path (e.g., "/var/www/html/stream/capture1")
        """
        super().__init__("HDMI Stream Controller", "HDMI", video_stream_path, video_capture_path, **kwargs)

        
    def set_quality(self, quality: str = 'sd') -> bool:
        """Soft per-device quality change: rewrite this device's line in
        active_captures.conf. The (already running) vpt-stream service loop
        detects the change and recycles just this device's ffmpeg. Does NOT
        restart the service — use the restart endpoint for that."""
        try:
            import os
            from shared.src.lib.utils.storage_path_utils import get_active_captures_conf_path
            
            device_id = self.device_id
            capture_dir = self.video_capture_path
            config_file = get_active_captures_conf_path()
            
            print(f"[HDMI] Updating quality for {device_id} to {quality}")
            
            # Read existing entries
            entries = []
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    entries = [line.strip() for line in f if line.strip()]
            
            # Update quality for this device. Match on a normalized path so
            # Windows separator/trailing-slash/case differences still hit.
            target = os.path.normcase(os.path.normpath(capture_dir))
            found = False
            for i, entry in enumerate(entries):
                parts = entry.split(',')
                if len(parts) == 3 and os.path.normcase(os.path.normpath(parts[0])) == target:
                    entries[i] = f"{parts[0]},{parts[1]},{quality}"
                    found = True
                    break
            
            if not found:
                print(f"[HDMI] Device {device_id} not running yet")
                return False
            
            # Simple direct write (file is 666, already exists, world-writable)
            with open(config_file, 'w') as f:
                f.write('\n'.join(entries) + '\n')
            
            print(f"[HDMI] Quality updated: {device_id} → {quality}")
            return True
            
        except Exception as e:
            print(f"[HDMI] Error updating quality: {e}")
            return False


            
    def get_status(self) -> Dict[str, Any]:
        """Get controller status using platform-specific service status."""
        try:
            import platform

            if platform.system() == 'Darwin':  # macOS
                # Use launchctl on macOS
                result = subprocess.run(
                    ['launchctl', 'list', 'com.virtualpytest.stream'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )

                if result.returncode == 0:
                    # launchctl list succeeded - service is loaded
                    is_streaming = True
                    service_status_text = "loaded_running"
                    service_status = {'activestate': 'loaded', 'substate': 'running'}
                else:
                    is_streaming = False
                    service_status_text = "not_loaded"
                    service_status = {'activestate': 'inactive', 'substate': 'dead'}

                return {
                    'success': True,
                    'controller_type': 'av',
                    'service_status': service_status_text,
                    'is_streaming': is_streaming,
                    'is_capturing': self.is_capturing_video,
                    'capture_session_id': self.capture_session_id,
                    'service_details': service_status,
                    'message': f'HDMI controller - service is {service_status_text}'
                }
            else:  # Linux
                # Get systemd service status
                result = subprocess.run(
                    ['sudo', 'systemctl', 'show', 'stream', '--property=ActiveState,SubState'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )

                if result.returncode == 0:
                    # Parse systemctl output
                    service_status = {}
                    for line in result.stdout.strip().split('\n'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            service_status[key.lower()] = value

                    # Check if stream service is running
                    is_streaming = (service_status.get('activestate') == 'active' and
                                  service_status.get('substate') == 'running')

                    service_status_text = f"{service_status.get('activestate', 'unknown')}_{service_status.get('substate', 'unknown')}"
                else:
                    return {
                        'success': False,
                        'controller_type': 'av',
                        'service_status': 'error',
                        'is_streaming': False,
                        'is_capturing': self.is_capturing_video,
                        'error': f'Failed to get service status: {result.stderr}'
                    }
                
                return {
                    'success': True,
                    'controller_type': 'av',
                    'service_status': service_status_text,
                    'is_streaming': is_streaming,
                    'is_capturing': self.is_capturing_video,
                    'capture_session_id': self.capture_session_id,
                    'service_details': service_status,
                    'message': f'HDMI controller - service is {service_status_text}'
                }
            
        except Exception as e:
            print(f"HDMI[{self.capture_source}]: Error getting status: {e}")
            return {
                'success': False,
                'controller_type': 'av',
                'service_status': 'error',
                'is_streaming': False,
                'is_capturing': self.is_capturing_video,
                'error': f'Failed to get controller status: {str(e)}'
            }
