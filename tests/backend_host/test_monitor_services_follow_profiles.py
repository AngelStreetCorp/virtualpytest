"""The three monitor services follow the profiles (TASK-90 goal 6)."""
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402
import shared.src.lib.utils.monitor_service as ms  # noqa: E402
import backend_host.src.lib.utils.monitor_profile as hostmp  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if mp._PROFILE_KEY.match(k):
            monkeypatch.delenv(k)


def fake_devices(monkeypatch, mapping):
    """capture folder -> device id, without a .env."""
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, 'get_device_info_from_capture_folder',
                        lambda f: {'device_id': mapping.get(f, f), 'device_index': mp.device_index_from_id(mapping.get(f, f))})


def test_services_per_profile():
    host_services = {'archiver': True, 'kpi': True, 'avq': True}    # TASK-95: on unless a profile (tv_lite) says off
    assert mp.profile_services('tv_app') == {'img': True, 'audio': True, 'subtitle': True, **host_services}
    assert mp.profile_services('counting_cars') == {'img': True, 'audio': False, 'subtitle': False, **host_services}
    # a manifest we cannot read keeps everything on (the tv_app behaviour) rather than silencing a device
    assert mp.profile_services('no_such_profile') == {'img': True, 'audio': True, 'subtitle': True, **host_services}


def test_folders_needing_a_service_follow_the_device_profile(monkeypatch):
    fake_devices(monkeypatch, {'capture1': 'device1', 'capture2': 'device2'})
    env = {'DEVICE2_MONITOR_PROFILE': 'counting_cars'}
    folders = ['capture1', 'capture2']
    assert mp.folders_needing_service('img', folders, env) == ['capture1', 'capture2']
    assert mp.folders_needing_service('audio', folders, env) == ['capture1']
    assert mp.folders_needing_service('subtitle', folders, env) == ['capture1']


def test_every_device_counting_means_audio_and_subtitle_have_nothing_to_do(monkeypatch):
    fake_devices(monkeypatch, {'capture1': 'device1', 'capture2': 'device2'})
    env = {'MONITOR_PROFILE': 'counting_cars'}
    assert mp.folders_needing_service('audio', ['capture1', 'capture2'], env) == []
    assert mp.folders_needing_service('img', ['capture1', 'capture2'], env) == ['capture1', 'capture2']


def test_wait_until_needed_idles_then_starts_when_the_profile_changes(monkeypatch):
    fake_devices(monkeypatch, {'capture1': 'device1'})
    monkeypatch.setattr(ms, 'capture_folders', lambda: ['capture1'])
    monkeypatch.setattr(ms, 'reload_profile_env', lambda: None)
    monkeypatch.setenv('MONITOR_PROFILE', 'counting_cars')
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            monkeypatch.setenv('MONITOR_PROFILE', 'tv_app')     # the operator switched the host back

    assert ms.wait_until_needed('audio', 'vpt-monitor-audio', sleep=sleep) == ['capture1']
    assert sleeps == [60, 60]


def test_a_host_with_no_capture_folder_is_not_idle(monkeypatch):
    monkeypatch.setattr(ms, 'capture_folders', lambda: [])
    monkeypatch.setattr(ms, 'reload_profile_env', lambda: None)
    assert ms.wait_until_needed('audio', 'vpt-monitor-audio', sleep=lambda s: pytest.fail('slept')) == []


def test_idle_service_stays_under_30_mb(tmp_path):
    """The idle path runs before any heavy import: run it in a fresh interpreter and read its RSS."""
    code = textwrap.dedent(f"""
        import os, sys, psutil
        sys.path.insert(0, {ROOT!r})
        os.environ.update(MONITOR_PROFILE='counting_cars', STREAM_BASE_PATH={str(tmp_path)!r},
                          DEVICE1_VIDEO_CAPTURE_PATH={str(tmp_path / 'capture1')!r})
        import shared.src.lib.utils.monitor_service as ms
        ms.capture_folders = lambda: ['capture1']
        ms.reload_profile_env = lambda: None
        def sleep(_):
            print(round(psutil.Process().memory_info().rss / 1e6, 1)); raise SystemExit(0)
        ms.wait_until_needed('audio', 'vpt-monitor-audio', sleep=sleep)
    """)
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rss = float(r.stdout.strip().splitlines()[-1])
    assert rss < 30, f'idle RSS {rss} MB'
    assert 'cv2' not in r.stdout


# ---- vpt-host: apply_monitor_profiles ------------------------------------------------------------

@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr(hostmp, 'STATE_FILE', str(tmp_path / 'applied.json'))
    env = {}
    monkeypatch.setattr(hostmp, 'read_env_files', lambda pattern=None: dict(env))
    restarted = []
    monkeypatch.setattr(hostmp, '_is_active', lambda unit: True)
    return env, restarted, (lambda unit: restarted.append(unit) or True)


def test_first_run_only_records(host):
    env, restarted, restart = host
    env.update({'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'})
    out = hostmp.apply_monitor_profiles(restart)
    assert out['first_run'] and restarted == []
    assert out['profiles'] == {'device1': 'tv_app', 'device2': 'tv_app'}


def test_unchanged_profiles_restart_nothing(host):
    env, restarted, restart = host
    env['DEVICE1_VIDEO_CAPTURE_PATH'] = '/x/capture1'
    hostmp.apply_monitor_profiles(restart)
    hostmp.apply_monitor_profiles(restart)
    assert restarted == []


