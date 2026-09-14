#!/usr/bin/env python3
"""
KPI Measurement Executor Service - Standalone Background Service

Measures actual time from navigation action to visual confirmation (node's KPI reference appearing).
Runs as separate systemd service, processes queued measurement requests via JSON files.

Architecture:
- NavigationExecutor writes KPI request JSON files to /tmp/kpi_queue/
- This service watches directory with inotify (zero CPU when idle)
- Processes requests and updates execution_results database
- No shared memory with Flask - completely decoupled!

Proven pattern: Same as capture_monitor.py and transcript_accumulator.py
"""

import os
import sys
import json
import time
import glob
import queue
import logging
import threading
import shutil
import uuid
import asyncio
from queue import Queue
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Scan-algorithm tuning constants (see docs/agent/execution/KPI_TROUBLESHOOTING.md "Two-pass scan").
#
# AHASH_DIFF_THRESHOLD: 8x8 average-hash Hamming distance above which a frame
# is considered "no longer the source state". Codec noise on H.264/MJPEG
# stills runs 4–8 bits on this hash; a stable scene transition runs 20+ bits.
# 18 is the comfortable middle. Tune by inspecting diffs on known-good scans.
#
# AHASH_STABLE_RUN: number of additional frames past the first divergent
# frame that must also diverge before we trust the boundary. Rejects
# single-frame compression flicker and focus-ring redraws.
#
# DIFF_BRACKET_VERIFY_DEPTH: after pixel-diff identifies a boundary frame,
# how many frames forward we are willing to run the real verifier on
# before giving up and falling back to exhaustive backward scan. 8 at
# 5 fps = 1.6 s of post-boundary window, which comfortably covers the
# Example STB menu animations (typically 1.0–1.4 s settle time from
# first pixel change to text/icon fully rendered). Bumped from 3 on
# 2026-05-20 after measuring the diff-found-boundary-but-verifier-failed
# fallback path on host1: every fallback we saw had a clean diff
# transition at idx 3 with the actual destination materialising at
# idx 5–10. Worst-case cost: 8 verifier calls, still cheaper than
# the previous step-2 backward scan (6–13 calls without diff guidance).
#
# SCAN_DEADLINE_SECONDS: hard wall-clock cap on _scan_until_match. Past
# this, the request fails with kpi_measurement_error = "scan budget
# exceeded" and the worker moves on so one slow scan can't snowball the
# queue and starve newer requests of their hot-storage thumbnails.
# Raised 10→30 on 2026-05-27: OCR text references cost ~1–1.5s/frame, so a
# 10s cap aborted (deadline_exceeded → NULL kpi_ms) before the verifier
# could walk a real transition. Since requests are queued (not on the live
# nav path), a longer scan only delays *this* measurement, never the user;
# the cheap aHash pre-pass keeps the common case well under 1s regardless.
#
# LATE_DEQUEUE_WARN_SECONDS: when a request file's age at dequeue exceeds
# this, log a warning and stamp the report with `late_scan=true`. Used to
# make queue backlog visible without changing the DB schema.
# ---------------------------------------------------------------------------
AHASH_DIFF_THRESHOLD = 18
AHASH_STABLE_RUN = 2
DIFF_BRACKET_VERIFY_DEPTH = 8
SCAN_DEADLINE_SECONDS = 30.0
LATE_DEQUEUE_WARN_SECONDS = 30.0
# Appear-then-disappear scans need the WHOLE timeout window of frames on disk
# before scanning (the disappear can land late). The KPI is queued right after the
# action's wait_time — usually shorter than the timeout — so we wait for the
# remaining frames to be captured. Capped so a misconfigured huge timeout can't
# stall the single worker indefinitely; hot storage retains ~60-75s of frames.
MAX_ATD_FRAME_WAIT_SECONDS = 30.0

# ---------------------------------------------------------------------------
# Long-window scan (device reboot / multi-minute waits) — see docs/agent/execution/KPI_TROUBLESHOOTING.md
# "Long-window scan".
#
# The hot captures dir holds only the newest ~300 frames (~60-75s at 5 fps);
# everything older is archived to the cold hour-folders ({base}/captures/{0..23}/)
# at 1 fps for ~24h, with mtime preserved. _copy_images_to_tmp therefore pulls
# the recent part of the window from hot (5 fps) and the older part from cold
# (1 fps) — see _discover_window_captures. 1 fps is plenty of resolution for a
# 2-minute measurement (boot time itself varies by seconds).
#
# The exhaustive frame-by-frame fallback scan is O(window): at 5 fps a 2-minute
# reboot window is hundreds of frames and an OCR reference (~1-1.5 s/frame) would
# blow SCAN_DEADLINE_SECONDS many times over. For windows longer than
# LONG_SCAN_WINDOW_SECONDS we instead bracket the absent→present transition with
# a coarse time-grid probe, binary-refine to the earliest matching frame, then
# sustain-check to reject a transient false-positive — ~log(N)+grid verifier
# calls instead of O(N). This assumes the target is a ~monotone step (absent
# during boot → present once rendered → stays present), which holds for
# boot-to-home KPIs; the sustain check guards against the assumption breaking.
LONG_SCAN_WINDOW_SECONDS = 60.0
# Wall-clock cap for the coarse-to-fine scan. Higher than SCAN_DEADLINE_SECONDS
# because a long window legitimately needs more (still bounded) verifier calls;
# bounded so one reboot measurement can't stall the single worker forever.
LONG_SCAN_DEADLINE_SECONDS = 120.0
# Coarse probe spacing (seconds) used to bracket the transition before binary
# refinement.
LONG_SCAN_COARSE_STEP_SECONDS = 10.0
# After binary search lands on a candidate earliest-match frame, require the
# match to still hold this many seconds later. Rejects a transient frame that
# merely resembles the target mid-boot. If it doesn't sustain, the candidate is
# treated as absent and the search resumes to its right.
LONG_SCAN_SUSTAIN_SECONDS = 3.0
# Safety cap on transient-island rejections inside the coarse-to-fine scan.
LONG_SCAN_MAX_ISLAND_RETRIES = 4
# Frame-wait cap for long windows: the request may be dequeued before the full
# reboot window has been captured, so allow waiting up to this long (vs the
# tighter MAX_ATD_FRAME_WAIT_SECONDS for normal windows) for the remaining
# frames to land.
MAX_LONG_FRAME_WAIT_SECONDS = 130.0
# Exhaustive fallback — runs ONLY when the coarse grid finds nothing over a long
# window. The coarse probe samples every ~LONG_SCAN_COARSE_STEP_SECONDS, so a
# target that appears AND disappears between two probes is stepped over entirely.
# We then scan frame-by-frame from the start, collapsing near-duplicate frames so
# a static window can't cost hundreds of verifier calls. Applies to BOTH image
# and text references.
#
# EXHAUSTIVE_MAX_SKIP_RUN caps how many consecutive near-duplicate frames we may
# skip — the correctness floor. At 4, even an entirely static window keeps 1 of
# every 5 frames ("max 1 frame every 5"), so a transient target can never be
# skipped by more than 4 frames regardless of what the similarity hash thinks.
EXHAUSTIVE_MAX_SKIP_RUN = 4
# 8x8 aHash (over the verification's search ROI) Hamming distance below which two
# frames are treated as near-duplicates during the exhaustive scan.
EXHAUSTIVE_DEDUP_HAMMING = 6
# Absolute ceiling on verifier calls in the exhaustive scan ("max out"). After
# dedup, if the distinct-frame set is still larger than this, even-sample down to
# it — so no pathological window (e.g. all-distinct frames) can blow the budget.
EXHAUSTIVE_MAX_PROBES = 64
# Cap on how many probed frames the report surfaces (one verification card each
# + a colored mosaic border each). The coarse scan probes ~8 (all shown); the
# exhaustive scan can probe many more — even-sample down to this many so the
# report stays readable and R2 uploads stay bounded. The mosaic still shows every
# frame via its own near-duplicate dedup; this only bounds the per-probe border
# overlay and the per-frame card list.
MAX_REPORTED_PROBES = 16

# KPI measures action→appear (the first frame the destination renders). An
# appear-then-disappear reference describes a transient; checked one frame at
# a time (timeout=0) its state machine can never observe the full sequence and
# would always fail. For the KPI scan we therefore reduce it to its appear
# half — the matching frame IS the action→appear anchor. The disappear half is
# still enforced by the LIVE navigation verifier, not here.
_KPI_APPEAR_NORMALIZE = {
    'waitForImageToAppearThenDisappear': 'waitForImageToAppear',
    'waitForTextToAppearThenDisappear': 'waitForTextToAppear',
    'waitForIconToAppearThenDisappear': 'waitForIconToAppear',
}

# Phase B of an appear-then-disappear KPI: once the appear frame is found, walk
# forward to the first frame where the element is gone. KPI = action→disappear
# (appear segment + visible-duration segment). The report then shows two cards:
# a `waitFor*ToAppear` FOUND at the appear frame and a `waitFor*ToDisappear`
# FOUND at the disappear frame.
_KPI_DISAPPEAR_NORMALIZE = {
    'waitForImageToAppearThenDisappear': 'waitForImageToDisappear',
    'waitForTextToAppearThenDisappear': 'waitForTextToDisappear',
    'waitForIconToAppearThenDisappear': 'waitForIconToDisappear',
}
_KPI_ATD_COMMANDS = frozenset(_KPI_APPEAR_NORMALIZE.keys())

# Setup path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_host_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_host_dir)
sys.path.insert(0, project_root)

import platform

# Cross-platform file monitoring: inotify on Linux, watchdog on macOS
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

if IS_LINUX:
    import inotify.adapters
else:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

# Per-measurement device context. Multiple STBs on one host feed a single
# vpt-kpi worker, so its log lines were indistinguishable by device. The worker
# is single-threaded (one request in flight), so a module global set at dequeue
# and cleared after is race-free and lets every line carry the device name.
_CURRENT_DEVICE = {'name': '-'}


class _DeviceLogFilter(logging.Filter):
    """Inject the current measurement's device name onto every record so the
    format string can print it. Never drops a record (always returns True);
    defaults to '-' for lines emitted between measurements (e.g. heartbeat)."""
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'device'):
            record.device = _CURRENT_DEVICE['name']
        return True


# Setup logging (systemd handles file output). The `[device]` field is populated
# by _DeviceLogFilter attached to the handler, so it applies to every record that
# reaches this handler — including propagated child-logger lines.
_kpi_log_handler = logging.StreamHandler()
_kpi_log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(device)s] %(message)s'))
_kpi_log_handler.addFilter(_DeviceLogFilter())
logging.basicConfig(level=logging.INFO, handlers=[_kpi_log_handler])
logger = logging.getLogger(__name__)

# KPI request queue directory
KPI_QUEUE_DIR = '/tmp/kpi_queue'


