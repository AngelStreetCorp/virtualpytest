"""Execution-event delivery contract (BUG-0151 / BUG-0199 / BUG-0201 regression guard).

Runs without a host or a server: `requests.post` is replaced, so nothing leaves the
process. What is pinned here is the contract three incidents were caused by breaking:

1. the POST carries the service credential — /server/* refuses an anonymous call;
2. a non-2xx answer is LOGGED, not swallowed (a rejection is a response, not an
   exception, so `try/except` around a bare post reports success for a 401);
3. a terminal event is delivered on the caller's thread, so its outcome is
   observable where the result was produced; `running` is not, because it is
   emitted from a request handler that still owes an HTTP response.
"""
import importlib

import pytest


@pytest.fixture
def emit(monkeypatch):
    """The module with requests.post and the host-name lookup stubbed out."""
    mod = importlib.import_module('backend_host.src.lib.utils.execution_event_utils')

    calls = []

    class _Response:
        def __init__(self, status_code=200, text='{"success":true}'):
            self.status_code = status_code
            self.text = text

    state = {'status_code': 200, 'text': '{"success":true}'}

    def fake_post(url, json=None, headers=None, timeout=None):
        import threading as _t
        calls.append({
            'url': url,
            'payload': json,
            'headers': headers or {},
            'timeout': timeout,
            'thread': _t.current_thread().name,
        })
        return _Response(state['status_code'], state['text'])

    monkeypatch.setattr(mod.requests, 'post', fake_post)
    monkeypatch.setattr(mod, 'get_host_instance', lambda: None)
    monkeypatch.setenv('SERVER_URL', 'http://server.test:5109')
    monkeypatch.setenv('API_KEY', 'test-key-123')
    return mod, calls, state


@pytest.mark.unit
def test_terminal_event_is_delivered_before_returning(emit):
    """A completed event must be posted inline — not handed to a detached thread."""
    mod, calls, _ = emit
    mod.emit_execution_event('verification', 'exec-1', 'completed', team_id='t', result={'ok': True})

    # Posted by the time the call returned, and on THIS thread.
    assert len(calls) == 1
    assert calls[0]['thread'] == 'MainThread'
    assert calls[0]['url'].endswith('/server/system/executionEvent')
    assert calls[0]['payload']['status'] == 'completed'
    assert calls[0]['timeout'] == mod._EMIT_BLOCKING_TIMEOUT_SECONDS


@pytest.mark.unit
@pytest.mark.parametrize('status', sorted(['completed', 'error', 'failed', 'aborted']))
def test_every_terminal_status_blocks(emit, status):
    mod, calls, _ = emit
    mod.emit_execution_event('navigation', 'exec-2', status, team_id='t')
    assert len(calls) == 1, f'{status} was not delivered inline'


@pytest.mark.unit
def test_running_event_does_not_block_the_request_handler(emit):
    """`running` is emitted from a route; it must not be posted on that thread."""
    mod, calls, _ = emit
    mod.emit_execution_event('verification', 'exec-3', 'running', team_id='t', progress=0)
    # Either not yet sent, or sent from the emit thread — never MainThread.
    assert all(c['thread'] != 'MainThread' for c in calls)


@pytest.mark.unit
def test_credential_is_sent(emit):
    """The whole of BUG-0151: without this header the server answers 401."""
    mod, calls, _ = emit
    mod.emit_execution_event('action', 'exec-4', 'completed', team_id='t')
    assert calls[0]['headers'].get('X-API-Key') == 'test-key-123'


@pytest.mark.unit
def test_rejection_is_logged_and_retried(emit, capsys):
    """A 401 is a response, not an exception. It must not read as success."""
    mod, calls, state = emit
    state['status_code'] = 401
    state['text'] = '{"error":"Authentication required"}'

    mod.emit_execution_event('verification', 'exec-5', 'completed', team_id='t')

    assert len(calls) == 2, 'a rejected emit must be retried once'
    out = capsys.readouterr().out
    assert 'Failed to emit execution event' in out
    assert '401' in out


@pytest.mark.unit
def test_blocking_can_be_overridden(emit):
    mod, calls, _ = emit
    mod.emit_execution_event('verification', 'exec-6', 'completed', team_id='t', blocking=False)
    assert all(c['thread'] != 'MainThread' for c in calls)


@pytest.mark.unit
def test_numpy_result_reaches_the_server_as_plain_json(emit):
    """A numpy value in `result` made requests.post raise before sending; the error was
    logged and dropped, the terminal event never arrived and the device lock was held."""
    import json as stdlib_json

    np = pytest.importorskip('numpy')
    mod, calls, _ = emit
    result = {
        'success': np.bool_(True),
        'details': {'score': np.float64(0.91), 'greyscale_found': np.bool_(False),
                    'location': (np.int64(1), np.int64(2)), 'nan': np.float64('nan')},
    }
    mod.emit_execution_event('testcase', 'exec-np', 'completed', team_id='t', result=result)

    assert len(calls) == 1
    payload = calls[0]['payload']
    # Exactly what requests does with json=: stdlib json, allow_nan=False.
    body = stdlib_json.loads(stdlib_json.dumps(payload, allow_nan=False))
    assert body['result'] == {
        'success': True,
        'details': {'score': 0.91, 'greyscale_found': False, 'location': [1, 2], 'nan': None},
    }


@pytest.mark.unit
def test_positive_control_numpy_payload_is_refused_by_requests_encoder():
    import json as stdlib_json

    np = pytest.importorskip('numpy')
    with pytest.raises(TypeError, match=r'bool_?'):
        stdlib_json.dumps({'result': {'success': np.bool_(True)}}, allow_nan=False)
