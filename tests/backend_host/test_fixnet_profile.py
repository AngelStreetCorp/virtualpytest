"""fixnet (TASK-151): a voice line has no picture, so the profile runs nothing that looks at a screen and keeps
only the KPI scan and the A/V quality score. The manifest, the model default that needs no .env line, the
services that follow, and what vpt-host stops and starts on a modem rack."""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402
import backend_host.src.lib.utils.monitor_profile as hostmp  # noqa: E402

RUN_FFMPEG = os.path.join(ROOT, 'backend_host', 'scripts', 'run_ffmpeg.sh')
PROFILES = os.path.join(ROOT, 'backend_host', 'config', 'monitor', 'profiles')

OFF_FOR_A_LINE = ('img', 'audio', 'subtitle', 'archiver')
KEPT_FOR_A_LINE = ('kpi', 'avq')


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if mp._PROFILE_KEY.match(k):
            monkeypatch.delenv(k)


# ---- the manifest ------------------------------------------------------------------------------

def test_the_profile_runs_no_screen_service_and_keeps_kpi_and_avq():
    services = mp.profile_services('fixnet')
    for s in OFF_FOR_A_LINE:
        assert services[s] is False, s
    for s in KEPT_FOR_A_LINE:
        assert services[s] is True, s
    assert services == {'img': False, 'audio': False, 'subtitle': False,
                        'archiver': False, 'kpi': True, 'avq': True}


def test_the_stream_stays_full_because_kpi_and_avq_read_its_outputs():
    """The opposite of tv_lite / pc: those are `lean` because no KPI and no AVQ read their ffmpeg outputs.
    `lean` drops the 5 fps thumbnails and slows captures to 2 fps; this profile runs both readers, so it must
    not starve them."""
    assert mp.profile_stream_mode('fixnet') == 'full'
    src = open(os.path.join(PROFILES, 'fixnet.yaml')).read()
    assert not re.search(r'^stream:\s*lean', src, re.M)


def test_both_validators_accept_the_manifest():
    from monitor.profiles import load_profile
    prof = load_profile('fixnet')
    assert prof.services.img is False and prof.services.archiver is False
    assert prof.services.kpi is True and prof.services.avq is True
    assert prof.stream == 'full'
    assert load_profile('tv_app').services.img is True


def test_a_typo_in_env_never_stops_a_device():
    assert mp.resolve_monitor_profile(1, env={'MONITOR_PROFILE': 'fixnt'}) == 'tv_app'
    assert mp.resolve_monitor_profile(1, env={'MONITOR_PROFILE': '../fixnet'}) == 'tv_app'


# ---- resolution: a modem needs no .env line ------------------------------------------------------

def test_a_voice_modem_resolves_to_fixnet_without_any_env_line():
    assert mp.MODEL_PROFILES['fx_dongle'] == 'fixnet'
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'fx_dongle'}) == 'fixnet'
    assert mp.resolve_monitor_profile(3, env={'DEVICE3_MODEL': 'fx_dongle'}) == 'fixnet'


def test_an_explicit_profile_still_wins_over_the_model_default():
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'fx_dongle',
                                               'DEVICE1_MONITOR_PROFILE': 'tv_app'}) == 'tv_app'
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'fx_dongle',
                                               'MONITOR_PROFILE': 'pc'}) == 'pc'


def test_the_other_model_defaults_are_untouched():
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'tello'}) == 'drone'
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'android_mobile'}) == 'mobile'
    assert mp.resolve_monitor_profile(1, env={'DEVICE1_MODEL': 'android_tv'}) == 'tv_app'


def test_the_settings_picker_describes_the_profile():
    entry = next(p for p in hostmp.list_profiles(PROFILES) if p['name'] == 'fixnet')
    assert entry['usable'] is True and entry['title'] == 'Voice line'
    assert entry['services']['img'] is False and entry['services']['avq'] is True
    assert entry['description'] and entry['cost']


# ---- which service each call site decides --------------------------------------------------------

def test_folders_for_each_service_on_a_modem_rack(monkeypatch):
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, 'get_device_info_from_capture_folder',
                        lambda f: {'device_index': int(f[-1])})
    env = {'DEVICE1_MODEL': 'fx_dongle', 'DEVICE2_MODEL': 'fx_dongle'}
    folders = ['capture1', 'capture2']
    for service in OFF_FOR_A_LINE:
        assert mp.folders_needing_service(service, folders, env) == [], service
    for service in KEPT_FOR_A_LINE:
        assert mp.folders_needing_service(service, folders, env) == folders, service


