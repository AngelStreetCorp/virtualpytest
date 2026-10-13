"""Quality routes: flaky / slow / not executed in window (TASK-42 §4.4).

The aggregation itself runs in SQL (``rm_quality_*``) and is verified against
deterministic sequences in ``test_run_services_pg.py``. These unit tests pin
the route contract: scope passed to the database, window/sample reporting,
response shape, the not-executed anti-join and validation.
"""

import os
import sys
from datetime import datetime, timezone

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_quality_routes import server_quality_bp  # noqa: E402
from backend_server.src.services.analytics import quality, scope as scope_mod  # noqa: E402

pytestmark = pytest.mark.unit

VIEW = ['reports.tests:view']


@pytest.fixture
def env(monkeypatch):
    fake = common.install(monkeypatch)
    client = common.make_app(server_quality_bp, permissions=VIEW).test_client()
    return fake, client


def _identity_row(**extra):
    row = {'script_name': 'goto_live', 'script_type': 'goto_live', 'userinterface_name': 'ui_a',
           'environment': 'prod', 'host_name': 'host-1', 'device_name': 'device1'}
    row.update(extra)
    return row


def test_flaky_passes_full_scope_and_reports_window_and_sample(env):
    fake, client = env
    fake.rpc_handlers['rm_quality_flaky'] = lambda p: [
        _identity_row(attempts=5, passes=3, fails=2, transitions=4, flaky_score='1.0000', is_flaky=True,
                      last_status='passed', last_result_id=common.new_id(),
                      first_started_at='2026-10-01T00:00:00+00:00', last_started_at='2026-10-02T00:00:00+00:00'),
        _identity_row(device_name='device2', attempts=6, passes=6, fails=0, transitions=0,
                      flaky_score='0.0000', is_flaky=False),
    ]
    resp = client.get('/server/script-results/flaky',
                      query_string={'team_id': common.TEAM_A, 'host_filter': '["host-1"]'})
    assert resp.status_code == 200
    body = resp.get_json()
    name, params = fake.rpc_calls[0]
    assert name == 'rm_quality_flaky'
    assert params['p_team_id'] == common.TEAM_A
    assert params['p_host_names'] == ['host-1']          # registry ∩ workspace filter
    assert params['p_device_keys'] is None
    assert params['p_min_attempts'] == 5
    assert body['window_days'] == 14                      # frozen default
    assert body['min_attempts'] == 5
    assert body['sample_size'] == 11                      # every evaluated attempt, not just flaky rows
    assert body['row_total'] == 1
    row = body['rows'][0]
    assert row['flaky_score'] == 1.0 and row['failures'] == 2 and row['transitions'] == 4
    assert row['identity'] == {k: v for k, v in _identity_row().items()}
    assert row['latest_script_result_id']


def test_devices_are_separate_identities_never_merged(env):
    fake, client = env
    fake.rpc_handlers['rm_quality_flaky'] = lambda p: [
        _identity_row(device_name='device1', attempts=5, passes=5, fails=0, transitions=0, flaky_score=0, is_flaky=False),
        _identity_row(device_name='device2', attempts=5, passes=0, fails=5, transitions=0, flaky_score=0, is_flaky=False),
    ]
    body = client.get('/server/script-results/flaky', query_string={'team_id': common.TEAM_A}).get_json()
    assert body['rows'] == []  # always-pass on one device + always-fail on another is not flakiness


def test_slow_shape_and_default_window(env):
    fake, client = env
    fake.rpc_handlers['rm_quality_slow'] = lambda p: [
        _identity_row(samples=20, p50_ms=1000, p95_ms=1900, max_ms=2000, last_result_id=common.new_id()),
    ]
    body = client.get('/server/script-results/slow', query_string={'team_id': common.TEAM_A}).get_json()
    assert body['window_days'] == 30
    assert body['percentile_method'] == 'nearest-rank'
    assert body['sample_size'] == 20
    assert body['rows'][0]['sample_count'] == 20 and body['rows'][0]['p95_ms'] == 1900
    assert fake.rpc_calls[0][1]['p_min_samples'] == 5


def test_no_registered_host_in_scope_means_no_query(env):
    fake, client = env
    body = client.get('/server/script-results/flaky',
                      query_string={'team_id': common.TEAM_A, 'host_filter': '["other-server-host"]'}).get_json()
    assert body['rows'] == [] and body['sample_size'] == 0
    assert fake.rpc_calls == []


def test_device_filter_narrows_hosts_and_keys(env):
    fake, client = env
    fake.rpc_handlers['rm_quality_slow'] = lambda p: []
    client.get('/server/script-results/slow', query_string={
        'team_id': common.TEAM_A, 'device_filter': '["host-2:device1", "elsewhere:device9"]'})
    params = fake.rpc_calls[0][1]
    assert params['p_host_names'] == ['host-2']
    assert params['p_device_keys'] == ['host-2:device1']


