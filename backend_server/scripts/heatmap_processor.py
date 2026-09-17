"""
Heatmap Processor Service

Continuous background service that generates heatmap mosaics every minute.
Uses circular buffer with HHMM naming (1440 fixed files).
"""

import sys
import os

# Add project root to path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Apply global typing compatibility early to fix third-party package issues
try:
    from shared.src.lib.utils.typing_compatibility import ensure_typing_compatibility
    ensure_typing_compatibility()
except ImportError:
    print("Warning: Could not apply typing compatibility fix")

# Now import everything else after typing fix
import time
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from PIL import Image
import io
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils


def _ascii_safe(text: object) -> str:
    """Return ASCII-safe text for systemd/journald streams."""
    return str(text).encode('ascii', 'ignore').decode('ascii')


def _safe_print(message: object) -> None:
    """Print ASCII-safe text to avoid stream encoding errors."""
    print(_ascii_safe(message))


def _clean_device_name(device_name: object, device_id: object = '') -> str:
    """Strip the internal '_Host' suffix that host (VNC) capture devices carry
    in their device_name so it never surfaces in the heatmap UI."""
    name = str(device_name or device_id or '').strip()
    if name.endswith('_Host'):
        name = name[:-len('_Host')]
    return name


class AsciiSafeFormatter(logging.Formatter):
    """Formatter that removes non-ASCII characters before emission."""

    def format(self, record: logging.LogRecord) -> str:
        return _ascii_safe(super().format(record))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    project_env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(project_env_path):
        load_dotenv(project_env_path, encoding='utf-8-sig')
        _safe_print(f"[@heatmap_processor] Loaded environment from {project_env_path}")
        _safe_print(f"[@heatmap_processor] SERVER_NAME={os.getenv('SERVER_NAME', 'default')}")
    else:
        _safe_print(f"[@heatmap_processor] Warning: .env not found at {project_env_path}")
except ImportError:
    _safe_print("[@heatmap_processor] Warning: python-dotenv not installed")

# Setup logging to /tmp/heatmap.log and stdout with ASCII-safe formatting.
_heatmap_formatter = AsciiSafeFormatter('%(asctime)s [HEATMAP] %(message)s')
_file_handler = RotatingFileHandler(
    '/tmp/heatmap.log',
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8'
)
_file_handler.setFormatter(_heatmap_formatter)
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_heatmap_formatter)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _stream_handler], force=True)
logger = logging.getLogger(__name__)

# Written every minute so the dashboard can tell a processor that is merely
# running from one that is running but producing nothing (see server_system_routes).
HEATMAP_STATUS_FILE = '/tmp/heatmap_status.json'


def cleanup_logs_on_startup():
    """Clean up heatmap log file on service restart for fresh debugging"""
    try:
        log_file = '/tmp/heatmap.log'
        
        _safe_print(f"[@heatmap_processor] Cleaning heatmap log on service restart...")
        
        if os.path.exists(log_file):
            # Truncate the file instead of deleting to avoid permission issues
            with open(log_file, 'w') as f:
                f.write(f"=== LOG CLEANED ON HEATMAP PROCESSOR RESTART: {datetime.now(timezone.utc).isoformat()} ===\n")
            _safe_print(f"[@heatmap_processor] Cleaned: {log_file}")
        else:
            _safe_print(f"[@heatmap_processor] Not found (will be created): {log_file}")
            
        _safe_print(f"[@heatmap_processor] Log cleanup complete - fresh logs for debugging")
            
    except Exception as e:
        _safe_print(f"[@heatmap_processor] Warning: Could not clean log file: {e}")

