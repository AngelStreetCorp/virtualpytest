#!/usr/bin/env python3
"""
Frame detector - analyzes frames for issues with rich metadata
Returns same format as original analyze_audio_video.py

NOTE: Subtitle OCR is handled by subtitle_monitor.py (separate process)
      This detector focuses on: blackscreen, freeze, macroblocks, zap, audio

CONFIGURATION:
- ENABLE_MACROBLOCKS: Set to False by default (reduces CPU load by ~30%)
  Change to True in detector.py to enable macroblocks detection
  
ADAPTIVE LOAD MANAGEMENT:
- When queue backlog > 50 frames (system overloaded):
  * Freeze detection: Runs every N frames (default: 5 frames = 1 second), returns cached result otherwise
  * Blackscreen detection: Runs every N frames (default: 5 frames = 1 second), returns cached result otherwise  
  * Macroblocks: Skipped entirely (even if ENABLE_MACROBLOCKS=True)
  * Reduces CPU load by ~80% during overload while still detecting incidents
  * All detections resume normal frequency when queue drops below threshold

ZAP STATE OPTIMIZATION:
- Tracks when device is zapping (blackscreen + banner detected)
- Skips expensive operations during zap
- Marks start/end frames in JSON for zap_executor
- Saves ~95% CPU during zap sequence (2ms vs ~40ms per frame)

FREEZE DETECTION OPTIMIZATION:
- In-memory thumbnail cache: Avoids disk I/O for previous frames
- Keeps last 3 frames in RAM per device (~500KB total)
- Reduces freeze detection time by 50-60% (15ms → 6ms)

BLACKSCREEN DETECTION OPTIMIZATION:
- Optimized sampling: Every 4th pixel (6.25%) instead of every 3rd (11%)
- Reduces blackscreen detection time by 33% (5ms → 3ms)
- No impact on accuracy (blackscreen detection is very tolerant)
"""
import os
import sys
import subprocess
import time
import logging
import cv2
import numpy as np
import json
from datetime import datetime
from contextlib import contextmanager
from collections import deque

# === CONFIGURATION ===
# OCR is handled by subtitle_monitor.py - removed from detector.py

# Macroblocks detection (expensive, disabled by default to reduce CPU load)
ENABLE_MACROBLOCKS = False  # Set to True to enable macroblocks detection

# Adaptive detection frequency when system is overloaded (queue > 30)
OVERLOAD_DETECTION_INTERVAL = 10  # Run expensive detections every N frames (2 seconds at 5fps) - OPTIMIZATION: Reduced from 5

# Freeze detection threshold (percentage of pixels that must differ)
FREEZE_THRESHOLD = 0.8  # 0.8% pixel difference = frozen - OPTIMIZATION: Increased from 2.0 to reduce false positives

from shared.src.lib.utils.storage_path_utils import (
    is_ram_mode,
    get_segments_path,
    get_capture_folder
)

logger = logging.getLogger('capture_monitor')

# Performance profiling
@contextmanager
def measure_time(task_name):
    """Context manager to measure execution time of a task"""
    start = time.perf_counter()
    yield
    elapsed = (time.perf_counter() - start) * 1000  # Convert to milliseconds
    return elapsed
from shared.src.lib.utils.image_utils import (
    load_and_downscale_image,
    analyze_blackscreen,
    analyze_freeze,
    analyze_macroblocks
)

