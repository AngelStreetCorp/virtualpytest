"""
tests/backend_server/test_mcp_execution_status.py — execute_testcase / execute_script return an
execution_id at once, and get_testcase_execution_status / get_script_execution_status read the run
(BUG-0378).

A client behind a proxy got 524s: execute_testcase held one HTTP request open for up to 300 s
(execute_script for up to 7200 s) while it polled for the end of the run. The status tools answer
within wait_seconds (max 50 s); a status read that timed out or got a 5xx is reported as
`unknown, done: false` (read again), never as the run's failure (BUG-0275).
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools import testcase_tools, script_tools  # noqa: E402
    from backend_server.src.mcp.utils import execution_status_reader  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

TC_RUNNING = {'success': True, 'status': {'status': 'running', 'current_block_id': 'nav-1'}}
TC_PASSED = {'success': True, 'status': {'status': 'completed', 'result': {
    'success': True, 'execution_time_ms': 4000, 'report_url': 'https://r/report.html'}}}
TC_TEST_FAILED = {'success': True, 'status': {'status': 'completed', 'result': {
    'success': False, 'error': 'verification failed', 'execution_time_ms': 3000}}}
TC_RUN_FAILED = {'success': True, 'status': {'status': 'failed', 'error': 'device offline'}}
TIMEOUT = {'success': False, 'error': 'Request timeout (30s)', 'timeout': True}
BAD_GATEWAY = {'success': False, 'error': 'HTTP 502: bad gateway', 'status_code': 502}
NOT_FOUND = {'success': False, 'error': 'HTTP 404: Execution not found', 'status_code': 404}

HOSTS = {'success': True, 'hosts': [{'host_name': 'pi1', 'devices': [{'device_id': 'device1'}]}]}


class _Api:
    """Replies to GETs in order (last one repeats); POST answers with `post_reply`."""

    def __init__(self, replies=(), post_reply=None, routes=None):
        self.replies, self.post_reply, self.routes = list(replies), post_reply, routes or {}
        self.gets, self.posts, self.n = [], [], 0

    def get(self, endpoint, params=None):
        self.gets.append((endpoint, params))
        if endpoint in self.routes:
            return self.routes[endpoint]
        reply = self.replies[min(self.n, len(self.replies) - 1)]
        self.n += 1
        return reply

    def post(self, endpoint, data=None, params=None):
        self.posts.append((endpoint, data, params))
        return self.post_reply


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    """sleep() advances a fake clock, so waits run instantly but wall-time limits still apply."""
    now = [1000.0]
    monkeypatch.setattr(execution_status_reader.time, 'time', lambda: now[0])
    monkeypatch.setattr(execution_status_reader.time, 'sleep', lambda s: now.__setitem__(0, now[0] + s))
    return now


def _tc_tools(api):
    tools = object.__new__(testcase_tools.TestCaseTools)
    tools.api = api
    return tools


def _script_tools(api):
    tools = object.__new__(script_tools.ScriptTools)
    tools.api = api
    return tools


def _tc_status(api, **params):
    return _tc_tools(api).get_testcase_execution_status({'execution_id': 'ex1', 'host_name': 'pi1', 'team_id': 't', **params})


# ---------- execute_testcase ----------

def test_execute_testcase_returns_the_execution_id_without_reading_status():
    api = _Api(post_reply={'success': True, 'execution_id': 'ex1'})
    r = _tc_tools(api).execute_testcase({'testcase_name': 'TC_01', 'host_name': 'pi1', 'device_id': 'device1',
                                         'team_id': 't', 'graph_json': {'nodes': [], 'edges': []}})
    assert r['isError'] is False
    assert r['structuredContent'] == {**r['structuredContent'], 'execution_id': 'ex1', 'status': 'running',
                                      'done': False, 'host_name': 'pi1', 'device_id': 'device1'}
    assert 'get_testcase_execution_status' in r['content'][0]['text']
    assert api.gets == []


# ---------- get_testcase_execution_status ----------

def test_testcase_status_waits_for_the_end_of_the_run():
    api = _Api([TC_RUNNING, TC_RUNNING, TC_PASSED])
    r = _tc_status(api, wait_seconds=20)
    s = r['structuredContent']
    assert len(api.gets) == 3
    assert (s['status'], s['done'], s['passed'], s['report_url']) == ('completed', True, True, 'https://r/report.html')
    assert api.gets[0] == ('/server/testcase/execution/ex1/status', {'host_name': 'pi1', 'team_id': 't'})


def test_testcase_status_answers_running_once_the_wait_is_spent(fake_clock):
    api = _Api([TC_RUNNING])
    started = fake_clock[0]
    r = _tc_status(api, wait_seconds=10)
    assert fake_clock[0] - started <= 10
    assert r['isError'] is False
    assert (r['structuredContent']['status'], r['structuredContent']['done']) == ('running', False)
    assert r['structuredContent']['current_block_id'] == 'nav-1'


def test_testcase_status_wait_zero_reads_once():
    api = _Api([TC_RUNNING])
    _tc_status(api, wait_seconds=0)
    assert len(api.gets) == 1


def test_testcase_status_wait_is_capped(fake_clock):
    started = fake_clock[0]
    _tc_status(_Api([TC_RUNNING]), wait_seconds=600)
    assert fake_clock[0] - started <= 50


def test_a_testcase_that_failed_its_checks_is_a_result_not_a_tool_error():
    r = _tc_status(_Api([TC_TEST_FAILED]))
    s = r['structuredContent']
    assert r['isError'] is False
    assert (s['status'], s['done'], s['passed'], s['error']) == ('completed', True, False, 'verification failed')


def test_a_run_that_failed_is_done_and_not_passed():
    s = _tc_status(_Api([TC_RUN_FAILED]))['structuredContent']
    assert (s['status'], s['done'], s['passed'], s['error']) == ('failed', True, False, 'device offline')


def test_slow_or_5xx_status_reads_are_read_again_within_the_wait():
    api = _Api([TIMEOUT, BAD_GATEWAY, TC_PASSED])
    s = _tc_status(api)['structuredContent']
    assert len(api.gets) == 3 and s['status'] == 'completed'


def test_a_slow_status_read_never_reads_as_the_runs_failure():
    r = _tc_status(_Api([TIMEOUT]), wait_seconds=0)
    s = r['structuredContent']
    assert r['isError'] is False
    assert (s['status'], s['done'], s['passed']) == ('unknown', False, None)


def test_CONTROL_an_unknown_execution_is_a_tool_error_at_once():
    api = _Api([NOT_FOUND, TC_PASSED])
    r = _tc_status(api)
    assert len(api.gets) == 1
    assert r['isError'] is True and 'Status check failed' in r['content'][0]['text']


def test_testcase_status_requires_execution_id_and_host():
    assert _tc_tools(_Api()).get_testcase_execution_status({'host_name': 'pi1'})['isError'] is True
    assert _tc_tools(_Api()).get_testcase_execution_status({'execution_id': 'ex1'})['isError'] is True


# ---------- execute_script / get_script_execution_status ----------

def test_execute_script_returns_the_execution_id_without_reading_status():
    api = _Api(post_reply={'success': True, 'task_id': 'task-1'},
               routes={'/server/system/getAllHosts': HOSTS})
    r = _script_tools(api).execute_script({'script_name': 'demo.py', 'host_name': 'pi1', 'device_id': 'device1', 'team_id': 't'})
    s = r['structuredContent']
    assert r['isError'] is False
    assert (s['execution_id'], s['kind'], s['status'], s['done']) == ('task-1', 'script', 'running', False)
    assert [g[0] for g in api.gets] == ['/server/system/getAllHosts']


def _script_status(replies, **params):
    api = _Api(replies)
    return api, _script_tools(api).get_script_execution_status({'execution_id': 'task-1', **params})


def test_script_status_reports_the_test_verdict():
    api, r = _script_status([
        {'success': True, 'task': {'status': 'running'}},
        {'success': True, 'task': {'status': 'completed', 'result': {'exit_code': 0, 'script_success': False}}},
    ])
    s = r['structuredContent']
    assert api.gets[0][0] == '/server/script/status/task-1'
    assert r['isError'] is False
    assert (s['status'], s['done'], s['passed'], s['exit_code']) == ('completed', True, False, 0)


def test_script_status_failed_and_unknown():
    _, r = _script_status([{'success': True, 'task': {'status': 'failed', 'error': 'exit 2', 'result': {'exit_code': 2}}}])
    assert (r['structuredContent']['status'], r['structuredContent']['passed']) == ('failed', False)
    _, r = _script_status([{'success': False, 'error': 'Task not found', 'status_code': 404}])
    assert r['isError'] is True


def test_clamp_wait_seconds():
    clamp = execution_status_reader.clamp_wait_seconds
    assert (clamp(None), clamp(''), clamp('x'), clamp(-5), clamp(7), clamp(999)) == (20, 20, 20, 0, 7, 50)


def test_the_status_text_keeps_the_old_reply_shape():
    text = _tc_status(_Api([TC_PASSED]))['content'][0]['text']
    assert text.startswith('✅ Test case completed\nResult: PASSED (4.0s)')
