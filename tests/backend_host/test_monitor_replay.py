"""Replay gate for vpt-monitor-img (TASK-90 §4.3): tv_app output must never change.

Feeds the recorded 2-minute fixture (tests/fixtures/monitor_tv_app) frame by frame through
FrameMonitor.process_frame with a frozen clock and compares every per-frame JSON (plus the
10-minute chunk and the detections handed to the incident manager) with expected.json.gz,
which the UNMODIFIED code produced. Re-recorded on 2026-10-13 from origin/main 7008485f3 (the unsplit capture_monitor.py with the
blackscreen / no_signal priority change, BUG-0504) on the fixture extended with a no_signal stretch, a freeze that becomes no_signal and a
near-black stretch (tests/fixtures/monitor_tv_app/build_fixture.py --extend); the split code has to reproduce that exactly.

Re-record only when tv_app behaviour is meant to change:
    python3 tests/backend_host/test_monitor_replay.py --record
"""
import gzip
import json
import os
import queue
import shutil
import sys
import time
import types
import datetime as _real_datetime_module

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPTS = os.path.join(ROOT, 'backend_host', 'scripts')
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'monitor_tv_app')
EXPECTED = os.path.join(FIXTURE, 'expected.json.gz')

# Wall-clock / timing fields that legitimately differ between runs. Everything else must match.
IGNORED_KEYS = {'performance_ms', 'analysis_time'}
# From goal 4 on tv_app also writes these four generic keys; they must be "tv_app" / empty (checked, then dropped).
# The brief names three (profile, observations, kpis); `events` is the fourth key of the §4.6 JSON, empty for tv_app.
GOAL4_KEYS = {'profile': 'tv_app', 'observations': [], 'events': {}, 'kpis': {}}

BASE_TS = 1760000000.0  # 2025-10-09 08:53:20 UTC; frame i is at BASE_TS + i / 5
FPS = 5


class _Clock:
    now = BASE_TS


def _install_stubs():
    """Make capture_monitor importable without inotify / watchdog (CI, macOS)."""
    for name in ('inotify', 'inotify.adapters', 'inotify.constants'):
        if name not in sys.modules:
            try:
                __import__(name)
            except Exception:
                mod = types.ModuleType(name)
                mod.IN_MOVED_TO = 0
                mod.Inotify = object
                sys.modules[name] = mod
    if 'inotify' in sys.modules and not hasattr(sys.modules['inotify'], 'adapters'):
        sys.modules['inotify'].adapters = sys.modules['inotify.adapters']
        sys.modules['inotify'].constants = sys.modules['inotify.constants']
    try:
        import watchdog  # noqa: F401
    except Exception:
        for name in ('watchdog', 'watchdog.observers', 'watchdog.events'):
            sys.modules[name] = types.ModuleType(name)
        sys.modules['watchdog.observers'].Observer = lambda *a, **k: types.SimpleNamespace()
        sys.modules['watchdog.events'].FileSystemEventHandler = object


