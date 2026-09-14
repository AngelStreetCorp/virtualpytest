#!/usr/bin/env python3
"""
Centralized Storage Path Utilities

Single source of truth for hot/cold storage path resolution.
Eliminates path duplication across the codebase.

HOT/COLD ARCHITECTURE:
- RAM MODE: Files in /hot/ subdirectory (tmpfs mounted)
- SD MODE: Files in root directory (traditional)

This module provides functions to:
- Detect storage mode (RAM vs SD)
- Resolve correct paths automatically
- Get device mappings from .env
"""
import os
import sys
import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# =====================================================
# SECURITY UTILITIES
# =====================================================

def sanitize_folder_name(folder_name: str) -> str:
    """
    Sanitize a folder name to prevent path traversal attacks.
    
    Only allows alphanumeric characters, underscores, and hyphens.
    Blocks dangerous patterns like '..', '/', '\', etc.
    
    Args:
        folder_name: Raw folder name from user input (URL params, etc.)
        
    Returns:
        Sanitized folder name safe for use in file paths
        
    Raises:
        ValueError: If folder name contains dangerous characters or is empty
        
    Example:
        sanitize_folder_name('capture1') -> 'capture1'
        sanitize_folder_name('../etc') -> raises ValueError
    """
    if not folder_name:
        raise ValueError('Folder name cannot be empty')
    
    # Block path traversal attempts
    if '..' in folder_name or '/' in folder_name or '\\' in folder_name:
        raise ValueError(f'Invalid folder name (path traversal not allowed): {folder_name}')
    
    # Only allow safe characters: alphanumeric, underscore, hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', folder_name):
        raise ValueError(f'Invalid folder name (only alphanumeric, underscore, hyphen allowed): {folder_name}')

    # Return werkzeug's canonical form: it is identical for every name that passed the checks
    # above, and it is the sanitizer SAST tools recognise on the way to filesystem sinks.
    from werkzeug.utils import secure_filename
    cleaned = secure_filename(folder_name)
    if cleaned != folder_name:
        raise ValueError(f'Invalid folder name: {folder_name}')
    return cleaned
    

# =====================================================
# BASE PATH CONFIGURATION (NO HARDCODING!)
# =====================================================

# Single source of truth for stream base path
# Lazy-resolved on first call (after dotenv has loaded env vars)
_STREAM_BASE_PATH = None

def get_stream_base_path():
    """
    Get the base stream path (configurable via environment).
    CENTRALIZED - Use this instead of hardcoding '/var/www/html/stream'!
    
    On Windows, auto-derives from HOST_VIDEO_CAPTURE_PATH if STREAM_BASE_PATH is not set.
    Lazy-resolved on first call to ensure env vars are loaded.
    
    Returns:
        Base stream path (e.g., '/var/www/html/stream' or 'C:\\virtualpytest\\stream')
    """
    global _STREAM_BASE_PATH
    if _STREAM_BASE_PATH is not None:
        return _STREAM_BASE_PATH
    
    explicit = os.getenv('STREAM_BASE_PATH')
    if explicit:
        _STREAM_BASE_PATH = explicit.rstrip('/\\')
        return _STREAM_BASE_PATH
    
    import platform
    if platform.system() != 'Windows':
        _STREAM_BASE_PATH = '/var/www/html/stream'
        return _STREAM_BASE_PATH
    
    # Windows: derive from HOST_VIDEO_CAPTURE_PATH if available
    # e.g., C:\virtualpytest\stream\capture -> parent = C:\virtualpytest\stream
    # Strip trailing slashes first — dirname('path\') returns 'path' instead of parent
    host_capture = os.getenv('HOST_VIDEO_CAPTURE_PATH')
    if host_capture:
        _STREAM_BASE_PATH = os.path.dirname(host_capture.rstrip('/\\'))
        print(f"[@storage_path_utils] Windows: STREAM_BASE_PATH auto-detected from HOST_VIDEO_CAPTURE_PATH={host_capture} -> {_STREAM_BASE_PATH}")
        return _STREAM_BASE_PATH
    
    # Try DEVICE1 path
    dev1_capture = os.getenv('DEVICE1_VIDEO_CAPTURE_PATH')
    if dev1_capture:
        _STREAM_BASE_PATH = os.path.dirname(dev1_capture.rstrip('/\\'))
        print(f"[@storage_path_utils] Windows: STREAM_BASE_PATH auto-detected from DEVICE1_VIDEO_CAPTURE_PATH={dev1_capture} -> {_STREAM_BASE_PATH}")
        return _STREAM_BASE_PATH
    
    # Last resort
    _STREAM_BASE_PATH = 'C:\\virtualpytest\\stream'
    print(f"[@storage_path_utils] WARNING: STREAM_BASE_PATH not set, using default: {_STREAM_BASE_PATH}")
    return _STREAM_BASE_PATH

def get_active_captures_conf_path():
    """
    Get the path to active_captures.conf file.
    CENTRALIZED - Single source of truth for capture config location!
    
    This file tracks FFmpeg processes and their quality settings.
    CSV Format: /var/www/html/stream/capture1,PID,quality
    
    Returns:
        Full path to active_captures.conf (e.g., '/var/www/html/stream/active_captures.conf')
    """
    return os.path.join(get_stream_base_path(), 'active_captures.conf')

def get_capture_folder_from_device_id(device_id: str) -> str:
    """
    Get capture folder name from device_id by reading .env configuration.
    CENTRALIZED - Single source of truth for device_id → capture_folder mapping!
    
    This avoids hardcoding device1 → capture1, as the mapping is defined in .env:
    - DEVICE1_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture1
    - DEVICE2_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture5  # Non-standard!
    
    Args:
        device_id: Device ID (e.g., 'device1', 'device2', 'host')
    
    Returns:
        Capture folder name (e.g., 'capture1', 'capture5')
    
    Raises:
        ValueError: If device_id is not configured in .env
    
    Example:
        >>> get_capture_folder_from_device_id('device1')
        'capture1'
        >>> get_capture_folder_from_device_id('host')
        'capture1'
    """
    # Get capture path directly from environment variables
    if device_id == 'host':
        capture_path = os.getenv('HOST_VIDEO_CAPTURE_PATH')
    else:
        # Extract device number from device_id (e.g., 'device1' -> '1')
        device_num = device_id.replace('device', '')
        if device_num.isdigit():
            capture_path = os.getenv(f'DEVICE{device_num}_VIDEO_CAPTURE_PATH')
        else:
            capture_path = None
    
    if not capture_path:
        raise ValueError(f'No capture path configured in .env for device_id: {device_id}')
    
    # Extract folder name from full path (e.g., '/var/www/html/stream/capture1' -> 'capture1')
    return os.path.basename(capture_path)

def get_device_base_path(device_folder):
    """
    Get device base directory path.
    CENTRALIZED - No more hardcoding!
    
    Args:
        device_folder: Device folder name (e.g., 'capture1', 'capture2')
        
    Returns:
        Full device base path (e.g., '/var/www/html/stream/capture1')
    """
    return os.path.join(get_stream_base_path(), device_folder)

# Cache for device mappings to avoid repeated .env lookups
_device_mapping_cache = {}

# Load environment variables using same approach as incident_manager.py
try:
    from dotenv import load_dotenv
    
    # Get script paths (storage_path_utils.py is in shared/src/lib/utils/)
    current_dir = os.path.dirname(os.path.abspath(__file__))  # shared/src/lib/utils/
    shared_lib_dir = os.path.dirname(current_dir)  # shared/src/lib/
    shared_src_dir = os.path.dirname(shared_lib_dir)  # shared/src/
    shared_dir = os.path.dirname(shared_src_dir)  # shared/
    project_root = os.path.dirname(shared_dir)  # project root
    
    # Load project root .env first
    # Use utf-8-sig encoding to handle Windows BOM (Byte Order Mark) transparently
    project_env_path = os.path.join(project_root, '.env')
    if os.path.exists(project_env_path):
        load_dotenv(project_env_path, encoding='utf-8-sig')
        logger.debug(f"Loaded project environment from {project_env_path}")
    
    # Load backend_host .env second (correct path from project root)
    backend_env_path = os.path.join(project_root, 'backend_host', 'src', '.env')
    if os.path.exists(backend_env_path):
        load_dotenv(backend_env_path, encoding='utf-8-sig')
        logger.debug(f"Loaded backend_host environment from {backend_env_path}")
        
        # Log critical variables for debugging
        host_capture = os.getenv('HOST_VIDEO_CAPTURE_PATH')
        logger.debug(f"HOST_VIDEO_CAPTURE_PATH={host_capture}")
    else:
        logger.warning(f"backend_host .env not found at {backend_env_path}")
        
