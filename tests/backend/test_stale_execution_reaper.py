"""The stale-row reaper must be per row, not per device (E50).

The server closed the deployment_executions rows that a host was stuck on. It asked the
host "is this DEVICE busy?" and skipped every stale row of that device when the answer
was yes. A game run that overran its own budget therefore shielded every dead row of
that host: the dead rows stayed 'running', the host's busy signal stayed non-empty, and
the deploy kept deferring - for exactly as long as the runaway kept running.

What is checked here:
  - a stale row is closed even when an UNRELATED run is live on the same device,
  - the row of a genuinely live run is not closed,
  - the host is asked per row (the execution id travels with the question),
  - a row the host cannot judge is left alone.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

system_routes = pytest.importorskip('backend_server.src.routes.server_system_routes')
supabase_utils = pytest.importorskip('shared.src.lib.utils.supabase_utils')
build_url_utils = pytest.importorskip('shared.src.lib.utils.build_url_utils')

HOST_NAME = '<host>'
DEVICE_ID = 'host'


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows, updates):
        self._rows = rows
        self._updates = updates
        self._filter = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        if self._filter is None:
            self._filter = {}
        self._filter[column] = value
        return self

    def update(self, values):
        self._updates.append({'values': values, 'filter': dict(self._filter or {})})
        return self

    def execute(self):
        return _Result(self._rows)


class _Supabase:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []

    def table(self, _name):
        return _Table(self._rows, self.updates)


def _row(execution_id, age_s=3 * 3600):
    started = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {
        'id': execution_id,
        'started_at': started.isoformat(),
        'scheduled_at': started.isoformat(),
        'deployments': {'host_name': HOST_NAME, 'device_id': DEVICE_ID},
    }


@pytest.fixture
def host_answers(monkeypatch):
    """The host's answers per execution id, and the questions it was asked."""
    answers = {}
    questions = []

    def fake_call_host(_host_info, endpoint, method='POST', data=None, query_params=None,
                       timeout=30, **_kwargs):
        questions.append({'endpoint': endpoint, 'query_params': query_params})
        execution_id = (query_params or {}).get('execution_id')
        # The ids in `answers` are the runs the host still sees alive. A host that answers
        # the per-row question echoes the id back - that is how the server knows the
        # answer is about this row and not about the device.
        return ({'busy': execution_id in answers, 'execution_id': execution_id}, 200)

    monkeypatch.setattr(build_url_utils, 'call_host', fake_call_host)
    return answers, questions


@pytest.fixture
def rows(monkeypatch):
    """The 'running' rows the server finds, and the updates it writes."""
    holder = {}

    def install(row_list):
        supabase = _Supabase(row_list)
        holder['supabase'] = supabase
        monkeypatch.setattr(supabase_utils, 'get_supabase_client', lambda: supabase)
        return supabase

    return install


def test_a_dead_row_is_reaped_even_when_another_run_is_live_on_the_device(rows, host_answers):
    """The bug: one live run on the device shielded every dead row of that device."""
    answers, questions = host_answers
    answers['exec-live'] = True          # the host says this run is alive
    supabase = rows([_row('exec-dead'), _row('exec-live')])

    system_routes._reap_stale_running_deployments_for_host(HOST_NAME, {'host_name': HOST_NAME})

    closed = [u['values']['status'] for u in supabase.updates]
    assert closed == ['failed']
    # The question carries the row: the host is asked per row, not per device.
    assert [q['query_params']['execution_id'] for q in questions] == ['exec-dead', 'exec-live']


def test_the_row_of_a_live_run_is_not_reaped(rows, host_answers):
    """A run that is really going must never be closed."""
    answers, _ = host_answers
    answers['exec-live'] = True
    supabase = rows([_row('exec-live')])

    system_routes._reap_stale_running_deployments_for_host(HOST_NAME, {'host_name': HOST_NAME})

    assert supabase.updates == []


def test_a_row_the_host_cannot_judge_is_left_alone(rows, monkeypatch):
    """No answer, no guess: the row stays until the host answers."""
    def failing_call_host(*_args, **_kwargs):
        return ({}, 500)

    monkeypatch.setattr(build_url_utils, 'call_host', failing_call_host)
    supabase = rows([_row('exec-unknown')])

    system_routes._reap_stale_running_deployments_for_host(HOST_NAME, {'host_name': HOST_NAME})

    assert supabase.updates == []


def test_an_old_host_leaves_the_row_alone(rows, monkeypatch):
    """A host that predates the per-row probe answers about the DEVICE, not the row.

    It ignores the execution_id and does not echo it back, so the server knows the answer
    is not about this row. Such an answer is not a proof that this row's run is gone, so
    the row must stay: an old host must never be able to close a live run (E50).
    """
    def old_call_host(*_args, **_kwargs):
        return ({'busy': False, 'device_id': DEVICE_ID, 'active_jobs': []}, 200)

    monkeypatch.setattr(build_url_utils, 'call_host', old_call_host)
    supabase = rows([_row('exec-old-host')])

    system_routes._reap_stale_running_deployments_for_host(HOST_NAME, {'host_name': HOST_NAME})

    assert supabase.updates == []


def test_a_fresh_row_is_left_alone(rows, host_answers):
    """A run that started a minute ago is not stale."""
    _answers, _questions = host_answers
    supabase = rows([_row('exec-fresh', age_s=60)])

    system_routes._reap_stale_running_deployments_for_host(HOST_NAME, {'host_name': HOST_NAME})

    assert supabase.updates == []
