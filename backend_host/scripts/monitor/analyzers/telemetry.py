"""telemetry: a vehicle's own readings next to its picture (TASK-90 goal 12, the `drone` profile).

No picture work. The vehicle controller (vpt-host) writes `telemetry_status.json` into the device's metadata folder
(`shared/src/lib/drone/telemetry_status.py`); this analyzer reads it at `sample_hz` on the shared sampled-worker thread, attaches the
newest reading compactly to every frame JSON (`telemetry`), keeps per-flight statistics (the stat KPIs of the manifest) and raises
the vehicle's events: `flying`, `battery_low`, `temp_high` and `telemetry_lost`. A file older than `stale_s` is "no telemetry";
if the vehicle was flying when it went quiet that is `telemetry_lost`.

Frame JSON `telemetry` (units: %, degrees C, metres, m/s, seconds; null/absent keys are left out):
  {"ok": true, "bat": 87, "temp": 62, "alt": 1.2, "spd": 0.4, "yaw": 12, "ft": 95, "fly": true, "x": 1.0, "y": 2.0,
   "lat": ..., "lon": ..., "fix": ..., "age": 0.3}        or     {"ok": false, "age": 12.4}   (no telemetry)

Settings (manifest keys next to `type`): battery_low (20), temp_high (80), stale_s (3), forget_after_s (600), only_flying (true).
"""
import time

from monitor.analyzers.sampled import SampledWorkerAnalyzer
from monitor.events import ProfileEvents

DEFAULTS = {
    'battery_low': 20.0,       # percent: at or below while flying
    'temp_high': 80.0,         # degrees C: the Tello's hot reading (temph) at or above while flying
    'stale_s': 3.0,            # telemetry older than this is "no telemetry"
    'forget_after_s': 600.0,   # a flight that went quiet longer ago than this is not reported lost any more (a stale file from yesterday)
    'only_flying': True,       # battery_low and temp_high are about a vehicle in the air; false = also on the ground
}


def compact(status, age):
    """The `telemetry` dict of a frame JSON from a status record (see the module docstring)."""
    out = {'ok': True, 'age': round(age, 1)}
    pairs = (
        ('bat', status.get('battery')),
        ('temp', status.get('temp_high')),
        ('alt', None if status.get('height_cm') is None else round(status['height_cm'] / 100.0, 2)),
        ('spd', status.get('speed_ms')),
        ('yaw', status.get('yaw')),
        ('ft', status.get('flight_time_s')),
        ('fly', bool(status.get('flying'))),
        ('lat', status.get('lat')),
        ('lon', status.get('lon')),
        ('fix', status.get('gps_fix')),
    )
    for key, value in pairs:
        if value is not None:
            out[key] = value
    pose = status.get('pose') or {}
    if pose.get('x') is not None and pose.get('y') is not None:
        out['x'], out['y'] = round(pose['x'] / 100.0, 2), round(pose['y'] / 100.0, 2)
    return out


class _Device:
    def __init__(self, profile, folder, metadata_dir):
        self.folder = folder
        self.metadata_dir = metadata_dir
        self.last_run = 0.0
        self.events = ProfileEvents(profile.events, profile.kpis, profile.incidents)
        self.last_fresh = None          # when a fresh reading was last seen by this process
        self.was_flying = False         # the last fresh reading said flying
        self.flight_start = None
        self.stats = {}                 # field -> {'min', 'max', 'last'} since the last takeoff


