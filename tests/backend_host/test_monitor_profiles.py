"""Monitor profile manifests and resolution (TASK-90 goal 3)."""
import os
import sys
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor import profiles as P  # noqa: E402
import shared.src.lib.utils.monitor_profile as mp  # noqa: E402
from shared.src.lib.utils.monitor_profile import resolve_monitor_profile  # noqa: E402
from backend_host.src.lib.utils.monitor_profile import get_monitor_profiles  # noqa: E402


def write(tmp_path, name, body):
    (tmp_path / f'{name}.yaml').write_text(textwrap.dedent(body))
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.endswith('_MONITOR_PROFILE') or k == 'MONITOR_PROFILE':
            monkeypatch.delenv(k)


@pytest.fixture
def extra_types():
    return None   # kept for the tests below; coco_detect and hsv_colour are registered types now


COUNTING = """
    name: counting_cars
    services: { img: true, audio: false, subtitle: false }
    img:
      runtime: edge
      analyzers:
        - type: coco_detect
          sample_hz: 2
          classes: [car, truck, bus]
          min_conf: 0.4
        - type: hsv_colour
          attr: colour
      track: { max_gap_s: 2.0, min_iou: 0.3 }
    events:
      car_seen: { attr: label, in: [car, truck, bus] }
    incidents: {}
    kpis:
      - { name: count_per_min, of: car_seen, window_s: 60 }
      - { name: count_by_colour, of: car_seen, group_by: colour, window_s: 600 }
"""


def test_shipped_tv_app_loads():
    prof = P.load_profile('tv_app')
    assert prof.name == 'tv_app'
    assert prof.services.img and prof.services.audio and prof.services.subtitle
    assert [a.type for a in prof.img.analyzers] == ['tv_app']


def test_counting_cars_manifest_validates(tmp_path, extra_types):
    prof = P.load_profile('counting_cars', write(tmp_path, 'counting_cars', COUNTING))
    assert prof.img.analyzers[0].sample_hz == 2
    assert prof.img.analyzers[0].classes == ['car', 'truck', 'bus']   # analyzer keys pass through
    assert prof.events['car_seen'].in_ == ['car', 'truck', 'bus']
    assert not prof.services.audio


def test_unknown_analyzer_type_is_rejected(tmp_path):
    d = write(tmp_path, 'counting_cars', COUNTING.replace('type: coco_detect', 'type: laser_beam'))
    with pytest.raises(P.ProfileError, match="unknown analyzer type"):
        P.load_profile('counting_cars', d)


def test_shipped_counting_cars_loads():
    prof = P.load_profile('counting_cars')
    assert [a.type for a in prof.img.analyzers] == ['coco_detect', 'hsv_colour']
    assert prof.img.analyzers[0].sample_hz == 2
    assert prof.incidents == {}
    assert not (prof.services.audio or prof.services.subtitle)


def bad(tmp_path, extra_types, body, match):
    d = write(tmp_path, 'bad', body)
    with pytest.raises(P.ProfileError, match=match):
        P.load_profile('bad', d)


def test_event_needs_exactly_one_test(tmp_path, extra_types):
    bad(tmp_path, extra_types, COUNTING.replace('counting_cars', 'bad').replace("in: [car, truck, bus]", "in: [car], equals: car"), "exactly one of")
    bad(tmp_path, extra_types, COUNTING.replace('counting_cars', 'bad').replace("{ attr: label, in: [car, truck, bus] }", "{ attr: label }"), "exactly one of")


def test_incident_must_reference_declared_event_or_kpi(tmp_path, extra_types):
    base = COUNTING.replace('counting_cars', 'bad')
    bad(tmp_path, extra_types, base.replace("incidents: {}", "incidents:\n      jam: { event: nope, after_s: 30 }"), "not declared")
    bad(tmp_path, extra_types, base.replace("incidents: {}", "incidents:\n      jam: { kpi: nope, above: 10, window_s: 60 }"), "not declared")


