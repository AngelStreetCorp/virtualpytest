"""Which monitoring profile a device uses (TASK-90 §4.5).

Order: DEVICE{N}_MONITOR_PROFILE, then MONITOR_PROFILE, then the model default (DEVICE{N}_MODEL: host_vnc -> pc,
phones -> mobile, tello -> drone, fx_dongle -> fixnet), then 'tv_app'. All three monitor services and
vpt-host import this, so they always agree. An unknown profile name logs an error and falls back to
tv_app: a typo in .env must never stop a monitor.
"""
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = 'tv_app'
# Model default, the last step before tv_app. An explicit .env value always wins. The host-level device (no index) is the
# host_vnc capture when HOST_VNC_STREAM_PATH is set (controller_manager creates it from that key).
# fx_dongle -> fixnet (TASK-151): a USB voice modem has no picture. Without this it fell through to tv_app, so a
# modem rack asked for the image, audio, subtitle and archiver services to watch a device that cannot be watched.
MODEL_PROFILES = {'host_vnc': 'pc', 'android_mobile': 'mobile', 'phone_agent': 'mobile', 'cloud_android_mobile': 'mobile',
                  'tello': 'drone', 'fx_dongle': 'fixnet'}
_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# shared/src/lib/utils/monitor_profile.py -> project root is four levels up
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
PROFILES_DIR = os.path.join(_PROJECT_ROOT, 'backend_host', 'config', 'monitor', 'profiles')


