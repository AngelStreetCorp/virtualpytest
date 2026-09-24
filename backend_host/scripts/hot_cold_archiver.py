#!/usr/bin/env python3
"""
HOT/COLD STORAGE ARCHIVER - Safety Cleanup + Progressive MP4 Building
======================================================================

Responsibilities:
1. SAFETY CLEANUP: Enforce hot storage limits on ALL file types (prevent RAM exhaustion)
2. Progressive MP4 building: HOT TS  1min MP4  append to growing 10min chunk in COLD
3. Audio extraction: 10min MP4  MP3 saved directly to COLD /audio/{hour}/
4. KEEP 1min MP4s: Rotating slots (0-9) for individual playback until overwritten

Progressive append: Each minute appends 1min to the growing chunk (same URL, grows 110min)
Result: Frontend timeline has NO CHANGES - same chunk URL just grows in duration
1min MP4s: Kept in temp/ using rotating slots, playable individually for ~10 minutes

Note: Metadata archival is handled by capture_monitor.py (incremental append to chunks)

What goes to COLD storage (SD mode) or HOT storage (RAM mode):
- Segments (as 10min MP4 chunks in /segments/{hour}/)
- Metadata (as 10min JSON chunks in /metadata/{hour}/)
- Audio (as 10min MP3 chunks in /audio/{hour}/ - HOT in RAM mode!)
- Transcripts (saved directly by transcript_accumulator.py in /transcript/{hour}/ - always COLD)

What stays HOT-only (deleted):
- Captures (uploaded to R2 cloud when needed)
- Thumbnails (local freeze detection only)
"""

import os
import sys
import time
import shutil
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from shared.src.lib.utils.storage_path_utils import get_capture_base_directories, is_ram_mode
from shared.src.lib.utils.storage_path_utils import get_active_captures_conf_path, parse_active_captures_conf
from shared.src.lib.utils.video_utils import merge_progressive_batch

# Configure logging (systemd handles file output)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [HOT_COLD_ARCHIVER] %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ANSI color codes for terminal output
class Colors:
    BLUE = '\033[94m'      # Cold storage
    CYAN = '\033[96m'      # Info/stats
    GREEN = '\033[92m'     # Success
    YELLOW = '\033[93m'    # Warning
    RED = '\033[91m'       # Error
    BOLD = '\033[1m'
    RESET = '\033[0m'      # Reset to default

# Configuration
# Note: This script doesn't use active_captures.conf - it discovers devices via get_capture_base_directories()
# which reads the file from the centralized location (/var/www/html/stream/active_captures.conf)

# DUAL-THREAD ARCHITECTURE:
# - HOT thread: Critical RAM management (fast, every 15s)
# - COLD thread: Batch cleanup (slow, every 60s, max 200 files per device)
HOT_THREAD_INTERVAL = 30    # 30s - hot storage cleanup + MP4 building (was 15s; halved spawn rate)
COLD_THREAD_INTERVAL = 60   # 60s - cold storage cleanup (batched)
COLD_BATCH_LIMIT = 5000     # Max files to delete per device per cold cycle (was 200 — too slow for backlogs)
ROOT_STALE_MAX_AGE_SECONDS = 3600      # 1h for root live files
ARCHIVE_STALE_MAX_AGE_SECONDS = 26 * 3600  # 26h for archived hour folders
VERIFICATION_CLEANUP_INTERVAL = 3600  # 1 hour - verification results cleanup
last_verification_cleanup = {}  # capture_dir -> last cleanup time (per-channel, not shared)

REPORTS_CLEANUP_INTERVAL = 3600        # 1 hour - reports cleanup check cadence
REPORTS_MAX_AGE_SECONDS = 30 * 86400   # 30 days - mirrors the MinIO script-reports/ ILM rule
last_reports_cleanup = {}  # capture_dir -> last cleanup time (per-channel)

# Hot storage limits
# LIFECYCLE:
# - Segments: HOT TS (FFmpeg auto-deletes @ 150, safety cleanup @ 200 if needed)  grouped as MP4 to COLD
# - Captures: HOT only  deleted (uploaded to R2 cloud when needed)
# - Thumbnails: HOT only  deleted (local freeze detection only)
# - Metadata: HOT individual JSONs  grouped & saved to COLD /metadata/{hour}/
# - Transcripts: Saved directly to COLD /transcript/{hour}/ (by transcript_accumulator.py)
# - Audio: Extracted directly to COLD /audio/{hour}/ (from 10min MP4 chunks)
#
# RAM Usage (HIGH QUALITY CAPTURES - Video content worst case):
# - Segments: 150  38KB = 6MB (FFmpeg auto-deletes, 200 limit = safety net)
# - Captures: 900  245KB = 220MB (180s buffer  deleted, R2 when needed)
# - Thumbnails: 100  28KB = 3MB (freeze detection  deleted)
# - Metadata: 750  1KB = 0.75MB (150s buffer  grouped to cold)
# - Transcripts: N/A (saved directly to cold by transcript_accumulator)
# - Audio: N/A (extracted directly to COLD /audio/{hour}/)
# Total: ~230MB per device worst case (58% of the 400MB mount).
# Measured on a real STB stream the frames are 24-81KB, i.e. ~21-70MB for the 900,
# so the 245KB figure above is the video-heavy ceiling, not the normal case. tmpfs
# allocates on demand, so the mount only costs what is actually written.
#
HOT_LIMITS = {
    'segments': 200,      # Safety limit > FFmpeg's 150 (only cleanup if FFmpeg fails)
    'captures': 900,      # 180s buffer  deleted (R2 cloud when needed)
                          # 900 rather than 300 so a KPI window up to 3 minutes stays on
                          # the live 5fps grid (+/-200ms). At 300 (60s) anything longer -
                          # a reboot measurement, say - fell back to the 1-2fps archive
                          # and was silently quantised to +/-500-1000ms.
                          # Needs the 400M mount (ensure_hot_mounts.sh); 900 x 245KB
                          # worst case does not fit the old 200M.
    'thumbnails': 100,    # For freeze detection  deleted
    'metadata': 750,      # 150s buffer  grouped to 10min chunks in cold
}

# ---------------------------------------------------------------------------- #
# Capture archiving (full-res stills → cold for 24h, for the AVQ frame viewer)  #
# ---------------------------------------------------------------------------- #
# OFF by default to preserve current behavior (captures are HOT-only → deleted).
# Enable per-host via the archiver service flag `--keep-captures true` (mirrors
# transcript.service) or the env var ARCHIVE_CAPTURES=true. Stills are sampled to
# ARCHIVE_CAPTURES_FPS (default 2 — measured ~7.5 GB/device/24h on a real host) and
# COPIED into captures/{hour}/ with time-based names — same hour-folder + 24h
# rolling-overwrite principle as segments/metadata. Cold cleanup is already done
# by cleanup_cold_captures() (>26h). A min-free-% guard prevents a full SD wedge.
#
# ARCHIVE_CAPTURES_FPS defaults to 2, not 1: a KPI measured on archived frames is
# quantised to their spacing, so 1 fps meant +/-1000ms with nothing on the report to
# say so. 2 fps halves that. Cost measured on a real host: ~3.7GB and ~72k files per
# device per 24h at 1 fps, so ~7.5GB and ~144k files at 2 fps. Check free space and
# inodes on the target host before enabling captures archiving.
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')

ARCHIVE_CAPTURES = _env_bool('ARCHIVE_CAPTURES', False)
try:
    ARCHIVE_CAPTURES_FPS = float(os.getenv('ARCHIVE_CAPTURES_FPS', '2') or '2')
except ValueError:
    ARCHIVE_CAPTURES_FPS = 2.0
try:
    ARCHIVE_CAPTURES_MIN_FREE_PCT = float(os.getenv('ARCHIVE_CAPTURES_MIN_FREE_PCT', '10') or '10')
except ValueError:
    ARCHIVE_CAPTURES_MIN_FREE_PCT = 10.0
CAPTURE_SEQ_FPS = 5   # cold filenames live in the native 5fps sequence space so a
                      # frame's time-of-day → capture_{seconds_today*5}.jpg aligns
                      # with the per-frame metadata math (see AVQFrameInspector).

# REMOVED: RETENTION_HOURS config
# 
# WHY: Natural 24h rolling buffer through time-based sequential filenames
# All files naturally overwrite after 24h - no retention configuration needed!
# 
# How it works:
# - Files get time-based names based on seconds since midnight
# - After 24h, same time  same filename  automatic overwrite
# - Result: All hour folders maintain 24h of data automatically

# File patterns for archive_hot_files() function (moves files from hot to cold hour folders)
# Note: Metadata uses merge_metadata_batch() instead (groups then saves to cold)
# Note: Transcripts saved directly to cold by transcript_accumulator.py
# Note: Audio extracted directly to cold /audio/{hour}/ (no hot storage needed)
FILE_PATTERNS = {
    'segments': 'segment_*.ts',     # Archived to cold (will be grouped as MP4)
}
# NOT archived (HOT-only with deletion): captures, thumbnails