except ImportError:
    logger.warning("python-dotenv not available, relying on system environment")



def get_device_info_from_capture_folder(capture_folder):
    """
    Get device info from .env by matching capture path - LIGHTWEIGHT (no DB)
    Extracted from IncidentManager to avoid loading incidents from database
    
    Returns:
        dict: Device info with keys:
            - device_id: Device identifier (e.g., 'device1', 'host')
            - device_name: Human-readable device name from env (e.g., 'Device 1')
            - device_model: Device model from env (e.g., 'H96_MAX', 'X96_MAX_PLUS')
            - stream_path: Video stream path
            - capture_path: Capture folder name (e.g., 'capture1')
    """
    # Check cache first
    if capture_folder in _device_mapping_cache:
        return _device_mapping_cache[capture_folder]
    
    base_path = get_stream_base_path()
    capture_path = os.path.join(base_path, capture_folder)
    logger.debug(f"[get_device_info] Looking up {capture_folder} -> {capture_path}")

    def _norm_path(path: str) -> str:
        if not path:
            return ''
        return os.path.normcase(os.path.normpath(path))
    
    # Check HOST first
    host_capture_path = os.getenv('HOST_VIDEO_CAPTURE_PATH')
    logger.debug(f"[get_device_info] HOST_VIDEO_CAPTURE_PATH={host_capture_path}")
    
    if _norm_path(host_capture_path) == _norm_path(capture_path):
        host_name = os.getenv('HOST_NAME', 'unknown')
        host_model = os.getenv('HOST_MODEL', 'unknown')
        host_stream_path = os.getenv('HOST_VIDEO_STREAM_PATH')
        device_info = {
            'device_id': 'host',
            'device_name': f"{host_name}_Host",
            'device_model': host_model,
            'stream_path': host_stream_path,
            'capture_path': capture_folder
        }
        _device_mapping_cache[capture_folder] = device_info
        return device_info
    
    # Check DEVICE1-4
    for i in range(1, 5):
        device_capture_path = os.getenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH')
        device_name = os.getenv(f'DEVICE{i}_NAME', f'device{i}')
        device_model = os.getenv(f'DEVICE{i}_MODEL', 'unknown')
        device_stream_path = os.getenv(f'DEVICE{i}_VIDEO_STREAM_PATH')
        
        if _norm_path(device_capture_path) == _norm_path(capture_path):
            device_info = {
                'device_id': f'device{i}',
                'device_name': device_name,
                'device_model': device_model,
                'stream_path': device_stream_path,
                'capture_path': capture_folder
            }
            _device_mapping_cache[capture_folder] = device_info
            return device_info
    
    # Fallback
    device_info = {'device_id': capture_folder, 'device_name': capture_folder, 'device_model': 'unknown', 'stream_path': None, 'capture_path': capture_folder}
    _device_mapping_cache[capture_folder] = device_info
    return device_info


