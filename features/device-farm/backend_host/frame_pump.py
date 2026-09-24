"""Screenshot pump: the farm device's picture, written where ffmpeg already looks.

A paired phone (features/mobile-app) writes JPEG frames to the slot's
`DEVICE{i}_VIDEO` image file and the host's existing ffmpeg `imagefile` grabber
turns that into HLS plus the `captures/capture_*.jpg` series. A cloud device gets
the same treatment, with WebDriver screenshots as the frame source — which is why
the AV controller stays the core `hdmi_stream` one and image/text/colour
verification, the REC preview and report thumbnails all work untouched.

Two properties matter more than throughput:

* **It never opens a session** (`driver_if_open()`): frames flow while the device
  is actually being used and stop when it is not. Every screenshot is a metered
  round-trip to the farm, so an always-pumping slot is a standing bill.
* **Writes are atomic** (`.tmp` + `os.replace`): ffmpeg reads that file
  continuously, and a half-written JPEG is a corrupt frame in the stream.
"""
import os
import threading
import time
from typing import Optional

from ..lib.types import FarmConfig

_LOG = '[@device-farm:pump]'

#: Sleep between polls while no session is open — long enough to cost nothing.
IDLE_POLL_SECONDS = 2.0
#: After this many consecutive failures, complain once and back off.
FAILURE_REPORT_EVERY = 10


# A 108x234 black JPEG, inlined so seeding needs no Pillow, no ffmpeg and no file on
# disk. It exists only to give the grabber a valid image to open; the first real
# screenshot replaces it within a second of the first command.
#
# It must be PORTRAIT, and roughly a phone's aspect. The host's grabber decides
# portrait vs landscape purely from the source image's width/height
# (`run_ffmpeg.sh`: orientation=portrait iff height > width) and then locks the whole
# ffmpeg pipeline to that. A square seed reads as landscape, and every capture for that
# device comes out rotated — which is how this was found: a 16x16 seed produced
# "Detected orientation: landscape (source: 16x16)" and 2340x1080 captures of a phone
# that was, and reported itself as, portrait.
_PLACEHOLDER_JPEG = __import__('base64').b64decode(
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dA'
    'RkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8'
    'fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCADqAGwDASIA'
    'AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA'
    'AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3'
    'ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm'
    'p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA'
    'AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx'
    'BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK'
    'U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3'
    'uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDjKKKK'
    'ACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA'
    'KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo'
    'oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii'
    'igAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKK'
    'ACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA'
    'KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAo'
    'oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii'
    'igAooooAKKKKACiiigAooooA/9k='
)

class FramePump:
    """One daemon thread per farm-backed slot."""

    def __init__(self, cfg: FarmConfig, session, frame_path: str):
        self.cfg = cfg
        self.session = session
        self.frame_path = frame_path
        self.frames_written = 0
        self.last_error: Optional[str] = None

        self._interval = 1.0 / cfg.screenshot_fps if cfg.screenshot_fps > 0 else 1.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._failures = 0

    # ---- lifecycle ----------------------------------------------------------
    def start(self) -> bool:
        if not self.frame_path:
            print(f"{_LOG} {self.cfg.device_id}: no DEVICE*_VIDEO image path - "
                  f"no stream for this slot (remote control still works)")
            return False
        if self._thread is not None:
            return True
        try:
            os.makedirs(os.path.dirname(self.frame_path) or '.', exist_ok=True)
        except OSError as e:
            print(f"{_LOG} {self.cfg.device_id}: cannot create frame folder: {e}")
            return False

        self._seed_placeholder()

        self._thread = threading.Thread(
            target=self._run, name=f'farm-pump-{self.cfg.device_id}', daemon=True)
        self._thread.start()
        print(f"{_LOG} {self.cfg.device_id}: pumping to {self.frame_path} "
              f"at {self.cfg.screenshot_fps} fps while a session is open")
        return True

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)

    # ---- loop ---------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            driver = self.session.driver_if_open()
            if driver is None:
                self._stop.wait(IDLE_POLL_SECONDS)
                continue
            started = time.time()
            self._capture_once(driver)
            # Pace from the start of the capture: a slow farm round-trip should not
            # add to the interval, it should eat into it.
            self._stop.wait(max(0.0, self._interval - (time.time() - started)))

    def _capture_once(self, driver) -> None:
        try:
            png = driver.get_screenshot_as_png()
        except Exception as e:
            self._note_failure(f'screenshot failed: {type(e).__name__}: {e}')
            return
        if not png:
            self._note_failure('screenshot returned no data')
            return
        try:
            self._write_frame(png)
        except Exception as e:
            self._note_failure(f'frame write failed: {e}')
            return
        self._failures = 0
        self.last_error = None
        self.frames_written += 1

    def _seed_placeholder(self) -> None:
        """Write one frame so the grabber has something to open, without a session.

        The host's ffmpeg grabber refuses to start until its source image exists, and
        it waits ~2 minutes before giving up. A farm slot has no image until the first
        session, so a brand-new slot could not stream at all — and because the grabbers
        are started in sequence, the one waiting held up every *other* device on the
        host too. Seeding costs nothing and opens no session (trap: the pump must never
        lease a device).

        Only ever written when nothing is there: a real frame from an earlier session is
        better than this, and must not be overwritten on restart.
        """
        if os.path.exists(self.frame_path):
            return
        try:
            self._write_frame(_PLACEHOLDER_JPEG)
            print(f"{_LOG} {self.cfg.device_id}: seeded a placeholder frame so the "
                  f"grabber can start before the first session")
        except OSError as e:
            print(f"{_LOG} {self.cfg.device_id}: could not seed a placeholder: {e}")

    def _write_frame(self, image_bytes: bytes) -> None:
        """Atomic replace, so ffmpeg never reads a torn file."""
        tmp_path = f'{self.frame_path}.tmp'
        with open(tmp_path, 'wb') as fh:
            fh.write(image_bytes)
        os.replace(tmp_path, self.frame_path)

    def _note_failure(self, message: str) -> None:
        self.last_error = message
        self._failures += 1
        if self._failures == 1 or self._failures % FAILURE_REPORT_EVERY == 0:
            print(f"{_LOG} {self.cfg.device_id}: {message} "
                  f"({self._failures} consecutive)")
        # Back off while broken: a farm that is refusing screenshots is not going to
        # start on the next 200ms tick, and the retries are themselves billable.
        self._stop.wait(min(IDLE_POLL_SECONDS * self._failures, 30.0))
