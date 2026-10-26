"""Plumbing shared by the profile analyzers that work on a sampled stream of frames (pipeline, ad_meter).

The frame worker only notes the newest frame (`analyze`); the work runs on this analyzer's own thread at `sample_hz`, never on
the frame worker, and the newest result is attached to every frame's JSON in between (`frame_record`). A subclass fills in
`register_device` (per-device state in `self._state`) and `process(folder, frame_path, ts)` (stores its result in `self._latest`).

WHICH FRAME THE RESULT BELONGS TO
--------------------------------
Because the result is reused until the next analysis, the JSON of capture N usually carries the boxes of an OLDER
frame. `frame_record` therefore names that older frame (`filename`) and its capture time (`captured_at`), so the
client draws the boxes on the picture they were measured on. Naming the newer capture instead put every circle on
bare belt next to its egg — see the note in `frame_record`.
"""
import logging
import os
import threading
import time

logger = logging.getLogger('capture_monitor')


class SampledWorkerAnalyzer:
    name = 'pipeline'

    def __init__(self, core, profile, sample_hz):
        self.core = core
        self.profile = profile
        self.sample_hz = sample_hz
        self._lock = threading.Lock()
        self._pending = {}    # capture_folder -> (frame_path, frame timestamp) newest frame not yet analysed
        self._state = {}      # capture_folder -> per-device state of the subclass (must hold 'last_run')
        self._latest = {}     # capture_folder -> result attached to frames
        self._latest_ts = {}  # capture_folder -> capture timestamp of the frame that produced `self._latest`
        self._latest_file = {}  # capture_folder -> file NAME of that same frame
        self._wake = threading.Event()
        self._failures = {}   # capture_folder -> [consecutive failures, time of the last log line]

    # ---- Analyzer interface --------------------------------------------------------------------
    def start(self):
        threading.Thread(target=self._worker, daemon=True, name=f'{self.name}-worker').start()
        logger.info(f"Started {self.profile.name} {self.name} worker ({self.sample_hz:g} Hz)")

    def declared_events(self):
        return list(self.profile.events)

    def analyze(self, ctx):
        """Frame worker side: only note the newest frame; the work happens on the worker. What goes to the incident manager is
        the profile's incident state as of the last sample plus the current frame (the alert's picture)."""
        with self._lock:
            self._pending[ctx.capture_folder] = (ctx.frame_path, ctx.timestamp)
            latest = self._latest.get(ctx.capture_folder) or {}
        self._wake.set()
        if latest.get('incidents'):
            return {'incidents': latest['incidents'], 'last_3_filenames': [ctx.frame_path]}
        return {}

    def frame_record(self, ctx, result, existing):
        from datetime import datetime, timezone
        record = {
            'analyzed': True,
            'subtitle_ocr_pending': False,   # no subtitle work for these profiles
            **existing,
            # THE FRAME THE BOXES WERE MEASURED ON, not the frame this JSON is attached to.
            #
            # The worker analyses the newest pending frame and its result is then attached to EVERY
            # frame's JSON until the next analysis (see the class docstring). The JSON of capture N
            # therefore usually carries the boxes of an OLDER frame, and the client draws the boxes
            # on the picture it fetches from `filename` (BUG-0836's frame-lock: "show the capture the
            # newest analysis was computed FROM"). When `filename` was the newer capture, the client
            # drew a picture up to one sample period + one analysis time newer than the boxes, and on
            # a belt every circle ended up on bare belt next to the egg it belonged to. Measured on
            # the device3 egg line: 19 px median offset, and 33 of 223 circles on empty belt.
            #
            # So `filename` names the ANALYSED frame, exactly like `captured_at` below is its capture
            # time. The two agree, and the client's picture and its boxes are the same frame again.
            'filename': self._latest_file.get(ctx.capture_folder) or ctx.filename,
            'timestamp': datetime.now().isoformat(),
            # When THIS frame was captured, as opposed to `timestamp`, which is when the analysis of it
            # finished (BUG-0836). The gap between the two is the whole overlay lag: the worker takes the
            # newest pending frame, so the one it analysed is up to one `sample_hz` period old, and the
            # analysis itself takes tens of milliseconds. The client needs the real age to move the boxes
            # forward onto the objects that have since moved (see `v` on each observation) and to say how
            # far behind the picture is.
            #
            # UTC with an offset, NOT the naive local time `timestamp` above carries: the client subtracts
            # this from its own clock to get the age, and a naive ISO string parses as *the browser's* local
            # time, so a browser in another timezone would compute an age off by hours and shift every box
            # by that much. Same _iso() convention as monitor/img_telemetry.py.
            'captured_at': datetime.fromtimestamp(
                self._latest_ts.get(ctx.capture_folder, ctx.timestamp), tz=timezone.utc).isoformat(),
        }
        with self._lock:
            latest = self._latest.get(ctx.capture_folder)
        if latest:
            record.update(latest)
        return record

    def chunk_fields(self, analysis_data):
        # what the archive playback overlay needs (the frontend reads these keys from the chunk entry)
        return {'profile': analysis_data.get('profile'), 'frame_size': analysis_data.get('frame_size'),
                'observations': analysis_data.get('observations') or [], 'events': analysis_data.get('events') or {},
                'kpis': analysis_data.get('kpis') or {}, 'focus': analysis_data.get('focus'),
                # so the archived overlay advances its boxes over a replayed clip exactly as the live one does
                'captured_at': analysis_data.get('captured_at')}

    def chunk_header(self, analysis_data):
        """Fields written once per 10-minute chunk, not once per frame: the manifest's `ui` block is the same in every frame (at 5 fps for 24 h
        that was a copy in every chunk entry); the overlay of an archived frame reads it from the chunk."""
        return {'ui': analysis_data['ui']} if analysis_data.get('ui') else {}

    # ---- worker --------------------------------------------------------------------------------
    def _worker(self):
        period = 1.0 / self.sample_hz
        while True:
            self._wake.wait(timeout=self._next_due_in(period))
            self._wake.clear()
            self.run_pending()

    def _next_due_in(self, period):
        """Seconds until the earliest pending frame is due. Waiting a whole period instead made a frame that arrived just
        before its slot wait one more period: at 5 Hz on a 5 fps capture the egg line analysed 3.2 frames a second on an
        idle box (BUG-0917)."""
        now = time.time()
        with self._lock:
            waits = [self._last_run(f) + period - now for f in self._pending]
        return max(0.005, min(waits)) if waits else period

    STALE_AFTER_FAILURES = 5       # in a row: the last good result is no longer true, frames stop carrying it (and its incidents)
    FAILURE_LOG_EVERY_S = 60.0

    def _last_run(self, folder):
        state = self._state.get(folder)
        return state.get('last_run', 0.0) if isinstance(state, dict) else getattr(state, 'last_run', 0.0)

    def run_pending(self):
        """Analyse the newest pending frame of every device whose last run is at least one period ago. A worker that keeps failing is not left
        showing its last good result for ever (a stale incident would never clear): after STALE_AFTER_FAILURES in a row the result is dropped,
        and the error is logged once, then at most once a minute with the count."""
        period = 1.0 / self.sample_hz
        now = time.time()
        with self._lock:
            due = [(f, item) for f, item in self._pending.items() if now - self._last_run(f) >= period]
            for f, _ in due:
                del self._pending[f]
        for folder, (frame_path, ts) in due:
            try:
                self.process(folder, frame_path, ts)
                with self._lock:
                    self._latest_ts[folder] = ts     # the analysed frame's own capture time, for `captured_at`
                    self._latest_file[folder] = os.path.basename(frame_path)   # and its name, for `filename`
                self._failures.pop(folder, None)
            except Exception as e:
                fail = self._failures.setdefault(folder, [0, 0.0])
                fail[0] += 1
                if fail[0] == 1 or now - fail[1] >= self.FAILURE_LOG_EVERY_S:
                    logger.error(f"[{folder}] {self.profile.name} {self.name} error ({fail[0]} in a row): {e}")
                    fail[1] = now
                if fail[0] == self.STALE_AFTER_FAILURES:
                    logger.error(f"[{folder}] {self.profile.name} {self.name}: {fail[0]} failures in a row, dropping the last result (it is no longer true)")
                    with self._lock:
                        self._latest.pop(folder, None)
                        self._latest_ts.pop(folder, None)
                        self._latest_file.pop(folder, None)

    def process(self, folder, frame_path, ts):
        raise NotImplementedError