class HeatmapProcessor:
    """Background processor for continuous heatmap generation"""
    
    def __init__(self):
        self.running = False
        self.server_path = self._get_server_path()
        # Performance: Reuse session for connection pooling
        import requests
        self.session = requests.Session()
        session_headers = {'User-Agent': 'HeatmapProcessor/1.0'}
        # Some hosts are only reachable via the public proxy, where /host/<name>/stream/...
        # now sits behind the host-session auth_request gate (BUG-0107 step 2). This is a
        # server-to-server fetch with no browser cookie, so it authenticates with the shared
        # service key instead — a no-op for hosts fetched LAN-direct via host_api_url.
        api_key = os.environ.get('API_KEY')
        if api_key:
            session_headers['X-API-Key'] = api_key
        self.session.headers.update(session_headers)
        # Performance: Cache fonts to avoid repeated loading
        self._fonts_cache = {}
        logger.info(f"🏷️ HeatmapProcessor server path: {self.server_path}")
    
    def _get_server_path(self) -> str:
        """Get server path for R2 storage organization using SERVER_NAME"""
        # Use SERVER_NAME to organize heatmaps by deployment instance
        # Examples: "hetzner-prod", "local-dev", "render-staging"
        server_name = os.getenv('SERVER_NAME', 'default')
        
        logger.info(f"📍 Using SERVER_NAME: {server_name} → R2 path: heatmaps/{server_name}/")
        return server_name
        
    def start(self):
        """Start continuous processing every minute"""
        cleanup_logs_on_startup()  # Clean logs on startup
        logger.info("🚀 Starting HeatmapProcessor...")
        self.running = True
        
        while self.running:
            try:
                self.process_current_minute()
                self.wait_for_next_minute()
            except KeyboardInterrupt:
                logger.info("🛑 HeatmapProcessor stopped by user")
                self.running = False
            except Exception as e:
                logger.error(f"❌ HeatmapProcessor error: {e}")
                time.sleep(60)  # Wait a minute before retrying
    
    def write_status(self, time_key: str, generated: bool, reason: str = '') -> None:
        """Record this minute's outcome so the dashboard reports what the processor
        actually produced, not just whether its unit is running."""
        try:
            status = {}
            if os.path.exists(HEATMAP_STATUS_FILE):
                try:
                    with open(HEATMAP_STATUS_FILE, 'r', encoding='utf-8') as status_file:
                        status = json.load(status_file) or {}
                except Exception:
                    status = {}

            now_iso = datetime.now(timezone.utc).isoformat()
            status['last_attempt'] = now_iso
            status['last_time_key'] = time_key
            if generated:
                status['last_success'] = now_iso
                status['last_success_time_key'] = time_key
                status['last_error'] = ''
            else:
                status['last_error'] = _ascii_safe(reason)

            tmp_path = f'{HEATMAP_STATUS_FILE}.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as status_file:
                json.dump(status, status_file)
            os.replace(tmp_path, HEATMAP_STATUS_FILE)
        except Exception as e:
            logger.warning(f"⚠️ Could not write heatmap status file: {e}")

    def process_current_minute(self):
        """Generate mosaic and analysis for current minute"""
        now = datetime.now(timezone.utc)
        time_key = f"{now.hour:02d}{now.minute:02d}"  # "1425"
        
        logger.info(f"🔄 Processing heatmap for {time_key}")
        
        try:
            # Get hosts and analysis data
            hosts_devices = self.get_hosts_devices()
            if not hosts_devices:
                logger.warning(f"⚠️ No hosts available for {time_key}")
                self.write_status(time_key, False, 'No hosts available')
                return
                
            # Fetch current captures using latest-json endpoint (same as useMonitoring)
            current_captures = self.fetch_current_captures(hosts_devices)
            if not current_captures:
                logger.warning(f"⚠️ No current captures retrieved for {time_key}")
                self.write_status(time_key, False, 'No current captures retrieved')
                return
                
                
            # Create complete device list with placeholders for missing captures
            complete_device_list = self.create_complete_device_list(hosts_devices, current_captures)
            
            # Create mosaic image (always full grid)
            mosaic_image = self.create_mosaic_image(complete_device_list)
            
            # Create OK and KO mosaics - OPTIMIZED: single pass filtering
            ok_devices, ko_devices = self.filter_devices_by_status(complete_device_list)
            
            ko_mosaic_image = self.create_mosaic_image(ko_devices) if ko_devices else None
            ok_mosaic_image = self.create_mosaic_image(ok_devices) if ok_devices else None
            
            logger.info(f"📊 Created mosaics: ALL({len(complete_device_list)}), OK({len(ok_devices)}), KO({len(ko_devices)})")
            
            # Create analysis JSON (includes all devices, even missing ones)
            analysis_json = self.create_analysis_json(complete_device_list, time_key)
            
            # Display consolidated JSON data in logs
            self.log_consolidated_json(analysis_json)
            
            # Upload to R2 with time-only naming
            success, uploaded_urls = self.upload_heatmap_files(time_key, mosaic_image, analysis_json, ok_mosaic_image, ko_mosaic_image)
            
            if success:
                logger.info(f"✅ Generated heatmap for {time_key} ({len(complete_device_list)} devices)")
            else:
                # The mosaics were built fine — nothing was stored. Say so, or this reads as
                # a healthy cycle in the journal (BUG-0109).
                logger.error(f"❌ Heatmap {time_key} NOT PUBLISHED ({len(complete_device_list)} devices "
                             f"processed): uploads failed, storage still holds the previous cycle. "
                             f"If the error is XMinioStorageFull, check `df -i` on the storage VM — "
                             f"inodes, not bytes.")
            self.write_status(time_key, success, '' if success else 'Upload failed')
            
        except Exception as e:
            logger.error(f"❌ Error processing {time_key}: {e}")
            self.write_status(time_key, False, str(e))
    
    def get_hosts_devices(self, attempts: int = 3, retry_delay: int = 3) -> List[Dict]:
        """Get hosts and devices, retrying briefly: the local Flask server runs a
        single worker, so a restart makes one call fail and would otherwise punch a
        one-minute hole in the 24h buffer."""
        for attempt in range(1, attempts + 1):
            hosts_devices = self._fetch_hosts_devices()
            if hosts_devices:
                return hosts_devices
            if attempt < attempts:
                logger.warning(f"⚠️ No hosts on attempt {attempt}/{attempts}, retrying in {retry_delay}s")
                time.sleep(retry_delay)
        return []

    def _fetch_hosts_devices(self) -> List[Dict]:
        """Get hosts and devices via server API endpoint (single attempt)"""
        try:
            import requests
            
            # Hardcoded: heatmap_processor ALWAYS runs in same container as Flask
            # No need for complex environment variable logic
            api_url = 'http://localhost:5109/server/system/getAllHosts'
            
            # Call server API to get all hosts. /server/* is closed by default
            # (TASK-09): present the shared service key or the guard answers 401.
            from shared.src.lib.utils.build_url_utils import server_auth_headers
            logger.info(f"📡 Making API request to: {api_url}")
            response = requests.get(api_url, headers=server_auth_headers(), timeout=10)
            logger.info(f"📨 Response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"❌ Server API returned status {response.status_code}")
                return []
            
            api_result = response.json()
            if not api_result.get('success', False):
                logger.error(f"❌ Server API error: {api_result.get('error', 'Unknown error')}")
                return []
            
            # API returns hosts as a list, not a dict
            hosts_list = api_result.get('hosts', [])
            logger.info(f"✅ Successfully fetched {len(hosts_list)} hosts from server")
            
            all_hosts = {host['host_name']: host for host in hosts_list}
            hosts_devices = []
            
            for host_name, host_data in all_hosts.items():
                devices = host_data.get('devices', [])
                
                if isinstance(devices, list) and devices:
                    for device in devices:
                        device_id = device.get('device_id', 'device1')
                        device_name = device.get('device_name', 'Unknown')
                        capabilities = device.get('device_capabilities', {})
                        av_capability = capabilities.get('av')
                        
                        logger.debug(f"🔧 Device {device_id} ({device_name}): AV={av_capability}")
                        
                        if (isinstance(capabilities, dict) and 'av' in capabilities and av_capability):
                            hosts_devices.append({
                                'host_name': host_name,
                                'device_id': device_id,
                                'device_name': device_name,
                                'host_data': host_data
                            })
                else:
                    host_capabilities = host_data.get('capabilities', {})
                    av_capability = host_capabilities.get('av')
                    logger.debug(f"🔧 Host {host_name}: AV={av_capability}")
                    
                    if (isinstance(host_capabilities, dict) and 'av' in host_capabilities and av_capability):
                        hosts_devices.append({
                            'host_name': host_name,
                            'device_id': 'host',
                            'device_name': 'host',
                            'host_data': host_data
                        })
            
            logger.info(f"🎯 Total AV devices found: {len(hosts_devices)}")
            return hosts_devices
            
        except Exception as e:
            logger.error(f"❌ Error getting hosts from API: {e}")
            return []
    
    def _fetch_device_capture(self, device: Dict) -> Optional[Dict]:
        """Fetch current capture for a single device (for parallel execution)"""
        try:
            from shared.src.lib.utils.build_url_utils import call_host
            
            host_name = device['host_name']
            device_id = device['device_id']
            device_name = device.get('device_name', 'Unknown')
            host_data = device['host_data']
            
            logger.info(f"🔗 [{host_name}/{device_id}/{device_name}] Calling host monitoring endpoint")

            # Use centralized call_host() which automatically adds API key
            response_data, status_code = call_host(
                host_data,
                '/host/monitoring/latest-json',
                method='POST',
                data={'device_id': device_id},
                timeout=10
            )
            
            logger.info(f"📥 [{host_name}/{device_id}/{device_name}] Response: HTTP {status_code}")

            if status_code == 200:
                if response_data.get('success') and 'json_data' in response_data and 'filename' in response_data:
                    # Host returns json_data directly - no need for separate request
                    json_data = response_data['json_data']
                    filename = response_data['filename']
                    
                    # Extract sequence from filename
                    import re
                    sequence_match = re.search(r'capture_(\d+)', filename)
                    sequence = sequence_match.group(1) if sequence_match else ''
                    
                    if sequence:
                        # Extract capture folder from json_data paths (works for all devices including host!)
                        capture_folder = None
                        search_fields = ['frame_path', 'thumbnail_path', 'last_3_filenames', 'last_3_thumbnails',
                                       'freeze_comparisons']  # freeze_comparisons contains paths too
                        
                        def _extract_capture_folder_from_path(path_value: str) -> Optional[str]:
                            if not path_value:
                                return None
                            normalized_path = str(path_value).replace('\\', '/')
                            match = re.search(r'/stream/(capture[^/]+)/', normalized_path)
                            return match.group(1) if match else None
                        
                        for field in search_fields:
                            if field not in json_data or not json_data[field]:
                                continue
                            
                            field_value = json_data[field]
                            path = None
                            
                            if isinstance(field_value, str):
                                path = field_value
                            elif isinstance(field_value, list) and len(field_value) > 0:
                                # For freeze_comparisons, extract from dict
                                if isinstance(field_value[0], dict):
                                    path = field_value[0].get('current_capture_path') or field_value[0].get('previous_capture_path')
                                else:
                                    path = field_value[0]
                            
                            capture_folder = _extract_capture_folder_from_path(path)
                            if capture_folder:
                                logger.info(f"✅ [{host_name}/{device_id}] Extracted '{capture_folder}' from {field}")
                                break
                        
                        # If key names are malformed, scan all nested string values as fallback
                        if not capture_folder:
                            def _scan_for_capture_folder(value) -> Optional[str]:
                                if isinstance(value, str):
                                    return _extract_capture_folder_from_path(value)
                                if isinstance(value, dict):
                                    for v in value.values():
                                        found = _scan_for_capture_folder(v)
                                        if found:
                                            return found
                                if isinstance(value, list):
                                    for v in value:
                                        found = _scan_for_capture_folder(v)
                                        if found:
                                            return found
                                return None
                            
                            capture_folder = _scan_for_capture_folder(json_data)
                            if capture_folder:
                                logger.info(f"✅ [{host_name}/{device_id}] Extracted '{capture_folder}' from nested scan")
                        
                        # Final fallback when capture folder can't be derived from json_data paths
                        # host devices always use 'capture', emulator devices use 'captureN' matching deviceN
                        if not capture_folder:
                            if device_id == 'host':
                                capture_folder = 'capture'
                            else:
                                device_num = ''.join(filter(str.isdigit, device_id)) or '1'
                                capture_folder = f'capture{device_num}'
                            logger.warning(f"⚠️ [{host_name}/{device_id}] No paths in json_data, using default '{capture_folder}'")
                        
                        # Build URLs - try extracted folder first, fall back to device config
                        from shared.src.lib.utils.build_url_utils import buildHostUrl, buildCaptureUrl, buildMetadataUrl
                        
                        capture_filename = f"capture_{sequence}.jpg"
                        json_filename = f"capture_{sequence}.json"
                        
                        if capture_folder:
                            # Use extracted capture folder
                            # Build URL with 'host/' prefix to match API call pattern
                            image_url = buildHostUrl(host_data, f'host/stream/{capture_folder}/captures/{capture_filename}')
                            json_url = buildHostUrl(host_data, f'host/stream/{capture_folder}/metadata/{json_filename}')
                        else:
                            # Fallback: use device config (works for devices with proper config)
                            logger.warning(f"⚠️ [{host_name}/{device_id}] No paths in json_data, using device config fallback")
                            try:
                                image_url = buildCaptureUrl(host_data, capture_filename, device_id)
                                json_url = buildMetadataUrl(host_data, json_filename, device_id)
                            except Exception as e:
                                logger.error(f"❌ [{host_name}/{device_id}] Fallback also failed: {e}")
                                return None
                        
                        logger.info(f"✅ [{host_name}/{device_id}] Built URLs from {capture_folder}:")
                        logger.info(f"   image_url: {image_url}")
                        logger.info(f"   json_url: {json_url}")
                        
                        # Analysis data is already in json_data
                        analysis_data = json_data if json_data.get('analyzed') else None
                        
                        logger.info(f"✅ Got json_data for {host_name}/{device_id}/{device_name}: sequence={sequence}")
                        
                        return {
                            'host_name': host_name,
                            'device_id': device_id,
                            'device_name': device_name,
                            'image_url': image_url,
                            'json_url': json_url,
                            'analysis': analysis_data,
                            'timestamp': response_data.get('timestamp', ''),
                            'sequence': sequence
                        }
                    else:
                        error_msg = response_data.get('error', 'Unknown error')
                        logger.warning(f"⚠️ No latest JSON for {host_name}/{device_id}/{device_name}: {error_msg}")
                        logger.warning(f"   Full response: {response_data}")
            else:
                logger.error(f"❌ API error for {host_name}/{device_id}/{device_name}: HTTP {status_code}")
                logger.error(f"   Error response: {response_data}")
        except Exception as e:
            logger.error(f"❌ Error fetching capture for {host_name}/{device_id}/{device_name}: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   Exception details: {str(e)}")
        
        return None
    
    def fetch_current_captures(self, hosts_devices: List[Dict]) -> List[Dict]:
        """Fetch current captures for all devices IN PARALLEL (OPTIMIZED)"""
        try:
            logger.info(f"🚀 Fetching captures for {len(hosts_devices)} devices in parallel...")
            start_time = time.time()
            
            current_captures = []
            
            # PERFORMANCE: Parallel execution with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(10, len(hosts_devices))) as executor:
                # Submit all tasks
                future_to_device = {
                    executor.submit(self._fetch_device_capture, device): device 
                    for device in hosts_devices
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_device):
                    device = future_to_device[future]
                    try:
                        result = future.result()
                        if result:
                            current_captures.append(result)
                            logger.info(f"✅ {result['host_name']}/{result['device_id']}: capture_{result['sequence']}.jpg")
                    except Exception as e:
                        logger.error(f"❌ Future failed for {device.get('host_name')}/{device.get('device_id')}: {e}")
            
            elapsed = time.time() - start_time
            logger.info(f"🎯 Fetched {len(current_captures)} captures from {len(hosts_devices)} devices in {elapsed:.2f}s (parallel)")
            return current_captures
            
        except Exception as e:
            logger.error(f"❌ Error fetching current captures: {e}")
            return []
    
    def create_complete_device_list(self, hosts_devices: List[Dict], current_captures: List[Dict]) -> List[Dict]:
        """Create complete device list with placeholders for missing captures"""
        complete_list = []
        
        # Create lookup for current captures
        captures_by_device = {}
        for capture in current_captures:
            key = f"{capture['host_name']}/{capture['device_id']}"
            captures_by_device[key] = capture
        
        # Process all expected devices
        for device in hosts_devices:
            host_name = device['host_name']
            device_id = device['device_id']
            key = f"{host_name}/{device_id}"
            
            if key in captures_by_device:
                # Device has current capture - use it
                complete_list.append(captures_by_device[key])
            else:
                # Device missing capture - create placeholder
                placeholder = {
                    'host_name': host_name,
                    'device_id': device_id,
                    'device_name': device.get('device_name', 'Unknown'),
                    'image_url': None,  # No image available
                    'json_url': None,   # No JSON available
                    'analysis': {},     # Empty analysis
                    'timestamp': '',    # No timestamp
                    'sequence': 'missing',
                    'is_placeholder': True,  # Mark as placeholder
                    'host_data': device['host_data']  # Keep host data for device info
                }
                complete_list.append(placeholder)
        
        return complete_list
    
    def save_heatmap_locally(self, time_key: str, mosaic_image: Image.Image) -> str:
        """Save heatmap locally before uploading for preview/debugging"""
        try:
            import os
            
            # Create heatmaps directory if it doesn't exist
            heatmaps_dir = os.path.join(os.path.dirname(__file__), '..', 'heatmaps')
            os.makedirs(heatmaps_dir, exist_ok=True)
            
            # Save with timestamp for uniqueness
            local_path = os.path.join(heatmaps_dir, f'heatmap_{time_key}.jpg')
            mosaic_image.save(local_path, format='JPEG', quality=85)
            
            return local_path
            
        except Exception as e:
            logger.warning(f"⚠️ Could not save heatmap locally: {e}")
            return "Failed to save locally"
    
    def log_consolidated_json(self, analysis_json: Dict):
        """Display consolidated JSON data in logs"""
        logger.info(f"📊 CONSOLIDATED JSON DATA:")
        logger.info(f"   🕐 Time Key: {analysis_json['time_key']}")
        logger.info(f"   📅 Timestamp: {analysis_json['timestamp']}")
        logger.info(f"   🖥️  Total Devices: {analysis_json['hosts_count']}")
        logger.info(f"   🚨 Incidents Count: {analysis_json['incidents_count']}")
        
        logger.info(f"   📋 Device Status Summary:")
        active_count = 0
        missing_count = 0
        incident_devices = []
        
        for device in analysis_json['devices']:
            if device['status'] == 'missing':
                missing_count += 1
            else:
                active_count += 1
                
            # Check for incidents using raw analysis data (handle None)
            analysis_data = device.get('analysis_json') or {}
            has_incident = (
                analysis_data.get('blackscreen', False) or
                analysis_data.get('freeze', False) or
                analysis_data.get('audio') is False
            )
            
            if has_incident and device['status'] != 'missing':
                incident_types = []
                if analysis_data.get('blackscreen', False):
                    incident_types.append('blackscreen')
                if analysis_data.get('freeze', False):
                    incident_types.append('freeze')
                if analysis_data.get('audio') is False:
                    incident_types.append('no_audio')
                
                device_name = device.get('device_name', 'Unknown')
                incident_devices.append({
                    'device': f"{device['host_name']}/{device['device_id']}/{device_name}",
                    'incidents': incident_types
                })
        
        logger.info(f"      ✅ Active: {active_count}")
        logger.info(f"      ❌ Missing: {missing_count}")
        
        if incident_devices:
            logger.info(f"   🚨 Devices with Incidents:")
            for incident_device in incident_devices:
                incidents_str = ', '.join(incident_device['incidents'])
                logger.info(f"      🔴 {incident_device['device']}: {incidents_str}")
        else:
            logger.info(f"   ✅ No incidents detected")
    
    
    def filter_devices_by_status(self, devices_data: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Filter devices into OK and KO lists in single pass (OPTIMIZED)"""
        ok_devices = []
        ko_devices = []
        
        for device in devices_data:
            analysis_data = device.get('analysis') or {}
            is_placeholder = device.get('is_placeholder', False)

            # Placeholders (missing devices) belong to neither OK nor KO.
            if is_placeholder:
                continue

            # Audio N/A (None/absent) is not a loss - only audio === False counts.
            has_incident = (
                analysis_data.get('blackscreen', False) or
                analysis_data.get('freeze', False) or
                analysis_data.get('audio') is False
            )

            if has_incident:
                ko_devices.append(device)
            else:
                ok_devices.append(device)

        return ok_devices, ko_devices
    
    def _get_cached_font(self, font_name: str, size: int = None):
        """Get font from cache or load it (OPTIMIZED)"""
        from PIL import ImageFont
        
        cache_key = f"{font_name}_{size}" if size else font_name
        
        if cache_key not in self._fonts_cache:
            if font_name == 'default':
                self._fonts_cache[cache_key] = ImageFont.load_default()
            else:
                try:
                    self._fonts_cache[cache_key] = ImageFont.truetype(font_name, size)
                except:
                    self._fonts_cache[cache_key] = ImageFont.load_default()
        
        return self._fonts_cache[cache_key]
    
    def add_border_and_label(self, img: Image.Image, image_data: Dict, cell_width: int, cell_height: int) -> Image.Image:
        """Add colored border and label to device image"""
        from PIL import ImageDraw
        
        # Check for incidents in raw analysis data
        analysis_data = image_data.get('analysis_json') or image_data.get('analysis') or {}
        is_placeholder = image_data.get('is_placeholder', False)

        # An incident is a real video/audio loss. Audio N/A (None/absent) is NOT a loss,
        # so it must never downgrade the border - only audio === False is an audio loss.
        has_incident = (
            analysis_data.get('blackscreen', False) or
            analysis_data.get('freeze', False) or
            analysis_data.get('audio') is False
        )

        # Add border
        # Grey is reserved for genuinely missing devices (placeholders). A real capture
        # with video OK gets green even when audio is N/A.
        if is_placeholder:
            border_color = (128, 128, 128)
        elif has_incident:
            border_color = (255, 0, 0)
        else:
            border_color = (0, 255, 0)
            
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, cell_width-1, cell_height-1], outline=border_color, width=4)
        
        # Add label - use cached font (OPTIMIZED)
        host_name = image_data.get('host_name', '')
        device_name = _clean_device_name(image_data.get('device_name'), image_data.get('device_id'))
        # Host (VNC) device_name is just the host name once '_Host' is stripped,
        # so avoid the redundant 'X_X' and show the host name alone.
        label = f"{host_name}_{device_name}" if device_name and device_name != host_name else host_name
        
        try:
            font = self._get_cached_font('default')
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            x_pos = cell_width - text_width - 5
            y_pos = cell_height - text_height - 5
            
            draw.text((x_pos, y_pos), label, fill='white', font=font)
        except:
            draw.text((cell_width-150, cell_height-20), label, fill='white', font=self._get_cached_font('default'))
        
        return img
    
    def _download_and_process_image(self, image_data: Dict, cell_width: int, cell_height: int) -> Tuple[Optional[Image.Image], Dict]:
        """Download and process a single image for mosaic (for parallel execution)"""
        host_name = image_data.get('host_name', 'unknown')
        device_id = image_data.get('device_id', 'unknown')
        try:
            image_url = image_data.get('image_url')
            
            if not image_url or image_url == 'None':
                return None, image_data
            
            response = self.session.get(image_url, timeout=10)
            if response.status_code == 200:
                img = Image.open(io.BytesIO(response.content))
                # Preserve aspect ratio: fit within cell, center on black background
                img.thumbnail((cell_width, cell_height), Image.Resampling.BILINEAR)
                cell = Image.new('RGB', (cell_width, cell_height), color='black')
                x_offset = (cell_width - img.width) // 2
                y_offset = (cell_height - img.height) // 2
                cell.paste(img, (x_offset, y_offset))
                img_with_border = self.add_border_and_label(cell, image_data, cell_width, cell_height)
                return img_with_border, image_data
            else:
                logger.error(f"❌ [{host_name}/{device_id}] Image download failed: HTTP {response.status_code} - {image_url}")
                raise Exception(f"HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"❌ [{host_name}/{device_id}] Error loading image: {e} - {image_data.get('image_url')}")
            return None, image_data
    
    def create_mosaic_image(self, images_data: List[Dict]) -> Image.Image:
        """Create mosaic image from device images - OPTIMIZED with parallel downloads"""
        if not images_data:
            logger.warning("⚠️ No images provided for mosaic - creating empty black image")
            return Image.new('RGB', (800, 600), color='black')
        
        logger.info(f"🎨 Creating mosaic from {len(images_data)} images")
        start_time = time.time()
        
        # Calculate grid layout
        count = len(images_data)
        if count <= 1:
            cols, rows = 1, 1
        elif count == 2:
            cols, rows = 2, 1
        elif count <= 4:
            cols, rows = 2, 2
        elif count <= 6:
            cols, rows = 3, 2
        elif count <= 9:
            cols, rows = 3, 3
        else:
            # For more than 9 devices, use 6 columns max
            cols = min(6, count)
            rows = math.ceil(count / cols)
        
        logger.info(f"📐 Grid layout: {cols}x{rows} (total cells: {cols*rows})")
        
        # Create mosaic
        cell_width, cell_height = 400, 300
        mosaic_width = cols * cell_width
        mosaic_height = rows * cell_height
        
        logger.info(f"🖼️ Mosaic dimensions: {mosaic_width}x{mosaic_height} pixels ({cell_width}x{cell_height} per cell)")
        mosaic = Image.new('RGB', (mosaic_width, mosaic_height), color='black')
        
        # PERFORMANCE: Download and process images in parallel
        processed_images = {}
        images_to_download = []
        
        for i, image_data in enumerate(images_data):
            if i >= cols * rows:
                break
            
            image_url = image_data.get('image_url')
            is_placeholder = image_data.get('is_placeholder', False)
            
            if not is_placeholder and image_url and image_url != 'None':
                images_to_download.append((i, image_data))
        
        # Download images in parallel if there are any
        if images_to_download:
            logger.info(f"📥 Downloading {len(images_to_download)} images in parallel...")
            with ThreadPoolExecutor(max_workers=min(10, len(images_to_download))) as executor:
                future_to_index = {
                    executor.submit(self._download_and_process_image, img_data, cell_width, cell_height): idx
                    for idx, img_data in images_to_download
                }
                
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        result_img, img_data = future.result()
                        if result_img:
                            processed_images[idx] = result_img
                            device_name = img_data.get('device_name', 'Unknown')
                            logger.debug(f"✅ Downloaded {img_data['host_name']}/{img_data['device_id']}/{device_name}")
                    except Exception as e:
                        logger.error(f"❌ Future failed for image {idx}: {e}")
        
        # Now assemble the mosaic
        for i, image_data in enumerate(images_data):
            if i >= cols * rows:
                break
                
            row = i // cols
            col = i % cols
            
            x = col * cell_width
            y = row * cell_height
            
            # Check if we have a pre-downloaded image
            if i in processed_images:
                # Use pre-downloaded and processed image
                mosaic.paste(processed_images[i], (x, y))
                continue
            
            # Otherwise create placeholder
            image_url = image_data.get('image_url')
            is_placeholder = image_data.get('is_placeholder', False)
            
            if True:  # Always create placeholder for non-downloaded images
                # Create placeholder with device info
                placeholder_color = '#2a2a2a' if is_placeholder else '#4a2a2a'  # Dark gray for missing, dark red for None
                placeholder = Image.new('RGB', (cell_width, cell_height), color=placeholder_color)
                
                # Add text overlay with device info
                try:
                    from PIL import ImageDraw
                    draw = ImageDraw.Draw(placeholder)
                    
                    # Use cached fonts (OPTIMIZED)
                    font = self._get_cached_font("/System/Library/Fonts/Arial.ttf", 24)
                    small_font = self._get_cached_font("/System/Library/Fonts/Arial.ttf", 16)
                    
                    # Device info text
                    host_name = image_data['host_name']
                    device_name = _clean_device_name(image_data.get('device_name'), image_data.get('device_id')) or 'Unknown'

                    # Center the text
                    text1 = f"{host_name}"
                    text2 = f"{device_name}"
                    text3 = "NO CAPTURE" if is_placeholder else "NOT FOUND"
                    
                    # Calculate text positions (centered)
                    bbox1 = draw.textbbox((0, 0), text1, font=font)
                    bbox2 = draw.textbbox((0, 0), text2, font=small_font)
                    bbox3 = draw.textbbox((0, 0), text3, font=small_font)
                    
                    text1_x = (cell_width - (bbox1[2] - bbox1[0])) // 2
                    text2_x = (cell_width - (bbox2[2] - bbox2[0])) // 2
                    text3_x = (cell_width - (bbox3[2] - bbox3[0])) // 2
                    
                    # Draw text
                    draw.text((text1_x, cell_height//2 - 40), text1, fill='white', font=font)
                    draw.text((text2_x, cell_height//2 - 10), text2, fill='lightgray', font=small_font)
                    draw.text((text3_x, cell_height//2 + 15), text3, fill='red', font=small_font)
                    
                except Exception as e:
                    logger.warning(f"⚠️ Could not add text to placeholder: {e}")
                
                mosaic.paste(placeholder, (x, y))
                status_text = "placeholder" if is_placeholder else "not found"
                device_name = image_data.get('device_name', 'Unknown')
                logger.debug(f"📝 Added {status_text} for {image_data['host_name']}/{image_data['device_id']}/{device_name}")
        
        elapsed = time.time() - start_time
        logger.info(f"🎨 Mosaic created in {elapsed:.2f}s ({len(processed_images)} images downloaded in parallel)")
        return mosaic
    
    def create_analysis_json(self, images_data: List[Dict], time_key: str) -> Dict:
        """Create analysis JSON for the minute - replace local paths with R2 URLs from alerts"""
        devices = []
        incidents_count = 0
        
        for image_data in images_data:
            analysis = image_data.get('analysis', {})
            is_placeholder = image_data.get('is_placeholder', False)
            
            # Check for incidents using raw analysis data (only for real captures with real data)
            has_incidents = False
            has_real_analysis = analysis and any(key in analysis for key in ['blackscreen', 'freeze', 'audio'])
            if not is_placeholder and has_real_analysis:
                has_incidents = (
                    analysis.get('blackscreen', False) or
                    analysis.get('freeze', False) or
                    analysis.get('audio') is False
                )
            
            if has_incidents:
                incidents_count += 1
            
            # Build device entry - use raw analysis data with local paths (24h retention allows local access)
            device_entry = {
                'host_name': image_data['host_name'],
                'device_id': image_data['device_id'],
                'device_name': image_data.get('device_name'),  # Include device_name for frontend tooltip
                'image_url': image_data.get('image_url'),
                'json_url': image_data.get('json_url'),
                'sequence': image_data.get('sequence', 'missing'),
                'analysis_json': analysis,  # Raw analysis with local paths (available for 24h)
                'status': 'missing' if is_placeholder else 'active',
                'is_placeholder': is_placeholder
            }
            
            devices.append(device_entry)
        
        return {
            'time_key': time_key,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'devices': devices,
            'incidents_count': incidents_count,
            'hosts_count': len(images_data)
        }
    
    def image_to_bytes(self, image: Image.Image) -> bytes:
        """Convert PIL Image to bytes"""
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
    
    def upload_heatmap_files(self, time_key: str, mosaic_image: Image.Image, analysis_json: Dict, ok_mosaic_image: Optional[Image.Image] = None, ko_mosaic_image: Optional[Image.Image] = None) -> Tuple[bool, Dict]:
        """Upload mosaic image and analysis JSON to R2"""
        try:
            import tempfile
            import os
            
            # Create temporary files
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as img_temp:
                mosaic_image.save(img_temp.name, format='JPEG', quality=85)
                img_temp_path = img_temp.name
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as json_temp:
                json.dump(analysis_json, json_temp, indent=2)
                json_temp_path = json_temp.name
            
            # Handle OK and KO mosaics if provided
            ok_img_temp_path = None
            ko_img_temp_path = None
            if ok_mosaic_image:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as ok_img_temp:
                    ok_mosaic_image.save(ok_img_temp.name, format='JPEG', quality=85)
                    ok_img_temp_path = ok_img_temp.name
            if ko_mosaic_image:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as ko_img_temp:
                    ko_mosaic_image.save(ko_img_temp.name, format='JPEG', quality=85)
                    ko_img_temp_path = ko_img_temp.name
            
            try:
                # Prepare file mappings for batch upload
                file_mappings = [
                    {
                        'local_path': img_temp_path,
                        'remote_path': f'heatmaps/{self.server_path}/{time_key}.jpg',
                        'content_type': 'image/jpeg'
                    },
                    {
                        'local_path': json_temp_path,
                        'remote_path': f'heatmaps/{self.server_path}/{time_key}.json',
                        'content_type': 'application/json'
                    }
                ]
                
                # Add OK and KO mosaics if available
                if ok_img_temp_path:
                    file_mappings.append({
                        'local_path': ok_img_temp_path,
                        'remote_path': f'heatmaps/{self.server_path}/{time_key}_ok.jpg',
                        'content_type': 'image/jpeg'
                    })
                if ko_img_temp_path:
                    file_mappings.append({
                        'local_path': ko_img_temp_path,
                        'remote_path': f'heatmaps/{self.server_path}/{time_key}_ko.jpg',
                        'content_type': 'image/jpeg'
                    })
                
                # Upload files using CloudflareUtils
                # Use for_report_assets=True so mosaic URLs work in generated HTML reports (14-day signed URLs in private mode)
                cloudflare_utils = get_cloudflare_utils()
                result = cloudflare_utils.upload_files(file_mappings, for_report_assets=True)
                
                # Log all uploaded URLs
                uploaded_urls = {}
                if result.get('uploaded_files'):
                    logger.info(f"✅ Uploaded {len(result['uploaded_files'])} files for {time_key}:")
                    for uploaded in result['uploaded_files']:
                        url = uploaded.get('url', 'URL not available')
                        logger.info(f"   🔗 {uploaded['remote_path']}: {url}")
                        
                        # Store main URLs for return
                        if uploaded['remote_path'].endswith(f'{time_key}.jpg'):
                            uploaded_urls['mosaic_url'] = url
                        elif uploaded['remote_path'].endswith(f'{time_key}.json'):
                            uploaded_urls['json_url'] = url
                
                failed_uploads = result.get('failed_uploads') or []
                if failed_uploads:
                    logger.error(f"❌ Failed uploads for {time_key}:")
                    for failed in failed_uploads:
                        logger.error(f"   ❌ {failed['remote_path']}: {failed['error']}")

                # Report the real outcome. This used to `return True` unconditionally, so a
                # cycle where every upload failed still logged "Generated heatmap" and wrote
                # a success status — the frontend's "data may be outdated" was the only hint,
                # and the heatmap silently stopped publishing for ~8h (BUG-0109).
                return (not failed_uploads), uploaded_urls
                    
            finally:
                # Clean up temporary files
                if os.path.exists(img_temp_path):
                    os.unlink(img_temp_path)
                if os.path.exists(json_temp_path):
                    os.unlink(json_temp_path)
                if ok_img_temp_path and os.path.exists(ok_img_temp_path):
                    os.unlink(ok_img_temp_path)
                if ko_img_temp_path and os.path.exists(ko_img_temp_path):
                    os.unlink(ko_img_temp_path)
                    
        except Exception as e:
            logger.error(f"❌ Error uploading heatmap files for {time_key}: {e}")
            return False, {}
    
    def wait_for_next_minute(self):
        """Wait until next minute boundary"""
        now = datetime.now(timezone.utc)
        seconds_to_wait = 60 - now.second
        logger.info(f"⏳ Waiting {seconds_to_wait}s for next minute...")
        time.sleep(seconds_to_wait)


if __name__ == "__main__":
    # Run processor directly
    processor = HeatmapProcessor()
    processor.start()