def test_device_filter_keys_are_translated_to_display_names(monkeypatch):
    # Workspaces store host:device_id; script_results rows store the display name.
    fake = common.install(monkeypatch, hosts={'host-1': [('device1', 'Living room TV')], 'host-2': ['device1']})
    fake.rpc_handlers['rm_quality_slow'] = lambda p: []
    client = common.make_app(server_quality_bp, permissions=VIEW).test_client()
    client.get('/server/script-results/slow', query_string={
        'team_id': common.TEAM_A, 'device_filter': '["host-1:device1", "host-2:device1"]'})
    params = fake.rpc_calls[0][1]
    assert params['p_device_keys'] == ['host-1:Living room TV', 'host-2:device1']


def test_device_keys_to_names_keeps_unregistered_keys():
    from backend_server.src.services.analytics.scope import device_keys_to_names
    hosts = {'host-1': {'devices': [{'device_id': 'device1', 'device_name': 'Kitchen'}]}}
    assert device_keys_to_names(['host-1:device1', 'gone:device7'], hosts) == ['host-1:Kitchen', 'gone:device7']
    assert device_keys_to_names(None, hosts) is None


@pytest.mark.parametrize('query', [
    {'window_days': '0'}, {'window_days': '366'}, {'window_days': 'x'}, {'limit': '0'},
    {'host_filter': 'not-json'}, {'device_filter': '["no-colon"]'},
])
def test_validation_errors(env, query):
    _, client = env
    query = {'team_id': common.TEAM_A, **query}
    assert client.get('/server/script-results/flaky', query_string=query).status_code == 400


def test_team_id_required_and_uuid(env):
    _, client = env
    assert client.get('/server/script-results/flaky').status_code == 400
    assert client.get('/server/script-results/flaky', query_string={'team_id': 'abc'}).status_code == 400


def test_permission_required(monkeypatch):
    common.install(monkeypatch)
    client = common.make_app(server_quality_bp, permissions=[]).test_client()
    assert client.get('/server/script-results/slow', query_string={'team_id': common.TEAM_A}).status_code == 403


def test_not_executed_is_an_anti_join_of_the_runnable_catalog(monkeypatch):
    fake = common.install(monkeypatch)
    fake.rpc_handlers['rm_executed_script_names'] = lambda p: [
        {'script_name': 'goto_live.py', 'attempts': 3, 'last_started_at': '2026-10-02T00:00:00Z'},
        {'script_name': 'Login smoke', 'attempts': 1, 'last_started_at': '2026-10-02T00:00:00Z'},
    ]
    catalog = [
        {'script_name': 'goto_live', 'script_type': 'script', 'testcase_id': None,
         'userinterface_name': None, 'environment': None, 'last_executed_at': None},
        {'script_name': 'zap_channels', 'script_type': 'script', 'testcase_id': None,
         'userinterface_name': None, 'environment': None, 'last_executed_at': None},
        {'script_name': 'Login smoke', 'script_type': 'testcase', 'testcase_id': common.new_id(),
         'userinterface_name': 'ui_a', 'environment': 'prod', 'last_executed_at': None},
    ]
    scope = scope_mod.build_scope(common.TEAM_A, ['host-1'], None, None)
    body = quality.not_executed(scope, 30, 100, now=datetime(2026, 10, 3, tzinfo=timezone.utc), catalog=catalog)
    assert body['label'] == 'not executed in window'
    assert [r['script_name'] for r in body['rows']] == ['zap_channels']
    assert body['runnable_total'] == 3 and body['row_total'] == 1


def test_runnable_catalog_excludes_hidden_scripts_and_testcases(monkeypatch):
    import backend_server.src.lib.utils.script_utils as script_utils
    import shared.src.lib.database.library_visibility_db as visibility
    import shared.src.lib.database.testcase_db as testcase_db

    hidden_tc = common.new_id()
    monkeypatch.setattr(script_utils, 'list_available_scripts', lambda: ['goto_live', 'secret_tool'])
    monkeypatch.setattr(visibility, 'list_hidden_library_keys',
                        lambda team, kind: {'secret_tool.py'} if kind == 'script' else {hidden_tc})
    monkeypatch.setattr(testcase_db, 'list_testcases', lambda team: [
        {'testcase_id': hidden_tc, 'testcase_name': 'Hidden case'},
        {'testcase_id': common.new_id(), 'testcase_name': 'Visible case', 'userinterface_name': 'ui', 'environment': 'dev'},
    ])
    names = [item['script_name'] for item in quality.runnable_catalog(common.TEAM_A)]
    assert names == ['goto_live', 'Visible case']


def test_not_executed_without_hosts_reports_nothing_runnable(monkeypatch):
    common.install(monkeypatch, hosts={})
    scope = scope_mod.build_scope(common.TEAM_A, [], None, None)
    body = quality.not_executed(scope, 30, 100, catalog=[{'script_name': 'x', 'script_type': 'script'}])
    assert body['rows'] == [] and body['runnable_total'] == 0
