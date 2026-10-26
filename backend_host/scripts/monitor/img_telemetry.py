"""Image telemetry (TASK-157, phase 1 + 2): what the img monitor receives per device, and what the VPT processes cost.

Metadata only. Nothing here decodes a frame: the file-event side counts an arrival and its size (one os.stat), the
frame worker counts an analyzed frame and how old it was, the drain path counts dropped frames. State per device is a
few integers and a 12-bucket histogram. Every WINDOW_S seconds one thread

  * writes `<metadata>/telemetry_status.json` per device (the host status payload and the stream overlay read it),
  * queues one row per device plus one `_host` row (process CPU / RSS, load per core) for a batch writer that inserts
    them into `image_telemetry_buckets` (idempotent upsert). A bounded queue, a timeout and backoff: a slow or dead DB
    drops rows (counted in `samples_dropped`), it never blocks a frame thread.

Names say what is measured: `frames_arrived` is the capture rate seen by the monitor (counted before the LIFO drain),
`image_bytes` / `estimated_image_throughput_bps` is JPEG on disk — not the ffmpeg stream bitrate, not network.
Unsupported or failed readings are None (null in the DB), never 0.

On per device when its monitor profile says `img.telemetry: true` (tv_app does; the others do not). Host kill switch:
IMG_TELEMETRY=false. IMG_TELEMETRY_WINDOW_S (default 60, 10..600).
Rollback: IMG_TELEMETRY=false and restart vpt-monitor-img, or `telemetry: false` in the profile. Retention: IMG_TELEMETRY_RETENTION_DAYS (default 7), pruned once a day.
"""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger('capture_monitor')

SCHEMA_VERSION = 1
HOST_ROW = '_host'
# Upper bounds (ms) of the frame-age histogram; the last bucket is open-ended.
AGE_BOUNDS_MS = (100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000)
_FALSY = ('0', 'false', 'no', 'off')
DB_QUEUE_MAX = 600            # rows; ~10 devices x 60 windows. Beyond this the oldest row is dropped.
DB_BATCH_MAX = 200
DB_BACKOFF_MAX_S = 300.0
STATUS_FILE = 'telemetry_status.json'


def enabled():
    """Host kill switch: IMG_TELEMETRY=false (or 0/no/off) turns telemetry off for every profile. Unset or true: the
    device's monitor profile decides (`img.telemetry`, on in tv_app)."""
    return os.getenv('IMG_TELEMETRY', '').strip().lower() not in _FALSY


def window_seconds():
    try:
        return min(600, max(10, int(os.getenv('IMG_TELEMETRY_WINDOW_S', '60'))))
    except ValueError:
        return 60


class _Counters:
    __slots__ = ('arrived', 'analyzed', 'dropped', 'bytes', 'ages', 'age_max', 'queue_max', 'last_age_ms')

    def __init__(self):
        self.arrived = self.analyzed = self.dropped = self.bytes = 0
        self.ages = [0] * (len(AGE_BOUNDS_MS) + 1)
        self.age_max = 0.0
        self.queue_max = 0
        self.last_age_ms = None


