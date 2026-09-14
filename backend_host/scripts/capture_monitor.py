#!/usr/bin/env python3
"""
Event-driven frame monitor - eliminates directory scanning bottleneck
Watches for new frames and processes them immediately (zero CPU when idle)
Uses FFmpeg atomic_writing feature to detect completed files

Cross-platform: Uses inotify on Linux, watchdog on macOS

Per-device queue processing:
- Each device has dedicated LIFO queue (stack) and worker thread
- LIFO = Process newest frames first (prevents stale analysis when backlog exists)
- Sequential processing within device prevents CPU spikes
- Parallel processing across devices maintains performance
- Queue size logging: Tracks backlog to detect performance issues

Zapping detection concurrency control:
- Per-device locks prevent concurrent processing of multiple blackscreens
- If a blackscreen is already being analyzed, subsequent ones are skipped
- This prevents race conditions where multiple workers read last_action.json
- Ensures each action is matched to only ONE blackscreen detection
"""

# CRITICAL: Limit CPU threads BEFORE importing OpenCV/NumPy
# OpenCV/NumPy/OpenBLAS create many threads by default
import os
os.environ['OMP_NUM_THREADS'] = '2'          # OpenMP
os.environ['MKL_NUM_THREADS'] = '2'          # Intel MKL
os.environ['OPENBLAS_NUM_THREADS'] = '2'     # OpenBLAS
os.environ['NUMEXPR_NUM_THREADS'] = '2'      # NumExpr

import sys
import json
import logging
import queue
import time
from queue import LifoQueue
import threading
from datetime import datetime
import subprocess
import platform
import tempfile

# Cross-platform file monitoring: inotify on Linux, watchdog on macOS
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

if IS_LINUX:
    import inotify.adapters
else:
    # macOS/other: use watchdog (cross-platform)
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from shared.src.lib.utils.storage_path_utils import (
    get_capture_base_directories, 
    get_capture_storage_path, 
    get_capture_folder, 
    get_device_info_from_capture_folder,
    get_metadata_path,
    get_captures_path,
    get_segments_path,
    get_segment_path_from_frame,
    get_device_segment_duration,
    get_capture_folder_from_device_id
)
from shared.src.lib.utils.audio_transcription_utils import check_audio_continuous
from shared.src.lib.utils.zapping_detector_utils import detect_and_record_zapping
from detector import detect_issues
from incident_manager import IncidentManager
from monitor_localize import MonitorLocalizer

