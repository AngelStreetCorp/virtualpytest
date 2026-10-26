"""drone profile (TASK-90 goal 12): the telemetry bridge, its staleness, the `telemetry` analyzer, the vehicle's events and incidents,
the manifest pieces (`stat` KPIs, `ui.hud`, `burn_in`), and the controller writing the file. No hardware: the Tello simulator on loopback."""
import copy
import json
import os
import socket
import sys
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import yaml  # noqa: E402

from monitor.analyzers import build_analyzers  # noqa: E402
from monitor.analyzers.telemetry import TelemetryAnalyzer, compact  # noqa: E402
from monitor.profiles import Profile, ProfileError, load_profile  # noqa: E402
from shared.src.lib.drone import telemetry_status as ts  # noqa: E402
from shared.src.lib.utils.monitor_profile import PROFILES_DIR, validate_manifest_light  # noqa: E402

T0 = 1_000_000.0


def state(**kw):
    base = {'bat': 87, 'templ': 55, 'temph': 62, 'h': 120, 'vgx': 3, 'vgy': 4, 'vgz': 0, 'yaw': 12, 'time': 95}
    base.update(kw)
    return base


def status(now=T0, flying=True, **kw):
    return ts.build_status(state(**kw), {'x': 100.0, 'y': 200.0}, flying=flying, now=now)


@pytest.fixture
def analyzer(tmp_path):
    profile = load_profile('drone')
    a = TelemetryAnalyzer(None, profile, metadata_dir_fn=lambda f: str(tmp_path / f))
    a.register_device('capture1')
    return a


def feed(a, st, age, now):
    return a.process_status('capture1', st, age, now)


# ---- the bridge ---------------------------------------------------------------------------------

def test_build_status_units_and_no_gps_for_a_tello():
    st = status()
    assert st['battery'] == 87 and st['temp_high'] == 62 and st['temp_low'] == 55
    assert st['height_cm'] == 120 and st['speed_ms'] == 0.5          # (3,4,0) dm/s = 5 dm/s = 0.5 m/s
    assert st['flight_time_s'] == 95 and st['flying'] is True
    assert st['lat'] is None and st['lon'] is None and st['gps_fix'] is None
    assert st['pose'] == {'x': 100.0, 'y': 200.0}
    gps = ts.build_status(state(), None, gps={'lat': 47.37, 'lon': 8.54, 'fix': 3})
    assert (gps['lat'], gps['lon'], gps['gps_fix']) == (47.37, 8.54, 3) and gps['pose'] is None


def test_the_file_is_written_whole_and_read_back_with_its_age(tmp_path):
    ts.write_atomic(str(tmp_path / ts.STATUS_FILE), json.dumps(status()))
    assert not [f for f in os.listdir(tmp_path) if f.endswith('.tmp')]
    data, age = ts.read_status(str(tmp_path))
    assert data['battery'] == 87 and ts.is_fresh(age)
    os.utime(tmp_path / ts.STATUS_FILE, (time.time() - 30, time.time() - 30))
    data, age = ts.read_status(str(tmp_path))
    assert data['battery'] == 87 and age >= 29 and not ts.is_fresh(age)     # old file: the reader says "no telemetry"


def test_a_missing_or_half_written_file_is_nothing(tmp_path):
    assert ts.read_status(str(tmp_path)) == (None, None)
    (tmp_path / ts.STATUS_FILE).write_text('{"battery": 8')
    assert ts.read_status(str(tmp_path)) == (None, None)


def test_the_writer_publishes_at_most_five_times_a_second_and_a_last_record_on_stop(tmp_path):
    calls = []

    def sample():
        calls.append(time.time())
        return status(now=time.time(), flying=True)

    w = ts.TelemetryStatusWriter(str(tmp_path), sample, burn_in=True, interval_s=0.0)   # a faster ask is clamped to 5 Hz
    w.start()
    time.sleep(1.05)
    w.stop(final=lambda st: dict(st, flying=False))
    assert 4 <= len(calls) <= 8
    data, _ = ts.read_status(str(tmp_path))
    assert data['flying'] is False                                       # the last record: landed, not lost
    assert (tmp_path / ts.HUD_FILE).read_text().startswith('BAT 87%')


def test_nothing_fresh_leaves_the_status_alone_and_the_hud_says_so(tmp_path):
    w = ts.TelemetryStatusWriter(str(tmp_path), lambda: None, burn_in=True)
    w.tick()
    assert not (tmp_path / ts.STATUS_FILE).exists()
    assert (tmp_path / ts.HUD_FILE).read_text() == ts.NO_TELEMETRY_TEXT


