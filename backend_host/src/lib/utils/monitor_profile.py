"""vpt-host side of monitor profiles (TASK-90): which profile each device runs, and keeping the three
monitor services in step with it.

Enabled state is never changed (vpt_user may only `systemctl start|stop|restart vpt-*`): when the profiles on
this host change, apply_monitor_profiles() restarts the monitor units whose devices changed and stops the ones no device needs (TASK-144), and each unit
then idles or works according to the profiles it reads (shared/src/lib/utils/monitor_service.py).
"""
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.monitor_profile import (
    PROFILES_DIR, SERVICES, device_index_from_id, folders_needing_service_for_devices, lean_devices,
    profile_exists, profile_services, profile_stream_mode, read_env_files, resolve_monitor_profile, validate_manifest_light)

logger = logging.getLogger(__name__)

SERVICE_UNITS = {'img': 'vpt-monitor-img', 'audio': 'vpt-monitor-audio', 'subtitle': 'vpt-monitor-subtitle',
                 'archiver': 'vpt-archiver', 'kpi': 'vpt-kpi', 'avq': 'vpt-avq'}
MONITOR_SERVICES = ('img', 'audio', 'subtitle')
STREAM_UNIT = 'vpt-stream'   # restarted when a device's stream mode (full / lean) changes: the ffmpeg graph is fixed at start
COMPANION_UNIT = 'vpt-companion'   # opt-in per device (DEVICEn_COMPANION=true), not a profile service: stopped when no device asks for it
_RESTARTABLE = re.compile(r'vpt-(monitor-(img|audio|subtitle)|archiver|kpi|avq|stream|companion)')
STATE_FILE = os.path.join('/var/tmp' if os.path.isdir('/var/tmp') else tempfile.gettempdir(), 'vpt_monitor_profiles_applied.json')
_DEVICE_KEY = re.compile(r'^DEVICE(\d+)_')


def _device_id(device: Any) -> Optional[str]:
    if isinstance(device, dict):
        return device.get('device_id')
    return getattr(device, 'device_id', None)


def get_monitor_profiles(devices: Optional[List[Any]]) -> Dict[str, str]:
    """{device_id: profile name} for the host's devices; a host with no device list reports its host-level profile."""
    out: Dict[str, str] = {}
    for device in devices or []:
        did = _device_id(device)
        if did:
            out[did] = resolve_monitor_profile(device_index_from_id(did))
    if not out:
        out['host'] = resolve_monitor_profile(None)
    return out


def get_profile_services(profiles: Dict[str, str]) -> Dict[str, Dict[str, bool]]:
    """{profile: {service: bool}} for the profiles in use on this host, so the Dashboard card knows which
    services each device's profile expects without a second fetch."""
    return {name: profile_services(name) for name in sorted(set(profiles.values()))}