def test_incident_shapes(tmp_path, extra_types):
    base = COUNTING.replace('counting_cars', 'bad')
    ok = base.replace("incidents: {}", "incidents:\n      busy: { kpi: count_per_min, above: 30, window_s: 60 }\n      seen: { event: car_seen, after_s: 30 }")
    d = write(tmp_path, 'bad', ok)
    assert set(P.load_profile('bad', d).incidents) == {'busy', 'seen'}
    bad(tmp_path, extra_types, base.replace("incidents: {}", "incidents:\n      x: { kpi: count_per_min, above: 1, below: 2, window_s: 60 }"), "exactly one of `above`")
    bad(tmp_path, extra_types, base.replace("incidents: {}", "incidents:\n      x: { event: car_seen }"), "needs `after_s`")
    bad(tmp_path, extra_types, base.replace("incidents: {}", "incidents:\n      x: { kpi: count_per_min, above: 1 }"), "needs `window_s`")


def test_kpi_must_reference_declared_event(tmp_path, extra_types):
    bad(tmp_path, extra_types, COUNTING.replace('counting_cars', 'bad').replace("of: car_seen, window_s: 60", "of: ghost, window_s: 60"), "not a declared event")


def test_unknown_keys_and_name_mismatch(tmp_path, extra_types):
    bad(tmp_path, extra_types, COUNTING.replace('counting_cars', 'bad') + "    surprise: 1\n", "surprise")
    d = write(tmp_path, 'other', COUNTING)           # file other.yaml declares counting_cars
    with pytest.raises(P.ProfileError, match="declares name"):
        P.load_profile('other', d)


def test_broken_yaml_and_missing_file(tmp_path):
    d = write(tmp_path, 'bad', "name: [unclosed\n")
    with pytest.raises(P.ProfileError, match="not valid YAML"):
        P.load_profile('bad', d)
    with pytest.raises(P.ProfileError, match="cannot read"):
        P.load_profile('absent', d)


def test_load_or_default_falls_back_to_tv_app(tmp_path):
    d = write(tmp_path, 'bad', "name: [unclosed\n")
    write(tmp_path, 'tv_app', open(os.path.join(P.PROFILES_DIR, 'tv_app.yaml')).read())
    assert P.load_profile_or_default('bad', d).name == 'tv_app'


# ---- resolution ------------------------------------------------------------------------------

def test_resolution_order(monkeypatch):
    assert resolve_monitor_profile(2) == 'tv_app'
    monkeypatch.setenv('MONITOR_PROFILE', 'tv_app')
    assert resolve_monitor_profile(2) == 'tv_app'


def test_device_key_wins_over_host_key(tmp_path, monkeypatch):
    d = str(tmp_path)
    for n in ('tv_app', 'host_one', 'dev_two'):
        (tmp_path / f'{n}.yaml').write_text('name: x\n')
    monkeypatch.setenv('MONITOR_PROFILE', 'host_one')
    monkeypatch.setenv('DEVICE2_MONITOR_PROFILE', 'dev_two')
    assert resolve_monitor_profile(2, d) == 'dev_two'
    assert resolve_monitor_profile(1, d) == 'host_one'
    assert resolve_monitor_profile(None, d) == 'host_one'


def test_unknown_profile_name_logs_and_falls_back(tmp_path, monkeypatch, caplog):
    (tmp_path / 'tv_app.yaml').write_text('name: tv_app\n')
    monkeypatch.setenv('MONITOR_PROFILE', 'counting_carz')
    with caplog.at_level('ERROR'):
        assert resolve_monitor_profile(1, str(tmp_path)) == 'tv_app'
    assert 'counting_carz' in caplog.text
    monkeypatch.setenv('MONITOR_PROFILE', '../etc/passwd')       # never a path
    assert resolve_monitor_profile(1, str(tmp_path)) == 'tv_app'


def test_host_reports_profile_per_device(monkeypatch):
    class Dev:
        def __init__(self, device_id):
            self.device_id = device_id
    assert get_monitor_profiles([Dev('device1'), {'device_id': 'device3'}, Dev('host')]) == {
        'device1': 'tv_app', 'device3': 'tv_app', 'host': 'tv_app'}
    assert get_monitor_profiles(None) == {'host': 'tv_app'}


# ---- the light validator (idle services) must agree with the pydantic loader (review WARN) ----------

