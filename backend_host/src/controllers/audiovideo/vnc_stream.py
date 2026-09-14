"""
VNC Stream Controller Implementation

This controller handles VNC stream acquisition by referencing continuously captured screenshots.
The host continuously takes screenshots using FFmpeg, and this controller references them by timestamp.
Uses shared FFmpeg-based capture functionality.
"""

import subprocess
from typing import Dict, Any, Optional
from ..base_controller import FFmpegCaptureController


class VNCStreamController(FFmpegCaptureController):
    """VNC Stream controller that references continuously captured screenshots by timestamp."""
    
    def __init__(self, video_stream_path: str = None, video_capture_path: str = None, **kwargs):
        """
        Initialize the VNC Stream controller.
        
        Args:
            video_stream_path: VNC stream path for viewing (e.g., "https://virtualpytest.com/host/vnc/vnc_lite.html")
            video_capture_path: FFmpeg video capture path (e.g., "/var/www/html/stream/capture3")
        """
        super().__init__("VNC Stream Controller", "VNC", video_stream_path, video_capture_path, **kwargs)
        
        # For VNC, video_stream_path is the VNC viewer URL
        self.vnc_stream_path = video_stream_path
        if self.vnc_stream_path:
            print(f"VNC[{self.capture_source}]: VNC Viewer URL: {self.vnc_stream_path}")
        
        # Store additional VNC-related environment variables
        self.vnc_password = kwargs.get('vnc_password')
        self.web_browser_path = kwargs.get('web_browser_path', '/usr/bin/chromium')

        
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
            
            print(f"VNC[{device_id}]: Updating quality to {quality}")
            
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
                print(f"VNC[{device_id}]: Device not running yet")
                return False
            
            # Simple direct write (file is 666, already exists, world-writable)
            with open(config_file, 'w') as f:
                f.write('\n'.join(entries) + '\n')
            
            print(f"VNC[{device_id}]: Quality updated → {quality}")
            return True
            
        except Exception as e:
            print(f"VNC[{device_id}]: Error updating quality: {e}")
            return False


            
    def get_vnc_viewer_url(self) -> Optional[str]:
        """
        Get the VNC viewer URL for direct VNC access.
        
        Returns:
            VNC viewer URL if configured, None otherwise
        """
        return self.vnc_stream_path
        
    def take_control(self) -> Dict[str, Any]:
        """
        Take control of VNC stream and verify it's working.
        
        Returns:
            Dictionary with success status and stream information
        """
        try:
            # Check stream status
            status = self.get_status()
            is_streaming = status.get('is_streaming', False)
            
            # For VNC stream, we use the same FFmpeg capture system as HDMI
            # Add VNC-specific capabilities like VNC viewing
            control_info = {
                'success': True,
                'status': 'stream_ready',
                'controller_type': 'av',
                'stream_info': status,
                'capabilities': ['video_capture', 'screenshot', 'streaming', 'vnc_viewing']
            }
            
            # Add VNC viewer URL if available
            if self.vnc_stream_path:
                control_info['vnc_viewer_url'] = self.vnc_stream_path
                
            return control_info
                
        except Exception as e:
            print(f"VNC[{self.capture_source}]: Take control error: {e}")
            return {
                'success': False,
                'status': 'error',
                'error': f'VNC controller error: {str(e)}',
                'controller_type': 'av'
            }
            
    def get_status(self) -> Dict[str, Any]:
        """Get controller status by checking FFmpeg capture system (same as HDMI)."""
        try:
            import os
            import time
            
            # For VNC, we use the same FFmpeg capture approach as HDMI
            # Check if the capture directory exists and has recent screenshots
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
            # Use centralized path resolution (handles hot/cold storage automatically)
            captures_path = get_capture_storage_path(self.video_capture_path, 'captures')
            
            if os.path.exists(captures_path) and os.access(captures_path, os.W_OK):
                # Check if there are recent screenshots (within last 30 seconds)
                recent_screenshots = []
                try:
                    for file in os.listdir(captures_path):
                        if file.startswith('capture_') and file.endswith('.jpg'):
                            file_path = os.path.join(captures_path, file)
                            file_time = os.path.getmtime(file_path)
                            if time.time() - file_time < 30:  # Last 30 seconds
                                recent_screenshots.append(file)
                except Exception as e:
                    print(f"VNC[{self.capture_source}]: Error checking recent screenshots: {e}")
                
                is_streaming = len(recent_screenshots) > 0
                
                return {
                    'success': True,
                    'controller_type': 'av',
                    'service_status': 'active_running' if is_streaming else 'active_waiting',
                    'is_streaming': is_streaming,
                    'is_capturing': self.is_capturing_video,
                    'capture_session_id': self.capture_session_id,
                    'recent_screenshots': len(recent_screenshots),
                    'message': f'VNC controller - {len(recent_screenshots)} recent screenshots found'
                }
            else:
                return {
                    'success': False,
                    'controller_type': 'av',
                    'service_status': 'error',
                    'is_streaming': False,
                    'is_capturing': self.is_capturing_video,
                    'error': f'VNC capture directory not accessible: {captures_path}'
                }
            
        except Exception as e:
            print(f"VNC[{self.capture_source}]: Error getting status: {e}")
            return {
                'success': False,
                'controller_type': 'av',
                'service_status': 'error',
                'is_streaming': False,
                'is_capturing': self.is_capturing_video,
                'error': f'Failed to get VNC controller status: {str(e)}'
            } 