def test_hud_text_has_a_gps_line_only_when_a_fix_exists():
    assert 'GPS' not in ts.hud_text(status())
    with_fix = ts.build_status(state(), None, gps={'lat': 47.3769, 'lon': 8.5417, 'fix': 3})
    assert ts.hud_text(status()) == 'BAT 87%  62C  ALT 1.2m  0.5m/s'
    assert ts.hud_text(with_fix) == 'BAT 87%  62C  ALT 1.2m  0.5m/s  47.37690,8.54170'
    assert '\n' not in ts.hud_text(with_fix)       # one line: ffmpeg 8's drawtext draws a line break as a missing-glyph box
    assert ts.hud_text(None) == ts.NO_TELEMETRY_TEXT


def test_burn_in_follows_the_device_variable_then_the_manifest(tmp_path):
    (tmp_path / 'on.yaml').write_text('name: on\nburn_in: true\n')
    (tmp_path / 'off.yaml').write_text('name: off\n')
    env = {'MONITOR_PROFILE': 'on'}
    assert ts.telemetry_burn_in(1, env, str(tmp_path)) is True
    assert ts.telemetry_burn_in(1, dict(env, DEVICE1_TELEMETRY_BURN_IN='0'), str(tmp_path)) is False   # the device variable wins
    assert ts.telemetry_burn_in(1, {'MONITOR_PROFILE': 'off', 'DEVICE1_TELEMETRY_BURN_IN': 'true'}, str(tmp_path)) is True
    assert ts.telemetry_burn_in(2, {'MONITOR_PROFILE': 'off'}, str(tmp_path)) is False
    assert ts.telemetry_burn_in(None, {}, str(tmp_path)) is False


# ---- the analyzer -------------------------------------------------------------------------------

def test_the_frame_carries_the_reading_compactly(analyzer):
    r = feed(analyzer, status(), 0.3, T0)
    t = r['telemetry']
    assert t == {'ok': True, 'age': 0.3, 'bat': 87, 'temp': 62, 'alt': 1.2, 'spd': 0.5, 'yaw': 12, 'ft': 95, 'fly': True, 'x': 1.0, 'y': 2.0}
    assert 'lat' not in t and 'lon' not in t                              # no GPS: the keys are not there
    assert len(json.dumps(t)) < 130
    assert r['observations'] == [] and r['ui']['title'] == 'Drone'
    # it is what the chunk entry keeps, and what the next frames get through frame_record
    assert analyzer.chunk_fields(r)['telemetry'] == t


def test_gps_keys_appear_when_a_fix_comes():
    st = ts.build_status(state(), None, flying=True, gps={'lat': 47.1, 'lon': 8.2, 'fix': 3}, now=T0)
    t = compact(st, 0.1)
    assert (t['lat'], t['lon'], t['fix']) == (47.1, 8.2, 3)


def test_a_stale_reading_is_no_telemetry(analyzer):
    r = feed(analyzer, status(flying=False), 12.0, T0)
    assert r['telemetry'] == {'ok': False, 'age': 12.0}
    assert feed(analyzer, None, None, T0)['telemetry'] == {'ok': False}
    assert 'telemetry_lost' not in r['events']                            # it never flew while we watched


def test_flying_event_and_flight_time(analyzer):
    r = feed(analyzer, status(), 0.1, T0)
    assert r['events']['flying']['duration_ms'] == 0
    r = feed(analyzer, status(), 0.1, T0 + 5)
    assert r['events']['flying']['duration_ms'] == 5000
    r = feed(analyzer, status(flying=False), 0.1, T0 + 6)
    assert 'flying' not in r['events']


def test_battery_low_only_while_flying_and_at_the_threshold(analyzer):
    assert 'battery_low' not in feed(analyzer, status(bat=21), 0.1, T0)['events']
    assert 'battery_low' in feed(analyzer, status(bat=20), 0.1, T0 + 1)['events']
    assert 'battery_low' not in feed(analyzer, status(flying=False, bat=15), 0.1, T0 + 2)['events']   # parked on 15 %: no alert


def test_battery_low_becomes_an_incident_after_its_delay(analyzer):
    feed(analyzer, status(bat=18), 0.1, T0)
    r = feed(analyzer, status(bat=18), 0.1, T0 + 2)
    assert r['incidents']['battery_low']['active'] is False               # after_s 5
    r = feed(analyzer, status(bat=18), 0.1, T0 + 6)
    assert r['incidents']['battery_low'] == {'active': True, 'value': 6.0}
    r = feed(analyzer, status(bat=60), 0.1, T0 + 7)
    assert r['incidents']['battery_low']['active'] is False