def _ahash64(path: str) -> Optional[int]:
    """8x8 average-hash for a capture. Returns int packed into 64 bits.

    ~1 ms per call on a Raspberry Pi 4 (loads the JPG, resizes to 8x8 in
    grayscale via PIL's Box filter, thresholds against the mean). Used by
    the pixel-diff pre-pass to locate the source→destination transition
    without paying OCR / template-match cost on every frame.

    Returns None on read errors so the caller can skip the frame instead
    of crashing the whole scan.
    """
    try:
        with Image.open(path) as im:
            arr = np.asarray(im.convert('L').resize((8, 8), Image.BOX),
                             dtype=np.uint8)
        bits = (arr > arr.mean()).flatten().astype(np.uint8)
        return int.from_bytes(np.packbits(bits).tobytes(), byteorder='big')
    except Exception as e:
        logger.warning(f"⚠️  Could not hash {os.path.basename(path)}: {e}")
        return None


def _hamming64(a: int, b: int) -> int:
    """Hamming distance between two 64-bit unsigned integers (0..64)."""
    return bin(a ^ b).count('1')


def _ahash64_roi(path: str, area: Optional[dict]) -> Optional[int]:
    """8x8 average-hash over a sub-region (the verification's search area) of a
    capture. Falls back to the full frame when `area` is None/invalid.

    Hashing only the region the verifier actually consumes means a change INSIDE
    that region (a banner appearing over an otherwise-static frame) always
    survives near-duplicate collapse, while changes elsewhere don't inflate the
    distinct-frame count. For a full-frame reference this is identical to
    _ahash64. Returns None on read errors so the caller can skip the frame.
    """
    try:
        with Image.open(path) as im:
            im = im.convert('L')
            if isinstance(area, dict) and all(area.get(k) is not None for k in ('x', 'y', 'width', 'height')):
                x, y = int(area['x']), int(area['y'])
                box = (max(0, x), max(0, y),
                       min(im.width, x + int(area['width'])),
                       min(im.height, y + int(area['height'])))
                if box[2] > box[0] and box[3] > box[1]:
                    im = im.crop(box)
            arr = np.asarray(im.resize((8, 8), Image.BOX), dtype=np.uint8)
        bits = (arr > arr.mean()).flatten().astype(np.uint8)
        return int.from_bytes(np.packbits(bits).tobytes(), byteorder='big')
    except Exception as e:
        logger.warning(f"⚠️  Could not ROI-hash {os.path.basename(path)}: {e}")
        return None


def _cold_captures_root(capture_dir: str) -> Optional[str]:
    """Map the live (hot) captures dir to the cold captures root holding the
    hour-folder archive ({root}/{0..23}/capture_*.jpg).

        RAM mode:  {base}/hot/captures  → {base}/captures
        SD mode:   {base}/captures      → {base}/captures (hour folders are subdirs)

    The cold archive keeps ~24h of frames at 1 fps (vs 5 fps / ~75s in hot), so
    it is the only source for the older part of a long (reboot) scan window.
    Returns None if the path doesn't match the expected layout.
    """
    cd = capture_dir.rstrip('/')
    if cd.endswith('/hot/captures'):
        return cd[: -len('/hot/captures')] + '/captures'
    if cd.endswith('/captures'):
        return cd
    return None


class _MeasurementLogCapture(logging.Handler):
    """In-memory log handler that buffers every record emitted while a single
    KPI measurement is processed.

    The KPI executor is a standalone single-threaded service (one request in
    flight at a time), so attaching this to the root logger for the duration
    of one _process_measurement call captures exactly that measurement's logs
    — the aHash Hamming distances, boundary candidate, verifier pass/fail,
    backward-scan walk, etc. We stash the joined text on the request and embed
    it in the report's collapsible "Measurement Log" section so a scan can be
    debugged after the fact without trawling journalctl on the host.
    """

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: List[str] = []
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            # A logging handler must never raise back into the emitting code.
            pass

    def text(self) -> str:
        return '\n'.join(self.lines)


class KPIMeasurementRequest:
    """KPI measurement request - loaded from JSON file"""
    def __init__(self, data: dict):
        # Validate required fields
        self.execution_result_id = data['execution_result_id']
        self.team_id = data['team_id']
        self.capture_dir = data['capture_dir']
        self.action_timestamp = data['action_timestamp']
        self.verification_timestamp = data['verification_timestamp']
        self.kpi_references = data['kpi_references']
        # Pass condition ('all' / 'any') resolved from the destination node by
        # NavigationExecutor. The scan rebuilds verification dicts (dropping any
        # per-item field), so this must be forwarded explicitly to
        # execute_verifications or it would silently default to 'all' and fail
        # nodes that pass live under 'any'.
        self.verification_pass_condition = data.get('verification_pass_condition', 'all')
        # Diagnostic for the report: True when kpi_references came from the
        # destination node's live verifications, False when from the action_set's
        # frozen kpi_references snapshot. Lets a reviewer see at a glance whether
        # editing a node's verifications would propagate to this KPI.
        self.use_verifications_for_kpi = bool(data.get('use_verifications_for_kpi', False))
        self.timeout_ms = data['timeout_ms']
        self.device_id = data['device_id']
        self.userinterface_name = data['userinterface_name']  # MANDATORY for reference resolution
        self.device_model = data.get('device_model')
        self.kpi_timestamp = data.get('kpi_timestamp')
        self.last_action_wait_ms = data.get('last_action_wait_ms', 0)
        self.request_file = data.get('_request_file')  # Track source file
        # Mtime of the request JSON file when it was enqueued — used to
        # detect queue backlog at dequeue time. Set by _enqueue_request_file.
        # When dequeue happens >LATE_DEQUEUE_WARN_SECONDS after this, the
        # report is stamped with `late_scan=true` so eyeballed report
        # anomalies (e.g. missing thumbnails) trace cleanly to a backlog.
        self.queued_at = data.get('_queued_at', time.time())
        # Set by _process_measurement after comparing queued_at to now —
        # report generators read it to show a banner on late scans.
        self.late_scan: bool = False
        # Extended metadata for report
        self.host_name = data.get('host_name')
        self.device_name = data.get('device_name')
        self.tree_id = data.get('tree_id')
        self.action_set_id = data.get('action_set_id')
        self.from_node_label = data.get('from_node_label')
        self.to_node_label = data.get('to_node_label')
        self.last_action = data.get('last_action')
        # Optional run-level friendly name (e.g. the standby mode display name set
        # by standby_measurement via device.navigation_context). Shown on the KPI
        # report header; the measured edge alone can't carry it (identical across modes).
        self.kpi_display_label = data.get('kpi_display_label')
        self.before_action_screenshot_path = data.get('before_action_screenshot_path')  # ✅ Before screenshot
        self.action_screenshot_path = data.get('action_screenshot_path')  # After screenshot
        self.action_details = data.get('action_details', {})  # ✅ NEW: Action execution details
        self.verification_evidence_list = data.get('verification_evidence_list', [])  # ✅ NEW: Verification evidence
        # NavigationExecutor sets this True when the live verifier ran
        # against the destination and FAILED. _process_measurement uses it
        # to skip the doomed scan and record a clean failure instead of
        # burning the 10 s scan budget.
        self.live_verification_failed: bool = data.get('live_verification_failed', False)
        # URL of the failure report the LIVE destination verifier already
        # generated (reference + failed source crop + overlay). When the
        # short-circuit below fires (no scan runs, so no KPI report is built),
        # this is stored as the row's kpi_report_url so the KPI summary still
        # links to the exact frame/crop that failed.
        self.live_verification_report_url: Optional[str] = data.get('live_verification_report_url')
        # Filled by _process_measurement from the per-measurement log capture;
        # embedded in the report's collapsible "Measurement Log" section.
        self.measurement_log: str = ''


