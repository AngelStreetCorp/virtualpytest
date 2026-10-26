"""Drone driving history: every command sent to a vehicle, kept in memory and on disk.

One JSON object per line in `<log dir>/<host>-<device>-<UTC day>.jsonl` (next to the per-flight telemetry CSV: /var/log/vpt/tello-commands,
falling back to /tmp/vpt-tello-commands), and the newest `RING` entries in memory for the history route. An entry says what was asked,
what was really sent (the guard may clip or refuse), what the drone answered and where it was afterwards:

  {"ts": "2026-10-14T09:00:01.234Z", "seq": 7, "command": "move", "params": {"direction": "forward", "cm": 50}, "sent": "forward 50",
   "success": true, "reply": "ok", "blocked": false, "landed": false, "error": null, "duration_ms": 2310, "airborne": true,
   "bat": 78, "h": 120, "pose": {"x": 100, "y": 250, "z": 80, "yaw": 0}, "flight": 2}

`flight` counts takeoffs since the controller started, so one flight's commands can be picked out. Stick input (`rc`, ~10 Hz while a
stick is held) is logged only when the values change, so holding a stick is one entry, not hundreds. stdlib only.
"""
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

PRIMARY_LOG_DIR = Path("/var/log/vpt/tello-commands")
FALLBACK_LOG_DIR = Path("/tmp/vpt-tello-commands")
RING = 500


def _log_dir() -> Path:
    for candidate in (PRIMARY_LOG_DIR, FALLBACK_LOG_DIR):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".writeprobe"
            probe.write_text("")
            probe.unlink()
            return candidate
        except OSError:
            continue
    return FALLBACK_LOG_DIR


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in name)


class CommandLog:
    def __init__(self, host: str, device_id: str, log_dir: Optional[str] = None, ring: int = RING):
        self.host, self.device_id = host, device_id
        self._dir = Path(log_dir) if log_dir else None
        self._ring: Deque[Dict[str, Any]] = deque(maxlen=ring)
        self._lock = threading.Lock()
        self._seq = 0
        self.flight = 0
        self._last_rc: Optional[str] = None
        self.path: Optional[str] = None

    def _file(self, now: datetime) -> Optional[Path]:
        try:
            d = self._dir or _log_dir()
            d.mkdir(parents=True, exist_ok=True)
            return d / f"{_safe(self.host)}-{_safe(self.device_id)}-{now.strftime('%Y%m%d')}.jsonl"
        except OSError:
            return None

    def record(self, command: str, params: Dict[str, Any], result: Dict[str, Any], started: float,
               airborne: bool, state: Optional[Dict[str, Any]] = None, pose: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
        """Log one command and its outcome. `started` is time.time() when it was received. Returns the entry (None = not logged:
        a read, or an `rc` identical to the last one)."""
        if command.startswith("get_"):
            return None
        sent = result.get("sent")
        with self._lock:
            if command == "rc":
                if sent == self._last_rc:
                    return None
                self._last_rc = sent
            else:
                self._last_rc = None
            if command == "takeoff" and result.get("success"):
                self.flight += 1
            self._seq += 1
            now = datetime.now(timezone.utc)
            state = state or {}
            entry = {
                "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
                "seq": self._seq,
                "command": command,
                "params": params or {},
                "sent": sent,
                "success": bool(result.get("success")),
                "reply": result.get("reply"),
                "blocked": bool(result.get("blocked")),
                "landed": bool(result.get("landed")),
                "error": result.get("error"),
                "duration_ms": int((time.time() - started) * 1000),
                "airborne": bool(airborne),
                "bat": state.get("bat"),
                "h": state.get("h"),
                "pose": pose,
                "flight": self.flight,
            }
            if result.get("clipped_from"):
                entry["clipped_from"] = result["clipped_from"]
            self._ring.append(entry)
            path = self._file(now)
            if path is not None:
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
                    self.path = str(path)
                except OSError as e:
                    logger.warning("drone command log: write failed: %s", e)
        return entry

    def history(self, limit: int = 100, flight: Optional[int] = None, since_seq: int = 0) -> List[Dict[str, Any]]:
        """Newest-last list of the last `limit` entries (of one flight, newer than `since_seq`)."""
        with self._lock:
            rows = [e for e in self._ring if e["seq"] > since_seq and (flight is None or e["flight"] == flight)]
        return rows[-max(1, int(limit)):]