def get_directory_size(path: str) -> int:
    """Get directory size in bytes"""
    try:
        result = subprocess.run(
            ['du', '-sb', path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except:
        pass
    return 0


def get_ram_disk_usage() -> Dict[str, any]:
    """Get RAM disk usage statistics for /var/www/html/stream/"""
    try:
        result = subprocess.run(
            ['df', '-h', '/var/www/html/stream/'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                return {
                    'size': parts[1],
                    'used': parts[2],
                    'available': parts[3],
                    'use_percent': parts[4]
                }
    except:
        pass
    return {}


def get_hot_folder_stats(capture_dir: str) -> Dict[str, int]:
    """Get file counts and sizes for live storage folders (hot if RAM, root if SD)"""
    ram_mode = is_ram_mode(capture_dir)
    hot_base = os.path.join(capture_dir, 'hot') if ram_mode else capture_dir

    stats = {}
    for file_type in ['segments', 'captures', 'thumbnails', 'metadata']:
        hot_dir = os.path.join(hot_base, file_type)
        if os.path.isdir(hot_dir):
            # Use os.scandir() — single syscall per entry (mtime+size from d_type/stat cache)
            count = 0
            total_size = 0
            try:
                with os.scandir(hot_dir) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False) and not entry.name.startswith('.'):
                            count += 1
                            try:
                                total_size += entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                pass
            except OSError:
                pass
            stats[file_type] = {
                'count': count,
                'size_bytes': total_size
            }
        else:
            stats[file_type] = {'count': 0, 'size_bytes': 0}

    return stats


def format_bytes(bytes_val: int) -> str:
    """Format bytes to human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f}TB"


def print_ram_summary(capture_dirs: List[str], label: str):
    """Print storage usage summary (hot if RAM, live if SD)"""
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"{label}")
    logger.info("=" * 80)
    
    # Global RAM disk stats
    ram_stats = get_ram_disk_usage()
    if ram_stats:
        logger.info(f"  RAM DISK (/var/www/html/stream/): {ram_stats['used']}/{ram_stats['size']} ({ram_stats['use_percent']}) - Available: {ram_stats['available']}")
    
    # Per-capture directory breakdown
    total_storage_size = 0
    for capture_dir in capture_dirs:
        device_name = os.path.basename(capture_dir)
        stats = get_hot_folder_stats(capture_dir)
        ram_mode = is_ram_mode(capture_dir)
        folder_label = "hot" if ram_mode else ""
        
        # Calculate totals
        total_files = sum(s['count'] for s in stats.values())
        total_size = sum(s['size_bytes'] for s in stats.values())
        total_storage_size += total_size
        
        # Build breakdown string
        breakdown = []
        for file_type, data in stats.items():
            if data['count'] > 0:
                limit = HOT_LIMITS.get(file_type, 0)
                limit_str = f"/{limit}" if limit > 0 else ""
                breakdown.append(f"{file_type}={data['count']}{limit_str}({format_bytes(data['size_bytes'])})")
        
        if folder_label:
            logger.info(f"   {device_name}/{folder_label}: {total_files} files, {format_bytes(total_size)} - [{', '.join(breakdown)}]")
        else:
            logger.info(f"   {device_name}: {total_files} files, {format_bytes(total_size)} - [{', '.join(breakdown)}]")
    
    logger.info(f"   Total storage: {format_bytes(total_storage_size)}")
    logger.info("=" * 80)


def get_file_hour(filepath: str) -> int:
    """Get hour (0-23) from file modification time"""
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime).hour
    except Exception as e:
        logger.error(f"Error getting file hour for {filepath}: {e}")
        return datetime.now().hour


def calculate_time_based_name(filepath: str, file_type: str, fps: int = 5) -> str:
    """
    Calculate time-based sequential filename for 24h rolling buffer
    
    Uses file mtime to calculate position in 24h cycle:
    - Segments (1s): 0-86399 (24h  3600s)
    - Images (5fps): 0-431999 (86400s  5fps)
    - Images (2fps): 0-172799 (86400s  2fps)
    - Transcripts: Keep original name (transcript_hourX.json)
    
    Args:
        filepath: Original file path
        file_type: 'segments', 'captures', 'metadata', 'transcripts'
        fps: Frames per second (for images only)
    
    Returns:
        New filename with time-based sequential number or original name for transcripts
    """
    try:
        # Special case: transcripts keep their original name (transcript_hour13.json)
        if file_type == 'transcripts':
            return os.path.basename(filepath)
        
        mtime = os.path.getmtime(filepath)
        dt = datetime.fromtimestamp(mtime)
        
        # Calculate seconds since midnight
        seconds_today = (dt.hour * 3600) + (dt.minute * 60) + dt.second
        
        if file_type == 'segments':
            # 1 segment per second: 0-86399
            sequence_num = seconds_today
            new_name = f"segment_{sequence_num:06d}.ts"
        elif file_type in ['captures', 'metadata']:
            # Images at FPS rate
            sequence_num = seconds_today * fps
            
            # Get original filename to extract extension and type
            original_name = os.path.basename(filepath)
            
            if file_type == 'metadata':
                new_name = f"capture_{sequence_num:06d}.json"
            else:  # captures
                new_name = f"capture_{sequence_num:06d}.jpg"
        else:
            # Unknown type, keep original name
            return os.path.basename(filepath)
        
        return new_name
        
    except Exception as e:
        logger.error(f"Error calculating time-based name for {filepath}: {e}")
        return os.path.basename(filepath)


def archive_hot_files(capture_dir: str, file_type: str) -> int:
    """
    Archive hot files to hour folders when exceeding limit
    
    **RAM MODE:** Reads from /hot/captures/, archives to /captures/X/
    **SD MODE:** Reads from /captures/, archives to /captures/X/
    
    GUARANTEES:
    - Always keeps the NEWEST hot_limit files in hot storage
    - Never archives files less than 60 seconds old (safety buffer)
    - Verifies correct file count after archiving
    
    Returns: Number of files archived
    """
    ram_mode = is_ram_mode(capture_dir)
    
    # Determine hot and cold paths based on mode
    if ram_mode:
        # RAM mode: hot storage in /hot/ subdirectory
        hot_dir = os.path.join(capture_dir, 'hot', file_type)
        cold_dir = os.path.join(capture_dir, file_type)
    else:
        # SD mode: hot storage in root, cold in hour subfolders
        hot_dir = os.path.join(capture_dir, file_type)
        cold_dir = hot_dir  # Same directory, hour folders are subdirs
    
    if not os.path.isdir(hot_dir):
        return 0
    
    pattern = FILE_PATTERNS[file_type]
    hot_limit = HOT_LIMITS[file_type]
    
    # Get files in hot storage (root only, not subdirs)
    try:
        files = []
        current_time = time.time()
        
        for item in Path(hot_dir).glob(pattern):
            if item.is_file() and item.parent == Path(hot_dir):
                files.append(item)
        
        file_count = len(files)
        
        if file_count < hot_limit:
            logger.debug(f"{file_type}: {file_count} files (within limit {hot_limit})")
            return 0
        
        # Calculate how many to archive
        to_archive = file_count - hot_limit
        
        # Sort by modification time (oldest first) - CRITICAL for keeping newest files
        files.sort(key=lambda f: f.stat().st_mtime)
        
        # Safety check: Never archive files less than 30 seconds old
        # This protects restart video operations from race conditions
        MIN_AGE_SECONDS = 30
        files_to_archive = []
        files_too_recent = []
        
        for filepath in files[:to_archive]:
            file_age = current_time - filepath.stat().st_mtime
            if file_age >= MIN_AGE_SECONDS:
                files_to_archive.append(filepath)
            else:
                files_too_recent.append(filepath)
        
        if files_too_recent:
            logger.warning(f"{file_type}: {len(files_too_recent)} files too recent to archive (< {MIN_AGE_SECONDS}s old) - keeping in hot storage for safety")
        
        if not files_to_archive:
            logger.info(f"{file_type}: {file_count} files, but all recent files (< {MIN_AGE_SECONDS}s old) - skipping archival for safety")
            return 0
        
        # Log what we're about to do
        oldest_file_age = current_time - files_to_archive[0].stat().st_mtime
        newest_kept_age = current_time - files[-1].stat().st_mtime
        logger.info(f"{file_type}: Archiving {len(files_to_archive)} old files ({file_count}  {hot_limit + len(files_too_recent)}, oldest={oldest_file_age:.1f}s, newest_kept={newest_kept_age:.1f}s)")
        
        archived_count = 0
        for filepath in files_to_archive:
            try:
                # Get hour from file mtime
                file_hour = get_file_hour(str(filepath))
                hour_folder = os.path.join(cold_dir, str(file_hour))
                
                # Ensure hour folder exists
                os.makedirs(hour_folder, exist_ok=True)
                
                # Calculate time-based sequential name for 24h rolling buffer
                # FPS detection: segments=1fps, captures/metadata=5fps default
                fps = 5 if file_type in ['captures', 'metadata'] else 1
                new_filename = calculate_time_based_name(str(filepath), file_type, fps)
                
                # Move file to hour folder with time-based name (RAM  SD or SD root  SD hour)
                dest_path = os.path.join(hour_folder, new_filename)
                
                # If file exists (24h rollover), overwrite it (natural rolling buffer behavior)
                if os.path.exists(dest_path):
                    logger.debug(f"Overwriting existing {new_filename} (24h rollover)")
                    os.remove(dest_path)
                
                shutil.move(str(filepath), dest_path)
                
                archived_count += 1
                mode_label = "RAMSD" if ram_mode else "hotcold"
                logger.debug(f"Archived {filepath.name}  {file_type}/{file_hour}/{new_filename} ({mode_label})")
                
            except Exception as e:
                logger.error(f"Error archiving {filepath}: {e}")
        
        # Verify: Count remaining files in hot storage
        remaining_files = [f for f in Path(hot_dir).glob(pattern) if f.is_file() and f.parent == Path(hot_dir)]
        remaining_count = len(remaining_files)
        
        if remaining_count > hot_limit + 10:  # Allow 10 file buffer for race conditions
            logger.warning(f"{file_type}: After archiving, hot storage still has {remaining_count} files (expected ~{hot_limit})")
        else:
            logger.info(f"{file_type}:  Verified hot storage has {remaining_count} files (target: {hot_limit})")
        
        return archived_count
        
    except Exception as e:
        logger.error(f"Error archiving {file_type} files: {e}")
        return 0

HOT_CLEANUP_BATCH = 5000  # Max files to delete per hot cleanup call (prevents multi-minute stalls)

def cleanup_hot_files(capture_dir: str, file_type: str, pattern: str) -> int:
    """
    Generic safety cleanup for hot storage - keep only newest N files, DELETE old ones.

    This is a safety net to prevent RAM exhaustion when merging/archiving processes fail.
    Works independently from progressive merging/archiving.

    Uses os.scandir() for single-syscall enumeration and caps deletions per cycle
    to avoid multi-minute stalls when backlogs are huge (e.g. 400K+ files).

    Args:
        capture_dir: Base capture directory
        file_type: Type of files ('segments', 'captures', 'metadata', 'audio', 'thumbnails')
        pattern: Glob pattern to match files

    Returns: Number of files deleted
    """
    import fnmatch

    ram_mode = is_ram_mode(capture_dir)

    # Determine hot path based on mode
    if ram_mode:
        hot_dir = os.path.join(capture_dir, 'hot', file_type)
    else:
        hot_dir = os.path.join(capture_dir, file_type)

    if not os.path.isdir(hot_dir):
        return 0

    hot_limit = HOT_LIMITS.get(file_type)
    if not hot_limit:
        return 0

    try:
        # Use os.scandir() — one syscall per entry, returns mtime from dirent cache
        scan_start = time.time()
        files_with_mtime = []
        try:
            with os.scandir(hot_dir) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False) and fnmatch.fnmatch(entry.name, pattern):
                        try:
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            files_with_mtime.append((entry.name, entry.path, mtime))
                        except OSError:
                            pass
        except OSError as e:
            logger.error(f"{file_type}: scandir failed on {hot_dir}: {e}")
            return 0

        file_count = len(files_with_mtime)
        scan_elapsed = time.time() - scan_start

        if file_count <= hot_limit:
            if file_count > 0:
                logger.debug(f"{file_type}: {file_count} files (within limit {hot_limit})")
            return 0

        # Calculate how many to delete, capped by batch limit
        to_delete_total = file_count - hot_limit
        to_delete = min(to_delete_total, HOT_CLEANUP_BATCH)

        if to_delete < to_delete_total:
            logger.info(f"{file_type}: Backlog {file_count} files, deleting batch of {to_delete}/{to_delete_total} (limit: {hot_limit}, scanned in {scan_elapsed*1000:.0f}ms)")
        else:
            logger.info(f"{file_type}: Found {file_count} files, deleting {to_delete} (limit: {hot_limit}, scanned in {scan_elapsed*1000:.0f}ms)")

        # Sort by mtime (oldest first) — only need the oldest `to_delete` entries
        # For huge backlogs, partial sort would be faster but Python doesn't have nsmallest for this size
        sort_start = time.time()
        files_with_mtime.sort(key=lambda x: x[2])
        sort_elapsed = time.time() - sort_start

        if sort_elapsed > 1.0:
            logger.warning(f"{file_type}: Sort took {sort_elapsed:.1f}s for {file_count} files")

        # Delete oldest files
        deleted_count = 0
        first_deleted = None
        last_deleted = None
        for name, path, _ in files_with_mtime[:to_delete]:
            try:
                os.remove(path)
                if first_deleted is None:
                    first_deleted = name
                last_deleted = name
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting {path}: {e}")

        if deleted_count > 0:
            remaining = file_count - deleted_count
            logger.info(f"{file_type}: Safety cleanup deleted {deleted_count} old files ({file_count} → {remaining}, target: {hot_limit})")
            logger.info(f"{file_type}: Deleted range: {first_deleted} ... {last_deleted}")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning {file_type}: {e}")
        return 0


STALE_HOT_MAX_AGE_S = 3600  # hot dirs hold ~60s of live data — anything older is leaked garbage

def sweep_stale_hot_files(capture_dir: str) -> int:
    """
    Catch-all sweep: delete ANY file older than STALE_HOT_MAX_AGE_S from the hot
    subdirs, regardless of filename.

    The per-type rotations only see their expected patterns (capture_*[0-9].jpg,
    segment_*.ts, ...). Files under other names are invisible to them and accumulate
    until the 200MB tmpfs is full and ffmpeg can no longer write segments — seen on
    host1 capture2 (2026-07-21): 17k text_detection_*.png from OCR
    verification plus orphaned capture_*.jpg.tmp filled the mount to 100%.

    Non-recursive by design: hour folders (SD-mode archives) are directories and
    are skipped; only stray files sitting in the hot/live dirs are eligible.
    """
    ram_mode = is_ram_mode(capture_dir)
    hot_base = os.path.join(capture_dir, 'hot') if ram_mode else capture_dir
    cutoff = time.time() - STALE_HOT_MAX_AGE_S
    deleted = 0
    for sub in ('segments', 'captures', 'thumbnails', 'metadata'):
        hot_dir = os.path.join(hot_base, sub)
        if not os.path.isdir(hot_dir):
            continue
        try:
            with os.scandir(hot_dir) as it:
                for entry in it:
                    if deleted >= HOT_CLEANUP_BATCH:
                        logger.info(f"stale-sweep: batch cap {HOT_CLEANUP_BATCH} reached, continuing next cycle")
                        return deleted
                    try:
                        if entry.is_file(follow_symlinks=False) and \
                                entry.stat(follow_symlinks=False).st_mtime < cutoff:
                            os.remove(entry.path)
                            deleted += 1
                    except OSError:
                        pass
        except OSError as e:
            logger.error(f"stale-sweep: scandir failed on {hot_dir}: {e}")
    if deleted:
        logger.info(f"stale-sweep: deleted {deleted} stale files (>{STALE_HOT_MAX_AGE_S}s) from hot dirs")
    return deleted


def rotate_hot_captures(capture_dir: str) -> int:
    """
    Rotate hot captures - keep only newest 300 files, DELETE old ones.
    
    Captures don't go to cold storage (pushed to cloud), so we just delete old files.
    This keeps RAM usage under control (60s buffer = 74MB worst case for video content).
    
    Returns: Number of files deleted
    """
    return cleanup_hot_files(capture_dir, 'captures', 'capture_*[0-9].jpg')


def _cold_free_percent(capture_dir: str) -> Optional[float]:
    """Free space % of the COLD filesystem holding capture_dir (the SD root).
    Returns None if it can't be determined (caller treats None as 'allow')."""
    try:
        st = os.statvfs(capture_dir)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            return None
        return 100.0 * free / total
    except Exception:
        return None


def archive_captures(capture_dir: str, fps: float = 1.0) -> int:
    """
    Archive sampled full-res stills from hot → cold captures/{hour}/ for the AVQ
    frame inspector (24h history). Same principle as segments: time-based names in
    hour folders, 24h rolling overwrite. Sampled to `fps` by keeping at most one
    frame per (1/fps)-second slot (default 1 fps = one still/second).

    Frames are COPIED (not moved): rotate_hot_captures still owns hot-RAM deletion,
    and the live capture/detection pipeline must keep the hot frames untouched.
    Idempotent — a slot already archived today is skipped, so re-running each cycle
    is cheap. OFF unless ARCHIVE_CAPTURES; skips if the SD is low on free space.

    Returns: number of stills newly archived this call.
    """
    ram_mode = is_ram_mode(capture_dir)
    hot_dir = os.path.join(capture_dir, 'hot', 'captures') if ram_mode else os.path.join(capture_dir, 'captures')
    if not os.path.isdir(hot_dir):
        return 0

    free_pct = _cold_free_percent(capture_dir)
    if free_pct is not None and free_pct < ARCHIVE_CAPTURES_MIN_FREE_PCT:
        logger.warning(f"captures: skip archiving — cold free {free_pct:.1f}% < {ARCHIVE_CAPTURES_MIN_FREE_PCT}%")
        return 0

    MIN_AGE_SECONDS = 30          # never archive frames mid-write (matches archive_hot_files)
    now = time.time()
    interval = 1.0 / fps if fps and fps > 0 else 1.0
    seen_slots = set()
    archived = 0
    try:
        files = []
        with os.scandir(hot_dir) as it:
            for entry in it:
                name = entry.name
                if (entry.is_file(follow_symlinks=False) and name.startswith('capture_')
                        and name.endswith('.jpg') and 'thumbnail' not in name):
                    try:
                        mtime = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    if now - mtime >= MIN_AGE_SECONDS:
                        files.append((entry.path, mtime))
        files.sort(key=lambda x: x[1])   # chronological, so the first frame per slot wins

        for path, mtime in files:
            dt = datetime.fromtimestamp(mtime)
            seconds_today = dt.hour * 3600 + dt.minute * 60 + dt.second
            slot = int(seconds_today / interval)
            if slot in seen_slots:
                continue
            seen_slots.add(slot)
            seq = seconds_today * CAPTURE_SEQ_FPS    # 5fps sequence space (metadata-aligned)
            hour_folder = os.path.join(capture_dir, 'captures', str(dt.hour))
            dest = os.path.join(hour_folder, f'capture_{seq:06d}.jpg')
            # Skip if this slot was already archived today (cheap idempotency); the
            # 24h rollover is handled by cleanup_cold_captures (>26h) + overwrite below.
            if os.path.exists(dest):
                try:
                    if now - os.path.getmtime(dest) < 23 * 3600:
                        continue
                except OSError:
                    pass
            try:
                os.makedirs(hour_folder, exist_ok=True)
                shutil.copy2(path, dest + '.tmp')
                os.replace(dest + '.tmp', dest)   # atomic — never serve a half-written JPEG
                archived += 1
            except Exception as e:
                logger.warning(f"captures: archive copy failed {os.path.basename(path)} → {dest}: {e}")
                try:
                    os.remove(dest + '.tmp')
                except OSError:
                    pass

        if archived:
            logger.info(f"captures:  Archived {archived} stills → cold (fps={fps}, free={free_pct if free_pct is None else round(free_pct,1)}%)")
        return archived

    except Exception as e:
        logger.error(f"Error archiving captures: {e}")
        return 0


def clean_old_thumbnails(capture_dir: str) -> int:
    """
    Clean old thumbnails from /hot/thumbnails/ directory - keep only newest 100 files.
    
    Thumbnails are generated by FFmpeg at same rate as captures (5fps v4l2, 2fps VNC).
    We keep a small buffer (100 files = ~3MB) for freeze detection comparisons.
    Old thumbnails are deleted to save RAM.
    
    Returns: Number of files deleted
    """
    return cleanup_hot_files(capture_dir, 'thumbnails', 'capture_*_thumbnail.jpg')


def cleanup_stale_files(
    base_dir: str,
    pattern: str,
    max_age_seconds: int,
    batch_limit: Optional[int] = None,
    root_only: bool = False,
    subdirs_only: bool = False,
    label: str = "Cold cleanup",
) -> int:
    """
    Delete files matching pattern older than max_age_seconds.

    Scope:
    - root_only=True: only files directly in base_dir
    - subdirs_only=True: only files in nested folders below base_dir
    - default: all files under base_dir (recursive)
    """
    import fnmatch

    if root_only and subdirs_only:
        raise ValueError("root_only and subdirs_only cannot both be True")

    if not os.path.isdir(base_dir):
        return 0

    now = time.time()
    old_files: List[Tuple[float, str]] = []  # (age, path)

    try:
        if root_only:
            # Fast path: os.scandir for root-only (avoids Path.glob + stat overhead on huge dirs)
            try:
                with os.scandir(base_dir) as it:
                    for entry in it:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if not fnmatch.fnmatch(entry.name, pattern):
                            continue
                        try:
                            age = now - entry.stat(follow_symlinks=False).st_mtime
                        except OSError:
                            continue
                        if age > max_age_seconds:
                            old_files.append((age, entry.path))
            except OSError as e:
                logger.error(f"{Colors.BLUE}{label}: scandir failed: {e}{Colors.RESET}")
                return 0
        else:
            # Recursive path: walk subdirs
            base_path = Path(base_dir)
            for f in base_path.rglob(pattern):
                if not f.is_file():
                    continue
                if subdirs_only and f.parent == base_path:
                    continue
                try:
                    age = now - f.stat().st_mtime
                except OSError:
                    continue
                if age > max_age_seconds:
                    old_files.append((age, str(f)))

        total_old = len(old_files)

        if total_old == 0:
            return 0

        # Sort oldest first (highest age) and apply batch limit
        old_files.sort(key=lambda x: x[0], reverse=True)

        if batch_limit and total_old > batch_limit:
            old_files = old_files[:batch_limit]
            logger.info(f"{Colors.BLUE}{label}: Batching {batch_limit} of {total_old} old files{Colors.RESET}")

        deleted = 0
        for _, path in old_files:
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass

        if deleted > 0:
            logger.info(f"{Colors.BLUE}{label}: Deleted {deleted} files older than {max_age_seconds}s{Colors.RESET}")

        return deleted

    except Exception as e:
        logger.error(f"{Colors.BLUE}{label}: Error during cleanup: {e}{Colors.RESET}")
        return 0


def cleanup_cold_captures(capture_dir: str, batch_limit: Optional[int] = None) -> int:
    """
    Cleanup stale capture files in root and archived subfolders.
    
    Args:
        capture_dir: Base capture directory
        batch_limit: Max files to delete (prevents long-running cycles)
    
    Returns: Number of files deleted
    """
    captures_dir = os.path.join(capture_dir, 'captures')
    deleted_root = cleanup_stale_files(
        captures_dir,
        'capture_*.jpg',
        ROOT_STALE_MAX_AGE_SECONDS,
        batch_limit,
        root_only=True,
        label="Cold captures(root)",
    )
    deleted_archive = cleanup_stale_files(
        captures_dir,
        'capture_*.jpg',
        ARCHIVE_STALE_MAX_AGE_SECONDS,
        batch_limit,
        subdirs_only=True,
        label="Cold captures(archive)",
    )
    return deleted_root + deleted_archive


def cleanup_cold_thumbnails(capture_dir: str, batch_limit: Optional[int] = None) -> int:
    """
    Delete thumbnails from cold root older than 1 HOUR (matches captures retention)
    
    Args:
        capture_dir: Base capture directory
        batch_limit: Max files to delete (prevents long-running cycles)
    
    Returns: Number of files deleted
    """
    thumbs_dir = os.path.join(capture_dir, 'thumbnails')
    deleted_root = cleanup_stale_files(
        thumbs_dir,
        'capture_*_thumbnail.jpg',
        ROOT_STALE_MAX_AGE_SECONDS,
        batch_limit,
        root_only=True,
        label="Cold thumbnails(root)",
    )
    deleted_archive = cleanup_stale_files(
        thumbs_dir,
        'capture_*_thumbnail.jpg',
        ARCHIVE_STALE_MAX_AGE_SECONDS,
        batch_limit,
        subdirs_only=True,
        label="Cold thumbnails(archive)",
    )
    return deleted_root + deleted_archive


def cleanup_cold_segments(capture_dir: str, batch_limit: Optional[int] = None) -> int:
    """
    Cleanup stale segment files in root and archived subfolders.
    """
    segments_dir = os.path.join(capture_dir, 'segments')
    deleted_root = cleanup_stale_files(
        segments_dir,
        'segment_*.ts',
        ROOT_STALE_MAX_AGE_SECONDS,
        batch_limit,
        root_only=True,
        label="Cold segments(root)",
    )
    deleted_archive = cleanup_stale_files(
        segments_dir,
        'chunk_10min_*.mp4',
        ARCHIVE_STALE_MAX_AGE_SECONDS,
        batch_limit,
        subdirs_only=True,
        label="Cold segments(archive)",
    )
    return deleted_root + deleted_archive


def cleanup_cold_metadata(capture_dir: str, batch_limit: Optional[int] = None) -> int:
    """
    Delete stale root metadata files older than 1 HOUR.

    This applies to both RAM and SD modes because metadata producers can leave
    old capture_*.json files in the root metadata folder when pipelines stall.

    Args:
        capture_dir: Base capture directory
        batch_limit: Max files to delete (prevents long-running cycles)

    Returns: Number of files deleted
    """
    metadata_dir = os.path.join(capture_dir, 'metadata')
    deleted_root = cleanup_stale_files(
        metadata_dir,
        'capture_*.json',
        ROOT_STALE_MAX_AGE_SECONDS,
        batch_limit,
        root_only=True,
        label="Cold metadata(root)",
    )
    deleted_archive = cleanup_stale_files(
        metadata_dir,
        'chunk_10min_*.json',
        ARCHIVE_STALE_MAX_AGE_SECONDS,
        batch_limit,
        subdirs_only=True,
        label="Cold metadata(archive)",
    )
    return deleted_root + deleted_archive


def _delete_stale_recursive(base_dir: str, max_age_seconds: float, label: str) -> int:
    """Delete files under base_dir older than max_age_seconds, recursively (content is
    written into per-run subfolders — a flat glob('*') never reaches nested files), then
    prune subfolders left empty by those deletions (bottom-up)."""
    deleted = 0
    now = time.time()
    if not os.path.isdir(base_dir):
        return 0
    try:
        for f in Path(base_dir).rglob('*'):
            if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
                os.remove(str(f))
                deleted += 1
        for d in sorted(Path(base_dir).rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass  # not empty — still has non-stale files
    except Exception as e:
        logger.error(f"Error cleaning {label}: {e}")
    if deleted > 0:
        logger.info(f"{label}: Deleted {deleted} files older than {max_age_seconds / 86400:.0f}d")
    return deleted


def cleanup_verification_results(capture_dir: str) -> int:
    """Delete verification results older than 24h."""
    verif_dir = os.path.join(capture_dir, 'captures', 'verification_results')
    return _delete_stale_recursive(verif_dir, 86400, "Verification")


def cleanup_reports(capture_dir: str) -> int:
    """Delete local report artifacts (HTML + embedded assets) older than 30 days.
    Mirrors the script-reports/ 30-day MinIO ILM rule (setup/local/linux/storage) —
    these are never uploaded themselves (only the images they reference are), so
    without this they accumulated on local disk forever."""
    reports_dir = os.path.join(capture_dir, 'reports')
    return _delete_stale_recursive(reports_dir, REPORTS_MAX_AGE_SECONDS, "Reports")


# Report artifacts written directly into the capture ROOT by verification and KPI
# runs. They are not under reports/, not under a hot subdir, and do not match any
# per-type rotation pattern, so before this nothing ever deleted them: vpt-pi1 had
# 5105 original_with_crop_*.png (1.8 GB) dating back to May, plus 2462 stray
# verification_failure_*.html. Matched by explicit prefix so the sweep can never
# touch config, manifests or test_video.mp4 sitting in the same directory.
CAPTURE_ROOT_ARTIFACT_PREFIXES = (
    'original_with_crop_',
    'verification_failure_',
    'kpi_failure_',
)


def cleanup_capture_root_artifacts(capture_dir: str) -> int:
    """Delete stale verification/KPI artifacts left loose in the capture root.

    Non-recursive and prefix-scoped by design — reports/ has its own sweep
    (cleanup_reports) and the hot subdirs have theirs (sweep_stale_hot_files).
    Shares the 30-day reports retention: these are the same class of artifact,
    referenced by the same HTML reports.
    """
    cutoff = time.time() - REPORTS_MAX_AGE_SECONDS
    deleted = 0
    try:
        with os.scandir(capture_dir) as it:
            for entry in it:
                if not entry.name.startswith(CAPTURE_ROOT_ARTIFACT_PREFIXES):
                    continue
                try:
                    if entry.is_file(follow_symlinks=False) and \
                            entry.stat(follow_symlinks=False).st_mtime < cutoff:
                        os.remove(entry.path)
                        deleted += 1
                except OSError:
                    pass
    except OSError as e:
        logger.error(f"Error cleaning capture root artifacts in {capture_dir}: {e}")
    if deleted:
        logger.info(f"Capture root: Deleted {deleted} stale artifacts older than {REPORTS_MAX_AGE_SECONDS / 86400:.0f}d")
    return deleted


def merge_metadata_batch(source_dir: str, pattern: str, output_path: Optional[str], batch_size: int, fps: int = 5, is_final: bool = False, capture_dir: Optional[str] = None) -> bool:
    """
    Merge metadata files into batches (mirrors merge_progressive_batch for MP4)
    Progressive grouping: individual JSONs  1min  10min chunks
    
    Args:
        source_dir: Directory with source metadata files
        pattern: File pattern to match ('capture_*.json' or '1min_*.json')
        output_path: Output file path (or None if is_final=True)
        batch_size: Number of items to batch (60 for 1min, 10 for 10min)
        fps: Frames per second (for calculating time ranges, default 5)
        is_final: If True, save to hour folder as chunk_10min_X.json
        capture_dir: Required if is_final=True
    
    Returns:
        bool: True if batch was created
    """
    import json
    
    # Find source files
    files = sorted(Path(source_dir).glob(pattern))
    
    if not files:
        return False
    
    # Calculate required files for batch
    if pattern == 'capture_*.json':
        # Individual files: batch_size is in seconds
        # e.g., 600 seconds * 5fps = 3000 files for 10 minutes
        required = batch_size * fps
    else:  # '1min_*.json' (legacy, not used anymore)
        # Need 10 files for 10 minutes
        required = batch_size
    
    if len(files) < required:
        return False
    
    # Take oldest files for batching
    batch_files = files[:required]
    
    try:
        # Aggregate data
        all_frames = []
        for file_path in batch_files:
            # Skip empty files
            if file_path.stat().st_size == 0:
                logger.warning(f"Skipping empty file: {file_path}")
                continue
            
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping corrupted JSON file {file_path}: {e}")
                continue
            
            if 'frames' in data:
                # Already aggregated (1min file)
                all_frames.extend(data['frames'])
            else:
                # Individual frame file
                sequence_match = file_path.stem.replace('capture_', '')
                sequence = int(sequence_match)
                all_frames.append({
                    'sequence': sequence,
                    'timestamp': data.get('timestamp'),
                    'filename': data.get('filename'),
                    'blackscreen': data.get('blackscreen', False),
                    'blackscreen_percentage': data.get('blackscreen_percentage', 0),
                    'freeze': data.get('freeze', False),
                    'freeze_diffs': data.get('freeze_diffs', []),
                    'audio': data.get('audio', True),
                    'volume_percentage': data.get('volume_percentage', 0),
                    'mean_volume_db': data.get('mean_volume_db', -100.0),
                    # Per-frame Localize verdict (identify_screen out), so the AVQ Frames
                    # inspector can show the SELECTED frame's screen — same field the live
                    # overlay reads. Omitted/None when Localize is disabled for the device.
                    'localize': data.get('localize'),
                })
        
        if not all_frames:
            return False
        
        # Sort by sequence
        all_frames.sort(key=lambda x: x['sequence'])
        
        # Calculate time range and chunk position
        first_seq = all_frames[0]['sequence']
        last_seq = all_frames[-1]['sequence']
        
        # Determine output path
        if is_final:
            # Save to hour folder as chunk_10min_X.json
            hour = (first_seq // (3600 * fps)) % 24
            chunk_index = ((first_seq % (3600 * fps)) // (600 * fps))  # 0-5
            
            hour_dir = os.path.join(capture_dir, 'metadata', str(hour))
            os.makedirs(hour_dir, exist_ok=True)
            
            output_path = os.path.join(hour_dir, f'chunk_10min_{chunk_index}.json')
        
        # Create output structure
        output_data = {
            'frames_count': len(all_frames),
            'frames': all_frames
        }
        
        if is_final:
            hour = (first_seq // (3600 * fps)) % 24
            chunk_index = ((first_seq % (3600 * fps)) // (600 * fps))
            output_data.update({
                'hour': hour,
                'chunk_index': chunk_index,
                'start_time': all_frames[0]['timestamp'],
                'end_time': all_frames[-1]['timestamp']
            })
        
        # Atomic write
        try:
            # Ensure parent directory exists (critical for temp files)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path + '.tmp', 'w') as f:
                json.dump(output_data, f, indent=2)
            os.replace(output_path + '.tmp', output_path)
        except Exception as e:
            logger.error(f"Metadata merge write/rename failed: {e}")
            # Clean up temp file if it exists
            try:
                os.remove(output_path + '.tmp')
            except:
                pass
            return False
        
        # Delete source files (including empty/corrupted ones)
        for file_path in batch_files:
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error merging metadata batch: {e}")
        return False


def rebuild_archive_manifest_from_disk(capture_dir: str) -> dict:
    """
    Scan hour directories and rebuild manifest with ALL available chunks from last 24h.
    
    Returns all chunks regardless of gaps - frontend will grey out missing chunks.
    This allows users to access any archived content even with recording gaps.
    
    Returns: Manifest dict with all chunks found on disk
    """
    import json
    
    segments_dir = os.path.join(capture_dir, 'segments')
    
    if not os.path.isdir(segments_dir):
        return {"chunks": [], "last_updated": None, "available_hours": [], "total_chunks": 0}
    
    # Build list of all existing chunks from all hour directories
    all_chunks = []
    
    for hour in range(24):
        hour_dir = os.path.join(segments_dir, str(hour))
        if not os.path.isdir(hour_dir):
            continue
        
        for mp4_file in Path(hour_dir).glob('chunk_10min_*.mp4'):
            try:
                chunk_index = int(mp4_file.stem.replace('chunk_10min_', ''))
                mp4_stat = mp4_file.stat()
                
                metadata_path = os.path.join(capture_dir, 'metadata', str(hour), f'chunk_10min_{chunk_index}.json')
                has_metadata = os.path.exists(metadata_path)
                
                chunk_info = {
                    "hour": hour,
                    "chunk_index": chunk_index,
                    "name": mp4_file.name,
                    "size": mp4_stat.st_size,
                    "created": mp4_stat.st_mtime,
                    "has_metadata": has_metadata
                }
                
                if has_metadata:
                    try:
                        with open(metadata_path) as f:
                            meta = json.load(f)
                        chunk_info.update({
                            "start_time": meta.get("start_time"),
                            "end_time": meta.get("end_time"),
                            "frames_count": meta.get("frames_count")
                        })
                    except:
                        pass
                
                all_chunks.append(chunk_info)
                
            except Exception as e:
                logger.warning(f"Error processing chunk file {mp4_file}: {e}")
    
    if not all_chunks:
        return {"chunks": [], "last_updated": None, "available_hours": [], "total_chunks": 0}
    
    # Sort chunks chronologically (by hour, then chunk_index)
    all_chunks.sort(key=lambda x: (x["hour"], x["chunk_index"]))
    
    manifest = {
        "chunks": all_chunks,
        "last_updated": time.time(),
        "available_hours": sorted(list(set(c["hour"] for c in all_chunks))),
        "total_chunks": len(all_chunks)
    }
    
    return manifest


def rebuild_manifest_from_disk(capture_dir: str, manifest_type: str) -> dict:
    """
    Generic manifest builder for both archive and transcript chunks.
    
    Args:
        capture_dir: Base capture directory
        manifest_type: 'archive' or 'transcript'
    
    Returns: Manifest dict with all chunks found on disk
    """
    import json
    
    if manifest_type == 'archive':
        base_dir = os.path.join(capture_dir, 'segments')
        file_pattern = 'chunk_10min_*.mp4'
        metadata_dir = os.path.join(capture_dir, 'metadata')
    else:  # transcript
        base_dir = os.path.join(capture_dir, 'transcript')
        file_pattern = 'chunk_10min_*.json'
        metadata_dir = None
    
    if not os.path.isdir(base_dir):
        return {"chunks": [], "last_updated": None, "available_hours": [], "total_chunks": 0}
    
    all_chunks = []
    
    for hour in range(24):
        hour_dir = os.path.join(base_dir, str(hour))
        if not os.path.isdir(hour_dir):
            continue
        
        for chunk_file in Path(hour_dir).glob(file_pattern):
            try:
                # Skip language-specific files (chunk_10min_0_fr.json, chunk_10min_0_de.json, etc.)
                # Only process base chunk files (chunk_10min_0.json)
                stem = chunk_file.stem.replace('chunk_10min_', '')
                if '_' in stem:
                    # This is a language-specific file (e.g., "0_fr"), skip it
                    continue
                
                chunk_index = int(stem)
                file_stat = chunk_file.stat()
                
                chunk_info = {
                    "hour": hour,
                    "chunk_index": chunk_index,
                    "name": chunk_file.name,
                    "size": file_stat.st_size,
                    "created": file_stat.st_mtime,
                }
                
                # Add type-specific metadata
                if manifest_type == 'archive' and metadata_dir:
                    metadata_path = os.path.join(metadata_dir, str(hour), f'chunk_10min_{chunk_index}.json')
                    chunk_info["has_metadata"] = os.path.exists(metadata_path)
                    if os.path.exists(metadata_path):
                        try:
                            with open(metadata_path) as f:
                                meta = json.load(f)
                            chunk_info.update({
                                "start_time": meta.get("start_time"),
                                "end_time": meta.get("end_time"),
                                "frames_count": meta.get("frames_count")
                            })
                        except:
                            pass
                elif manifest_type == 'transcript':
                    try:
                        with open(chunk_file) as f:
                            data = json.load(f)
                        segments = data.get("segments", []) or []
                        segment_count = len(segments)
                        segment_start = None
                        segment_end = None
                        segment_coverage_seconds = 0.0
                        if segment_count > 0:
                            segment_start = min(s.get("start", 0) for s in segments)
                            segment_end = max(s.get("end", 0) for s in segments)
                            for seg in segments:
                                seg_start = seg.get("start", 0) or 0
                                seg_end = seg.get("end", 0) or 0
                                if seg_end > seg_start:
                                    segment_coverage_seconds += (seg_end - seg_start)
                        chunk_info.update({
                            "language": data.get("language", "unknown"),
                            "confidence": data.get("confidence", 0.0),
                            "has_transcript": bool(data.get("transcript", "").strip()),
                            "timestamp": data.get("timestamp"),
                            "segment_count": segment_count,
                            "has_timed_segments": segment_count > 0,
                            "segment_start": segment_start,
                            "segment_end": segment_end,
                            "segment_coverage_seconds": round(segment_coverage_seconds, 3),
                        })
                        
                        # Check if corresponding MP3 exists in same hour folder
                        # No timestamp comparison needed - hour folder matching ensures they belong together
                        # (24h rolling buffer automatically overwrites old files in same hour/chunk slot)
                        device_folder = os.path.basename(capture_dir)
                        from shared.src.lib.utils.storage_path_utils import get_audio_path
                        audio_base = get_audio_path(device_folder)
                        audio_path = os.path.join(audio_base, str(hour), f'chunk_10min_{chunk_index}.mp3')
                        
                        has_mp3 = os.path.exists(audio_path)
                        
                        chunk_info["has_mp3"] = has_mp3
                        if has_mp3:
                            try:
                                chunk_info["audio_mtime"] = os.path.getmtime(audio_path)
                            except:
                                pass
                        if not has_mp3:
                            chunk_info["unavailable_since"] = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                    except:
                        pass
                
                all_chunks.append(chunk_info)
                
            except Exception as e:
                logger.warning(f"Error processing {manifest_type} file {chunk_file}: {e}")
    
    if not all_chunks:
        return {"chunks": [], "last_updated": None, "available_hours": [], "total_chunks": 0}
    
    all_chunks.sort(key=lambda x: (x["hour"], x["chunk_index"]))
    
    return {
        "chunks": all_chunks,
        "last_updated": time.time(),
        "available_hours": sorted(list(set(c["hour"] for c in all_chunks))),
        "total_chunks": len(all_chunks)
    }


def rebuild_archive_manifest_from_disk(capture_dir: str) -> dict:
    """Rebuild archive manifest - wrapper for generic function"""
    return rebuild_manifest_from_disk(capture_dir, 'archive')


def rebuild_transcript_manifest_from_disk(capture_dir: str) -> dict:
    """Rebuild transcript manifest - wrapper for generic function"""
    return rebuild_manifest_from_disk(capture_dir, 'transcript')


def update_manifest(capture_dir: str, hour: int, chunk_index: int, chunk_path: str, manifest_type: str, has_mp3: bool = True):
    """
    Generic manifest updater for both archive and transcript chunks.
    
    Args:
        capture_dir: Base capture directory
        hour: Hour (0-23)
        chunk_index: Chunk index (0-5)
        chunk_path: Path to chunk file
        manifest_type: 'archive' or 'transcript'
        has_mp3: Whether corresponding MP3 exists (transcript only)
    """
    import json
    
    if manifest_type == 'archive':
        manifest_path = os.path.join(capture_dir, 'segments', 'archive_manifest.json')
    else:  # transcript
        manifest_path = os.path.join(capture_dir, 'transcript', 'transcript_manifest.json')
    
    # Load existing manifest
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except:
            manifest = {"chunks": [], "last_updated": None}
    else:
        manifest = {"chunks": [], "last_updated": None}
    
    file_stat = Path(chunk_path).stat()
    chunk_info = {
        "hour": hour,
        "chunk_index": chunk_index,
        "name": os.path.basename(chunk_path),
        "size": file_stat.st_size,
        "created": file_stat.st_mtime,
    }
    
    # Add type-specific metadata
    if manifest_type == 'archive':
        metadata_path = os.path.join(capture_dir, 'metadata', str(hour), f'chunk_10min_{chunk_index}.json')
        chunk_info["has_metadata"] = os.path.exists(metadata_path)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path) as f:
                    meta = json.load(f)
                chunk_info.update({
                    "start_time": meta.get("start_time"),
                    "end_time": meta.get("end_time"),
                    "frames_count": meta.get("frames_count")
                })
            except:
                pass
    elif manifest_type == 'transcript':
        # Validate MP3 existence in same hour folder
        # No timestamp comparison needed - hour folder matching ensures they belong together
        # (24h rolling buffer automatically overwrites old files in same hour/chunk slot)
        device_folder = os.path.basename(capture_dir)
        from shared.src.lib.utils.storage_path_utils import get_audio_path
        audio_base = get_audio_path(device_folder)
        audio_path = os.path.join(audio_base, str(hour), f'chunk_10min_{chunk_index}.mp3')
        
        has_mp3_validated = os.path.exists(audio_path)
        
        chunk_info["has_mp3"] = has_mp3_validated
        if has_mp3_validated:
            try:
                chunk_info["audio_mtime"] = os.path.getmtime(audio_path)
            except:
                pass
        if not has_mp3_validated:
            chunk_info["unavailable_since"] = datetime.now().isoformat()
        
        try:
            with open(chunk_path) as f:
                data = json.load(f)
            segments = data.get("segments", []) or []
            segment_count = len(segments)
            segment_start = None
            segment_end = None
            segment_coverage_seconds = 0.0
            if segment_count > 0:
                segment_start = min(s.get("start", 0) for s in segments)
                segment_end = max(s.get("end", 0) for s in segments)
                for seg in segments:
                    seg_start = seg.get("start", 0) or 0
                    seg_end = seg.get("end", 0) or 0
                    if seg_end > seg_start:
                        segment_coverage_seconds += (seg_end - seg_start)
            
            # Include full transcript data in manifest (optimization: 1 call instead of 2)
            chunk_info.update({
                "language": data.get("language", "unknown"),
                "confidence": data.get("confidence", 0.0),
                "has_transcript": bool(data.get("transcript", "").strip()),
                "timestamp": data.get("timestamp"),
                "transcript": data.get("transcript", ""),  # Full transcript text
                "segments": segments,  # Timed segments for subtitles
                "transcription_time_seconds": data.get("transcription_time_seconds", 0),
                "mp3_file": data.get("mp3_file", ""),
                "segment_count": segment_count,
                "has_timed_segments": segment_count > 0,
                "segment_start": segment_start,
                "segment_end": segment_end,
                "segment_coverage_seconds": round(segment_coverage_seconds, 3),
            })
            
            # Check for pre-translated language files
            available_languages = ['original']  # Original language is always available
            available_dubbed_languages = []  # Dubbed audio files
            
            chunk_dir = os.path.dirname(chunk_path)
            chunk_basename = os.path.basename(chunk_path).replace('.json', '')
            
            # Check for language-specific transcript files
            # If transcript exists for a language, dubbed audio can be generated on-demand
            for lang_code in ['fr', 'en', 'es', 'de', 'it']:
                # Check transcript file
                lang_file = os.path.join(chunk_dir, f'{chunk_basename}_{lang_code}.json')
                if os.path.exists(lang_file):
                    available_languages.append(lang_code)
                    # If transcript exists, audio can be dubbed on-demand
                    available_dubbed_languages.append(lang_code)
            
            chunk_info["available_languages"] = available_languages
            chunk_info["available_dubbed_languages"] = available_dubbed_languages
            
            logger.debug(f"Transcript manifest updated: {chunk_basename} - languages={available_languages}, dubbed={available_dubbed_languages}, transcript_chars={len(data.get('transcript', ''))}")
        except Exception as e:
            logger.error(f"Error updating transcript manifest for {chunk_path}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Set defaults on error
            chunk_info["available_languages"] = ['original']
            chunk_info["available_dubbed_languages"] = []
    
    # Update manifest: replace current chunk entry
    manifest["chunks"] = [c for c in manifest["chunks"] if not (c["hour"] == hour and c["chunk_index"] == chunk_index)]
    manifest["chunks"].append(chunk_info)

    # Prune stale entries whose files no longer exist on disk
    # This prevents the manifest from referencing deleted files (e.g. after 24h rollover)
    if manifest_type == 'archive':
        base_dir = os.path.join(capture_dir, 'segments')
    else:
        base_dir = os.path.join(capture_dir, 'transcript')

    before_count = len(manifest["chunks"])
    manifest["chunks"] = [
        c for c in manifest["chunks"]
        if os.path.exists(os.path.join(base_dir, str(c["hour"]), c["name"]))
    ]
    pruned = before_count - len(manifest["chunks"])
    if pruned > 0:
        logger.info(f"Pruned {pruned} stale entries from {manifest_type} manifest (files no longer on disk)")

    manifest["chunks"].sort(key=lambda x: (x["hour"], x["chunk_index"]))
    manifest["last_updated"] = time.time()
    manifest["available_hours"] = sorted(list(set(c["hour"] for c in manifest["chunks"])))
    manifest["total_chunks"] = len(manifest["chunks"])
    
    # Save atomically
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path + '.tmp', 'w') as f:
        json.dump(manifest, f, indent=2)
    os.replace(manifest_path + '.tmp', manifest_path)
    
    logger.info(f"Updated {manifest_type} manifest: {manifest['total_chunks']} chunks across {len(manifest['available_hours'])} hours")


def update_archive_manifest(capture_dir: str, hour: int, chunk_index: int, mp4_path: str):
    """Update archive manifest - wrapper for generic function"""
    update_manifest(capture_dir, hour, chunk_index, mp4_path, 'archive')


def update_transcript_manifest(capture_dir: str, hour: int, chunk_index: int, transcript_path: str, has_mp3: bool = True):
    """Update transcript manifest - wrapper for generic function"""
    update_manifest(capture_dir, hour, chunk_index, transcript_path, 'transcript', has_mp3=has_mp3)


def cleanup_temp_files(capture_dir: str) -> Tuple[int, int, int]:
    """
    Safety cleanup for temp/ directories - delete orphaned 1min files.
    
    Why this is needed:
    - 1min MP4: Rotating slots (0-9) auto-overwrite, NO cleanup needed!
    - 1min JSON: Delete after 2 hours (if 10min merging fails repeatedly)
    - 1min MP3: Rotating slots (0-9) auto-overwrite, light cleanup as safety net
    - Prevents disk exhaustion from orphaned temp files
    
    Returns: (segments_deleted, metadata_deleted, mp3_deleted)
    """
    import time
    
    segments_deleted = 0
    metadata_deleted = 0
    mp3_deleted = 0
    now = time.time()
    max_age_seconds = 7200  # 2 hours for JSON
    max_age_mp3_seconds = 900  # 15 minutes for MP3 (rotating slots should handle @ 10min)
    
    # Cleanup segments temp directory
    # NOTE: 1min MP4s use rotating slots (0-9) and auto-overwrite - NO cleanup needed!
    # They remain playable individually until overwritten (~10 minutes)
    segments_temp = os.path.join(capture_dir, 'segments', 'temp')
    if os.path.isdir(segments_temp):
        # SKIP 1min_*.mp4 files - they use rotating slots and shouldn't be deleted
        logger.debug(f"Skipping cleanup of 1min MP4s (rotating slot system - last 10 files kept)")
        
        # Only cleanup if there are non-rotating files (shouldn't happen, but safety net)
        try:
            pass  # No cleanup needed for rotating slot MP4s
        except Exception as e:
            logger.error(f"Error scanning segments temp directory: {e}")
    
    # Cleanup metadata temp directory
    metadata_temp = os.path.join(capture_dir, 'metadata', 'temp')
    if os.path.isdir(metadata_temp):
        try:
            for f in Path(metadata_temp).glob('1min_*.json'):
                if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
                    try:
                        os.remove(str(f))
                        metadata_deleted += 1
                    except Exception as e:
                        logger.error(f"Error deleting old temp metadata {f}: {e}")
        except Exception as e:
            logger.error(f"Error scanning metadata temp directory: {e}")
    
    # Cleanup audio temp directory (1min MP3s with rotating slots)
    # Rotating slots (0-9) should auto-delete old files, but this is a safety net
    device_folder = os.path.basename(capture_dir)
    from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
    audio_cold = get_cold_storage_path(device_folder, 'audio')
    audio_temp = os.path.join(audio_cold, 'temp')
    
    if os.path.isdir(audio_temp):
        try:
            for f in Path(audio_temp).glob('1min_*.mp3'):
                if f.is_file():
                    file_age = now - f.stat().st_mtime
                    if file_age > max_age_mp3_seconds:
                        try:
                            os.remove(str(f))
                            mp3_deleted += 1
                            logger.warning(f"Safety cleanup: Deleted stuck 1min MP3 ({file_age:.0f}s old): {f.name}")
                        except Exception as e:
                            logger.error(f"Error deleting old temp MP3 {f}: {e}")
        except Exception as e:
            logger.error(f"Error scanning audio temp directory: {e}")
    
    if segments_deleted > 0 or metadata_deleted > 0 or mp3_deleted > 0:
        logger.info(f"Temp cleanup: Deleted {segments_deleted} old segments (>2h), {metadata_deleted} old metadata (>2h), {mp3_deleted} old MP3s (>15min)")
    
    return segments_deleted, metadata_deleted, mp3_deleted


def process_hot_storage(capture_dir: str):
    """
    HOT STORAGE PROCESSING (Fast, Critical, Every 15s)
    
    1. SAFETY CLEANUP: Delete old files from HOT storage (prevent RAM exhaustion)
       - Segments: Keep 200 newest (safety net - FFmpeg normally auto-deletes @ 150)
       - Captures: Keep 300 newest (deleted, uploaded to R2 when needed)
       - Thumbnails: Keep 100 newest (deleted, local freeze detection only)
       - Metadata: Keep 750 newest (individual JSONs, archived incrementally by capture_monitor)
    2. Progressive MP4 building: HOT TS  1min MP4  append to growing 10min chunk in COLD
    3. Audio extraction: COLD 10min MP4  direct to COLD /audio/{hour}/
    
    Progressive append: Same chunk URL grows from 1min to 10min (no timeline changes)
    """
    ram_mode = is_ram_mode(capture_dir)
    mode_label = "RAM (hot)" if ram_mode else "SD (cold)"
    logger.info(f" FAST LOOP ({mode_label}): {os.path.basename(capture_dir)}")
    
    start_time = time.time()
    
    # SAFETY CLEANUP: Apply in both modes.
    # cleanup_hot_files() resolves to /hot/* in RAM mode and root folders in SD mode.
    # Segments are primarily handled by FFmpeg; this is an additional safety net.
    deleted_segments = cleanup_hot_files(capture_dir, 'segments', 'segment_*.ts')
    # Optionally archive sampled full-res stills to cold (24h) for the AVQ frame
    # inspector — BEFORE rotate_hot_captures deletes them from the hot RAM buffer.
    if ARCHIVE_CAPTURES:
        archive_captures(capture_dir, ARCHIVE_CAPTURES_FPS)
    deleted_captures = rotate_hot_captures(capture_dir)
    deleted_thumbnails = clean_old_thumbnails(capture_dir)
    deleted_metadata = cleanup_hot_files(capture_dir, 'metadata', 'capture_*.json')
    sweep_stale_hot_files(capture_dir)  # catch-all for filenames the rotations above can't see
    # Note: Cold cleanup moved to separate thread
    # Note: Audio extracted directly to COLD - no hot cleanup needed
    
    if not ram_mode:
        logger.info(f" SD mode detected for {capture_dir} (no /hot). Using cold folders directly for archiving.")
    
    # METADATA ARCHIVAL: Handled by capture_monitor.py (incremental append)
    # Chunks are created/updated in real-time as frames arrive - no batch merging needed!
    
    # SEGMENTS PROGRESSIVE BUILDING: TS  1min MP4  append to growing 10min chunk
    hot_segments = os.path.join(capture_dir, 'hot', 'segments') if ram_mode else os.path.join(capture_dir, 'segments')
    logger.info(f" Segment source: {hot_segments}")
    if not os.path.isdir(hot_segments):
        logger.warning(f" Segments folder not found: {hot_segments}")
        return
    temp_dir = os.path.join(capture_dir, 'segments', 'temp')
    if not os.path.isdir(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f" Created temp dir: {temp_dir}")
    
    # Step 1: Merge 60 TS  1min MP4 (with rotating slot naming for individual playback)
    # Calculate minute slot (0-9) for rotating filenames - same as MP3
    current_minute = datetime.now().minute
    minute_slot = current_minute % 10  # 0-9 rotating slot
    
    # Use rotating slot naming instead of timestamp - keeps last 10 files playable
    mp4_1min_path = os.path.join(temp_dir, f'1min_{minute_slot}.mp4')
    
    # Delete old file in this slot BEFORE creating new one (prevents race condition)
    if os.path.exists(mp4_1min_path):
        try:
            os.remove(mp4_1min_path)
            logger.debug(f"Deleted old 1min_{minute_slot}.mp4 (rotating slot)")
        except Exception as e:
            logger.warning(f"Failed to delete old 1min MP4 slot: {e}")
    
    mp4_start = time.time()
    # Quick visibility: count available segments before merge
    try:
        segment_count = len(list(Path(hot_segments).glob('segment_*.ts')))
        logger.info(f" Segments available: {segment_count}")
    except Exception:
        segment_count = None

    # Determine how many segments make ~60s (prefer real m3u8 durations over device model)
    from shared.src.lib.utils.storage_path_utils import get_device_segment_duration
    device_folder = os.path.basename(capture_dir)
    segment_duration = None
    m3u8_path = os.path.join(hot_segments, 'output.m3u8')
    if os.path.exists(m3u8_path):
        try:
            durations = []
            with open(m3u8_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#EXTINF:'):
                        try:
                            val = float(line.split(':', 1)[1].split(',')[0])
                            durations.append(val)
                        except Exception:
                            continue
            if durations:
                # Use median of last up to 10 values to avoid spikes
                recent = durations[-10:]
                recent.sort()
                mid = len(recent) // 2
                segment_duration = recent[mid] if len(recent) % 2 == 1 else (recent[mid - 1] + recent[mid]) / 2.0
        except Exception as e:
            logger.warning(f" Failed to read segment duration from m3u8: {e}")

    if segment_duration is None:
        segment_duration = get_device_segment_duration(device_folder)

    segments_needed = max(1, int(round(60.0 / segment_duration)))
    logger.info(f" Segment duration: {segment_duration:.2f}s  need {segments_needed} segments for ~60s")

    # skip_faststart on the 1-min hot MP4: it's only used as input to the 10-min
    # progressive append (which keeps faststart for streaming-friendly playback).
    # Skipping the second-pass moov relocation here halves disk I/O for the hot
    # build, where I/O — not CPU — is the bottleneck on the Pi's storage.
    mp4_1min = merge_progressive_batch(hot_segments, 'segment_*.ts', mp4_1min_path, segments_needed, True, 20, skip_faststart=True)
    if mp4_1min:
        mp4_elapsed = time.time() - mp4_start
        logger.info(f"\033[34m Created 1min MP4 (slot {minute_slot}):\033[0m {mp4_1min} \033[90m({mp4_elapsed:.2f}s)\033[0m")
    else:
        logger.info("  1min MP4 not created (not enough segments yet or merge failed)")
    
    mp4_10min = None
    if mp4_1min:
        # Create 1min MP3 in audio temp dir (hot/cold aware for inotify + instant transcription)
        # Use rotating slot naming (0-9) instead of timestamps to avoid cleanup
        from shared.src.lib.utils.storage_path_utils import calculate_chunk_location, get_audio_path, get_device_info_from_capture_folder
        from pathlib import Path as PathLib
        
        # Get device folder and calculate chunk location from current time
        device_folder = os.path.basename(capture_dir)
        now = datetime.now()
        hour, chunk_index = calculate_chunk_location(now)
        
        # minute_slot already calculated above at line 1004 - reuse it
        
        # Device info - audio is now supported for all devices including host/VNC
        device_info = get_device_info_from_capture_folder(device_folder)
        device_id = device_info.get('device_id', device_folder)
        
        # Extract audio for all devices (host/VNC now have PulseAudio)
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
        audio_cold = get_cold_storage_path(device_folder, 'audio')
        audio_temp_dir = os.path.join(audio_cold, 'temp')
        os.makedirs(audio_temp_dir, exist_ok=True)
        
        # Use rotating slot naming: 1min_0.mp3 through 1min_9.mp3
        # Delete old file in this slot BEFORE creating new one (prevents race condition)
        mp3_1min = os.path.join(audio_temp_dir, f'1min_{minute_slot}.mp3')
        
        # Delete old file in this slot first (if exists)
        if os.path.exists(mp3_1min):
            try:
                os.remove(mp3_1min)
                logger.debug(f"[{device_folder}] Deleted old 1min_{minute_slot}.mp3 (rotating slot)")
            except Exception as e:
                logger.warning(f"[{device_folder}] Failed to delete old MP3 slot: {e}")
        
        try:
            import subprocess
            mp3_start = time.time()
            subprocess.run(
                ['ffmpeg', '-i', mp4_1min, '-vn', '-acodec', 'libmp3lame', '-q:a', '4', '-f', 'mp3', f'{mp3_1min}.tmp', '-y'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15
            )
            os.replace(f'{mp3_1min}.tmp', mp3_1min)
            mp3_elapsed = time.time() - mp3_start
            logger.info(f"\033[32m Created 1min MP3 (slot {minute_slot}):\033[0m {mp3_1min} \033[90m({mp3_elapsed:.2f}s)\033[0m")
        except subprocess.CalledProcessError as e:
            # MP4 has no audio track (VNC/silent source) - this is expected
            logger.info(f" Skipped MP3 (no audio in source): {mp4_1min}")
            mp3_1min = None
        except Exception as e:
            logger.warning(f"MP3 extraction error: {e}")
            mp3_1min = None
        
        # Progressive append MP4
        hour_dir = os.path.join(capture_dir, 'segments', str(hour))
        if not os.path.isdir(hour_dir):
            os.makedirs(hour_dir, exist_ok=True)
            logger.info(f" Created archive hour dir: {hour_dir}")
        mp4_path = os.path.join(hour_dir, f'chunk_10min_{chunk_index}.mp4')
        
        mp4_append_start = time.time()
        if os.path.exists(mp4_path):
            # Check if existing chunk is from current 10-minute window (24h rolling buffer fix)
            # If file is from yesterday's same time slot, OVERWRITE it instead of APPEND
            file_mtime = os.path.getmtime(mp4_path)
            file_dt = datetime.fromtimestamp(file_mtime)
            file_hour, file_chunk = calculate_chunk_location(file_dt)
            
            # Check if file is from current window (within last 10 minutes)
            is_current_window = (file_hour == hour and file_chunk == chunk_index and 
                                now.timestamp() - file_mtime < 600)  # 10 minutes
            
            if not is_current_window:
                # File is old (from yesterday or earlier) - OVERWRITE instead of append
                logger.info(f" Old chunk detected (age: {(now.timestamp() - file_mtime)/3600:.1f}h), overwriting: {mp4_path}")
                shutil.copy(mp4_1min, mp4_path)
                mp4_append_elapsed = time.time() - mp4_append_start
                created_size = os.path.getsize(mp4_path)
                logger.info(f"\033[34m Overwritten 10min MP4:\033[0m {mp4_path} \033[90m({mp4_append_elapsed:.2f}s, {created_size/1024/1024:.2f}MB)\033[0m")
                mp4_10min = mp4_path
            else:
                # File is current - APPEND as normal
                from shared.src.lib.utils.video_utils import merge_video_files
                # Use temporary file to prevent corruption from in-place overwrite
                temp_output = mp4_path + '.tmp'
                
                # Log input file details for diagnostics
                input1_size = os.path.getsize(mp4_path)
                input2_size = os.path.getsize(mp4_1min)
                logger.debug(f"MP4 merge inputs: {mp4_path} ({input1_size/1024/1024:.2f}MB) + {mp4_1min} ({input2_size/1024/1024:.2f}MB)")
                
                # Enable faststart flag for progressive chunks (prevents corruption from broken moov atoms)
                result = merge_video_files([mp4_path, mp4_1min], temp_output, 'mp4', False, 60, None, False)
                mp4_append_elapsed = time.time() - mp4_append_start
                
                # Enhanced diagnostics
                if not result:
                    logger.error(f"merge_video_files returned False (FFmpeg process failed or timed out after 60s)")
                if result and not os.path.exists(temp_output):
                    logger.error(f"merge_video_files returned True but temp file was not created: {temp_output}")
                
                if result and os.path.exists(temp_output):
                    # Verify output file size before replacing
                    temp_size = os.path.getsize(temp_output)
                    original_size = input1_size  # Reuse from above
                    new_chunk_size = input2_size  # Reuse from above
                    
                    # Expected size should be roughly original + new chunk (allow 5% variance for MP4 overhead)
                    expected_min_size = original_size + (new_chunk_size * 0.95)
                    
                    if temp_size < expected_min_size:
                        logger.error(f"\033[31m MP4 concat produced suspiciously small file:\033[0m {temp_size/1024/1024:.2f}MB (expected {expected_min_size/1024/1024:.2f}MB, original={original_size/1024/1024:.2f}MB + new={new_chunk_size/1024/1024:.2f}MB)")
                        os.remove(temp_output)
                        logger.warning(f"Discarded corrupted output, original file preserved")
                    elif temp_size < 100000:  # Less than 100KB is definitely wrong
                        logger.error(f"\033[31m MP4 concat produced tiny file:\033[0m {temp_size} bytes (likely corrupted)")
                        os.remove(temp_output)
                        logger.warning(f"Discarded corrupted output, original file preserved")
                    else:
                        # Atomic replace: only overwrite original if merge succeeded and size is valid
                        os.replace(temp_output, mp4_path)
                        final_size = os.path.getsize(mp4_path)
                        logger.info(f"\033[34m Appended to 10min MP4:\033[0m {mp4_path} \033[90m({mp4_append_elapsed:.2f}s, {original_size/1024/1024:.2f}MB  {final_size/1024/1024:.2f}MB, +{(final_size-original_size)/1024/1024:.2f}MB)\033[0m")
                        mp4_10min = mp4_path  # Mark success
                else:
                    logger.error(f"\033[31m Failed to append (likely corrupted), recreating from scratch\033[0m")
                    # Clean up temp file
                    if os.path.exists(temp_output):
                        try:
                            os.remove(temp_output)
                        except:
                            pass
                    # Delete corrupted original and immediately start fresh with current 1min MP4
                    try:
                        os.remove(mp4_path)
                        shutil.copy(mp4_1min, mp4_path)
                        created_size = os.path.getsize(mp4_path)
                        logger.info(f"\033[34m Recreated 10min MP4 from scratch:\033[0m {mp4_path} \033[90m({created_size/1024/1024:.2f}MB)\033[0m")
                        mp4_10min = mp4_path  # Mark success
                    except Exception as e:
                        logger.error(f"Recovery failed: {e}")
        else:
            shutil.copy(mp4_1min, mp4_path)
            mp4_append_elapsed = time.time() - mp4_append_start
            created_size = os.path.getsize(mp4_path)
            logger.info(f"\033[34m Created 10min MP4:\033[0m {mp4_path} \033[90m({mp4_append_elapsed:.2f}s, {created_size/1024/1024:.2f}MB)\033[0m")
            mp4_10min = mp4_path  # Mark success
        
        # Progressive append MP3 to 10min chunk (after transcription happens via inotify)
        mp3_10min_path = None
        if mp3_1min and os.path.exists(mp3_1min):
            # Use same audio_cold from above
            audio_hour_dir = os.path.join(audio_cold, str(hour))
            os.makedirs(audio_hour_dir, exist_ok=True)
            mp3_10min_path = os.path.join(audio_hour_dir, f'chunk_10min_{chunk_index}.mp3')
            
            mp3_append_start = time.time()
            if os.path.exists(mp3_10min_path):
                # Check if existing MP3 chunk is from current 10-minute window (24h rolling buffer fix)
                # If file is from yesterday's same time slot, OVERWRITE it instead of APPEND
                file_mtime = os.path.getmtime(mp3_10min_path)
                file_dt = datetime.fromtimestamp(file_mtime)
                file_hour, file_chunk = calculate_chunk_location(file_dt)
                
                # Check if file is from current window (within last 10 minutes)
                is_current_window = (file_hour == hour and file_chunk == chunk_index and 
                                    now.timestamp() - file_mtime < 600)  # 10 minutes
                
                if not is_current_window:
                    # File is old (from yesterday or earlier) - OVERWRITE instead of append
                    logger.info(f" Old MP3 chunk detected (age: {(now.timestamp() - file_mtime)/3600:.1f}h), overwriting: {mp3_10min_path}")
                    shutil.copy(mp3_1min, mp3_10min_path)
                    mp3_append_elapsed = time.time() - mp3_append_start
                    created_size = os.path.getsize(mp3_10min_path)
                    logger.info(f"\033[32m Overwritten 10min MP3:\033[0m {mp3_10min_path} \033[90m({mp3_append_elapsed:.3f}s, {created_size/1024:.1f}KB)\033[0m")
                else:
                    # File is current - APPEND as normal
                    try:
                        # Use temp file for atomic append (prevents corruption if process killed mid-write)
                        temp_output = mp3_10min_path + '.tmp'
                        original_size = os.path.getsize(mp3_10min_path)
                        new_chunk_size = os.path.getsize(mp3_1min)
                        
                        shutil.copy(mp3_10min_path, temp_output)  # Copy existing file
                        with open(temp_output, 'ab') as dest:
                            with open(mp3_1min, 'rb') as src:
                                dest.write(src.read())
                        
                        # Verify output file size before replacing
                        temp_size = os.path.getsize(temp_output)
                        expected_size = original_size + new_chunk_size
                        
                        if temp_size < expected_size:
                            logger.error(f"\033[31m MP3 append produced wrong size:\033[0m {temp_size/1024:.1f}KB (expected {expected_size/1024:.1f}KB)")
                            os.remove(temp_output)
                            logger.warning(f"Discarded corrupted output, original file preserved")
                        elif temp_size < 10000:  # Less than 10KB is definitely wrong
                            logger.error(f"\033[31m MP3 append produced tiny file:\033[0m {temp_size} bytes (likely corrupted)")
                            os.remove(temp_output)
                            logger.warning(f"Discarded corrupted output, original file preserved")
                        else:
                            os.replace(temp_output, mp3_10min_path)  # Atomic replace
                            final_size = os.path.getsize(mp3_10min_path)
                            mp3_append_elapsed = time.time() - mp3_append_start
                            logger.info(f"\033[32m Appended to 10min MP3:\033[0m {mp3_10min_path} \033[90m({mp3_append_elapsed:.3f}s, {original_size/1024:.1f}KB  {final_size/1024:.1f}KB, +{new_chunk_size/1024:.1f}KB)\033[0m")
                    except Exception as e:
                        logger.warning(f"Failed to append MP3: {e}")
                        # Clean up temp file on failure (original file remains intact)
                        temp_output = mp3_10min_path + '.tmp'
                        if os.path.exists(temp_output):
                            try:
                                os.remove(temp_output)
                                logger.debug(f"Cleaned up failed MP3 temp file: {temp_output}")
                            except Exception as cleanup_error:
                                logger.warning(f"Failed to clean up MP3 temp file: {cleanup_error}")
            else:
                shutil.copy(mp3_1min, mp3_10min_path)
                mp3_append_elapsed = time.time() - mp3_append_start
                created_size = os.path.getsize(mp3_10min_path)
                logger.info(f"\033[32m Created 10min MP3:\033[0m {mp3_10min_path} \033[90m({mp3_append_elapsed:.3f}s, {created_size/1024:.1f}KB)\033[0m")
            
            # No deletion needed - rotating slot system automatically manages old files
            # File will be overwritten in ~10 minutes when slot rotates
            logger.debug(f"1min MP3 appended to 10min chunk (slot {minute_slot} will auto-rotate)")
        
        # No deletion of 1min MP4 - rotating slot system keeps last 10 files playable
        # File will be overwritten in ~10 minutes when slot rotates
        logger.debug(f"1min MP4 kept in temp/ for individual playback (slot {minute_slot} will auto-rotate)")
        
        # Update manifest only if MP4 operation succeeded
        if mp4_10min:
            update_archive_manifest(capture_dir, hour, chunk_index, mp4_path)
    
    # SAFETY CLEANUP: Delete orphaned 1min files from temp/
    # MP4: Rotating slots (no cleanup - kept for playback)
    # JSON: 2h timeout (failed merges)
    # MP3: Rotating slots (15min safety net)
    deleted_temp_segments, deleted_temp_metadata, deleted_temp_mp3 = cleanup_temp_files(capture_dir)
    
    elapsed = time.time() - start_time
    
    # Build status summary
    if mp4_10min:
        mp4_info = ", MP4: "
    elif mp4_1min:  # 1min was created but 10min append failed
        mp4_info = ", MP4:  failed"
    else:
        mp4_info = ""
    
    # Safety cleanup stats (HOT only)
    safety_deletes = []
    if deleted_segments > 0:
        safety_deletes.append(f"{deleted_segments} seg")
    if deleted_captures > 0:
        safety_deletes.append(f"{deleted_captures} cap")
    if deleted_thumbnails > 0:
        safety_deletes.append(f"{deleted_thumbnails} thumb")
    if deleted_metadata > 0:
        safety_deletes.append(f"{deleted_metadata} meta")
    if deleted_temp_segments > 0:
        safety_deletes.append(f"{deleted_temp_segments} temp_seg")
    if deleted_temp_metadata > 0:
        safety_deletes.append(f"{deleted_temp_metadata} temp_meta")
    if deleted_temp_mp3 > 0:
        safety_deletes.append(f"{deleted_temp_mp3} temp_mp3")
    
    cleanup_info = f"del: {', '.join(safety_deletes)}" if safety_deletes else "del: 0"
    
    logger.info(f"   FAST done in {elapsed:.2f}s ({cleanup_info}{mp4_info})")


def process_cold_storage(capture_dir: str):
    """
    COLD STORAGE PROCESSING (Slow, Batched, Every 60s)
    
    Cleanup old files from COLD storage with batch limits to prevent long-running cycles.
    - Root live files: Delete stale items older than 1h
    - Archived chunks/subfolders: Delete stale items older than 26h
    
    This runs in a separate thread to avoid blocking hot storage cleanup.
    """
    logger.info(f"{Colors.BLUE}  COLD: {os.path.basename(capture_dir)}{Colors.RESET}")
    
    start_time = time.time()
    
    # Batch-limited cold cleanup (prevents hour-long cycles)
    deleted_cold_segments = cleanup_cold_segments(capture_dir, COLD_BATCH_LIMIT)
    deleted_cold_captures = cleanup_cold_captures(capture_dir, COLD_BATCH_LIMIT)
    deleted_cold_thumbnails = cleanup_cold_thumbnails(capture_dir, COLD_BATCH_LIMIT)
    deleted_cold_metadata = cleanup_cold_metadata(capture_dir, COLD_BATCH_LIMIT)
    
    elapsed = time.time() - start_time
    
    # Build status summary
    cold_deletes = []
    if deleted_cold_segments > 0:
        cold_deletes.append(f"{deleted_cold_segments} seg")
    if deleted_cold_captures > 0:
        cold_deletes.append(f"{deleted_cold_captures} cap")
    if deleted_cold_thumbnails > 0:
        cold_deletes.append(f"{deleted_cold_thumbnails} thumb")
    if deleted_cold_metadata > 0:
        cold_deletes.append(f"{deleted_cold_metadata} meta")
    
    cleanup_info = f"del: {', '.join(cold_deletes)}" if cold_deletes else "del: 0"
    
    logger.info(f"{Colors.BLUE}   COLD done in {elapsed:.2f}s ({cleanup_info}){Colors.RESET}")


def hot_storage_loop():
    """
    HOT STORAGE THREAD (Every 15s)
    
    Fast, critical RAM management:
    - SAFETY CLEANUP: Enforce limits on hot storage types (prevent RAM exhaustion)
    - Segments: HOT TS  1min MP4  progressively append to 10min chunk in COLD
    - Audio: Extract from 10min chunks  directly to COLD /audio/{hour}/
    
    Progressive append: Each minute appends to growing chunk (no batch-merge-at-end)
    Result: Timeline has no changes, same URL grows from 1min to 10min duration
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info(" ARCHIVER FAST LOOP STARTED (formerly HOT loop)")
    logger.info("=" * 80)
    logger.info(f"Interval: {HOT_THREAD_INTERVAL}s (fast retry / low-latency append)")
    logger.info(f"Hot/live limits: {HOT_LIMITS}")
    logger.info("Strategy: Live segments  1min MP4  append to 10min chunk (fast retry)")
    logger.info("=" * 80)
    
    # STARTUP ONLY: Rebuild all manifests from disk to discover existing chunks
    logger.info("")
    logger.info("=" * 60)
    logger.info("STARTUP: Rebuilding archive and transcript manifests from disk...")
    logger.info("=" * 60)
    
    # Get capture directories for startup
    capture_dirs = get_capture_base_directories()
    conf_path = get_active_captures_conf_path()
    logger.info(f" Active captures conf: {conf_path} (exists: {os.path.exists(conf_path)})")
    try:
        parsed = parse_active_captures_conf()
        if parsed:
            logger.info(f" Parsed active_captures.conf entries ({len(parsed)}): {parsed}")
        else:
            logger.info(" Parsed active_captures.conf entries: []")
    except Exception as e:
        logger.warning(f" Failed to parse active_captures.conf: {e}")
    if not capture_dirs:
        logger.warning(" No capture directories found. Archiver will idle until active_captures.conf or env paths are available.")
    else:
        logger.info(f" Capture directories loaded ({len(capture_dirs)}): {capture_dirs}")
    
    for capture_dir in capture_dirs:
        try:
            import json
            
            # Rebuild video archive manifest
            manifest = rebuild_archive_manifest_from_disk(capture_dir)
            manifest_path = os.path.join(capture_dir, 'segments', 'archive_manifest.json')
            
            # Save rebuilt manifest
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            with open(manifest_path + '.tmp', 'w') as f:
                json.dump(manifest, f, indent=2)
            os.replace(manifest_path + '.tmp', manifest_path)
            
            logger.info(f" {os.path.basename(capture_dir)}: Rebuilt archive manifest with {manifest['total_chunks']} chunks across {len(manifest['available_hours'])} hours")
            
            # Log detailed manifest info
            if manifest['total_chunks'] > 0:
                logger.info(f"    Archive: Available hours: {manifest['available_hours']}")
                # Show first and last chunk as examples
                first_chunk = manifest['chunks'][0]
                last_chunk = manifest['chunks'][-1]
                logger.info(f"    Archive: First chunk: hour {first_chunk['hour']}, chunk {first_chunk['chunk_index']}, size {first_chunk['size']/1024/1024:.1f}MB")
                logger.info(f"    Archive: Last chunk: hour {last_chunk['hour']}, chunk {last_chunk['chunk_index']}, size {last_chunk['size']/1024/1024:.1f}MB")
            else:
                logger.info(f"    Archive: No chunks found")
            
            # Rebuild transcript manifest
            transcript_manifest = rebuild_transcript_manifest_from_disk(capture_dir)
            transcript_manifest_path = os.path.join(capture_dir, 'transcript', 'transcript_manifest.json')
            
            # Save rebuilt transcript manifest
            os.makedirs(os.path.dirname(transcript_manifest_path), exist_ok=True)
            with open(transcript_manifest_path + '.tmp', 'w') as f:
                json.dump(transcript_manifest, f, indent=2)
            os.replace(transcript_manifest_path + '.tmp', transcript_manifest_path)
            
            logger.info(f" {os.path.basename(capture_dir)}: Rebuilt transcript manifest with {transcript_manifest['total_chunks']} chunks across {len(transcript_manifest['available_hours'])} hours")
            
            # Log detailed transcript manifest info
            if transcript_manifest['total_chunks'] > 0:
                logger.info(f"    Transcript: Available hours: {transcript_manifest['available_hours']}")
                # Show first and last transcript chunk
                first_trans = transcript_manifest['chunks'][0]
                last_trans = transcript_manifest['chunks'][-1]
                logger.info(f"    Transcript: First chunk: hour {first_trans['hour']}, chunk {first_trans['chunk_index']}, lang={first_trans.get('language', 'unknown')}, has_text={first_trans.get('has_transcript', False)}")
                logger.info(f"    Transcript: Last chunk: hour {last_trans['hour']}, chunk {last_trans['chunk_index']}, lang={last_trans.get('language', 'unknown')}, has_text={last_trans.get('has_transcript', False)}")
            else:
                logger.info(f"    Transcript: No chunks found")
            
        except Exception as e:
            logger.error(f"Error rebuilding manifests for {capture_dir}: {e}")
    logger.info("=" * 60)
    
    while True:
        try:
            cycle_start = time.time()
            
            logger.info("")
            logger.info("=" * 80)
            logger.info(f" ARCHIVER FAST CYCLE at {datetime.now().strftime('%H:%M:%S')}")
            logger.info("=" * 80)
            
            # Get active capture directories
            capture_dirs = get_capture_base_directories()
            if not capture_dirs:
                logger.warning(" No capture directories found for FAST cycle; skipping.")
            
            any_ram = any(is_ram_mode(d) for d in capture_dirs) if capture_dirs else False
            mode_label = "RAM (hot)" if any_ram else "SD (cold)"

            # BEFORE CLEANING SUMMARY
            print_ram_summary(capture_dirs, " BEFORE FAST CYCLE")
            
            # Process each directory (hot storage only)
            for capture_dir in capture_dirs:
                try:
                    process_hot_storage(capture_dir)
                except Exception as e:
                    logger.error(f"Error processing hot storage for {capture_dir}: {e}", exc_info=True)
            
            # AFTER CLEANING SUMMARY
            print_ram_summary(capture_dirs, " AFTER FAST CYCLE")
            
            cycle_elapsed = time.time() - cycle_start
            logger.info(f" FAST cycle completed in {cycle_elapsed:.2f}s (mode: {mode_label}, next in {HOT_THREAD_INTERVAL}s)")
            
            # Sleep until next cycle
            time.sleep(HOT_THREAD_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info(" HOT thread: Received interrupt signal, shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in hot storage loop: {e}", exc_info=True)
            time.sleep(HOT_THREAD_INTERVAL)


def cold_storage_loop():
    """
    COLD STORAGE THREAD (Every 60s)
    
    Batch cleanup of cold storage (non-blocking):
    - Captures: Delete files older than 1h (max 200 files per device per cycle)
    - Thumbnails: Delete files older than 1h (max 200 files per device per cycle)
    
    Batch limits prevent hour-long cycles that block hot storage cleanup.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"{Colors.BLUE}  COLD STORAGE THREAD STARTED{Colors.RESET}")
    logger.info("=" * 80)
    logger.info(f"{Colors.BLUE}Interval: {COLD_THREAD_INTERVAL}s{Colors.RESET}")
    logger.info(f"{Colors.BLUE}Batch limit: {COLD_BATCH_LIMIT} files per device per cycle{Colors.RESET}")
    logger.info("=" * 80)
    
    while True:
        try:
            cycle_start = time.time()
            
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"{Colors.BLUE}  COLD CYCLE at {datetime.now().strftime('%H:%M:%S')}{Colors.RESET}")
            logger.info("=" * 80)
            
            # Get active capture directories
            capture_dirs = get_capture_base_directories()
            if not capture_dirs:
                logger.warning(" No capture directories found for COLD cycle; skipping.")
            
            # Process each directory (cold storage only)
            for capture_dir in capture_dirs:
                try:
                    process_cold_storage(capture_dir)
                    
                    # Verification cleanup every 1 hour, tracked per capture_dir so one
                    # channel firing doesn't reset the clock for the other three.
                    if time.time() - last_verification_cleanup.get(capture_dir, 0) > VERIFICATION_CLEANUP_INTERVAL:
                        cleanup_verification_results(capture_dir)
                        last_verification_cleanup[capture_dir] = time.time()

                    # Reports cleanup every 1 hour (30-day retention), same per-channel tracking.
                    if time.time() - last_reports_cleanup.get(capture_dir, 0) > REPORTS_CLEANUP_INTERVAL:
                        cleanup_reports(capture_dir)
                        # Same cadence and retention for the loose artifacts that
                        # sit in the capture root rather than under reports/.
                        cleanup_capture_root_artifacts(capture_dir)
                        last_reports_cleanup[capture_dir] = time.time()

                except Exception as e:
                    logger.error(f"{Colors.BLUE}Error processing cold storage for {capture_dir}: {e}{Colors.RESET}", exc_info=True)
            
            cycle_elapsed = time.time() - cycle_start
            logger.info(f"{Colors.BLUE}  COLD cycle completed in {cycle_elapsed:.2f}s (next in {COLD_THREAD_INTERVAL}s){Colors.RESET}")
            
            # Sleep until next cycle
            time.sleep(COLD_THREAD_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info(f"{Colors.BLUE}  COLD thread: Received interrupt signal, shutting down...{Colors.RESET}")
            break
        except Exception as e:
            logger.error(f"{Colors.BLUE}Error in cold storage loop: {e}{Colors.RESET}", exc_info=True)
            time.sleep(COLD_THREAD_INTERVAL)


def _parse_capture_args(argv):
    """Mirror transcript.service's `--transcript true`: `--keep-captures true`
    enables 24h full-res still archiving; `--keep-captures-fps N` sets the sample
    rate. CLI overrides the ARCHIVE_CAPTURES / ARCHIVE_CAPTURES_FPS env fallbacks."""
    global ARCHIVE_CAPTURES, ARCHIVE_CAPTURES_FPS
    if '--keep-captures' in argv:
        i = argv.index('--keep-captures')
        val = argv[i + 1] if i + 1 < len(argv) else 'true'
        ARCHIVE_CAPTURES = val.strip().lower() in ('1', 'true', 'yes', 'on')
    if '--keep-captures-fps' in argv:
        i = argv.index('--keep-captures-fps')
        try:
            ARCHIVE_CAPTURES_FPS = float(argv[i + 1])
        except (IndexError, ValueError):
            pass


if __name__ == '__main__':
    try:
        _parse_capture_args(sys.argv[1:])

        # Kill any existing archiver instances before starting
        from shared.src.lib.utils.system_utils import kill_existing_script_instances
        killed = kill_existing_script_instances('hot_cold_archiver.py')
        if killed:
            logger.info(f"Killed existing archiver instances: {killed}")
            time.sleep(1)

        # Quiet by default; raise verbosity on demand with
        # `sudo pkill -USR1 -f hot_cold_archiver.py` (SIGUSR2 to restore).
        from shared.src.lib.utils.log_control import install_runtime_log_control
        install_runtime_log_control('ARCHIVER_LOG_LEVEL')

        logger.info("")
        logger.info("=" * 80)
        logger.info("HOT/COLD ARCHIVER - DUAL-THREAD ARCHITECTURE")
        logger.info("=" * 80)
        logger.info(" HOT THREAD: Critical RAM management (every 15s)")
        logger.info(f"{Colors.BLUE}  COLD THREAD: Batch cleanup (every 60s, max 200 files/device){Colors.RESET}")
        if ARCHIVE_CAPTURES:
            logger.info(f" CAPTURE ARCHIVING: ON ({ARCHIVE_CAPTURES_FPS} fps → cold captures/{{hour}}/, 24h, min-free {ARCHIVE_CAPTURES_MIN_FREE_PCT}%)")
        else:
            logger.info(" CAPTURE ARCHIVING: off (set --keep-captures true or ARCHIVE_CAPTURES=true to keep 24h full-res stills)")
        logger.info("=" * 80)
        
        # Create and start both threads
        hot_thread = threading.Thread(target=hot_storage_loop, name="HotStorageThread", daemon=True)
        cold_thread = threading.Thread(target=cold_storage_loop, name="ColdStorageThread", daemon=True)
        
        hot_thread.start()
        cold_thread.start()
        
        logger.info(" Both threads started successfully")
        
        # Keep main thread alive
        try:
            while True:
                hot_thread.join(timeout=1.0)
                cold_thread.join(timeout=1.0)
                if not hot_thread.is_alive():
                    logger.error(" HOT thread died, restarting...")
                    hot_thread = threading.Thread(target=hot_storage_loop, name="HotStorageThread", daemon=True)
                    hot_thread.start()
                if not cold_thread.is_alive():
                    logger.error(f"{Colors.BLUE}  COLD thread died, restarting...{Colors.RESET}")
                    cold_thread = threading.Thread(target=cold_storage_loop, name="ColdStorageThread", daemon=True)
                    cold_thread.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down both threads...")
            sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