class KPIExecutorService:
    """Standalone KPI executor service - cross-platform (inotify on Linux, watchdog on macOS)"""
    
    def __init__(self):
        self.running = False
        self.work_queue = Queue(maxsize=100)
        self.worker_thread = None
        
        # Ensure queue directory exists
        os.makedirs(KPI_QUEUE_DIR, exist_ok=True)
        
        # Platform-specific file watcher initialization
        if IS_LINUX:
            self.inotify = inotify.adapters.Inotify()
            self.inotify.add_watch(KPI_QUEUE_DIR)
            self._watcher_type = 'inotify'
        else:
            self.observer = Observer()
            self._watcher_type = 'watchdog'
        
        logger.info(f"✓ Watching KPI queue directory: {KPI_QUEUE_DIR} ({self._watcher_type})")
    
    def start(self):
        """Start worker thread"""
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(self.work_queue,),
            daemon=True,
            name="KPI-Worker"
        )
        self.worker_thread.start()
        logger.info(f"✅ KPI worker thread started")
    
    def _worker_loop(self, work_queue):
        """Worker thread - processes KPI measurement requests"""
        logger.info("🔄 KPI worker loop started")
        
        iteration = 0
        while self.running:
            try:
                # Wait for measurement request
                try:
                    request_file, request = work_queue.get(timeout=1.0)
                except queue.Empty:
                    # Periodic heartbeat
                    iteration += 1
                    if iteration % 120 == 0:
                        logger.info(f"💓 KPI worker heartbeat (queue size: {work_queue.qsize()})")
                    continue

                # Stamp every log line for this request with its device so a
                # shared host's interleaved measurements are attributable. Reset
                # in the finally below once the request is done.
                _CURRENT_DEVICE['name'] = (
                    getattr(request, 'device_name', None)
                    or getattr(request, 'device_id', None)
                    or '-'
                )

                # Log immediately
                logger.info(f"📥 KPI worker dequeued: {os.path.basename(request_file)}")
                
                # Process measurement
                try:
                    logger.info(f"🎬 KPI processing started: {request.execution_result_id[:8]}")
                    # Run async method in event loop
                    import asyncio
                    asyncio.run(self._process_measurement(request))
                    logger.info(f"🏁 KPI processing finished")
                    
                    # Delete processed request file
                    try:
                        os.remove(request_file)
                        logger.debug(f"🗑️  Deleted processed request: {os.path.basename(request_file)}")
                    except Exception as e:
                        logger.warning(f"Could not delete request file: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error processing KPI measurement: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    work_queue.task_done()
                    # Clear device context so between-request lines (heartbeat,
                    # next dequeue) aren't misattributed to the finished device.
                    _CURRENT_DEVICE['name'] = '-'

            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)
        
        logger.info("🛑 KPI worker loop exited")
    
    async def _process_measurement(self, request: KPIMeasurementRequest):
        """Process a single KPI request, capturing its logs for the report.

        Attaches a per-measurement log handler to the root logger for the whole
        request (single-threaded service → no cross-talk), then hands off to
        _process_measurement_inner. The captured text is snapshotted onto the
        request right before each report is generated (inside inner) and the
        handler is always detached here in finally.
        """
        log_capture = _MeasurementLogCapture()
        root_logger = logging.getLogger()
        root_logger.addHandler(log_capture)
        try:
            await self._process_measurement_inner(request, log_capture)
        finally:
            # Final snapshot covers any early-return path that didn't build a
            # report; harmless to overwrite when a report path already set it.
            if not request.measurement_log:
                request.measurement_log = log_capture.text()
            root_logger.removeHandler(log_capture)

    async def _process_measurement_inner(self, request: KPIMeasurementRequest,
                                         log_capture: '_MeasurementLogCapture'):
        """Process single KPI measurement request"""
        logger.info(f"🔍 Processing KPI measurement")
        logger.info(f"   • Execution result: {request.execution_result_id[:8]}")
        # Log the edge + action_set so the worker is greppable by device (line
        # prefix) AND by edge/action_set — neither was in the log before, so
        # `journalctl -u vpt-kpi | grep <action_set_id>` returned nothing.
        logger.info(f"   • Device: {request.device_name or request.device_id}  "
                    f"| Edge: {request.from_node_label} → {request.to_node_label}  "
                    f"| action_set: {request.action_set_id}")

        # DEBUG: Show exact values received
        logger.info(f"   • verification_timestamp: {request.verification_timestamp}")
        logger.info(f"   • last_action_wait_ms: {request.last_action_wait_ms}ms")
        logger.info(f"   • action_timestamp: {time.strftime('%H:%M:%S', time.localtime(request.action_timestamp))}")
        logger.info(f"   • timeout_ms: {request.timeout_ms}ms")
        logger.info(f"   • kpi_references: {len(request.kpi_references)}")

        # Late-scan detection: if the JSON request file has been sitting in
        # /tmp/kpi_queue/ for >LATE_DEQUEUE_WARN_SECONDS, the worker is
        # backed up. Hot-storage thumbnails for this request's scan window
        # may already have rolled, which is the failure mode we hit on
        # 2026-05-20 (a8dccc31 — 66s queue wait, thumbnails missing). We
        # log a warning and stamp the request so the report can surface it.
        queue_wait_s = max(0.0, time.time() - request.queued_at)
        request.late_scan = queue_wait_s >= LATE_DEQUEUE_WARN_SECONDS
        if request.late_scan:
            logger.warning(f"⏳ Late dequeue: request waited {queue_wait_s:.1f}s in queue "
                           f"(threshold {LATE_DEQUEUE_WARN_SECONDS}s) — hot thumbnails may be stale")
        else:
            logger.info(f"   • Queue wait: {queue_wait_s:.1f}s")
        
        # Check if KPI already calculated during verification
        if request.kpi_timestamp:
            kpi_ms = int((request.kpi_timestamp - request.action_timestamp) * 1000)
            logger.info(f"⚡ KPI already calculated during verification: {kpi_ms}ms")
            logger.info(f"   • Skipping post-processing scan")
            self._update_result(request.execution_result_id, request.team_id, True, kpi_ms, None,
                                display_label=request.kpi_display_label)
            return

        # Live-verifier short-circuit. When the navigation step's destination
        # verifier ran (with its own retry budget) and failed, the destination
        # was not on screen during the wait period. Our scan window is
        # bounded by the same wait period, so we cannot possibly find what
        # the live verifier already missed. Skip the doomed scan and record
        # a clean failure instead of burning the 10 s budget.
        if request.live_verification_failed and not request.verification_timestamp:
            logger.info(f"⏭️  Skipping scan: live verifier already failed on destination "
                        f"(no scan window can recover that)")
            # Adopt the live verifier's own failure report (if it produced one)
            # as the KPI report URL. We never run the scan here, so we can't
            # generate a KPI-specific report — but the verification report
            # already shows the reference + failed source crop + overlay, which
            # is exactly what the summary needs to link to.
            if request.live_verification_report_url:
                logger.info(f"🔗 Using live verification failure report as KPI report: "
                            f"{request.live_verification_report_url}")
            self._update_result(
                request.execution_result_id,
                request.team_id,
                False,
                None,
                "skipped: live destination verification failed",
                request.live_verification_report_url,
                display_label=request.kpi_display_label,
            )
            return
        
        start_time = time.time()

        # Estimate the scan window length up front to pick the right budgets.
        # A long window (device reboot / multi-minute wait) is scanned by the
        # coarse-to-fine bounded search, which needs a higher (still bounded)
        # wall-clock deadline and may need to wait longer for late frames.
        if request.verification_timestamp:
            est_window_s = max(0.0, request.verification_timestamp - request.action_timestamp)
        else:
            est_window_s = max(request.last_action_wait_ms, request.timeout_ms) / 1000.0
        is_long_window = est_window_s > LONG_SCAN_WINDOW_SECONDS
        scan_deadline = LONG_SCAN_DEADLINE_SECONDS if is_long_window else SCAN_DEADLINE_SECONDS
        frame_wait_cap = MAX_LONG_FRAME_WAIT_SECONDS if is_long_window else MAX_ATD_FRAME_WAIT_SECONDS
        if is_long_window:
            logger.info(f"🪜 Long window (~{est_window_s:.0f}s): scan budget {scan_deadline:.0f}s, "
                        f"frame-wait cap {frame_wait_cap:.0f}s")

        # NO live-verification anchor: the scan window's upper bound is the KPI's
        # own timeout (action + timeout_ms), but the request is queued right after
        # the action's wait_time — usually SHORTER than the timeout (e.g. wait=10s,
        # timeout=20s). At that moment only the early part of the window has been
        # captured; we scan already-written frames (never future ones), so without
        # this wait we'd scan ~10s of a 20s window, miss a destination that renders
        # late, and report a false "no match in 20s window" against frames that
        # only spanned 12s. Wait for the rest of the window to be captured first.
        # (Also covers appear-then-disappear, whose disappear half can land late.)
        # When a live verifier DID run (verification_timestamp set), the destination
        # already appeared and was found, so every frame we need is already on disk
        # — no wait. Frames keep being captured; hot storage holds ~60-75s and the
        # cold archive holds ~24h, so the late frames are still present when we
        # wake. Capped at frame_wait_cap (larger for long windows) so a
        # misconfigured huge timeout can't stall the single worker.
        if not request.verification_timestamp:
            window_end = request.action_timestamp + request.timeout_ms / 1000.0
            remaining = window_end - time.time()
            if remaining > 0:
                wait_s = min(remaining, frame_wait_cap)
                logger.info(f"⏳ No verification anchor: waiting {wait_s:.1f}s for the full "
                            f"{request.timeout_ms}ms timeout window of frames before scanning")
                time.sleep(wait_s)

        # CRITICAL: Copy images from hot/cold storage to /tmp/ (RAM) to avoid a race:
        # hot keeps only the newest ~300 frames (~60-75s) and may roll them during
        # processing; the older part of a long window is read from the cold archive.
        working_dir, extra_before_filename = self._copy_images_to_tmp(request)
        if not working_dir:
            self._update_result(request.execution_result_id, request.team_id, False, None, "Failed to copy images from hot storage",
                                display_label=request.kpi_display_label)
            return
        
        try:
            # Scan captures from /tmp/ working directory.
            # Wall-clock-bounded: a runaway scan can't snowball the queue
            # and starve subsequent requests of their hot-storage thumbnails.
            # `progress` is a mutable dict the scan keeps current so that on
            # deadline we can still report how much work was done (otherwise
            # Grafana's "captures scanned" metric collapses to 0 for every
            # timeout, masking whether scans are doing 1 or 10 verifier
            # calls before being killed).
            progress: Dict = {'captures_scanned': 0, 'verification_evidence_list': []}
            # Reset per-frame probe bookkeeping (the scan populates these on self
            # via _record_probe). Reset here so a cancelled/deadline scan can't
            # surface a previous request's frames in the report.
            self._probe_outcomes = {}
            self._probe_evidence = {}
            try:
                match_result = await asyncio.wait_for(
                    self._scan_until_match(request, working_dir, extra_before_filename, progress),
                    timeout=scan_deadline,
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ Scan budget exceeded ({scan_deadline:.0f}s) "
                             f"after {progress['captures_scanned']} verifier calls")
                match_result = {
                    'success': False,
                    'timestamp': None,
                    'capture_index': None,
                    'all_captures': [],
                    'captures_scanned': progress['captures_scanned'],
                    'error': f'scan budget exceeded ({scan_deadline:.0f}s)',
                    'algorithm': 'deadline_exceeded',
                    'verification_evidence_list': progress['verification_evidence_list'],
                }
            
            logger.info(f"🔍 Scan completed, processing result: success={match_result.get('success')}")

            # Attach per-frame probe bookkeeping for the report: the mosaic borders
            # every frame the verifier actually ran on (so the 10s coarse gaps are
            # visible), and the failure report renders one verification card per
            # probed frame. Bound the surfaced set (even-sampled, always keeping
            # any passing probe) so the exhaustive image path — which can probe
            # hundreds on a true no-match — can't flood the report.
            probed = sorted(self._probe_outcomes)
            if len(probed) > MAX_REPORTED_PROBES:
                step = len(probed) / float(MAX_REPORTED_PROBES)
                kept_probes = {probed[int(k * step)] for k in range(MAX_REPORTED_PROBES)}
                kept_probes.update(i for i in probed if self._probe_outcomes[i])  # keep passes
                reported_probes = sorted(kept_probes)
                logger.info(f"📎 Probed {len(probed)} frames; surfacing "
                            f"{len(reported_probes)} in report (capped at {MAX_REPORTED_PROBES})")
            else:
                reported_probes = probed
            match_result['probe_outcomes'] = {i: self._probe_outcomes[i] for i in reported_probes}

            # Phase B for appear-then-disappear references: the scan above found
            # the APPEAR frame; now walk forward to the first frame where the
            # element is gone. KPI becomes action→disappear (the sum of the
            # appear segment + the visible-duration segment), and the report
            # gets a second "disappear" verification card. If it never
            # disappears within the window the measurement fails cleanly.
            if match_result.get('success') and self._is_appear_then_disappear(request):
                try:
                    atd = await asyncio.wait_for(
                        self._scan_for_disappear(request, working_dir, match_result),
                        timeout=scan_deadline,
                    )
                except asyncio.TimeoutError:
                    atd = None
                    logger.error(f"⏰ Disappear scan budget exceeded ({scan_deadline:.0f}s)")
                if atd is None:
                    match_result['success'] = False
                    match_result['error'] = 'element appeared but never disappeared within scan window'
                    match_result['algorithm'] = (match_result.get('algorithm', '') + '+no_disappear')
                else:
                    # Keep capture_index/timestamp on the APPEAR frame (the top
                    # strip's "match" card stays the moment-of-appearance). Stash
                    # the disappear frame for the new 5th card, and set the KPI
                    # endpoint to the disappear timestamp so the stored value is
                    # action→disappear.
                    appear_ts = match_result['timestamp']
                    match_result['appear_timestamp'] = appear_ts
                    match_result['disappear_timestamp'] = atd['disappear_timestamp']
                    match_result['disappear_index'] = atd['disappear_index']
                    match_result['kpi_endpoint_timestamp'] = atd['disappear_timestamp']
                    match_result['verification_evidence_list'] = atd['evidence_list']
                    match_result['captures_scanned'] = (
                        match_result.get('captures_scanned', 0) + atd['captures_scanned'])
                    match_result['algorithm'] = (match_result.get('algorithm', '') + '+disappear')
                    logger.info(f"🔁 Appear-then-disappear: appear→disappear "
                                f"= {int((atd['disappear_timestamp'] - appear_ts) * 1000)}ms; "
                                f"total action→disappear "
                                f"= {int((atd['disappear_timestamp'] - request.action_timestamp) * 1000)}ms")

            # Store result
            if match_result['success']:
                # KPI endpoint is the disappear frame for appear-then-disappear,
                # otherwise the match (appear) frame.
                kpi_endpoint_ts = match_result.get('kpi_endpoint_timestamp', match_result['timestamp'])
                kpi_ms = int((kpi_endpoint_ts - request.action_timestamp) * 1000)
                algorithm = match_result.get('algorithm', 'unknown')
                logger.info(f"✅ KPI match found!")
                logger.info(f"   • KPI duration: {kpi_ms}ms")
                logger.info(f"   • Algorithm: {algorithm}")
                logger.info(f"   • Captures scanned: {match_result['captures_scanned']}")

                # The scan IS the authoritative source for the report's
                # "Verification (N)" cards: kpi_executor ran every reference
                # against the matching capture, so it has the per-reference
                # evidence (image / source crop / pass-fail / details).
                # Always overwrite — the navigation-supplied list is ignored.
                # Like the failure path, surface the evidence of EVERY probed
                # frame (the capped/sampled reported set — passes are force-
                # kept, so the match frame always survives): the report's frame
                # selector lets the reader inspect what each analyzed frame
                # looked like against each reference, not just the match.
                # Appear-then-disappear keeps its dedicated appear+disappear
                # evidence pair (Phase B replaced the list above).
                if match_result.get('disappear_timestamp') is not None:
                    request.verification_evidence_list = match_result.get('verification_evidence_list') or []
                else:
                    per_frame_evidence = [it for idx in reported_probes
                                          if idx in self._probe_evidence
                                          for it in self._probe_evidence[idx]]
                    request.verification_evidence_list = (
                        per_frame_evidence or match_result.get('verification_evidence_list') or [])
                logger.info(f"📎 verification_evidence_list from scan: "
                            f"{len(request.verification_evidence_list)} items "
                            f"({len(reported_probes)} reported / {len(self._probe_evidence)} probed frames)")

                # Snapshot the measurement log so the report can embed it.
                request.measurement_log = log_capture.text()

                # Generate KPI report with thumbnails (from working directory)
                from shared.src.lib.utils.kpi_report_generator import generate_kpi_success_report
                report_url = generate_kpi_success_report(request, match_result, kpi_ms, working_dir, extra_before_filename)
                
                self._update_result(request.execution_result_id, request.team_id, True, kpi_ms, None, report_url,
                                    display_label=request.kpi_display_label)
            else:
                algorithm = match_result.get('algorithm', 'unknown')
                logger.error(f"❌ KPI measurement failed: {match_result['error']}")
                logger.info(f"   • Algorithm: {algorithm}")
                logger.info(f"   • Captures scanned: {match_result.get('captures_scanned', 0)}")

                # One verification card per probed frame (the capped/sampled set
                # from reported_probes) so the failure report shows the frames the
                # verifier checked and their scores — matching the mosaic's
                # bordered tiles. Falls back to the last-attempt evidence if no
                # per-frame evidence was captured.
                per_frame_evidence = [it for idx in reported_probes
                                      if idx in self._probe_evidence
                                      for it in self._probe_evidence[idx]]
                request.verification_evidence_list = (
                    per_frame_evidence or match_result.get('verification_evidence_list') or [])
                logger.info(f"📎 verification_evidence_list from failed scan: "
                            f"{len(request.verification_evidence_list)} items "
                            f"({len(reported_probes)} reported / {len(self._probe_evidence)} probed frames)")

                # Snapshot the measurement log so the report can embed it.
                request.measurement_log = log_capture.text()

                # Generate self-contained failure report, upload to MinIO/R2,
                # and persist its URL so failed KPIs are retrievable from storage
                # (same as the success path) and the full URL shows in the log.
                from shared.src.lib.utils.kpi_report_generator import generate_kpi_failure_report
                report_url = generate_kpi_failure_report(request, match_result, working_dir)
                if report_url:
                    logger.error(f"🔍 KPI FAILURE REPORT: {report_url}")

                self._update_result(request.execution_result_id, request.team_id, False, None, match_result['error'], report_url,
                                    display_label=request.kpi_display_label)
            
            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"⏱️  KPI processing completed in {processing_time}ms")
        
        except Exception as e:
            logger.error(f"❌ Exception during KPI scan: {e}")
            import traceback
            traceback.print_exc()
            # Store failure result
            error_msg = f"Exception during scan: {str(e)}"
            self._update_result(request.execution_result_id, request.team_id, False, None, error_msg,
                                display_label=request.kpi_display_label)
            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"⏱️  KPI processing failed in {processing_time}ms")
        
        finally:
            # Cleanup: Delete working directory
            self._cleanup_working_dir(working_dir)
    
    def _discover_window_captures(
        self,
        request: KPIMeasurementRequest,
        scan_start: float,
        scan_end: float,
    ) -> List[dict]:
        """Find every capture frame that falls in (or just before) the scan
        window, drawing from BOTH hot and cold storage.

        Hot (`request.capture_dir`, 5 fps) only retains the newest ~300 frames
        (~60-75s). For a long window (e.g. a 2-minute reboot) the earlier part
        of the window has already rolled out of hot and lives in the cold
        hour-folder archive ({root}/{0..23}/, 1 fps, ~24h, mtime preserved).

        We take the recent part of the window from hot at full 5 fps, and only
        the part OLDER than hot's coverage from cold at 1 fps — partitioning at
        hot's oldest frame so the two sources never produce duplicate frames.

        Returns an mtime-sorted list of {'path', 'ts', 'filename'} dicts. A small
        margin before scan_start is included so the caller can pick the
        "before window" reference frame even when the window starts in cold.
        """
        margin = 5.0  # seconds before scan_start, for the before-window frame
        lower = scan_start - margin

        # --- Hot frames (flat live dir) ---
        hot: List[dict] = []
        hot_pattern = os.path.join(request.capture_dir, "capture_*.jpg")
        for source_path in glob.glob(hot_pattern):
            if "_thumbnail" in source_path:
                continue
            try:
                ts = os.path.getmtime(source_path)
            except (OSError, IOError):
                continue
            hot.append({'path': source_path, 'ts': ts,
                        'filename': os.path.basename(source_path)})

        # Boundary between hot and cold coverage: the oldest hot frame. Anything
        # older than this is only available from the cold archive.
        hot_coverage_start = min((c['ts'] for c in hot), default=float('inf'))

        combined = [c for c in hot if lower <= c['ts'] <= scan_end]

        # --- Cold frames (hour-folder archive), only for the part of the window
        #     older than hot's coverage, so we never duplicate a hot frame. ---
        cold_upper = min(scan_end, hot_coverage_start)
        if lower < cold_upper:
            cold_root = _cold_captures_root(request.capture_dir)
            if cold_root and os.path.isdir(cold_root):
                # Only stat the hour folders the window actually spans (folder
                # name = local-time hour of the frame's mtime; see archiver
                # get_file_hour). Usually 1-2 folders for a multi-minute window.
                hours = set()
                t = lower
                while t <= cold_upper:
                    hours.add(time.localtime(t).tm_hour)
                    t += 3600
                hours.add(time.localtime(cold_upper).tm_hour)

                cold_count = 0
                for hour in sorted(hours):
                    hour_dir = os.path.join(cold_root, str(hour))
                    if not os.path.isdir(hour_dir):
                        continue
                    for source_path in glob.glob(os.path.join(hour_dir, "capture_*.jpg")):
                        if "_thumbnail" in source_path:
                            continue
                        try:
                            ts = os.path.getmtime(source_path)
                        except (OSError, IOError):
                            continue
                        if lower <= ts < cold_upper:
                            combined.append({'path': source_path, 'ts': ts,
                                             'filename': os.path.basename(source_path)})
                            cold_count += 1
                if cold_count:
                    logger.info(f"   • Pulled {cold_count} frame(s) from cold archive "
                                f"{cold_root} (window predates hot coverage by "
                                f"{max(0.0, hot_coverage_start - scan_start):.0f}s)")

        combined.sort(key=lambda x: x['ts'])
        return combined

    def _copy_images_to_tmp(self, request: KPIMeasurementRequest) -> tuple:
        """
        Copy required images AND thumbnails from hot/cold storage to /tmp/ working directory (RAM).
        Avoids race condition where hot storage images are deleted during processing.

        Returns:
            (working_dir, extra_before_filename) or (None, None) if copy failed
        """
        
        # Create working directory in /tmp/ (RAM)
        working_id = str(uuid.uuid4())[:8]
        working_dir = f'/tmp/kpi_working/{request.execution_result_id[:8]}_{working_id}'
        os.makedirs(working_dir, exist_ok=True)
        
        logger.info(f"📂 Copying images to /tmp/ working directory...")
        logger.info(f"   • Source: {request.capture_dir}")
        logger.info(f"   • Working dir: {working_dir}")
        
        # Calculate scan window based on available information.
        #
        # Window policy (2026-05-20 rewrite — see docs/agent/execution/KPI_TROUBLESHOOTING.md):
        #   The window is bounded by what we KNOW: action_timestamp on the
        #   lower side, and the closest available anchor on the upper side
        #   (verification_timestamp if it exists, else action+wait).
        #   `timeout_ms` (max of kpi_references[i].timeout) is no longer
        #   used to clip scan_start — that clip was inventing inflated KPI
        #   values whenever verification took longer than timeout_ms, e.g.
        #   reporting 5203 ms on a step whose UI actually rendered in ~700
        #   ms. The pixel-diff pre-pass in _scan_until_match keeps the work
        #   cheap even when the window is wide, so there's no perf
        #   incentive to clip the window anymore.
        if request.verification_timestamp:
            # Case 1: scan the entire action → verification gap.
            scan_end = request.verification_timestamp
            scan_start = request.action_timestamp
            logger.info(f"   • Scan mode: WITH verification (action → verification, no clip)")
        elif request.last_action_wait_ms > 0:
            # Case 2: no verification anchor, but we know the wait period.
            wait_end = request.action_timestamp + request.last_action_wait_ms / 1000
            # The KPI reference's own `timeout_ms` is the max time we'd wait for
            # the destination to render. The post-press wait can be SHORTER than
            # that (e.g. wait=10s, timeout=20s) — so the destination may appear
            # after the wait but still inside the timeout window. Take the full
            # timeout as the upper bound. Safe: the scan returns the EARLIEST
            # match, so a wider scan_end never inflates the KPI value, it only
            # lets a late-rendering destination actually be found.
            timeout_end = request.action_timestamp + request.timeout_ms / 1000
            scan_end = max(wait_end, timeout_end)
            # Scan the FULL action→scan_end window — no 20s clip. The old clip
            # ("last 20s only" for waits >60s) made long windows like a device
            # reboot unmeasurable: the boot-to-home transition can land anywhere
            # in the 2-minute window, not just its final 20s. Long windows are
            # now cheap to scan via the coarse-to-fine bounded search in
            # _scan_until_match (see LONG_SCAN_* constants), so there is no perf
            # reason to clip — and the cold-storage frames make the early part
            # of the window available again.
            scan_start = request.action_timestamp
            logger.info(f"   • Scan mode: NO verification, WITH wait "
                        f"(action → max(wait={request.last_action_wait_ms}ms, "
                        f"timeout={request.timeout_ms}ms), no clip)")
        else:
            # Case 3: nothing to anchor against — use timeout_ms forward.
            scan_start = request.action_timestamp
            scan_end = request.action_timestamp + request.timeout_ms / 1000
            logger.info(f"   • Scan mode: NO verification, NO wait (forward from action, "
                        f"capped at {request.timeout_ms}ms)")

        # Appear-then-disappear references describe a transient that plays out
        # over the reference's FULL `timeout` window: the element appears, stays
        # visible, then disappears. The action/verification anchor above only
        # marks the APPEAR side — bounding scan_end there truncates the disappear
        # half and the measurement fails with "appeared but never disappeared".
        # `timeout` is therefore a single GLOBAL window: extend scan_end to
        # action + timeout_ms so the whole appear→disappear sequence is scannable.
        # MUST stay mirrored with the identical block in _scan_until_match.
        if self._is_appear_then_disappear(request):
            atd_end = request.action_timestamp + request.timeout_ms / 1000
            if atd_end > scan_end:
                logger.info(f"   • Appear-then-disappear: extending window to full "
                            f"timeout ({request.timeout_ms}ms global)")
                scan_end = atd_end

        logger.info(f"   • Scan window: {scan_end - scan_start:.2f}s")

        # Discover candidate frames from BOTH hot (5 fps, ~75s) and the cold
        # hour-folder archive (1 fps, ~24h) so a long window still has its older
        # frames. Returns a single mtime-sorted list (paths point at the live
        # source files; we copy the in-window subset to /tmp below).
        copied_captures = 0
        copied_capture_names = []  # Track which captures we copied (dedupe by basename)
        all_available_captures = self._discover_window_captures(request, scan_start, scan_end)

        # Find first capture in scan window
        first_in_window_idx = None
        extra_before_filename = None  # Track the extra frame filename

        for i, cap in enumerate(all_available_captures):
            if scan_start <= cap['ts'] <= scan_end:
                first_in_window_idx = i
                break

        # Copy the frame BEFORE first frame in window (if exists) — the pixel-diff
        # pre-pass uses it as the "still source" reference.
        if first_in_window_idx is not None and first_in_window_idx > 0:
            before_window_cap = all_available_captures[first_in_window_idx - 1]
            dest_path = os.path.join(working_dir, before_window_cap['filename'])
            try:
                shutil.copy2(before_window_cap['path'], dest_path)
                copied_captures += 1
                copied_capture_names.append(before_window_cap['filename'])
                extra_before_filename = before_window_cap['filename']  # Store it
                logger.info(f"📸 Copied extra frame BEFORE: {before_window_cap['path']} → {dest_path}")
            except (OSError, IOError) as e:
                logger.warning(f"Could not copy before-window frame: {e}")

        # Copy all captures in scan window (hot + cold), preserving mtimes so the
        # scan can order and window-filter them identically to the live files.
        for cap in all_available_captures:
            ts = cap['ts']
            if not (scan_start <= ts <= scan_end):
                continue
            filename = cap['filename']
            if filename in copied_capture_names:  # Don't copy twice
                continue
            try:
                dest_path = os.path.join(working_dir, filename)
                shutil.copy2(cap['path'], dest_path)  # copy2 preserves timestamps
                copied_captures += 1
                copied_capture_names.append(filename)
                logger.debug(f"📸 Copied: {cap['path']} → {dest_path}")
            except (OSError, IOError) as e:
                logger.warning(f"Could not copy {cap['path']}: {e}")
                continue
        
        if copied_captures == 0:
            logger.error(f"❌ No captures copied from {request.capture_dir}")
            return None, None
        
        logger.info(f"✅ Copied {copied_captures} captures to /tmp/ (RAM) - includes 1 before scan window")

        # NOTE: we deliberately do NOT copy the FFmpeg hot/thumbnails files.
        # The scan only reads full captures, and the report synthesises its
        # strip thumbnails on-the-fly from the exact full frames it selects
        # (kpi_report_generator.make_thumbnail_from_full). The hot/thumbnails
        # files are numbered with an independent `-start_number` and could
        # point at a different moment after unequal dir cleanups — relying on
        # them caused the "thumbnail ≠ original" mismatch, so they're gone.

        return working_dir, extra_before_filename
    
    def _cleanup_working_dir(self, working_dir: str):
        """Delete working directory and all its contents"""
        if not working_dir or not os.path.exists(working_dir):
            return
        
        try:
            shutil.rmtree(working_dir)
            logger.debug(f"🗑️  Cleaned up working directory: {working_dir}")
        except Exception as e:
            logger.warning(f"Could not cleanup working directory {working_dir}: {e}")
    
    async def _scan_until_match(
        self,
        request: KPIMeasurementRequest,
        capture_dir: str,
        extra_before_filename: Optional[str] = None,
        progress: Optional[Dict] = None,
    ) -> dict:
        """Find the earliest capture where the destination is on screen.

        Two-pass design (2026-05-20 rewrite):
            1. PIXEL-DIFF PRE-PASS — cheap 8x8 aHash on every frame, find
               the first frame that diverges from the "before action"
               frame and stays diverged for AHASH_STABLE_RUN more frames.
               Cost: ~1 ms per frame, no OCR or template-match.
            2. VERIFY THE BOUNDARY — run the real verifications on the
               boundary frame and up to DIFF_BRACKET_VERIFY_DEPTH-1 frames
               forward. The first that passes is the KPI match.
            3. FALLBACK — if the diff pre-pass can't locate a stable
               transition (e.g. animated background or no "before action"
               reference), drop into the original quick-check-then-
               backward-scan algorithm.

        Args:
            request: KPI measurement request.
            capture_dir: Directory holding the in-window captures.
            extra_before_filename: Filename of the frame copied from just
                BEFORE the scan window (anchor for pixel diff). May be
                None if the scan window starts at the very first capture.
        """
        action_timestamp = request.action_timestamp
        verification_timestamp = request.verification_timestamp
        kpi_references = request.kpi_references
        
        logger.info(f"🔍 Scanning captures in: {capture_dir}")
        
        # Get device instance
        from backend_host.src.lib.utils.host_utils import get_device_by_id
        
        device = get_device_by_id(request.device_id)
        if not device:
            return {'success': False, 'error': f'Device {request.device_id} not found', 'captures_scanned': 0}
        
        # Use device's verification_executor
        verif_executor = device.verification_executor
        if not verif_executor:
            return {'success': False, 'error': f'No verification_executor for device {request.device_id}', 'captures_scanned': 0}
        
        # Window policy: must mirror _copy_images_to_tmp exactly, otherwise
        # we'd scan frames that weren't copied (or skip frames that were).
        # Both Case 1 and Case 2 use the FULL action→anchor span — no
        # timeout_ms clip. See _copy_images_to_tmp for the rationale.
        pattern = os.path.join(capture_dir, "capture_*.jpg")
        all_captures = []

        if verification_timestamp:
            scan_end = verification_timestamp
            scan_start = action_timestamp
            logger.info(f"🎯 Scan window: action → verification "
                        f"({scan_end - scan_start:.2f}s, no clip)")
        elif request.last_action_wait_ms > 0:
            # Mirror of _copy_images_to_tmp Case 2: extend scan_end to the full
            # kpi timeout when it exceeds the post-press wait, so a destination
            # that renders after the wait but within timeout_ms is still found.
            wait_end = action_timestamp + request.last_action_wait_ms / 1000
            timeout_end = action_timestamp + request.timeout_ms / 1000
            scan_end = max(wait_end, timeout_end)
            # No 20s clip (mirrors _copy_images_to_tmp Case 2): long windows are
            # handled by the coarse-to-fine bounded scan below, so we scan the
            # whole action→scan_end span.
            scan_start = action_timestamp
            logger.info(f"🎯 Scan window: action → max(wait="
                        f"{request.last_action_wait_ms}ms, timeout={request.timeout_ms}ms) "
                        f"({scan_end - scan_start:.2f}s, no clip)")
        else:
            scan_start = action_timestamp
            scan_end = action_timestamp + request.timeout_ms / 1000
            logger.info(f"🎯 Scan window: action + {request.timeout_ms}ms (forward, no anchor)")

        # Appear-then-disappear: the disappear can land later than the action/
        # verification anchor, so `timeout` defines a single GLOBAL window —
        # extend scan_end to action + timeout_ms. MUST stay mirrored with the
        # identical block in _copy_images_to_tmp (else we'd scan frames that
        # weren't copied, or skip copied frames).
        if self._is_appear_then_disappear(request):
            atd_end = action_timestamp + request.timeout_ms / 1000
            if atd_end > scan_end:
                logger.info(f"🎯 Appear-then-disappear: window extended to full "
                            f"timeout ({request.timeout_ms}ms global)")
                scan_end = atd_end

        for path in glob.glob(pattern):
            if "_thumbnail" in path:
                continue
            try:
                ts = os.path.getmtime(path)
                if scan_start <= ts <= scan_end:
                    all_captures.append({'path': path, 'timestamp': ts})
            except OSError:
                continue
        
        # Sort by timestamp
        all_captures.sort(key=lambda x: x['timestamp'])
        
        if not all_captures:
            return {'success': False, 'error': 'No captures found in time window', 'captures_scanned': 0}
        
        total_captures = len(all_captures)
        
        logger.info(f"📸 Found {total_captures} captures in window")
        
        # Convert kpi_references to verification format
        # CRITICAL: Force timeout=0 to check ONLY the provided image (no future frame scanning)
        verifications = []
        for kpi_ref in kpi_references:
            command = kpi_ref.get('command', 'waitForImageToAppear')
            # Appear-then-disappear refs measure action→appear for KPI; reduce
            # to the appear half so the single-frame (timeout=0) check can match.
            normalized_command = _KPI_APPEAR_NORMALIZE.get(command, command)
            params = dict(kpi_ref.get('params', {}))  # Copy params
            original_timeout = params.get('timeout', 0)
            params['timeout'] = 0  # Force single-image check (no waiting for future frames)
            verifications.append({
                'verification_type': kpi_ref.get('verification_type', 'image'),
                'command': normalized_command,
                'params': params
            })
            if normalized_command != command:
                logger.info(f"   • Verification: {command} → {normalized_command} "
                            f"(appear-then-disappear reduced to appear for KPI; timeout forced to 0s)")
            else:
                logger.info(f"   • Verification: {command} (timeout: {original_timeout}ms → forced to 0 for single-image check)")
        
        logger.info(f"   • Total verifications configured: {len(verifications)}")
        
        # The scan calls execute_verifications repeatedly against successive
        # captures. The result of each call carries verification_evidence_list:
        # per-reference evidence (reference image, source crop, pass/fail,
        # match details). The report generator's "Verification (N)" cards
        # are built from that list — and the kpi_executor is the authoritative
        # source of it. We track `latest_evidence` across every call so that:
        #   - on success, we forward the evidence from the matching capture
        #   - on failure, we forward the last attempted evidence (which
        #     reference and source crop were checked, what didn't match)
        latest_evidence: list = []

        # Helper to test a capture. Returns (success, full_result_dict).
        async def test_capture(capture, label):
            logger.info(f"🔍 Quick check - {label}: {os.path.basename(capture['path'])}")
            try:
                result = await verif_executor.execute_verifications(
                    verifications=verifications,
                    userinterface_name=request.userinterface_name,  # MANDATORY parameter
                    image_source_url=capture['path'],
                    team_id=request.team_id,
                    verification_pass_condition=request.verification_pass_condition,  # Match live nav verdict ('all'/'any')
                    suppress_failure_report=True  # No per-frame R2 upload; keeps scan within budget
                )
                success = result.get('success', False)
                logger.info(f"   ↳ Result: {success}")
                return success, result
            except Exception as e:
                logger.error(f"   ↳ ERROR in test_capture: {e}")
                import traceback
                traceback.print_exc()
                return False, {}

        captures_scanned = 0
        checked_indices: set = set()

        from shared.src.lib.utils.scan_mosaic import format_offset

        def _record_probe(idx: int, capture: dict, success, result) -> None:
            """Record a single verifier probe: mark the index checked, remember
            its pass/fail (for the mosaic border), and stash its evidence —
            annotated with the frame's offset — so the report can render one
            verification card per probed frame. Also keeps `latest_evidence`
            current for the single-card success path. Accumulates per frame
            instead of overwriting, so every probed frame survives into the
            report (and is force-kept in the mosaic)."""
            nonlocal latest_evidence
            checked_indices.add(idx)
            self._probe_outcomes[idx] = bool(success)
            ev = result.get('verification_evidence_list') if isinstance(result, dict) else None
            if ev:
                latest_evidence = ev
                offset = capture['timestamp'] - request.action_timestamp
                name = os.path.basename(capture['path']).replace('capture_', '').replace('.jpg', '')
                annotated = []
                for item in ev:
                    it = dict(item)
                    it['frame_index'] = idx
                    it['frame_label'] = f"{name} · {format_offset(offset)}"
                    it['frame_offset'] = offset
                    # The probed capture itself — lets the report draw the
                    # search-area rectangle on THIS frame (not the match frame).
                    it['capture_path'] = capture['path']
                    # Probe-level outcome (pass condition over all refs) — the
                    # report's frame chips are colored from this, while item
                    # 'success' stays the per-reference verdict.
                    it['frame_success'] = bool(success)
                    it.setdefault('success', bool(success))
                    annotated.append(it)
                self._probe_evidence[idx] = annotated

        # Sync local counters into the caller's progress dict so that if
        # wait_for trips the deadline mid-scan, _process_measurement can
        # still report captures_scanned (Grafana) + the last verifier's
        # evidence (failure report). Cheap — dict assignment, ~ns.
        def _sync_progress() -> None:
            if progress is not None:
                progress['captures_scanned'] = captures_scanned
                progress['verification_evidence_list'] = latest_evidence

        # Memoised single-frame verify by index — used by the coarse-to-fine
        # bounded search so its binary refinement never re-runs the (expensive)
        # verifier on a frame it has already probed.
        probe_cache: Dict[int, bool] = {}

        async def _probe(idx: int, label: str) -> bool:
            nonlocal captures_scanned
            if idx in probe_cache:
                return probe_cache[idx]
            captures_scanned += 1
            _sync_progress()
            ok, result = await test_capture(all_captures[idx], label)
            _record_probe(idx, all_captures[idx], ok, result)
            _sync_progress()
            probe_cache[idx] = ok
            return ok

        def _match_result(idx: int, algorithm: str) -> dict:
            return {
                'success': True,
                'timestamp': all_captures[idx]['timestamp'],
                'capture_path': all_captures[idx]['path'],
                'capture_index': idx,
                'all_captures': all_captures,
                'captures_scanned': captures_scanned,
                'error': None,
                'algorithm': algorithm,
                'verification_evidence_list': latest_evidence,
            }

        def _no_match_result(algorithm: str) -> dict:
            window_duration = scan_end - scan_start
            return {
                'success': False,
                'timestamp': None,
                'capture_index': None,
                'all_captures': all_captures,
                'captures_scanned': captures_scanned,
                'error': f'No match found in {total_captures} captures '
                         f'({window_duration:.2f}s window, {algorithm})',
                'algorithm': algorithm,
                'verification_evidence_list': latest_evidence,
            }

        async def _bounded_earliest_match() -> dict:
            """Coarse-to-fine boundary search for the earliest matching frame.

            Used for LONG windows (device reboot / multi-minute waits) where an
            exhaustive frame-by-frame scan would blow the verifier budget. Three
            stages: (1) coarse time-grid probe to bracket the absent→present
            transition, (2) binary refinement to the earliest matching frame,
            (3) sustain check to reject a transient false-positive (a frame that
            momentarily resembles the target mid-boot). On a rejected island the
            search resumes to its right. ~log(N)+grid verifier calls vs O(N).

            Assumes the target is a ~monotone step (absent → present → stays).
            """
            # Build a coarse time grid (≈ every LONG_SCAN_COARSE_STEP_SECONDS),
            # always including the final frame so a late transition is caught.
            grid: List[int] = []
            next_t = all_captures[0]['timestamp']
            for i, cap in enumerate(all_captures):
                if cap['timestamp'] >= next_t:
                    grid.append(i)
                    next_t = cap['timestamp'] + LONG_SCAN_COARSE_STEP_SECONDS
            if not grid or grid[-1] != total_captures - 1:
                grid.append(total_captures - 1)

            logger.info(f"🪜 Coarse-to-fine scan: {len(grid)} coarse probe points "
                        f"over {total_captures} frames")

            search_from = 0          # earliest index that could still be absent
            island_retries = 0

            while True:
                # Stage 1: first coarse point (>= search_from) that matches.
                lo_absent: Optional[int] = None
                hi_match: Optional[int] = None
                for gi in grid:
                    if gi < search_from:
                        continue
                    if await _probe(gi, f"coarse grid idx {gi}/{total_captures}"):
                        hi_match = gi
                        break
                    lo_absent = gi
                if hi_match is None:
                    return _no_match_result('coarse_to_fine_no_match')

                # Stage 2: binary-refine the earliest match in (lo, hi_match].
                lo = lo_absent if lo_absent is not None else search_from - 1
                hi = hi_match
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if await _probe(mid, f"refine idx {mid}/{total_captures}"):
                        hi = mid
                    else:
                        lo = mid
                boundary = hi

                # Stage 3: sustain check ~LONG_SCAN_SUSTAIN_SECONDS later.
                target_t = all_captures[boundary]['timestamp'] + LONG_SCAN_SUSTAIN_SECONDS
                sustain_idx = boundary
                for j in range(boundary + 1, total_captures):
                    sustain_idx = j
                    if all_captures[j]['timestamp'] >= target_t:
                        break
                if sustain_idx == boundary:
                    # Boundary is at/near the end — nothing later to check; the
                    # coarse probe already confirmed presence here, accept it.
                    return _match_result(boundary, 'coarse_to_fine')
                if await _probe(sustain_idx, f"sustain idx {sustain_idx}/{total_captures}"):
                    return _match_result(boundary, 'coarse_to_fine')

                # Transient island: skip past it and search again to its right.
                island_retries += 1
                if island_retries > LONG_SCAN_MAX_ISLAND_RETRIES:
                    logger.warning(f"   ↳ Sustain failed {island_retries}x; accepting "
                                   f"boundary idx {boundary} anyway")
                    return _match_result(boundary, 'coarse_to_fine+unsustained')
                logger.info(f"   ↳ Transient match at idx {boundary} (gone by idx "
                            f"{sustain_idx}) — resuming search to the right")
                search_from = sustain_idx + 1
                if search_from >= total_captures:
                    return _no_match_result('coarse_to_fine_transient_only')

        async def _exhaustive_dedup_scan() -> dict:
            """Frame-by-frame fallback when the coarse grid found nothing.

            The coarse probe samples every ~LONG_SCAN_COARSE_STEP_SECONDS, so a
            target only briefly on screen can fall entirely between two probes.
            Here we scan forward from the start and return the EARLIEST matching
            frame (action→appear is the KPI; we do NOT sustain-check — a transient
            target is a valid match, unlike the coarse path which guards against a
            mid-boot false positive).

            Cost control (applies to both image and text references):
              - collapse near-duplicate frames by an 8x8 aHash over the
                verification's search ROI, with a hard cap on consecutive skips
                (EXHAUSTIVE_MAX_SKIP_RUN) so even an all-identical window keeps 1
                of every 5 frames and a transient target can't be skipped by more
                than 4 frames;
              - if the distinct set is still larger than EXHAUSTIVE_MAX_PROBES,
                even-sample down to that ceiling ("max out").
            """
            # ROI for dedup = the first reference's search area; None → full frame.
            roi = None
            for v in verifications:
                a = (v.get('params') or {}).get('area')
                if isinstance(a, dict) and all(a.get(k) is not None for k in ('x', 'y', 'width', 'height')):
                    roi = a
                    break

            candidates: List[int] = []
            last_hash: Optional[int] = None
            run = 0
            for i in range(total_captures):
                sig = _ahash64_roi(all_captures[i]['path'], roi)
                similar = (last_hash is not None and sig is not None
                           and _hamming64(sig, last_hash) < EXHAUSTIVE_DEDUP_HAMMING)
                if similar and run < EXHAUSTIVE_MAX_SKIP_RUN:
                    run += 1
                    continue
                candidates.append(i)
                run = 0
                if sig is not None:
                    last_hash = sig

            deduped = len(candidates)
            if deduped > EXHAUSTIVE_MAX_PROBES:
                stride = deduped / float(EXHAUSTIVE_MAX_PROBES)
                candidates = [candidates[int(k * stride)] for k in range(EXHAUSTIVE_MAX_PROBES)]
            logger.info(f"🔁 Exhaustive scan: {total_captures} frames → {deduped} distinct "
                        f"(ROI dedup, skip-cap {EXHAUSTIVE_MAX_SKIP_RUN}, "
                        f"roi={'yes' if roi else 'full-frame'}) → verifying "
                        f"{len(candidates)} (ceiling {EXHAUSTIVE_MAX_PROBES})")

            for idx in candidates:
                if idx in probe_cache:
                    if probe_cache[idx]:
                        return _match_result(idx, 'exhaustive_dedup')
                    continue
                if await _probe(idx, f"exhaustive idx {idx}/{total_captures}"):
                    return _match_result(idx, 'exhaustive_dedup')

            return _no_match_result('exhaustive_dedup_no_match')

        # ─────────────────────────────────────────────────────────────────
        # PASS 1: PIXEL-DIFF BOUNDARY DETECTION
        # ─────────────────────────────────────────────────────────────────
        # Hash every in-window frame (and the before-window reference if we
        # have one) with 8×8 aHash. Walk forward, find the first frame
        # whose Hamming distance from the reference exceeds the threshold
        # AND stays above it for AHASH_STABLE_RUN more frames. That's the
        # transition boundary — verify it with the real verifier in PASS 2.
        #
        # Skip the pre-pass when:
        #   - There's no before-window frame to use as the "still source"
        #     reference (would have nothing to compare against).
        #   - The window has fewer than (AHASH_STABLE_RUN + 1) frames to
        #     confirm a stable boundary.
        # ─────────────────────────────────────────────────────────────────
        before_window_path: Optional[str] = None
        if extra_before_filename:
            cand = os.path.join(capture_dir, extra_before_filename)
            if os.path.exists(cand):
                before_window_path = cand

        diff_boundary_idx: Optional[int] = None
        diff_skipped_reason: Optional[str] = None

        if before_window_path is None:
            diff_skipped_reason = "no before-window reference frame"
        elif total_captures < (AHASH_STABLE_RUN + 1):
            diff_skipped_reason = f"only {total_captures} frames (need {AHASH_STABLE_RUN + 1}+)"
        else:
            ref_hash = _ahash64(before_window_path)
            if ref_hash is None:
                diff_skipped_reason = "could not hash before-window reference"
            else:
                logger.info(f"🧮 Pass 1: pixel-diff vs {os.path.basename(before_window_path)}")
                diffs: List[Optional[int]] = []
                for cap in all_captures:
                    h = _ahash64(cap['path'])
                    diffs.append(None if h is None else _hamming64(h, ref_hash))

                logger.info(f"   ↳ Hamming distances: " +
                            ' '.join(['?' if d is None else str(d) for d in diffs]))

                # Find first i where diff[i] >= threshold AND the next
                # AHASH_STABLE_RUN frames also exceed it. Single-frame
                # spikes (codec noise, focus-ring flicker) are rejected.
                for i in range(total_captures - AHASH_STABLE_RUN):
                    window = diffs[i:i + AHASH_STABLE_RUN + 1]
                    if any(d is None for d in window):
                        continue
                    if all(d >= AHASH_DIFF_THRESHOLD for d in window):
                        diff_boundary_idx = i
                        break

                if diff_boundary_idx is None:
                    logger.info(f"   ↳ No stable divergence found "
                                f"(threshold={AHASH_DIFF_THRESHOLD}, "
                                f"stable_run={AHASH_STABLE_RUN}) — falling back to exhaustive scan")
                else:
                    logger.info(f"   ↳ Boundary candidate at idx {diff_boundary_idx} "
                                f"({os.path.basename(all_captures[diff_boundary_idx]['path'])})")

        if diff_skipped_reason:
            logger.info(f"🧮 Pass 1 skipped: {diff_skipped_reason}")

        # ─────────────────────────────────────────────────────────────────
        # PASS 2: VERIFY BOUNDARY (cheap — 1–3 calls in the common case)
        # ─────────────────────────────────────────────────────────────────
        if diff_boundary_idx is not None:
            max_walk = min(DIFF_BRACKET_VERIFY_DEPTH, total_captures - diff_boundary_idx)
            for step in range(max_walk):
                idx = diff_boundary_idx + step
                captures_scanned += 1
                _sync_progress()
                ok, result = await test_capture(
                    all_captures[idx],
                    f"diff boundary +{step} (idx {idx}/{total_captures})",
                )
                _record_probe(idx, all_captures[idx], ok, result)
                _sync_progress()
                if ok:
                    return {
                        'success': True,
                        'timestamp': all_captures[idx]['timestamp'],
                        'capture_path': all_captures[idx]['path'],
                        'capture_index': idx,
                        'all_captures': all_captures,
                        'captures_scanned': captures_scanned,
                        'error': None,
                        'algorithm': 'pixel_diff_then_verify',
                        'verification_evidence_list': latest_evidence,
                    }
            logger.info(f"   ↳ Boundary did not verify within {max_walk} frames — "
                        f"falling through")

        # ─────────────────────────────────────────────────────────────────
        # LONG-WINDOW FALLBACK: coarse-to-fine bounded search.
        # For windows longer than LONG_SCAN_WINDOW_SECONDS (device reboot,
        # multi-minute waits) the exhaustive step-2 backward scan below is
        # O(window) and would blow the verifier budget on OCR references. Use
        # the bounded boundary search instead (~log(N)+grid verifier calls).
        # ─────────────────────────────────────────────────────────────────
        window_seconds = scan_end - scan_start
        if window_seconds > LONG_SCAN_WINDOW_SECONDS:
            logger.info(f"🪜 Long window ({window_seconds:.0f}s > "
                        f"{LONG_SCAN_WINDOW_SECONDS:.0f}s): coarse-to-fine bounded scan "
                        f"(skipping exhaustive backward scan)")
            bounded = await _bounded_earliest_match()
            # The coarse grid samples every ~10s, so a target that appears AND
            # disappears between two probes is stepped over entirely. When the
            # grid finds nothing at all, fall back to a frame-by-frame scan from
            # the start (dedup-bounded for OCR) before declaring no match.
            if not bounded.get('success') and bounded.get('algorithm') == 'coarse_to_fine_no_match':
                logger.info("🔁 Coarse grid found no match — exhaustive dedup fallback")
                return await _exhaustive_dedup_scan()
            return bounded

        # ─────────────────────────────────────────────────────────────────
        # FALLBACK: Original quick-check + step-2 backward scan.
        # Kept verbatim from the pre-2026-05-20 implementation as a safety
        # net for animated-background screens where pixel diff can't find
        # a stable transition.
        # ─────────────────────────────────────────────────────────────────
        logger.info(f"⚡ Fallback Phase 1: Quick check (early only)")

        # Quick check: T0+200ms (early in the scan window)
        target_ts = scan_start + 0.2
        early_idx = min(range(total_captures), key=lambda i: abs(all_captures[i]['timestamp'] - target_ts))
        if early_idx in checked_indices:
            logger.info(f"   ↳ Skipping early idx {early_idx} (already verified in pass 2)")
            early_ok = False
            early_result: dict = {}
        else:
            captures_scanned += 1
            _sync_progress()
            early_ok, early_result = await test_capture(all_captures[early_idx], f"early check (start+200ms, idx {early_idx}/{total_captures})")
            _record_probe(early_idx, all_captures[early_idx], early_ok, early_result)
            _sync_progress()
        if early_ok:
            return {
                'success': True,
                'timestamp': all_captures[early_idx]['timestamp'],
                'capture_path': all_captures[early_idx]['path'],
                'capture_index': early_idx,  # ✅ Return index for thumbnail selection
                'all_captures': all_captures,  # ✅ Return full list for before/match selection
                'captures_scanned': captures_scanned,
                'error': None,
                'algorithm': 'quick_check_early',
                'verification_evidence_list': latest_evidence,
            }

        logger.info(f"⚡ Quick check: no early match, proceeding to backward scan")
        checked_indices.add(early_idx)
        logger.info(f"   ↳ Early idx checked: {early_idx}")
        
        # PHASE 2: BACKWARD SCAN (optimized to find earliest match)
        logger.info(f"🔙 Phase 2: Backward scan from verification → action")
        logger.info(f"   ↳ Will scan {total_captures - len(checked_indices)} remaining captures")
        logger.info(f"   ↳ Strategy: Scan backward in steps of 2, fill gap when boundary found")
        
        earliest_match = None  # Track the earliest (closest to action) match found
        match_evidence: list = []  # Evidence captured AT the matching frame

        # Scan backward in steps of 2 (skip every other frame for speed)
        for i in range(total_captures - 1, -1, -2):
            if i in checked_indices:
                continue

            capture = all_captures[i]
            captures_scanned += 1
            _sync_progress()

            logger.info(f"🔍 Backward scan {i+1}/{total_captures}: {os.path.basename(capture['path'])}")

            try:
                result = await verif_executor.execute_verifications(
                    verifications=verifications,
                    userinterface_name=request.userinterface_name,  # MANDATORY parameter
                    image_source_url=capture['path'],
                    team_id=request.team_id,
                    verification_pass_condition=request.verification_pass_condition,  # Match live nav verdict ('all'/'any')
                    suppress_failure_report=True  # No per-frame R2 upload; keeps scan within budget
                )
                # Record this probe (pass/fail + evidence) per frame.
                _record_probe(i, capture, result.get('success'), result)
                _sync_progress()

                if result.get('success'):
                    # Found a match - keep scanning backward to find earliest
                    earliest_match = {
                        'timestamp': capture['timestamp'],
                        'capture_path': capture['path'],
                        'index': i
                    }
                    match_evidence = result.get('verification_evidence_list') or []
                    logger.info(f"   ↳ Match found! Continuing backward (step -2)...")
                elif earliest_match:
                    # No match after having matches - check the skipped frame (i+1) to fill the gap
                    gap_idx = i + 1
                    if gap_idx < total_captures and gap_idx not in checked_indices:
                        logger.info(f"   ↳ Checking skipped frame at idx {gap_idx} to confirm boundary...")
                        gap_capture = all_captures[gap_idx]
                        captures_scanned += 1
                        _sync_progress()

                        gap_result = await verif_executor.execute_verifications(
                            verifications=verifications,
                            userinterface_name=request.userinterface_name,
                            image_source_url=gap_capture['path'],
                            team_id=request.team_id,
                            verification_pass_condition=request.verification_pass_condition,  # Match live nav verdict ('all'/'any')
                            suppress_failure_report=True  # No per-frame R2 upload; keeps scan within budget
                        )
                        _record_probe(gap_idx, gap_capture, gap_result.get('success'), gap_result)
                        _sync_progress()

                        if gap_result.get('success'):
                            # Gap frame matches, so earliest is the gap frame
                            earliest_match = {
                                'timestamp': gap_capture['timestamp'],
                                'capture_path': gap_capture['path'],
                                'index': gap_idx
                            }
                            match_evidence = gap_result.get('verification_evidence_list') or []
                            logger.info(f"   ↳ Gap frame matches - earliest is at idx {gap_idx}")

                    # Return the earliest match found
                    logger.info(f"   ↳ Boundary confirmed - earliest match at idx {earliest_match['index']}")
                    return {
                        'success': True,
                        'timestamp': earliest_match['timestamp'],
                        'capture_path': earliest_match['capture_path'],
                        'capture_index': earliest_match['index'],  # ✅ Return index for thumbnail selection
                        'all_captures': all_captures,  # ✅ Return full list for before/match selection
                        'captures_scanned': captures_scanned,
                        'error': None,
                        'algorithm': 'backward_scan_step2',
                        'verification_evidence_list': match_evidence,
                    }
                else:
                    logger.debug(f"   ↳ No match")
            except Exception as e:
                logger.error(f"   ↳ ERROR in backward scan: {e}")
                import traceback
                traceback.print_exc()
                continue

        # If we have a match at the end (reached start while still matching)
        # Check if there's a skipped frame at index 0 that we need to verify
        if earliest_match:
            if earliest_match['index'] > 0 and 0 not in checked_indices:
                logger.info(f"   ↳ Checking first frame (idx 0) to confirm earliest...")
                first_capture = all_captures[0]
                captures_scanned += 1
                _sync_progress()

                first_result = await verif_executor.execute_verifications(
                    verifications=verifications,
                    userinterface_name=request.userinterface_name,
                    image_source_url=first_capture['path'],
                    team_id=request.team_id,
                    verification_pass_condition=request.verification_pass_condition,  # Match live nav verdict ('all'/'any')
                    suppress_failure_report=True  # No per-frame R2 upload; keeps scan within budget
                )
                _record_probe(0, first_capture, first_result.get('success'), first_result)
                _sync_progress()

                if first_result.get('success'):
                    earliest_match = {
                        'timestamp': first_capture['timestamp'],
                        'capture_path': first_capture['path'],
                        'index': 0
                    }
                    match_evidence = first_result.get('verification_evidence_list') or []
                    logger.info(f"   ↳ First frame matches - earliest is at idx 0")

            logger.info(f"   ↳ Reached start of window - earliest match at idx {earliest_match['index']}")
            return {
                'success': True,
                'timestamp': earliest_match['timestamp'],
                'capture_path': earliest_match['capture_path'],
                'capture_index': earliest_match['index'],  # ✅ Return index for thumbnail selection
                'all_captures': all_captures,  # ✅ Return full list for before/match selection
                'captures_scanned': captures_scanned,
                'error': None,
                'algorithm': 'backward_scan_step2',
                'verification_evidence_list': match_evidence,
            }
        
        # No match found - backward scan completed without finding match
        logger.info(f"🔙 Backward scan completed: checked {captures_scanned} captures total")
        window_duration = scan_end - scan_start
        error_msg = f'No match found in {total_captures} captures ({window_duration:.2f}s window)'
        logger.warning(f"⚠️  {error_msg}")
        
        return {
            'success': False,
            'timestamp': None,
            'capture_index': None,  # ✅ Include for consistency
            'all_captures': all_captures,  # ✅ Include for consistency (even on failure)
            'captures_scanned': captures_scanned,
            'error': error_msg,
            'algorithm': 'exhaustive_search_failed',
            # No match was ever found — forward the last attempted evidence
            # so the failure report still shows which references were
            # checked and why they didn't match.
            'verification_evidence_list': latest_evidence,
        }

    def _is_appear_then_disappear(self, request: KPIMeasurementRequest) -> bool:
        """True if any KPI reference is a waitFor*ToAppearThenDisappear command."""
        return any(
            kpi_ref.get('command') in _KPI_ATD_COMMANDS
            for kpi_ref in request.kpi_references
        )

    async def _scan_for_disappear(
        self,
        request: KPIMeasurementRequest,
        capture_dir: str,
        appear_result: dict,
    ) -> Optional[dict]:
        """Phase B of an appear-then-disappear measurement.

        Starting one frame past the appear frame, walk forward and run the
        `waitFor*ToDisappear` half on each capture. The first frame where it
        passes (element gone) is the disappear frame — the measurement
        endpoint. Returns a dict with `disappear_timestamp` / `disappear_index`
        / `captures_scanned` and a combined `evidence_list` of
        [appear card, disappear card] for the report. Returns None if the
        element never disappears within the scan window (→ clean failure).
        """
        all_captures = appear_result.get('all_captures') or []
        appear_index = appear_result.get('capture_index')
        if appear_index is None or appear_index >= len(all_captures) - 1:
            logger.info("🔁 No frame after appear within window — cannot observe disappear")
            return None

        from backend_host.src.lib.utils.host_utils import get_device_by_id
        device = get_device_by_id(request.device_id)
        if not device or not getattr(device, 'verification_executor', None):
            return None
        verif_executor = device.verification_executor

        # Build the disappear verifications (ThenDisappear → Disappear, single-frame).
        disappear_verifications = []
        for kpi_ref in request.kpi_references:
            disappear_command = _KPI_DISAPPEAR_NORMALIZE.get(kpi_ref.get('command', ''))
            if not disappear_command:
                continue
            params = dict(kpi_ref.get('params', {}))
            params['timeout'] = 0
            disappear_verifications.append({
                'verification_type': kpi_ref.get('verification_type', 'image'),
                'command': disappear_command,
                'params': params,
            })
        if not disappear_verifications:
            return None

        appear_evidence = appear_result.get('verification_evidence_list') or []
        captures_scanned = 0
        for i in range(appear_index + 1, len(all_captures)):
            capture = all_captures[i]
            captures_scanned += 1
            try:
                result = await verif_executor.execute_verifications(
                    verifications=disappear_verifications,
                    userinterface_name=request.userinterface_name,
                    image_source_url=capture['path'],
                    team_id=request.team_id,
                    verification_pass_condition=request.verification_pass_condition,  # Match live nav verdict ('all'/'any')
                    suppress_failure_report=True,
                )
            except Exception as e:
                logger.error(f"   ↳ ERROR in disappear scan: {e}")
                continue
            if result.get('success'):  # disappear verification passed → element gone
                disappear_evidence = result.get('verification_evidence_list') or []
                logger.info(f"🔍 Disappear at idx {i}/{len(all_captures)}: "
                            f"{os.path.basename(capture['path'])}")
                return {
                    'disappear_timestamp': capture['timestamp'],
                    'disappear_index': i,
                    'captures_scanned': captures_scanned,
                    'evidence_list': appear_evidence + disappear_evidence,
                }
        logger.info(f"🔁 Element still present through end of window "
                    f"({captures_scanned} frames after appear) — no disappear")
        return None

    def _update_result(self, execution_result_id: str, team_id: str, success: bool, kpi_ms: int, error: str, report_url: str = None, display_label: str = None):
        """Update execution_results with KPI measurement.

        `display_label` is the run-level friendly name carried on the request
        (script-set via navigation_context, else the action_set's kpi_name). It
        is persisted so the KPI dashboard can label the row by it — the edge
        alone can't, since several measurements may share one edge.
        """
        try:
            from shared.src.lib.database.execution_results_db import update_execution_result_with_kpi
            
            result = update_execution_result_with_kpi(
                execution_result_id=execution_result_id,
                team_id=team_id,
                kpi_measurement_success=success,
                kpi_measurement_ms=kpi_ms,
                kpi_measurement_error=error,
                kpi_report_url=report_url,
                kpi_display_label=display_label
            )
            
            if result:
                if report_url:
                    logger.info(f"💾 Stored KPI result: {kpi_ms}ms (success: {success}) - Report: {report_url}")
                else:
                    logger.info(f"💾 Stored KPI result: {kpi_ms}ms (success: {success})")
            else:
                logger.warning(f"⚠️  Failed to update execution_result_id: {execution_result_id[:8]}")
                
        except Exception as e:
            logger.error(f"❌ Error storing KPI result: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_existing_requests(self):
        """Process any existing request files on startup"""
        logger.info("Scanning for existing KPI requests...")
        
        request_files = sorted(glob.glob(os.path.join(KPI_QUEUE_DIR, 'kpi_request_*.json')))
        
        if request_files:
            logger.info(f"Found {len(request_files)} pending KPI requests")
            for request_file in request_files:
                try:
                    self._enqueue_request_file(request_file)
                except Exception as e:
                    logger.error(f"Error loading request {request_file}: {e}")
        else:
            logger.info("No pending KPI requests")
    
    def _enqueue_request_file(self, request_file: str):
        """Load and enqueue a request file"""
        with open(request_file, 'r') as f:
            data = json.load(f)

        data['_request_file'] = request_file
        # Stamp the original on-disk mtime so the worker can detect
        # late-dequeues (queue backlog) when it finally pulls the request.
        try:
            data['_queued_at'] = os.path.getmtime(request_file)
        except OSError:
            data['_queued_at'] = time.time()
        request = KPIMeasurementRequest(data)
        
        try:
            self.work_queue.put_nowait((request_file, request))
            logger.info(f"📋 Queued KPI request: {os.path.basename(request_file)}")
        except queue.Full:
            logger.error(f"❌ Queue full! Dropping request: {os.path.basename(request_file)}")
    
    def _handle_kpi_request(self, path, filename):
        """Handle KPI request file event"""
        if filename.startswith('kpi_request_') and filename.endswith('.json'):
            request_file = os.path.join(path, filename)
            logger.info(f"🆕 New KPI request detected: {filename}")
            
            try:
                self._enqueue_request_file(request_file)
            except Exception as e:
                logger.error(f"Error enqueueing request {filename}: {e}")
    
    def run(self):
        """Main event loop - watch for new KPI request files"""
        logger.info("=" * 80)
        logger.info(f"Starting KPI executor {self._watcher_type} event loop")
        logger.info("Zero CPU when idle - event-driven processing")
        logger.info("=" * 80)
        
        # Process any existing requests first
        self._process_existing_requests()
        
        if IS_LINUX:
            self._run_inotify()
        else:
            self._run_watchdog()
    
    def _run_inotify(self):
        """Linux inotify event loop"""
        try:
            for event in self.inotify.event_gen(yield_nones=False):
                (_, type_names, path, filename) = event
                
                if 'IN_MOVED_TO' not in type_names:
                    continue
                
                self._handle_kpi_request(path, filename)
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.inotify.remove_watch(KPI_QUEUE_DIR)
    
    def _run_watchdog(self):
        """macOS/cross-platform watchdog event loop"""
        service = self
        
        class KPIRequestHandler(FileSystemEventHandler):
            def on_moved(self, event):
                if event.is_directory:
                    return
                path = os.path.dirname(event.dest_path)
                filename = os.path.basename(event.dest_path)
                service._handle_kpi_request(path, filename)
            
            def on_created(self, event):
                if event.is_directory:
                    return
                path = os.path.dirname(event.src_path)
                filename = os.path.basename(event.src_path)
                if not filename.startswith('.'):
                    time.sleep(0.05)
                    service._handle_kpi_request(path, filename)
        
        event_handler = KPIRequestHandler()
        self.observer.schedule(event_handler, KPI_QUEUE_DIR, recursive=False)
        
        try:
            self.observer.start()
            logger.info(f"Watchdog observer started for {KPI_QUEUE_DIR}")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.observer.stop()
            self.observer.join()


def main():
    """Main entry point"""
    
    # Kill any existing kpi_executor instances
    from shared.src.lib.utils.system_utils import kill_existing_script_instances
    killed = kill_existing_script_instances('kpi_executor.py')
    if killed:
        logger.info(f"Killed existing kpi_executor instances: {killed}")
        time.sleep(1)
    
    logger.info("=" * 80)
    logger.info("Starting KPI Measurement Executor Service")
    logger.info("Performance: Zero CPU when idle, event-driven processing")
    logger.info("Queue: JSON files in /tmp/kpi_queue/")
    logger.info("=" * 80)
    
    # Start service
    service = KPIExecutorService()
    service.start()
    service.run()


if __name__ == '__main__':
    main()