class TelemetryAnalyzer(SampledWorkerAnalyzer):
    name = 'telemetry'

    def __init__(self, core, profile, metadata_dir_fn=None):
        spec = profile.img.analyzers[0]
        extra = {k: v for k, v in spec.model_dump().items() if k not in ('type', 'sample_hz')}
        unknown = set(extra) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"telemetry: unknown settings {sorted(unknown)}; known: {sorted(DEFAULTS)}")
        self.p = {**DEFAULTS, **extra}
        super().__init__(core, profile, spec.sample_hz or 2.0)
        self.ui = profile.ui.model_dump(exclude_none=True) if getattr(profile, 'ui', None) else None
        self.metadata_dir_fn = metadata_dir_fn
        if metadata_dir_fn is None and core is not None:
            from shared.src.lib.utils.storage_path_utils import get_metadata_path
            self.metadata_dir_fn = get_metadata_path

    # ---- Analyzer interface ---------------------------------------------------------------------
    def register_device(self, capture_folder):
        with self._lock:
            self._state[capture_folder] = _Device(self.profile, capture_folder, self.metadata_dir_fn(capture_folder))

    def chunk_fields(self, analysis_data):
        out = super().chunk_fields(analysis_data)
        out['telemetry'] = analysis_data.get('telemetry')
        return out

    # ---- worker ---------------------------------------------------------------------------------
    def process(self, folder, frame_path, ts):
        from shared.src.lib.drone.telemetry_status import read_status
        dev = self._state[folder]
        dev.last_run = time.time()
        status, age = read_status(dev.metadata_dir)
        return self.process_status(folder, status, age, time.time())

    def process_status(self, folder, status, age, now):
        """One sample from a status record and its age (None, None = no file). Returns the result attached to the frames."""
        p = self.p
        dev = self._state[folder]
        fresh = status is not None and age is not None and age <= p['stale_s']
        obs = []
        if fresh:
            tel = compact(status, age)
            flying = bool(status.get('flying'))
            if flying and not dev.was_flying:
                dev.flight_start = now
                dev.stats = {}              # a new flight: statistics start again
            dev.was_flying, dev.last_fresh = flying, now
            self._update_stats(dev, tel)
            if flying:
                obs.append({'label': 'flying', 'track_id': 'flight', 'conf': 1.0, 'start': dev.flight_start or now, 'attrs': {}})
            air = flying or not p['only_flying']
            if air and tel.get('bat') is not None and tel['bat'] <= p['battery_low']:
                obs.append({'label': 'battery_low', 'track_id': 'battery', 'conf': 1.0, 'attrs': {'value': tel['bat']}})
            if air and tel.get('temp') is not None and tel['temp'] >= p['temp_high']:
                obs.append({'label': 'temp_high', 'track_id': 'temp', 'conf': 1.0, 'attrs': {'value': tel['temp']}})
        else:
            tel = {'ok': False}
            if age is not None:
                tel['age'] = round(age, 1)
            # it was in the air when it went quiet, and not so long ago that this is yesterday's file (after a monitor restart the
            # file itself says what the last reading was)
            known = dev.last_fresh is not None
            flying_before = dev.was_flying if known else bool(status and status.get('flying'))
            quiet_since = dev.last_fresh if known else (now - age if age is not None else None)
            if flying_before and quiet_since is not None and now - quiet_since <= p['forget_after_s']:
                obs.append({'label': 'telemetry_lost', 'track_id': 'link', 'conf': 1.0, 'attrs': {}})
        events, kpis, incidents = dev.events.update(obs, [], now)
        kpis.update(self._stat_kpis(dev))
        result = {'observations': [], 'events': events, 'kpis': kpis, 'telemetry': tel}
        if incidents:
            result['incidents'] = incidents
        if self.ui:
            result['ui'] = self.ui
        with self._lock:
            self._latest[folder] = result
        return result

    def _update_stats(self, dev, tel):
        for kpi in self.profile.kpis:
            if kpi.stat is None:
                continue
            value = tel.get(kpi.stat.field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            s = dev.stats.setdefault(kpi.stat.field, {'min': value, 'max': value, 'last': value})
            s['min'], s['max'], s['last'] = min(s['min'], value), max(s['max'], value), value

    def _stat_kpis(self, dev):
        out = {}
        for kpi in self.profile.kpis:
            if kpi.stat is not None:
                s = dev.stats.get(kpi.stat.field)
                out[kpi.name] = None if s is None else s[kpi.stat.fn]
        return out
