"""
Telemetry logger for Tello flights.

The plain Tello has no GPS — the position is dead-reckoned (start pose +
integrated motion commands + yaw from the on-board IMU). The state
datagram (``shared/src.lib.drone.tello.TelloClient._state_loop``)
delivers this at ~10 Hz on UDP 8890; the dead-reckoned pose lives in
``SafetyGuard.pose``. We sample both at a fixed interval and write one
row per sample to a per-flight CSV.

A new file is opened on every takeoff and closed on every land. The
file path is exposed on the controller's ``last_log_path`` so the VPT
device-control panel (and Atlas, via the TelloTools skill) can show it
back to the user after the flight.

The position column is the dead-reckoned pose with margins, not a
survey-grade fix. If you need real position, the Tello Talent can
correct its pose with Mission Pads (ArUco markers on the floor, recognised
by the on-board downward camera); the controller does not apply that
correction today — it is a follow-up if accuracy matters.

Path:
  /var/log/vpt/tello-flights/<host>-<device>-<UTC>.csv
  (falls back to /tmp/vpt-tello-flights/ if /var/log/vpt/ is not writable)
"""

from __future__ import annotations

import csv
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional


logger = logging.getLogger(__name__)


PRIMARY_LOG_DIR = Path("/var/log/vpt/tello-flights")
FALLBACK_LOG_DIR = Path("/tmp/vpt-tello-flights")


def _log_dir() -> Path:
    """Pick a writable log directory, falling back if /var/log/vpt isn't writable."""
    for candidate in (PRIMARY_LOG_DIR, FALLBACK_LOG_DIR):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # Touch a probe file to confirm writability for vpt_user.
            probe = candidate / ".writeprobe"
            probe.write_text("")
            probe.unlink()
            return candidate
        except OSError:
            continue
    # Last resort — the FALLBACK always exists, so we should never get here.
    return FALLBACK_LOG_DIR


def _safe(value: Any) -> str:
    """CSV-friendly conversion: None -> ''; floats with no fractional part are fine."""
    if value is None:
        return ""
    return str(value)


class TelemetryLogger:
    """Per-flight Tello state + dead-reckoned pose logger.

    Started by the controller on a successful ``takeoff`` and stopped on
    ``land`` (or any error path that lands the drone). One CSV file per
    flight. The thread is a daemon so a controller that crashes mid-flight
    doesn't leave a half-open file with a live thread.

    Constructor injection: the ``sample_fn`` passed to ``start()`` must
    return a dict (or None to skip that tick). It runs on the logger's
    background thread, so it should be cheap and not block on I/O.
    """

    COLUMNS = (
        "t_iso", "t_ms", "phase",
        "bat", "temph", "h", "tof", "baro", "time",
        "pose_x", "pose_y", "pose_z", "yaw", "pose_source", "pad_id",
        "vgx", "vgy", "vgz",
        "agx", "agy", "agz",
        "guard_blocks", "commands_sent",
    )

    def __init__(self, host: str, device_id: str, interval_s: float = 0.2) -> None:
        self.host = host
        self.device_id = device_id
        self.interval_s = max(0.05, float(interval_s))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file = None
        self._writer = None
        self._t0: Optional[float] = None
        self._path: Optional[Path] = None
        self._sample_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sample_fn: Callable[[], Optional[Dict[str, Any]]]) -> Path:
        """Open the per-flight file, write the header, start the sampler thread."""
        if self.is_running:
            raise RuntimeError("telemetry logger already running for this controller")
        d = _log_dir()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Sanitize host / device for filename safety.
        safe_host = "".join(c if c.isalnum() or c in "-._" else "_" for c in self.host)
        safe_dev = "".join(c if c.isalnum() or c in "-._" else "_" for c in self.device_id)
        self._path = d / f"{safe_host}-{safe_dev}-{ts}.csv"
        self._file = open(self._path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.COLUMNS)
        self._file.flush()
        self._sample_fn = sample_fn
        self._t0 = time.time()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"tello-telemetry-{safe_host}-{safe_dev}",
        )
        self._thread.start()
        logger.info(
            "tello telemetry log started: %s (interval=%.3fs, host=%s device=%s)",
            self._path, self.interval_s, self.host, self.device_id,
        )
        return self._path

    def stop(self) -> Optional[Path]:
        """Stop the sampler, close the file. Returns the path (or None if never started)."""
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass
            self._file = None
            self._writer = None
        if self._path is not None:
            logger.info("tello telemetry log closed: %s", self._path)
        return self._path

    def _run(self) -> None:
        # The first sample happens immediately so the file has data even on a
        # 200 ms tick that lands just after takeoff.
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # never let the sampler thread die loudly
                self._last_error = repr(e)
                logger.warning("tello telemetry tick failed: %s", e)
            # sleep, but wake on stop
            if self._stop.wait(self.interval_s):
                break
        # One last sample so the file has the final pose at land time.
        try:
            self._tick()
        except Exception:
            pass

    def _tick(self) -> None:
        if self._sample_fn is None or self._writer is None or self._file is None:
            return
        sample = self._sample_fn() or {}
        with self._lock:
            t_ms = int((time.time() - (self._t0 or time.time())) * 1000)
            self._writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                t_ms,
                _safe(sample.get("phase")),
                _safe(sample.get("bat")),
                _safe(sample.get("temph")),
                _safe(sample.get("h")),
                _safe(sample.get("tof")),
                _safe(sample.get("baro")),
                _safe(sample.get("time")),
                _safe(sample.get("pose_x")),
                _safe(sample.get("pose_y")),
                _safe(sample.get("pose_z")),
                _safe(sample.get("yaw")),
                _safe(sample.get("pose_source")),
                _safe(sample.get("pad_id")),
                _safe(sample.get("vgx")),
                _safe(sample.get("vgy")),
                _safe(sample.get("vgz")),
                _safe(sample.get("agx")),
                _safe(sample.get("agy")),
                _safe(sample.get("agz")),
                _safe(sample.get("guard_blocks")),
                _safe(sample.get("commands_sent")),
            ])
            self._file.flush()