def _motion_shape(diff, motion_thr=12, cell_thr=0.04, grid=4):
    """Coarse SPATIAL classification of a frame-to-frame diff — the same motion signal freeze
    detection already produces. Distinguishes full-frame motion (live TV) from a horizontal band
    (carousel) or a compact box (picture-in-picture), so the monitor can tell "live motion" apart
    from a moving UI. Pre-localize (raw shape only); capture_monitor fuses this with the localize
    result + hysteresis to emit the final motion state. ~sub-ms on a 320x180 thumbnail.

    Returns {kind, pct, cells, rows, cols}:
      static : almost no change (freeze / still UI)
      full   : motion distributed across the frame  -> live candidate
      band   : wide + short horizontal strip        -> carousel candidate
      box    : compact localized region             -> picture-in-picture candidate
      minor  : some motion, no clear shape
    """
    h, w = diff.shape[:2]
    m = diff > motion_thr
    pct = round(float(m.mean()) * 100.0, 1)
    ys = np.linspace(0, h, grid + 1).astype(int)
    xs = np.linspace(0, w, grid + 1).astype(int)
    cell = np.zeros((grid, grid), dtype=bool)
    for r in range(grid):
        for c in range(grid):
            sub = m[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            if sub.size and sub.mean() > cell_thr:
                cell[r, c] = True
    cells = int(cell.sum())
    rows = int(cell.any(axis=1).sum())
    cols = int(cell.any(axis=0).sum())
    if pct < 1.0:
        kind = 'static'
    elif cells >= (grid * grid) // 2 and rows >= 3 and cols >= 3:
        kind = 'full'
    elif rows <= 2 and cols >= 3:
        kind = 'band'
    elif rows <= 2 and cols <= 2 and cells == rows * cols and cells <= 3:
        kind = 'box'                         # one SOLID compact block (not scattered spots)
    else:
        kind = 'minor'
    return {'kind': kind, 'pct': pct, 'cells': cells, 'rows': rows, 'cols': cols}


def detect_freeze_pixel_diff(current_img, thumbnails_dir, filename, fps=5, queue_size=0, freeze_duration_ms=0):
    """
    Freeze detection using pixel difference - OPTIMIZED with in-memory cache
    
    Compares current thumbnail with previous 3 thumbnails using cv2.absdiff.
    Uses in-memory cache to avoid disk I/O on thumbnail loading (5-10ms savings).
    
    ADAPTIVE SAMPLING WHEN OVERLOADED:
    - When queue_size > 30, only run freeze detection every N frames (default: every 10th frame = 2 seconds)
    - Reduces CPU load during backlog while still detecting freezes
    - Other frames return last known state (cached result)
    
    LONG FREEZE OPTIMIZATION:
    - When freeze has been ongoing for >30s, only check every 30s (150 frames at 5fps)
    - Long freezes are confirmed incidents, no need to check frequently
    - Saves significant CPU during long freeze incidents
    
    Args:
        current_img: Current thumbnail (grayscale numpy array, 320x180)
        thumbnails_dir: Directory containing thumbnails
        filename: Current frame filename (e.g., capture_000001.jpg)
        fps: Frames per second
        queue_size: Current processing queue size (adaptive sampling if > 30)
        freeze_duration_ms: Duration of ongoing freeze in milliseconds (0 if no freeze)
        
    Returns:
        (frozen: bool, details: dict)
    """
    global _freeze_thumbnail_cache, _freeze_result_cache
    
    try:
        # Extract frame number
        frame_number = int(filename.split('_')[1].split('.')[0])
    except:
        return False, {}
    
    # Get device key for cache
    device_key = os.path.dirname(thumbnails_dir)
    
    # LONG FREEZE OPTIMIZATION: If freeze ongoing for >30s, only check every 30s (150 frames at 5fps)
    if freeze_duration_ms > 30000:
        LONG_FREEZE_INTERVAL = 150  # 30 seconds at 5fps
        if frame_number % LONG_FREEZE_INTERVAL != 0:
            # Return cached result - no need to check frequently for long freezes
            if device_key in _freeze_result_cache:
                cached = _freeze_result_cache[device_key]
                return cached['frozen'], {
                    **cached['details'],
                    'skipped_reason': 'long_freeze_optimization',
                    'freeze_duration_ms': freeze_duration_ms,
                    'last_detection_frame': cached.get('frame_number', 0)
                }
            else:
                # No cache - assume still frozen
                return True, {
                    'skipped_reason': 'long_freeze_no_cache',
                    'freeze_duration_ms': freeze_duration_ms
                }
    
    # ADAPTIVE: When overloaded, only detect every N frames (2 seconds) - OPTIMIZATION: Lowered threshold from 50 to 30
    if queue_size > 30:
        # Check if this frame should run detection
        if frame_number % OVERLOAD_DETECTION_INTERVAL != 0:
            # Return cached result from previous detection
            if device_key in _freeze_result_cache:
                cached = _freeze_result_cache[device_key]
                return cached['frozen'], {
                    **cached['details'],
                    'skipped_reason': 'adaptive_sampling',
                    'queue_size': queue_size,
                    'last_detection_frame': cached.get('frame_number', 0)
                }
            else:
                # No cache yet - return not frozen
                return False, {
                    'skipped_reason': 'adaptive_sampling_no_cache',
                    'queue_size': queue_size
                }
    
    # Initialize cache for this device if needed
    if device_key not in _freeze_thumbnail_cache:
        _freeze_thumbnail_cache[device_key] = deque(maxlen=FREEZE_THUMBNAIL_CACHE_MAXLEN)
    
    cache = _freeze_thumbnail_cache[device_key]
    
    # Need at least 2 previous frames for comparison
    if frame_number < 2:
        # Add current frame to cache and return
        cache.append((frame_number, current_img.copy()))
        return False, {}
    
    # Compare with cached thumbnails (last 3 frames)
    pixel_diffs = []
    frames_compared = []
    cache_hits = 0
    disk_loads = 0
    motion_info = None   # spatial motion shape from the closest-prev diff (live / carousel / pip)
    
    # Check last 3 frames in reverse order (N-1, N-2, N-3)
    for i in range(1, 4):
        prev_frame_num = frame_number - i
        if prev_frame_num < 0:
            break
        
        # Try to find in cache first
        prev_img = None
        for cached_num, cached_img in reversed(cache):
            if cached_num == prev_frame_num:
                prev_img = cached_img
                cache_hits += 1
                break
        
        # If not in cache, load from disk (fallback)
        if prev_img is None:
            frame_prefix = filename.rsplit('_', 1)[0]
            frame_digits = len(filename.split('_')[1].split('.')[0])
            prev_filename = f"{frame_prefix}_{str(prev_frame_num).zfill(frame_digits)}_thumbnail.jpg"
            prev_path = os.path.join(thumbnails_dir, prev_filename)
            
            if os.path.exists(prev_path):
                prev_img = cv2.imread(prev_path, cv2.IMREAD_GRAYSCALE)
                disk_loads += 1
                
                # Add to cache for future use
                if prev_img is not None:
                    cache.append((prev_frame_num, prev_img.copy()))
        
        if prev_img is None:
            continue
        
        # Validate size match
        if prev_img.shape != current_img.shape:
            continue
        
        # Compute absolute pixel difference
        diff = cv2.absdiff(current_img, prev_img)

        # Motion shape from the closest available prev frame (computed once, reuses this diff)
        if motion_info is None:
            motion_info = _motion_shape(diff)

        # Count pixels with difference > 10 (threshold for "different")
        different_pixels = np.sum(diff > 10)
        total_pixels = diff.size
        
        # Convert to percentage difference
        diff_percentage = (different_pixels / total_pixels) * 100
        
        pixel_diffs.append(diff_percentage)
        frames_compared.append(f"frame_{prev_frame_num}")
        
        # EARLY EXIT: If difference > 5%, NOT frozen - stop checking more frames
        if diff_percentage > 5.0:
            break
    
    # Add current frame to cache (deque maxlen evicts the oldest)
    cache.append((frame_number, current_img.copy()))
    
    # Frozen if ALL checked frames have < threshold difference (VERY STRICT)
    frozen = len(pixel_diffs) >= 2 and all(diff < FREEZE_THRESHOLD for diff in pixel_diffs)
    
    details = {
        'frame_differences': [round(d, 2) for d in pixel_diffs],
        'frames_compared': frames_compared,
        'frames_found': len(frames_compared),
        'frames_needed': 2,
        'detection_method': 'pixel_diff_cached',
        'threshold': FREEZE_THRESHOLD,
        'cache_hits': cache_hits,
        'disk_loads': disk_loads,
        'motion': motion_info,   # {kind, pct, cells, rows, cols} or None
    }
    
    # Cache result for adaptive sampling (when overloaded)
    _freeze_result_cache[device_key] = {
        'frozen': frozen,
        'details': details,
        'frame_number': frame_number
    }
    
    return frozen, details

# Performance: Cache for optimization

# Zap state tracking for CPU optimization
_zap_state_cache = {}  # In-memory cache for fast access

# Freeze detection optimization - cache thumbnails in memory.
#
# Bounded at the structure, not by the callers. Two bugs used to let this grow
# without limit (BUG-0095): the disk-fallback branch appended without a matching
# pop, and the hourly cleanup was called with a key that never matched, so it
# freed nothing while logging success. 4.84 GB on vpt-pi1 over seven days.
# A deque with maxlen cannot grow whatever the call sites do.
#
# 8 = the 3 previous frames the comparison needs, the current one, and headroom
# so a burst of disk-fallback inserts cannot evict a frame we are about to read.
FREEZE_THUMBNAIL_CACHE_MAXLEN = 8
_freeze_thumbnail_cache = {}  # {device_dir: deque[(frame_number, thumbnail_img)], maxlen bounded}

# Freeze result cache for adaptive sampling (when overloaded)
_freeze_result_cache = {}  # {device_dir: {'frozen': bool, 'details': dict, 'frame_number': int}}

# Blackscreen result cache for adaptive sampling (when overloaded)
_blackscreen_result_cache = {}  # {device_dir: {'blackscreen': bool, 'percentage': float, 'frame_number': int}}

# Cache cleanup tracking
_cache_last_cleanup = {}  # {device_dir: timestamp}
CACHE_CLEANUP_INTERVAL = 3600  # Clean cache every hour (1 hour = 3600 seconds)

def cleanup_old_caches(device_key):
    """
    Periodic cache cleanup to prevent memory leaks.
    Called every hour per device to clear stale cache entries.
    """
    global _freeze_thumbnail_cache, _freeze_result_cache, _blackscreen_result_cache, _cache_last_cleanup
    
    current_time = time.time()
    last_cleanup = _cache_last_cleanup.get(device_key, 0)
    
    # Only cleanup if it's been more than CACHE_CLEANUP_INTERVAL seconds
    if current_time - last_cleanup < CACHE_CLEANUP_INTERVAL:
        return
    
    # Clear freeze thumbnail cache for this device
    if device_key in _freeze_thumbnail_cache:
        old_size = len(_freeze_thumbnail_cache[device_key])
        # clear(), not a new list: reassigning would drop the maxlen bound
        _freeze_thumbnail_cache[device_key].clear()
        logger.debug(f"[{device_key}] Cache cleanup: Freed {old_size} freeze thumbnails")
    
    # Clear freeze result cache
    if device_key in _freeze_result_cache:
        del _freeze_result_cache[device_key]
    
    # Clear blackscreen result cache
    if device_key in _blackscreen_result_cache:
        del _blackscreen_result_cache[device_key]
    
    # Update last cleanup time
    _cache_last_cleanup[device_key] = current_time
    logger.info(f"[{device_key}] Memory cache cleanup completed (next cleanup in {CACHE_CLEANUP_INTERVAL/3600:.1f}h)")

def get_zap_state_file(capture_dir):
    """Get path to zap state file for device"""
    return os.path.join(capture_dir, '.zap_state.json')


def load_zap_state(capture_dir):
    """Load zap state from file or cache"""
    global _zap_state_cache
    
    # Check in-memory cache first
    if capture_dir in _zap_state_cache:
        return _zap_state_cache[capture_dir]
    
    # Try to load from file
    state_file = get_zap_state_file(capture_dir)
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
                _zap_state_cache[capture_dir] = state
                return state
        except:
            pass
    
    return None

def save_zap_state(capture_dir, state):
    """Save zap state to file and cache"""
    global _zap_state_cache
    
    _zap_state_cache[capture_dir] = state
    
    # Persist to file
    state_file = get_zap_state_file(capture_dir)
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        logger.warning(f"Failed to save zap state: {e}")

def clear_zap_state(capture_dir):
    """Clear zap state (zap sequence ended)"""
    global _zap_state_cache
    
    # Remove from cache
    if capture_dir in _zap_state_cache:
        del _zap_state_cache[capture_dir]
    
    # Remove file
    state_file = get_zap_state_file(capture_dir)
    if os.path.exists(state_file):
        try:
            os.remove(state_file)
        except Exception as e:
            logger.warning(f"Failed to remove zap state file: {e}")


def quick_blackscreen_check(img, threshold=10):
    """Fast blackscreen check for zap monitoring (no edge detection needed) - OPTIMIZED"""
    img_height, img_width = img.shape
    header_y = int(img_height * 0.05)
    split_y = int(img_height * 0.7)
    
    top_region = img[header_y:split_y, :]
    # Optimized sampling: every 4th pixel (6.25% sample) instead of every 3rd (11%)
    sample = top_region[::4, ::4]
    sample_dark = np.sum(sample <= threshold)
    sample_total = sample.shape[0] * sample.shape[1]
    dark_percentage = (sample_dark / sample_total) * 100
    
    # ✅ THRESHOLD: Raised from 85% to 95% (matches main blackscreen detection)
    return bool(dark_percentage > 95), dark_percentage

# analyze_subtitles() removed - now handled by subtitle_monitor.py

def detect_issues(image_path, fps=5, queue_size=0, DEBUG=0, skip_freeze=False, skip_blackscreen=False, skip_macroblocks=False, freeze_duration_ms=0):
    """
    Main detection function - OPTIMIZED WORKFLOW with zap state tracking
    
    Workflow:
    1. Check if device is zapping (state file)
       - IF zapping → FAST PATH (just monitor blackscreen)
       - IF NOT zapping → FULL PATH (all detections)
    2. Load image
    3. Edge detection (CORE - reused)
    4. Blackscreen + Zap detection (fast sampling)
    5. Freeze detection
    6. Macroblocks (skip if freeze or blackscreen)
    7. Audio analysis (cached every 5 seconds)
    
    ZAP STATE OPTIMIZATION:
    - When zap detected: Save state, mark start frame
    - During zap: Skip expensive ops (~2ms vs full detection)
    - When blackscreen ends: Mark end frame, clear state
    
    INCIDENT PRIORITY OPTIMIZATION:
    - skip_freeze: Skip freeze detection (when blackscreen is ongoing)
    - skip_blackscreen: Skip blackscreen detection (when freeze is ongoing)
    - skip_macroblocks: Skip macroblocks detection (when blackscreen/freeze is ongoing)
    - Saves CPU by only checking the ONGOING incident type
    
    NOTE: Subtitle OCR is handled by subtitle_monitor.py (separate process)
    
    Args:
        image_path: Path to capture image
        fps: Frames per second (5 for v4l2, 2 for x11grab/VNC) - used for freeze detection
        queue_size: Current queue backlog
        debug: Enable debug output (unused, kept for compatibility)
        skip_freeze: Skip freeze detection (incident priority optimization)
        skip_blackscreen: Skip blackscreen detection (incident priority optimization)
        skip_macroblocks: Skip macroblocks detection (incident priority optimization)
    """
    # Performance timing storage
    timings = {}
    total_start = time.perf_counter()
    
    capture_dir = os.path.dirname(os.path.dirname(image_path))  # Go up from /captures/
    filename = os.path.basename(image_path)
    
    # Extract frame number for sampling
    try:
        frame_number = int(filename.split('_')[1].split('.')[0])
    except:
        frame_number = 0
    
    # === CHECK: Is device currently zapping? ===
    zap_state = load_zap_state(capture_dir)
    
    if zap_state and zap_state.get('zapping'):
        # FAST PATH: Device is zapping - optimize!
        start = time.perf_counter()
        try:
            import cv2
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise Exception("Failed to load image")
            timings['image_load'] = (time.perf_counter() - start) * 1000
            
            # Quick blackscreen check (no edge detection needed)
            start = time.perf_counter()
            blackscreen, dark_percentage = quick_blackscreen_check(img)
            timings['blackscreen'] = (time.perf_counter() - start) * 1000
            
            if not blackscreen:
                # ZAP SEQUENCE ENDED!
                timestamp = datetime.fromtimestamp(os.path.getmtime(image_path)).isoformat()
                start_timestamp = datetime.fromisoformat(zap_state['start_timestamp'])
                end_timestamp = datetime.fromisoformat(timestamp)
                duration = (end_timestamp - start_timestamp).total_seconds()
                
                # Calculate next frame filename for banner detection
                next_frame_number = frame_number + 1
                # Preserve original filename format (e.g., capture_000001.jpg)
                frame_prefix = filename.rsplit('_', 1)[0]  # "capture"
                frame_digits = len(filename.split('_')[1].split('.')[0])  # Number of digits
                next_frame = f"{frame_prefix}_{str(next_frame_number).zfill(frame_digits)}.jpg"
                
                clear_zap_state(capture_dir)
                
                timings['total'] = (time.perf_counter() - total_start) * 1000
                
                return {
                    'timestamp': timestamp,
                    'filename': filename,
                    'blackscreen': False,
                    'blackscreen_percentage': round(dark_percentage, 1),
                    'blackscreen_threshold': 10,
                    'blackscreen_region': '5-70%',
                    'zap': False,
                    'has_bottom_content': False,
                    'bottom_edge_density': 0.0,
                    'zap_sequence_end': True,
                    'zap_sequence_info': {
                        'start_frame': zap_state['start_frame'],
                        'end_frame': filename,
                        'next_frame': next_frame,
                        'duration_seconds': round(duration, 3),
                        'start_timestamp': zap_state['start_timestamp'],
                        'end_timestamp': timestamp,
                        'frames_in_sequence': frame_number - zap_state['start_frame_number'] + 1
                    },
                    'freeze': False,
                    'freeze_comparisons': [],
                    'last_3_filenames': [],
                    'last_3_thumbnails': [],
                    'macroblocks': False,
                    'quality_score': 0.0,
                    'performance_ms': {k: round(v, 2) for k, v in timings.items()}
                }
            else:
                # ZAP CONTINUES - return minimal result
                timings['total'] = (time.perf_counter() - total_start) * 1000
                
                return {
                    'timestamp': datetime.fromtimestamp(os.path.getmtime(image_path)).isoformat(),
                    'filename': filename,
                    'blackscreen': True,
                    'blackscreen_percentage': round(dark_percentage, 1),
                    'blackscreen_threshold': 10,
                    'blackscreen_region': '5-70%',
                    'zap': True,
                    'zap_in_progress': True,
                    'has_bottom_content': True,
                    'bottom_edge_density': 0.0,
                    'freeze': False,
                    'freeze_comparisons': [],
                    'last_3_filenames': [],
                    'last_3_thumbnails': [],
                    'macroblocks': False,
                    'quality_score': 0.0,
                    'performance_ms': {k: round(v, 2) for k, v in timings.items()}
                }
        except Exception as e:
            # Error during fast path - clear state and fall through to full detection
            clear_zap_state(capture_dir)
            logger.warning(f"Zap fast path error: {e}, falling back to full detection")
    
    # === FULL PATH: Normal detection (not zapping) ===
    
    # Get thumbnails directory (handles both RAM and SD modes)
    try:
        from shared.src.lib.utils.build_url_utils import get_device_local_thumbnails_path
        thumbnails_dir = get_device_local_thumbnails_path(image_path)
    except:
        # Fallback to manual path construction
        captures_dir = os.path.dirname(image_path)
        capture_parent = os.path.dirname(captures_dir)
        thumbnails_dir = os.path.join(capture_parent, 'thumbnails')

    # Periodic cache cleanup (every hour per device). This MUST use the same key
    # the caches are stored under — os.path.dirname(thumbnails_dir), e.g.
    # /var/www/html/stream/capture1/hot — not capture_dir. It used to be called
    # with capture_dir, which never matched, so it freed nothing while logging
    # "Memory cache cleanup completed" (BUG-0095). Hence it sits here, after
    # thumbnails_dir exists, rather than earlier where the key was not available.
    cleanup_old_caches(os.path.dirname(thumbnails_dir))
    
    # TIMING: Load image
    start = time.perf_counter()
    try:
        import cv2
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise Exception("Failed to load image")
        img_height, img_width = img.shape
        timings['image_load'] = (time.perf_counter() - start) * 1000
    except Exception as e:
        return {
            'timestamp': datetime.now().isoformat(),
            'filename': filename,
            'error': f'Image load error: {str(e)}'
        }
    
    # === STEP 1: Edge Detection (CORE - runs always) ===
    # OPT-2026-05-05: Canny runs on the 320x180 thumbnail instead of the full
    # 1280x720 capture. The only consumer of `edges` is the bottom-edge density
    # check at STEP 3 — that's a percentage measure of banner/OSD content, so
    # the smaller image is sufficient. Saves ~22x pixels of work per frame.
    # ROLLBACK if zap-confirmation gets noisy: replace `edge_src_img` and the
    # edge_split_y line below with `edges = cv2.Canny(img, 50, 150)` and use
    # `edges[split_y:img_height, :]` at STEP 3.
    start = time.perf_counter()
    edge_src_path = os.path.join(thumbnails_dir, filename.replace('.jpg', '_thumbnail.jpg'))
    edge_src_img = cv2.imread(edge_src_path, cv2.IMREAD_GRAYSCALE) if os.path.exists(edge_src_path) else None
    if edge_src_img is None:
        # Thumbnail missing — fall back to full image so detection still works.
        edge_src_img = img
    edges = cv2.Canny(edge_src_img, 50, 150)
    edge_height, _ = edges.shape
    edge_split_y = int(edge_height * 0.7)  # Same 70% split, in thumbnail-space
    timings['edge_detection'] = (time.perf_counter() - start) * 1000

    # Define regions (full-image coords, used by blackscreen sampling on `img`)
    header_y = int(img_height * 0.05)  # Skip top 5% (TV time/header)
    split_y = int(img_height * 0.7)     # Blackscreen region: 5-70%
    
    # === STEP 2: Blackscreen Detection (optimized sampling) ===
    # ADAPTIVE: When overloaded, only detect every N frames (2 seconds) - OPTIMIZATION: Lowered threshold from 50 to 30
    start = time.perf_counter()
    
    # Threshold = 10 (matches production - accounts for compression artifacts)
    threshold = 10
    
    # ✅ SKIP: If freeze incident is ongoing, don't waste CPU checking blackscreen
    if skip_blackscreen:
        blackscreen = False
        dark_percentage = 0.0
        timings['blackscreen'] = 0.0  # Skipped - incident priority
    else:
        # Check if we should use cached result (adaptive sampling when overloaded)
        if queue_size > 30 and frame_number % OVERLOAD_DETECTION_INTERVAL != 0:
            # Return cached blackscreen result
            global _blackscreen_result_cache
            device_key = capture_dir
            if device_key in _blackscreen_result_cache:
                cached = _blackscreen_result_cache[device_key]
                blackscreen = cached['blackscreen']
                dark_percentage = cached['percentage']
                timings['blackscreen'] = 0.0  # Skipped - adaptive sampling
            else:
                # No cache - assume not blackscreen
                blackscreen = False
                dark_percentage = 0.0
                timings['blackscreen'] = 0.0  # Skipped - no cache
        else:
            # Run full blackscreen detection
            # Analyze 5% to 70% (skip header, skip bottom banner)
            top_region = img[header_y:split_y, :]
            
            # Sample every 4th pixel (6.25% sample) - OPTIMIZED from every 3rd (11%)
            sample = top_region[::4, ::4]
            sample_dark = np.sum(sample <= threshold)
            sample_total = sample.shape[0] * sample.shape[1]
            dark_percentage = (sample_dark / sample_total) * 100
            
            # Full scan only if edge case (70-90%)
            if 70 <= dark_percentage <= 90:
                total_pixels = top_region.shape[0] * top_region.shape[1]
                dark_pixels = np.sum(top_region <= threshold)
                dark_percentage = (dark_pixels / total_pixels) * 100
            
            # ✅ THRESHOLD: Raised from 85% to 95% to avoid false positives on dark content
            # Dark movies/credits (85-94% dark) should NOT trigger blackscreen
            # Real blackscreens (channel change, technical issues) are 95-100% pure black
            blackscreen = bool(dark_percentage > 95)
            timings['blackscreen'] = (time.perf_counter() - start) * 1000
            
            # Cache result for next frames (when overloaded) - OPTIMIZATION: Lowered threshold from 50 to 30
            if queue_size > 30:
                device_key = capture_dir
                _blackscreen_result_cache[device_key] = {
                    'blackscreen': blackscreen,
                    'percentage': dark_percentage,
                    'frame_number': frame_number
                }
    
    # === STEP 3: Bottom Content Check (ONLY if blackscreen - for zap confirmation) ===
    start = time.perf_counter()
    if blackscreen:
        # Check bottom 30% for banner/channel info (zap confirmation)
        # NOTE (OPT-2026-05-05): edges is in thumbnail-space (see STEP 1), so we
        # slice with edge_split_y / edge_height instead of split_y / img_height.
        edges_bottom = edges[edge_split_y:edge_height, :]
        bottom_edge_density = np.sum(edges_bottom > 0) / edges_bottom.size * 100
        has_bottom_content = bool(3 < bottom_edge_density < 20)
        timings['zap'] = (time.perf_counter() - start) * 1000
    else:
        # No blackscreen = no need to check for zapping
        has_bottom_content = False
        bottom_edge_density = 0.0
        timings['zap'] = 0.0  # Skipped
    
    # Zap decision: blackscreen + bottom content
    zap = blackscreen and has_bottom_content
    
    # === NEW: Check if zap STARTS this frame ===
    zap_sequence_start = False
    if zap and not zap_state:
        # Zap sequence STARTS - save state
        zap_sequence_start = True
        save_zap_state(capture_dir, {
            'zapping': True,
            'start_frame': filename,
            'start_timestamp': datetime.fromtimestamp(os.path.getmtime(image_path)).isoformat(),
            'start_frame_number': frame_number
        })
        print(f"🎯 [Detector] Zap sequence started at {filename}")
    
    # === STEP 4: Freeze Detection (Pixel diff - fastest & most accurate) ===
    start = time.perf_counter()
    
    # ✅ SKIP: If blackscreen incident is ongoing, don't waste CPU checking freeze
    if skip_freeze:
        frozen = False
        freeze_details = {}
        timings['freeze'] = 0.0  # Skipped - incident priority
    else:
        # Load current frame thumbnail for freeze detection (compare thumbnails with thumbnails)
        current_thumbnail_filename = filename.replace('.jpg', '_thumbnail.jpg')
        current_thumbnail_path = os.path.join(thumbnails_dir, current_thumbnail_filename)
        
        if os.path.exists(current_thumbnail_path):
            current_thumbnail = cv2.imread(current_thumbnail_path, cv2.IMREAD_GRAYSCALE)
            if current_thumbnail is not None:
                frozen, freeze_details = detect_freeze_pixel_diff(current_thumbnail, thumbnails_dir, filename, fps, queue_size, freeze_duration_ms)
            else:
                frozen, freeze_details = False, {}
        else:
            frozen, freeze_details = False, {}
        
        timings['freeze'] = (time.perf_counter() - start) * 1000
    
    # === STEP 5: Subtitle Detection - REMOVED ===
    # Subtitle OCR is now handled exclusively by subtitle_monitor.py (separate process)
    # No OCR code runs in detector.py anymore
    
    # === STEP 6: Macroblock Analysis (skip if freeze or blackscreen) ===
    # ADAPTIVE: Auto-skip macroblocks when system is overloaded (queue > 50)
    start = time.perf_counter()
    if not ENABLE_MACROBLOCKS:
        # Macroblocks detection disabled by configuration
        macroblocks, quality_score = False, 0.0
        timings['macroblocks'] = 0.0  # Disabled
    elif skip_macroblocks:
        # ✅ SKIP: Incident ongoing (blackscreen/freeze) - don't waste CPU checking macroblocks
        macroblocks, quality_score = False, 0.0
        timings['macroblocks'] = 0.0  # Skipped - incident priority
    elif blackscreen or frozen:
        # Skip if blackscreen/freeze already detected in current frame (priority rules)
        macroblocks, quality_score = False, 0.0
        timings['macroblocks'] = 0.0  # Skipped
    elif queue_size > 30:  # OPTIMIZATION: Lowered threshold from 50 to 30
        # ADAPTIVE: Auto-skip when system overloaded (even if ENABLE_MACROBLOCKS=True)
        # This prevents false macroblocks when it's likely a freeze
        # Also reduces CPU load during backlog processing
        if ENABLE_MACROBLOCKS and queue_size % 25 == 0:
            logger.debug(f"Auto-skipping macroblocks due to queue backlog ({queue_size} frames)")
        macroblocks, quality_score = False, 0.0
        timings['macroblocks'] = 0.0  # Skipped (auto - queue backlog)
    else:
        # System healthy - run macroblocks detection
        macroblocks, quality_score = analyze_macroblocks(image_path)
        timings['macroblocks'] = (time.perf_counter() - start) * 1000
    
    # Build freeze comparison list showing current vs previous frames
    # ALWAYS populate these fields (even when not frozen) so images are available for display
    freeze_comparisons = []
    freeze_debug_info = {}
    last_3_filenames = []  # For display/R2 upload - ALWAYS populated when comparison data exists
    last_3_thumbnails = []  # For display/R2 upload - ALWAYS populated when comparison data exists
    
    if freeze_details and 'frames_compared' in freeze_details:
        captures_dir = os.path.dirname(image_path)
        
        # Get current frame info
        current_capture_path = image_path
        current_thumbnail_filename = filename.replace('.jpg', '_thumbnail.jpg')
        current_thumbnail_path = os.path.join(thumbnails_dir, current_thumbnail_filename)
        
        # Build comparison for each previous frame checked (ALWAYS, not just when frozen)
        for idx, frame_compared in enumerate(freeze_details['frames_compared']):
            # frame_compared is like "frame_12345" - extract number and build proper filename
            prev_frame_num = int(frame_compared.split('_')[1])
            
            # Build filenames with same format as current file
            frame_prefix = filename.rsplit('_', 1)[0]  # "capture"
            frame_digits = len(filename.split('_')[1].split('.')[0])
            capture_filename = f"{frame_prefix}_{str(prev_frame_num).zfill(frame_digits)}.jpg"
            thumbnail_filename = f"{frame_prefix}_{str(prev_frame_num).zfill(frame_digits)}_thumbnail.jpg"
            
            prev_capture_path = os.path.join(captures_dir, capture_filename)
            prev_thumbnail_path = os.path.join(thumbnails_dir, thumbnail_filename)
            
            # Get difference percentage for this comparison
            diff_percentage = freeze_details['frame_differences'][idx] if idx < len(freeze_details['frame_differences']) else None
            
            # Collect paths for display - only if files exist
            if os.path.exists(prev_capture_path):
                last_3_filenames.append(prev_capture_path)
            if os.path.exists(prev_thumbnail_path):
                last_3_thumbnails.append(prev_thumbnail_path)
            
            # Add structured comparison (for all frames, not just frozen)
            freeze_comparisons.append({
                'current_frame': filename,
                'previous_frame': capture_filename,
                'difference_percentage': diff_percentage,
                'current_capture_path': current_capture_path,
                'previous_capture_path': prev_capture_path,
                'current_thumbnail_path': current_thumbnail_path,
                'previous_thumbnail_path': prev_thumbnail_path,
                'frozen': bool(diff_percentage < 5.0) if diff_percentage is not None else None
            })
    
    # Capture freeze detection debug info
    if freeze_details:
        freeze_debug_info = {
            'frames_found': freeze_details.get('frames_found', 0),
            'frames_needed': freeze_details.get('frames_needed', 2),
            'frames_checked': freeze_details.get('frames_checked', []),
            'detection_method': freeze_details.get('detection_method', 'unknown'),
            'thumbnails_dir': thumbnails_dir
        }

    # Restore freeze_diffs for downstream consumers (incident metadata/UI)
    freeze_diffs = []
    if freeze_details and freeze_details.get('frame_differences'):
        freeze_diffs = freeze_details['frame_differences']
    elif freeze_comparisons:
        freeze_diffs = [
            c.get('difference_percentage')
            for c in freeze_comparisons
            if c.get('difference_percentage') is not None
        ]
    
    # Calculate total time
    timings['total'] = (time.perf_counter() - total_start) * 1000
    
    # Build result with enhanced metadata
    result = {
        'timestamp': datetime.fromtimestamp(os.path.getmtime(image_path)).isoformat(),
        'filename': filename,
        
        # Blackscreen (enhanced)
        'blackscreen': bool(blackscreen),
        'blackscreen_percentage': round(dark_percentage, 1),
        'blackscreen_threshold': threshold,
        'blackscreen_region': '5-70%',
        
        # Zap detection (NEW)
        'zap': zap,
        'has_bottom_content': has_bottom_content,
        'bottom_edge_density': round(bottom_edge_density, 1),
        
        # Zap sequence tracking (NEW)
        'zap_sequence_start': zap_sequence_start,
        
        # Motion shape (raw, pre-localize): live / carousel / pip / static / minor
        'motion': (freeze_details or {}).get('motion'),

        # Freeze (with detailed comparisons)
        'freeze': bool(frozen),
        'freeze_diffs': freeze_diffs,
        'freeze_comparisons': freeze_comparisons,  # ALWAYS populated (even when not frozen)
        'freeze_debug': freeze_debug_info if freeze_debug_info else None,
        'last_3_filenames': last_3_filenames,  # ALWAYS populated - for display even when not frozen
        'last_3_thumbnails': last_3_thumbnails,  # ALWAYS populated - for display even when not frozen
        
        # Macroblocks (unchanged)
        'macroblocks': bool(macroblocks),
        'quality_score': round(quality_score, 1),
        
        # Performance (enhanced)
        'performance_ms': {k: round(v, 2) for k, v in timings.items()}
    }
    
    return result
