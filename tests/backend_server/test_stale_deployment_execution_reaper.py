"""A deployment_executions row stuck in 'running' must not keep a host busy (BUG-0780).

The host reads those rows to decide which of its devices are busy. One row that never
flipped out of `running` — because the run died before it could write its verdict — keeps
the whole host "busy" for ever: the Run page padlocks the target and the Device page polls
a running.log that does not exist.

The sweep closes such a row, but only when the host itself says the run behind THAT row is
gone, and only after a long grace period.

The question is per row, not per device (E50): a live run on the same device says nothing about a
dead row on that device, and asking per device is what let one runaway run shield every dead row
of the host. The host echoes the execution_id it was asked about; an answer without that echo
comes from a host on an old build, which answered about the DEVICE, so the row is kept.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class _Query:
    """The tiny slice of the PostgREST builder the sweep uses."""

    def __init__(self, table: str, state: dict):
        self.table = table
        self.state = state
        self.filters: list = []
        self.payload = None

    def select(self, *_a, **_kw):
        return self

    def eq(self, column: str, value):
        self.filters.append((column, value))
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def execute(self):
        if self.payload is not None:
            self.state['updates'].append((self.table, dict(self.payload), list(self.filters)))
            return _Result([])
        rows = []
        for row in self.state['rows']:
            if all(row.get(col) == val for col, val in self.filters if col in row):
                rows.append(row)
        return _Result(rows)


class _Result:
    def __init__(self, data):
        self.data = data


class _Supabase:
    def __init__(self, state: dict):
        self.state = state

    def table(self, name: str):
        return _Query(name, self.state)


@pytest.fixture
def sweep(monkeypatch):
    try:
        from backend_server.src.routes import server_system_routes as mod
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'server deps not installed: {exc}')

    state = {'rows': [], 'updates': [], 'busy': False, 'host_answers': True,
             'old_build': False, 'busy_by_execution': {}}

    import shared.src.lib.utils.supabase_utils as su
    monkeypatch.setattr(su, 'get_supabase_client', lambda: _Supabase(state))

    def fake_call_host(host, path, method='GET', **kw):
        if not state['host_answers']:
            return {}, 503
        execution_id = (kw.get('query_params') or {}).get('execution_id')
        if not execution_id:
            return {'busy': state['busy']}, 200
        # A host on the current build answers the per-row question and echoes the id back.
        # An old build ignores the id and answers about the DEVICE: no echo, and the server
        # keeps the row because that answer says nothing about this row.
        if state['old_build']:
            return {'busy': state['busy']}, 200
        busy = state['busy_by_execution'].get(execution_id, state['busy'])
        return {'busy': busy, 'execution_id': execution_id}, 200
    import shared.src.lib.utils.build_url_utils as bu
    monkeypatch.setattr(bu, 'call_host', fake_call_host)

    return mod, state


def _run(mod, state, host_name='host-clone-1'):
    mod._reap_stale_running_deployments_for_host(host_name, {'host_name': host_name})


def test_a_stuck_row_on_an_idle_device_is_closed(sweep):
    mod, state = sweep
    state['rows'] = [{
        'id': 'exec-1',
        'started_at': _iso(5),          # five hours old
        'scheduled_at': _iso(5),
        'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'},
    }]

    _run(mod, state)

    assert len(state['updates']) == 1
    table, payload, filters = state['updates'][0]
    assert table == 'deployment_executions'
    assert payload['status'] == 'failed'
    assert payload['success'] is False
    assert 'stuck' in payload['error_message']
    assert ('id', 'exec-1') in filters


def test_a_row_on_a_device_the_host_is_working_on_is_left_alone(sweep):
    mod, state = sweep
    state['busy'] = True
    state['rows'] = [{
        'id': 'exec-1',
        'started_at': _iso(5),
        'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'},
    }]

    _run(mod, state)

    assert state['updates'] == []


def test_a_fresh_row_is_left_alone(sweep):
    mod, state = sweep
    state['rows'] = [{
        'id': 'exec-1',
        'started_at': _iso(0.1),        # six minutes old: the script may still be starting
        'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'},
    }]

    _run(mod, state)

    assert state['updates'] == []


def test_a_row_is_kept_when_the_host_does_not_answer(sweep):
    mod, state = sweep
    state['host_answers'] = False
    state['rows'] = [{
        'id': 'exec-1',
        'started_at': _iso(5),
        'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'},
    }]

    _run(mod, state)

    assert state['updates'] == []


def test_the_host_is_asked_once_per_row(sweep):
    """The question is per ROW, not per device (E50).

    A live run on the same device says nothing about a dead row on that device, so each row is
    probed on its own and each question carries that row's id. Asking once per device is what
    let one runaway run shield every dead row of the host.
    """
    mod, state = sweep
    state['rows'] = [
        {'id': 'exec-1', 'started_at': _iso(5), 'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}},
        {'id': 'exec-2', 'started_at': _iso(6), 'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}},
    ]

    calls = []
    import shared.src.lib.utils.build_url_utils as bu
    original = bu.call_host

    def counting(host, path, method='GET', **kw):
        calls.append((path, (kw.get('query_params') or {}).get('execution_id')))
        return original(host, path, method=method, **kw)
    bu.call_host = counting
    try:
        _run(mod, state)
    finally:
        bu.call_host = original

    assert len(calls) == 2
    assert {execution_id for _path, execution_id in calls} == {'exec-1', 'exec-2'}
    assert len(state['updates']) == 2


def test_a_live_run_does_not_shield_a_dead_row_on_the_same_device(sweep):
    """The reason the question is per row (E50).

    Two rows on one device: one is still running, one died. The live one must not keep the dead
    one alive - that shielding is exactly what left rows stuck in 'running' for ever.
    """
    mod, state = sweep
    state['busy_by_execution'] = {'exec-live': True}
    state['rows'] = [
        {'id': 'exec-live', 'started_at': _iso(5), 'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}},
        {'id': 'exec-dead', 'started_at': _iso(6), 'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}},
    ]

    _run(mod, state)

    assert len(state['updates']) == 1
    table, payload, filters = state['updates'][0]
    assert table == 'deployment_executions'
    assert ('id', 'exec-dead') in filters
    assert payload['status'] == 'failed'


def test_a_row_is_kept_when_the_host_does_not_answer_the_per_row_question(sweep):
    """A host on an old build answers about the DEVICE, not about this row.

    Its "not busy" says nothing about this row, and acting on it would close a live run once the
    grace period passed (BUG-0780). The row stays.
    """
    mod, state = sweep
    state['old_build'] = True
    state['rows'] = [{'id': 'exec-1', 'started_at': _iso(5),
                      'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}}]

    _run(mod, state)

    assert state['updates'] == []


def test_the_close_is_guarded_by_status_running(sweep):
    mod, state = sweep
    state['rows'] = [{'id': 'exec-1', 'started_at': _iso(5),
                      'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}}]
    _run(mod, state)
    filters = state['updates'][0][2]
    # A run that finished between the select and the update must not be overwritten.
    assert ('status', 'running') in filters


@pytest.mark.parametrize('body', [{}, {'busy': None}, {'busy': 'maybe'}, []])
def test_an_answer_without_a_busy_flag_counts_as_busy(sweep, monkeypatch, body):
    mod, state = sweep
    import shared.src.lib.utils.build_url_utils as bu
    monkeypatch.setattr(bu, 'call_host', lambda *a, **k: (body, 200))
    state['rows'] = [{'id': 'exec-1', 'started_at': _iso(5),
                      'deployments': {'host_name': 'host-clone-1', 'device_id': 'host'}}]
    _run(mod, state)
    assert state['updates'] == []


# --- host side: the is_busy endpoint ---------------------------------------------------------

@pytest.fixture
def host_client(monkeypatch):
    import importlib.util
    from unittest.mock import MagicMock
    if importlib.util.find_spec('sklearn') is None:  # heavy ML dep the route package imports but is_busy never uses
        for name in ('sklearn', 'sklearn.feature_extraction', 'sklearn.feature_extraction.text',
                     'sklearn.metrics', 'sklearn.metrics.pairwise'):
            monkeypatch.setitem(sys.modules, name, MagicMock())
    try:
        from flask import Flask
        from backend_host.src.routes import host_system_routes as hs
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'host deps not installed: {exc}')
    app = Flask(__name__)
    app.register_blueprint(hs.host_system_bp, url_prefix='/host/system')
    return app.test_client()


def _is_busy(client):
    resp = client.get('/host/system/device/host/is_busy')
    assert resp.status_code == 200
    return resp.get_json()


def test_host_idle_when_nothing_runs(host_client):
    body = _is_busy(host_client)
    assert body['busy'] is False


def test_host_busy_between_campaign_steps(host_client):
    """A DB campaign runs each step in its own subprocess: in the gap no script exists."""
    from shared.src.lib.executors import campaign_executor as ce
    started = {}
    with ce._in_flight_lock:
        ce._in_flight_campaigns['k'] = {'type': 'campaign', 'campaign_id': 'c1',
                                        'device_id': 'host', 'started_at': 1.0}
    try:
        started = _is_busy(host_client)
    finally:
        with ce._in_flight_lock:
            ce._in_flight_campaigns.pop('k', None)
    assert started['busy'] is True
    assert _is_busy(host_client)['busy'] is False


def test_in_flight_registry_is_cleared_even_when_the_campaign_raises():
    try:
        from shared.src.lib.executors import campaign_executor as ce
    except ImportError as exc:  # pragma: no cover
        pytest.skip(str(exc))
    ex = ce.CampaignExecutor()

    def boom(cfg):
        assert ce.get_in_flight_campaigns()[0]['campaign_id'] == 'c1'
        raise RuntimeError('x')
    ex._execute_campaign = boom
    with pytest.raises(RuntimeError):
        ex.execute_campaign({'campaign_id': 'c1', 'name': 'n', 'device': 'host'})
    assert ce.get_in_flight_campaigns() == []


def test_host_reports_busy_when_a_sub_check_raises(host_client, monkeypatch):
    import shared.src.lib.executors.script_executor as se

    class Boom:
        def __enter__(self):
            raise RuntimeError('lock broken')

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(se, '_running_processes_lock', Boom())
    body = _is_busy(host_client)
    assert body['busy'] is True
    assert 'scripts' in body['check_errors']


def test_real_execute_campaign_registers_its_device_while_running():
    try:
        from shared.src.lib.executors import campaign_executor as ce
    except ImportError as exc:  # pragma: no cover
        pytest.skip(str(exc))
    seen = []
    ex = ce.CampaignExecutor()
    ex._execute_campaign = lambda cfg: seen.extend(ce.get_in_flight_campaigns()) or {'success': True}
    ex.execute_campaign({'campaign_id': 'c1', 'name': 'n', 'device': 'host'})
    assert [c['device_id'] for c in seen] == ['host']
    assert ce.get_in_flight_campaigns() == []
