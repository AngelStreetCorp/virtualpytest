"""
Monitoring > Analytics — the reshaping and the cache.

These are pure unit tests: the six aggregates are exercised against fixture rows, not
a live database, so they run anywhere. The views themselves are verified in SQL (see
setup/db/schema/048_analytics_views.sql) and through the live checks in the task doc.

What is worth pinning here is the logic that is easy to get quietly wrong:
  - top-N truncation must not lose the tail's total
  - 'down' must be reachable (a device that stopped reporting)
  - Overview must never touch the expensive availability rollup
  - stale-while-revalidate must serve stale instead of blocking, and must not drop a
    good value when a refresh fails
"""

import sys
import time
from pathlib import Path

import pytest

# Pure unit tests: no live server, no database. conftest's autouse probe skips
# anything unmarked when the backend is unreachable, which would have turned this
# whole file into a wall of "skipped" that reads like success.
pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from shared.src.lib.database import analytics_db as A  # noqa: E402
from backend_server.src.lib.utils.section_cache import SectionCache  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — shaped exactly like the views return
# ---------------------------------------------------------------------------

DEVICE_ROWS = [
    {'host_name': 'vpt-pi1', 'device_id': 'device1', 'device_name': 'S21x',
     'device_model': 'android_mobile', 'ffmpeg_status': 'active',
     'monitor_status': 'active', 'status': 'up'},
    {'host_name': 'vpt-pi1', 'device_id': 'device2', 'device_name': 'mi',
     'device_model': 'android_tv', 'ffmpeg_status': 'active',
     'monitor_status': 'active', 'status': 'up'},
    {'host_name': 'host-clone-1', 'device_id': 'device2', 'device_name': 'Phone slot 1',
     'device_model': 'phone_agent', 'ffmpeg_status': 'active',
     'monitor_status': 'stuck', 'status': 'issue'},
    {'host_name': 'labox-web', 'device_id': 'host', 'device_name': 'labox-web_Host',
     'device_model': None, 'ffmpeg_status': 'stopped',
     'monitor_status': 'stopped', 'status': 'down'},
]

INCIDENT_ROWS = [
    {'day': '2026-09-16', 'severity': 'critical', 'component': 'ffmpeg',
     'host_name': 'vpt-pi1', 'device_name': 'mi', 'status': 'resolved',
     'incidents': 32, 'resolved': 32, 'avg_duration_minutes': 100.0},
    {'day': '2026-09-16', 'severity': 'high', 'component': 'monitor',
     'host_name': 'vpt-pi1', 'device_name': 'S21x', 'status': 'open',
     'incidents': 161, 'resolved': 0, 'avg_duration_minutes': None},
    {'day': '2026-09-17', 'severity': 'critical', 'component': 'ffmpeg',
     'host_name': 'vpt-pi3', 'device_name': 'stb4', 'status': 'resolved',
     'incidents': 5, 'resolved': 5, 'avg_duration_minutes': 200.0},
]

ALERT_ROWS = [
    {'day': '2026-09-16', 'incident_type': 'freeze', 'status': 'resolved',
     'host_name': 'vpt-pi1', 'device_name': 'stb4', 'alerts': 512,
     'checked': 0, 'discarded': 0},
    {'day': '2026-09-17', 'incident_type': 'freeze', 'status': 'active',
     'host_name': 'vpt-pi1', 'device_name': 'stb4', 'alerts': 8,
     'checked': 0, 'discarded': 0},
    {'day': '2026-09-17', 'incident_type': 'audio_loss', 'status': 'active',
     'host_name': 'vpt-pi3', 'device_name': 'mi', 'alerts': 4,
     'checked': 2, 'discarded': 1},
]

AVAIL_ROWS = [
    {'day': '2026-09-17', 'host_name': 'host-clone-1', 'device_id': 'device2',
     'device_name': 'Phone slot 1', 'total_minutes': 1440, 'healthy_minutes': 98,
     'availability_percent': 6.8},
    {'day': '2026-09-17', 'host_name': 'vpt-pi1', 'device_id': 'device2',
     'device_name': 'mi', 'total_minutes': 1440, 'healthy_minutes': 1437,
     'availability_percent': 99.8},
    {'day': '2026-09-16', 'host_name': 'vpt-pi1', 'device_id': 'device2',
     'device_name': 'mi', 'total_minutes': 1440, 'healthy_minutes': 1440,
     'availability_percent': 100.0},
]