def parse_active_captures_conf():
    """
    Parse active_captures.conf and return structured data.
    CSV Format: /var/www/html/stream/capture1,PID,quality
    
    Returns:
        List of dicts with 'directory', 'pid', 'quality'
    """
    active_captures_file = get_active_captures_conf_path()
    captures = []
    
    if os.path.exists(active_captures_file):
        try:
            with open(active_captures_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Support both comma and pipe delimiters (Windows run_ffmpeg used pipe historically)
                    if ',' in line:
                        parts = [p.strip() for p in line.split(',')]
                    else:
                        parts = [p.strip() for p in line.split('|')]

                    if len(parts) < 1 or not parts[0]:
                        continue

                    captures.append({
                        'directory': parts[0],
                        'pid': parts[1] if len(parts) > 1 else '',
                        'quality': parts[2] if len(parts) > 2 else ''
                    })
            
            #logger.debug(f"Parsed {len(captures)} capture entries from {active_captures_file}")
        except Exception as e:
            logger.error(f"❌ Error reading {active_captures_file}: {e}")
    
    return captures


def get_capture_base_directories():
    """
    Get list of capture base directories from /tmp/active_captures.conf
    Returns base paths like /var/www/html/stream/capture1 (not /captures subdirectory)
    
    This is the CENTRALIZED source of truth for all capture directory lookups.
    """
    captures = parse_active_captures_conf()
    base_dirs = [c['directory'] for c in captures if os.path.isdir(c['directory'])]
    
    if base_dirs:
        logger.info(f"✅ Loaded {len(base_dirs)} capture directories from active_captures.conf")
        return base_dirs

    # Fallback (Windows/dev): derive from env if active_captures.conf is missing or empty
    from shared.src.lib.utils.build_url_utils import normalize_capture_base_dir
    env_dirs = []
    host_capture = os.getenv('HOST_VIDEO_CAPTURE_PATH')
    if host_capture:
        env_dirs.append(host_capture)
    for i in range(1, 11):
        cap = os.getenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH')
        if cap:
            env_dirs.append(cap)

    fallback_dirs = []
    for path in env_dirs:
        base = normalize_capture_base_dir(path)
        if base and os.path.isdir(base):
            fallback_dirs.append(base)

    if fallback_dirs:
        logger.info(f"✅ Loaded {len(fallback_dirs)} capture directories from environment")
        return fallback_dirs
    
    return base_dirs


def is_ram_mode(capture_base_dir):
    """
    Check if capture directory uses RAM hot storage (Linux only).
    Returns True if /hot/ exists and is mounted as tmpfs.
    On Windows, returns True only if a 'hot' directory exists (opt-in).
    
    Args:
        capture_base_dir: Base directory like /var/www/html/stream/capture1
        
    Returns:
        True if RAM mode is active, False otherwise
    """
    import platform
    if platform.system() == 'Windows':
        # Windows: treat as RAM mode only if /hot exists (some setups mirror Linux layout)
        hot_path = os.path.join(capture_base_dir, 'hot')
        return os.path.exists(hot_path)

    hot_path = os.path.join(capture_base_dir, 'hot')
    
    if not os.path.exists(hot_path):
        return False
    
    # Check if it's a tmpfs mount (RAM)
    try:
        with open('/proc/mounts', 'r') as f:
            mounts = f.read()
            if hot_path in mounts and 'tmpfs' in mounts:
                return True
    except Exception:
        pass
    
    # If /hot/ exists but isn't tmpfs, still treat as RAM mode
    # (for development/testing on Linux)
    return True

def get_capture_storage_path(device_folder_or_path, subfolder):
    """
    Get the correct storage path based on hot/cold architecture.
    CENTRALIZED PATH RESOLUTION - Use this everywhere!
    
    Args:
        device_folder_or_path: Either:
            - Device folder name (e.g., 'capture1') - RECOMMENDED
            - Full base path (e.g., '/var/www/html/stream/capture1') - backward compatible
        subfolder: Subfolder name ('captures', 'thumbnails', 'segments', 'metadata')
        
    Returns:
        Path to the active storage location (hot if RAM mode, cold otherwise)
        
    Examples:
        # Recommended usage (just device name):
        get_capture_storage_path('capture1', 'captures')
        -> '/var/www/html/stream/capture1/hot/captures' (RAM mode)
        -> '/var/www/html/stream/capture1/captures' (SD mode)
        
        # Backward compatible (full path):
        get_capture_storage_path('/var/www/html/stream/capture1', 'captures')
        -> Same result as above
    """
    # Auto-detect if we got a device name or full path (handle both / and \ for cross-platform)
    if os.sep in device_folder_or_path or '/' in device_folder_or_path or ':' in device_folder_or_path:
        # Full path provided (backward compatible, works on both Linux and Windows)
        capture_base_dir = device_folder_or_path
        # Normalize if a subfolder path was provided (e.g., .../capture1/captures or .../capture1/hot/captures)
        from shared.src.lib.utils.build_url_utils import normalize_capture_base_dir
        capture_base_dir = normalize_capture_base_dir(capture_base_dir)
    else:
        # Device name provided (recommended) - build full path
        capture_base_dir = get_device_base_path(device_folder_or_path)
    
    # Check RAM mode and return appropriate path
    if is_ram_mode(capture_base_dir):
        # RAM mode: files in /hot/ subdirectory
        return os.path.join(capture_base_dir, 'hot', subfolder)
    else:
        # SD mode: files in root directory
        return os.path.join(capture_base_dir, subfolder)

def get_cold_storage_path(device_folder_or_path, subfolder):
    """
    Get COLD storage path (never uses /hot/ even in RAM mode).
    
    Used for:
    - Audio (MP3 chunks extracted directly to cold)
    - Transcripts (JSON files saved directly to cold)
    - Segments/metadata hour folders (final chunks in cold)
    
    Args:
        device_folder_or_path: Device folder name (e.g., 'capture1') or full path
        subfolder: Subfolder name ('audio', 'transcript', 'segments', 'metadata')
        
    Returns:
        Path to cold storage location (always device_base_path/subfolder)
        
    Examples:
        get_cold_storage_path('capture1', 'audio')
        -> '/var/www/html/stream/capture1/audio' (regardless of RAM mode)
    """
    # Auto-detect if we got a device name or full path (handle both / and \ for cross-platform)
    if os.sep in device_folder_or_path or '/' in device_folder_or_path or ':' in device_folder_or_path:
        # Full path provided (works on both Linux and Windows)
        capture_base_dir = device_folder_or_path
    else:
        # Device name provided - build full path
        capture_base_dir = get_device_base_path(device_folder_or_path)
    
    # Always return cold path (no /hot/ prefix)
    return os.path.join(capture_base_dir, subfolder)


# =====================================================
# HIGH-LEVEL CONVENIENCE FUNCTIONS
# =====================================================
# These functions provide direct access to specific storage paths.
# Other files should use these instead of building paths manually!
# =====================================================

def get_audio_path(device_folder):
    """
    Get audio storage path (HOT or COLD depending on mode).
    
    - HOT: Live MP3 chunks being created/appended in RAM
    - COLD: Final archived audio (SD mode only)
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to audio directory:
        - RAM mode: '/var/www/html/stream/capture1/hot/audio'
        - SD mode: '/var/www/html/stream/capture1/audio'
    """
    return get_capture_storage_path(device_folder, 'audio')


def get_transcript_path(device_folder):
    """
    Get transcript storage path (ALWAYS COLD).
    
    Transcript JSON files are saved directly to cold storage by transcript_accumulator.
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to transcript directory (e.g., '/var/www/html/stream/capture1/transcript')
    """
    return get_cold_storage_path(device_folder, 'transcript')


def get_segments_path(device_folder):
    """
    Get segments storage path (HOT or COLD depending on mode).
    
    - HOT: Live TS segments being recorded by FFmpeg
    - COLD: Final 10-min MP4 chunks in hour folders
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to segments directory:
        - RAM mode: '/var/www/html/stream/capture1/hot/segments'
        - SD mode: '/var/www/html/stream/capture1/segments'
    """
    return get_capture_storage_path(device_folder, 'segments')


def get_cold_segments_path(device_folder):
    """
    Get COLD segments storage path (ALWAYS COLD, never hot).
    
    Used for final 10-minute MP4 chunks that are archived by hot_cold_archiver.
    These chunks are always written to cold storage in hour folders.
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to cold segments directory (e.g., '/var/www/html/stream/capture1/segments')
    """
    return get_cold_storage_path(device_folder, 'segments')


def get_video_scratch_dir(device_folder):
    """
    Get a scratch directory for transient video-merge intermediates.

    ALWAYS lives on the COLD volume (same filesystem as the 10-minute COLD
    chunks), NEVER on /tmp or the HOT RAM disk.

    Why: report-video extraction for a long test merges hundreds of MB of
    intermediates and runs a two-pass `faststart` that needs a full second
    copy of the output. /tmp is a tiny LVM volume (~2.8 GB) and the HOT dir is
    a ~200 MB tmpfs — both overflow with "No space left on device" on long
    tests. The COLD volume (e.g. /data, ~900 GB) is the only place with room.

    Returns:
        Path to a (created) scratch directory, e.g.
        '/var/www/html/stream/capture4/tmp_video' (-> /data/stream/... on hosts
        where the stream root is the big NVMe volume).
    """
    scratch = os.path.join(get_device_base_path(device_folder), 'tmp_video')
    try:
        os.makedirs(scratch, exist_ok=True)
    except OSError as e:
        logger.warning(f"[{device_folder}] could not create video scratch dir {scratch}: {e}")
    return scratch


def get_captures_path(device_folder):
    """
    Get captures storage path (HOT or COLD depending on mode).
    
    - HOT: Live captures being generated by FFmpeg
    - COLD: Available for scripts/R2 upload
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to captures directory:
        - RAM mode: '/var/www/html/stream/capture1/hot/captures'
        - SD mode: '/var/www/html/stream/capture1/captures'
    """
    return get_capture_storage_path(device_folder, 'captures')


def get_thumbnails_path(device_folder):
    """
    Get thumbnails storage path (HOT or COLD depending on mode).
    
    - HOT: Live thumbnails being generated by FFmpeg for freeze detection
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to thumbnails directory:
        - RAM mode: '/var/www/html/stream/capture1/hot/thumbnails'
        - SD mode: '/var/www/html/stream/capture1/thumbnails'
    """
    return get_capture_storage_path(device_folder, 'thumbnails')


def get_thumbnail_path_from_capture(capture_path: str) -> str:
    """
    Get thumbnail path from capture image path.
    CENTRALIZED - Handles hot/cold storage automatically!
    
    Preserves storage location (hot→hot, cold→cold).
    
    Args:
        capture_path: Full path to capture image
        
    Returns:
        Full path to corresponding thumbnail
        
    Examples:
        >>> get_thumbnail_path_from_capture('/var/www/html/stream/capture4/hot/captures/capture_000001.jpg')
        '/var/www/html/stream/capture4/hot/thumbnails/capture_000001_thumbnail.jpg'
        
        >>> get_thumbnail_path_from_capture('/var/www/html/stream/capture4/captures/capture_000001.jpg')
        '/var/www/html/stream/capture4/thumbnails/capture_000001_thumbnail.jpg'
        
        >>> get_thumbnail_path_from_capture('/tmp/kpi_working/abc123/capture_000001.jpg')
        '/tmp/kpi_working/abc123/capture_000001_thumbnail.jpg'
    """
    # Get directory and filename
    capture_dir = os.path.dirname(capture_path)
    capture_filename = os.path.basename(capture_path)
    
    # Generate thumbnail filename (capture_X.jpg → capture_X_thumbnail.jpg)
    thumb_filename = capture_filename.replace('.jpg', '_thumbnail.jpg')
    
    # Check if capture is in a 'captures' directory
    dir_basename = os.path.basename(capture_dir)
    if dir_basename == 'captures':
        # Replace captures directory with thumbnails directory
        thumb_dir = os.path.join(os.path.dirname(capture_dir), 'thumbnails')
    else:
        # If not in captures directory (e.g., working directory), use same directory
        thumb_dir = capture_dir
    
    return os.path.join(thumb_dir, thumb_filename)


def get_metadata_path(device_folder):
    """
    Get metadata storage path (HOT or COLD depending on mode).
    
    - HOT: Live individual frame metadata JSONs
    - COLD: Final 10-min grouped metadata chunks in hour folders
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to metadata directory:
        - RAM mode: '/var/www/html/stream/capture1/hot/metadata'
        - SD mode: '/var/www/html/stream/capture1/metadata'
    """
    return get_capture_storage_path(device_folder, 'metadata')


def get_running_log_path(device_folder):
    """
    Get path to running script log file (ALWAYS HOT storage).
    
    This file is written by script executor during deployment execution
    and contains real-time progress updates (JSON format).
    The frontend polls this file to display script execution overlay.
    
    File is cleared at script start and overwritten during execution.
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Path to running.log file in hot storage
        (e.g., '/var/www/html/stream/capture1/hot/running.log')
        
    Note:
        This file is served through the backend host stream API (default port 6109):
        http://<host>:6109/host/stream/<device_folder>/hot/running.log
    """
    device_base = get_device_base_path(device_folder)
    return os.path.join(device_base, 'hot', 'running.log')


def get_transcript_chunk_path(device_folder, hour, chunk_index, language='original'):
    """
    Get path to specific transcript chunk JSON file.
    CENTRALIZED - Use this instead of building paths manually!
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        hour: Hour (0-23)
        chunk_index: Chunk index within hour (0-5 for 10-min chunks)
        language: Language code ('original', 'es', 'fr', etc.)
        
    Returns:
        Full path to transcript JSON file
        (e.g., '/var/www/html/stream/capture1/transcript/1/chunk_10min_0.json')
        (e.g., '/var/www/html/stream/capture1/transcript/1/chunk_10min_0_es.json')
    """
    transcript_base = get_transcript_path(device_folder)
    lang_suffix = '' if language == 'original' else f'_{language}'
    return os.path.join(transcript_base, str(hour), f'chunk_10min_{chunk_index}{lang_suffix}.json')


def get_audio_chunk_path(device_folder, hour, chunk_index, language='original'):
    """
    Get path to specific audio chunk MP3 file.
    CENTRALIZED - Use this instead of building paths manually!
    
    Args:
        device_folder: Device folder name (e.g., 'capture1')
        hour: Hour (0-23)
        chunk_index: Chunk index within hour (0-5 for 10-min chunks)
        language: Language code ('original' for source audio, 'es', 'fr' for dubbed)
        
    Returns:
        Full path to audio MP3 file
        (e.g., '/var/www/html/stream/capture1/audio/1/chunk_10min_0.mp3')
        (e.g., '/var/www/html/stream/capture1/audio/1/chunk_10min_0_es.mp3')
    """
    audio_base = get_cold_storage_path(device_folder, 'audio')
    lang_suffix = '' if language == 'original' else f'_{language}'
    return os.path.join(audio_base, str(hour), f'chunk_10min_{chunk_index}{lang_suffix}.mp3')


def get_capture_folder(capture_dir):
    """
    Extract capture folder name from path (handles both HOT and COLD storage)
    
    Examples:
        /var/www/html/stream/capture1/captures -> capture1
        /var/www/html/stream/capture1/hot/captures -> capture1
        /var/www/html/stream/capture4/hot/segments -> capture4
        /var/www/html/stream/capture4 -> capture4  (base path)
        /var/www/html/stream/capture4/captures/capture_000001.jpg -> capture4  (file path)
    """
    if not capture_dir:
        return None
    
    # Check if this is a hot storage path (cross-platform: handle both / and \)
    # Normalize to forward slashes for consistent matching
    normalized = capture_dir.replace('\\', '/')
    if '/hot/' in normalized:
        # Hot path: /var/www/html/stream/capture1/hot/captures
        # Split and get the part before /hot/
        parts = normalized.split('/')
        # Find the index of 'hot'
        try:
            hot_index = parts.index('hot')
            # Device folder is one level before 'hot'
            return parts[hot_index - 1]
        except (ValueError, IndexError):
            # Fallback to old logic if 'hot' not found
            return os.path.basename(os.path.dirname(capture_dir))
    else:
        # Check if this is a file path (has extension)
        basename = os.path.basename(capture_dir)
        if '.' in basename:
            # File path: /var/www/html/stream/capture4/captures/capture_000001.jpg
            # Need to go up to find capture folder
            parent_dir = os.path.dirname(capture_dir)  # /var/www/html/stream/capture4/captures
            parent_basename = os.path.basename(parent_dir)  # captures
            if parent_basename in ['captures', 'segments', 'thumbnails', 'metadata', 'audio', 'transcript']:
                # Go up one more level to get capture folder
                return os.path.basename(os.path.dirname(parent_dir))  # capture4
            else:
                # Might already be at capture folder level
                return parent_basename
        elif basename.startswith('capture') and not basename.endswith('s'):
            # Base path like /var/www/html/stream/capture4 -> capture4
            # (check not ending with 's' to avoid matching 'captures' folder)
            return basename
        else:
            # Subfolder path: /var/www/html/stream/capture1/captures -> capture1
            return os.path.basename(os.path.dirname(capture_dir))


def get_capture_number_from_segment(segment_number: int, fps: int, segment_duration: float = 1.0) -> int:
    """
    Calculate capture/image number from video segment number.

    frames_per_segment = fps * segment_duration (= run_ffmpeg's captures_per_segment).
    Pass the real segment_duration (e.g. 0.4 for v4l2) — defaulting to 1.0 silently
    desyncs the mapping on sub-second segments.

    Args:
        segment_number: Video segment number (e.g. 78741 from segment_000078741.ts)
        fps: Capture rate (5 for v4l2, etc.)
        segment_duration: HLS segment length in seconds (v4l2 0.4, x11grab 1.0)

    Examples:
        >>> get_capture_number_from_segment(78741, 5, 1.0)   # 5 frames/segment
        393705
        >>> get_capture_number_from_segment(100, 5, 0.4)     # 2 frames/segment
        200
    """
    frames_per_segment = max(1, round(fps * segment_duration))
    return segment_number * frames_per_segment


def get_segment_number_from_capture(frame_number: int, fps: int, segment_duration: float = 1.0) -> int:
    """
    Calculate video segment number from capture/frame number.
    (Inverse of get_capture_number_from_segment)
    
    Args:
        frame_number: Frame/capture number (e.g., 2497 from capture_000002497.jpg)
        fps: Frames per second / capture rate (e.g., 5 for v4l2, 2 for x11grab)
        
    Returns:
        Segment number that contains this frame
        
    Examples:
        >>> get_segment_number_from_capture(2497, 5)  # v4l2 device
        499  # segment_000000499.ts
        
        >>> get_segment_number_from_capture(1200, 2)  # x11grab device
        600  # segment_000000600.ts
        
    Note:
        frames_per_segment = fps * segment_duration (= run_ffmpeg captures_per_segment).
        Pass the real segment_duration — default 1.0 desyncs on sub-second segments.
        - fps=5, 1.0s: 5 frames/segment → frames 2495-2499 → segment 499
        - fps=5, 0.4s: 2 frames/segment → frames 200-201   → segment 100
    """
    frames_per_segment = max(1, round(fps * segment_duration))
    return frame_number // frames_per_segment


def get_device_fps(capture_folder: str) -> int:
    """
    Get FPS for a device based on its device model.
    
    Args:
        capture_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Capture FPS — 5 for both v4l2 and VNC (run_ffmpeg pins captures to fps=5 on
        both pipelines; see OPTIMIZATION.md §2c/§2f).

    Examples:
        >>> get_device_fps('capture1')  # HDMI device
        5
        >>> get_device_fps('capture3')  # VNC device
        5
    """
    # Captures are pinned to 5 fps on every standard pipeline (v4l2 and x11grab both
    # use [cap]fps=5). Kept as a function so callers stay decoupled from that constant.
    return 5


def get_device_segment_duration(capture_folder: str) -> float:
    """
    Get HLS segment duration for a device based on its device model.
    
    Args:
        capture_folder: Device folder name (e.g., 'capture1')
        
    Returns:
        Segment duration in seconds: 1.0 for HDMI devices, 4.0 for VNC devices
        
    Examples:
        >>> get_device_segment_duration('capture1')  # HDMI device
        1.0
        
        >>> get_device_segment_duration('capture3')  # VNC device  
        4.0
        
    Note:
        Segment duration is configurable per device (run_ffmpeg.sh hls_time), so the
        authoritative source is the live playlist's #EXTINF values — NOT the device
        model. We read those first; the device-model heuristic is only a last resort
        if the playlist can't be read.
    """
    # PRIMARY (config-aware): median #EXTINF from the device's live output.m3u8.
    try:
        m3u8_path = os.path.join(get_segments_path(capture_folder), 'output.m3u8')
        if os.path.exists(m3u8_path):
            durations = []
            with open(m3u8_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#EXTINF:'):
                        try:
                            durations.append(float(line.split(':', 1)[1].split(',')[0]))
                        except Exception:
                            continue
            if durations:
                recent = sorted(durations[-10:])
                mid = len(recent) // 2
                median = recent[mid] if len(recent) % 2 == 1 else (recent[mid - 1] + recent[mid]) / 2.0
                if median > 0:
                    return round(median, 3)
    except Exception as e:
        logger.warning(f"Could not read segment duration from m3u8 for {capture_folder}: {e}")

    # LAST RESORT: device-model heuristic (only if the playlist is unreadable).
    try:
        device_info = get_device_info_from_capture_folder(capture_folder)
        device_model = device_info.get('device_model', '').lower()
        if 'vnc' in device_model or 'x11grab' in device_model or 'host' in device_model:
            return 4.0
        else:
            return 1.0  # Default for hardware devices (HDMI, v4l2)
    except Exception as e:
        logger.warning(f"Could not determine segment duration for {capture_folder}: {e}, defaulting to 1.0s")
        return 1.0  # Safe default (most common)


def get_segment_path_from_frame(capture_folder: str, frame_filename: str) -> str:
    """
    Get the segment path for a given frame filename.
    HIGH-LEVEL UTILITY - Handles all the complexity internally!
    
    This function:
    1. Extracts frame number from filename
    2. Determines device FPS automatically (5 for HDMI, 2 for VNC)
    3. Calculates segment number (frame // fps)
    4. Finds segment file (.ts or .mp4)
    5. Returns full path to segment
    
    Args:
        capture_folder: Device folder name (e.g., 'capture1')
        frame_filename: Frame filename (e.g., 'capture_000002497.jpg')
        
    Returns:
        Full path to segment file, or None if not found
        
    Examples:
        >>> get_segment_path_from_frame('capture1', 'capture_000002497.jpg')
        '/var/www/html/stream/capture1/hot/segments/segment_000000499.ts'
        
        >>> get_segment_path_from_frame('capture3', 'capture_000001200.jpg')  # VNC device
        '/var/www/html/stream/capture3/segments/segment_000000600.ts'
        
    Note:
        - Automatically handles hot/cold storage
        - Automatically determines FPS based on device model
        - Tries both .ts and .mp4 extensions
    """
    try:
        # Extract frame number from filename
        frame_number = int(frame_filename.split('_')[1].split('.')[0])
        
        # Get device FPS + segment duration (automatic)
        device_fps = get_device_fps(capture_folder)
        segment_duration = get_device_segment_duration(capture_folder)

        # Calculate segment number (automatic, segment-duration aware)
        segment_number = get_segment_number_from_capture(frame_number, device_fps, segment_duration)
        
        # Get segments directory (automatic hot/cold detection)
        segments_dir = get_segments_path(capture_folder)
        
        if not os.path.exists(segments_dir):
            logger.warning(f"Segments directory not found: {segments_dir}")
            return None
        
        # Try both .ts and .mp4 extensions
        segment_name_ts = f"segment_{segment_number:09d}.ts"
        segment_name_mp4 = f"segment_{segment_number:09d}.mp4"
        
        segment_path_ts = os.path.join(segments_dir, segment_name_ts)
        segment_path_mp4 = os.path.join(segments_dir, segment_name_mp4)
        
        if os.path.exists(segment_path_ts):
            return segment_path_ts
        elif os.path.exists(segment_path_mp4):
            return segment_path_mp4
        else:
            logger.debug(f"Segment not found for frame {frame_number} (tried {segment_name_ts}, {segment_name_mp4})")
            return None
            
    except Exception as e:
        logger.warning(f"Failed to get segment path from frame {frame_filename}: {e}")
        return None


def calculate_chunk_location(timestamp):
    """
    Calculate hour and chunk_index from timestamp for 10-minute chunks.
    CENTRALIZED - Use this for both metadata and MP4 chunk placement!
    
    Args:
        timestamp: datetime object or ISO format string
        
    Returns:
        Tuple of (hour, chunk_index) where:
        - hour: 0-23 (hour of day)
        - chunk_index: 0-5 (which 10-minute window within the hour)
        
    Examples:
        >>> from datetime import datetime
        >>> calculate_chunk_location(datetime(2025, 10, 9, 15, 4))
        (15, 0)  # 15:00-15:10
        >>> calculate_chunk_location(datetime(2025, 10, 9, 15, 25))
        (15, 2)  # 15:20-15:30
    """
    from datetime import datetime
    
    # Handle string timestamps
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    
    hour = timestamp.hour
    chunk_index = timestamp.minute // 10  # 0-5 for 10-minute windows
    
    return hour, chunk_index


def copy_to_cold_storage(hot_or_cold_path):
    """
    Copy file from hot to cold storage if needed. If already in cold, return as-is.
    
    Args:
        hot_or_cold_path: File path (hot or cold storage)
        
    Returns:
        Cold storage path, or None if copy failed
    """
    import shutil
    
    from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path, is_hot_storage_path
    if not is_hot_storage_path(hot_or_cold_path):
        return hot_or_cold_path  # Already in cold
    
    cold_path = convert_hot_to_cold_path(hot_or_cold_path)
    os.makedirs(os.path.dirname(cold_path), exist_ok=True)
    
    if os.path.exists(hot_or_cold_path):
        shutil.copy2(hot_or_cold_path, cold_path)
        return cold_path
    
    return None


# =====================================================
# HYBRID VIDEO EXTRACTION (HOT + COLD)
# =====================================================

def _vlog(device_folder: str, msg: str, level: str = 'info'):
    """Emit a video-extraction diagnostic to BOTH the logger (journal) and stdout.

    Report-video extraction runs in the script process, whose execution.txt only captures
    print() — the module logger alone is invisible there. Dual output (low-frequency, once per
    test) makes "Hybrid video extraction failed" debuggable from the report logs: every decision
    and failure reason (HOT segment count, COLD chunk presence, ffmpeg stderr) is recorded.
    """
    line = f"📹 [VideoExtract:{device_folder}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    getattr(logger, level, logger.info)(line)


def _fmt_ts(ts: float) -> str:
    """Wall-clock HH:MM:SS for a unix timestamp (for VideoExtract diagnostics)."""
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime('%H:%M:%S')


def _probe_media_duration(path: str) -> Optional[float]:
    """Container duration in seconds via ffprobe, or None if unreadable."""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, timeout=15)
        if result.returncode == 0:
            return float(result.stdout.decode().strip())
    except Exception:
        pass
    return None


def _summarize_report_video(device_folder: str, path: str,
                            window_start_ts: float, window_end_ts: float,
                            gaps: Optional[list] = None):
    """Log the final video's real coverage: window start/end, media duration, missing footage.

    A report video that silently drops the middle of a test looks fine by filename and size;
    the only cheap generation-time signal is (wall window span) vs (actual media duration).
    Any shortfall beyond a few seconds of seam slop means footage is missing and is logged
    as a warning with the known gap ranges.
    """
    span = window_end_ts - window_start_ts
    media = _probe_media_duration(path)
    gap_notes = ', '.join(
        f"{_fmt_ts(a)}→{_fmt_ts(b)} ({b - a:.1f}s)" for a, b in (gaps or []) if b - a > 1.0
    )
    if media is None:
        _vlog(device_folder,
              f"FINAL VIDEO: window {_fmt_ts(window_start_ts)}→{_fmt_ts(window_end_ts)} ({span:.1f}s) | "
              f"media duration UNKNOWN (ffprobe failed on {path})", 'warning')
        return
    missing = span - media
    line = (f"FINAL VIDEO: window {_fmt_ts(window_start_ts)}→{_fmt_ts(window_end_ts)} ({span:.1f}s wall) | "
            f"media {media:.1f}s | missing {max(0.0, missing):.1f}s")
    if gap_notes:
        line += f" | known gaps: {gap_notes}"
    _vlog(device_folder, line, 'warning' if missing > 3.0 else 'info')


def extract_test_video_hybrid(
    device_folder: str,
    start_time,
    duration_seconds: int,
    output_path: str,
    lead_seconds: int = 15
) -> Optional[str]:
    """
    Extract test video using HYBRID approach (HOT + COLD).

    Strategy:
    1. Try HOT segments first (recent data, last ~90s)
    2. If not enough, backfill gap from COLD chunks
    3. Merge both pieces seamlessly

    This solves the problem where archiver has already moved old segments to COLD,
    leaving only recent segments in HOT storage.

    Args:
        device_folder: Device folder name (e.g., 'capture1', 'capture3')
        start_time: Test start time (datetime object)
        duration_seconds: Test duration in seconds
        output_path: Where to save final MP4
        lead_seconds: Seconds of footage to include BEFORE the test start. COLD
            10-min chunks are built by progressive `-c copy` appends, so seeking
            into them (`-ss OFFSET -c copy`) is only as accurate as their
            accumulated internal PTS — a few seconds of drift can clip the opening.
            A fixed lead-in guarantees the real start is well inside the COLD
            region rather than at its fragile leading edge. Extra footage at the
            head is acceptable (preferred over a clipped start); set 0 to disable.
            Default is 15s: enough to swallow the few-seconds PTS drift while
            keeping report videos small — a 60s lead was previously the dominant
            component of every short-test video's size in object storage.

    Returns:
        Path to created video file, or None if failed

    Example:
        >>> from datetime import datetime, timedelta
        >>> test_start = datetime.now() - timedelta(seconds=154)
        >>> video = extract_test_video_hybrid('capture3', test_start, 154, '/tmp/test.mp4')
        >>> # Creates video even if only 64s available in HOT (backfills 90s from COLD)
    """
    from datetime import timedelta
    import glob

    try:
        # Pull the window start back by the lead buffer; the end is the real test
        # end. All selection/extraction below works on this widened window.
        window_start = start_time - timedelta(seconds=max(0, lead_seconds))
        start_time = window_start
        end_time = window_start + timedelta(seconds=duration_seconds + max(0, lead_seconds))

        # All transient intermediates live on the COLD volume (same filesystem as
        # the COLD chunks), never /tmp or the HOT RAM disk — those are too small
        # for a long test's merge and overflow with "No space left on device".
        scratch_dir = get_video_scratch_dir(device_folder)
        
        # ============================================
        # STEP 1: Select HOT segments that fall INSIDE the test window
        # ============================================
        # The report video must represent the TEST window [start, end], not whatever
        # happened to be streaming when extraction ran (extraction fires after early
        # device release + final screenshot, so "the latest segments" are post-test
        # footage). We therefore select HOT segments by TIME, not by recency/count:
        # a segment's mtime ≈ the wall-clock instant ffmpeg finished writing it (≈ the
        # END of that ~segment_duration of footage). This also removes the old
        # count×median-EXTINF *estimate* of available HOT seconds, whose error let COLD
        # and HOT double-cover the seam and overshoot the requested duration.
        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()
        SEAM_MARGIN_S = 2.0  # a little slop at the edges is fine for a report video

        hot_segments_dir = get_segments_path(device_folder)  # REUSE: auto hot/cold detection
        all_hot = sorted(glob.glob(f"{hot_segments_dir}/segment_*.ts"))

        # Drop the newest segment: vpt-stream is actively writing it, so it may
        # be truncated/locked and break the concat merge. Losing ~1s of tail is
        # harmless for a report video.
        candidate_hot = all_hot[:-1] if len(all_hot) > 1 else all_hot

        segment_duration = get_device_segment_duration(device_folder)  # REUSE: 1s or 4s per segment

        # Keep segments whose footage overlaps [start, end]. Footage spans roughly
        # [mtime - segment_duration, mtime], so test against both edges (+ margin).
        window_hot = []
        for seg in candidate_hot:
            try:
                m = os.path.getmtime(seg)
            except OSError:
                continue
            if m >= start_ts - SEAM_MARGIN_S and (m - segment_duration) <= end_ts + SEAM_MARGIN_S:
                window_hot.append(seg)

        available_hot_seconds = round(len(window_hot) * segment_duration, 1)

        # The COLD/HOT seam is the footage-START of the OLDEST in-window HOT segment.
        # COLD must supply [window start → seam]; HOT supplies [seam → end]. No estimate.
        if window_hot:
            hot_oldest_mtime = min(os.path.getmtime(s) for s in window_hot)
            seam_ts = max(start_ts, hot_oldest_mtime - segment_duration)
        else:
            seam_ts = end_ts  # nothing usable in HOT → COLD must cover the whole window
        cold_gap_seconds = max(0.0, seam_ts - start_ts)

        _vlog(device_folder,
              f"need {duration_seconds}s | window {start_time:%H:%M:%S}→{end_time:%H:%M:%S} | "
              f"HOT dir={hot_segments_dir} exists={os.path.isdir(hot_segments_dir)} "
              f"segments={len(all_hot)} in-window={len(window_hot)} @ {segment_duration}s "
              f"→ HOT covers ~{available_hot_seconds}s, COLD must fill {cold_gap_seconds:.1f}s")

        if cold_gap_seconds <= 0.5:
            # ✅ Whole window is still in HOT - use only the in-window HOT segments
            if not window_hot:
                _vlog(device_folder, "FAILED: no in-window HOT segments and no COLD gap to fill", 'error')
                return None
            _vlog(device_folder, f"HOT-only path: merging {len(window_hot)} in-window segments")
            result = _merge_segments_to_mp4(window_hot, output_path, scratch_dir=scratch_dir)
            if not result:
                _vlog(device_folder, f"FAILED: HOT-only merge of {len(window_hot)} segments produced no output", 'error')
            else:
                _summarize_report_video(device_folder, result, start_ts, end_ts)
            return result

        # ============================================
        # STEP 2: Backfill the older part of the window from COLD ([start → seam])
        # ============================================
        _vlog(device_folder, f"backfilling {cold_gap_seconds:.1f}s from COLD [window start → seam]")

        cold_gap_file, cold_cov = _extract_from_cold_chunks(device_folder, start_time, cold_gap_seconds, scratch_dir=scratch_dir)

        if not cold_gap_file or not os.path.exists(cold_gap_file):
            if window_hot:
                _vlog(device_folder,
                      f"COLD backfill produced nothing → falling back to HOT-only ({available_hot_seconds}s); "
                      f"video will be SHORTER than the {duration_seconds}s test", 'warning')
                result = _merge_segments_to_mp4(window_hot, output_path, scratch_dir=scratch_dir)
                if not result:
                    _vlog(device_folder, "FAILED: HOT fallback merge produced no output", 'error')
                else:
                    _summarize_report_video(device_folder, result, start_ts, end_ts,
                                            gaps=[(start_ts, seam_ts)])
                return result
            _vlog(device_folder,
                  f"FAILED: nothing to build a video from — COLD backfill empty AND no in-window HOT segments "
                  f"(HOT dir '{hot_segments_dir}' has {len(all_hot)} segment_*.ts files). "
                  f"Likely the stream wasn't capturing for this device/window.", 'error')
            return None

        # Footage the COLD side could not supply (offsets shifted, archiver lag, missing
        # chunks) plus the COLD→HOT seam itself if COLD ends short of the oldest HOT segment.
        known_gaps = list(cold_cov.get('gaps') or [])
        cold_end_ts = cold_cov.get('end_ts') or seam_ts

        # Merge in-window HOT segments to MP4
        hot_tail_file = os.path.join(scratch_dir, f"hot_tail_{int(time.time())}.mp4")
        hot_tail_result = _merge_segments_to_mp4(window_hot, hot_tail_file, scratch_dir=scratch_dir) if window_hot else None

        if not hot_tail_result or not os.path.exists(hot_tail_result):
            _vlog(device_folder, f"no usable HOT tail ({len(window_hot)} segments) → using COLD gap only", 'warning')
            # shutil.move (not os.replace): cold_gap_file is on the COLD scratch volume and
            # output_path may be on a different filesystem, so rename() can raise OSError(EXDEV).
            import shutil
            shutil.move(cold_gap_file, output_path)
            # COLD's own gaps already cover [start → seam]; the unusable HOT part is extra.
            if end_ts - seam_ts > 1.0:
                known_gaps.append((seam_ts, end_ts))
            _summarize_report_video(device_folder, output_path, start_ts, end_ts, gaps=known_gaps)
            return output_path

        # ============================================
        # STEP 3: Concatenate COLD + HOT
        # ============================================
        if cold_end_ts < seam_ts - 2.0:
            # The concat will splice these directly together, so the viewer sees a
            # hidden time-jump here — call it out loudly at generation time. (The gap
            # itself is already in known_gaps via COLD's trailing-gap detection.)
            _vlog(device_folder,
                  f"SEAM GAP: COLD footage ends {_fmt_ts(cold_end_ts)} but HOT starts {_fmt_ts(seam_ts)} "
                  f"— {seam_ts - cold_end_ts:.1f}s of the test will be missing from the video", 'warning')
        _vlog(device_folder,
              f"merging COLD {_fmt_ts(cold_cov.get('start_ts') or start_ts)}→{_fmt_ts(cold_end_ts)} "
              f"+ HOT {_fmt_ts(seam_ts)}→{_fmt_ts(end_ts)} ({available_hot_seconds}s)")
        result = _concat_videos([cold_gap_file, hot_tail_file], output_path)
        if not result:
            _vlog(device_folder, "FAILED: final COLD+HOT concat produced no output", 'error')
        else:
            _summarize_report_video(device_folder, result, start_ts, end_ts, gaps=known_gaps)

        # Cleanup temp files
        try:
            if os.path.exists(cold_gap_file):
                os.remove(cold_gap_file)
            if os.path.exists(hot_tail_file):
                os.remove(hot_tail_file)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp files: {e}")

        return result

    except Exception as e:
        import traceback
        _vlog(device_folder, f"EXCEPTION during extraction: {e}\n{traceback.format_exc()}", 'error')
        return None


def _extract_from_cold_chunks(
    device_folder: str,
    start_time,
    duration_seconds: int,
    scratch_dir: Optional[str] = None
):
    """
    Extract [start_time, start_time + duration] from COLD 10-minute chunks.

    Chunk timelines are anchored on REAL data, not the nominal 10-min boundary.
    The archiver appends "the previous ~60s" once a minute into the chunk chosen
    by the CURRENT wall clock, so a chunk's first media second can be up to a
    minute BEFORE its nominal window start, and its last media second trails the
    wall clock by up to a minute. Assuming media t=0 == nominal boundary (the old
    code) shifted every extraction up to 60s early — a report video full of
    pre-test footage. Instead, each chunk's media↔wall mapping is derived from
    its tail: mtime is stamped when the last 1-min append lands, so media time t
    covers wall (mtime - media_duration + t).

    Returns:
        (path, coverage) where path is the extracted MP4 (or None) and coverage is
        {'start_ts', 'end_ts', 'gaps': [(gap_start_ts, gap_end_ts), ...]} describing
        the wall-clock range the footage ACTUALLY covers.
    """
    import subprocess
    from datetime import timedelta

    CHUNK_SECONDS = 10 * 60  # nominal wall-clock span of each COLD chunk

    if scratch_dir is None:
        scratch_dir = get_video_scratch_dir(device_folder)

    empty_coverage = {'start_ts': None, 'end_ts': None, 'gaps': []}

    try:
        cold_base = get_cold_segments_path(device_folder)
        wanted_start_ts = start_time.timestamp()
        wanted_end_ts = wanted_start_ts + float(duration_seconds)

        # Candidate chunks: every nominal 10-min window overlapping the wanted range,
        # plus one window on each side — real coverage leaks ~60s across nominal
        # boundaries (see docstring), so boundary footage may live in the neighbor.
        candidates = []
        seen = set()
        cand = start_time - timedelta(seconds=CHUNK_SECONDS)
        stop = start_time + timedelta(seconds=float(duration_seconds) + CHUNK_SECONDS)
        while cand <= stop:
            hour, chunk_index = calculate_chunk_location(cand)
            if (hour, chunk_index) not in seen:
                seen.add((hour, chunk_index))
                candidates.append((hour, chunk_index,
                                   os.path.join(cold_base, str(hour), f'chunk_10min_{chunk_index}.mp4')))
            cand += timedelta(seconds=CHUNK_SECONDS)

        pieces = []
        gaps = []  # (start_ts, end_ts) wall ranges with no footage
        covered_start_ts = None
        cursor_ts = wanted_start_ts
        piece_idx = 0

        for hour, chunk_index, chunk_path in candidates:
            if cursor_ts >= wanted_end_ts - 0.5:
                break
            if not os.path.exists(chunk_path):
                continue

            media_dur = _probe_media_duration(chunk_path)
            if not media_dur or media_dur <= 0:
                _vlog(device_folder, f"COLD chunk {hour}/{chunk_index}: unreadable duration, skipping", 'warning')
                continue

            chunk_end_ts = os.path.getmtime(chunk_path)   # wall time of last appended footage
            chunk_start_ts = chunk_end_ts - media_dur     # wall time of media t=0
            # Skip chunks whose real coverage misses the remaining wanted range —
            # including stale files (yesterday's slot in the 24h rolling buffer).
            if chunk_end_ts <= cursor_ts + 0.5 or chunk_start_ts >= wanted_end_ts - 0.5:
                continue

            take_start_ts = max(cursor_ts, chunk_start_ts)
            take_end_ts = min(wanted_end_ts, chunk_end_ts)
            take = take_end_ts - take_start_ts
            if take < 0.5:
                continue

            if take_start_ts > cursor_ts + 1.0:
                gaps.append((cursor_ts, take_start_ts))
                _vlog(device_folder,
                      f"COLD GAP: no footage {_fmt_ts(cursor_ts)}→{_fmt_ts(take_start_ts)} "
                      f"({take_start_ts - cursor_ts:.1f}s missing before chunk {hour}/{chunk_index})", 'warning')

            offset = take_start_ts - chunk_start_ts
            piece_path = os.path.join(scratch_dir, f"cold_gap_{device_folder}_{int(time.time()*1000)}_{piece_idx}.mp4")
            result = subprocess.run([
                'ffmpeg', '-ss', f'{offset:.3f}',
                '-i', chunk_path,
                '-t', f'{take:.3f}',
                '-c', 'copy',  # No re-encoding = instant
                # Zero-base this slice's timestamps so the later concat doesn't
                # inherit the chunk's mid-file PTS (~offset seconds in).
                '-avoid_negative_ts', 'make_zero',
                piece_path, '-y'
            ], capture_output=True, timeout=60)

            if result.returncode == 0 and os.path.exists(piece_path) and os.path.getsize(piece_path) > 0:
                # Verify what ffmpeg ACTUALLY produced — `-t` past EOF succeeds silently.
                actual = _probe_media_duration(piece_path) or 0.0
                short = take - actual
                _vlog(device_folder,
                      f"COLD chunk {hour}/{chunk_index}: media offset {offset:.1f}s "
                      f"= wall {_fmt_ts(take_start_ts)}→{_fmt_ts(take_start_ts + actual)} "
                      f"(actual {actual:.1f}s of {take:.1f}s requested"
                      + (f" — {short:.1f}s SHORT" if short > 2.0 else "") + ")",
                      'warning' if short > 2.0 else 'info')
                pieces.append(piece_path)
                if covered_start_ts is None:
                    covered_start_ts = take_start_ts
                # Advance by the REAL extracted footage; a following chunk that overlaps
                # the shortfall (coverage leaks across boundaries) will pick it up.
                cursor_ts = take_start_ts + max(actual, 0.0)
                piece_idx += 1
            else:
                _vlog(device_folder,
                      f"COLD extract failed (rc={result.returncode}) for {chunk_path} @offset {offset:.1f}s: "
                      f"{result.stderr.decode(errors='replace')[-300:]}", 'error')
                gaps.append((take_start_ts, take_end_ts))
                cursor_ts = take_end_ts

        if not pieces:
            _vlog(device_folder,
                  f"COLD backfill empty: no chunks covered window {start_time:%H:%M:%S} +{duration_seconds}s "
                  f"under {cold_base} (chunks not archived yet, or device has no COLD history)", 'error')
            return None, empty_coverage

        if cursor_ts < wanted_end_ts - 1.0:
            gaps.append((cursor_ts, wanted_end_ts))
            _vlog(device_folder,
                  f"COLD coverage ends {wanted_end_ts - cursor_ts:.1f}s early "
                  f"({_fmt_ts(cursor_ts)} vs wanted {_fmt_ts(wanted_end_ts)}) — "
                  f"archiver hasn't appended that footage yet", 'warning')

        coverage = {'start_ts': covered_start_ts, 'end_ts': cursor_ts, 'gaps': gaps}

        if len(pieces) == 1:
            return pieces[0], coverage

        # Concatenate the per-chunk pieces into one gap file.
        merged_path = os.path.join(scratch_dir, f"cold_gap_{device_folder}_{int(time.time()*1000)}_merged.mp4")
        merged = _concat_videos(pieces, merged_path)
        for p in pieces:
            try:
                os.remove(p)
            except OSError:
                pass
        return (merged if merged and os.path.exists(merged) else None), coverage

    except Exception as e:
        logger.error(f"[{device_folder}] COLD chunk extraction failed: {e}")
        return None, empty_coverage


def _merge_segments_to_mp4(segment_files: list, output_path: str, scratch_dir: Optional[str] = None) -> Optional[str]:
    """
    Merge TS segments to MP4 using FFmpeg concat demuxer.

    Args:
        segment_files: List of .ts segment file paths
        output_path: Output MP4 path
        scratch_dir: Directory for the private staging snapshot. Defaults to the
            system temp dir, but for long videos the caller passes a COLD-volume
            scratch dir so the snapshot of (potentially hundreds of) segments does
            not overflow the tiny /tmp LVM volume.

    Returns:
        Output path if successful, None otherwise
    """
    import subprocess
    import shutil
    import tempfile

    if not segment_files:
        return None

    staging_dir = None
    try:
        # Snapshot segments into a private temp dir before merging. The HOT
        # segment directory is a live RAM disk: vpt-stream appends to the newest
        # segment and vpt-archiver deletes the oldest ones every ~15s, so a
        # segment listed by glob() can vanish before ffmpeg opens it ("Impossible
        # to open segment_*.ts" → merge fails). Copying first makes the merge
        # immune to concurrent rotation; segments that disappear mid-snapshot are
        # simply skipped.
        if scratch_dir:
            os.makedirs(scratch_dir, exist_ok=True)
        staging_dir = tempfile.mkdtemp(prefix='vpt_merge_', dir=scratch_dir)
        staged_files = []
        for seg in segment_files:
            try:
                dst = os.path.join(staging_dir, os.path.basename(seg))
                shutil.copy2(seg, dst)
                staged_files.append(dst)
            except (FileNotFoundError, OSError):
                # Segment was rotated out by the archiver mid-snapshot — skip it.
                continue

        if not staged_files:
            _vlog('', f"segment merge failed: all {len(segment_files)} segments rotated out before snapshot could copy them", 'error')
            return None

        # Create concat file list (referencing the staged copies)
        concat_file = os.path.join(staging_dir, 'concat.txt')
        with open(concat_file, 'w') as f:
            for seg in staged_files:
                f.write(f"file '{seg}'\n")

        # Merge using concat demuxer (fast, no re-encoding)
        result = subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',  # No re-encoding
            output_path, '-y'
        ], capture_output=True, timeout=60)

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        else:
            _vlog('', f"ffmpeg segment merge failed (rc={result.returncode}, {len(staged_files)} segments): "
                      f"{result.stderr.decode(errors='replace')[-300:]}", 'error')
            return None

    except Exception as e:
        _vlog('', f"segment merge exception: {e}", 'error')
        return None
    finally:
        # Always clean up the staging snapshot
        if staging_dir and os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)


