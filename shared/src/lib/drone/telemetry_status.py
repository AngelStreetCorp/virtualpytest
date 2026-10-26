"""Telemetry bridge: the vehicle controller (vpt-host) tells the monitor what the vehicle reports (TASK-90 goal 12).

The monitors are separate processes and cannot read a controller. The controller writes
`<device metadata folder>/telemetry_status.json` atomically, at most 5 times a second; the `drone` monitor profile
(`backend_host/scripts/monitor/analyzers/telemetry.py`) reads it, and a file older than `TELEMETRY_MAX_AGE_S` means
"no telemetry" (the same staleness pattern as `audio_status.json`). A rover can write the same file: the keys below are
not Tello specific, and `lat` / `lon` / `gps_fix` are null for a vehicle without GPS (the Tello has none).

Opt-in burn-in (profile `burn_in: true` or `DEVICE<N>_TELEMETRY_BURN_IN=1`): the writer also keeps
`telemetry_hud.txt` (one line) in the same folder, the text `run_ffmpeg.sh` draws top right with `drawtext=textfile=...:reload=1`.

stdlib only: the monitor and the controller both import it.
"""
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

STATUS_FILE = 'telemetry_status.json'
HUD_FILE = 'telemetry_hud.txt'
MIN_INTERVAL_S = 0.2            # at most 5 writes a second
TELEMETRY_MAX_AGE_S = 3.0       # older than this = no telemetry
VG_UNIT_M_S = 0.1               # Tello state vgx/vgy/vgz are decimetres per second (SDK 2.0 state; check on hardware)
NO_TELEMETRY_TEXT = 'NO TELEMETRY'