def test_temp_high(analyzer):
    assert 'temp_high' not in feed(analyzer, status(temph=79), 0.1, T0)['events']
    feed(analyzer, status(temph=85), 0.1, T0 + 1)
    r = feed(analyzer, status(temph=85), 0.1, T0 + 12)
    assert r['incidents']['temp_high']['active'] is True


def test_telemetry_lost_only_when_it_goes_quiet_in_the_air(analyzer):
    feed(analyzer, status(), 0.1, T0)
    r = feed(analyzer, status(), 8.0, T0 + 8)                              # stale while the last reading said flying
    assert r['telemetry']['ok'] is False
    assert r['incidents']['telemetry_lost']['active'] is True              # after_s 0
    r = feed(analyzer, status(now=T0 + 9), 0.1, T0 + 9)                    # it comes back
    assert r['incidents']['telemetry_lost']['active'] is False


def test_a_clean_landing_then_silence_is_not_lost(analyzer):
    feed(analyzer, status(), 0.1, T0)
    feed(analyzer, status(flying=False), 0.1, T0 + 10)                     # the controller's last record: landed
    r = feed(analyzer, status(flying=False), 20.0, T0 + 40)
    assert r['telemetry']['ok'] is False and 'telemetry_lost' not in r['events']


def test_yesterdays_file_is_not_a_lost_drone(analyzer):
    r = feed(analyzer, status(), 86400.0, T0)                              # monitor starts, the file says flying but is a day old
    assert 'telemetry_lost' not in r['events']


def test_a_monitor_restart_just_after_the_link_died_reports_lost(analyzer):
    r = feed(analyzer, status(), 30.0, T0)                                 # the file says flying and went quiet 30 s ago
    assert r['events']['telemetry_lost']


def test_statistics_are_per_flight(analyzer):
    feed(analyzer, status(bat=90, h=100, time=10), 0.1, T0)
    feed(analyzer, status(bat=70, h=350, time=50), 0.1, T0 + 40)
    r = feed(analyzer, status(bat=60, h=200, time=80), 0.1, T0 + 70)
    assert r['kpis'] == {'flight_time': 80, 'min_battery': 60, 'max_altitude': 3.5}
    feed(analyzer, status(flying=False, bat=60, h=0, time=80), 0.1, T0 + 71)    # landed: the summary stays
    r = feed(analyzer, status(flying=False, bat=55, h=0, time=80), 0.1, T0 + 80)
    assert r['kpis']['max_altitude'] == 3.5
    feed(analyzer, status(bat=95, h=50, time=3), 0.1, T0 + 100)                  # next takeoff: the numbers start again
    r = feed(analyzer, status(bat=94, h=60, time=5), 0.1, T0 + 101)
    assert r['kpis'] == {'flight_time': 5, 'min_battery': 94, 'max_altitude': 0.6}


def test_the_newest_result_is_what_frames_get(analyzer):
    class Ctx:
        capture_folder, filename, timestamp, frame_path = 'capture1', 'capture_1.jpg', T0, 'x.jpg'
    feed(analyzer, status(bat=18), 0.1, T0)
    feed(analyzer, status(bat=18), 0.1, T0 + 6)
    rec = analyzer.frame_record(Ctx, {}, {})
    assert rec['telemetry']['bat'] == 18 and rec['incidents']['battery_low']['active'] is True
    assert analyzer.analyze(Ctx)['incidents']['battery_low']['active'] is True      # what the incident manager is handed


def test_process_reads_the_file_the_bridge_wrote(analyzer, tmp_path):
    folder = tmp_path / 'capture1'
    folder.mkdir()
    ts.write_atomic(str(folder / ts.STATUS_FILE), json.dumps(ts.build_status(state(), None, flying=True, now=time.time())))
    analyzer.process('capture1', 'frame.jpg', time.time())
    assert analyzer._latest['capture1']['telemetry']['bat'] == 87


# ---- the manifest -------------------------------------------------------------------------------

def raw_drone():
    with open(os.path.join(PROFILES_DIR, 'drone.yaml')) as f:
        return yaml.safe_load(f)


def both(raw):
    """(pydantic accepts, light validator accepts)"""
    try:
        Profile.model_validate(raw)
        a = True
    except Exception:
        a = False
    try:
        validate_manifest_light(raw, raw['name'])
        b = True
    except ValueError:
        b = False
    return a, b


