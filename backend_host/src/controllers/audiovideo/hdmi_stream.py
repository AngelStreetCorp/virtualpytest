"""
HDMI Stream Controller Implementation

This controller handles HDMI stream acquisition by referencing continuously captured screenshots.
The host continuously takes screenshots using FFmpeg, and this controller references them by timestamp.
Uses shared FFmpeg-based capture functionality.
"""

import glob
import json
import os
import re
import subprocess
import time
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

    # A monitor frame record older than this says nothing about the box now.
    SIGNAL_FRAME_MAX_AGE_S = 15

    def get_signal_state(self) -> Dict[str, Any]:
        """Is the box on this input asleep? `standby` True / False, or None when nothing can tell.

        1. `hdmi_hid`: the capture dongle's own HDMI flag (shared/src/lib/utils/hdmi_signal.py, MS2130).
        2. `monitor`: the newest frame record the capture monitor wrote (no_signal or blackscreen = standby).
        `signal` is the HDMI flag when the dongle gives one, else None.
        """
        from shared.src.lib.utils.hdmi_signal import signal_present
        m = re.search(r'(\d+)$', str(getattr(self, 'device_id', '')))
        signal = signal_present(int(m.group(1))) if m else None
        if signal is not None:
            return {'standby': not signal, 'signal': signal, 'source': 'hdmi_hid'}
        frame = self._latest_monitor_record()
        if frame is not None:
            return {'standby': bool(frame.get('no_signal') or frame.get('blackscreen')), 'signal': None, 'source': 'monitor',
                    'no_signal': bool(frame.get('no_signal')), 'blackscreen': bool(frame.get('blackscreen'))}
        return {'standby': None, 'signal': None, 'source': None}

    def _latest_monitor_record(self) -> Optional[Dict[str, Any]]:
        files = glob.glob(os.path.join(self.video_capture_path, 'hot', 'metadata', 'capture_*.json'))
        if not files:
            return None
        newest = max(files, key=os.path.getmtime)
        if time.time() - os.path.getmtime(newest) > self.SIGNAL_FRAME_MAX_AGE_S:
            return None
        try:
            with open(newest) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


            
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