def _concat_videos(video_files: list, output_path: str) -> Optional[str]:
    """
    Concatenate MP4 pieces into one MP4 via MPEG-TS intermediates.

    The pieces come from different muxers — COLD chunk slices at the MP4 track
    timescale, HOT tails remuxed from 90kHz MPEG-TS segments — and feeding them
    straight to the concat demuxer (with or without +genpts) mis-scales the later
    input's timestamps by the timescale ratio: a ~101s video reports ~888s and the
    player timeline/seek bar is garbage. Remuxing each piece to MPEG-TS first
    forces a uniform 90kHz timebase and strips MP4 edit lists, so the final
    concat+remux is duration-accurate.

    Args:
        video_files: List of MP4 file paths (concatenated in order)
        output_path: Output MP4 path

    Returns:
        Output path if successful, None otherwise
    """
    import subprocess

    if not video_files:
        return None

    temp_files = []
    try:
        # Intermediates live next to the output (COLD volume — big enough).
        base_dir = os.path.dirname(output_path) or '.'
        tag = int(time.time() * 1000)

        ts_pieces = []
        for i, vf in enumerate(video_files):
            ts_path = os.path.join(base_dir, f".concat_{tag}_{i}.ts")
            result = subprocess.run([
                'ffmpeg', '-y', '-v', 'error', '-i', vf,
                '-c', 'copy', '-bsf:v', 'h264_mp4toannexb', '-f', 'mpegts', ts_path
            ], capture_output=True, timeout=120)
            if result.returncode != 0 or not os.path.exists(ts_path) or os.path.getsize(ts_path) == 0:
                _vlog('', f"concat: TS remux failed for {vf}: "
                          f"{result.stderr.decode(errors='replace')[-300:]}", 'error')
                return None
            temp_files.append(ts_path)
            ts_pieces.append(ts_path)

        concat_list = os.path.join(base_dir, f".concat_{tag}.txt")
        with open(concat_list, 'w') as f:
            for ts_path in ts_pieces:
                f.write(f"file '{ts_path}'\n")
        temp_files.append(concat_list)

        temp_output = output_path + '.tmp'
        # aac_adtstoasc: AAC comes out of MPEG-TS as ADTS, which the mp4 muxer
        # rejects on host ffmpeg builds that don't auto-insert the filter.
        result = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-c', 'copy', '-bsf:a', 'aac_adtstoasc', '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero', '-f', 'mp4', temp_output
        ], capture_output=True, timeout=300)
        if result.returncode != 0 or not os.path.exists(temp_output):
            _vlog('', f"concat: final merge failed ({len(video_files)} files): "
                      f"{result.stderr.decode(errors='replace')[-300:]}", 'error')
            temp_files.append(temp_output)
            return None

        os.replace(temp_output, output_path)
        return output_path

    except Exception as e:
        _vlog('', f"video concatenation exception ({len(video_files)} files): {e}", 'error')
        return None
    finally:
        for p in temp_files:
            try:
                os.remove(p)
            except OSError:
                pass