def get_monitor_profile_params(profiles: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """{device_id: {profile, captions: True, delay_s, language, whisper_model}} for the devices whose profile has captions
    (TASK-103); the player reads delay_s from here. Devices without captions are absent."""
    from shared.src.lib.utils.monitor_profile import device_captions
    out: Dict[str, Dict[str, Any]] = {}
    for did, name in profiles.items():
        caps = device_captions(device_index_from_id(did))
        if caps is not None:
            out[did] = {'profile': name, 'captions': True, **caps}
    return out


def get_monitoring_off(profiles: Dict[str, str]) -> List[str]:
    """Device ids ({device_id: profile} given) whose profile runs no monitor for them (tv_lite): the UI shows
    'monitoring off' for these instead of an empty overlay or a 24 h button that opens nothing."""
    return sorted(d for d, name in profiles.items() if not profile_services(name).get('img', True))


def get_overlay_on(profiles: Dict[str, str]) -> List[str]:
    """Device ids ({device_id: profile} given) whose profile draws its own overlay (a `ui` block: eggs, cars). The
    stream modal opens with monitoring on for these, because the overlay IS what the device is for."""
    return sorted(d for d, name in profiles.items() if _has_ui(name))


_UI_CACHE: Dict[str, bool] = {}


def _has_ui(name: str) -> bool:
    if name not in _UI_CACHE:            # a manifest changes only with a deploy, which restarts the host
        raw, _ = _load_manifest(name)
        _UI_CACHE[name] = bool(raw and raw.get('ui'))
    return _UI_CACHE[name]


def localize_off_reason(device_id: str) -> Optional[str]:
    """Why Localize is refused on `device_id`, or None. Owner, 2026-10-14: a device whose profile runs no
    vpt-monitor-img (lite / tv_lite) gets no Localize at all. Same profile data and rule as `monitoring_off` in
    the host's system stats, which the frontend and the MCP gate read."""
    profiles = {device_id: resolve_monitor_profile(device_index_from_id(device_id))}
    if not get_monitoring_off(profiles):
        return None
    return (f"Localize is off for {device_id}: its monitoring profile '{profiles[device_id]}' does not run "
            f"the image monitor (vpt-monitor-img)")


def _desired_state() -> Dict[str, Any]:
    """Profiles per device and the devices each service must serve, from the .env files as they are now.

    The `services` field is the host-level view of which systemd units must be active. It is computed
    via `folders_needing_service_for_devices`, which iterates `profiles` and asks
    `profile_services(...).get(s)` for each — the same decision `folders_needing_service` makes on
    the imager side and `wait_until_needed` makes at unit startup (BUG-0563). The three views agree
    because they all call `profile_services` on the same `name` from the same `.env`.

    The `lean` field lists devices whose profile is `stream: lean` (e.g. `tv_lite`, `pc`,
    `caption_playback`-with-lean); `services_to_restart` and `apply_monitor_profiles` use it to
    decide whether to restart `vpt-stream` (the ffmpeg graph is fixed at start, so a lean↔full
    switch needs a full restart).
    """
    env = {**read_env_files(re.compile(r'.*')) }
    device_ids = sorted({f'device{m.group(1)}' for k in env for m in [_DEVICE_KEY.match(k)] if m}, key=lambda d: int(d[6:]))
    if not device_ids:
        device_ids = ['host']
    profiles = {d: resolve_monitor_profile(device_index_from_id(d), env=env) for d in device_ids}
    services = {s: sorted(folders_needing_service_for_devices(s, profiles)) for s in SERVICES}
    companion = [d for d in device_ids if str(env.get(f'{d.upper()}_COMPANION', '')).strip().lower() in ('1', 'true', 'yes', 'on')]
    return {'profiles': profiles, 'services': services, 'lean': lean_devices(profiles), 'companion': companion}


def _read_state() -> Optional[Dict[str, Any]]:
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def units_not_needed() -> List[str]:
    """The units no device on this host needs, per the last applied profiles.

    TASK-144 stops these when no device asks for them, so a host that has them
    stopped is working as configured, not broken. The host status must not read a
    stopped one of them as a failed critical service (it showed every host whose
    profile needs no image monitoring, archiver or KPI as "error" right after a
    deploy). Unknown state -> an empty list: the status then treats them as needed,
    which is the safe direction.
    """
    state = _read_state() or {}
    services = state.get('services') or {}
    if not isinstance(services, dict):
        return []
    return [SERVICE_UNITS[s] for s in SERVICES if s in services and not services.get(s)]


def _write_state(state: Dict[str, Any]) -> None:
    try:
        tmp = f'{STATE_FILE}.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        logger.warning("cannot record the applied monitor profiles in %s: %s", STATE_FILE, e)


def services_to_restart(previous: Dict[str, Any], desired: Dict[str, Any]) -> List[str]:
    """Services whose device set changed, or whose devices run a different profile than before.

    A service the record does not know yet (written before TASK-95) ran for every device; that is
    the conservative default and is preserved.

    BUG-0563 cross-reference: the per-device decision is also enforced *inside* the imager
    (`capture_monitor.py:_init_capture_dirs`) via `folders_needing_service('img', [...])`, and at
    unit startup via `wait_until_needed`. The three call sites all consult
    `profile_services(...).get(s)`, so a profile change can never make the orchestrator restart a
    unit that the imager would have skipped, or vice versa.
    """
    changed = []
    for s in SERVICES:
        before, after = previous.get('services', {}).get(s), desired['services'][s]
        if before is None:
            before = sorted(previous.get('profiles', {}))
        if before != after:
            changed.append(s)
            continue
        # the host services (archiver, kpi, avq) do not care which profile a device runs, only whether they serve it
        if s in MONITOR_SERVICES and any(previous.get('profiles', {}).get(d) != desired['profiles'].get(d) for d in after):
            changed.append(s)
    return changed


def units_to_stop_start(previous: Optional[Dict[str, Any]], desired: Dict[str, Any]) -> Dict[str, List[str]]:
    """Pure decision (TASK-144): {'stop': units no device needs, 'start': units a device needs now that the last
    applied record said nobody did}. The caller stops only the ones that are active and starts only the ones that
    are not, so a unit an operator stopped on purpose is never started by a profile that never wanted it off."""
    stop, start = [], []
    before_all = (previous or {})
    rows = [(SERVICE_UNITS[s], desired['services'].get(s), before_all.get('services', {}).get(s)) for s in SERVICES]
    rows.append((COMPANION_UNIT, desired.get('companion'), before_all.get('companion')))
    for unit, now, before in rows:
        if not now:
            stop.append(unit)
        elif before is not None and not before:   # known to have been unneeded before; unknown (old record) = leave alone
            start.append(unit)
    return {'stop': stop, 'start': start}


def _stop(unit: str) -> bool:
    if not _RESTARTABLE.fullmatch(unit):
        return False
    try:
        r = subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("could not stop %s: %s", unit, e)
        return False
    if r.returncode != 0:
        logger.warning("stop of %s failed: %s", unit, (r.stderr or r.stdout).strip())
    return r.returncode == 0


def _start(unit: str) -> bool:
    if not _RESTARTABLE.fullmatch(unit):
        return False
    try:
        r = subprocess.run(['sudo', '-n', 'systemctl', 'start', unit], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("could not start %s: %s", unit, e)
        return False
    return r.returncode == 0


def _restart(unit: str) -> bool:
    if not _RESTARTABLE.fullmatch(unit):
        return False
    try:
        r = subprocess.run(['sudo', '-n', 'systemctl', 'restart', unit], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("could not restart %s: %s", unit, e)
        return False
    if r.returncode != 0:
        logger.warning("restart of %s failed: %s", unit, (r.stderr or r.stdout).strip())
    return r.returncode == 0


def _is_active(unit: str) -> bool:
    """`systemctl is-active` (no sudo needed). A stopped or disabled unit must stay that way: `restart` would start it
    (on a lite host that means Whisper and Tesseract on 1 GB), and sudoers only allows start|stop|restart anyway."""
    try:
        r = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() in ('active', 'activating')


def _result_file() -> str:
    return os.path.join(os.path.dirname(STATE_FILE), 'vpt_monitor_profiles_result.json')


def _write_result(result: Dict[str, Any]) -> None:
    try:
        path = _result_file()
        tmp = f'{path}.tmp'
        with open(tmp, 'w') as f:
            json.dump(result, f)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("cannot record the monitor profile apply result in %s: %s", _result_file(), e)


def read_apply_result() -> Optional[Dict[str, Any]]:
    """The outcome of the last apply_monitor_profiles() run (state 'applying' while it runs), or None."""
    try:
        with open(_result_file(), 'r') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def requested_profiles(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """{device_id: the name the .env asks for, '' = none}: what resolve_monitor_profile() starts from, before it falls back."""
    env = env if env is not None else read_env_files(re.compile(r'.*'))
    ids = sorted({f'device{m.group(1)}' for k in env for m in [_DEVICE_KEY.match(k)] if m}, key=lambda d: int(d[6:])) or ['host']
    out = {}
    for d in ids:
        index = device_index_from_id(d)
        raw = (env.get(f'DEVICE{index}_MONITOR_PROFILE') if index is not None else '') or ''
        out[d] = raw.strip() or (env.get('MONITOR_PROFILE') or '').strip()
    return out


def profile_problem(name: str, profiles_dir: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Why `name` cannot run as asked, or None. kind: unknown (no manifest, device falls back to tv_app), invalid (manifest
    refused, tv_app), model_missing (the manifest runs but its model file is not there: the img service leaves the device out)."""
    if not profile_exists(name, profiles_dir):
        return {'kind': 'unknown', 'reason': f'no profile named {name!r} on this host'}
    manifest, error = _load_manifest(name, profiles_dir)
    if error:
        return {'kind': 'invalid', 'reason': error}
    missing = [m for m in _models_needed(manifest) if not m['present']]
    if missing:
        return {'kind': 'model_missing', 'reason': 'model file missing: ' + ', '.join(
            f"{m['env']} ({m['path'] or 'not set'})" for m in missing)}
    return None


def _load_manifest(name: str, profiles_dir: Optional[str] = None):
    try:
        import yaml
        with open(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'), 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        validate_manifest_light(raw, name)
        return raw, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


_DEFAULT_MODEL_ENV = {'coco_detect': 'MONITOR_COCO_MODEL', 'egg_classify': 'MONITOR_EGG_MODEL'}


def _models_needed(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{env, path, present}] for every analyzer that loads a model file (the env var names the path)."""
    out, seen = [], set()
    envs = None
    for a in ((manifest.get('img') or {}).get('analyzers') or []):
        if not isinstance(a, dict):
            continue
        env_name = a.get('model_env') or _DEFAULT_MODEL_ENV.get(a.get('type'))
        if not env_name or env_name in seen:
            continue
        seen.add(env_name)
        if envs is None:
            envs = read_env_files(re.compile(r'^MONITOR_.*_MODEL$'))
        path = (os.environ.get(env_name) or envs.get(env_name) or '').strip()
        out.append({'env': env_name, 'path': path, 'present': bool(path) and os.path.isfile(path)})
    return out


# What a profile adds on top of tv_app, in words (docs/agent/devices/MONITOR_PROFILES.md section 10). A profile not listed
# here gets a line built from its services.
PROFILE_NOTES = {
    'tv_app': {'description': 'TV-app testing: black screen, freeze, zap, audio loss and subtitles. What the monitors always did.',
               'cost': 'Nothing added: runs the image, audio and subtitle monitors.'},
    'counting_cars': {'description': 'Counts cars, trucks and buses crossing the picture with an object detector.',
                      'cost': 'Image monitor only (audio and subtitle idle). A detector at 2 Hz on its own thread, about +60 MB memory; needs the YOLOX model file.'},
    'egg_quality': {'description': 'Finds eggs on a belt and classifies each as good or bad.',
                    'cost': 'Image monitor only (audio and subtitle idle). Detector at 4 Hz plus a small classifier, about +16 MB memory, up to 40 small crop images on disk; needs the egg model file.'},
    'egg_quality_yolo_belt': {'title': 'Egg line (belt model)',
                              'description': 'Circles every egg on a conveyor belt with a model trained on belts. Finds 98.6 % of the eggs where the older egg model finds 78 %, in one pass a frame instead of twelve.',
                              'cost': 'Image monitor only (audio and subtitle idle). One 960x960 detection pass at 1 Hz plus a small grader on every crop, about +60 MB memory; needs the belt model file.'},
    'egg_count_yolo_belt': {'title': 'Egg count (belt model)',
                            'description': 'Counts the eggs on a conveyor belt with the belt model, and only counts them: no good/bad grade, because the image of a white egg on a blue belt says nothing about what is inside it.',
                            'cost': 'Image monitor only (audio and subtitle idle). One 960x960 detection pass at 1.2 Hz, about +60 MB memory; needs the belt model file.'},
    'egg_count_yolo_belt_fast': {'title': 'Egg count (fast)',
                                 'description': 'The same honest egg count, three times faster: the belt model exported at 640x640 finds 98 % of the eggs in a third of the time. Use it when the rate of the count matters more than the last egg.',
                                 'cost': 'Image monitor only (audio and subtitle idle). One 640x640 detection pass at 2 Hz, about +60 MB memory; needs the 640 export of the belt model file.'},
    'tv_lite': {'title': 'TV lite',
                'description': 'Stream and control only: live video, screenshots on demand and remote control, no monitoring (no incidents, no zap detection, no 24 h review buffer).',
                'cost': 'Runs no monitor, archiver, KPI scan or AVQ for the device and writes fewer ffmpeg outputs (no 5 fps thumbnails), so a host carries more streams. Restarts vpt-stream: the video of every device on this host drops for a few seconds.'},
    'pc': {'title': 'PC',
           'description': 'Same lean shape as tv_lite, semantically named for PC / desktop / server captures (host_vnc, VDI, WebDriver). No TV-app monitoring, no audio checks, no 24 h review buffer. Use this on a headless box whose devices do not need blackscreen / freeze / zap detection.',
           'cost': 'Same as tv_lite: runs no monitor, archiver, KPI scan or AVQ for the device. On a host whose every device runs pc (or any profile with img:false), apply_monitor_profiles() stops vpt-monitor-img and vpt-monitor-audio, releasing the inotify watcher and the RSS the imager held while idle.'},
    'fixnet': {'title': 'Voice line',
               'description': 'For a USB voice modem or any audio-only line: no image, audio-level or subtitle monitoring, and no 24 h review buffer, because there is no picture to watch. Keeps the KPI scan and the per-minute A/V quality score.',
               'cost': 'Runs no monitor and no archiver for the device; keeps vpt-kpi and vpt-avq. On a modem rack apply_monitor_profiles() stops vpt-monitor-img, -audio, -subtitle and vpt-archiver, and the stopped units read as "not needed" rather than as a host in error (BUG-0729). Stream mode stays full because KPI and AVQ do read the ffmpeg outputs.'},
    'drone': {'description': "A drone's battery, temperature, altitude, speed, flight time and GPS (when it has a fix) next to its picture, with alerts for low battery, heat and a lost link.",
              'cost': 'Image monitor only (audio and subtitle idle). Reads a small status file the drone controller writes; a few KB of memory, no model file.'},
    'ad_meter': {'description': 'Measures how much of a live TV channel is commercial breaks, from the picture only.',
                 'cost': 'Image monitor only (audio and subtitle idle). About 1-3 ms per sample at 2 Hz, up to +26 MB memory, a few MB of break history in the device folder; no model file.'},
}


def list_profiles(profiles_dir: Optional[str] = None, is_active=None) -> List[Dict[str, Any]]:
    """The profiles available on this host, for the Settings picker: title, services it needs, model files, whether it can run now."""
    is_active = is_active or _is_active
    out = []
    for fname in sorted(os.listdir(profiles_dir or PROFILES_DIR)):
        name, ext = os.path.splitext(fname)
        if ext != '.yaml' or not profile_exists(name, profiles_dir):
            continue
        manifest, error = _load_manifest(name, profiles_dir)
        services = profile_services(name, profiles_dir) if manifest else {s: True for s in SERVICES}
        models = _models_needed(manifest) if manifest else []
        problem = profile_problem(name, profiles_dir)
        note = PROFILE_NOTES.get(name) or {}
        needs = [s for s in SERVICES if services.get(s)]
        out.append({
            'name': name,
            'title': ((manifest or {}).get('ui') or {}).get('title') or note.get('title') or name,
            'services': services,
            'stream': profile_stream_mode(name, profiles_dir) if manifest else 'full',
            'models': models,
            'usable': problem is None,
            'reason': problem['reason'] if problem else None,
            'description': note.get('description') or '',
            'cost': note.get('cost') or ('Runs the ' + ', '.join(needs) + ' monitor' + ('s' if len(needs) > 1 else '') + ' for its devices.'),
        })
    return out


def unit_states(is_active=None) -> Dict[str, Dict[str, Any]]:
    is_active = is_active or _is_active
    return {s: {'unit': SERVICE_UNITS[s], 'active': bool(is_active(SERVICE_UNITS[s]))} for s in SERVICES}


def start_apply(**kwargs) -> None:
    """Mark the apply as running (so the first status poll after a save already says so) and run it on a background thread."""
    _write_result({'state': 'applying', 'started_at': time.time()})
    threading.Thread(target=apply_monitor_profiles, kwargs=kwargs, daemon=True, name='apply-monitor-profiles').start()


def apply_monitor_profiles(restart=None, is_active=None, stop=None, start=None) -> Dict[str, Any]:
    """Compare the profiles in the .env files with the ones last applied; restart the monitor units that follow
    a changed profile. Returns {'profiles', 'restarted', 'first_run'}. Never raises: the host must come up
    whatever happens here. The outcome is also kept in the result file for GET /host/monitor/profiles/status.

    Only units that are running are restarted; a stopped or disabled one is left alone and picks the profile up when it is
    started (reported as 'not_running'). The record is written only when every restart succeeded, so a failed one is tried again at the next call.
    The first run on a host (no record) only records the profiles: the units were started from the same .env.
    """
    started = time.time()
    result = _apply(restart, is_active, stop, start)
    result.update({'state': 'done', 'started_at': started, 'finished_at': time.time()})
    _write_result(result)
    return result


def _stop_unneeded(previous, desired, stop, is_active) -> List[str]:
    """Stop every active profile-driven unit that no device needs (runs on every apply, first run included, so a unit
    systemd started at boot is stopped too). Enabled state is untouched: it comes back at the next boot and is stopped again."""
    return [u for u in units_to_stop_start(previous, desired)['stop'] if is_active(u) and stop(u)]


def _apply(restart=None, is_active=None, stop=None, start=None) -> Dict[str, Any]:
    restart = restart or _restart
    stop = stop or _stop
    start = start or _start
    is_active = is_active or _is_active
    try:
        desired = _desired_state()
        previous = _read_state()
        requested = requested_profiles()
        fallbacks = []
        for d, profile in desired['profiles'].items():
            asked = requested.get(d) or ''
            problem = profile_problem(asked) if asked else None
            if problem:
                fallbacks.append({'device': d, 'requested': asked, 'effective': profile, **problem})
        base = {'profiles': desired['profiles'], 'requested': requested, 'fallbacks': fallbacks}
        if previous is None:
            _write_state(desired)
            logger.info("monitor profiles recorded: %s", desired['profiles'])
            stopped = _stop_unneeded(None, desired, stop, is_active)
            return {**base, 'restarted': [], 'failed': [], 'not_running': [], 'stopped': stopped, 'started': [], 'first_run': True}
        restarted, failed, not_running = [], [], []
        decision = units_to_stop_start(previous, desired)
        stopped = _stop_unneeded(previous, desired, stop, is_active)
        started = [u for u in decision['start'] if not is_active(u) and start(u)]
        units = [SERVICE_UNITS[s] for s in services_to_restart(previous, desired) if SERVICE_UNITS[s] not in decision['stop'] + decision['start']]
        if previous.get('lean', []) != desired['lean']:
            units.append(STREAM_UNIT)
        for unit in units:
            if not is_active(unit):
                not_running.append(unit)
                continue
            (restarted if restart(unit) else failed).append(unit)
        if failed:
            logger.warning("monitor profile restart failed for %s; the profiles are not recorded, the next call retries", failed)
        else:
            _write_state(desired)
        if restarted:
            logger.info("monitor profiles changed %s -> %s; restarted %s", previous.get('profiles'), desired['profiles'], restarted)
        return {**base, 'restarted': restarted, 'failed': failed, 'not_running': not_running,
                'stopped': stopped, 'started': started, 'first_run': False}
    except Exception as e:  # noqa: BLE001
        logger.error("apply_monitor_profiles failed: %s", e)
        return {'profiles': {}, 'restarted': [], 'failed': [], 'not_running': [], 'stopped': [], 'started': [], 'fallbacks': [], 'first_run': False, 'error': str(e)}