HOST_ROWS = [
    {'host_name': 'vpt-pi1', 'server_name': None, 'cpu_percent': 45.0,
     'memory_percent': 29.0, 'disk_percent': 47.0, 'uptime_days': 148.7,
     'cpu_temperature_celsius': 64.0, 'reachability': 'reporting'},
    {'host_name': 'labox-dongle', 'server_name': 'Awesomation', 'cpu_percent': 77.0,
     'memory_percent': 50.0, 'disk_percent': 90.0, 'uptime_days': 2.8,
     'cpu_temperature_celsius': None, 'reachability': 'silent'},
]

VIEW_FIXTURES = {
    'analytics_device_status': DEVICE_ROWS,
    'analytics_host_status': HOST_ROWS,
    'analytics_incidents_daily': INCIDENT_ROWS,
    'analytics_alerts_daily': ALERT_ROWS,
    'analytics_device_availability_daily': AVAIL_ROWS,
}


@pytest.fixture
def views(monkeypatch):
    """Serve fixture rows for every view, and record which ones were read."""
    read = []

    def fake_rows(view, limit=20000):
        read.append(view)
        return VIEW_FIXTURES.get(view, [])

    monkeypatch.setattr(A, '_rows', fake_rows)
    return read


# ---------------------------------------------------------------------------
# top-N
# ---------------------------------------------------------------------------

def test_top_n_keeps_the_tail_total():
    """Truncating to ten bars must not silently lose the other values."""
    pairs = {f'device{i}': i for i in range(1, 16)}   # 15 devices, sum 120
    out = A._top_n(pairs, n=10)

    assert len(out) == 11, "ten bars plus one 'others' row"
    assert out[-1]['is_others'] is True
    assert sum(r['value'] for r in out) == sum(pairs.values()) == 120


def test_top_n_no_others_row_when_it_fits():
    out = A._top_n({'a': 3, 'b': 1}, n=10)
    assert len(out) == 2
    assert not any(r.get('is_others') for r in out)


def test_top_n_is_ordered_biggest_first():
    out = A._top_n({'small': 1, 'big': 99, 'mid': 50}, n=10)
    assert [r['name'] for r in out] == ['big', 'mid', 'small']


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def test_device_status_counts_all_three_states(views):
    """'issue' and 'down' both have to be reachable — a fleet is not just up/not-up."""
    out = A.get_device_status()
    assert out['counts'] == {'up': 2, 'issue': 1, 'down': 1}
    assert out['total'] == 4


def test_device_model_missing_becomes_unknown_not_dropped(views):
    out = A.get_device_status()
    names = {r['name'] for r in out['by_model']}
    assert 'unknown' in names, "a device with no model must still be counted"
    assert sum(r['value'] for r in out['by_model']) == 4


def test_devices_section_picks_the_latest_day_and_sorts_worst_first(views):
    out = A.get_devices_section()
    assert out['availability_day'] == '2026-09-17'
    assert [r['name'] for r in out['availability_worst']] == ['Phone slot 1', 'mi']
    assert out['availability_worst'][0]['value'] == 6.8


def test_devices_availability_timeline_is_fleet_wide_per_day(views):
    out = A.get_devices_section()
    by_day = {r['day']: r['availability_percent'] for r in out['availability_timeline']}
    # 2026-09-17: (98 + 1437) / 2880 = 53.3%
    assert by_day['2026-09-17'] == pytest.approx(53.3, abs=0.1)
    assert by_day['2026-09-16'] == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Overview — the performance contract
# ---------------------------------------------------------------------------

def test_overview_never_reads_the_expensive_rollup(views, monkeypatch):
    """The whole point of the tabbed page: opening it must not pay for the Devices tab.

    analytics_device_availability_daily is the 1382 ms aggregate. If this test ever
    fails, the landing tab got slow and the tab split stopped earning its keep.
    """
    monkeypatch.setattr(A, 'get_kpi_section',
                        lambda team_id=None, days=30: {'pass_rate': 82.0, 'timeline': [],
                                                       'total_runs': 100})
    A.get_overview_section(team_id=None)
    assert 'analytics_device_availability_daily' not in views