def _frozen_datetime_module():
    real = _real_datetime_module

    class FrozenDatetime(real.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(_Clock.now, tz)

        @classmethod
        def utcnow(cls):
            return cls.utcfromtimestamp(_Clock.now)

    shim = types.ModuleType('datetime')
    shim.__dict__.update({k: v for k, v in real.__dict__.items() if not k.startswith('__')})
    shim.datetime = FrozenDatetime
    return shim, FrozenDatetime


def _scrub(value, root):
    if isinstance(value, dict):
        return {k: _scrub(v, root) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [_scrub(v, root) for v in value]
    if isinstance(value, str):
        return value.replace(root, '<ROOT>')
    return value


def run_replay(work_dir, env_extra=None, frames=None, configure=None, after_frame=None, device_count=1):
    """Replay the fixture under work_dir through FrameMonitor with a frozen clock.

    Returns {'frames': {name: json}, 'chunks': {...}, 'detections': [...]} for capture1. With device_count > 1 the same
    frames are fed to capture1..captureN (DEVICE1..N) and the result also has 'devices': {captureN: that same dict}.

    env_extra / frames / configure() / after_frame(frame_monitor, name, capture_folder) / device_count let other profiles
    reuse the harness (test_counting_cars.py, test_monitor_per_device.py); the tv_app gate uses none of them."""
    os.environ['TZ'] = 'UTC'
    if hasattr(time, 'tzset'):
        time.tzset()
    _install_stubs()
    stream = os.path.join(work_dir, 'stream')
    folders = [f'capture{i}' for i in range(1, device_count + 1)]
    names = sorted(os.listdir(os.path.join(FIXTURE, 'captures')))
    if frames is not None:
        names = names[:frames]
    paths = {}
    for folder in folders:
        device = os.path.join(stream, folder)
        caps = os.path.join(device, 'captures')
        thumbs = os.path.join(device, 'thumbnails')
        meta = os.path.join(device, 'metadata')
        for d in (caps, thumbs, meta):
            os.makedirs(d, exist_ok=True)
        for i, name in enumerate(names):
            src = os.path.join(FIXTURE, 'captures', name)
            shutil.copy(src, os.path.join(caps, name))
            shutil.copy(src, os.path.join(thumbs, name.replace('.jpg', '_thumbnail.jpg')))
            ts = BASE_TS + i / FPS
            os.utime(os.path.join(caps, name), (ts, ts))
            os.utime(os.path.join(thumbs, name.replace('.jpg', '_thumbnail.jpg')), (ts, ts))
        shutil.copy(os.path.join(FIXTURE, 'audio_status.json'), os.path.join(meta, 'audio_status.json'))
        paths[folder] = (device, caps, meta)

    env = {
        'STREAM_BASE_PATH': stream,
        'HOST_NAME': 'replay-host',
    }
    for n, folder in enumerate(folders, start=1):
        env[f'DEVICE{n}_VIDEO_CAPTURE_PATH'] = paths[folder][0]
        env[f'DEVICE{n}_NAME'] = f'device{n}'
        env[f'DEVICE{n}_MODEL'] = 'replay_fixture'
    env.update(env_extra or {})
    saved_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    saved_modules = {}
    try:
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import shared.src.lib.utils.storage_path_utils as spu
        spu._STREAM_BASE_PATH = stream
        spu._device_mapping_cache.clear()
        import detector
        import incident_manager
        import monitor.core as capture_monitor
        import monitor.analyzers.tv_app as tv_app
        for cache in ('_freeze_thumbnail_cache', '_freeze_result_cache', '_blackscreen_result_cache'):
            getattr(detector, cache, {}).clear()

        shim, Frozen = _frozen_datetime_module()
        real_time = time.time
        time.time = lambda: _Clock.now
        for mod in (capture_monitor, tv_app, detector, incident_manager):
            if hasattr(mod, 'datetime'):
                saved_modules[mod] = mod.datetime
                mod.datetime = Frozen
        saved_modules['sys.modules.datetime'] = sys.modules['datetime']
        sys.modules['datetime'] = shim

        class QuietIncidentManager(incident_manager.IncidentManager):
            def __init__(self, *a, **k):
                super().__init__(skip_startup_cleanup=True)

        if configure:
            configure()
        saved_im = capture_monitor.IncidentManager
        capture_monitor.IncidentManager = QuietIncidentManager
        handed_over = {}
        try:
            fm = capture_monitor.FrameMonitor([], 'replay-host')
            iqs = {}
            for folder in folders:
                fm._init_device(paths[folder][1])   # directory info + profile + analyzers, no thread
                # the real incident worker is a thread; drain its queue inline so the output is deterministic
                iqs[folder] = queue.Queue()
                fm.incident_queues[folder] = iqs[folder]
                handed_over[folder] = []
            for analyzers in fm._analyzers_by_profile.values():
                for a in analyzers:
                    if hasattr(a, 'zapping_executor'):
                        a.zapping_executor.submit = lambda *args, **kw: None  # zap reports need AI/network
            for i, name in enumerate(names):
                _Clock.now = BASE_TS + i / FPS
                for folder in folders:
                    fm.process_frame(paths[folder][1], name, 0)
                    if after_frame:
                        after_frame(fm, name, folder)
                    while not iqs[folder].empty():
                        handed_over[folder].append(iqs[folder].get_nowait()[0])
            fm._flush_dirty_chunks(force=True)
            _Clock.now += 10
            fm._flush_dirty_chunks(force=True)
        finally:
            capture_monitor.IncidentManager = saved_im
            time.time = real_time

        results = {}
        for folder in folders:
            meta = paths[folder][2]
            out = {'frames': {}, 'chunks': {}}
            for dirpath, _dirs, files in sorted(os.walk(meta)):
                for name in sorted(files):
                    path = os.path.join(dirpath, name)
                    if name.startswith('capture_') and name.endswith('.json'):
                        with open(path) as f:
                            out['frames'][name] = _scrub(json.load(f), work_dir)
                    elif name.startswith('chunk_'):
                        key = os.path.relpath(path, meta)
                        with open(path) as f:
                            out['chunks'][key] = _scrub(json.load(f), work_dir)
            out['detections'] = _scrub(handed_over[folder], work_dir)
            results[folder] = out
        out = dict(results['capture1'])
        if device_count > 1:
            out['devices'] = results
        return out
    finally:
        for mod, dt in saved_modules.items():
            if isinstance(mod, str):
                sys.modules['datetime'] = dt
            else:
                mod.datetime = dt
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _drop_goal4_keys(obj):
    """From goal 4 on tv_app also writes profile/observations/kpis; they must be the empty tv_app values."""
    if isinstance(obj, dict):
        for k, v in GOAL4_KEYS.items():
            if k in obj:
                assert obj[k] == v, f'{k}={obj[k]!r}, expected {v!r}'
                del obj[k]
        for v in obj.values():
            _drop_goal4_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            _drop_goal4_keys(v)


def test_tv_app_replay_matches_recording(tmp_path):
    with gzip.open(EXPECTED, 'rt') as f:
        expected = json.load(f)
    got = run_replay(str(tmp_path))
    assert all(fr.get('profile') == 'tv_app' for fr in got['frames'].values()), 'every frame JSON carries profile=tv_app'
    _drop_goal4_keys(got)
    assert set(got['frames']) == set(expected['frames'])
    bad = [n for n in expected['frames'] if got['frames'][n] != expected['frames'][n]]
    assert not bad, f'{len(bad)} frame JSONs differ, first: {bad[0]}\n' + _diff(expected['frames'][bad[0]], got['frames'][bad[0]])
    assert got['chunks'] == expected['chunks']
    assert got['detections'] == expected['detections']


def test_fixture_covers_blackscreen_freeze_and_no_signal():
    with gzip.open(EXPECTED, 'rt') as f:
        expected = json.load(f)
    frames = expected['frames'].values()
    assert any(fr.get('blackscreen') for fr in frames), 'fixture has no blackscreen frame'
    assert any(fr.get('freeze') for fr in frames), 'fixture has no freeze frame'
    assert any(fr.get('no_signal') for fr in frames), 'fixture has no no_signal frame'
    assert not any(fr.get('freeze') and (fr.get('blackscreen') or fr.get('no_signal')) for fr in frames), 'freeze must lose to blackscreen / no_signal'
    assert any('no_signal_event_start' in fr for fr in frames), 'the no_signal event lifecycle keys are in the fixture'
    # BUG-0661 regression: the fixture must exercise both the "near-black that IS a blackscreen"
    # case (lit pixels <= 2%, kind=nearblack_bs) and the "dark live scene" case (lit pixels > 2%,
    # kind=nearblack). Read the timeline so the assertion stays correct if the stretch sizes change.
    timeline_path = os.path.join(FIXTURE, 'timeline.json')
    with open(timeline_path) as f:
        timeline = json.load(f)
    by_kind = {seg['kind']: seg for seg in timeline['segments']}
    for kind in ('nearblack_bs', 'nearblack'):
        assert kind in by_kind, f'fixture timeline is missing the {kind!r} stretch'
    def seq_to_name(first_seq, offset):
        return f'capture_{first_seq + offset:09d}.json'
    nb_bs = by_kind['nearblack_bs']
    nb_bs_frames = [expected['frames'][seq_to_name(nb_bs['first_seq'], i)] for i in range(nb_bs['frames'])]
    assert all(fr.get('blackscreen') for fr in nb_bs_frames), (
        f'BUG-0661: the nearblack_bs stretch (lit pixels <= 2%) must be classified as blackscreen, '
        f'but frames {nb_bs["first_seq"]}..{nb_bs["first_seq"] + nb_bs["frames"] - 1} are not'
    )
    nb = by_kind['nearblack']
    nb_frames = [expected['frames'][seq_to_name(nb['first_seq'], i)] for i in range(nb['frames'])]
    assert not any(fr.get('blackscreen') for fr in nb_frames), (
        f'BUG-0661: the nearblack stretch (lit pixels > 2%, dark live scene) must NOT be classified '
        f'as blackscreen, but frames {nb["first_seq"]}..{nb["first_seq"] + nb["frames"] - 1} are'
    )


def _diff(a, b):
    keys = sorted(set(a) | set(b))
    return '\n'.join(f'  {k}: expected {a.get(k)!r:.120} got {b.get(k)!r:.120}' for k in keys if a.get(k) != b.get(k))


if __name__ == '__main__':
    import tempfile
    if '--record' in sys.argv:
        with tempfile.TemporaryDirectory() as d:
            rec = run_replay(d)
        with gzip.open(EXPECTED, 'wt', compresslevel=9) as f:
            json.dump(rec, f, sort_keys=True)
        print(f"recorded {len(rec['frames'])} frames, {len(rec['chunks'])} chunks -> {EXPECTED}")
    else:
        sys.exit(pytest.main([__file__, '-q']))