# Setup logging (systemd handles file output)
# Use INFO for important events, DEBUG for repetitive per-frame logs.
# Override via CAPTURE_MONITOR_LOG_LEVEL env var when debugging — e.g.
# `systemctl set-environment CAPTURE_MONITOR_LOG_LEVEL=DEBUG` before
# restarting vpt-host to see the per-frame ARRIVED / QUEUED / PROCESSING trace.
_log_level_name = os.getenv('CAPTURE_MONITOR_LOG_LEVEL', 'INFO').upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def _atomic_write_json(path: str, data: dict = None, raw_text: str = None) -> None:
    """
    Write JSON atomically to avoid partial reads by other processes.

    This is used when writing per-frame metadata JSON files that may be consumed
    immediately by other components (e.g., host monitoring endpoints, heatmap).
    """
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    # Keep temp file in the same directory so os.replace() is atomic on that filesystem.
    # Use a deterministic ".tmp" name to avoid Windows NamedTemporaryFile locking issues.
    tmp_path = f"{path}.tmp"

    with open(tmp_path, 'w', encoding='utf-8') as f:
        if raw_text is not None:
            f.write(raw_text)
        else:
            json.dump(data, f, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some platforms/filesystems may not support fsync; atomic replace still helps.
            pass

    os.replace(tmp_path, path)

# Log memory usage periodically (every hour)
_last_memory_log = 0
MEMORY_LOG_INTERVAL = 3600  # 1 hour

def log_memory_usage():
    """Log memory usage periodically to help track memory leaks"""
    global _last_memory_log
    current_time = time.time()
    
    if current_time - _last_memory_log < MEMORY_LOG_INTERVAL:
        return
    
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        logger.info(f"📊 [MEMORY] capture_monitor.py using {memory_mb:.1f}MB RAM")
        
        # Alert if memory exceeds 1GB
        if memory_mb > 1024:
            logger.warning(f"⚠️  [MEMORY] capture_monitor.py exceeds 1GB ({memory_mb:.1f}MB) - possible memory leak!")
        
        _last_memory_log = current_time
    except Exception as e:
        logger.warning(f"Failed to log memory usage: {e}")

class FrameMonitor:
    """Event-driven frame monitor with per-device queue processing
    
    Cross-platform: Uses inotify on Linux, watchdog on macOS
    """
    
    def __init__(self, capture_dirs, host_name):
        self.host_name = host_name
        self.incident_manager = IncidentManager()

        # Per-frame screen identification (Localize) for the monitoring overlay.
        # Opt-in per device via DEVICE{N}_USERINTERFACE; throttled to ~1/sec in
        # process_frame. Best-effort: never blocks or breaks frame processing.
        self.localizer = MonitorLocalizer()
        # Localize runs OFF the per-frame loop in a background thread so its OCR/
        # translate cost never affects freeze/blackscreen latency.
        #   _latest_frame:  device_id -> newest captured frame path (set by the frame
        #                   loop, read by the worker — a single cheap dict write/frame).
        #   _last_localize: device_id -> last computed result (written by the worker,
        #                   attached to every analyzed frame for a stable "Screen:"
        #                   line). No entry for disabled devices → overlay hides it.
        self._latest_frame = {}
        self._last_localize = {}
        # Per-device gatekeeper for the motion classifier: debounces the displayed state so it
        # doesn't flip live/unknown/ui every frame when localize briefly abstains or motion
        # hovers at threshold. {device_id: {'shown': str, 'cand': str, 'n': int}}
        self._motion_gate = {}
        # Last fused motion per device. detect_freeze (and thus motion) runs ~1/5 frames; the
        # cached result is written on the skipped frames so the overlay state never flickers.
        self._last_motion = {}

        # Platform-specific file watcher initialization
        if IS_LINUX:
            self.inotify = inotify.adapters.Inotify()
            self._watcher_type = 'inotify'
        else:
            # macOS: use watchdog
            self.observer = Observer()
            self._watcher_type = 'watchdog'
        
        self.dir_to_info = {}
        self.device_queues = {}
        self.device_workers = {}

        # Incident processing is offloaded to a dedicated per-device thread.
        # process_detection() does synchronous R2 uploads + Supabase
        # create/resolve which can block for seconds on a Pi; running it on
        # the frame worker stalled frame processing and overflowed the LIFO
        # capture queue (→ "Queue over 150, SKIPPING"). These threads keep
        # that I/O off the hot path. Queue is coalesced (latest wins) since
        # the incident state machine is time-based, not per-frame.
        self.incident_queues = {}
        self.incident_workers = {}
        self._incident_drop_state = {}  # {capture_folder: {'count': int, 'last_log': float}}
        
        # Audio cache: last known audio status per device (updated every 5s by transcript_accumulator)
        self.audio_cache = {}  # {capture_folder: {'audio': bool, 'mean_volume_db': float, 'timestamp': str}}
        
        # Zapping cache: track recent zapping events to add cache to next frames
        # {capture_folder: {'zap_data': {...}, 'frames_written': 0, 'max_frames': 6}}
        self.zapping_cache = {}
        
        # Zapping detection locks: prevent concurrent processing of multiple blackscreens on same device
        # {capture_folder: threading.Lock()} - one lock per device
        self.zapping_locks = {}
        
        # Zapping detection thread pool (prevents blocking frame processing)
        # AI banner analysis takes ~5s - run in background to avoid queue backlog
        from concurrent.futures import ThreadPoolExecutor
        self.zapping_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="zapping-worker")
        
        # ✅ LIFO BACKLOG TRACKING: Track last processed sequence per device
        # Prevents starting new events when processing old frames from backlog
        # {capture_folder: max_sequence_processed}
        self.last_processed_sequence = {}

        # Chunk write coalescing. _append_to_chunk used to json.load + sort +
        # json.dump the whole 10-min chunk file on *every* frame (~1/s/device).
        # With ~600 frames/chunk that is O(N²) per chunk and measured at ~43%
        # of this process's CPU (py-spy, host1, 2026-05-19). We now keep the
        # chunk in memory, append O(1), and flush to disk at most every
        # _chunk_flush_interval_s, plus on 10-min rollover and on shutdown.
        # Nothing live reads the chunk: the frontend's /monitoring/latest-json
        # serves the newest *per-frame* metadata file (written every frame,
        # unchanged), so a ≤2s flush lag on a 10-min aggregate is invisible.
        # Worst case on a hard kill: ≤2s of chunk metadata (never images,
        # never the live overlay).
        self._chunk_cache = {}            # {chunk_path: {data, seen, dirty, last_flush, capture_folder}}
        self._chunk_cache_lock = threading.Lock()
        self._chunk_flush_interval_s = 2.0

        # Capture-stall observability (see docs/agent/devices/FFMPEG_TROUBLESHOOT.md Step B).
        # Tracks wallclock of the last inotify/watchdog file-arrival event per device
        # so a lightweight watcher thread can log when FFmpeg stops emitting jpgs
        # while its process appears healthy otherwise. Populated on first event;
        # None = not yet seen any frame.
        self.last_frame_arrival = {}     # {capture_folder: monotonic seconds}
        self.last_frame_filename = {}    # {capture_folder: filename}
        self.stall_state = {}            # {capture_folder: True when currently stalled}
        self.stall_started_at = {}       # {capture_folder: monotonic seconds at stall start}
        # Warn when no new frame has arrived for longer than this. The takeScreenshot
        # route fails at 3s, so 5s is the smallest threshold that won't fire on
        # normal fps jitter but still catches real stalls before they compound.
        self.stall_warn_threshold_s = 5.0
        
        for capture_dir in capture_dirs:
            # Use centralized path utilities (handles both hot and cold storage)
            capture_folder = get_capture_folder(capture_dir)
            
            # Get parent directory (device base path)
            if '/hot/' in capture_dir:
                # Hot storage: /var/www/html/stream/capture1/hot/captures
                # Parent is /var/www/html/stream/capture1
                parent_dir = '/'.join(capture_dir.split('/')[:-2])
            else:
                # Cold storage: /var/www/html/stream/capture1/captures
                # Parent is /var/www/html/stream/capture1
                parent_dir = os.path.dirname(capture_dir)
            
            self.dir_to_info[capture_dir] = {
                'capture_dir': parent_dir,
                'capture_folder': capture_folder
            }
            
            if os.path.exists(capture_dir):
                if IS_LINUX:
                    self.inotify.add_watch(capture_dir)
                # macOS watchdog scheduling happens in run() after all dirs are registered
                logger.info(f"Watching: {capture_dir} -> {capture_folder}")
            else:
                logger.warning(f"Directory not found: {capture_dir}")
            
            # LIFO queue (stack) - process newest frames first to avoid stale analysis
            work_queue = LifoQueue(maxsize=1000)
            self.device_queues[capture_folder] = work_queue
            
            # Initialize lock for this device (one lock per device)
            self.zapping_locks[capture_folder] = threading.Lock()
            
            worker = threading.Thread(
                target=self._device_worker,
                args=(capture_folder, work_queue),
                daemon=True,
                name=f"worker-{capture_folder}"
            )
            worker.start()
            self.device_workers[capture_folder] = worker
            logger.info(f"Started worker thread: {capture_folder}")

            # Dedicated incident worker (R2 upload + Supabase create/resolve).
            # Bounded queue + coalescing drain in _incident_worker keeps it
            # near-empty in steady state; the cap only matters if Supabase/R2
            # is unreachable, in which case we drop (state machine recovers).
            incident_queue = queue.Queue(maxsize=200)
            self.incident_queues[capture_folder] = incident_queue
            incident_worker = threading.Thread(
                target=self._incident_worker,
                args=(capture_folder, incident_queue),
                daemon=True,
                name=f"incident-{capture_folder}"
            )
            incident_worker.start()
            self.incident_workers[capture_folder] = incident_worker
            logger.info(f"Started incident worker thread: {capture_folder}")
        
        # Single background localize worker for all devices (~1/sec each). Kept off
        # the per-frame workers so the title-layer OCR/translate spike on a screen
        # change never delays freeze/blackscreen processing.
        self._localize_thread = threading.Thread(
            target=self._localize_worker,
            daemon=True,
            name="localize-worker",
        )
        self._localize_thread.start()
        logger.info("Started localize worker thread")

        self.process_existing_frames(capture_dirs)

    def _localize_worker(self):
        """Compute Localize for each device ~1/sec from its newest captured frame.

        Runs in its own daemon thread (not the per-frame workers) so the title-layer
        OCR/translate cost on a screen change never adds latency to freeze/blackscreen
        detection. Best-effort: any failure is logged and skipped; the overlay simply
        keeps the last result. localize_frame returns None for devices with no
        DEVICE{N}_USERINTERFACE, which we never cache (overlay hides the line).
        """
        while True:
            try:
                for device_id, frame_path in list(self._latest_frame.items()):
                    try:
                        result = self.localizer.localize_frame(device_id, frame_path)
                        if result is not None:
                            self._last_localize[device_id] = result
                    except Exception as e:
                        logger.warning(f"[localize] worker failed for {device_id}: {e}")
            except Exception as e:
                logger.warning(f"[localize] worker loop error: {e}")
            time.sleep(1.0)

    def _device_worker(self, capture_folder, work_queue):
        """Worker thread for sequential frame processing per device (LIFO - newest first)"""
        frame_count = 0
        prev_queue_size = 0
        max_queue_size_seen = 0
        last_backlog_warning = 0
        # Threshold below which BACKLOG PEAK announcements are useless noise —
        # during warm-up the max grows monotonically on every single frame,
        # which spams the journal and contributes nothing diagnostic. Only
        # announce peaks that represent actual contention.
        BACKLOG_PEAK_MIN = 20
        BACKLOG_PEAK_JUMP = 10

        while True:
            work_item = work_queue.get()
            frame_count += 1
            # Unpack sequence threaded through from the enqueue side so we
            # don't re-parse the filename here (see _handle_file_event).
            if len(work_item) == 3:
                path, filename, sequence = work_item
            else:
                # Backward-compat safety: should not happen in steady state.
                path, filename = work_item[:2]
                try:
                    sequence = int(filename.split('_')[1].split('.')[0])
                except Exception:
                    sequence = None
            queue_size = work_queue.qsize()

            # Drain stale frames: keep only the newest, discard the rest.
            # Without this the LIFO queue fills to 150 and never empties —
            # old frames sit at the bottom forever, the worker can never
            # catch up, and thumbnails/freeze detection stop working.
            drained = 0
            while not work_queue.empty():
                try:
                    drained_item = work_queue.get_nowait()
                    if len(drained_item) == 3:
                        path, filename, sequence = drained_item
                    else:
                        path, filename = drained_item[:2]
                        try:
                            sequence = int(filename.split('_')[1].split('.')[0])
                        except Exception:
                            sequence = None
                    drained += 1
                except:
                    break
            if drained > 0:
                queue_size = 0
                # Only surface drain events that indicate real backlog. LIFO
                # drain of ≤5 stale frames is the steady-state happy path.
                if drained > 5:
                    logger.info(f"[{capture_folder}] 🗑️ Drained {drained} stale frames, processing newest: {filename}")
                else:
                    logger.debug(f"[{capture_folder}] drained {drained} stale frames, processing newest: {filename}")

            # Tracing log — at DEBUG so it stays out of production journal.
            logger.debug(f"[{capture_folder}] 🔄 PROCESSING: {filename} (seq={sequence}, queue_size={queue_size})")

            # Track maximum backlog for diagnostics. Only announce peaks that
            # are both (a) meaningful in magnitude and (b) a notable jump over
            # the previous high, to avoid a flood during warm-up.
            if queue_size > max_queue_size_seen:
                if queue_size >= BACKLOG_PEAK_MIN and (queue_size - max_queue_size_seen) >= BACKLOG_PEAK_JUMP:
                    logger.warning(f"[{capture_folder}] 📈 BACKLOG PEAK: {queue_size} frames (prev max: {max_queue_size_seen})")
                max_queue_size_seen = queue_size

            # Log backlog more frequently during high load
            current_time = time.time()
            if queue_size > 50 and (current_time - last_backlog_warning) > 5:
                logger.warning(f"[{capture_folder}] ⚠️  BACKLOG: {queue_size} frames pending (peak: {max_queue_size_seen})")
                last_backlog_warning = current_time
            elif queue_size > 20 and (current_time - last_backlog_warning) > 10:
                logger.info(f"[{capture_folder}] 📊 Queue: {queue_size} frames (peak: {max_queue_size_seen})")
                last_backlog_warning = current_time

            try:
                self.process_frame(path, filename, queue_size)
            except Exception as e:
                logger.error(f"[{capture_folder}] Worker error: {e}")
            finally:
                prev_queue_size = queue_size
                work_queue.task_done()

    def _incident_worker(self, capture_folder, incident_queue):
        """Background incident state machine + R2/Supabase I/O for one device.

        Decoupled from the frame worker on purpose: process_detection() does
        synchronous R2 uploads and Supabase create/resolve that can block for
        seconds on a Pi. Running it here keeps the frame worker free so the
        LIFO capture queue never overflows during an incident.

        The queue is coalesced (newest detection wins, older ones dropped):
        the incident state machine is wall-clock based — it only needs to be
        invoked periodically with the current detection, not once per frame —
        so dropping intermediate detections cannot miss or duplicate an
        incident, and it bounds memory if R2/Supabase is slow.
        """
        while True:
            item = incident_queue.get()
            # Coalesce: keep only the most recent pending detection.
            while not incident_queue.empty():
                try:
                    item = incident_queue.get_nowait()
                except queue.Empty:
                    break
            detection_result, host_name = item
            try:
                self.incident_manager.process_detection(
                    capture_folder, detection_result, host_name
                )
            except Exception as e:
                logger.error(f"[{capture_folder}] Incident worker error: {e}")

    def process_existing_frames(self, capture_dirs):
        """Skip startup scan - file watcher catches new frames immediately"""
        logger.info(f"Skipping startup scan ({self._watcher_type} will catch new frames immediately)")
        return
    
    def _append_to_chunk(self, capture_folder, filename, analysis_data, fps=5):
        """Append a frame to the in-memory 10-min chunk buffer.

        Called ~1/s/device. Disk is touched at most every
        _chunk_flush_interval_s, on 10-min rollover, and on shutdown — not
        per frame. See _flush_chunk_locked / _flush_dirty_chunks.
        """
        try:
            sequence = int(filename.split('_')[1].split('.')[0])

            from shared.src.lib.utils.storage_path_utils import (
                calculate_chunk_location, get_device_base_path)
            from datetime import datetime

            timestamp = analysis_data.get('timestamp') or datetime.now().isoformat()
            hour, chunk_index = calculate_chunk_location(timestamp)

            base_path = get_device_base_path(capture_folder)
            chunk_dir = os.path.join(base_path, 'metadata', str(hour))
            os.makedirs(chunk_dir, exist_ok=True)
            chunk_path = os.path.join(chunk_dir, f'chunk_10min_{chunk_index}.json')

            # Prepare frame data (extract only what we need for archive)
            frame_data = {
                'sequence': sequence,
                'timestamp': analysis_data.get('timestamp'),
                'filename': analysis_data.get('filename'),
                'blackscreen': analysis_data.get('blackscreen', False),
                'blackscreen_percentage': analysis_data.get('blackscreen_percentage', 0),
                'freeze': analysis_data.get('freeze', False),
                'freeze_diffs': analysis_data.get('freeze_diffs', [])
            }

            # ✅ OPTIMIZATION: action timestamp for zap_executor matching (1 chunk read vs 100 frame JSONs)
            if analysis_data.get('last_action_timestamp'):
                frame_data['last_action_timestamp'] = analysis_data.get('last_action_timestamp')
                frame_data['last_action_executed'] = analysis_data.get('last_action_executed')

            # ✅ OPTIMIZATION: complete zapping metadata for zap_executor (avoids reading 100 individual JSONs)
            if analysis_data.get('zapping_detected'):
                frame_data['zapping_detected'] = True
                frame_data['zapping_id'] = analysis_data.get('zapping_id')
                frame_data['zapping_channel_name'] = analysis_data.get('zapping_channel_name', '')
                frame_data['zapping_channel_number'] = analysis_data.get('zapping_channel_number', '')
                frame_data['zapping_program_name'] = analysis_data.get('zapping_program_name', '')
                frame_data['zapping_program_start_time'] = analysis_data.get('zapping_program_start_time', '')
                frame_data['zapping_program_end_time'] = analysis_data.get('zapping_program_end_time', '')
                frame_data['zapping_blackscreen_duration_ms'] = analysis_data.get('zapping_blackscreen_duration_ms', 0)
                frame_data['zapping_detection_type'] = analysis_data.get('zapping_detection_type', 'unknown')
                frame_data['zapping_confidence'] = analysis_data.get('zapping_confidence', 0.0)
                frame_data['zapping_detected_at'] = analysis_data.get('zapping_detected_at')

            now_mono = time.monotonic()
            with self._chunk_cache_lock:
                entry = self._chunk_cache.get(chunk_path)
                if entry is None:
                    # New 10-min window (or first touch after a restart).
                    # Roll over: fully persist + evict any *other* chunk this
                    # device still had open so the completed chunk is on disk.
                    for other_path, other in list(self._chunk_cache.items()):
                        if other['capture_folder'] == capture_folder and other_path != chunk_path:
                            self._flush_chunk_locked(other_path, other)
                            del self._chunk_cache[other_path]
                    # Resume an existing on-disk chunk ONLY if it is today's.
                    #
                    # calculate_chunk_location() keys the path by (hour, 10-min
                    # slot) with NO date, so metadata/{hour}/chunk_10min_{idx}
                    # .json is reused every day. By design the slot is meant to
                    # be OVERWRITTEN when it comes around again ("files
                    # naturally overwrite after 24h" — hot_cold_archiver).
                    # Blindly resuming the file is correct only for a same-day
                    # restart; resuming a *previous day's* file makes it
                    # accumulate ~600 frames/day forever (observed: 11k frames
                    # / 26 days — that unbounded N is what made the flush
                    # O(N) expensive, not the frame rate). So resume only when
                    # the existing file is from the current date; otherwise
                    # start fresh, which restores the intended slot rotation.
                    fresh = {'hour': hour, 'chunk_index': chunk_index,
                             'frames_count': 0, 'frames': []}
                    cur_date = (timestamp or '')[:10]
                    loaded = self._load_chunk_from_disk(chunk_path)
                    if loaded and cur_date:
                        last_ts = (loaded.get('end_time')
                                   or (loaded.get('frames') or [{}])[-1].get('timestamp')
                                   or '')
                        if last_ts[:10] == cur_date:
                            chunk_data = loaded
                        else:
                            logger.info(
                                f"[{capture_folder}] ↻ Rotating stale chunk slot "
                                f"{os.path.basename(chunk_path)} "
                                f"(was {last_ts[:10] or 'unknown'}, now {cur_date}) — fresh"
                            )
                            chunk_data = fresh
                    else:
                        chunk_data = fresh
                    entry = {
                        'data': chunk_data,
                        'seen': {f.get('sequence') for f in chunk_data.get('frames', [])},
                        'dirty': False,
                        'last_flush': now_mono,
                        'capture_folder': capture_folder,
                    }
                    self._chunk_cache[chunk_path] = entry

                if sequence in entry['seen']:
                    return  # duplicate (LIFO backlog re-process) — nothing to do

                entry['data']['frames'].append(frame_data)
                entry['seen'].add(sequence)
                entry['dirty'] = True

                if now_mono - entry['last_flush'] >= self._chunk_flush_interval_s:
                    self._flush_chunk_locked(chunk_path, entry)

        except Exception as e:
            logger.error(f"[{capture_folder}] ✗ Chunk append FAILED → {chunk_path if 'chunk_path' in locals() else 'unknown'}: {e}")
            raise Exception(f"Chunk append error: {e}")

    def _load_chunk_from_disk(self, chunk_path):
        """Load an existing chunk so a restart resumes it instead of
        truncating. Returns None (caller starts fresh) on any failure."""
        import json
        try:
            if os.path.exists(chunk_path):
                with open(chunk_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Chunk load failed ({chunk_path}): {e} — starting fresh")
        return None

    def _flush_chunk_locked(self, chunk_path, entry):
        """Serialize one buffered chunk to disk. Caller MUST hold
        _chunk_cache_lock.

        The O(N) sort + zapping summary moved here (once per flush, ~every
        2s) from per-append. indent dropped — the chunk is machine-read by
        zap_executor, not a human — which alone roughly halves encode cost.
        Keeps the original cross-process file lock + atomic os.replace.
        """
        if not entry.get('dirty'):
            return
        import json
        from shared.src.lib.utils.file_lock_utils import lock_file, unlock_file
        data = entry['data']
        frames = data['frames']
        frames.sort(key=lambda x: x.get('sequence', 0))
        data['frames_count'] = len(frames)
        if frames:
            data['start_time'] = frames[0].get('timestamp')
            data['end_time'] = frames[-1].get('timestamp')
        zapping_frames = [f for f in frames if f.get('zapping')]
        data['zapping_count'] = len(zapping_frames)
        if zapping_frames:
            data['zapping_sequences'] = [f['sequence'] for f in zapping_frames]
        lock_path = chunk_path + '.lock'
        try:
            with open(lock_path, 'w') as lock_fh:
                lock_file(lock_fh, exclusive=True)
                try:
                    with open(chunk_path + '.tmp', 'w') as f:
                        json.dump(data, f, separators=(',', ':'))
                    os.replace(chunk_path + '.tmp', chunk_path)
                finally:
                    unlock_file(lock_fh)
            try:
                os.remove(lock_path)
            except OSError:
                pass
            entry['dirty'] = False
            entry['last_flush'] = time.monotonic()
        except Exception as e:
            logger.error(f"[{entry.get('capture_folder')}] ✗ Chunk flush FAILED → {chunk_path}: {e}")

    def _flush_dirty_chunks(self):
        """Flush every dirty chunk buffer. Called ~every 2s by the stall
        watcher and once on shutdown so no completed metadata is lost."""
        with self._chunk_cache_lock:
            for chunk_path, entry in list(self._chunk_cache.items()):
                if entry.get('dirty'):
                    self._flush_chunk_locked(chunk_path, entry)
    
    def _add_event_duration_metadata(self, capture_folder, detection_result, current_filename, queue_size=0):
        """Add event duration tracking for all event types"""
        from datetime import datetime
        
        device_info = get_device_info_from_capture_folder(capture_folder)
        device_id = device_info.get('device_id', capture_folder)
        device_model = device_info.get('device_model', 'unknown')
        device_state = self.incident_manager.get_device_state(device_id)
        current_time = datetime.now()
        
        # ✅ LIFO BACKLOG PROTECTION: Extract current sequence
        try:
            current_sequence = int(current_filename.split('_')[1].split('.')[0])
        except:
            current_sequence = None

        # 🔁 FFMPEG COUNTER-RESET DETECTION
        # A capture stall makes the watchdog restart ffmpeg, which rewinds the
        # `capture_%09d.jpg` counter back to 1. Without handling that here,
        # last_processed_sequence stays pinned at the pre-restart high value,
        # every post-restart frame is mis-flagged as LIFO backlog, and the
        # chronological guard below permanently SKIPs closing freeze/blackscreen
        # incidents — turning a single ~10s stall into a fake multi-hour freeze.
        #
        # A genuine LIFO reorder is only a handful of frames deep (queue depth
        # ~30). A restart rewinds by the whole cycle, which is always >100
        # frames (watchdog STALE_SEC=30 + RESTART_SPACING_SEC=60 at ~5fps, and
        # observed restarts happen near seq ~350). RESET_THRESHOLD=50 sits
        # comfortably above the backlog depth and well below a real cycle, so
        # it distinguishes the two without false positives.
        SEQUENCE_RESET_THRESHOLD = 50
        if current_sequence is not None:
            prev_seq = self.last_processed_sequence.get(capture_folder, 0)
            if prev_seq - current_sequence > SEQUENCE_RESET_THRESHOLD:
                logger.warning(
                    f"[{capture_folder}] 🔁 SEQUENCE RESET: counter rewound "
                    f"{prev_seq} → {current_sequence} (ffmpeg restart); "
                    f"resyncing and abandoning stale event state"
                )
                self.last_processed_sequence[capture_folder] = current_sequence
                # The frame numbering before vs. after the restart is a hard
                # discontinuity: pre-restart frames are not comparable to
                # post-restart ones, so any incident opened before the restart
                # cannot be continued or measured. Drop it — if the underlying
                # issue is real it re-detects fresh on the new stream. This is
                # the same state mutation as a normal "Event END", minus the
                # (meaningless across a discontinuity) END duration emit.
                for _evt in ('blackscreen', 'freeze', 'audio', 'macroblocks'):
                    device_state[f'{_evt}_event_start'] = None
                    device_state[f'{_evt}_start_sequence'] = None
                device_state['freeze_clear_candidate_start'] = None
                device_state['freeze_clear_candidate_count'] = 0

        # Check if we're processing an old frame (LIFO backlog)
        is_processing_backlog = False
        if current_sequence is not None:
            last_seq = self.last_processed_sequence.get(capture_folder, 0)
            if current_sequence < last_seq:
                is_processing_backlog = True
                logger.debug(f"[{capture_folder}] 🔄 LIFO BACKLOG: Processing old frame seq={current_sequence} (last={last_seq})")
            else:
                # Update last processed sequence (only if newer)
                self.last_processed_sequence[capture_folder] = current_sequence
        
        # Track all event types with same logic
        # Freeze clear hysteresis prevents one-frame false negatives from
        # closing and reopening incidents while the picture is still frozen.
        FREEZE_CLEAR_GRACE_MS = 5000
        for event_type in ['blackscreen', 'freeze', 'audio', 'macroblocks']:
            # For audio: True=good, False=problem (inverse of other events)
            if event_type == 'audio':
                # Track audio_loss (absence of audio)
                event_active = not detection_result.get(event_type, True)  # No audio = problem
            else:
                event_active = detection_result.get(event_type, False)
            
            event_start_key = f'{event_type}_event_start'
            freeze_clear_candidate_key = 'freeze_clear_candidate_start'
            freeze_clear_count_key = 'freeze_clear_candidate_count'
            freeze_clear_file_key = 'freeze_clear_candidate_filename'  # first content frame (real recovery)

            if event_active:
                if event_type == 'freeze':
                    # Freeze confirmed again, cancel any pending clear candidate.
                    if device_state.get(freeze_clear_candidate_key):
                        device_state[freeze_clear_candidate_key] = None
                        device_state[freeze_clear_count_key] = 0
                        device_state[freeze_clear_file_key] = None
                if not device_state.get(event_start_key):
                    # ✅ LIFO BACKLOG PROTECTION: Skip event START if processing old frame
                    # This prevents starting new events when processing backlog frames
                    # Example: Frame 8099 (new) already ended freeze, then we process 8096 (old) and detect freeze start
                    # We should NOT start a new event for the old frame!
                    if is_processing_backlog and current_sequence is not None:
                        logger.warning(f"[{capture_folder}] ⏭️  SKIP {event_type.upper()} START: Processing old frame (seq={current_sequence}, backlog)")
                        logger.warning(f"[{capture_folder}]     This prevents false events from LIFO queue processing")
                        continue  # Skip this event type, move to next
                    
                    # Event START
                    device_state[event_start_key] = current_time.isoformat()
                    detection_result[f'{event_type}_event_start'] = device_state[event_start_key]
                    detection_result[f'{event_type}_event_duration_ms'] = 0
                    
                    # ✅ Store sequence number for chronological validation (all event types)
                    if current_sequence is not None:
                        device_state[f'{event_type}_start_sequence'] = current_sequence
                    
                    # ✅ ZAPPING: Copy BEFORE + FIRST frames (original + thumbnail) to cold storage
                    if event_type == 'blackscreen':
                        try:
                            from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage
                            
                            current_sequence = int(current_filename.split('_')[1].split('.')[0])
                            
                            # BEFORE frame (current - 1)
                            before_filename = f"capture_{current_sequence-1:09d}.jpg"
                            before_thumbnail_filename = f"capture_{current_sequence-1:09d}_thumbnail.jpg"
                            
                            captures_dir = get_captures_path(capture_folder)
                            thumbnails_dir = get_thumbnails_path(capture_folder)
                            
                            before_original_path = os.path.join(captures_dir, before_filename)
                            before_thumbnail_path = os.path.join(thumbnails_dir, before_thumbnail_filename)
                            
                            copied_count = 0
                            
                            # Copy BEFORE original + thumbnail
                            if os.path.exists(before_original_path):
                                before_original_cold = copy_to_cold_storage(before_original_path)
                                if before_original_cold:
                                    device_state['blackscreen_before_original_cold'] = before_original_cold
                                    copied_count += 1
                            if os.path.exists(before_thumbnail_path):
                                before_thumbnail_cold = copy_to_cold_storage(before_thumbnail_path)
                                if before_thumbnail_cold:
                                    device_state['blackscreen_before_thumbnail_cold'] = before_thumbnail_cold
                                    copied_count += 1
                            device_state['blackscreen_before_filename'] = before_filename
                            
                            # FIRST blackscreen frame (current)
                            first_filename = current_filename
                            first_thumbnail_filename = current_filename.replace('.jpg', '_thumbnail.jpg')
                            
                            first_original_path = os.path.join(captures_dir, first_filename)
                            first_thumbnail_path = os.path.join(thumbnails_dir, first_thumbnail_filename)
                            
                            # Copy FIRST original + thumbnail
                            if os.path.exists(first_original_path):
                                first_original_cold = copy_to_cold_storage(first_original_path)
                                if first_original_cold:
                                    device_state['blackscreen_start_original_cold'] = first_original_cold
                                    copied_count += 1
                            if os.path.exists(first_thumbnail_path):
                                first_thumbnail_cold = copy_to_cold_storage(first_thumbnail_path)
                                if first_thumbnail_cold:
                                    device_state['blackscreen_start_thumbnail_cold'] = first_thumbnail_cold
                                    copied_count += 1
                                else:
                                    logger.warning(f"[{capture_folder}] ⚠️  Failed to copy FIRST thumbnail: {first_thumbnail_path}")
                            else:
                                logger.warning(f"[{capture_folder}] ⚠️  FIRST thumbnail not found: {first_thumbnail_path}")
                            device_state['blackscreen_start_filename'] = first_filename
                            device_state['blackscreen_start_sequence'] = current_sequence  # 🔒 VALIDATION: Store sequence for chronological check
                            
                            logger.info(f"[{capture_folder}] 📋 BLACKSCREEN START: Copied {copied_count}/4 images to cold")
                            logger.info(f"[{capture_folder}] 📋 STORED: blackscreen_start_sequence={current_sequence}, queue_size={queue_size}")
                        except Exception as e:
                            logger.warning(f"[{capture_folder}] ⚠️  Failed to capture blackscreen START images: {e}")
                    
                    elif event_type == 'freeze':
                        try:
                            from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage
                            
                            current_sequence = int(current_filename.split('_')[1].split('.')[0])
                            
                            # BEFORE frame (current - 1)
                            before_filename = f"capture_{current_sequence-1:09d}.jpg"
                            before_thumbnail_filename = f"capture_{current_sequence-1:09d}_thumbnail.jpg"
                            
                            captures_dir = get_captures_path(capture_folder)
                            thumbnails_dir = get_thumbnails_path(capture_folder)
                            
                            before_original_path = os.path.join(captures_dir, before_filename)
                            before_thumbnail_path = os.path.join(thumbnails_dir, before_thumbnail_filename)
                            
                            copied_count = 0
                            
                            # Copy BEFORE original + thumbnail
                            if os.path.exists(before_original_path):
                                before_original_cold = copy_to_cold_storage(before_original_path)
                                if before_original_cold:
                                    device_state['freeze_before_original_cold'] = before_original_cold
                                    copied_count += 1
                            if os.path.exists(before_thumbnail_path):
                                before_thumbnail_cold = copy_to_cold_storage(before_thumbnail_path)
                                if before_thumbnail_cold:
                                    device_state['freeze_before_thumbnail_cold'] = before_thumbnail_cold
                                    copied_count += 1
                            device_state['freeze_before_filename'] = before_filename
                            
                            # FIRST freeze frame (current)
                            first_filename = current_filename
                            first_thumbnail_filename = current_filename.replace('.jpg', '_thumbnail.jpg')
                            
                            first_original_path = os.path.join(captures_dir, first_filename)
                            first_thumbnail_path = os.path.join(thumbnails_dir, first_thumbnail_filename)
                            
                            # Copy FIRST original + thumbnail
                            if os.path.exists(first_original_path):
                                first_original_cold = copy_to_cold_storage(first_original_path)
                                if first_original_cold:
                                    device_state['freeze_start_original_cold'] = first_original_cold
                                    copied_count += 1
                            if os.path.exists(first_thumbnail_path):
                                first_thumbnail_cold = copy_to_cold_storage(first_thumbnail_path)
                                if first_thumbnail_cold:
                                    device_state['freeze_start_thumbnail_cold'] = first_thumbnail_cold
                                    copied_count += 1
                                else:
                                    logger.warning(f"[{capture_folder}] ⚠️  Failed to copy FIRST freeze thumbnail: {first_thumbnail_path}")
                            else:
                                logger.warning(f"[{capture_folder}] ⚠️  FIRST freeze thumbnail not found: {first_thumbnail_path}")
                            device_state['freeze_start_filename'] = first_filename
                            device_state['freeze_start_sequence'] = current_sequence  # 🔒 VALIDATION: Store sequence for chronological check
                            
                            # 🔍 DEBUG: Log stored filenames with frame numbers
                            logger.info(f"[{capture_folder}] 📋 FREEZE START: Copied {copied_count}/4 images to cold")
                            logger.info(f"[{capture_folder}] 📋 STORED in device_state:")
                            logger.info(f"[{capture_folder}]     freeze_before_filename: {before_filename}")
                            logger.info(f"[{capture_folder}]     freeze_start_filename: {first_filename}")
                            logger.info(f"[{capture_folder}]     freeze_start_sequence: {current_sequence}")
                            logger.info(f"[{capture_folder}]     current_queue_size: {queue_size}")
                        except Exception as e:
                            logger.warning(f"[{capture_folder}] ⚠️  Failed to capture freeze START images: {e}")

                    elif event_type == 'audio':
                        # Audio loss is non-visual, but the incident manager still wants a
                        # representative frame to show (incident_manager.process_detection
                        # reads `audio_loss_start_thumbnail_cold`). Copy the current frame —
                        # the first one where audio dropped — so the alert isn't empty.
                        # NOTE: the device_state key is `audio_loss_*` (the issue_type), not
                        # `audio_*` (the event_type), to match the reader's lookup.
                        try:
                            from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage

                            captures_dir = get_captures_path(capture_folder)
                            thumbnails_dir = get_thumbnails_path(capture_folder)

                            start_thumbnail_filename = current_filename.replace('.jpg', '_thumbnail.jpg')
                            start_original_path = os.path.join(captures_dir, current_filename)
                            start_thumbnail_path = os.path.join(thumbnails_dir, start_thumbnail_filename)

                            copied_count = 0

                            # Copy START original + thumbnail to cold storage
                            if os.path.exists(start_original_path):
                                start_original_cold = copy_to_cold_storage(start_original_path)
                                if start_original_cold:
                                    device_state['audio_loss_start_original_cold'] = start_original_cold
                                    copied_count += 1
                            if os.path.exists(start_thumbnail_path):
                                start_thumbnail_cold = copy_to_cold_storage(start_thumbnail_path)
                                if start_thumbnail_cold:
                                    device_state['audio_loss_start_thumbnail_cold'] = start_thumbnail_cold
                                    copied_count += 1
                                else:
                                    logger.warning(f"[{capture_folder}] ⚠️  Failed to copy audio_loss START thumbnail: {start_thumbnail_path}")
                            else:
                                logger.warning(f"[{capture_folder}] ⚠️  audio_loss START thumbnail not found: {start_thumbnail_path}")
                            device_state['audio_loss_start_filename'] = current_filename

                            logger.info(f"[{capture_folder}] 📋 AUDIO LOSS START: Copied {copied_count}/2 images to cold ({current_filename})")
                        except Exception as e:
                            logger.warning(f"[{capture_folder}] ⚠️  Failed to capture audio_loss START images: {e}")

                    # Log event start
                    if event_type == 'audio':
                        volume = detection_result.get('mean_volume_db', -100)
                        logger.info(f"[{capture_folder}] 🔇 AUDIO LOSS started (volume={volume:.1f}dB)")
                    elif event_type == 'freeze':
                        freeze_diffs = detection_result.get('freeze_diffs', [])
                        diffs_str = f"diffs={freeze_diffs}" if freeze_diffs else "diffs=[]"
                        logger.info(f"[{capture_folder}] ⚠️  FREEZE started ({diffs_str})")
                    else:
                        logger.info(f"[{capture_folder}] ⚠️  {event_type.upper()} started")
                else:
                    # Event ONGOING
                    start = datetime.fromisoformat(device_state[event_start_key])
                    detection_result[f'{event_type}_event_start'] = device_state[event_start_key]
                    duration_ms = int((current_time - start).total_seconds() * 1000)
                    detection_result[f'{event_type}_event_duration_ms'] = duration_ms
                    
                    # Log ongoing event every 10 seconds
                    if duration_ms % 10000 < 200:  # Log approximately every 10s
                        if event_type == 'audio':
                            volume = detection_result.get('mean_volume_db', -100)
                            logger.info(f"[{capture_folder}] 🔇 AUDIO LOSS ongoing: {duration_ms/1000:.1f}s (volume={volume:.1f}dB)")
                        else:
                            logger.info(f"[{capture_folder}] ⚠️  {event_type.upper()} ongoing: {duration_ms/1000:.1f}s")
            elif device_state.get(event_start_key):
                if event_type == 'freeze':
                    # Require a sustained non-freeze period before ending freeze.
                    clear_candidate_start = device_state.get(freeze_clear_candidate_key)
                    clear_candidate_count = int(device_state.get(freeze_clear_count_key, 0) or 0)
                    if not clear_candidate_start:
                        device_state[freeze_clear_candidate_key] = current_time.isoformat()
                        device_state[freeze_clear_count_key] = 1
                        # This frame is the first one with the picture back — the REAL recovery
                        # frame, used as the "after" image (not the grace-confirmed frame ~5s later).
                        device_state[freeze_clear_file_key] = current_filename
                        logger.info(f"[{capture_folder}] ⏳ FREEZE clear candidate started (grace={FREEZE_CLEAR_GRACE_MS/1000:.1f}s)")
                        continue
                    else:
                        clear_candidate_dt = datetime.fromisoformat(clear_candidate_start)
                        clear_elapsed_ms = int((current_time - clear_candidate_dt).total_seconds() * 1000)
                        clear_candidate_count += 1
                        device_state[freeze_clear_count_key] = clear_candidate_count
                        detection_result['freeze_clear_candidate_duration_ms'] = clear_elapsed_ms
                        detection_result['freeze_clear_candidate_frames'] = clear_candidate_count
                        if clear_elapsed_ms < FREEZE_CLEAR_GRACE_MS:
                            if clear_candidate_count == 1 or clear_candidate_count % 10 == 0:
                                logger.info(
                                    f"[{capture_folder}] ⏳ FREEZE clear candidate ongoing: "
                                    f"{clear_elapsed_ms/1000:.1f}s/{FREEZE_CLEAR_GRACE_MS/1000:.1f}s "
                                    f"(frames={clear_candidate_count})"
                                )
                            continue
                        # Grace satisfied: allow freeze end below.
                        device_state[freeze_clear_candidate_key] = None
                        device_state[freeze_clear_count_key] = 0
                        logger.info(
                            f"[{capture_folder}] ✅ FREEZE clear candidate confirmed after "
                            f"{clear_elapsed_ms/1000:.1f}s ({clear_candidate_count} frames)"
                        )

                # ✅ LIFO BACKLOG PROTECTION: Check if event END makes sense chronologically
                # If processing old frame AND event started at a NEWER sequence, skip this END
                # Example: Frame 8095-8099 (freeze), frame 8099 already ended it
                # Then we process 8087 (old, from backlog) which is NOT freeze
                # Device state still has freeze_start from 8096 (newer frame processed later)
                # We should NOT end an event that started AFTER the current frame!
                if is_processing_backlog and current_sequence is not None:
                    # Get event start sequence from device_state if available
                    event_start_seq_key = f'{event_type}_start_sequence'
                    event_start_seq = device_state.get(event_start_seq_key)
                    
                    if event_start_seq and current_sequence < event_start_seq:
                        logger.warning(f"[{capture_folder}] ⏭️  SKIP {event_type.upper()} END: Event started at seq={event_start_seq}, current={current_sequence} (backlog)")
                        logger.warning(f"[{capture_folder}]     Cannot end an event that started AFTER this frame!")
                        continue  # Skip this event type
                
                # Event END
                start = datetime.fromisoformat(device_state[event_start_key])
                detection_result[f'{event_type}_event_end'] = current_time.isoformat()
                total_duration_ms = int((current_time - start).total_seconds() * 1000)
                # The REAL end of a freeze is when the picture came back — i.e. when the clear
                # candidate STARTED — not when the FREEZE_CLEAR_GRACE_MS confirmation elapsed.
                # Measuring to the confirmation counts the ~5s grace as freeze time, inflating a
                # sub-second freeze to ~5s+ and the downstream zap duration with it. clear_candidate_dt
                # is set above for any freeze that reaches this END block.
                event_real_end_dt = current_time
                # The frame whose timestamp/content marks the real end ("after" image). For a
                # freeze that's the clear-candidate (first content) frame, captured before the
                # grace; for blackscreen it's the current closure frame.
                event_recovery_filename = current_filename
                if event_type == 'freeze':
                    event_real_end_dt = clear_candidate_dt
                    event_recovery_filename = device_state.get(freeze_clear_file_key) or current_filename
                    total_duration_ms = max(0, int((clear_candidate_dt - start).total_seconds() * 1000))
                detection_result[f'{event_type}_event_total_duration_ms'] = total_duration_ms
                device_state[event_start_key] = None

                # ✅ Clear sequence tracking when event ends
                event_start_seq_key = f'{event_type}_start_sequence'
                if event_start_seq_key in device_state:
                    device_state[event_start_seq_key] = None
                if event_type == 'freeze':
                    device_state[freeze_clear_candidate_key] = None
                    device_state[freeze_clear_count_key] = 0
                    device_state[freeze_clear_file_key] = None  # captured into event_recovery_filename above
                
                # ✅ ZAPPING: Copy LAST + AFTER frames (original + thumbnail) to cold storage
                if event_type == 'blackscreen':
                    try:
                        from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage
                        
                        current_sequence = int(current_filename.split('_')[1].split('.')[0])
                        
                        captures_dir = get_captures_path(capture_folder)
                        thumbnails_dir = get_thumbnails_path(capture_folder)
                        
                        copied_count = 0
                        
                        # LAST blackscreen frame (current - 1)
                        last_filename = f"capture_{current_sequence-1:09d}.jpg"
                        last_thumbnail_filename = f"capture_{current_sequence-1:09d}_thumbnail.jpg"
                        
                        last_original_path = os.path.join(captures_dir, last_filename)
                        last_thumbnail_path = os.path.join(thumbnails_dir, last_thumbnail_filename)
                        
                        # Copy LAST original + thumbnail
                        if os.path.exists(last_original_path):
                            last_original_cold = copy_to_cold_storage(last_original_path)
                            if last_original_cold:
                                device_state['blackscreen_last_original_cold'] = last_original_cold
                                copied_count += 1
                        if os.path.exists(last_thumbnail_path):
                            last_thumbnail_cold = copy_to_cold_storage(last_thumbnail_path)
                            if last_thumbnail_cold:
                                device_state['blackscreen_last_thumbnail_cold'] = last_thumbnail_cold
                                copied_count += 1
                        device_state['blackscreen_last_filename'] = last_filename
                        
                        # AFTER frame will be handled by zapping_detector (it's the analyzed frame)
                        # Just store the filename for reference
                        device_state['blackscreen_closure_filename'] = current_filename
                        
                        logger.info(f"[{capture_folder}] 📋 BLACKSCREEN END: Copied {copied_count}/2 LAST images (AFTER=analyzed frame, copied during banner detection)")
                    except Exception as e:
                        logger.warning(f"[{capture_folder}] ⚠️  Failed to capture blackscreen END images: {e}")
                
                elif event_type == 'freeze':
                    try:
                        from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage

                        # Anchor on the REAL recovery frame (first content frame), not the
                        # grace-confirmed frame ~5s later, so LAST = last frozen frame and the
                        # AFTER frame is the true moment the picture returned.
                        current_sequence = int(event_recovery_filename.split('_')[1].split('.')[0])

                        captures_dir = get_captures_path(capture_folder)
                        thumbnails_dir = get_thumbnails_path(capture_folder)

                        copied_count = 0

                        # LAST freeze frame = the frame just before recovery
                        last_filename = f"capture_{current_sequence-1:09d}.jpg"
                        last_thumbnail_filename = f"capture_{current_sequence-1:09d}_thumbnail.jpg"
                        
                        last_original_path = os.path.join(captures_dir, last_filename)
                        last_thumbnail_path = os.path.join(thumbnails_dir, last_thumbnail_filename)
                        
                        # Copy LAST original + thumbnail
                        if os.path.exists(last_original_path):
                            last_original_cold = copy_to_cold_storage(last_original_path)
                            if last_original_cold:
                                device_state['freeze_last_original_cold'] = last_original_cold
                                copied_count += 1
                        if os.path.exists(last_thumbnail_path):
                            last_thumbnail_cold = copy_to_cold_storage(last_thumbnail_path)
                            if last_thumbnail_cold:
                                device_state['freeze_last_thumbnail_cold'] = last_thumbnail_cold
                                copied_count += 1
                        device_state['freeze_last_filename'] = last_filename

                        # AFTER frame = the real recovery frame (first content frame), analyzed
                        # for the banner by zapping_detector and shown as the "After" image.
                        device_state['freeze_closure_filename'] = event_recovery_filename
                        
                        # 🔍 DEBUG: Log stored filenames with frame numbers
                        logger.info(f"[{capture_folder}] 📋 FREEZE END: Copied {copied_count}/2 LAST images (AFTER=analyzed frame, copied during banner detection)")
                        logger.info(f"[{capture_folder}] 📋 STORED in device_state:")
                        logger.info(f"[{capture_folder}]     freeze_last_filename: {last_filename}")
                        # Log the value we actually STORE (event_recovery_filename, the real
                        # recovery frame) — not current_filename, which is the grace-confirmed
                        # frame ~5s later and made the closure look far later than it is.
                        logger.info(f"[{capture_folder}]     freeze_closure_filename: {event_recovery_filename}")
                        logger.info(f"[{capture_folder}]     freeze_end_sequence: {current_sequence}")
                        logger.info(f"[{capture_folder}]     current_queue_size: {queue_size}")
                    except Exception as e:
                        logger.warning(f"[{capture_folder}] ⚠️  Failed to capture freeze END images: {e}")
                
                # Log event end
                if event_type == 'audio':
                    volume = detection_result.get('mean_volume_db', -100)
                    logger.info(f"[{capture_folder}] 🔊 AUDIO RESTORED after {total_duration_ms/1000:.1f}s (volume={volume:.1f}dB)")
                elif event_type == 'freeze':
                    freeze_comparisons = detection_result.get('freeze_comparisons', [])
                    freeze_diffs = [c.get('difference_percentage', 0) for c in freeze_comparisons]
                    diffs_str = f"diffs={freeze_diffs}" if freeze_diffs else "diffs=[]"
                    logger.info(f"[{capture_folder}] ✅ FREEZE ended after {total_duration_ms/1000:.1f}s ({diffs_str})")
                else:
                    logger.info(f"[{capture_folder}] ✅ {event_type.upper()} ended after {total_duration_ms/1000:.1f}s")
                
                # ✅ Automatic zapping detection when blackscreen ends
                if event_type == 'blackscreen' and total_duration_ms < 10000:
                    # Trigger for blackscreens up to 10s (zapping can take time depending on signal/TV)
                    # Blackscreens > 10s are likely real incidents, not channel changes
                    logger.info(f"[{capture_folder}] Blackscreen ended ({total_duration_ms}ms) - checking for zapping...")
                    
                    # Get start filename and sequence for validation
                    blackscreen_start_filename = device_state.get('blackscreen_start_filename')
                    blackscreen_start_sequence = device_state.get('blackscreen_start_sequence', 0)
                    
                    # 🔍 DEBUG: Log what we're passing to audio check
                    logger.info(f"[{capture_folder}] 📋 RETRIEVED from device_state for audio check:")
                    logger.info(f"[{capture_folder}]     blackscreen_start_filename: {blackscreen_start_filename}")
                    logger.info(f"[{capture_folder}]     blackscreen_start_sequence: {blackscreen_start_sequence}")
                    logger.info(f"[{capture_folder}]     current_filename (END): {current_filename}")
                    
                    # 🔒 SEQUENCE VALIDATION: Ensure chronological order
                    if blackscreen_start_filename and current_filename:
                        try:
                            start_frame_num = int(blackscreen_start_filename.split('_')[1].split('.')[0])
                            end_frame_num = int(current_filename.split('_')[1].split('.')[0])
                            logger.info(f"[{capture_folder}]     start_frame_number: {start_frame_num}")
                            logger.info(f"[{capture_folder}]     end_frame_number: {end_frame_num}")
                            
                            # ❌ CRITICAL VALIDATION: Detect non-chronological processing
                            if start_frame_num > end_frame_num:
                                logger.error(f"[{capture_folder}] ❌ NON-CHRONOLOGICAL EVENT DETECTED!")
                                logger.error(f"[{capture_folder}]     start_frame ({start_frame_num}) > end_frame ({end_frame_num})")
                                logger.error(f"[{capture_folder}]     Frame difference: {start_frame_num - end_frame_num} frames")
                                logger.error(f"[{capture_folder}]     ROOT CAUSE: LIFO queue processing + backlog")
                                logger.error(f"[{capture_folder}]     IMPACT: Event processed backwards, audio check will fail")
                                logger.error(f"[{capture_folder}]     SOLUTION: Clearing stale state and ABORTING this event")
                                
                                # Clear stale blackscreen state
                                device_state['blackscreen_start_filename'] = None
                                device_state['blackscreen_start_sequence'] = None
                                device_state['blackscreen_start_time'] = None
                                
                                # Don't process this event - it's invalid
                                logger.warning(f"[{capture_folder}] ⏭️  SKIPPING zapping detection for non-chronological event")
                                continue  # Skip to next iteration (don't submit to executor)
                                
                            elif blackscreen_start_sequence and blackscreen_start_sequence >= end_frame_num:
                                # Extra validation using stored sequence
                                logger.error(f"[{capture_folder}] ❌ SEQUENCE VALIDATION FAILED!")
                                logger.error(f"[{capture_folder}]     stored_start_sequence ({blackscreen_start_sequence}) >= end_frame ({end_frame_num})")
                                logger.error(f"[{capture_folder}]     This confirms LIFO processing issue")
                                
                                # Clear stale state
                                device_state['blackscreen_start_filename'] = None
                                device_state['blackscreen_start_sequence'] = None
                                device_state['blackscreen_start_time'] = None
                                
                                logger.warning(f"[{capture_folder}] ⏭️  SKIPPING zapping detection for invalid sequence")
                                continue
                                
                        except Exception as e:
                            logger.warning(f"[{capture_folder}] Failed to parse frame numbers: {e}")
                    
                    # ✅ SKIP if already learned different pattern (e.g., device zaps on freeze, not blackscreen)
                    learned_type = device_state.get('zapping_event_type')
                    if learned_type and learned_type != 'blackscreen':
                        logger.info(f"[{capture_folder}] ⏭️  SKIP zapping check (device zaps on {learned_type}, not blackscreen)")
                        continue
                    
                    # ✅ NON-BLOCKING: Submit to thread pool (AI analysis takes ~5s, don't block frame queue!)
                    self.zapping_executor.submit(
                        self._check_for_zapping_async,
                        capture_folder=capture_folder,
                        device_id=device_id,
                        device_model=device_model,
                        current_filename=current_filename,
                        blackscreen_duration_ms=total_duration_ms,
                        blackscreen_start_filename=blackscreen_start_filename,
                        event_type='blackscreen',
                        event_end_unix=event_real_end_dt.timestamp()
                    )
                
                # ✅ Automatic zapping detection when freeze ends
                elif event_type == 'freeze' and total_duration_ms < 10000:
                    # Trigger for freezes up to 10s (zapping can take time depending on signal/TV)
                    # Freezes > 10s are likely real incidents, not channel changes
                    logger.info(f"[{capture_folder}] Freeze ended ({total_duration_ms}ms) - checking for zapping...")
                    
                    # Get start filename and sequence for validation
                    freeze_start_filename = device_state.get('freeze_start_filename')
                    freeze_start_sequence = device_state.get('freeze_start_sequence', 0)
                    
                    # 🔍 DEBUG: Log what we're passing to audio check
                    logger.info(f"[{capture_folder}] 📋 RETRIEVED from device_state for audio check:")
                    logger.info(f"[{capture_folder}]     freeze_start_filename: {freeze_start_filename}")
                    logger.info(f"[{capture_folder}]     freeze_start_sequence: {freeze_start_sequence}")
                    logger.info(f"[{capture_folder}]     current_filename (END): {current_filename}")
                    
                    # 🔒 SEQUENCE VALIDATION: Ensure chronological order
                    if freeze_start_filename and current_filename:
                        try:
                            start_frame_num = int(freeze_start_filename.split('_')[1].split('.')[0])
                            end_frame_num = int(current_filename.split('_')[1].split('.')[0])
                            logger.info(f"[{capture_folder}]     start_frame_number: {start_frame_num}")
                            logger.info(f"[{capture_folder}]     end_frame_number: {end_frame_num}")
                            
                            # ❌ CRITICAL VALIDATION: Detect non-chronological processing
                            if start_frame_num > end_frame_num:
                                logger.error(f"[{capture_folder}] ❌ NON-CHRONOLOGICAL EVENT DETECTED!")
                                logger.error(f"[{capture_folder}]     start_frame ({start_frame_num}) > end_frame ({end_frame_num})")
                                logger.error(f"[{capture_folder}]     Frame difference: {start_frame_num - end_frame_num} frames")
                                logger.error(f"[{capture_folder}]     ROOT CAUSE: LIFO queue processing + backlog")
                                logger.error(f"[{capture_folder}]     IMPACT: Event processed backwards, audio check will fail")
                                logger.error(f"[{capture_folder}]     SOLUTION: Clearing stale state and ABORTING this event")
                                
                                # Clear stale freeze state
                                device_state['freeze_start_filename'] = None
                                device_state['freeze_start_sequence'] = None
                                device_state['freeze_start_time'] = None
                                
                                # Don't process this event - it's invalid
                                logger.warning(f"[{capture_folder}] ⏭️  SKIPPING zapping detection for non-chronological event")
                                continue  # Skip to next iteration (don't submit to executor)
                                
                            elif freeze_start_sequence and freeze_start_sequence >= end_frame_num:
                                # Extra validation using stored sequence
                                logger.error(f"[{capture_folder}] ❌ SEQUENCE VALIDATION FAILED!")
                                logger.error(f"[{capture_folder}]     stored_start_sequence ({freeze_start_sequence}) >= end_frame ({end_frame_num})")
                                logger.error(f"[{capture_folder}]     This confirms LIFO processing issue")
                                
                                # Clear stale state
                                device_state['freeze_start_filename'] = None
                                device_state['freeze_start_sequence'] = None
                                device_state['freeze_start_time'] = None
                                
                                logger.warning(f"[{capture_folder}] ⏭️  SKIPPING zapping detection for invalid sequence")
                                continue
                                
                        except Exception as e:
                            logger.warning(f"[{capture_folder}] Failed to parse frame numbers: {e}")
                    
                    # ✅ SKIP if already learned different pattern (e.g., device zaps on blackscreen, not freeze)
                    learned_type = device_state.get('zapping_event_type')
                    if learned_type and learned_type != 'freeze':
                        logger.info(f"[{capture_folder}] ⏭️  SKIP zapping check (device zaps on {learned_type}, not freeze)")
                        continue
                    
                    # ✅ NON-BLOCKING: Submit to thread pool (AI analysis takes ~5s, don't block frame queue!)
                    # Analyze the REAL recovery frame (first content frame) for the banner and use
                    # it as the "after" image — not the grace-confirmed frame ~5s later.
                    self.zapping_executor.submit(
                        self._check_for_zapping_async,
                        capture_folder=capture_folder,
                        device_id=device_id,
                        device_model=device_model,
                        current_filename=event_recovery_filename,
                        blackscreen_duration_ms=total_duration_ms,  # Keep same param name (it's just event_duration)
                        blackscreen_start_filename=freeze_start_filename,  # Keep same param name (it's just event_start)
                        event_type='freeze',
                        event_end_unix=event_real_end_dt.timestamp()  # real recovery instant (grace excluded)
                    )

        # While a freeze clear-candidate grace is in progress, the picture is recovering —
        # don't keep reporting an active freeze on the overlay/issues even though individual
        # frames may still flag it. The event lifecycle above already used the per-frame value.
        if device_state.get('freeze_clear_candidate_start') and detection_result.get('freeze'):
            detection_result['freeze'] = False
            detection_result['freeze_recovering'] = True

        return detection_result

    def _find_frame_at_timestamp(self, captures_dir, target_ts):
        """Return the capture frame shown just after target_ts (the key-press time).

        Picks the first frame whose mtime is at/after the press, falling back to the
        nearest frame just before it. Frames in hot storage are written by ffmpeg, so
        mtime ≈ capture time. Hot retains ~70s, so a few-seconds-old press frame is present.
        """
        first_after = first_after_dt = None
        nearest_before = nearest_before_dt = None
        try:
            with os.scandir(captures_dir) as it:
                for e in it:
                    if not (e.name.startswith('capture_') and e.name.endswith('.jpg')):
                        continue
                    dt = e.stat().st_mtime - target_ts
                    if dt >= 0:
                        if first_after_dt is None or dt < first_after_dt:
                            first_after, first_after_dt = e.name, dt
                    elif nearest_before_dt is None or dt > nearest_before_dt:
                        nearest_before, nearest_before_dt = e.name, dt
        except FileNotFoundError:
            return None
        return first_after or nearest_before

    def _check_for_zapping_async(self, capture_folder, device_id, device_model, current_filename, blackscreen_duration_ms, blackscreen_start_filename=None, event_type='blackscreen', event_end_unix=None):
        """
        Check if blackscreen/freeze was caused by zapping (channel change).
        This happens AFTER event ends, analyzing the first normal frame.
        
        ✅ ASYNC: Runs in background thread pool to avoid blocking frame processing queue
        (AI banner analysis takes ~5 seconds - would cause major queue backlog if synchronous)
        
        ✅ LOCKING: Uses per-device lock to prevent concurrent processing of multiple events
        - If lock is already held (another event being processed), skip this one
        - Prevents race conditions where multiple events try to read last_action.json
        
        ✅ AUDIO PRE-CHECK: Checks audio in SAME 1-second TS segment where event occurred
        - If audio present → proceed with banner detection (likely zapping - TV audio during channel switch)
        - If no audio → abort (likely freeze/signal loss, not zapping)
        
        ✅ SUPPORTS: Both blackscreen and freeze event types (identical processing flow)
        
        Uses shared zapping detection utility (reuses existing banner detection AI).
        """
        # ✅ TRY TO ACQUIRE LOCK (non-blocking)
        lock = self.zapping_locks.get(capture_folder)
        if not lock:
            logger.error(f"[{capture_folder}] No lock found for device - this should not happen!")
            return
        
        # Try to acquire lock without blocking
        lock_acquired = lock.acquire(blocking=False)
        if not lock_acquired:
            logger.info(f"[{capture_folder}] ⏭️  SKIP: Another event is already being processed (frame: {current_filename})")
            logger.info(f"[{capture_folder}]     This prevents race conditions and stale action reads")
            return

        # Capture this worker's logs (thread-local — safe under the zapping
        # thread pool) so the zap report can embed a "Measurement Log" section.
        from shared.src.lib.utils.measurement_log_capture import (
            begin_measurement_log, end_measurement_log)
        begin_measurement_log()

        try:
            event_name = event_type.upper()
            logger.info(f"[{capture_folder}] 🔒 LOCK ACQUIRED - Zapping worker started for {current_filename} ({event_name} event)")
            
            # ✅ FIRST CHECK: Only detect zapping for system-triggered actions (within 10s)
            # This prevents wasting resources (audio analysis, FFmpeg, AI tokens) on manual user zaps
            action_info = self._get_action_from_device_state(capture_folder)

            # Re-anchor the action delay to the REAL recovery instant (when the picture came
            # back), not to "now" — the worker runs only after the freeze-clear grace, so the
            # default now-based time_since_action overshoots by ~the grace. Using event_end_unix
            # makes the action→content delay (and the report's Total Zap Duration) tight.
            if action_info and event_end_unix and action_info.get('last_action_timestamp'):
                action_info['time_since_action_ms'] = max(
                    0, int((event_end_unix - action_info['last_action_timestamp']) * 1000)
                )

            if not action_info:
                logger.info(f"[{capture_folder}] ⏭️  ABORT: No recent action found (> 10s old or missing)")
                logger.info(f"[{capture_folder}]     Only monitoring zaps triggered by our system")
                logger.info(f"[{capture_folder}]     Manual user zaps are not tracked")
                logger.info(f"[{capture_folder}]     Skipping all analysis (audio + banner detection)")
                
                # ✅ Write "aborted" status so zap_executor doesn't timeout
                self._write_zapping_aborted(capture_folder, current_filename, 'No recent action - not system-triggered zap')
                return

            # ✅ SECOND CHECK: Only a channel-change key produces a real zap. Other key presses
            # (navigation, OK, HOME, PLAY, …) can also cause a brief freeze/blackscreen but are
            # NOT zapping — skip them so they don't pollute zap metrics. Channel keys are
            # CHANNEL_UP / CHANNEL_DOWN; direct channel entry uses digit keys (KEY_0..KEY_9).
            action_key = (action_info.get('action_params') or {}).get('key') or action_info.get('last_action_executed')
            is_zap_key = action_key in ('CHANNEL_UP', 'CHANNEL_DOWN') or (
                isinstance(action_key, str) and (
                    action_key.isdigit() or (action_key.startswith('KEY_') and action_key[4:].isdigit())
                )
            )
            if not is_zap_key:
                logger.info(f"[{capture_folder}] ⏭️  ABORT: action '{action_key}' is not a channel-change key")
                logger.info(f"[{capture_folder}]     Only CHANNEL_UP / CHANNEL_DOWN / digit presses are treated as zaps")
                self._write_zapping_aborted(capture_folder, current_filename, f"Action '{action_key}' is not a channel-change key")
                return

            # ✅ WRITE "in_progress" marker (after action check - only if we're proceeding)
            # This allows zap_executor to wait instead of reading stale data
            self._write_zapping_in_progress(capture_folder, current_filename, blackscreen_duration_ms)
            
            # ✅ PRE-CHECK: Audio DROPOUT detection across ALL segments during event + 1 extra after
            # We merge segments from event start to end + 1 more to check if audio comes back
            logger.info(f"[{capture_folder}] 🔊 Pre-check: Checking for audio dropout across {event_name} period...")
            audio_info = self._check_segment_audio(
                capture_folder, 
                blackscreen_start_filename=blackscreen_start_filename,
                blackscreen_end_filename=current_filename  # End of blackscreen
            )
            
            # ✅ CRITICAL: Validate audio check succeeded before making decisions
            # If segments_checked is empty, audio analysis FAILED - we cannot determine if zapping
            segments_checked = audio_info.get('segments_checked', [])
            if not segments_checked or len(segments_checked) == 0:
                logger.warning(f"[{capture_folder}] ⏭️  ABORT: Audio check FAILED (no segments analyzed) - cannot determine if zapping")
                logger.warning(f"[{capture_folder}]     Possible causes: segments not found, ffmpeg error, timeout")
                logger.warning(f"[{capture_folder}]     This prevents wasting AI tokens on uncertain events")
                self._write_zapping_aborted(capture_folder, current_filename, 'Audio check failed - no segments analyzed')
                return
            
            if audio_info['has_continuous_audio']:
                # Check if it's actual audio or just constant silence
                mean_volume = audio_info.get('mean_volume_db', 0)
                silence_duration = audio_info.get('silence_duration', 0)
                
                # ✅ PROTECTION: Silence > 2s = real incident, not zapping
                # Zapping causes brief silence (0.1-1s), not extended silence
                MAX_ZAPPING_SILENCE = 2.0
                
                if silence_duration > MAX_ZAPPING_SILENCE:
                    logger.info(f"[{capture_folder}] ⏭️  ABORT: Silence too long ({silence_duration:.1f}s > {MAX_ZAPPING_SILENCE}s)")
                    logger.info(f"[{capture_folder}]     This is a REAL incident (freeze/blackscreen), not zapping")
                    logger.info(f"[{capture_folder}]     mean_volume={mean_volume:.1f}dB")
                    logger.info(f"[{capture_folder}]     Skipping banner detection to avoid wasting AI tokens")
                    
                    # ✅ Write "aborted" status so zap_executor doesn't timeout
                    self._write_zapping_aborted(capture_folder, current_filename, f'Silence too long ({silence_duration:.1f}s > {MAX_ZAPPING_SILENCE}s) - real incident')
                    return
                elif mean_volume <= -90:  # Constant silence but short (< 2s) - might be real zapping
                    logger.warning(f"[{capture_folder}] ⚠️  Constant silence detected (no audio throughout)")
                    logger.warning(f"[{capture_folder}]     mean_volume={mean_volume:.1f}dB, silence={silence_duration:.1f}s")
                    logger.warning(f"[{capture_folder}]     Proceeding with banner detection (short silence < {MAX_ZAPPING_SILENCE}s)")
                    # Continue to banner detection
                else:
                    # Actual continuous audio → ABORT (likely dark content, not zapping)
                    logger.info(f"[{capture_folder}] ⏭️  ABORT: Continuous audio detected - likely dark content, not zapping")
                    logger.info(f"[{capture_folder}]     Checked {len(segments_checked)} segments: {segments_checked}")
                    logger.info(f"[{capture_folder}]     mean_volume={mean_volume:.1f}dB, silence={silence_duration:.1f}s")
                    
                    # ✅ Write "aborted" status so zap_executor doesn't timeout
                    self._write_zapping_aborted(capture_folder, current_filename, 'Continuous audio detected')
                    return
            else:
                # Audio dropout detected → PROCEED with banner detection (likely zapping)
                # Example: 800ms audio + 200ms silence during channel switch
                logger.info(f"[{capture_folder}] ✅ Audio dropout detected - proceeding with banner detection (likely zapping)")
                logger.info(f"[{capture_folder}]     Checked {len(segments_checked)} segments: {segments_checked}")
                logger.info(f"[{capture_folder}]     mean_volume={audio_info.get('mean_volume_db', 0):.1f}dB, silence={audio_info.get('silence_duration', 0):.1f}s")
            
            # Get device_state to access transition images (same way as _add_event_duration_metadata)
            device_state = self.incident_manager.get_device_state(device_id)
            
            # ✅ READ transition image paths from device_state (already copied to cold during event tracking)
            # Support both blackscreen and freeze event types
            if event_type == 'blackscreen':
                before_frame = device_state.get('blackscreen_before_filename')
                first_frame = device_state.get('blackscreen_start_filename')
                last_frame = device_state.get('blackscreen_last_filename')
                after_frame = device_state.get('blackscreen_closure_filename', current_filename)
                
                # Read cold storage paths (already copied during blackscreen tracking)
                before_original = device_state.get('blackscreen_before_original_cold')
                before_thumbnail = device_state.get('blackscreen_before_thumbnail_cold')
                first_original = device_state.get('blackscreen_start_original_cold')
                first_thumbnail = device_state.get('blackscreen_start_thumbnail_cold')
                last_original = device_state.get('blackscreen_last_original_cold')
                last_thumbnail = device_state.get('blackscreen_last_thumbnail_cold')
            elif event_type == 'freeze':
                before_frame = device_state.get('freeze_before_filename')
                first_frame = device_state.get('freeze_start_filename')
                last_frame = device_state.get('freeze_last_filename')
                after_frame = device_state.get('freeze_closure_filename', current_filename)
                
                # Read cold storage paths (already copied during freeze tracking)
                before_original = device_state.get('freeze_before_original_cold')
                before_thumbnail = device_state.get('freeze_before_thumbnail_cold')
                first_original = device_state.get('freeze_start_original_cold')
                first_thumbnail = device_state.get('freeze_start_thumbnail_cold')
                last_original = device_state.get('freeze_last_original_cold')
                last_thumbnail = device_state.get('freeze_last_thumbnail_cold')
            
            # AFTER frame is copied by zapping_detector (it's the analyzed frame) - no need to read from device_state
            
            # ✅ FALLBACK: If thumbnails are None but we have filenames, construct paths from hot storage
            from shared.src.lib.utils.storage_path_utils import get_thumbnails_path, get_captures_path, copy_to_cold_storage
            thumbnails_dir = get_thumbnails_path(capture_folder)
            captures_dir = get_captures_path(capture_folder)
            
            if not before_thumbnail and before_frame:
                before_thumbnail_hot = os.path.join(thumbnails_dir, before_frame.replace('.jpg', '_thumbnail.jpg'))
                if os.path.exists(before_thumbnail_hot):
                    before_thumbnail = copy_to_cold_storage(before_thumbnail_hot)
                    if before_thumbnail:
                        logger.info(f"[{capture_folder}] 📸 Recovered BEFORE thumbnail from hot storage")
            
            if not first_thumbnail and first_frame:
                first_thumbnail_hot = os.path.join(thumbnails_dir, first_frame.replace('.jpg', '_thumbnail.jpg'))
                if os.path.exists(first_thumbnail_hot):
                    first_thumbnail = copy_to_cold_storage(first_thumbnail_hot)
                    if first_thumbnail:
                        logger.info(f"[{capture_folder}] 📸 Recovered FIRST thumbnail from hot storage")
            
            if not last_thumbnail and last_frame:
                last_thumbnail_hot = os.path.join(thumbnails_dir, last_frame.replace('.jpg', '_thumbnail.jpg'))
                if os.path.exists(last_thumbnail_hot):
                    last_thumbnail = copy_to_cold_storage(last_thumbnail_hot)
                    if last_thumbnail:
                        logger.info(f"[{capture_folder}] 📸 Recovered LAST thumbnail from hot storage")
            
            # Same for originals
            if not before_original and before_frame:
                before_original_hot = os.path.join(captures_dir, before_frame)
                if os.path.exists(before_original_hot):
                    before_original = copy_to_cold_storage(before_original_hot)
            
            if not first_original and first_frame:
                first_original_hot = os.path.join(captures_dir, first_frame)
                if os.path.exists(first_original_hot):
                    first_original = copy_to_cold_storage(first_original_hot)
            
            if not last_original and last_frame:
                last_original_hot = os.path.join(captures_dir, last_frame)
                if os.path.exists(last_original_hot):
                    last_original = copy_to_cold_storage(last_original_hot)

            # Single-sample transition: when the freeze/blackscreen lasts one frame, START and
            # END are the SAME capture. The end frame is often already gone from hot storage by
            # the time we copy it here, but its cold copy was made when the START was fresh — so
            # reuse the start images for the end instead of rendering "No Image" in the report.
            if last_frame and last_frame == first_frame:
                last_original = last_original or first_original
                last_thumbnail = last_thumbnail or first_thumbnail

            # ✅ AT-PRESS frame: the picture shown just after the key press. Makes the
            # press→freeze gap visible in the report — the STB often keeps the OLD channel
            # (with the destination banner overlaid) for seconds before the freeze, which is
            # what makes "Total zap" much larger than the freeze. Hot storage retains ~70s of
            # frames, so the ~few-seconds-old press frame is reliably still present here.
            at_press_frame = None
            at_press_original = None
            at_press_thumbnail = None
            action_ts = action_info.get('last_action_timestamp') if action_info else None
            if action_ts:
                try:
                    at_press_frame = self._find_frame_at_timestamp(captures_dir, action_ts)
                    if at_press_frame:
                        at_press_thumb_hot = os.path.join(thumbnails_dir, at_press_frame.replace('.jpg', '_thumbnail.jpg'))
                        if os.path.exists(at_press_thumb_hot):
                            at_press_thumbnail = copy_to_cold_storage(at_press_thumb_hot)
                        at_press_orig_hot = os.path.join(captures_dir, at_press_frame)
                        if os.path.exists(at_press_orig_hot):
                            at_press_original = copy_to_cold_storage(at_press_orig_hot)
                        logger.info(f"[{capture_folder}] 📸 AT-PRESS frame={at_press_frame} (key press → first picture)")
                except Exception as press_err:
                    logger.warning(f"[{capture_folder}] Could not capture at-press frame: {press_err}")

            # DEBUG: Log what we got from device_state
            event_name = event_type.upper()
            logger.info(f"[{capture_folder}] 📋 {event_name} transition images from device_state:")
            logger.info(f"  AT-PRESS: frame={at_press_frame}, thumbnail={at_press_thumbnail}")
            logger.info(f"  BEFORE: frame={before_frame}, thumbnail={before_thumbnail}")
            logger.info(f"  FIRST:  frame={first_frame}, thumbnail={first_thumbnail}")
            logger.info(f"  LAST:   frame={last_frame}, thumbnail={last_thumbnail}")
            logger.info(f"  AFTER:  frame={after_frame}, thumbnail=(will be copied during banner analysis)")

            # Build transition images dict (AFTER will be added by zapping_detector)
            transition_images = {
                'at_press_frame': at_press_frame,
                'at_press_original_path': at_press_original,
                'at_press_thumbnail_path': at_press_thumbnail,
                'before_frame': before_frame,
                'before_original_path': before_original,
                'before_thumbnail_path': before_thumbnail,
                'first_blackscreen_frame': first_frame,
                'first_blackscreen_original_path': first_original,
                'first_blackscreen_thumbnail_path': first_thumbnail,
                'last_blackscreen_frame': last_frame,
                'last_blackscreen_original_path': last_original,
                'last_blackscreen_thumbnail_path': last_thumbnail,
                # AFTER will be filled by zapping_detector with the analyzed frame
                'after_frame': after_frame
            }
            
            # Log which thumbnails are available (for R2 upload)
            thumbnails = [before_thumbnail, first_thumbnail, last_thumbnail]
            images_found = sum(1 for path in thumbnails if path)
            missing = []
            if not before_thumbnail: missing.append('before')
            if not first_thumbnail: missing.append('first')
            if not last_thumbnail: missing.append('last')
            
            logger.info(f"[{capture_folder}] 📸 Transition thumbnails ready: {images_found}/3" + (f", missing: {missing}" if missing else "") + " (AFTER added during banner analysis)")
            
            # 🔍 DEBUG: Show action_info being passed to zapping detector
            logger.info(f"[{capture_folder}] 📝 Action info being passed to zapping detector:")
            logger.info(f"[{capture_folder}]    last_action_executed: {action_info.get('last_action_executed')}")
            logger.info(f"[{capture_folder}]    last_action_timestamp: {action_info.get('last_action_timestamp')}")
            logger.info(f"[{capture_folder}]    time_since_action_ms: {action_info.get('time_since_action_ms')}ms")
            
            # detect_and_record_zapping does Phase 1 (detection + R2 image upload + a 'pending'
            # last_zapping.json) BEFORE the slow AI banner call, then Phase 2 enriches it with
            # channel info. So zap_executor's poll matches this action and returns detection +
            # timing + image URLs within seconds, independent of AI latency.
            result = detect_and_record_zapping(
                device_id=device_id,
                device_model=device_model,
                capture_folder=capture_folder,
                frame_filename=current_filename,
                blackscreen_duration_ms=blackscreen_duration_ms,
                action_info=action_info,
                audio_info=audio_info,  # Pass audio dropout analysis to zapping record
                transition_images=transition_images,  # ✅ NEW: Pass transition images
                transition_type=event_type  # 'freeze' | 'blackscreen' — the actual transition type
            )
            
            # Log result regardless of success/failure for debugging
            if result.get('zapping_detected'):
                channel_name = result.get('channel_name', 'Unknown')
                channel_number = result.get('channel_number', '')
                detection_type = result.get('detection_type', 'unknown')
                logger.info(f"[{capture_folder}] 📺 {detection_type.upper()} ZAPPING: {channel_name} {channel_number}")
                
                # Log R2 upload status for transition images with full URLs
                r2_images = result.get('r2_images', {})
                if r2_images:
                    uploaded = [k for k, v in r2_images.items() if v and k.endswith('_url')]
                    logger.info(f"[{capture_folder}] 📤 R2 upload: {len(uploaded)}/5 transition images uploaded to R2")
                    
                    # Log each URL (or None if missing)
                    logger.info(f"[{capture_folder}] R2 URLs:")
                    logger.info(f"  - before: {r2_images.get('before_url', 'MISSING')}")
                    logger.info(f"  - first_blackscreen: {r2_images.get('first_blackscreen_url', 'MISSING')}")
                    logger.info(f"  - last_blackscreen: {r2_images.get('last_blackscreen_url', 'MISSING')}")
                    logger.info(f"  - after: {r2_images.get('after_url', 'MISSING')}")
                    
                    if len(uploaded) < 4:
                        missing = [k.replace('_url', '') for k in ['before_url', 'first_blackscreen_url', 'last_blackscreen_url', 'after_url'] if not r2_images.get(k)]
                        logger.warning(f"[{capture_folder}] ⚠️  Missing R2 images: {missing}")
                else:
                    logger.warning(f"[{capture_folder}] ⚠️  No R2 images in result")
                
                # ✅ Cache: zapping_detector fills gap (existing frames), capture_monitor adds next 5 frames
                try:
                    original_sequence = int(current_filename.split('_')[1].split('.')[0])
                    # Use same ID format as zapping_detector (based on original frame for deduplication)
                    zap_id = result.get('id', f"zap_cache_{current_filename}")
                    self.zapping_cache[capture_folder] = {
                        'zap_data': {
                            'detected': True,
                            'id': zap_id,  # Same ID for all cache frames (deduplication)
                            'channel_name': channel_name,
                            'channel_number': channel_number,
                            'program_name': result.get('program_name', ''),
                            'program_start_time': result.get('program_start_time', ''),  # ✅ Now returned from detector
                            'program_end_time': result.get('program_end_time', ''),      # ✅ Now returned from detector
                            'blackscreen_duration_ms': blackscreen_duration_ms,
                            'transition_type': result.get('transition_type', event_type),  # 'freeze' | 'blackscreen' — drives UI label
                            'report_url': result.get('report_url'),  # Per-event zap report (R2)
                            'detection_type': detection_type,
                            'confidence': result.get('confidence', 0.0),
                            'audio_silence_duration': result.get('audio_silence_duration', 0.0),  # ✅ Now in result
                            'time_since_action_ms': result.get('time_since_action_ms'),           # ✅ Now in result
                            'total_zap_duration_ms': result.get('total_zap_duration_ms'),         # ✅ Backend calculated total
                            'original_frame': current_filename
                        },
                        'frames_remaining': 5  # Add cache to next 5 frames
                    }
                    logger.info(f"[{capture_folder}] 📋 Cache: will add to next 5 frames (safety margin)")
                except Exception as e:
                    logger.error(f"[{capture_folder}] Failed to setup cache: {e}")
                
                # ✅ LEARN: Store which event type triggers zapping (first confirmed zapping only)
                if not device_state.get('zapping_event_type'):
                    device_state['zapping_event_type'] = event_type
                    logger.info(f"[{capture_folder}] 🎓 LEARNED: Zapping is {event_type}-based (will only check {event_type} from now on)")
                
            elif result.get('error'):
                # The zap was already recorded by the preliminary detected-pending write above
                # (transition + action). A failure here is only in the AI banner / R2 / DB
                # enrichment, so do NOT downgrade it — channel info just stays empty.
                logger.warning(f"[{capture_folder}] ⚠️  Banner enrichment failed ({result.get('error')}) - zap kept as detected (channel info empty)")
            else:
                logger.info(f"[{capture_folder}] ℹ️  Zap recorded from transition; no banner enrichment available")

        except Exception as e:
            logger.error(f"[{capture_folder}] Error during banner enrichment: {e}")
            import traceback
            traceback.print_exc()
            # The zap was already recorded by the preliminary detected-pending write above;
            # an enrichment error must not downgrade it to not-detected.
        finally:
            # ✅ ALWAYS RELEASE LOCK (even if exception occurred)
            lock.release()
            event_name = event_type.upper() if 'event_type' in locals() else 'UNKNOWN'
            logger.info(f"[{capture_folder}] 🔓 LOCK RELEASED - Zapping worker finished for {current_filename} ({event_name} event)")
            end_measurement_log()
    
    def _check_segment_audio(self, capture_folder, blackscreen_start_filename=None, blackscreen_end_filename=None):
        """
        Check for audio DROPOUTS across ALL segments spanning event duration + 1 extra segment after.
        
        This merges multiple TS segments (from event start to end + 1 more) and checks audio continuity
        across the entire period. This catches audio dropouts that span segment boundaries.
        
        Works for both BLACKSCREEN and FREEZE events (parameter names use "blackscreen" for backward compat).
        
        Example:
        - Event: frame 2495-2498 (800ms at 5fps)
        - Segments: 499 (frames 2495-2499), 500 (frames 2500-2504)
        - We check: segment 499 + 500 + 501 (start + end + 1 extra after)
        - This detects if audio cuts during zapping and comes back after
        
        This is called BEFORE expensive AI banner detection to avoid false positives:
        - If continuous audio → ABORT (likely dark content with audio, not zapping)
        - If audio dropout → PROCEED with banner detection (likely zapping - audio cuts during channel switch)
        
        Args:
            capture_folder: Device folder (e.g., 'capture1')
            blackscreen_start_filename: Frame where event started (e.g., 'capture_000002495.jpg')
            blackscreen_end_filename: Frame where event ended (e.g., 'capture_000002498.jpg')
        
        Returns:
            dict: Audio analysis result with keys:
                - has_continuous_audio (bool): True if audio is continuous, False if dropout detected
                - silence_duration (float): Total silence duration in seconds
                - mean_volume_db (float): Mean volume in dB
                - segment_duration (float): Total segment duration analyzed
                - segments_checked (list): List of segment numbers checked
        """
        try:
            # 🔍 DEBUG: Log what we received
            logger.info(f"[{capture_folder}] 🔊 _check_segment_audio called:")
            logger.info(f"[{capture_folder}]     start_filename: {blackscreen_start_filename}")
            logger.info(f"[{capture_folder}]     end_filename: {blackscreen_end_filename}")
            
            if not blackscreen_start_filename or not blackscreen_end_filename:
                logger.warning(f"[{capture_folder}] Missing blackscreen start/end filenames")
                return {
                    'has_continuous_audio': False,
                    'silence_duration': 0.0,
                    'mean_volume_db': -100.0,
                    'segment_duration': 0.0,
                    'segments_checked': []
                }
            
            # Extract frame numbers from filenames
            start_frame = int(blackscreen_start_filename.split('_')[1].split('.')[0])
            end_frame = int(blackscreen_end_filename.split('_')[1].split('.')[0])
            
            # 🔍 DEBUG: Log extracted frame numbers
            logger.info(f"[{capture_folder}]     start_frame_number: {start_frame}")
            logger.info(f"[{capture_folder}]     end_frame_number: {end_frame}")
            
            # 🔒 VALIDATION: Check if chronological
            if start_frame > end_frame:
                logger.error(f"[{capture_folder}] ❌ CRITICAL: Non-chronological frame numbers in audio check!")
                logger.error(f"[{capture_folder}]     start_frame ({start_frame}) > end_frame ({end_frame})")
                logger.error(f"[{capture_folder}]     Difference: {start_frame - end_frame} frames")
                logger.error(f"[{capture_folder}]     ROOT CAUSES:")
                logger.error(f"[{capture_folder}]       1. LIFO queue processing + backlog (MOST LIKELY)")
                logger.error(f"[{capture_folder}]       2. Hot storage rotated between event start and end")
                logger.error(f"[{capture_folder}]       3. Stale data in device_state from previous event")
                logger.error(f"[{capture_folder}]       4. Frame counter wrapped around (unlikely)")
                logger.error(f"[{capture_folder}]     IMPACT: Cannot determine audio segments, results would be invalid")
                logger.error(f"[{capture_folder}]     ABORTING audio check")
                return {
                    'has_continuous_audio': False,
                    'silence_duration': 0.0,
                    'mean_volume_db': -100.0,
                    'segment_duration': 0.0,
                    'segments_checked': []  # Empty = validation failed
                }
            
            # Get segment numbers from frames
            from shared.src.lib.utils.storage_path_utils import get_device_fps, get_segment_number_from_capture, get_device_segment_duration
            device_fps = get_device_fps(capture_folder)
            segment_duration = get_device_segment_duration(capture_folder)

            logger.info(f"[{capture_folder}]     device_fps: {device_fps}, segment_duration: {segment_duration}s")

            start_segment = get_segment_number_from_capture(start_frame, device_fps, segment_duration)
            end_segment = get_segment_number_from_capture(end_frame, device_fps, segment_duration)
            
            logger.info(f"[{capture_folder}]     start_segment: {start_segment} (frame {start_frame})")
            logger.info(f"[{capture_folder}]     end_segment: {end_segment} (frame {end_frame})")
            
            # ✅ CAP AUDIO WINDOW TO ~2s: the dropout happens at the START of a channel
            # change, so we only need the first ~2s — even if a slow STB freezes for 10s.
            # Count is DURATION-AWARE so the window stays ~2s regardless of segment size
            # (2 segments @ 1s, 5 @ 0.4s); a fixed count of 2 would only cover 0.8s at 0.4s
            # and miss dropouts. Still bounded, so queue backlog can't make it analyze 9+s.
            AUDIO_WINDOW_SECONDS = 2.0
            num_segments = max(2, round(AUDIO_WINDOW_SECONDS / segment_duration)) if segment_duration else 2
            segments_to_check = [start_segment + i for i in range(num_segments)]

            logger.info(f"[{capture_folder}] Event: frames {start_frame}-{end_frame} → segments {start_segment}-{end_segment}")
            logger.info(f"[{capture_folder}] Will analyze {len(segments_to_check)} segment(s) [~{AUDIO_WINDOW_SECONDS}s window @ {segment_duration}s/seg]: {segments_to_check}")
            
            # Find all segment files
            segments_dir = get_segments_path(capture_folder)
            if not os.path.exists(segments_dir):
                logger.warning(f"[{capture_folder}] Segments directory not found: {segments_dir}")
                return {
                    'has_continuous_audio': False,
                    'silence_duration': 0.0,
                    'mean_volume_db': -100.0,
                    'segment_duration': 0.0,
                    'segments_checked': []
                }
            
            # Build segment file list (segments are .ts files in segments directory)
            segment_files = [os.path.join(segments_dir, f"segment_{seg_num:09d}.ts") for seg_num in segments_to_check]
            
            logger.info(f"[{capture_folder}] Will check {len(segment_files)} segments: {segments_to_check}")
            
            # ✅ DIAGNOSTIC: Check which segments exist and their sizes
            logger.info(f"[{capture_folder}] 📋 Segment files diagnostic:")
            available_segments = []
            missing_segments = []
            
            for seg_num in segments_to_check:
                seg_file = os.path.join(segments_dir, f"segment_{seg_num:09d}.ts")
                if os.path.exists(seg_file):
                    size_kb = os.path.getsize(seg_file) / 1024
                    logger.info(f"[{capture_folder}]   ✓ {seg_file} ({size_kb:.1f} KB)")
                    available_segments.append((seg_num, seg_file))
                else:
                    logger.warning(f"[{capture_folder}]   ✗ MISSING: {seg_file}")
                    missing_segments.append(seg_file)
            
            # ✅ RESILIENT: Use whatever segments we have (even just 1)
            if len(available_segments) == 0:
                logger.error(f"[{capture_folder}] ❌ No segments available: 0/{len(segment_files)} found")
                for missing in missing_segments:
                    logger.error(f"[{capture_folder}]   - {missing}")
                
                # ✅ SIMPLE FALLBACK: Race condition - try previous segment (start_segment - 1)
                logger.warning(f"[{capture_folder}] 🔄 RACE CONDITION: Expected segments not written yet")
                
                if start_segment > 0:
                    fallback_segment = start_segment - 1
                    fallback_path = os.path.join(segments_dir, f"segment_{fallback_segment:09d}.ts")
                    
                    if os.path.exists(fallback_path):
                        logger.warning(f"[{capture_folder}]     Using previous segment: {fallback_segment}")
                        
                        # Use the single fallback segment
                        available_segments = [(fallback_segment, fallback_path)]
                        segment_files_to_use = [fallback_path]
                        segments_used = [fallback_segment]
                        
                        logger.info(f"[{capture_folder}] 🔊 Analyzing fallback segment: {fallback_segment}")
                    else:
                        logger.error(f"[{capture_folder}] ❌ Fallback segment {fallback_segment} also missing")
                        return {
                            'has_continuous_audio': False,
                            'silence_duration': 0.0,
                            'mean_volume_db': -100.0,
                            'segment_duration': 0.0,
                            'segments_checked': []
                        }
                else:
                    logger.error(f"[{capture_folder}] ❌ Cannot fallback - start_segment is 0")
                    return {
                        'has_continuous_audio': False,
                        'silence_duration': 0.0,
                        'mean_volume_db': -100.0,
                        'segment_duration': 0.0,
                        'segments_checked': []
                    }
            else:
                # Some expected segments found - use them
                segment_files_to_use = [seg_file for _, seg_file in available_segments]
                segments_used = [seg_num for seg_num, _ in available_segments]
            
            # ✅ PARTIAL ANALYSIS: Use whatever segments we have
            if missing_segments and len(available_segments) < len(segment_files):
                logger.warning(f"[{capture_folder}] ⚠️  Partial analysis: {len(available_segments)}/{len(segment_files)} segments available")
                logger.warning(f"[{capture_folder}]     Missing: {[os.path.basename(m) for m in missing_segments]}")
                logger.info(f"[{capture_folder}]     Proceeding with available segments (better than aborting)")
            
            logger.info(f"[{capture_folder}] 🔊 Analyzing {len(segment_files_to_use)} segment(s): {segments_used}")
            
            # ✅ OPTIMIZATION: Single segment = check directly (no merge needed)
            if len(segment_files_to_use) == 1:
                single_segment = segment_files_to_use[0]
                segment_size = os.path.getsize(single_segment) / 1024
                logger.info(f"[{capture_folder}] 📁 Single segment analysis (no merge needed): {os.path.basename(single_segment)} ({segment_size:.1f} KB)")
                
                # Calculate duration for this single segment
                segment_duration = get_device_segment_duration(capture_folder)
                logger.info(f"[{capture_folder}] Analyzing single segment audio: {segment_duration:.1f}s")
                
                has_continuous_audio, silence_duration, mean_volume = check_audio_continuous(
                    file_path=single_segment,
                    sample_duration=segment_duration,
                    min_silence_duration=0.1,
                    timeout=10,
                    context=capture_folder
                )
                
                # ✅ LOG: Immediately log the raw result
                logger.info(f"[{capture_folder}] 🔊 Audio check returned: continuous={has_continuous_audio}, silence={silence_duration:.2f}s, volume={mean_volume:.1f}dB")
                
                # ✅ DISTINGUISH: Constant silence vs dropout
                # If silence_duration ≈ segment_duration → constant silence (no audio at all)
                # If silence_duration < segment_duration → true dropout (audio cut out temporarily)
                if abs(silence_duration - segment_duration) < 0.05:  # Within 50ms tolerance
                    logger.info(f"[{capture_folder}] 🔇 CONSTANT SILENCE: {silence_duration:.2f}s silence in {segment_duration:.1f}s total (mean: {mean_volume:.1f}dB)")
                    logger.info(f"[{capture_folder}]     This is NOT a dropout - no audio present at all")
                    # Treat constant silence as "continuous" (i.e., no dropout occurred)
                    has_continuous_audio = True
                elif has_continuous_audio:
                    logger.info(f"[{capture_folder}] 🔊 Audio CONTINUOUS: {mean_volume:.1f}dB (single segment)")
                else:
                    logger.info(f"[{capture_folder}] 🔇 Audio DROPOUT: {silence_duration:.2f}s silence in {segment_duration:.1f}s (mean: {mean_volume:.1f}dB)")
                
                return {
                    'has_continuous_audio': has_continuous_audio,
                    'silence_duration': silence_duration,
                    'mean_volume_db': mean_volume,
                    'segment_duration': segment_duration,
                    'segments_checked': segments_used
                }
            
            # ✅ Multiple segments: Merge and check
            logger.info(f"[{capture_folder}] 🔗 Merging {len(segment_files_to_use)} segments for audio analysis")
            
            # ✅ Use FIXED filenames (overwrite each time - no space accumulation!)
            concat_list_path = f'/tmp/{capture_folder}_concat_list.txt'
            merged_path = f'/tmp/{capture_folder}_audio_check.ts'
            
            try:
                # Write concat list (overwrites previous file)
                with open(concat_list_path, 'w') as f:
                    for seg_file in segment_files_to_use:
                        f.write(f"file '{seg_file}'\n")
                
                logger.info(f"[{capture_folder}] 📝 Concat list written to: {concat_list_path}")
                
                # Merge segments with ffmpeg (overwrites previous merged file)
                merge_cmd = [
                    'ffmpeg',
                    '-hide_banner',
                    '-loglevel', 'warning',  # Changed from 'error' to 'warning' for more details
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_list_path,
                    '-c', 'copy',
                    '-y',  # Overwrite without asking
                    merged_path
                ]
                
                logger.info(f"[{capture_folder}] 🔧 FFmpeg command: {' '.join(merge_cmd)}")
                
                result = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=10)
                
                # Clean up concat list (tiny file, but good practice)
                if os.path.exists(concat_list_path):
                    os.unlink(concat_list_path)
                
                if result.returncode != 0:
                    logger.error(f"[{capture_folder}] ❌ FFmpeg merge FAILED (exit code {result.returncode})")
                    logger.error(f"[{capture_folder}] 📋 Attempted segments: {segments_to_check}")
                    logger.error(f"[{capture_folder}] 📂 Segments directory: {segments_dir}")
                    logger.error(f"[{capture_folder}] 📝 Concat list: {concat_list_path}")
                    logger.error(f"[{capture_folder}] 📤 Output path: {merged_path}")
                    if result.stderr:
                        logger.error(f"[{capture_folder}] 🔴 FFmpeg STDERR:")
                        for line in result.stderr.strip().split('\n'):
                            logger.error(f"[{capture_folder}]     {line}")
                    if result.stdout:
                        logger.error(f"[{capture_folder}] 🔵 FFmpeg STDOUT:")
                        for line in result.stdout.strip().split('\n'):
                            logger.error(f"[{capture_folder}]     {line}")
                    
                    # ✅ Return EMPTY segments_checked so caller knows merge FAILED
                    return {
                        'has_continuous_audio': False,
                        'silence_duration': 0.0,
                        'mean_volume_db': -100.0,
                        'segment_duration': 0.0,
                        'segments_checked': []  # ✅ EMPTY = merge failed (caller will abort)
                    }
                
                # Get total duration of merged file
                merged_size = os.path.getsize(merged_path)
                logger.info(f"[{capture_folder}] Merged {len(segment_files_to_use)} segments → {merged_path} ({merged_size/1024:.1f} KB)")
                
                # Analyze merged file for audio continuity
                segment_duration = get_device_segment_duration(capture_folder) * len(segment_files_to_use)
                logger.info(f"[{capture_folder}] Analyzing merged audio: {segment_duration:.1f}s total")
                
                has_continuous_audio, silence_duration, mean_volume = check_audio_continuous(
                    file_path=merged_path,
                    sample_duration=segment_duration,  # Full duration of merged segments
                    min_silence_duration=0.1,  # Detect silence >= 100ms
                    timeout=15,  # Higher timeout for merged file
                    context=capture_folder
                )
                
                # ✅ DISTINGUISH: Constant silence vs dropout
                # If silence_duration ≈ segment_duration → constant silence (no audio at all)
                # If silence_duration < segment_duration → true dropout (audio cut out temporarily)
                if abs(silence_duration - segment_duration) < 0.05:  # Within 50ms tolerance
                    logger.info(f"[{capture_folder}] 🔇 CONSTANT SILENCE: {silence_duration:.2f}s silence in {segment_duration:.1f}s total (mean: {mean_volume:.1f}dB)")
                    logger.info(f"[{capture_folder}]     This is NOT a dropout - no audio present at all")
                    # Treat constant silence as "continuous" (i.e., no dropout occurred)
                    has_continuous_audio = True
                elif has_continuous_audio:
                    logger.info(f"[{capture_folder}] 🔊 Audio CONTINUOUS: {mean_volume:.1f}dB (no dropouts across {len(segment_files_to_use)} segments)")
                else:
                    logger.info(f"[{capture_folder}] 🔇 Audio DROPOUT detected: {silence_duration:.2f}s silence in {segment_duration:.1f}s total (mean: {mean_volume:.1f}dB)")
                
                return {
                    'has_continuous_audio': has_continuous_audio,
                    'silence_duration': silence_duration,
                    'mean_volume_db': mean_volume,
                    'segment_duration': segment_duration,
                    'segments_checked': segments_used
                }
                
            finally:
                # Clean up merged file (frees space immediately instead of waiting for next overwrite)
                if os.path.exists(merged_path):
                    try:
                        os.unlink(merged_path)
                        logger.debug(f"[{capture_folder}] Cleaned up merged audio file: {merged_path}")
                    except Exception as e:
                        logger.warning(f"[{capture_folder}] Failed to delete merged audio file: {e}")
                
                # Also clean up concat list if it still exists
                if os.path.exists(concat_list_path):
                    try:
                        os.unlink(concat_list_path)
                    except:
                        pass
            
        except Exception as e:
            logger.warning(f"[{capture_folder}] Audio check failed: {e}")
            import traceback
            traceback.print_exc()
            # On error, assume dropout detected (safer to proceed with banner detection)
            return {
                'has_continuous_audio': False,
                'silence_duration': 0.0,
                'mean_volume_db': -100.0,
                'segment_duration': 0.0,
                'segments_checked': []
            }
    
    def _write_zapping_in_progress(self, capture_folder: str, frame_filename: str, blackscreen_duration_ms: int):
        """
        Write "in_progress" marker to last_zapping.json IMMEDIATELY when detection starts.
        This allows zap_executor to poll and wait instead of reading stale data.
        
        Written before expensive AI processing (~40 seconds), updated when complete.
        
        ✅ TIMEOUT PROTECTION: Includes timestamp to detect stale markers (> 5 minutes = stale)
        """
        try:
            from shared.src.lib.utils.storage_path_utils import get_metadata_path
            from datetime import datetime
            
            metadata_path = get_metadata_path(capture_folder)
            last_zapping_path = os.path.join(metadata_path, 'last_zapping.json')
            
            in_progress_data = {
                'status': 'in_progress',
                'started_at': datetime.now().isoformat(),
                'started_at_unix': time.time(),  # ✅ ADD: Unix timestamp for timeout check
                'frame_filename': frame_filename,
                'blackscreen_duration_ms': blackscreen_duration_ms,
                'message': 'AI banner detection in progress (may take up to 40 seconds)',
                'timeout_seconds': 300  # ✅ ADD: Max time before marker is considered stale (5 minutes)
            }
            
            # Atomic write
            with open(last_zapping_path + '.tmp', 'w') as f:
                json.dump(in_progress_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(last_zapping_path + '.tmp', last_zapping_path)
            
            logger.info(f"[{capture_folder}] 📝 Written 'in_progress' marker to last_zapping.json")
            
        except Exception as e:
            logger.error(f"[{capture_folder}] Failed to write in_progress marker: {e}")
    
    def _write_zapping_aborted(self, capture_folder: str, frame_filename: str, reason: str):
        """
        Write "aborted" status when zapping detection is skipped/aborted.
        This prevents zap_executor from timing out waiting for a result.
        """
        try:
            from shared.src.lib.utils.storage_path_utils import get_metadata_path
            from datetime import datetime
            
            metadata_path = get_metadata_path(capture_folder)
            last_zapping_path = os.path.join(metadata_path, 'last_zapping.json')
            
            aborted_data = {
                'status': 'aborted',
                'zapping_detected': False,
                'aborted_at': datetime.now().isoformat(),
                'frame_filename': frame_filename,
                'reason': reason
            }
            
            # Atomic write
            with open(last_zapping_path + '.tmp', 'w') as f:
                json.dump(aborted_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(last_zapping_path + '.tmp', last_zapping_path)
            
            logger.info(f"[{capture_folder}] 📝 Written 'aborted' status to last_zapping.json: {reason}")

        except Exception as e:
            logger.error(f"[{capture_folder}] Failed to write aborted status: {e}")

    def _get_action_from_device_state(self, capture_folder):
        """Read last_action.json from hot storage (simple IPC between processes)"""
        logger.info(f"[{capture_folder}] Reading last_action.json...")
        try:
            import time
            
            # Build path using centralized utility (same as last_zapping.json)
            metadata_path = get_metadata_path(capture_folder)
            last_action_path = os.path.join(metadata_path, 'last_action.json')
            
            logger.info(f"[{capture_folder}] Path: {last_action_path}")
            
            # Check if file exists
            if not os.path.exists(last_action_path):
                logger.info(f"[{capture_folder}] ❌ File not found")
                return None
            
            # Read JSON
            with open(last_action_path, 'r') as f:
                action_data = json.load(f)
            
            # 🔍 DEBUG: Show full file content
            logger.info(f"[{capture_folder}] 📄 last_action.json content:")
            logger.info(f"[{capture_folder}]    {json.dumps(action_data, indent=2)}")
            
            action_timestamp = action_data.get('timestamp')
            if not action_timestamp:
                logger.info(f"[{capture_folder}] ❌ No timestamp in file")
                return None
            
            # Check 10s timeout
            current_time = time.time()
            time_since_action = current_time - action_timestamp
            
            if time_since_action > 10.0:
                logger.info(f"[{capture_folder}] ❌ Action too old ({time_since_action:.1f}s)")
                return None
            
            # Success
            logger.info(f"[{capture_folder}] ✅ AUTOMATIC - action: {action_data.get('command')} ({time_since_action:.1f}s ago)")
            return {
                'last_action_executed': action_data.get('command'),
                'last_action_timestamp': action_timestamp,
                'action_params': action_data.get('params', {}),
                'time_since_action_ms': int(time_since_action * 1000)
            }
                
        except Exception as e:
            logger.error(f"[{capture_folder}] Error reading last_action.json: {e}")
            return None
    
    def _fuse_motion_state(self, device_id, analysis_data):
        """Name the motion STATE from the raw motion shape + the localize result + black/freeze.

        The key discriminator for LIVE is not motion magnitude (carousel / splash / screensaver /
        picture-in-picture all move) but: full-frame distributed motion AND no UI node matched.
        A carousel or PiP still matches a node (its chrome is stable) -> stays 'ui' with a flag.
        'live' is held behind a short sustain window so a splash / scene-cut can't flip it.

        Sets analysis_data['motion']['state'] in: blackscreen | no_signal | static | ui | motion | live
        plus motion['pip'] / motion['carousel'] flags on a matched UI screen.
        """
        motion = analysis_data.get('motion')
        if not motion:
            # detector skipped motion this frame (freeze runs ~1/5) — reuse last so the overlay
            # state stays stable, like localize.
            cached = self._last_motion.get(device_id)
            if cached:
                analysis_data['motion'] = cached
            return
        kind = motion.get('kind')
        loc = analysis_data.get('localize') or {}
        matched = bool(loc.get('node'))
        frozen = bool(analysis_data.get('freeze'))

        # Motion is about MOTION only — blackscreen / no-signal have their own lines, never shown here.
        # box/band are motion SHAPES (PiP / carousel) and imply a UI screen even when localize abstains
        # on the moving content, so flag them regardless of a node match (this is why PiP was missed:
        # the flag used to require a match, but content-heavy home screens make localize abstain).
        if frozen or kind == 'static':
            raw = 'static'
        elif kind == 'box':
            raw = 'ui'                                    # compact moving region = picture-in-picture
            motion['pip'] = True
        elif kind == 'band':
            raw = 'ui'                                    # horizontal moving strip = carousel
            motion['carousel'] = True
        elif matched:
            raw = 'ui'                                    # a known screen (full/minor in-screen motion)
        elif kind == 'full':
            raw = 'live'                                  # full-frame motion + no node match
        else:
            raw = 'unknown'

        motion['raw_state'] = raw                         # ungated, for debugging
        motion['state'] = self._motion_gatekeeper(device_id, raw)
        self._last_motion[device_id] = motion

    def _motion_gatekeeper(self, device_id, raw):
        """Debounce the motion state so it doesn't flip on transient frames (a still moment in live
        TV, or localize briefly abstaining on a moving screen). A new state must persist CONFIRM
        consecutive observations to be shown; 'live' is extra-sticky (LIVE_EXIT) so a lull or a
        single localize hit doesn't drop it. Keeps a tiny per-device history (candidate + count)."""
        CONFIRM, LIVE_EXIT = 5, 10
        g = self._motion_gate.setdefault(device_id, {'shown': raw, 'cand': raw, 'n': 0})
        if raw == g['shown']:
            g['cand'], g['n'] = raw, 0                    # still on the shown state — reset pending
        else:
            g['n'] = g['n'] + 1 if raw == g['cand'] else 1
            g['cand'] = raw
            need = LIVE_EXIT if g['shown'] == 'live' else CONFIRM
            if g['n'] >= need:
                g['shown'], g['n'] = raw, 0               # candidate held long enough — switch
        return g['shown']

    def process_frame(self, captures_path, filename, queue_size=0):
        """Process a single frame - called by file watcher events"""
        from datetime import datetime  # Import at function scope to avoid shadowing issues
        
        # Log memory usage periodically (every hour)
        log_memory_usage()
        
        # Filter out temporary files and thumbnails
        # FFmpeg atomic_writing creates .tmp files first, then renames
        if '.tmp' in filename or '_thumbnail' in filename:
            return
        
        if not filename.startswith('capture_') or not filename.endswith('.jpg'):
            return
        
        frame_path = os.path.join(captures_path, filename)
        
        # CRITICAL: Write JSON metadata to metadata/ directory, not captures/
        # Get capture info to determine device folder
        if captures_path not in self.dir_to_info:
            logger.warning(f"Unknown capture path: {captures_path}")
            return
        
        info = self.dir_to_info[captures_path]
        capture_folder = info['capture_folder']
        
        # Use convenience function - no manual path building!
        metadata_path = get_metadata_path(capture_folder)
        
        # Ensure metadata directory exists with correct permissions (mode=0o777 for full access)
        # This ensures the archiver (running as different user) can move files
        os.makedirs(metadata_path, mode=0o777, exist_ok=True)
        
        # JSON file goes to metadata directory with same filename
        json_filename = filename.replace('.jpg', '.json')
        json_file = os.path.join(metadata_path, json_filename)
        
        # Check if we need to run detection (expensive) or just add audio (cheap)
        needs_detection = True
        if os.path.exists(json_file):
            try:
                with open(json_file, 'r') as f:
                    check_json = json.load(f)
                # If already analyzed, skip detection (but continue to add audio if needed)
                if check_json.get('analyzed'):
                    needs_detection = False
                    # If already has audio, skip entirely BUT update cache first!
                    if 'audio' in check_json:
                        # CRITICAL: Update cache before returning to propagate fresh audio data
                        self.audio_cache[capture_folder] = {
                            'audio': check_json['audio'],
                            'mean_volume_db': check_json.get('mean_volume_db', -100),
                            'audio_check_timestamp': check_json.get('audio_check_timestamp'),
                            'audio_segment_file': check_json.get('audio_segment_file')
                        }
                        return
            except:
                pass  # If can't read, run detection
        
        try:
            sequence = int(filename.split('_')[1].split('.')[0])
            
            # ✅ OPTIMIZATION: Get device state early to check if freeze is ongoing
            device_info = get_device_info_from_capture_folder(capture_folder)
            device_id = device_info.get('device_id', capture_folder)
            device_state = self.incident_manager.get_device_state(device_id)
            
            # ✅ INCIDENT AUDIO HANDLING: During freeze/blackscreen, always set audio=false
            # Reasons:
            # 1. We skip audio checking during incidents (performance optimization)
            # 2. Video incidents make audio state unreliable
            # 3. Showing stale "audio=true" during freeze is confusing
            has_freeze_incident = bool(device_state.get('freeze_event_start'))
            has_blackscreen_incident = bool(device_state.get('blackscreen_event_start'))
            
            # Read audio status from shared file (written by transcript_accumulator every 5-10s)
            # This ensures max 5-10s lag regardless of frame processing order
            audio_status_path = os.path.join(metadata_path, 'audio_status.json')
            if os.path.exists(audio_status_path):
                try:
                    with open(audio_status_path, 'r') as f:
                        audio_status = json.load(f)
                    new_audio = audio_status.get('audio', False)
                    new_volume = audio_status.get('mean_volume_db', -100)
                    
                    # Update cache if changed
                    if capture_folder not in self.audio_cache:
                        self.audio_cache[capture_folder] = {'audio': new_audio, 'mean_volume_db': new_volume}
                        audio_val = "✅ YES" if new_audio else "❌ NO"
                        logger.info(f"[{capture_folder}] 🔍 Audio from status file: audio={audio_val}, volume={new_volume:.1f}dB")
                    elif self.audio_cache[capture_folder].get('audio') != new_audio:
                        self.audio_cache[capture_folder] = {'audio': new_audio, 'mean_volume_db': new_volume}
                        audio_val = "✅ YES" if new_audio else "❌ NO"
                        logger.info(f"[{capture_folder}] 🔄 Audio changed: audio={audio_val}, volume={new_volume:.1f}dB")
                    else:
                        self.audio_cache[capture_folder] = {'audio': new_audio, 'mean_volume_db': new_volume}
                except:
                    pass  # Skip if file is being written
            
            # Check if JSON already exists and extract audio data early (needed for event tracking)
            existing_audio_data = {}
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r') as f:
                        existing_json = json.load(f)
                    if 'audio' in existing_json:
                        existing_audio_data = {
                            'audio': existing_json['audio'],
                            'mean_volume_db': existing_json.get('mean_volume_db', -100),
                            'audio_check_timestamp': existing_json.get('audio_check_timestamp'),
                            'audio_segment_file': existing_json.get('audio_segment_file')
                        }
                        # CRITICAL FIX: Immediately update cache when reading JSON with audio data
                        # This ensures transcript_accumulator's fresh audio data propagates to subsequent frames
                        self.audio_cache[capture_folder] = existing_audio_data
                        audio_val = "✅ YES" if existing_audio_data['audio'] else "❌ NO"
                        volume = existing_audio_data.get('mean_volume_db', -100)
                        logger.debug(f"[{capture_folder}] 🔄 Cache updated from existing JSON: audio={audio_val}, volume={volume:.1f}dB")
                except:
                    pass
            
            # Use cached audio if JSON doesn't have it yet
            if not existing_audio_data and capture_folder in self.audio_cache:
                existing_audio_data = self.audio_cache[capture_folder]
            
            # ✅ INCIDENT PRIORITY OPTIMIZATION: Skip expensive checks if another incident is ongoing
            # Check device_state to see what's currently active (already loaded above at line 1621)
            
            skip_freeze = False
            skip_blackscreen = False
            skip_macroblocks = False
            
            if needs_detection:
                # Check if blackscreen is ongoing → skip freeze and macroblocks detection
                if device_state.get('blackscreen_event_start'):
                    skip_freeze = True
                    skip_macroblocks = True
                    logger.debug(f"[{capture_folder}] ⏩ Skipping freeze/macroblocks detection (blackscreen ongoing)")
                
                # Check if freeze is ongoing → skip macroblocks detection ONLY.
                # We intentionally KEEP blackscreen detection running during a freeze: it is cheap
                # (pixel sampling) and outranks freeze. A zap that freezes on a dark frame before
                # going fully black would otherwise lock in as FREEZE forever (skip_blackscreen
                # blocked reclassification). Letting blackscreen run lets it reclassify below.
                elif device_state.get('freeze_event_start'):
                    skip_macroblocks = True
                    logger.debug(f"[{capture_folder}] ⏩ Skipping macroblocks detection (freeze ongoing)")
                
                # Calculate freeze duration for optimization (long freezes need less frequent checking)
                freeze_duration_ms = 0
                if device_state.get('freeze_event_start'):
                    freeze_start = datetime.fromisoformat(device_state['freeze_event_start'])
                    freeze_duration_ms = int((datetime.now() - freeze_start).total_seconds() * 1000)
                
                # Run detection with skip flags (avoids wasting CPU on lower-priority checks)
                detection_result = detect_issues(
                    frame_path, 
                    queue_size=queue_size, 
                    skip_freeze=skip_freeze, 
                    skip_blackscreen=skip_blackscreen,
                    skip_macroblocks=skip_macroblocks,
                    freeze_duration_ms=freeze_duration_ms  # Pass freeze duration for long-freeze optimization
                )
            else:
                # JSON exists without audio - just add audio from cache (no detection needed)
                detection_result = {}  # Empty dict to merge with existing data
            
            # Merge audio data into detection_result BEFORE event tracking
            if existing_audio_data:
                detection_result.update(existing_audio_data)
            
            # ✅ PRIORITY SUPPRESSION: Apply BEFORE event tracking to avoid unnecessary processing
            # Priority: Blackscreen > Freeze > Macroblocks
            if detection_result is not None:
                has_blackscreen = detection_result.get('blackscreen', False)
                has_freeze = detection_result.get('freeze', False)
                has_macroblocks = detection_result.get('macroblocks', False)
                
                # Suppress lower-priority events BEFORE tracking starts
                if has_blackscreen:
                    # Blackscreen has priority - suppress freeze and macroblocks
                    if has_freeze:
                        detection_result['freeze'] = False
                        logger.debug(f"[{capture_folder}] Suppressing freeze (blackscreen has priority)")
                    # RECLASSIFY freeze → blackscreen: if a freeze event is already in progress when
                    # the picture goes fully black, the frozen frames were the dark leading edge of a
                    # blackscreen, not a real freeze. Tear the freeze event down silently (no freeze
                    # zap is submitted) so the incident is tracked as a blackscreen from here. Without
                    # this the freeze sits in its clear-grace window and later closes as a mislabeled
                    # FREEZE zap on a black "after" frame.
                    if device_state.get('freeze_event_start'):
                        logger.info(f"[{capture_folder}] 🔄 RECLASSIFY freeze → blackscreen (frozen dark frames were blackscreen onset)")
                        device_state['freeze_event_start'] = None
                        device_state['freeze_start_sequence'] = None
                        device_state['freeze_clear_candidate_start'] = None
                        device_state['freeze_clear_candidate_count'] = 0
                        device_state['freeze_clear_candidate_filename'] = None
                    if has_macroblocks:
                        detection_result['macroblocks'] = False
                        logger.debug(f"[{capture_folder}] Suppressing macroblocks (blackscreen has priority)")
                elif has_freeze:
                    # Freeze has priority over macroblocks
                    if has_macroblocks:
                        detection_result['macroblocks'] = False
                        logger.debug(f"[{capture_folder}] Suppressing macroblocks (freeze has priority)")
            
            # ALWAYS add event duration tracking (needed for audio_loss even when skipping detection)
            # NOTE: Suppressed events won't trigger tracking since they're now False
            if detection_result is not None:
                detection_result = self._add_event_duration_metadata(capture_folder, detection_result, filename, queue_size)
            
            # Build issues list for logging
            issues = []
            has_blackscreen = detection_result and detection_result.get('blackscreen', False)
            has_freeze = detection_result and detection_result.get('freeze', False)
            has_macroblocks = detection_result and detection_result.get('macroblocks', False)
            
            if has_blackscreen:
                issues.append('blackscreen')
            elif has_freeze:
                issues.append('freeze')
            elif has_macroblocks:
                issues.append('macroblocks')
            
            if issues:
                logger.info(f"[{capture_folder}] Issues: {issues}")
            
            # NOTE: Comparison images (last_3_filenames, last_3_thumbnails) are ALWAYS in JSON
            # even when there's no freeze - this allows displaying them on demand later
            
            # R2 upload is now handled ONLY by incident_manager when creating/resolving DB incidents
            # This simplifies the flow and ensures timing is correct
            
            # Offload incident logic (30s report delay, R2 upload, Supabase
            # create/resolve) to the per-device incident worker so the frame
            # worker never blocks on network I/O. Pass a shallow copy so the
            # incident worker can enrich it (r2_images) without racing the
            # JSON write below. Return value (transitions) is unused.
            incident_queue = self.incident_queues.get(capture_folder)
            if incident_queue is not None and detection_result is not None:
                try:
                    incident_queue.put_nowait((dict(detection_result), self.host_name))
                except queue.Full:
                    # Rate-limit: a saturated worker drops ~5 detections/sec, which would
                    # otherwise spam thousands of identical lines. Log at most once per 5s
                    # with the accumulated drop count instead.
                    drop = self._incident_drop_state.setdefault(capture_folder, {'count': 0, 'last_log': 0.0})
                    drop['count'] += 1
                    now = time.time()
                    if now - drop['last_log'] >= 5.0:
                        logger.warning(
                            f"[{capture_folder}] Incident queue full, dropped {drop['count']} detection(s) "
                            f"(R2/Supabase slow?); time-based state machine will recover"
                        )
                        drop['count'] = 0
                        drop['last_log'] = now
            
            try:
                # Reuse existing_json if we read it earlier, otherwise read now
                existing_data = {}
                if 'existing_json' in locals() and existing_json:
                    existing_data = existing_json
                elif os.path.exists(json_file):
                    try:
                        with open(json_file, 'r') as f:
                            existing_data = json.load(f)
                    except Exception as e:
                        logger.warning(f"[{capture_folder}] Failed to read existing JSON: {e}")
                
                # Audio handling: Update cache if JSON has fresh audio data
                if existing_audio_data and 'audio' in existing_audio_data:
                    # Already extracted audio earlier - update cache
                    self.audio_cache[capture_folder] = existing_audio_data
                    audio_val = "✅ YES" if existing_audio_data['audio'] else "❌ NO"
                    volume = existing_audio_data.get('mean_volume_db', -100)
                    # Per-frame (~10fps × N devices) — DEBUG only, otherwise it floods the
                    # journal and buries real events (zapping, freeze, errors). Enable with
                    # CAPTURE_MONITOR_LOG_LEVEL=DEBUG when debugging audio detection.
                    logger.debug(f"[{capture_folder}] 🔄 Updated audio cache from {json_file}: audio={audio_val}, volume={volume:.1f}dB")
                    # Make sure existing_data has audio
                    existing_data.update(existing_audio_data)
                elif capture_folder in self.audio_cache:
                    # No audio in JSON but we have cached value - use it
                    existing_data.update(self.audio_cache[capture_folder])
                    audio_val = "✅ YES" if self.audio_cache[capture_folder]['audio'] else "❌ NO"
                    volume = self.audio_cache[capture_folder].get('mean_volume_db', -100)
                    logger.debug(f"[{capture_folder}] 📋 Using cached audio for {json_file}: audio={audio_val}, volume={volume:.1f}dB")
                
                # ✅ CHECK FOR ZAPPING CACHE: Add to next N frames after detection
                zap_cache_data = None
                if capture_folder in self.zapping_cache:
                    cache_entry = self.zapping_cache[capture_folder]
                    if cache_entry['frames_remaining'] > 0:
                        # Add cache to this frame
                        zap_data = cache_entry['zap_data']
                        sequence = int(filename.split('_')[1].split('.')[0])
                        zap_cache_data = {
                            'detected': True,
                            'id': zap_data['id'],  # Same ID for all cache frames (deduplication)
                            'channel_name': zap_data['channel_name'],
                            'channel_number': zap_data['channel_number'],
                            'program_name': zap_data['program_name'],
                            'program_start_time': zap_data['program_start_time'],  # ✅ Now populated
                            'program_end_time': zap_data['program_end_time'],      # ✅ Now populated
                            'blackscreen_duration_ms': zap_data['blackscreen_duration_ms'],
                            'transition_type': zap_data.get('transition_type', 'blackscreen'),  # 'freeze' | 'blackscreen' — drives UI label
                            'report_url': zap_data.get('report_url'),  # Per-event zap report (R2)
                            'detection_type': zap_data['detection_type'],
                            'confidence': zap_data['confidence'],
                            'detected_at': datetime.now().isoformat(),
                            'audio_silence_duration': zap_data['audio_silence_duration'],
                            'time_since_action_ms': zap_data.get('time_since_action_ms'),      # ✅ ADD: For calculation
                            'total_zap_duration_ms': zap_data.get('total_zap_duration_ms'),    # ✅ ADD: Backend calculated
                            'original_frame': zap_data['original_frame']
                        }
                        
                        # Track frames for logging
                        if 'frames_list' not in cache_entry:
                            cache_entry['frames_list'] = []
                        cache_entry['frames_list'].append(json_file)
                        cache_entry['frames_remaining'] -= 1
                        logger.debug(f"[{capture_folder}] 📋 Added zap_cache to {json_file} ({5 - cache_entry['frames_remaining']}/5)")
                        
                        # Clean up if done
                        if cache_entry['frames_remaining'] <= 0:
                            frames_list = ', '.join(cache_entry['frames_list'])
                            logger.info(f"[{capture_folder}] ✅ Cache safety margin complete (5 frames): {frames_list}")
                            del self.zapping_cache[capture_folder]
                
                if detection_result:
                    # Determine if transcription is worthwhile (skip if incidents present or no audio)
                    freeze = detection_result.get('freeze', False)
                    blackscreen = detection_result.get('blackscreen', False)
                    has_audio = existing_data.get('audio', True)  # Default to True if not yet checked
                    
                    # Skip transcription if freeze, blackscreen, or no audio
                    transcription_needed = not (freeze or blackscreen or not has_audio)
                    
                    # Determine skip reason for logging
                    skip_reason = None
                    if freeze:
                        skip_reason = "freeze"
                    elif blackscreen:
                        skip_reason = "blackscreen"
                    elif not has_audio:
                        skip_reason = "no_audio"
                    
                    analysis_data = {
                        "analyzed": True,
                        "subtitle_ocr_pending": True,
                        "transcription_needed": transcription_needed,
                        "skip_reason": skip_reason,
                        **existing_data,  # Includes audio from cache or JSON
                        **detection_result  # Merge detection results (overwrites if keys conflict)
                    }
                else:
                    analysis_data = {
                        "analyzed": True,
                        "subtitle_ocr_pending": True,
                        **existing_data,  # Includes audio from cache or JSON
                        "error": "detection_result_was_none"
                    }
                
                # ✅ ADD CACHE TO ANALYSIS DATA (if available)
                if zap_cache_data:
                    analysis_data['zap_cache'] = zap_cache_data

                # ✅ LOCALIZE: identify the current screen (opt-in per device via
                # DEVICE{N}_USERINTERFACE). The actual matching runs OFF this loop in a
                # background thread (_localize_worker) so its OCR/translate cost never
                # touches freeze/blackscreen latency — here we only record the latest
                # frame for that thread and attach the last result it computed. Always
                # attached when enabled (stable "Screen:" line); disabled devices have
                # no cache entry → no field → overlay hides the line.
                self._latest_frame[device_id] = frame_path
                if device_id in self._last_localize:
                    analysis_data['localize'] = self._last_localize[device_id]

                # MOTION STATE: fuse the raw motion shape (detector) with the localize result so
                # full-frame motion with NO matched node = live TV, while a carousel / PiP (which
                # still match a node) stay 'ui' with a flag.
                self._fuse_motion_state(device_id, analysis_data)

                _atomic_write_json(json_file, data=analysis_data)
                
                # Log successful individual JSON creation
                sequence = int(filename.split('_')[1].split('.')[0])
                has_r2_images = 'r2_images' in analysis_data and analysis_data['r2_images']
                if has_r2_images:
                    r2_count = len(analysis_data.get('r2_images', {}).get('thumbnail_urls', []))
                    logger.info(f"[{capture_folder}] ✓ Created JSON → {json_file} (seq={sequence}, r2_urls={r2_count})")
                else:
                    logger.debug(f"[{capture_folder}] ✓ Created JSON → {json_file} (seq={sequence})")
                
                # Append to chunk: 1 frame per second only (HLS displays at 1-second granularity)
                # OPTIMIZATION: Skip chunk append during backlog to reduce I/O and lock contention
                if sequence % 5 == 0 and queue_size <= 30:
                    try:
                        self._append_to_chunk(capture_folder, filename, analysis_data)
                    except Exception as e:
                        logger.warning(f"[{capture_folder}] Chunk append failed: {e}")
                    
            except Exception as e:
                logger.error(f"[{capture_folder}] Error saving: {e}")
                _atomic_write_json(
                    json_file,
                    raw_text='{"analyzed": true, "subtitle_ocr_pending": true, "error": "failed_to_save_full_data"}'
                )
        
        except Exception as e:
            logger.error(f"[{capture_folder}] Error: {e}")
            _atomic_write_json(
                json_file,
                data={"analyzed": True, "subtitle_ocr_pending": True, "error": str(e)}
            )
    
    def _handle_file_event(self, path, filename):
        """Handle file event from either inotify or watchdog - enqueue for processing"""
        if path in self.dir_to_info:
            capture_folder = self.dir_to_info[path]['capture_folder']

            # Stall observability: record this arrival and surface recovery
            # if we were previously flagged as stalled. See _run_stall_watcher.
            now_mono = time.monotonic()
            self.last_frame_arrival[capture_folder] = now_mono
            self.last_frame_filename[capture_folder] = filename
            if self.stall_state.get(capture_folder):
                stalled_for = now_mono - self.stall_started_at.get(capture_folder, now_mono)
                logger.warning(
                    f"[{capture_folder}] ✅ CAPTURE RESUMED after {stalled_for:.1f}s stall (new: {filename})"
                )
                self.stall_state[capture_folder] = False

            # Parse the sequence once here, thread it through the queue tuple
            # so the worker side doesn't re-parse the filename. The capture
            # filenames follow `capture_%09d.jpg`; anything else we tolerate
            # with sequence=None.
            try:
                sequence = int(filename.split('_')[1].split('.')[0])
            except Exception:
                sequence = None

            # Tracing lines demoted to DEBUG — previously emitted at INFO on
            # every frame (3 lines × ~20 frames/s = 60 log calls/s), which
            # was ~5 ms/s of CPU just for logging and flooded the journal.
            logger.debug(f"[{capture_folder}] 📥 FILE ARRIVED: {filename} (seq={sequence})")

            work_queue = self.device_queues[capture_folder]
            queue_size = work_queue.qsize()

            # Don't fill queue if >150 (images may be deleted from hot storage before processing)
            if queue_size > 150:
                logger.warning(
                    f"[{capture_folder}] ⏭️  Queue over 150 ({queue_size}), SKIPPING {filename} "
                    f"(seq={sequence}) - images may expire"
                )
            else:
                try:
                    logger.debug(
                        f"[{capture_folder}] 📤 QUEUED: {filename} "
                        f"(seq={sequence}, queue_size={queue_size} → {queue_size+1})"
                    )
                    work_queue.put_nowait((path, filename, sequence))

                    if queue_size > 100:
                        logger.warning(f"[{capture_folder}] 🔴 Queue backlog: {queue_size}/1000 frames")
                    elif queue_size > 50 and queue_size % 25 == 0:
                        logger.warning(f"[{capture_folder}] 🟡 Queue backlog: {queue_size}/1000 frames")

                except queue.Full:
                    logger.error(f"[{capture_folder}] 🚨 Queue FULL, dropping: {filename}")
    
    def _run_stall_watcher(self):
        """Warn once when a device stops producing jpg frames for > threshold.

        FFmpeg can keep its HLS branch alive while the image2 branch silently
        stalls (see docs/agent/devices/FFMPEG_TROUBLESHOOT.md). We already track each
        arrival in _handle_file_event — this thread just sweeps the timestamps
        every few seconds so a stall shows up in our own logs with timestamps
        precise enough to correlate with the takeScreenshot failures.

        Cost: O(devices) work per tick, no filesystem calls.
        """
        check_interval_s = 2.0
        while True:
            try:
                time.sleep(check_interval_s)
                now_mono = time.monotonic()
                for capture_folder, last_seen in list(self.last_frame_arrival.items()):
                    age = now_mono - last_seen
                    if age >= self.stall_warn_threshold_s:
                        if not self.stall_state.get(capture_folder):
                            self.stall_state[capture_folder] = True
                            self.stall_started_at[capture_folder] = last_seen
                            last_name = self.last_frame_filename.get(capture_folder, '?')
                            logger.warning(
                                f"[{capture_folder}] ⚠️  CAPTURE STALL: "
                                f"no new frames for {age:.1f}s (last: {last_name})"
                            )
                # Coalesced chunk persistence (see __init__). Runs on the same
                # 2s cadence; also covers devices that stopped producing frames
                # (their last buffer still gets flushed here).
                self._flush_dirty_chunks()
            except Exception as e:
                logger.error(f"[stall_watcher] tick error: {e}")

    def run(self):
        """Main event loop - enqueue frames for worker threads"""
        logger.info(f"Starting {self._watcher_type} event loop (zero CPU when idle)...")
        logger.info("Waiting for FFmpeg to write new frames...")

        # Background observer that surfaces FFmpeg jpg-branch stalls. Daemon
        # so it dies with the main thread on shutdown.
        stall_thread = threading.Thread(
            target=self._run_stall_watcher,
            daemon=True,
            name='capture-stall-watcher',
        )
        stall_thread.start()

        if IS_LINUX:
            self._run_inotify()
        else:
            self._run_watchdog()
    
    def _run_inotify(self):
        """Linux inotify event loop"""
        try:
            for event in self.inotify.event_gen(yield_nones=False):
                (_, type_names, path, filename) = event
                
                # IN_MOVED_TO = atomic file move (FFmpeg atomic_writing)
                if 'IN_MOVED_TO' in type_names:
                    self._handle_file_event(path, filename)
                        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            # Persist any buffered chunk metadata before exit.
            try:
                self._flush_dirty_chunks()
            except Exception as e:
                logger.error(f"Final chunk flush failed: {e}")
            for path in self.dir_to_info.keys():
                try:
                    self.inotify.remove_watch(path)
                except:
                    pass
    
    def _run_watchdog(self):
        """macOS/cross-platform watchdog event loop"""
        monitor = self  # Reference for event handler
        
        class CaptureEventHandler(FileSystemEventHandler):
            """Handle file system events - specifically atomic file moves"""
            
            def on_moved(self, event):
                """Called when a file is moved/renamed (FFmpeg atomic_writing)"""
                if event.is_directory:
                    return
                
                # Get destination path (the final file location)
                dest_path = event.dest_path
                path = os.path.dirname(dest_path)
                filename = os.path.basename(dest_path)
                
                # Only process image files
                if filename.endswith(('.jpg', '.jpeg', '.png')):
                    monitor._handle_file_event(path, filename)
            
            def on_created(self, event):
                """Fallback: handle created events for non-atomic writes"""
                if event.is_directory:
                    return
                
                path = os.path.dirname(event.src_path)
                filename = os.path.basename(event.src_path)
                
                # Only process image files (skip temp files)
                if filename.endswith(('.jpg', '.jpeg', '.png')) and not filename.startswith('.'):
                    # Small delay to ensure file is fully written
                    time.sleep(0.05)
                    monitor._handle_file_event(path, filename)
        
        event_handler = CaptureEventHandler()
        
        # Schedule watches for all capture directories
        for path in self.dir_to_info.keys():
            if os.path.exists(path):
                self.observer.schedule(event_handler, path, recursive=False)
                logger.info(f"Watchdog watching: {path}")
        
        try:
            self.observer.start()
            logger.info("Watchdog observer started")
            
            # Keep running until interrupted
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.observer.stop()
            self.observer.join()

def cleanup_stale_zapping_markers():
    """
    Clean up any stale zapping detection markers left by crashed/stuck processes.
    
    Stale markers (in_progress > 5 minutes old) can cause high CPU and block detection.
    This runs once at startup to ensure clean state.
    """
    try:
        logger.info("🧹 [STARTUP] Checking for stale zapping markers...")
        
        base_dirs = get_capture_base_directories()
        cleaned_count = 0
        checked_count = 0
        
        for base_dir in base_dirs:
            capture_folder = get_capture_folder(base_dir)
            checked_count += 1
            
            try:
                metadata_path = get_metadata_path(capture_folder)
                last_zapping_path = os.path.join(metadata_path, 'last_zapping.json')
                
                if os.path.exists(last_zapping_path):
                    with open(last_zapping_path, 'r') as f:
                        zapping_data = json.load(f)
                    
                    status = zapping_data.get('status')
                    if status == 'in_progress':
                        # Check if stale (> 5 minutes old)
                        started_at_unix = zapping_data.get('started_at_unix')
                        timeout_seconds = zapping_data.get('timeout_seconds', 300)
                        
                        if started_at_unix:
                            age_seconds = time.time() - started_at_unix
                            if age_seconds > timeout_seconds:
                                # STALE - remove it
                                os.remove(last_zapping_path)
                                cleaned_count += 1
                                logger.warning(f"🗑️  [{capture_folder}] Removed STALE marker (age: {age_seconds:.0f}s > {timeout_seconds}s)")
                            else:
                                logger.info(f"⏳ [{capture_folder}] Found recent in_progress marker (age: {age_seconds:.0f}s) - keeping")
                        else:
                            # No timestamp - assume stale (old format)
                            os.remove(last_zapping_path)
                            cleaned_count += 1
                            logger.warning(f"🗑️  [{capture_folder}] Removed STALE marker (no timestamp)")
            
            except Exception as e:
                logger.warning(f"⚠️  [{capture_folder}] Error checking marker: {e}")
                continue
        
        if cleaned_count > 0:
            logger.info(f"✅ [STARTUP] Cleaned {cleaned_count}/{checked_count} stale zapping markers")
        else:
            logger.info(f"✅ [STARTUP] No stale markers found ({checked_count} devices checked)")
    
    except Exception as e:
        logger.error(f"❌ [STARTUP] Error during stale marker cleanup: {e}")

def main():
    """Main entry point"""
    
    # Kill any existing capture_monitor instances before starting
    from shared.src.lib.utils.system_utils import kill_existing_script_instances
    killed = kill_existing_script_instances('capture_monitor.py')
    if killed:
        logger.info(f"Killed existing capture_monitor instances: {killed}")
        time.sleep(1)

    # Quiet by default on the live 5fps path; raise verbosity on demand with
    # `sudo pkill -USR1 -f capture_monitor.py` (SIGUSR2 to restore). No restart.
    from shared.src.lib.utils.log_control import install_runtime_log_control
    install_runtime_log_control('CAPTURE_MONITOR_LOG_LEVEL')

    logger.info("=" * 80)
    watcher_name = "inotify" if IS_LINUX else "watchdog"
    logger.info(f"Starting {watcher_name}-based incident monitor ({platform.system()})")
    logger.info("Performance: Zero CPU when idle, event-driven processing")
    logger.info("No directory scanning = 95% CPU reduction vs polling")
    logger.info("Queue Strategy: LIFO (newest frames first) - ensures real-time analysis")
    logger.info("=" * 80)
    
    # ✅ STARTUP CLEANUP: Clear any stale zapping markers from previous crashed instances
    cleanup_stale_zapping_markers()
    
    host_name = os.getenv('HOST_NAME', 'unknown')
    
    # Get base directories and resolve hot/cold paths automatically
    base_dirs = get_capture_base_directories()
    capture_dirs = []
    
    for base_dir in base_dirs:
        # Extract device folder name (e.g., 'capture1' from '/var/www/html/stream/capture1')
        device_folder = os.path.basename(base_dir)
        # Use convenience function - no manual path building!
        capture_path = get_captures_path(device_folder)
        capture_dirs.append(capture_path)
    
    logger.info(f"Found {len(capture_dirs)} capture directories")
    for capture_dir in capture_dirs:
        # Check if it's hot or cold storage
        storage_type = "HOT (RAM)" if '/hot/' in capture_dir else "COLD (SD)"
        capture_folder = get_capture_folder(capture_dir)  # Use centralized utility
        logger.info(f"Monitoring [{storage_type}]: {capture_dir} -> {capture_folder}")
    
    # Auto-resolve orphaned incidents for capture folders no longer being monitored
    # Use centralized utility to extract capture folder names (handles both hot and cold paths)
    monitored_capture_folders = []
    for capture_dir in capture_dirs:
        capture_folder = get_capture_folder(capture_dir)  # Use centralized utility
        monitored_capture_folders.append(capture_folder)
    
    incident_manager = IncidentManager()
    incident_manager.cleanup_orphaned_incidents(monitored_capture_folders, host_name)
    
    # Start monitoring (blocks forever, zero CPU when idle!)
    monitor = FrameMonitor(capture_dirs, host_name)
    monitor.run()
        
if __name__ == '__main__':
    main() 