def _num(value, default=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return int(v) if v.is_integer() else v      # 62, not 62.0: the record is read 5 times a second


def build_status(state: Dict[str, Any], pose: Optional[Dict[str, float]] = None, flying: bool = False,
                 source: str = 'tello', gps: Optional[Dict[str, Any]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """The status record from a Tello state datagram (bat, templ/temph, h, vgx/vgy/vgz, yaw, time), the controller's
    dead-reckoned pose (cm) and the optional GPS fix. Units in the record: percent, degrees C, metres, m/s, seconds."""
    vx, vy, vz = (_num(state.get(k), 0.0) for k in ('vgx', 'vgy', 'vgz'))
    speed = (vx * vx + vy * vy + vz * vz) ** 0.5 * VG_UNIT_M_S
    h = _num(state.get('h'))
    gps = gps or {}
    return {
        'v': 1,
        'ts': round(now if now is not None else time.time(), 3),
        'source': source,
        'battery': None if state.get('bat') is None else int(_num(state.get('bat'), 0)),
        'temp_low': _num(state.get('templ')),
        'temp_high': _num(state.get('temph')),
        'height_cm': h,
        'speed_ms': round(speed, 2),
        'yaw': _num(state.get('yaw')),
        'flight_time_s': _num(state.get('time')),
        'flying': bool(flying),
        'pose': None if not pose else {'x': round(float(pose['x']), 1), 'y': round(float(pose['y']), 1)},
        'lat': None if gps.get('lat') is None else round(float(gps['lat']), 6),
        'lon': None if gps.get('lon') is None else round(float(gps['lon']), 6),
        'gps_fix': gps.get('fix'),
    }


def hud_text(status: Optional[Dict[str, Any]]) -> str:
    """The text burned into the picture: ONE line (`BAT 87%  62C  ALT 1.2m  0.5m/s  47.37690,8.54170`, the GPS part only with a fix). One
    line on purpose: ffmpeg 8's drawtext draws the line break of a multi-line text file as a missing-glyph box."""
    if not status:
        return NO_TELEMETRY_TEXT
    parts = []
    if status.get('battery') is not None:
        parts.append(f"BAT {int(status['battery'])}%")
    t = status.get('temp_high')
    if t is not None:
        parts.append(f"{t:.0f}C")
    h = status.get('height_cm')
    if h is not None:
        parts.append(f"ALT {h / 100.0:.1f}m")
    if status.get('speed_ms') is not None:
        parts.append(f"{status['speed_ms']:.1f}m/s")
    if status.get('lat') is not None and status.get('lon') is not None:
        parts.append(f"{status['lat']:.5f},{status['lon']:.5f}")
    return '  '.join(parts) or NO_TELEMETRY_TEXT


def write_atomic(path: str, text: str) -> None:
    """Write-then-rename: a reader sees the old or the new file, never half of one."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def read_status(folder: str, max_age_s: float = TELEMETRY_MAX_AGE_S, now: Optional[float] = None):
    """(status dict or None, age in seconds or None). The age is the file's modification time: a writer that stopped
    leaves a file that gets old. A missing or half-written file is (None, None)."""
    path = os.path.join(folder, STATUS_FILE)
    try:
        age = (now if now is not None else time.time()) - os.path.getmtime(path)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    return (data if isinstance(data, dict) else None), age


def is_fresh(age_s: Optional[float], max_age_s: float = TELEMETRY_MAX_AGE_S) -> bool:
    return age_s is not None and age_s <= max_age_s


_TRUE = {'1', 'true', 'yes', 'on'}
_FALSE = {'0', 'false', 'no', 'off'}


def telemetry_burn_in(device_index: Optional[int], env=None, profiles_dir: Optional[str] = None) -> bool:
    """Burn the HUD into the video for this device? `DEVICE<N>_TELEMETRY_BURN_IN` decides when set (1/0), otherwise the
    device's profile manifest (`burn_in: true`). The shell twin is `telemetry_burn_in` in run_ffmpeg.sh."""
    env = os.environ if env is None else env
    raw = (env.get(f'DEVICE{device_index}_TELEMETRY_BURN_IN') if device_index is not None else None) or ''
    raw = raw.strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    from shared.src.lib.utils.monitor_profile import PROFILES_DIR, resolve_monitor_profile
    name = resolve_monitor_profile(device_index, profiles_dir, env)
    try:
        with open(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'), 'r', encoding='utf-8') as f:
            return re.search(r'^burn_in:\s*true\b', f.read(), re.M) is not None
    except OSError:
        return False


class TelemetryStatusWriter:
    """Background thread: calls `sample_fn()` (a status dict, or None when there is nothing fresh to say) and publishes it
    at most every `interval_s` into `folder`. When `sample_fn` returns None the status file is left alone (it ages into
    "no telemetry") and, with burn-in, the HUD text says NO TELEMETRY. `stop()` publishes one last sample (the controller
    makes it `flying: false` after a clean landing, so a vehicle that landed is not a lost one)."""

    def __init__(self, folder: str, sample_fn: Callable[[], Optional[Dict[str, Any]]], burn_in: bool = False,
                 interval_s: float = MIN_INTERVAL_S):
        self.folder = folder
        self.sample_fn = sample_fn
        self.burn_in = burn_in
        self.interval_s = max(MIN_INTERVAL_S, float(interval_s))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_hud = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        os.makedirs(self.folder, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='telemetry-status-writer')
        self._thread.start()

    def stop(self, final: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._thread = None
        try:
            self.tick(final)
        except Exception as e:
            logger.warning('telemetry status: last write failed: %s', e)

    def tick(self, final=None) -> Optional[Dict[str, Any]]:
        status = self.sample_fn()
        if status is not None and final is not None:
            status = final(status)
        if status is not None:
            write_atomic(os.path.join(self.folder, STATUS_FILE), json.dumps(status, separators=(',', ':')))
        if self.burn_in:
            text = hud_text(status)
            if text != self._last_hud:     # drawtext reload=1 re-reads the file every frame: only touch it when it changes
                write_atomic(os.path.join(self.folder, HUD_FILE), text)
                self._last_hud = text
        return status

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:           # a full disk or a vanished folder must not kill the controller
                logger.warning('telemetry status: write failed: %s', e)
            self._stop.wait(self.interval_s)
