"""Report query model and POST /server/run-management/query (+ CSV export).

One validated filter drives table, counts, chart and export: these tests pin
the validation allowlists, the parameters handed to ``rm_run_query`` and the
projection of the single result into rows / counts / chart points / CSV.
"""

import os
import sys
from datetime import datetime, timezone

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_tql_routes import server_tql_bp  # noqa: E402
from backend_server.src.services.analytics import report_query  # noqa: E402

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


def definition(**overrides):
    doc = {'filter': {'schema_version': 1, 'tql': 'status:failed'},
           'columns': ['script_name', 'status', 'labels'], 'chart': {'type': 'status_by_day'}}
    doc.update(overrides)
    return doc


@pytest.mark.parametrize('doc,field', [
    ({'filter': {'schema_version': 2, 'tql': ''}}, 'filter.schema_version'),
    ({'filter': 'status:failed'}, 'filter'),
    ({'filter': {'schema_version': 1, 'tql': 'bogus:x'}}, 'filter.tql'),
    (definition(columns=['script_name', 'metadata']), 'columns'),
    (definition(columns=['html_report_r2_url']), 'columns'),
    (definition(chart={'type': 'pie3d'}), 'chart.type'),
    (definition(chart={'type': 'status_by_group', 'group_by': 'error_msg'}), 'chart.group_by'),
    (definition(chart={'type': 'status_share', 'group_by': 'host_name'}), 'chart.group_by'),
    (definition(sort='error_msg'), 'sort'),
    (definition(order='sideways'), 'order'),
    (definition(include_discarded='yes'), 'include_discarded'),
])
def test_definition_allowlists(doc, field):
    with pytest.raises(report_query.QueryError) as exc:
        report_query.validate_definition(doc, now=NOW)
    assert exc.value.field == field


def test_definition_round_trip_is_versioned():
    parsed = report_query.validate_definition(
        definition(chart={'type': 'status_by_group', 'group_by': 'host_name'}), now=NOW)
    doc = parsed.to_document()
    assert doc['filter'] == {'schema_version': 1, 'tql': 'status:failed'}
    assert doc['chart'] == {'type': 'status_by_group', 'group_by': 'host_name'}
    assert parsed.sql_chart == 'group:host_name'


def test_window_defaults_and_bounds():
    parsed = report_query.validate_definition(definition(), now=NOW)
    since, until = report_query.resolve_window(parsed.parsed, now=NOW)
    assert (until - since).days == 30
    long_range = report_query.validate_definition(
        definition(filter={'schema_version': 1, 'tql': 'since:2025-01-01 until:2026-10-01'}), now=NOW)
    with pytest.raises(report_query.QueryError):
        report_query.resolve_window(long_range.parsed, now=NOW)


@pytest.fixture
def env(monkeypatch):
    fake = common.install(monkeypatch)
    client = common.make_app(server_tql_bp, permissions=['reports.tests:view']).test_client()
    return fake, client


def _seed_governance(fake):
    label_id, milestone_id = common.new_id(), common.new_id()
    fake.tables['run_label_definitions'] = [
        {'id': label_id, 'team_id': common.TEAM_A, 'name': 'Smoke'},
        {'id': common.new_id(), 'team_id': common.TEAM_B, 'name': 'smoke'},
    ]
    fake.tables['run_milestones'] = [{'id': milestone_id, 'team_id': common.TEAM_A, 'name': 'Sprint 12'}]
    return label_id, milestone_id


def test_query_executes_once_with_resolved_ids_and_scope(env):
    fake, client = env
    label_id, milestone_id = _seed_governance(fake)
    row_id = common.new_id()
    fake.tables['script_result_labels'] = [{'team_id': common.TEAM_A, 'script_result_id': row_id, 'run_label_id': label_id}]
    fake.rpc_handlers['rm_run_query'] = lambda p: {
        'total': 7, 'counts': {'passed': 0, 'failed': 7, 'unknown': 0},
        'rows': [{'id': row_id, 'script_name': '=cmd()', 'status': 'failed', 'milestone_id': milestone_id}],
        'series': [{'x': '2026-10-01', 'passed': 0, 'failed': 7, 'other': 0}],
    }
    resp = client.post('/server/run-management/query', json={
        'team_id': common.TEAM_A, 'host_filter': ['host-1'],
        'filter': {'schema_version': 1, 'tql': 'label:SMOKE milestone:"sprint 12" status:failed script:goto*'},
        'columns': ['script_name', 'status', 'labels', 'milestone'], 'chart': {'type': 'status_by_day'},
        'limit': 25, 'offset': 50,
    })
    assert resp.status_code == 200, resp.get_json()
    assert len(fake.rpc_calls) == 1
    params = fake.rpc_calls[0][1]
    assert params['p_team_id'] == common.TEAM_A and params['p_host_names'] == ['host-1']
    assert params['p_label_ids'] == [label_id]          # team A's label only
    assert params['p_milestone_ids'] == [milestone_id]
    assert params['p_statuses'] == ['failed'] and params['p_scripts'] == ['goto*']
    assert params['p_limit'] == 25 and params['p_offset'] == 50 and params['p_chart'] == 'status_by_day'
    body = resp.get_json()
    assert body['total'] == 7 and body['counts']['failed'] == 7 and body['counts']['skipped'] == 0
    assert body['chart']['points'][0]['failed'] == 7
    assert body['rows'][0]['labels'] == 'Smoke' and body['rows'][0]['milestone'] == 'Sprint 12'
    assert set(body['rows'][0]) == {'script_name', 'status', 'labels', 'milestone', 'script_result_id'}


