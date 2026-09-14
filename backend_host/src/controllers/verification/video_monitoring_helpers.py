"""
Video Monitoring Helpers

Dedicated helper functions for video monitoring and capture management.
Extracted from FFmpegCaptureController to maintain clean separation of concerns.
"""

import os
import time
import re
from typing import Dict, Any, Optional, List


class VideoMonitoringHelpers:
    """Helper class for video monitoring functionality."""
    
    def __init__(self, av_controller, device_name: str = "Monitoring"):
        """
        Initialize monitoring helpers.
        
        Args:
            av_controller: AV controller instance
            device_name: Name for logging purposes
        """
        self.av_controller = av_controller
        self.device_name = device_name
        self.capture_source = getattr(av_controller, 'capture_source', 'AV')
        
        # Get paths from controller - for monitoring we need the capture path
        self.video_stream_path = getattr(av_controller, 'video_stream_path', '')
        self.video_capture_path = getattr(av_controller, 'video_capture_path', '')
        
        # For monitoring, we need to get the actual captures folder from the image controller
        # The AV controller might not have the right path, so we'll get it dynamically
    
    def _get_capture_folder(self) -> Optional[str]:
        """Get the capture folder path from the image controller"""
        try:
            # Import here to avoid circular imports
            from  backend_host.src.lib.utils.host_utils import get_controller
            
            # Get the device_id from the AV controller if available
            device_id = getattr(self.av_controller, 'device_id', 'device1')
            
            # Get the image controller which has the captures_path
            image_controller = get_controller(device_id, 'verification_image')
            if image_controller and hasattr(image_controller, 'captures_path'):
                return image_controller.captures_path
            
            # Fallback to AV controller path + captures
            if self.video_capture_path:
                from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
                # Use centralized path resolution (handles hot/cold storage automatically)
                return get_capture_storage_path(self.video_capture_path, 'captures')
            
            return None
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Error getting capture folder: {e}")
            return None

    def _find_latest_metadata_json(self, metadata_folder: str) -> Optional[Dict[str, Any]]:
        """
        Find latest capture JSON in one directory pass.
        Uses ctime to handle sequence resets after FFmpeg restarts.
        """
        latest_file = None
        latest_ctime = -1.0
        latest_sequence = -1

        try:
            with os.scandir(metadata_folder) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue

                    filename = entry.name
                    if not (filename.startswith('capture_') and filename.endswith('.json')):
                        continue

                    try:
                        ctime = entry.stat().st_ctime
                    except OSError:
                        continue

                    sequence_match = re.search(r'capture_(\d+)\.json', filename)
                    sequence_number = int(sequence_match.group(1)) if sequence_match else -1

                    # Primary order: newest ctime. Tie-breaker: higher sequence.
                    if ctime > latest_ctime or (ctime == latest_ctime and sequence_number > latest_sequence):
                        latest_ctime = ctime
                        latest_sequence = sequence_number
                        latest_file = {
                            'filename': filename,
                            'timestamp': ctime,
                            'filepath': entry.path
                        }
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Metadata scan error: {e}")
            return None

        return latest_file
    
    def list_captures(self, limit: int = 180) -> Dict[str, Any]:
        """
        List captured frames for monitoring with URLs built like screenshots.
        
        Args:
            limit: Maximum number of captures to return
            
        Returns:
            Dictionary with capture list results
        """
        try:
            print(f"MonitoringHelpers[{self.device_name}]: Listing captures, limit: {limit}")
            
            # Get capture folder - need to get it from image controller
            capture_folder = self._get_capture_folder()
            
            if not capture_folder or not os.path.exists(capture_folder):
                return {
                    'success': False,
                    'error': f'Capture folder not found: {capture_folder}',
                    'captures': [],
                    'total': 0
                }
            
            # List all capture files (not test_capture files or thumbnails)
            capture_files = []
            for filename in os.listdir(capture_folder):
                if (filename.startswith('capture_') and 
                    filename.endswith('.jpg') and 
                    '_thumbnail' not in filename):
                    filepath = os.path.join(capture_folder, filename)
                    if os.path.isfile(filepath):
                        # Get file modification time as timestamp
                        timestamp = int(os.path.getmtime(filepath) * 1000)
                        capture_files.append({
                            'filename': filename,
                            'timestamp': timestamp,
                            'filepath': filepath
                        })
            
            # Sort by timestamp (newest first) and limit
            capture_files.sort(key=lambda x: x['timestamp'], reverse=True)
            capture_files = capture_files[:limit]
            
            # Build URLs using the same mechanism as takeScreenshot
            captures = self._build_capture_urls(capture_files)
            
            print(f"MonitoringHelpers[{self.device_name}]: Found {len(captures)} capture files with URLs")
            
            return {
                'success': True,
                'captures': captures,
                'total': len(captures)
            }
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: List captures error: {str(e)}")
            return {
                'success': False,
                'error': f'List captures error: {str(e)}',
                'captures': [],
                'total': 0
            }
    
    def get_latest_monitoring_json(self) -> Dict[str, Any]:
        """
        Get the latest available JSON analysis file for monitoring.
        
        Returns:
            Dictionary with latest JSON file information
        """
        try:
            # Get capture folder path first
            capture_folder = self._get_capture_folder()
            
            if not capture_folder or not os.path.exists(capture_folder):
                return {
                    'success': False,
                    'error': f'Capture folder not found: {capture_folder}'
                }
            
            # Get metadata folder - JSON files are stored there, not in captures/
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, get_capture_folder
            # Extract device folder from path (cross-platform, hot/cold aware)
            device_folder = get_capture_folder(capture_folder)
            
            metadata_folder = get_capture_storage_path(device_folder, 'metadata')
            
            if not os.path.exists(metadata_folder):
                return {
                    'success': False,
                    'error': f'Metadata folder not found: {metadata_folder}'
                }
            
            latest_json = self._find_latest_metadata_json(metadata_folder)
            if not latest_json:
                return {
                    'success': False,
                    'error': 'No JSON analysis files found'
                }
            
            # Read JSON content directly (eliminates second HTTP request from frontend)
            import json
            try:
                with open(latest_json['filepath'], 'r') as f:
                    json_data = json.load(f)
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to read JSON file: {str(e)}'
                }
            
            return {
                'success': True,
                'json_data': json_data,
                'filename': latest_json['filename'],
                'timestamp': latest_json['timestamp']
            }
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Latest JSON error: {str(e)}")
            return {
                'success': False,
                'error': f'Latest JSON error: {str(e)}'
            }
    
    def get_capture_statistics(self, timeframe_hours: int = 24) -> Dict[str, Any]:
        """
        Get capture statistics for monitoring dashboard.
        
        Args:
            timeframe_hours: Hours to look back for statistics
            
        Returns:
            Dictionary with capture statistics
        """
        try:
            capture_folder = self._get_capture_folder()
            
            if not capture_folder or not os.path.exists(capture_folder):
                return {
                    'success': False,
                    'error': f'Capture folder not found: {capture_folder}'
                }
            
            current_time = time.time()
            cutoff_time = current_time - (timeframe_hours * 3600)  # Convert hours to seconds
            
            # Count captures in timeframe
            total_captures = 0
            json_files = 0
            image_files = 0
            
            for filename in os.listdir(capture_folder):
                if filename.startswith('capture_'):
                    filepath = os.path.join(capture_folder, filename)
                    if os.path.isfile(filepath):
                        file_mtime = os.path.getmtime(filepath)
                        if file_mtime >= cutoff_time:
                            total_captures += 1
                            if filename.endswith('.json'):
                                json_files += 1
                            elif filename.endswith('.jpg') and '_thumbnail' not in filename:
                                image_files += 1
            
            # Calculate capture rate (captures per hour)
            capture_rate = total_captures / timeframe_hours if timeframe_hours > 0 else 0
            
            return {
                'success': True,
                'timeframe_hours': timeframe_hours,
                'total_captures': total_captures,
                'image_files': image_files,
                'json_files': json_files,
                'capture_rate_per_hour': round(capture_rate, 2),
                'analysis_coverage': round((json_files / image_files * 100) if image_files > 0 else 0, 1)
            }
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Statistics error: {str(e)}")
            return {
                'success': False,
                'error': f'Statistics error: {str(e)}'
            }
    
    def cleanup_old_captures(self, retention_hours: int = 72) -> Dict[str, Any]:
        """
        Clean up old capture files to manage disk space.
        
        Args:
            retention_hours: Hours to retain files (default: 72 hours = 3 days)
            
        Returns:
            Dictionary with cleanup results
        """
        try:
            capture_folder = self._get_capture_folder()
            
            if not capture_folder or not os.path.exists(capture_folder):
                return {
                    'success': False,
                    'error': f'Capture folder not found: {capture_folder}'
                }
            
            current_time = time.time()
            cutoff_time = current_time - (retention_hours * 3600)
            
            deleted_files = []
            deleted_count = 0
            total_size_freed = 0
            
            for filename in os.listdir(capture_folder):
                if filename.startswith('capture_'):
                    filepath = os.path.join(capture_folder, filename)
                    if os.path.isfile(filepath):
                        file_mtime = os.path.getmtime(filepath)
                        if file_mtime < cutoff_time:
                            try:
                                file_size = os.path.getsize(filepath)
                                os.remove(filepath)
                                deleted_files.append(filename)
                                deleted_count += 1
                                total_size_freed += file_size
                            except Exception as e:
                                print(f"MonitoringHelpers[{self.device_name}]: Failed to delete {filename}: {e}")
            
            # Convert bytes to MB
            size_freed_mb = total_size_freed / (1024 * 1024)
            
            print(f"MonitoringHelpers[{self.device_name}]: Cleanup complete - {deleted_count} files deleted, {size_freed_mb:.1f} MB freed")
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'size_freed_mb': round(size_freed_mb, 1),
                'retention_hours': retention_hours,
                'deleted_files': deleted_files[:10]  # Return first 10 for logging
            }
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Cleanup error: {str(e)}")
            return {
                'success': False,
                'error': f'Cleanup error: {str(e)}'
            }
    
    def get_capture_health_status(self) -> Dict[str, Any]:
        """
        Get health status of capture system for monitoring.
        
        Returns:
            Dictionary with health status information
        """
        try:
            capture_folder = self._get_capture_folder()
            
            if not os.path.exists(capture_folder):
                return {
                    'success': False,
                    'healthy': False,
                    'error': f'Capture folder not found: {capture_folder}'
                }
            
            current_time = time.time()
            
            # Check for recent captures (within last 5 minutes)
            recent_cutoff = current_time - 300  # 5 minutes
            recent_captures = 0
            
            # Check for very recent captures (within last 30 seconds)
            very_recent_cutoff = current_time - 30
            very_recent_captures = 0
            
            latest_capture_time = 0
            
            for filename in os.listdir(capture_folder):
                if (filename.startswith('capture_') and 
                    filename.endswith('.jpg') and 
                    '_thumbnail' not in filename):
                    filepath = os.path.join(capture_folder, filename)
                    if os.path.isfile(filepath):
                        file_mtime = os.path.getmtime(filepath)
                        latest_capture_time = max(latest_capture_time, file_mtime)
                        
                        if file_mtime >= recent_cutoff:
                            recent_captures += 1
                        
                        if file_mtime >= very_recent_cutoff:
                            very_recent_captures += 1
            
            # Determine health status
            healthy = recent_captures > 0
            status = "healthy" if healthy else "unhealthy"
            
            if very_recent_captures > 0:
                status = "active"
            elif recent_captures == 0:
                status = "stalled"
            
            # Calculate time since last capture
            time_since_last = current_time - latest_capture_time if latest_capture_time > 0 else float('inf')
            
            return {
                'success': True,
                'healthy': healthy,
                'status': status,
                'recent_captures_5min': recent_captures,
                'very_recent_captures_30sec': very_recent_captures,
                'time_since_last_capture_sec': round(time_since_last, 1) if time_since_last != float('inf') else None,
                'latest_capture_timestamp': latest_capture_time if latest_capture_time > 0 else None
            }
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: Health check error: {str(e)}")
            return {
                'success': False,
                'healthy': False,
                'error': f'Health check error: {str(e)}'
            }
    
    def _build_capture_urls(self, capture_files: List[Dict]) -> List[Dict]:
        """Build URLs for capture files using existing URL building utilities"""
        try:
            from shared.src.lib.utils.build_url_utils import buildCaptureUrlFromPath
            from  backend_host.src.lib.utils.host_utils import get_host_instance as get_host
            
            host = get_host()
            host_dict = host.to_dict()
            
            # Get the device_id from the AV controller
            device_id = getattr(self.av_controller, 'device_id', 'device1')
            
            captures = []
            for capture in capture_files:
                try:
                    # Build URL from file path using same mechanism as screenshots
                    capture_url = buildCaptureUrlFromPath(host_dict, capture['filepath'], device_id)
                    
                    client_capture_url = capture_url
                    
                    captures.append({
                        'filename': capture['filename'],
                        'timestamp': capture['timestamp'],
                        'url': client_capture_url
                    })
                except Exception as url_error:
                    print(f"MonitoringHelpers[{self.device_name}]: Failed to build URL for {capture['filename']}: {url_error}")
                    # Skip captures that can't have URLs built
                    continue
            
            return captures
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: URL building error: {e}")
            return []
    
    def _build_json_url(self, json_filepath: str) -> str:
        """
        Build URL for JSON file from metadata folder path.
        Properly handles hot/cold storage paths using centralized utilities.
        
        Example paths:
          RAM: /var/www/html/stream/capture1/hot/metadata/capture_000000433.json
          SD:  /var/www/html/stream/capture1/metadata/capture_000000433.json
        
        Returns URL: /host/stream/capture1/metadata/capture_000000433.json
        (NGINX handles hot/cold fallback via try_files directive)
        """
        try:
            from shared.src.lib.utils.build_url_utils import buildHostUrl
            from backend_host.src.lib.utils.host_utils import get_host_instance as get_host
            
            # Extract components from filepath
            # Path format: /var/www/html/stream/{device_folder}/[hot/]{subfolder}/{filename}
            filename = os.path.basename(json_filepath)
            
            # Extract device folder (e.g., 'capture1')
            path_parts = json_filepath.split('/')
            stream_idx = path_parts.index('stream') if 'stream' in path_parts else -1
            if stream_idx < 0:
                raise ValueError(f"Invalid path format - 'stream' not found: {json_filepath}")
            
            device_folder = path_parts[stream_idx + 1]  # Next after 'stream'
            
            # Build URL path: /host/stream/{device_folder}/metadata/{filename}
            # NGINX try_files will handle hot/cold fallback automatically
            url_path = f"host/stream/{device_folder}/metadata/{filename}"
            
            # Get host info and build complete URL
            host = get_host()
            host_dict = host.to_dict()
            
            json_url = buildHostUrl(host_dict, url_path)
            
            print(f"MonitoringHelpers[{self.device_name}]: Built JSON URL: {json_url}")
            return json_url
            
        except Exception as e:
            print(f"MonitoringHelpers[{self.device_name}]: JSON URL building error: {e}")
            # Fallback to relative path
            filename = os.path.basename(json_filepath)
            return f"{self.video_stream_path}/captures/{filename}"