def age_percentile_ms(hist, pct):
    """Upper bound (ms) of the bucket holding the pct-th percentile; None for an empty histogram.
    The open-ended last bucket reports the largest bound (a floor, not an estimate)."""
    total = sum(hist)
    if not total:
        return None
    target = total * pct / 100.0
    seen = 0
    for i, n in enumerate(hist):
        seen += n
        if seen >= target:
            return float(AGE_BOUNDS_MS[min(i, len(AGE_BOUNDS_MS) - 1)])
    return float(AGE_BOUNDS_MS[-1])


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class ImageTelemetry:
    def __init__(self, host_name, window_s=None, status_dir_fn=None, device_id_fn=None, sink=None, proc_sampler=None):
        self.host_name = host_name
        self.window_s = window_s or window_seconds()
        self._status_dir_fn = status_dir_fn          # capture_folder -> metadata dir
        self._device_id_fn = device_id_fn            # capture_folder -> device id
        self._lock = threading.Lock()
        self._dev = {}                               # capture_folder -> _Counters
        self._window_start = time.time()
        self._rows = queue.Queue(maxsize=DB_QUEUE_MAX)
        self._rows_dropped = 0
        self._sink = sink                            # callable(list_of_rows) -> raises on failure; default: supabase upsert
        self._proc = proc_sampler or ProcessSampler()
        self._started = False

    # ---- hot-path hooks: integers only, no I/O except the one stat
    def _get(self, folder):
        c = self._dev.get(folder)
        if c is None:
            c = self._dev[folder] = _Counters()
        return c

    def on_arrival(self, folder, frame_path):
        try:
            size = os.stat(frame_path).st_size
        except OSError:
            size = None
        with self._lock:
            c = self._get(folder)
            c.arrived += 1
            if size is not None:
                c.bytes += size

    def on_analyzed(self, folder, frame_path, queue_size=0):
        try:
            age_ms = max(0.0, (time.time() - os.stat(frame_path).st_mtime) * 1000.0)
        except OSError:
            age_ms = None
        with self._lock:
            c = self._get(folder)
            c.analyzed += 1
            if queue_size > c.queue_max:
                c.queue_max = queue_size
            if age_ms is not None:
                c.last_age_ms = age_ms
                c.age_max = max(c.age_max, age_ms)
                for i, bound in enumerate(AGE_BOUNDS_MS):
                    if age_ms <= bound:
                        c.ages[i] += 1
                        break
                else:
                    c.ages[-1] += 1

    def on_dropped(self, folder, n=1):
        if n > 0:
            with self._lock:
                self._get(folder).dropped += n

    # ---- window flush
    def flush(self, now=None):
        """Close the window: write the status files, queue the DB rows. Returns the records (for tests)."""
        now = now or time.time()
        with self._lock:
            elapsed = max(1e-6, now - self._window_start)
            start = self._window_start
            snap, self._dev = self._dev, {}
            self._window_start = now
        proc = self._proc.sample()
        bucket = _iso(int(start))
        records = []
        for folder, c in snap.items():
            device_id = self._device_id_fn(folder) if self._device_id_fn else folder
            rec = {
                'host_name': self.host_name, 'device_id': device_id, 'capture_folder': folder,
                'bucket_start': bucket, 'bucket_seconds': int(round(elapsed)),
                'frames_arrived': c.arrived, 'frames_analyzed': c.analyzed, 'frames_dropped': c.dropped,
                'image_bytes': c.bytes,
                'arrived_fps': round(c.arrived / elapsed, 2),
                'estimated_image_throughput_bps': int(c.bytes * 8 / elapsed),
                'frame_age_p95_ms': age_percentile_ms(c.ages, 95),
                'frame_age_max_ms': round(c.age_max) if c.analyzed and c.age_max else None,
                'queue_depth_max': c.queue_max,
                'samples_dropped': self._rows_dropped,
                'schema_version': SCHEMA_VERSION,
            }
            records.append(rec)
            self._write_status(folder, rec, proc)
            self._enqueue(rec)
        host = {
            'host_name': self.host_name, 'device_id': HOST_ROW, 'capture_folder': HOST_ROW,
            'bucket_start': bucket, 'bucket_seconds': int(round(elapsed)),
            'samples_dropped': self._rows_dropped, 'schema_version': SCHEMA_VERSION, **proc,
        }
        records.append(host)
        self._enqueue(host)
        return records

    def _write_status(self, folder, rec, proc):
        if not self._status_dir_fn:
            return
        try:
            meta = self._status_dir_fn(folder)
            os.makedirs(meta, mode=0o777, exist_ok=True)
            path = os.path.join(meta, STATUS_FILE)
            tmp = f'{path}.tmp'
            with open(tmp, 'w') as f:
                json.dump({**rec, 'process': proc, 'written_at': time.time()}, f)
            os.replace(tmp, path)
        except Exception as e:  # noqa: BLE001 - telemetry must never raise into the monitor
            logger.warning(f'[img_telemetry] status write failed for {folder}: {e}')

    def _enqueue(self, row):
        while True:
            try:
                self._rows.put_nowait(row)
                return
            except queue.Full:
                try:
                    self._rows.get_nowait()
                    self._rows_dropped += 1
                except queue.Empty:
                    pass

    # ---- threads
    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._flush_loop, daemon=True, name='img-telemetry-flush').start()
        threading.Thread(target=self._writer_loop, daemon=True, name='img-telemetry-db').start()
        logger.info(f'[img_telemetry] on: window={self.window_s}s')

    def _flush_loop(self):
        while True:
            time.sleep(self.window_s)
            try:
                self.flush()
            except Exception as e:  # noqa: BLE001
                logger.error(f'[img_telemetry] flush failed: {e}')

    def _write_batch(self, batch):
        (self._sink or _supabase_sink)(batch)

    def _writer_loop(self):
        backoff = 0.0
        last_prune = 0.0
        while True:
            batch = [self._rows.get()]
            while len(batch) < DB_BATCH_MAX:
                try:
                    batch.append(self._rows.get_nowait())
                except queue.Empty:
                    break
            try:
                self._write_batch(batch)
                backoff = 0.0
            except Exception as e:  # noqa: BLE001
                backoff = min(DB_BACKOFF_MAX_S, max(5.0, backoff * 2))
                for row in batch:           # keep the batch for the retry, bounded by the queue
                    self._enqueue(row)
                logger.warning(f'[img_telemetry] DB write failed ({len(batch)} rows kept, retry in {backoff:.0f}s): {e}')
                time.sleep(backoff)
                continue
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                try:
                    _prune()
                except Exception as e:  # noqa: BLE001
                    logger.warning(f'[img_telemetry] prune failed: {e}')