def test_unknown_label_name_is_a_400_not_an_empty_result(env):
    fake, client = env
    _seed_governance(fake)
    resp = client.post('/server/run-management/query', json={
        'team_id': common.TEAM_A, 'filter': {'schema_version': 1, 'tql': 'label:nope'}})
    assert resp.status_code == 400
    assert fake.rpc_calls == []


def test_query_rejects_parse_errors_with_position(env):
    _, client = env
    resp = client.post('/server/run-management/query', json={
        'team_id': common.TEAM_A, 'filter': {'schema_version': 1, 'tql': 'host:a bogus:1'}})
    assert resp.status_code == 400
    assert resp.get_json()['position'] == 7


def test_export_uses_same_filter_and_escapes_formulas(env):
    fake, client = env
    fake.rpc_handlers['rm_run_query'] = lambda p: {
        'total': 2, 'counts': {'passed': 1, 'failed': 1, 'unknown': 0},
        'rows': [{'id': common.new_id(), 'script_name': '=HYPERLINK("http://x")', 'status': 'failed'},
                 {'id': common.new_id(), 'script_name': '@SUM(A1)', 'status': 'passed'}],
        'series': [],
    }
    resp = client.post('/server/run-management/query/export', json={
        'team_id': common.TEAM_A, 'filter': {'schema_version': 1, 'tql': ''},
        'columns': ['script_name', 'status'], 'chart': {'type': 'none'}})
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert '"\'=HYPERLINK(""http://x"")"' in text
    assert "'@SUM(A1)" in text
    assert resp.headers['X-Total-Count'] == '2' and resp.headers['X-Truncated'] == 'false'
    assert fake.rpc_calls[0][1]['p_limit'] == report_query.MAX_PAGE_SIZE and len(fake.rpc_calls) == 1


def _paged_rpc(total_rows):
    rows = [{'id': common.new_id(), 'script_name': f's{i}', 'status': 'passed'} for i in range(total_rows)]

    def handler(p):
        limit = max(min(p['p_limit'], 500), 1)  # rm_run_query's clamp
        return {'total': total_rows, 'counts': {'passed': total_rows}, 'series': [],
                'rows': rows[p['p_offset']:p['p_offset'] + limit]}
    return handler


def test_export_pages_the_query_up_to_the_cap(env):
    fake, client = env
    fake.rpc_handlers['rm_run_query'] = _paged_rpc(1203)
    resp = client.post('/server/run-management/query/export', json={
        'team_id': common.TEAM_A, 'filter': {'schema_version': 1, 'tql': ''},
        'columns': ['script_name'], 'chart': {'type': 'none'}})
    assert resp.status_code == 200
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 1 + 1203 and lines[-1] == 's1202'
    assert [c[1]['p_offset'] for c in fake.rpc_calls] == [0, 500, 1000]
    assert all(c[1]['p_limit'] <= report_query.MAX_PAGE_SIZE for c in fake.rpc_calls)
    assert len({(c[1]['p_since'], c[1]['p_until']) for c in fake.rpc_calls}) == 1  # one window
    assert resp.headers['X-Total-Count'] == '1203' and resp.headers['X-Truncated'] == 'false'


def test_export_stops_at_the_cap_and_says_so(env, monkeypatch):
    fake, client = env
    monkeypatch.setattr(report_query, 'EXPORT_ROW_CAP', 700)
    fake.rpc_handlers['rm_run_query'] = _paged_rpc(2000)
    resp = client.post('/server/run-management/query/export', json={
        'team_id': common.TEAM_A, 'filter': {'schema_version': 1, 'tql': ''},
        'columns': ['script_name'], 'chart': {'type': 'none'}})
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 1 + 700
    assert [c[1]['p_limit'] for c in fake.rpc_calls] == [500, 200]
    assert resp.headers['X-Row-Cap'] == '700' and resp.headers['X-Truncated'] == 'true'
    assert resp.headers['X-Total-Count'] == '2000'


def test_query_with_no_host_in_scope_returns_empty_without_db(env):
    fake, client = env
    resp = client.post('/server/run-management/query', json={
        'team_id': common.TEAM_A, 'host_filter': ['unknown-host'], 'filter': {'schema_version': 1, 'tql': ''}})
    assert resp.status_code == 200
    assert resp.get_json()['total'] == 0 and fake.rpc_calls == []


def test_body_and_query_team_mismatch_is_rejected(env):
    _, client = env
    resp = client.post(f'/server/run-management/query?team_id={common.TEAM_A}', json={
        'team_id': common.TEAM_B, 'filter': {'schema_version': 1, 'tql': ''}})
    assert resp.status_code == 400