def test_overview_reads_the_incidents_figure_it_is_given(views, monkeypatch):
    """The Overview tile takes the figure the caller hands it (BUG-0788).

    The Overview tab and the Incidents tab show the same open-incident count. They
    used to compute it twice, on two different cache clocks, so the two tabs could
    disagree for minutes (the Overview recomputed every 30 s, the Incidents tab
    served a value up to five minutes old).
    """
    monkeypatch.setattr(A, 'get_kpi_section',
                        lambda team_id=None, days=30: {'pass_rate': 82.0, 'timeline': [],
                                                       'total_runs': 100})
    incidents = A.get_incidents_section(days=14)
    tiles = A.get_overview_section(team_id=None, incidents=incidents)['tiles']
    assert tiles['incidents_open'] == incidents['open']


def test_the_overview_loader_takes_the_figure_from_the_incidents_cache(views, monkeypatch):
    """The Overview tile and the Incidents tab read one cache entry, so one number."""
    monkeypatch.setattr(A, 'get_kpi_section',
                        lambda team_id=None, days=30: {'pass_rate': 82.0, 'timeline': [],
                                                       'total_runs': 100})
    from backend_server.src.routes import server_analytics_routes as routes

    asked = []

    def fake_get(section, team_id=None):
        asked.append(section)
        return {'open': 42, 'timeline': [], 'severities': []}, 'fresh'

    monkeypatch.setattr(routes.analytics_cache, 'get', fake_get)
    tiles = routes._overview_loader('team-1')['tiles']
    assert tiles['incidents_open'] == 42
    assert asked == ['incidents'], "the Overview must read the incidents cache, not the database"


def test_the_overview_response_carries_the_incidents_cache_figure(monkeypatch):
    """The Overview tile and the Incidents tab read one cache entry (BUG-0788).

    The Overview payload is cached on its own clock, so the copy of the figure it
    holds can be a pre-warm pass behind the incidents entry. The route reads the
    figure from the incidents cache at request time, so the two tabs cannot
    disagree — not even for the half hour between two pre-warm passes.
    """
    from flask import Flask

    from backend_server.src.routes import server_analytics_routes as routes

    flask_app = Flask(__name__)
    monkeypatch.setattr(routes, 'check_supabase', lambda: None)

    cache = SectionCache()
    cache.register('overview', lambda team_id: {'tiles': {'incidents_open': 999}}, fresh=60, stale=600)
    cache.register('incidents', lambda team_id: {'open': 42}, fresh=60, stale=600)
    monkeypatch.setattr(routes, 'analytics_cache', cache)

    with flask_app.test_request_context('/server/analytics/overview'):
        body = routes.get_section('overview').get_json()

    assert body['data']['tiles']['incidents_open'] == 42


def test_overview_tiles_carry_every_headline_number(views, monkeypatch):
    monkeypatch.setattr(A, 'get_kpi_section',
                        lambda team_id=None, days=30: {'pass_rate': 82.0, 'timeline': [],
                                                       'total_runs': 100})
    tiles = A.get_overview_section(team_id=None)['tiles']
    assert tiles['devices_up'] == 2
    assert tiles['devices_issue'] == 1
    assert tiles['devices_down'] == 1
    assert tiles['devices_total'] == 4
    assert tiles['hosts_total'] == 2
    assert tiles['hosts_reporting'] == 1      # labox-dongle is 'silent'
    assert tiles['alerts_active'] == 12       # 8 freeze + 4 audio_loss
    assert tiles['incidents_open'] == 161


# ---------------------------------------------------------------------------
# Incidents / alerts
# ---------------------------------------------------------------------------

def test_incident_timeline_has_a_key_for_every_severity(views):
    """Stacked bars need a value per series per day, including zeroes."""
    out = A.get_incidents_section()
    assert out['severities'] == ['critical', 'high']
    for row in out['timeline']:
        assert set(out['severities']).issubset(row.keys())
    by_day = {r['day']: r for r in out['timeline']}
    assert by_day['2026-09-17']['high'] == 0


def test_mttr_is_weighted_by_resolved_count_not_a_flat_mean(views):
    """(100*32 + 200*5) / 37 = 113.5 -> 114, not the flat mean (100+200)/2 = 150.

    The distinction matters: one long-running incident must not drag the average up
    as much as thirty short ones pull it down.
    """
    assert A.get_incidents_section()['mttr_minutes'] == 114


