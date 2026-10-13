"""FrameGrabber: ffmpeg reads the Tello H.264 UDP stream and keeps the latest BGR frame."""

import subprocess
import threading
import time
from typing import Optional, Tuple

import numpy as np


class FrameGrabber:
    def __init__(self, url: str, width: int = 960, height: int = 720):
        if url.startswith("udp://") and "?" not in url:
            url += "?overrun_nonfatal=1&fifo_size=5000000"
        self.url = url
        self.width = width
        self.height = height
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._at = 0.0
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        cmd = ["ffmpeg", "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
               "-probesize", "65536", "-analyzeduration", "500000", "-i", self.url,
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{self.width}x{self.height}", "pipe:1"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="frame-grabber")
        self._thread.start()

    def _read_loop(self) -> None:
        size = self.width * self.height * 3
        out = self._proc.stdout
        while self._running:
            buf = out.read(size)
            if not buf or len(buf) < size:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(self.height, self.width, 3)
            with self._cond:
                self._frame = frame
                self._at = time.time()
                self._cond.notify_all()
        self._running = False

    def stop(self) -> None:
        self._running = False
        p = self._proc
        if p:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            if p.stdout:
                p.stdout.close()
        self._proc = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def latest(self) -> Tuple[Optional[np.ndarray], float]:
        with self._cond:
            if self._frame is None:
                return None, 0.0
            return self._frame.copy(), self._at

    def wait_frame(self, newer_than: float, timeout_s: float = 3.0) -> Optional[np.ndarray]:
        deadline = time.time() + timeout_s
        with self._cond:
            while self._frame is None or self._at <= newer_than:
                left = deadline - time.time()
                if left <= 0:
                    return None
                self._cond.wait(left)
            return self._frame.copy()