def profile_exists(name: str, profiles_dir: Optional[str] = None) -> bool:
    return bool(_NAME_RE.match(name or '')) and os.path.isfile(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'))


def resolve_monitor_profile(device_index: Optional[int], profiles_dir: Optional[str] = None,
                            env: Optional[Mapping[str, str]] = None) -> str:
    """Profile name for DEVICE{device_index} (None = the host-level device or "no device").

    env: read these variables instead of the process environment (vpt-host reads the .env files fresh, because
    its own environment was fixed when it started).
    """
    env = os.environ if env is None else env
    candidates = []
    if device_index is not None:
        candidates.append((f'DEVICE{device_index}_MONITOR_PROFILE', env.get(f'DEVICE{device_index}_MONITOR_PROFILE')))
    candidates.append(('MONITOR_PROFILE', env.get('MONITOR_PROFILE')))
    for source, raw in candidates:
        name = (raw or '').strip()
        if not name:
            continue
        if profile_exists(name, profiles_dir):
            return name
        logger.error("%s=%r is not a known monitor profile (no %s.yaml in %s); falling back to %s",
                     source, name, name, profiles_dir or PROFILES_DIR, DEFAULT_PROFILE)
        return DEFAULT_PROFILE
    if device_index is not None:
        model = (env.get(f'DEVICE{device_index}_MODEL') or '').strip()
    else:
        model = 'host_vnc' if (env.get('HOST_VNC_STREAM_PATH') or '').strip() else ''
    default = MODEL_PROFILES.get(model)
    if default and profile_exists(default, profiles_dir):
        return default
    return DEFAULT_PROFILE


# ---- which service a profile needs (TASK-90 goal 6) ------------------------------------------------

# The three monitor services, then the host services a profile may switch off (TASK-95): the archiver (24 h review
# buffer), vpt-kpi (navigation KPI scans) and vpt-avq (per-minute A/V KPIs). The last three default to ON, so a
# profile that does not mention them behaves as before.
SERVICES = ('img', 'audio', 'subtitle', 'archiver', 'kpi', 'avq')
_DEFAULT_ON = {'img', 'archiver', 'kpi', 'avq'}
STREAM_MODES = ('full', 'lean')
_ALL_SERVICES = {s: True for s in SERVICES}   # tv_app, and the answer for a manifest we cannot read
_PROFILE_KEY = re.compile(r'^(DEVICE\d+_)?MONITOR_PROFILE$')


def device_index_from_id(device_id: Optional[str]) -> Optional[int]:
    """'device3' -> 3; 'host' (or anything else) -> None."""
    m = re.fullmatch(r'device(\d+)', device_id or '')
    return int(m.group(1)) if m else None


# Analyzer types a manifest may name. A new analyzer adds its type here and in monitor.analyzers.
ANALYZER_TYPES = {'tv_app', 'coco_detect', 'hsv_colour', 'egg_detect', 'yolo_seg_detect', 'egg_classify',
                  'ad_meter', 'telemetry'}
_TOP_KEYS = {'name', 'services', 'stream', 'img', 'audio', 'subtitle', 'events', 'incidents', 'kpis', 'on_incident', 'ui', 'burn_in', 'captions'}
UI_COLOURS = ('green', 'red', 'amber', 'grey', 'blue', 'purple', 'white', 'black', 'yellow', 'brown')


# ---- caption playback (TASK-103): a profile with a `captions` section transcribes that device's audio ----
CAPTION_KEYS = {'delay_s', 'whisper_model', 'language'}
DEFAULT_CAPTION_DELAY_S = 150
WHISPER_MODELS = ('tiny', 'base')


def validate_manifest_light(raw, name: str) -> None:
    """Raise ValueError when a manifest is one the img service would refuse (backend_host/scripts/monitor/profiles.py,
    pydantic). This is the same decision without importing pydantic (+15 MB), so an idle audio or subtitle service
    can make it too: a manifest the img service replaces by tv_app must not make the other services skip the device.
    tests/backend_host/test_monitor_profiles.py runs both validators over the same manifests."""
    if not isinstance(raw, dict):
        raise ValueError('top level must be a mapping')
    if set(raw) - _TOP_KEYS:
        raise ValueError(f'unknown keys {sorted(set(raw) - _TOP_KEYS)}')
    if raw.get('name') != name:
        raise ValueError(f"declares name {raw.get('name')!r}")
    services = raw.get('services') or {}
    if not isinstance(services, dict) or set(services) - set(SERVICES) or not all(isinstance(v, bool) for v in services.values()):
        raise ValueError(f'services must be {{{"|".join(SERVICES)}: true|false}}')
    if raw.get('stream', 'full') not in STREAM_MODES:
        raise ValueError('stream is full or lean')
    if 'burn_in' in raw and not isinstance(raw['burn_in'], bool):
        raise ValueError('burn_in is true or false')
    caps = raw.get('captions')
    if caps is not None:
        if not isinstance(caps, dict) or set(caps) - CAPTION_KEYS:
            raise ValueError(f'captions takes only {sorted(CAPTION_KEYS)}')
        ds = caps.get('delay_s', DEFAULT_CAPTION_DELAY_S)
        if not isinstance(ds, (int, float)) or isinstance(ds, bool) or not 60 <= ds <= 600:
            raise ValueError('captions.delay_s is 60..600')
        if caps.get('whisper_model', 'tiny') not in WHISPER_MODELS:
            raise ValueError(f'captions.whisper_model is one of {WHISPER_MODELS}')
        lang = caps.get('language')
        if lang is not None and not (isinstance(lang, str) and re.fullmatch(r'[a-z]{2,3}', lang)):
            raise ValueError('captions.language is a language code such as de, or absent for auto')
        if not (raw.get('services') or {}).get('audio'):
            raise ValueError('captions needs services.audio: true')
    img = raw.get('img')
    if not isinstance(img, dict) or not img.get('analyzers') or not isinstance(img['analyzers'], list):
        raise ValueError('img.analyzers is required')
    for a in img['analyzers']:
        if not isinstance(a, dict) or a.get('type') not in ANALYZER_TYPES:
            raise ValueError(f"unknown analyzer type {a.get('type') if isinstance(a, dict) else a!r}")
    if not isinstance(img.get('telemetry', False), bool):
        raise ValueError('img.telemetry is true or false')
    track = img.get('track')
    if track is not None:
        allowed = {'algo', 'max_gap_s', 'min_iou', 'votes', 'min_votes', 'cold_gate', 'count_line_x', 'count_dir'}
        cl = track.get('count_line_x') if isinstance(track, dict) else None
        if cl is not None and (not isinstance(cl, (int, float)) or isinstance(cl, bool) or not 0 < cl < 1):
            raise ValueError('track.count_line_x is a fraction of the frame width, 0..1')
        if isinstance(track, dict) and track.get('count_dir', 'right') not in ('right', 'left'):
            raise ValueError('track.count_dir is right or left')
        cg = track.get('cold_gate', 0) if isinstance(track, dict) else 0
        if not isinstance(cg, (int, float)) or isinstance(cg, bool) or not 0 <= cg <= 5:
            raise ValueError('track.cold_gate is 0..5')
        if not isinstance(track, dict) or set(track) - allowed:
            raise ValueError('track has unknown keys')
        if track.get('algo', 'iou') not in ('iou', 'ocsort'):
            raise ValueError('track.algo is iou or ocsort')
        votes = track.get('votes', 1)
        if not isinstance(votes, int) or not 1 <= votes <= 15:
            raise ValueError('track.votes is 1..15')
        mv = track.get('min_votes')
        if mv is not None and (not isinstance(mv, int) or mv < 1 or mv > votes):
            raise ValueError('track.min_votes is 1..votes')
    events = raw.get('events') or {}
    kpis = raw.get('kpis') or []
    incidents = raw.get('incidents') or {}
    for ename, spec in events.items():
        if not isinstance(spec, dict) or 'attr' not in spec or ('equals' in spec) == ('in' in spec):
            raise ValueError(f'event {ename!r} needs attr and exactly one of equals / in')
    kpi_names = [k.get('name') for k in kpis if isinstance(k, dict)]
    if len(kpi_names) != len(kpis) or len(set(kpi_names)) != len(kpi_names):
        raise ValueError('kpis need unique names')
    stat_names = {k.get('name') for k in kpis if isinstance(k, dict) and 'stat' in k}
    for k in kpis:
        if 'stat' in k:
            st = k['stat']
            if set(k) != {'name', 'stat'} or not isinstance(st, dict) or set(st) != {'field', 'fn'} \
                    or not isinstance(st['field'], str) or not st['field'] or st['fn'] not in ('min', 'max', 'last'):
                raise ValueError(f"kpi {k.get('name')!r}: a stat kpi is {{name, stat: {{field, fn: min|max|last}}}} and nothing else")
            continue
        if k.get('of') not in events or not isinstance(k.get('window_s'), (int, float)) or isinstance(k.get('window_s'), bool) or k['window_s'] <= 0:
            raise ValueError(f"kpi {k.get('name')!r}: needs a declared event in `of` and window_s > 0")
        shapes = [s for s in ('group_by', 'pct_where', 'pct_time', 'first_in_hour') if k.get(s) not in (None, False)]
        if len(shapes) > 1:
            raise ValueError(f"kpi {k.get('name')!r}: one of group_by, pct_where, pct_time or first_in_hour")
        if 'pct_where' in k:
            pw = k['pct_where']
            if not isinstance(pw, dict) or 'attr' not in pw or ('equals' in pw) == ('in' in pw):
                raise ValueError(f"kpi {k.get('name')!r}: pct_where is {{attr, equals|in}} and excludes group_by")
        for flag in ('pct_time', 'first_in_hour', 'since_midnight'):
            if flag in k and not isinstance(k[flag], bool):
                raise ValueError(f"kpi {k.get('name')!r}: {flag} is true or false")
        if k.get('since_midnight') and (not k.get('pct_time') or k['window_s'] < 90000):
            raise ValueError(f"kpi {k.get('name')!r}: since_midnight goes with pct_time and window_s of at least 90000")
    ui = raw.get('ui')
    if ui is not None:
        grouped = {k.get('name') for k in kpis if isinstance(k, dict) and k.get('group_by')}
        plain = {k.get('name') for k in kpis if isinstance(k, dict) and not k.get('group_by')}
        if not isinstance(ui, dict) or set(ui) - {'title', 'headline', 'stats', 'counters', 'box', 'focus_panel',
                                                  'state_badge', 'hud'} or not isinstance(ui.get('title'), str):
            raise ValueError('ui needs a title and only title, headline, stats, counters, box, focus_panel, state_badge')
        hl = ui.get('headline')
        if hl is not None and (not isinstance(hl, dict) or not {'kpi', 'label'} <= set(hl) <= {'kpi', 'label', 'unit'}
                               or hl['kpi'] not in plain or hl.get('unit') not in (None, '%', 'min')):
            raise ValueError('ui.headline is {kpi: <plain kpi>, label, unit?: % | min}')
        stats = ui.get('stats')
        if stats is not None:
            if not isinstance(stats, list) or not stats or any(
                    not isinstance(s, dict) or 'label' not in s or set(s) - {'label', 'kpi', 'observations'}
                    or ('observations' in s and not isinstance(s['observations'], bool))
                    or bool(s.get('kpi')) == bool(s.get('observations'))
                    or (s.get('kpi') is not None and s['kpi'] not in plain) for s in stats):
                raise ValueError('ui.stats is [{label, kpi: <plain kpi>} | {label, observations: true}]')
        ct = ui.get('counters')
        if ct is not None:
            items = ct.get('items') if isinstance(ct, dict) else None
            if not items or set(ct) != {'kpi', 'items'} or ct['kpi'] not in grouped or any(
                    not isinstance(i, dict) or 'key' not in i or i.get('colour') not in UI_COLOURS or set(i) - {'key', 'colour', 'label'} for i in items):
                raise ValueError('ui.counters is {kpi: <group_by kpi>, items: [{key, colour, label?}]}')
        box = ui.get('box') or {}
        if set(box) - {'shape', 'badge', 'colour_by'} or box.get('shape', 'rect') not in ('rect', 'ellipse') \
                or box.get('badge', 'none') not in ('none', 'votes') or box.get('colour_by', 'none') not in ('none', 'verdict'):
            raise ValueError('ui.box is {shape: rect|ellipse, badge: none|votes, colour_by: none|verdict}')
        sb = ui.get('state_badge')
        if sb is not None and (not isinstance(sb, dict) or not {'event', 'label'} <= set(sb) <= {'event', 'label', 'colour'}
                               or sb['event'] not in events or sb.get('colour', 'red') not in UI_COLOURS):
            raise ValueError('ui.state_badge is {event: <declared event>, label, colour?}')
        hud = ui.get('hud')
        if hud is not None:
            if not isinstance(hud, list) or not hud:
                raise ValueError('ui.hud is a non-empty list of {key, label, format?, key2?, short?, unit?, decimals?, warn_above?, warn_below?}')
            for it in hud:
                if not isinstance(it, dict) or not {'key', 'label'} <= set(it) <= {'key', 'label', 'format', 'key2', 'short', 'unit', 'decimals', 'warn_above', 'warn_below'} \
                        or not isinstance(it['key'], str) or not isinstance(it['label'], str) \
                        or not (it.get('short') is None or (isinstance(it['short'], str) and len(it['short']) <= 4)) \
                        or it.get('format', 'number') not in ('number', 'battery', 'duration', 'latlon') \
                        or (it.get('format') == 'latlon') != ('key2' in it) \
                        or not isinstance(it.get('decimals', 0), int) or isinstance(it.get('decimals', 0), bool) or not 0 <= it.get('decimals', 0) <= 6 \
                        or any(isinstance(it.get(w), bool) or not isinstance(it.get(w, 0), (int, float)) for w in ('warn_above', 'warn_below')):
                    raise ValueError(f'ui.hud item {it!r} is not valid')
        fp = ui.get('focus_panel')
        if fp is not None and (not isinstance(fp, dict) or set(fp) - {'crop', 'probs', 'title'}):
            raise ValueError('ui.focus_panel is {crop, probs, title}')
    for iname, inc in incidents.items():
        if not isinstance(inc, dict) or (('event' in inc) == ('kpi' in inc)):
            raise ValueError(f'incident {iname!r} needs exactly one of event / kpi')
        if 'event' in inc and (inc['event'] not in events or 'after_s' not in inc):
            raise ValueError(f'incident {iname!r}: declared event and after_s required')
        if inc.get('kpi') in stat_names:
            raise ValueError(f'incident {iname!r}: kpi {inc["kpi"]!r} is a telemetry statistic')
        if 'kpi' in inc and (inc['kpi'] not in kpi_names or ('above' in inc) == ('below' in inc) or 'window_s' not in inc):
            raise ValueError(f'incident {iname!r}: declared kpi, one of above / below, and window_s required')
        if 'kpi' in inc:
            mw, ms = inc.get('min_watch_s'), inc.get('min_samples')
            if (mw is not None and (not isinstance(mw, (int, float)) or isinstance(mw, bool) or mw < 0)) or \
                    (ms is not None and (not isinstance(ms, int) or isinstance(ms, bool) or ms < 0)):
                raise ValueError(f'incident {iname!r}: min_watch_s is a number >= 0, min_samples an integer >= 0')
        elif 'min_watch_s' in inc or 'min_samples' in inc:
            raise ValueError(f'incident {iname!r}: an event incident takes only event and after_s')


def profile_services(name: str, profiles_dir: Optional[str] = None) -> Dict[str, bool]:
    """{service: bool} for SERVICES: the services the profile's manifest turns on. A manifest that
    cannot be read or that the img service would refuse counts as tv_app (everything on): img runs that device as
    tv_app, so the other services must serve it as tv_app."""
    try:
        import yaml
        with open(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'), 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        validate_manifest_light(raw, name)
        declared = raw.get('services') or {}
        return {s: bool(declared.get(s, s in _DEFAULT_ON)) for s in SERVICES}
    except Exception as e:
        logger.error("profile %r is unusable (%s); its devices count as %s", name, e, DEFAULT_PROFILE)
        return dict(_ALL_SERVICES)


def read_env_files(key_pattern=_PROFILE_KEY) -> Dict[str, str]:
    """Variables matching key_pattern (default: the profile keys) as the .env files say now (project .env wins
    over backend_host/src/.env, like the services load them)."""
    out: Dict[str, str] = {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return out
    for path in (os.path.join(_PROJECT_ROOT, 'backend_host', 'src', '.env'), os.path.join(_PROJECT_ROOT, '.env')):
        if os.path.isfile(path):
            for k, v in (dotenv_values(path, encoding='utf-8-sig') or {}).items():
                if key_pattern.match(k) and v is not None:
                    out[k] = v
    return out


# Profile variables the process was started with (systemd EnvironmentFile or a drop-in `Environment=`): never overridden
# by a later reload. A change to one of them reaches an idle service through vpt-host, which restarts the running units
# (apply_monitor_profiles); the reload below only adds keys that were absent at start.
_STARTUP_KEYS = {k for k in os.environ if _PROFILE_KEY.match(k)}
_set_from_files: set = set()


def reload_profile_env() -> None:
    """Pick up profile variables that appeared in the .env files after this process started, so a profile added
    while a service idles is seen at its next check. Values the process started with are left alone (a systemd
    drop-in must keep winning); a key a reload added and the files no longer carry is dropped again."""
    fresh = {k: v for k, v in read_env_files().items() if k not in _STARTUP_KEYS}
    for k in [k for k in _set_from_files if k not in fresh]:
        os.environ.pop(k, None)
        _set_from_files.discard(k)
    os.environ.update(fresh)
    _set_from_files.update(fresh)


def folders_needing_service(service: str, capture_folders: Iterable[str], env: Optional[Mapping[str, str]] = None,
                            profiles_dir: Optional[str] = None) -> List[str]:
    """The capture folders (captureN) whose device's profile turns `service` on.

    Single source of truth for "does this device need this monitor service?" (BUG-0563). Three
    callers consult it; they all see the same answer, so the imager, the host orchestrator and the
    per-directory filter cannot disagree:

    - `shared.src.lib.utils.monitor_service.wait_until_needed` — the unit's idle gate at startup.
    - `_desired_state` below — the host orchestrator's "should this unit run?" decision.
    - `capture_monitor.py:_init_capture_dirs` — the per-capture-dir filter that decides which
      capture folders get an inotify watch and a frame worker.

    If you change the contract, change all three call sites (and the test
    `tests/backend_host/test_monitor_services_follow_profiles.py`).
    """
    from shared.src.lib.utils.storage_path_utils import get_device_info_from_capture_folder
    out = []
    for folder in capture_folders:
        index = get_device_info_from_capture_folder(folder).get('device_index')
        name = resolve_monitor_profile(index, profiles_dir, env)
        if profile_services(name, profiles_dir).get(service):
            out.append(folder)
    return out


def folders_needing_service_for_devices(service: str, profiles: Mapping[str, str], profiles_dir: Optional[str] = None) -> List[str]:
    """Device ids ({device_id: profile} given) whose profile turns `service` on."""
    return [d for d, name in profiles.items() if profile_services(name, profiles_dir).get(service)]


def profile_stream_mode(name: str, profiles_dir: Optional[str] = None) -> str:
    """'full' (every output the monitors read) or 'lean' (TASK-95 tv_lite: fewer ffmpeg outputs). An unreadable
    manifest is 'full': the device is run as tv_app and needs everything."""
    try:
        import yaml
        with open(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'), 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        validate_manifest_light(raw, name)
        return raw.get('stream', 'full')
    except Exception as e:
        logger.error("profile %r is unusable (%s); its stream stays full", name, e)
        return 'full'


def lean_devices(device_profiles: Mapping[str, str], profiles_dir: Optional[str] = None) -> List[str]:
    """Device ids ({device_id: profile} given) whose profile asks for the lean ffmpeg outputs."""
    return sorted(d for d, name in device_profiles.items() if profile_stream_mode(name, profiles_dir) == 'lean')


# ---- "monitoring off" for a capture folder (TASK-95) ---------------------------------------------------------

def profile_for_capture_folder(folder: str, env: Optional[Mapping[str, str]] = None) -> str:
    """Profile name of the device whose capture folder is `folder` (captureN or a path ending in it)."""
    from shared.src.lib.utils.storage_path_utils import get_device_info_from_capture_folder
    index = get_device_info_from_capture_folder(os.path.basename(str(folder).rstrip('/\\'))).get('device_index')
    return resolve_monitor_profile(index, env=env)


def monitoring_off(folder: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """True when the device's profile runs no monitor for it (tv_lite): no frame JSONs, zap files, audio status or
    incidents exist, and anything that waits for them should say so instead of timing out."""
    try:
        return not profile_services(profile_for_capture_folder(folder, env)).get('img', True)
    except Exception:  # noqa: BLE001 - a lookup failure must never turn into "monitoring off"
        return False


def is_lean_capture_folder(folder: str, env: Optional[Mapping[str, str]] = None) -> bool:
    try:
        return profile_stream_mode(profile_for_capture_folder(folder, env)) == 'lean'
    except Exception:  # noqa: BLE001
        return False


MONITORING_OFF_MESSAGE = ("Monitoring is off for this device (monitor profile tv_lite): it has no per-frame analysis, "
                          "zapping, audio status or alerts. Use a device with the tv_app profile for this check.")


def profile_captions(name: str, profiles_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """{delay_s, whisper_model, language} when the profile's manifest has a `captions` section, else None
    (also None for a manifest that cannot be read: the device then runs as tv_app)."""
    try:
        import yaml
        with open(os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml'), 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        validate_manifest_light(raw, name)
    except Exception:  # noqa: BLE001 - profile_services logs the unusable manifest
        return None
    caps = raw.get('captions')
    if caps is None:
        return None
    return {'delay_s': caps.get('delay_s', DEFAULT_CAPTION_DELAY_S), 'whisper_model': caps.get('whisper_model', 'tiny'),
            'language': caps.get('language')}


def device_captions(device_index: Optional[int], env: Optional[Mapping[str, str]] = None,
                    profiles_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Caption settings of DEVICE{device_index}, or None when its profile has none. DEVICE{N}_CAPTION_LANGUAGE
    (a code, or `auto`) overrides the manifest's language for that device."""
    env = os.environ if env is None else env
    params = profile_captions(resolve_monitor_profile(device_index, profiles_dir, env), profiles_dir)
    if params is None:
        return None
    if device_index is not None:
        override = (env.get(f'DEVICE{device_index}_CAPTION_LANGUAGE') or '').strip().lower()
        if override:
            params['language'] = None if override == 'auto' else override
    return params


def folders_with_captions(capture_folders: Iterable[str], env: Optional[Mapping[str, str]] = None,
                          profiles_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{captureN: caption params} for the folders whose device profile has captions."""
    from shared.src.lib.utils.storage_path_utils import get_device_info_from_capture_folder
    out = {}
    for folder in capture_folders:
        index = get_device_info_from_capture_folder(folder).get('device_index')
        params = device_captions(index, env, profiles_dir)
        if params is not None:
            out[folder] = params
    return out