def test_the_shipped_manifest_loads_and_builds_the_telemetry_analyzer():
    p = load_profile('drone')
    assert p.services.img and not p.services.audio and p.burn_in is False
    assert isinstance(build_analyzers(None, p)[0], TelemetryAnalyzer)
    assert [i.key for i in p.ui.hud] == ['bat', 'temp', 'alt', 'spd', 'ft', 'lat']
    assert both(raw_drone()) == (True, True)


def mutate(fn):
    raw = copy.deepcopy(raw_drone())
    fn(raw)
    return raw


@pytest.mark.parametrize('fn', [
    lambda r: r['kpis'].append({'name': 'x', 'stat': {'field': 'bat', 'fn': 'avg'}}),                  # unknown fn
    lambda r: r['kpis'].append({'name': 'x', 'of': 'flying', 'window_s': 60, 'stat': {'field': 'bat', 'fn': 'min'}}),   # stat takes no event
    lambda r: r['kpis'].append({'name': 'x', 'of': 'flying'}),                                         # no window
    lambda r: r['incidents'].update(low={'kpi': 'min_battery', 'below': 20, 'window_s': 60}),          # incident on a statistic
    lambda r: r['ui']['hud'].append({'key': 'lat', 'label': 'GPS', 'format': 'latlon'}),               # latlon needs key2
    lambda r: r['ui']['hud'].append({'key': 'a', 'label': 'A', 'key2': 'b'}),                          # key2 only with latlon
    lambda r: r['ui']['hud'].append({'key': 'a', 'label': 'A', 'format': 'sparkle'}),
    lambda r: r['ui'].update(hud=[]),
    lambda r: r.update(burn_in='sometimes'),
])
def test_bad_manifests_are_refused_by_both_validators(fn):
    assert both(mutate(fn)) == (False, False)


def test_burn_in_true_is_accepted_by_both():
    assert both(mutate(lambda r: r.update(burn_in=True))) == (True, True)


def test_the_profile_loads_through_the_loader_error_path(tmp_path):
    (tmp_path / 'drone.yaml').write_text('name: drone\nimg: {analyzers: [{type: telemetry}]}\nkpis: [{name: a}]\n')
    with pytest.raises(ProfileError):
        load_profile('drone', str(tmp_path))


# ---- the controller writes the file ---------------------------------------------------------------

def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_the_tello_controller_publishes_while_linked_and_says_landed_when_released(tmp_path):
    from backend_host.src.controllers.remote.tello import TelloRemoteController
    from shared.src.lib.drone.sim.tello_sim import TelloSim
    from shared.src.lib.drone.sim.world import Pose, default_room

    state_port = _free_udp_port()
    cmd_port = _free_udp_port()
    sim = TelloSim(default_room(), 3, '127.0.0.1', cmd_port=cmd_port, state_port=state_port, video_port=_free_udp_port(), drift=0.0, seed=1,
                   time_scale=8.0, start_pose=Pose(100, 100, 0, 0))
    sim.start()
    ctrl = TelloRemoteController(tello_ip='127.0.0.1', cmd_port=cmd_port, state_port=state_port, local_ip='127.0.0.1', local_cmd_port=_free_udp_port(),
                                 name='t3', telemetry_status_dir=str(tmp_path), device_id='device3')
    try:
        ctrl.connect()
        assert ctrl.execute_command('takeoff')['success'] is True
        deadline = time.time() + 5
        data = None
        while time.time() < deadline:
            data, age = ts.read_status(str(tmp_path))
            if data and data['flying']:
                break
            time.sleep(0.1)
        assert data and data['flying'] is True and data['battery'] is not None and data['source'] == 'tello'
        assert data['lat'] is None                                             # a Tello has no GPS
        assert ts.is_fresh(age)
        assert ctrl.execute_command('land')['success'] is True
    finally:
        ctrl.disconnect()
        sim.stop()
    data, _ = ts.read_status(str(tmp_path))
    assert data['flying'] is False                                             # the last record after a clean landing
    assert not (tmp_path / ts.HUD_FILE).exists()                               # burn-in is off unless asked for


def test_the_bridge_is_off_when_the_device_has_no_capture_folder():
    from backend_host.src.controllers.remote.tello import TelloRemoteController
    c = TelloRemoteController(tello_ip='127.0.0.1', name='t', device_id='')
    assert c._status_dir() is None