def _supabase_sink(rows):
    from shared.src.lib.database.image_telemetry_db import upsert_rows
    upsert_rows(rows)


def _prune():
    from shared.src.lib.database.image_telemetry_db import prune
    prune(int(os.getenv('IMG_TELEMETRY_RETENTION_DAYS', '7')))


class ProcessSampler:
    """CPU % (of one core) and RSS of this monitor and of all ffmpeg processes, plus load per core. None on failure."""

    def __init__(self):
        self._self = None
        self._ffmpeg = {}

    def sample(self):
        out = {'cpu_pct_monitor': None, 'rss_monitor_bytes': None, 'cpu_pct_ffmpeg': None, 'rss_ffmpeg_bytes': None,
               'load_per_core': None}
        try:
            import psutil
            if self._self is None:
                self._self = psutil.Process()
                self._self.cpu_percent(None)      # primes the interval; the first window reports None
            else:
                out['cpu_pct_monitor'] = round(self._self.cpu_percent(None), 1)
            out['rss_monitor_bytes'] = self._self.memory_info().rss
            cpu, rss, seen = 0.0, 0, False
            alive = {}
            for p in psutil.process_iter(['name', 'pid']):
                name = (p.info.get('name') or '').lower()
                if not name.startswith('ffmpeg'):
                    continue
                try:
                    if p.pid in self._ffmpeg:
                        proc = self._ffmpeg[p.pid]
                        cpu += proc.cpu_percent(None)
                        seen = True
                    else:
                        proc = p
                        proc.cpu_percent(None)
                    rss += proc.memory_info().rss
                    alive[p.pid] = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self._ffmpeg = alive
            if alive:
                out['rss_ffmpeg_bytes'] = rss
                out['cpu_pct_ffmpeg'] = round(cpu, 1) if seen else None
            if hasattr(os, 'getloadavg'):
                out['load_per_core'] = round(os.getloadavg()[0] / (os.cpu_count() or 1), 2)
        except Exception as e:  # noqa: BLE001
            logger.debug(f'[img_telemetry] process sample failed: {e}')
        return out
