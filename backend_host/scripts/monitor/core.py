"""vpt-monitor-img core (TASK-90): discovery, per-device queues and workers, JSON write, chunks,
incident hand-off. What is detected is done by the profile analyzers (monitor/analyzers).
Started by backend_host/scripts/capture_monitor.py.

Original module docstring:

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

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from shared.src.lib.utils.storage_path_utils import (
    get_capture_base_directories, 
    parse_active_captures_conf,
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
import cv2
# OpenCV's own thread pool (pthreads backend, NOT governed by OMP_NUM_THREADS
# above) defaults to one worker per CPU. On 320x180 thumbnails each parallel_for
# costs more in pool wake/spin than it saves: on an 8-thread host the 7 pool
# workers burned ~half of the monitor's CPU (OPTIMIZATION.md §6). Parallelism
# here comes from the per-device threads instead (cv2 releases the GIL).
cv2.setNumThreads(0)
from incident_manager import IncidentManager
from monitor import img_telemetry

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
logger = logging.getLogger('capture_monitor')


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

from monitor.util import AUDIO_STATUS_MAX_AGE_S, _format_volume_db

from monitor.analyzers import build_analyzers
from monitor.analyzers.tv_app import cleanup_stale_zapping_markers
from monitor.context import FrameContext
from incident_manager import TV_INCIDENT_TYPES
from monitor.profiles import load_profile_or_default
from shared.src.lib.utils.monitor_profile import folders_needing_service, resolve_monitor_profile


class FrameMonitor:
    """Event-driven frame monitor with per-device queue processing
    
    Cross-platform: Uses inotify on Linux, watchdog on macOS
    """

    def __init__(self, capture_dirs, host_name):
        self.host_name = host_name
        self.incident_manager = IncidentManager()

        # One profile and analyzer set per device (TASK-90). A device whose profile cannot start (a missing or
        # corrupt model file, a broken manifest) is left out and retried on the 10 s rescan; it never stops the
        # monitoring of the other devices, and FrameMonitor itself never fails because of it.
        self.device_profile = {}     # capture_folder -> Profile
        self.device_analyzers = {}   # capture_folder -> [Analyzer] (instances are shared by devices with the same profile)
        self._analyzers_by_profile = {}
        self._profile_errors = {}    # capture_folder -> last error logged (one log line per distinct error)
        # active_captures.conf is re-read this often so a grabber that run_ffmpeg.sh
        # appended after we started is still picked up (BUG-0220). Set before the first
        # _assign_profile: its error log quotes it, and a device that fails at startup
        # must be left out, not crash the monitor of the whole host.
        self.dir_rescan_interval_s = 10.0
        for capture_dir in capture_dirs:
            self._assign_profile(capture_dir)

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

        # TASK-157: image telemetry. Created on the first frame of a device whose profile has img.telemetry (tv_app),
        # unless the host kill switch IMG_TELEMETRY=false is set. Counters only, see monitor/img_telemetry.py.
        self.telemetry = None
        self._telemetry_allowed = img_telemetry.enabled()
        self._telemetry_lock = threading.Lock()
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
        # The flush re-encodes the WHOLE chunk, so its cost grows with the chunk: an egg-belt chunk
        # (5 fps x 180 boxes a frame) reaches ~40 MB and every 2 s took a fifth of the process,
        # under the GIL the detector thread needs (BUG-0917). A chunk waits at least this many
        # times its own last encode time between flushes, so persistence stays ~5 % of the CPU
        # whatever the chunk holds; a small chunk still flushes every 2 s.
        self._chunk_flush_cost_ratio = 20.0

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

        # Capture dirs that have a live file watch. A registered dir can lack one when it
        # did not exist yet at startup; _rescan_capture_dirs retries it.
        self._watched_dirs = set()
        self._missing_logged = set()
        self._watchdog_handler = None  # macOS: set in _run_watchdog, then watches are scheduled
        self._last_dir_rescan = time.monotonic()

        for analyzers in self._analyzers_by_profile.values():
            for analyzer in analyzers:
                analyzer.start()

        for capture_dir in capture_dirs:
            self._register_capture_dir(capture_dir)

        self.process_existing_frames(capture_dirs)

    def _assign_profile(self, capture_dir):
        """Resolve the profile of the device behind this capture dir and build (or reuse) its analyzers."""
        capture_folder = get_capture_folder(capture_dir)
        try:
            info = get_device_info_from_capture_folder(capture_folder)
            profile = load_profile_or_default(resolve_monitor_profile(info.get('device_index')))
            analyzers = self._analyzers_by_profile.get(profile.name)
            if analyzers is None:
                analyzers = build_analyzers(self, profile)
                self._analyzers_by_profile[profile.name] = analyzers
        except Exception as e:  # noqa: BLE001 - FileNotFoundError, cv2.error on a corrupt model, a broken manifest...
            if self._profile_errors.get(capture_folder) != str(e):
                self._profile_errors[capture_folder] = str(e)
                logger.error(f"[{capture_folder}] cannot start this device's monitor profile, device left out "
                             f"(retried every {self.dir_rescan_interval_s:.0f}s): {e}")
            return None
        self._profile_errors.pop(capture_folder, None)
        self.device_profile[capture_folder] = profile
        self.device_analyzers[capture_folder] = analyzers
        self.incident_manager.set_profile(
            info.get('device_id', capture_folder), profile.name,
            TV_INCIDENT_TYPES if profile.name == 'tv_app' else profile.incidents.keys())
        logger.info(f"[{capture_folder}] Monitor profile: {profile.name}")
        return capture_folder

    def _init_device(self, capture_dir):
        """Directory bookkeeping plus the device's profile state; no thread, no watch (the replay test calls this)."""
        # Use centralized path utilities (handles both hot and cold storage)
        capture_folder = get_capture_folder(capture_dir)
        if capture_folder not in self.device_analyzers and self._assign_profile(capture_dir) is None:
            return None   # nothing is recorded for a device that cannot run: no dir_to_info, no queue, no watch
        
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
        for analyzer in self.device_analyzers[capture_folder]:
            analyzer.register_device(capture_folder)   # per-device analyzer state (tv_app: the zapping lock)
        return capture_folder

    def _register_capture_dir(self, capture_dir):
        """Watch one capture dir and start its frame + incident workers."""
        capture_folder = self._init_device(capture_dir)
        if capture_folder is None:
            return
        
        # LIFO queue (stack) - process newest frames first to avoid stale analysis
        work_queue = LifoQueue(maxsize=1000)
        self.device_queues[capture_folder] = work_queue
        
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

        # Last: the watch may deliver events at once (watchdog calls back on its own
        # thread), and _handle_file_event needs this dir's queue to exist.
        self._add_watch(capture_dir)

    def _add_watch(self, capture_dir):
        """Start watching capture_dir if it exists. Returns True when watched."""
        if capture_dir in self._watched_dirs:
            return True
        if not os.path.exists(capture_dir):
            if capture_dir not in self._missing_logged:
                self._missing_logged.add(capture_dir)
                logger.warning(f"Directory not found: {capture_dir} (retried every "
                               f"{self.dir_rescan_interval_s:.0f}s)")
            return False
        if IS_LINUX:
            self.inotify.add_watch(capture_dir)
        elif self._watchdog_handler is not None:
            self.observer.schedule(self._watchdog_handler, capture_dir, recursive=False)
        else:
            return False  # macOS: _run_watchdog schedules every registered dir on start
        self._watched_dirs.add(capture_dir)
        self._missing_logged.discard(capture_dir)
        logger.info(f"Watching: {capture_dir} -> {self.dir_to_info[capture_dir]['capture_folder']}")
        return True

    def _maybe_rescan_capture_dirs(self):
        """Pick up capture dirs added to active_captures.conf after startup.

        run_ffmpeg.sh rewrites active_captures.conf one grabber at a time while
        vpt-monitor-img may already be starting (a cascaded restart starts them within
        seconds). The list read in main() can therefore miss the last grabbers, and
        nothing else would ever add them: that device's frames were then never
        analysed while ffmpeg, the stall watcher and systemd all looked healthy
        (BUG-0220). Re-reading the conf is a small file read every ~10s; dirs are
        only ever added here, never removed.
        """
        now = time.monotonic()
        if now - self._last_dir_rescan < self.dir_rescan_interval_s:
            return
        self._last_dir_rescan = now
        try:
            for capture in parse_active_captures_conf():
                base_dir = capture['directory']
                if not os.path.isdir(base_dir):
                    continue
                capture_dir = get_captures_path(os.path.basename(base_dir))
                if capture_dir not in self.dir_to_info:
                    if not folders_needing_service('img', [os.path.basename(base_dir)]):
                        continue   # this device's profile does not use the img service (main() filters the same way; BUG-0563)
                    logger.warning(f"🆕 Capture dir added after startup, now monitoring: {capture_dir}")
                    self._register_capture_dir(capture_dir)
            for capture_dir in list(self.dir_to_info):
                if capture_dir not in self._watched_dirs:
                    self._add_watch(capture_dir)
        except Exception as e:
            logger.error(f"[dir_rescan] failed: {e}")

    def _tele(self, capture_folder):
        """True when image telemetry is on for this device: not killed on the host and its profile has img.telemetry."""
        if not self._telemetry_allowed:
            return False
        profile = self.device_profile.get(capture_folder)
        if not (profile and profile.img.telemetry):
            return False
        if self.telemetry is None:
            with self._telemetry_lock:
                if self.telemetry is None:
                    t = img_telemetry.ImageTelemetry(
                        self.host_name,
                        status_dir_fn=get_metadata_path,
                        device_id_fn=lambda folder: get_device_info_from_capture_folder(folder).get('device_id', folder),
                    )
                    t.start()
                    self.telemetry = t
        return True

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
                if self._tele(capture_folder):
                    self.telemetry.on_dropped(capture_folder, drained)
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

            if self._tele(capture_folder):
                self.telemetry.on_analyzed(capture_folder, os.path.join(path, filename), queue_size)
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
        started = time.monotonic()
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
            entry['flush_cost'] = entry['last_flush'] - started
        except Exception as e:
            logger.error(f"[{entry.get('capture_folder')}] ✗ Chunk flush FAILED → {chunk_path}: {e}")

    def _flush_due(self, entry, now_mono):
        """Whether a dirty chunk has waited long enough: the 2 s floor, or 20x its last encode."""
        wait = max(self._chunk_flush_interval_s, self._chunk_flush_cost_ratio * entry.get('flush_cost', 0.0))
        return now_mono - entry['last_flush'] >= wait

    def _flush_dirty_chunks(self, force=False):
        """Flush the dirty chunk buffers that are due. Called ~every 2s by the
        stall watcher, and with force=True on shutdown so no completed metadata is lost."""
        now_mono = time.monotonic()
        with self._chunk_cache_lock:
            for chunk_path, entry in list(self._chunk_cache.items()):
                if entry.get('dirty') and (force or self._flush_due(entry, now_mono)):
                    self._flush_chunk_locked(chunk_path, entry)

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
                **self.device_analyzers[capture_folder][0].chunk_fields(analysis_data),
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

                # chunk-level fields (an analyzer's `chunk_header`, e.g. a profile's ui block): once per chunk, rewritten only when they change
                header = getattr(self.device_analyzers[capture_folder][0], 'chunk_header', None)
                for key, value in (header(analysis_data) if header else {}).items():
                    if entry['data'].get(key) != value:
                        entry['data'][key] = value
                        entry['dirty'] = True

                entry['data']['frames'].append(frame_data)
                entry['seen'].add(sequence)
                entry['dirty'] = True

                if self._flush_due(entry, now_mono):
                    self._flush_chunk_locked(chunk_path, entry)

        except Exception as e:
            logger.error(f"[{capture_folder}] ✗ Chunk append FAILED → {chunk_path if 'chunk_path' in locals() else 'unknown'}: {e}")
            raise Exception(f"Chunk append error: {e}")

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
                    # A stopped or stuck vpt-monitor-audio leaves this file frozen. Past
                    # AUDIO_STATUS_MAX_AGE_S the reading says nothing about now: report
                    # unknown (as for a device without audio) instead of repeating it.
                    if time.time() - os.path.getmtime(audio_status_path) > AUDIO_STATUS_MAX_AGE_S:
                        new_audio, new_volume = None, None
                    
                    # Update cache if changed
                    if capture_folder not in self.audio_cache:
                        self.audio_cache[capture_folder] = {'audio': new_audio, 'mean_volume_db': new_volume}
                        audio_val = "N/A" if new_audio is None else ("✅ YES" if new_audio else "❌ NO")
                        logger.info(f"[{capture_folder}] 🔍 Audio from status file: audio={audio_val}, volume={_format_volume_db(new_volume)}")
                    elif self.audio_cache[capture_folder].get('audio') != new_audio:
                        self.audio_cache[capture_folder] = {'audio': new_audio, 'mean_volume_db': new_volume}
                        audio_val = "N/A" if new_audio is None else ("✅ YES" if new_audio else "❌ NO")
                        logger.info(f"[{capture_folder}] 🔄 Audio changed: audio={audio_val}, volume={_format_volume_db(new_volume)}")
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
                        audio_val = "N/A" if existing_audio_data['audio'] is None else ("✅ YES" if existing_audio_data['audio'] else "❌ NO")
                        volume = existing_audio_data.get('mean_volume_db', -100)
                        logger.debug(f"[{capture_folder}] 🔄 Cache updated from existing JSON: audio={audio_val}, volume={_format_volume_db(volume)}")
                except:
                    pass
            
            # Use cached audio if JSON doesn't have it yet
            if not existing_audio_data and capture_folder in self.audio_cache:
                existing_audio_data = self.audio_cache[capture_folder]
            

            ctx = FrameContext(
                capture_folder=capture_folder, device_index=None, sequence=sequence,
                timestamp=time.time(), frame_path=frame_path, thumbnail=None,
                device_state=device_state, profile=self.device_profile[capture_folder],
                filename=filename, device_id=device_id, queue_size=queue_size, json_file=json_file,
                needs_detection=needs_detection, audio=existing_audio_data,
            )
            analyzer = self.device_analyzers[capture_folder][0]
            detection_result = analyzer.analyze(ctx)

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
                    audio_val = "N/A" if existing_audio_data['audio'] is None else ("✅ YES" if existing_audio_data['audio'] else "❌ NO")
                    volume = existing_audio_data.get('mean_volume_db', -100)
                    # Per-frame (~10fps × N devices) — DEBUG only, otherwise it floods the
                    # journal and buries real events (zapping, freeze, errors). Enable with
                    # CAPTURE_MONITOR_LOG_LEVEL=DEBUG when debugging audio detection.
                    logger.debug(f"[{capture_folder}] 🔄 Updated audio cache from {json_file}: audio={audio_val}, volume={_format_volume_db(volume)}")
                    # Make sure existing_data has audio
                    existing_data.update(existing_audio_data)
                elif capture_folder in self.audio_cache:
                    # No audio in JSON but we have cached value - use it
                    existing_data.update(self.audio_cache[capture_folder])
                    audio_val = "N/A" if self.audio_cache[capture_folder]['audio'] is None else ("✅ YES" if self.audio_cache[capture_folder]['audio'] else "❌ NO")
                    volume = self.audio_cache[capture_folder].get('mean_volume_db', -100)
                    logger.debug(f"[{capture_folder}] 📋 Using cached audio for {json_file}: audio={audio_val}, volume={_format_volume_db(volume)}")
                
                analysis_data = analyzer.frame_record(ctx, detection_result, existing_data)
                # Generic output every profile shares (TASK-90 §4.6); tv_app writes the empty values.
                analysis_data['profile'] = self.device_profile[capture_folder].name
                analysis_data.setdefault('observations', [])
                analysis_data.setdefault('events', {})
                analysis_data.setdefault('kpis', {})

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

            work_queue = self.device_queues.get(capture_folder)
            if work_queue is None:
                return   # a device whose profile could not start has no queue
            queue_size = work_queue.qsize()
            if self._tele(capture_folder) and filename.startswith('capture_') and filename.endswith('.jpg') \
                    and '_thumbnail' not in filename and '.tmp' not in filename:
                self.telemetry.on_arrival(capture_folder, os.path.join(path, filename))

            # Don't fill queue if >150 (images may be deleted from hot storage before processing)
            if queue_size > 150:
                logger.warning(
                    f"[{capture_folder}] ⏭️  Queue over 150 ({queue_size}), SKIPPING {filename} "
                    f"(seq={sequence}) - images may expire"
                )
                if self._tele(capture_folder):
                    self.telemetry.on_dropped(capture_folder, 1)
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
            # yield_nones=True: a None every idle second so the dir rescan still runs
            # on a host whose only capture dirs were the ones missed at startup.
            for event in self.inotify.event_gen(yield_nones=True):
                self._maybe_rescan_capture_dirs()
                if event is None:
                    continue
                (_, type_names, path, filename) = event
                
                # IN_MOVED_TO = atomic file move (FFmpeg atomic_writing)
                if 'IN_MOVED_TO' in type_names:
                    self._handle_file_event(path, filename)
                        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            # Persist any buffered chunk metadata before exit.
            try:
                self._flush_dirty_chunks(force=True)
            except Exception as e:
                logger.error(f"Final chunk flush failed: {e}")
            for path in self._watched_dirs:
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
        
        self._watchdog_handler = CaptureEventHandler()

        # Schedule watches for all capture directories registered so far
        for path in list(self.dir_to_info):
            self._add_watch(path)
        
        try:
            self.observer.start()
            logger.info("Watchdog observer started")
            
            # Keep running until interrupted
            while True:
                time.sleep(1)
                self._maybe_rescan_capture_dirs()
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.observer.stop()
            self.observer.join()



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
    
    # BUG-0563: per-capture-dir filter — the imager's third (and innermost) view of "does this device
    # need the img service?". We use the same `folders_needing_service` helper the host orchestrator
    # uses (`apply_monitor_profiles` -> `_desired_state` -> `folders_needing_service_for_devices`) and
    # the unit-startup idle gate uses (`wait_until_needed`). One decision function, three call sites
    # — they cannot diverge. The result on the wire: a host with six devices but three on `pc` /
    # `tv_lite` shows `Found 3 capture directories` and skips the rest with
    # `[captureN] profile does not use the img service, skipped`, with no inotify watch on the
    # skipped capture folders and no per-capture frame worker.
    needed = set(folders_needing_service('img', [os.path.basename(b) for b in base_dirs]))
    for base_dir in base_dirs:
        # Extract device folder name (e.g., 'capture1' from '/var/www/html/stream/capture1')
        device_folder = os.path.basename(base_dir)
        if device_folder not in needed:
            logger.info(f"[{device_folder}] profile does not use the img service, skipped")
            continue
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