BASE = COUNTING.replace('counting_cars', 'bad')
PARITY_CASES = {
    'valid': BASE,
    'unknown analyzer': BASE.replace('type: coco_detect', 'type: laser_beam'),
    'event with both tests': BASE.replace("in: [car, truck, bus]", "in: [car], equals: car"),
    'event with neither': BASE.replace("{ attr: label, in: [car, truck, bus] }", "{ attr: label }"),
    'incident of unknown event': BASE.replace("incidents: {}", "incidents:\n      jam: { event: nope, after_s: 30 }"),
    'incident of unknown kpi': BASE.replace("incidents: {}", "incidents:\n      jam: { kpi: nope, above: 10, window_s: 60 }"),
    'incident above and below': BASE.replace("incidents: {}", "incidents:\n      x: { kpi: count_per_min, above: 1, below: 2, window_s: 60 }"),
    'event incident without after_s': BASE.replace("incidents: {}", "incidents:\n      x: { event: car_seen }"),
    'kpi incident without window': BASE.replace("incidents: {}", "incidents:\n      x: { kpi: count_per_min, above: 1 }"),
    'valid kpi incident': BASE.replace("incidents: {}", "incidents:\n      busy: { kpi: count_per_min, above: 30, window_s: 60 }"),
    'kpi of unknown event': BASE.replace("of: car_seen, window_s: 60", "of: ghost, window_s: 60"),
    'unknown top key': BASE + "    surprise: 1\n",
    'unknown service key': BASE.replace("services: { img: true, audio: false, subtitle: false }", "services: { img: true, video: true }"),
    'track votes and ocsort': BASE.replace("track: { max_gap_s: 2.0, min_iou: 0.3 }", "track: { algo: ocsort, max_gap_s: 2.0, min_iou: 0.3, votes: 3, min_votes: 2 }"),
    'track unknown algo': BASE.replace("track: { max_gap_s: 2.0, min_iou: 0.3 }", "track: { algo: kalman9000 }"),
    'track min_votes above votes': BASE.replace("track: { max_gap_s: 2.0, min_iou: 0.3 }", "track: { votes: 2, min_votes: 3 }"),
    'track unknown key': BASE.replace("track: { max_gap_s: 2.0, min_iou: 0.3 }", "track: { speed: 9 }"),
    'pct_where kpi': BASE.replace("  - { name: count_per_min, of: car_seen, window_s: 60 }", "  - { name: bad_pct, of: car_seen, window_s: 60, pct_where: { attr: colour, in: [red] } }"),
    'pct_where with group_by': BASE.replace("  - { name: count_per_min, of: car_seen, window_s: 60 }", "  - { name: bad_pct, of: car_seen, window_s: 60, group_by: colour, pct_where: { attr: colour, in: [red] } }"),
    'no analyzers': "    name: bad\n    img:\n      analyzers: []\n",
}


@pytest.mark.parametrize('case', sorted(PARITY_CASES))
def test_light_validator_agrees_with_the_loader(tmp_path, case):
    import yaml
    d = write(tmp_path, 'bad', PARITY_CASES[case])
    try:
        P.load_profile('bad', d)
        loader_ok = True
    except P.ProfileError:
        loader_ok = False
    try:
        from shared.src.lib.utils.monitor_profile import validate_manifest_light
        validate_manifest_light(yaml.safe_load(textwrap.dedent(PARITY_CASES[case])), 'bad')
        light_ok = True
    except ValueError:
        light_ok = False
    assert light_ok == loader_ok, f'{case}: loader_ok={loader_ok} light_ok={light_ok}'


def test_an_invalid_manifest_counts_as_tv_app_for_the_idle_services(tmp_path):
    """img falls back to tv_app for such a device; audio and subtitle must then serve it, not skip it."""
    d = write(tmp_path, 'bad', PARITY_CASES['unknown analyzer'])
    assert mp.profile_services('bad', d) == {s: True for s in mp.SERVICES}
    d = write(tmp_path, 'good', BASE.replace('name: bad', 'name: good'))
    assert mp.profile_services('good', d) == {'img': True, 'audio': False, 'subtitle': False, 'archiver': True, 'kpi': True, 'avq': True}


def test_without_pyyaml_tv_app_still_runs_and_other_profiles_fall_back(monkeypatch, caplog):
    monkeypatch.setattr(P, 'yaml', None)
    assert P.load_profile_or_default('tv_app').name == 'tv_app'
    monkeypatch.undo()
    assert P.builtin_tv_app().model_dump() == P.load_profile('tv_app').model_dump()   # same content as tv_app.yaml
    monkeypatch.setattr(P, 'yaml', None)
    assert P.load_profile_or_default('counting_cars').name == 'tv_app'
