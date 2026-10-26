from backend_host.src.lib.utils import monitor_profile as mp

ALL = {s: ['capture1'] for s in mp.SERVICES}
NONE = {s: [] for s in mp.SERVICES}


def test_stops_unneeded_and_keeps_core():
    d = {'services': {**ALL, 'kpi': [], 'avq': []}, 'companion': []}
    r = mp.units_to_stop_start({'services': ALL, 'companion': []}, d)
    assert set(r['stop']) == {'vpt-kpi', 'vpt-avq', 'vpt-companion'}
    assert not {'vpt-stream', 'vpt-host'} & set(r['stop'])


def test_starts_only_what_was_unneeded_before():
    prev = {'services': {**ALL, 'audio': []}, 'companion': ['device1']}
    r = mp.units_to_stop_start(prev, {'services': ALL, 'companion': ['device1']})
    assert r == {'stop': [], 'start': ['vpt-monitor-audio']}


def test_first_run_and_old_record_never_start():
    assert mp.units_to_stop_start(None, {'services': ALL, 'companion': []})['start'] == []
    assert mp.units_to_stop_start({'services': ALL}, {'services': ALL, 'companion': ['device1']})['start'] == []


def test_apply_calls_stop_only_for_active():
    calls = []
    d = {'services': {**ALL, 'kpi': []}, 'companion': []}
    out = mp._stop_unneeded(None, d, lambda u: calls.append(u) or True, lambda u: u != 'vpt-companion')
    assert 'vpt-kpi' in out and 'vpt-companion' not in out