def test_switching_every_device_to_counting_restarts_all_three_and_back_again(host):
    env, restarted, restart = host
    env.update({'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'})
    hostmp.apply_monitor_profiles(restart)
    env['MONITOR_PROFILE'] = 'counting_cars'
    out = hostmp.apply_monitor_profiles(restart)
    # img: its devices run a different profile; audio and subtitle: their device sets became empty
    assert sorted(out['restarted']) == ['vpt-monitor-audio', 'vpt-monitor-img', 'vpt-monitor-subtitle']
    restarted.clear()
    del env['MONITOR_PROFILE']
    out = hostmp.apply_monitor_profiles(restart)
    assert sorted(out['restarted']) == ['vpt-monitor-audio', 'vpt-monitor-img', 'vpt-monitor-subtitle']


def test_one_device_changing_restarts_only_what_follows_it(host):
    env, restarted, restart = host
    env.update({'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'})
    hostmp.apply_monitor_profiles(restart)
    env['DEVICE2_MONITOR_PROFILE'] = 'counting_cars'
    out = hostmp.apply_monitor_profiles(restart)
    assert sorted(out['restarted']) == ['vpt-monitor-audio', 'vpt-monitor-img', 'vpt-monitor-subtitle']   # device2 leaves audio/subtitle, img re-reads
    restarted.clear()
    env['DEVICE1_MONITOR_PROFILE'] = 'tv_app'                      # a no-op edit
    assert hostmp.apply_monitor_profiles(restart)['restarted'] == []


def test_restart_only_touches_monitor_units():
    assert hostmp._restart('vpt-host') is False
    assert hostmp._restart('vpt-monitor-img; rm -rf /') is False


def test_stopped_units_are_never_started_by_a_profile_change(host, monkeypatch):
    """review BLOCK 3: `systemctl restart` starts a stopped unit (a lite host would start Whisper and Tesseract)."""
    env, restarted, restart = host
    env.update({'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'})
    hostmp.apply_monitor_profiles(restart, is_active=lambda u: u == 'vpt-monitor-img')    # audio and subtitle are off
    env['MONITOR_PROFILE'] = 'counting_cars'
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: u == 'vpt-monitor-img')
    assert out['restarted'] == ['vpt-monitor-img'] and restarted == ['vpt-monitor-img']


def test_a_failed_restart_is_retried_at_the_next_call(host):
    env, restarted, restart = host
    env.update({'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1'})
    hostmp.apply_monitor_profiles(restart)
    env['MONITOR_PROFILE'] = 'counting_cars'
    out = hostmp.apply_monitor_profiles(lambda unit: False, is_active=lambda u: True)
    assert out['restarted'] == [] and out['failed']
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)           # same change, nothing was recorded
    assert sorted(out['restarted']) == ['vpt-monitor-audio', 'vpt-monitor-img', 'vpt-monitor-subtitle']
    restarted.clear()
    assert hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)['restarted'] == []   # now recorded


def test_windows_control_path_falls_back_to_the_old_service_names():
    from backend_host.src.lib.utils.system_info_utils import _windows_service_candidates
    assert _windows_service_candidates('vpt-monitor-img') == ['vpt-monitor-img', 'vpt-monitor']
    assert _windows_service_candidates('vpt-monitor-audio') == ['vpt-monitor-audio', 'vpt-transcript']
    assert _windows_service_candidates('vpt-monitor-subtitle') == ['vpt-monitor-subtitle', 'vpt-subtitle']


def test_reload_never_overrides_a_value_the_process_started_with(monkeypatch):
    """review WARN: a systemd drop-in `Environment=MONITOR_PROFILE=...` must keep winning over the .env file."""
    monkeypatch.setattr(mp, '_STARTUP_KEYS', {'MONITOR_PROFILE'})
    monkeypatch.setattr(mp, '_set_from_files', set())
    monkeypatch.setenv('MONITOR_PROFILE', 'tv_app')                       # from the drop-in at start
    files = {'MONITOR_PROFILE': 'counting_cars', 'DEVICE2_MONITOR_PROFILE': 'counting_cars'}
    monkeypatch.setattr(mp, 'read_env_files', lambda key_pattern=None: dict(files))
    mp.reload_profile_env()
    assert os.environ['MONITOR_PROFILE'] == 'tv_app'                      # kept
    assert os.environ['DEVICE2_MONITOR_PROFILE'] == 'counting_cars'       # new since start: picked up
    del files['DEVICE2_MONITOR_PROFILE']
    mp.reload_profile_env()
    assert 'DEVICE2_MONITOR_PROFILE' not in os.environ                    # and dropped again with the file
    monkeypatch.delenv('MONITOR_PROFILE')


def test_an_idle_service_survives_the_log_level_signals(tmp_path):
    """review WARN: pkill -USR1 on an idle monitor killed it (the handler is installed only after the idle phase)."""
    code = textwrap.dedent(f"""
        import os, sys, signal
        sys.path.insert(0, {ROOT!r})
        os.environ.update(MONITOR_PROFILE='counting_cars', STREAM_BASE_PATH={str(tmp_path)!r},
                          DEVICE1_VIDEO_CAPTURE_PATH={str(tmp_path / 'capture1')!r})
        import shared.src.lib.utils.monitor_service as ms
        ms.capture_folders = lambda: ['capture1']
        ms.reload_profile_env = lambda: None
        def sleep(_):
            os.kill(os.getpid(), signal.SIGUSR1); os.kill(os.getpid(), signal.SIGUSR2)
            print('survived'); raise SystemExit(0)
        ms.wait_until_needed('audio', 'vpt-monitor-audio', sleep=sleep)
    """)
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and 'survived' in r.stdout, (r.returncode, r.stderr)