def test_alerts_review_state_accounts_for_every_alert(views):
    review = A.get_alerts_section()['review']
    assert review['checked'] == 2
    assert review['discarded'] == 1
    assert review['unreviewed'] == 521        # 524 total - 2 - 1
    assert sum(review.values()) == 524


def test_alerts_active_counts_only_active_rows(views):
    assert A.get_alerts_section()['active'] == 12


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------

def test_cache_serves_from_memory_inside_the_fresh_window():
    calls = []
    cache = SectionCache()
    cache.register('x', lambda team_id: calls.append(1) or len(calls), fresh=60, stale=600)

    assert cache.get('x')[0] == 1
    assert cache.get('x') == (1, 'fresh')
    assert len(calls) == 1, "second read must not recompute"


def test_cache_serves_stale_immediately_rather_than_blocking():
    """Past `fresh`, the caller gets the old value NOW and a refresh runs behind it.

    This is the property a plain TTL does not have: with a TTL the unlucky caller
    who arrives at expiry pays the whole query.
    """
    calls = []

    def slow(team_id):
        calls.append(1)
        if len(calls) > 1:
            time.sleep(0.3)          # a refresh nobody should ever wait for
        return len(calls)

    cache = SectionCache()
    cache.register('x', slow, fresh=0, stale=600)

    cache.get('x')                    # prime
    started = time.time()
    value, state = cache.get('x')
    elapsed = time.time() - started

    assert state == 'stale'
    assert value == 1, "the stale value, not the one still being computed"
    assert elapsed < 0.1, f"served in {elapsed:.3f}s — it blocked on the refresh"


def test_cache_keeps_the_stale_value_when_a_refresh_fails():
    """Old numbers beat an error page."""
    state = {'n': 0}

    def flaky(team_id):
        state['n'] += 1
        if state['n'] > 1:
            raise RuntimeError('database went away')
        return 'good'

    cache = SectionCache()
    cache.register('x', flaky, fresh=0, stale=600)

    assert cache.get('x')[0] == 'good'
    for _ in range(20):
        value, _ = cache.get('x')
        assert value == 'good', "a failed refresh must not evict the good value"
        time.sleep(0.01)


def test_cache_keys_are_per_section_so_one_does_not_evict_another():
    cache = SectionCache()
    cache.register('a', lambda team_id: 'A', fresh=60, stale=600)
    cache.register('b', lambda team_id: 'B', fresh=60, stale=600)

    cache.get('a')
    cache.get('b')
    assert cache.get('a') == ('A', 'fresh')


def test_cache_keys_are_per_team():
    cache = SectionCache()
    cache.register('x', lambda team_id: f'data-for-{team_id}', fresh=60, stale=600)

    assert cache.get('x', team_id='t1')[0] == 'data-for-t1'
    assert cache.get('x', team_id='t2')[0] == 'data-for-t2'


def test_unknown_section_raises_so_the_route_can_404():
    """It must not fall through — auto_proxy would try to proxy it to a host."""
    cache = SectionCache()
    cache.register('known', lambda team_id: 1, fresh=60, stale=600)
    with pytest.raises(KeyError):
        cache.get('nope')


def test_register_rejects_a_stale_window_shorter_than_fresh():
    cache = SectionCache()
    with pytest.raises(ValueError):
        cache.register('x', lambda team_id: 1, fresh=600, stale=30)


def test_the_overview_charts_keep_a_14_day_window(views, monkeypatch):
    """The Overview says "last 14 days": the 30-day incidents cache entry must not feed its charts."""
    monkeypatch.setattr(A, 'get_kpi_section',
                        lambda team_id=None, days=30: {'pass_rate': 82.0, 'timeline': [], 'total_runs': 1})
    from backend_server.src.routes import server_analytics_routes as routes

    days = [f'2026-09-{d:02d}' for d in range(1, 31)]
    rows = [{'day': d, 'severity': 'high', 'incidents': 1, 'status': 'resolved'} for d in days]
    monkeypatch.setitem(VIEW_FIXTURES, 'analytics_incidents_daily', rows)
    thirty_day = A.get_incidents_section(days=30)
    assert len(thirty_day['timeline']) == 30
    thirty_day['open'] = 7
    monkeypatch.setattr(routes.analytics_cache, 'get', lambda section, team_id=None: (thirty_day, 'fresh'))

    out = routes._overview_loader('team-1')
    assert len(out['incidents_timeline']) == 14
    assert out['tiles']['incidents_open'] == 7