def test_one_modem_beside_a_monitored_device_keeps_the_screen_services_for_the_other(monkeypatch):
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, 'get_device_info_from_capture_folder',
                        lambda f: {'device_index': int(f[-1])})
    env = {'DEVICE1_MODEL': 'fx_dongle', 'DEVICE2_MODEL': 'android_tv'}
    folders = ['capture1', 'capture2']
    for service in OFF_FOR_A_LINE:
        assert mp.folders_needing_service(service, folders, env) == ['capture2'], service
    for service in KEPT_FOR_A_LINE:
        assert mp.folders_needing_service(service, folders, env) == folders, service


# ---- vpt-host -----------------------------------------------------------------------------------

@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr(hostmp, 'STATE_FILE', str(tmp_path / 'applied.json'))
    env = {'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'}
    monkeypatch.setattr(hostmp, 'read_env_files', lambda pattern=None: dict(env))
    stopped, started = [], []
    return env, stopped, started, (lambda u: stopped.append(u) or True), (lambda u: started.append(u) or True)


def test_a_modem_rack_stops_the_four_screen_services_and_keeps_kpi_and_avq(host):
    env, stopped, started, stop, start = host
    env['DEVICE1_MODEL'] = 'fx_dongle'
    env['DEVICE2_MODEL'] = 'fx_dongle'
    hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    # vpt-companion is stopped too: it is opt-in per device and no modem asks for it.
    assert sorted(stopped) == ['vpt-archiver', 'vpt-companion', 'vpt-monitor-audio',
                               'vpt-monitor-img', 'vpt-monitor-subtitle']
    assert 'vpt-kpi' not in stopped and 'vpt-avq' not in stopped


def test_the_applied_record_is_what_the_host_status_reads_as_not_needed(host):
    """BUG-0729: the four stopped units must read as "no device needs this", not as a failed critical service.
    vpt-kpi and vpt-avq must stay OUT of that list, or a running service would be downgraded too."""
    env, stopped, started, stop, start = host
    env['DEVICE1_MODEL'] = 'fx_dongle'
    env['DEVICE2_MODEL'] = 'fx_dongle'
    hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    not_needed = hostmp.units_not_needed()
    for unit in ('vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle', 'vpt-archiver'):
        assert unit in not_needed, unit
    for unit in ('vpt-kpi', 'vpt-avq', 'vpt-host', 'vpt-stream'):
        assert unit not in not_needed, unit


def test_a_stopped_kpi_is_not_absorbed_into_the_not_needed_list_on_a_mixed_host(host):
    env, stopped, started, stop, start = host
    env['DEVICE1_MODEL'] = 'fx_dongle'
    env['DEVICE2_MODEL'] = 'fx_dongle'
    hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    env['DEVICE2_MODEL'] = 'android_tv'
    hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    assert 'vpt-monitor-img' not in hostmp.units_not_needed()      # device2 needs it again
    assert 'vpt-avq' not in hostmp.units_not_needed()


def test_no_device_switching_to_fixnet_never_restarts_the_stream(host):
    """stream stays `full`, so the ffmpeg graph is untouched: no video drop on the rack."""
    env, stopped, started, stop, start = host
    hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    env['DEVICE1_MODEL'] = 'fx_dongle'
    out = hostmp.apply_monitor_profiles(lambda u: True, is_active=lambda u: True, stop=stop, start=start)
    assert 'vpt-stream' not in out['restarted']
    assert hostmp._desired_state()['lean'] == []


# ---- run_ffmpeg.sh ------------------------------------------------------------------------------

def _bash_functions(*names):
    """The text of the named top-level shell functions, to run them without the rest of the script."""
    src = open(RUN_FFMPEG).read()
    out = []
    for n in names:
        m = re.search(r'^%s\(\) \{\n.*?^\}\n' % re.escape(n), src, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return '\n'.join(out)


def _mode(index, env):
    script = ('MONITOR_PROFILES_DIR=%s\n' % PROFILES) + _bash_functions('stream_mode_for') + '\nstream_mode_for %s\n' % index
    full_env = {k: v for k, v in os.environ.items() if not mp._PROFILE_KEY.match(k)}
    full_env.update(env)
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=full_env).stdout.strip()


def test_run_ffmpeg_streams_a_fixnet_device_full():
    assert _mode('device1', {'DEVICE1_MONITOR_PROFILE': 'fixnet'}) == 'full'
    assert _mode('host', {'MONITOR_PROFILE': 'fixnet'}) == 'full'
    assert _mode('device1', {}) == 'full'