"""
tests/backend_host/test_testcase_background_report.py -- a testcase reports 'completed' once its
browser is closed and its verdict is in script_results; the report tail runs in the background.

Measured 2026-09-29: the MCP caller polled until finalize had returned, i.e. through the video
extract, mosaic, ~22 screenshot uploads, log/DOM/video/mosaic/HTML/review uploads and the final
DB write -- 7-11 s on host-clone-3, ~25 s on host-clone-2 -- for a verdict known before any of it.

What must hold:
  * order: browser closed -> verdict in script_results -> status 'completed' -> report tail
    (never 'completed' before the close: the next test's Chrome would race the dying one on
    the debug port);
  * the tail uploads what THIS run produced although the next run has started: the log text is
    frozen, the DOM capture files are copied (the next run numbers its files from 01 again in
    the same folder), and the tail's own prints stay out of the next run's capture;
  * script_results gets its report paths when the tail ends, and only that final write adds
    the row to the analysis queue;
  * VPT_TESTCASE_BACKGROUND_REPORT switches it: pass (default) | all | off.
"""
import asyncio
import importlib
import io
import os
import sys
import threading
import types
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.backend_host.test_testcase_fresh_start import _load_executor_module  # noqa: E402

testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor
script_executor_mod = importlib.import_module('shared.src.lib.executors.script_executor')
ScriptExecutor = script_executor_mod.ScriptExecutor
ScriptExecutionContext = script_executor_mod.ScriptExecutionContext
script_results_db = importlib.import_module('shared.src.lib.database.script_results_db')
dom_capture = importlib.import_module('shared.src.lib.utils.dom_capture')
detached = importlib.import_module('shared.src.lib.utils.detached_output')
phase_timing = importlib.import_module('shared.src.lib.utils.phase_timing')


# ---------------------------------------------------------------------------
# ScriptExecutor.finalize_execution_context(defer_report=True): the head, then the tail
# ---------------------------------------------------------------------------

@pytest.fixture
def dom_session(tmp_path):
    """One DOM capture on disk, as the web controller leaves it."""
    dom_capture.reset_dom_captures()
    capture_dir = tmp_path / 'dom'
    capture_dir.mkdir()
    original = capture_dir / '01_todos_dom.txt'
    original.write_text('<html>run A</html>', encoding='utf-8')
    dom_capture._session.captures.append({'name': 'todos', 'title': 'TodoMVC', 'url': 'https://x/todomvc',
                                          'path': str(original), 'sha256': 'a', 'captured_at': 't'})
    yield original
    dom_capture.reset_dom_captures()


@pytest.fixture
def finalize_world(monkeypatch):
    """Record the order of every finalize side effect; nothing leaves the process."""
    events = []
    seen = {}
    ex = ScriptExecutor('TC_ORDER')
    monkeypatch.setattr(ex, '_ensure_device_powered_on', lambda ctx: events.append('power'))
    monkeypatch.setattr(ex, '_release_device_early', lambda ctx: events.append('release'))
    monkeypatch.setattr(ex, '_close_web_browser_if_needed', lambda ctx: events.append('close_browser'))
    monkeypatch.setattr(ex, 'get_device_info_for_report_context', lambda ctx: {'device_model': 'host_vnc'})
    monkeypatch.setattr(ex, 'get_host_info_for_report_context', lambda ctx: {})
    monkeypatch.setattr(ex, '_build_verification_review_markdown', lambda *a, **k: '# review')

    def fake_report(ctx, device_info, host_info, ui, detached_inputs=None):
        events.append('report')
        seen['detached_inputs'] = detached_inputs
        seen['dom_contents'] = [open(c['path'], encoding='utf-8').read()
                                for c in (detached_inputs or {}).get('dom_captures', [])]
        return {'success': True, 'report_url': 'https://r2/report.html', 'report_path': 'reports/x/report.html',
                'logs_url': 'https://r2/execution.txt', 'logs_path': 'script-logs/x/execution.txt'}

    monkeypatch.setattr(ex, 'generate_report_for_context', fake_report)
    monkeypatch.setattr(script_results_db, 'record_script_execution_outcome',
                        lambda **kw: events.append(('db_outcome', kw)) or True)
    monkeypatch.setattr(script_executor_mod, 'update_script_execution_result',
                        lambda **kw: events.append(('db_final', kw)) or True)
    cloudflare = importlib.import_module('shared.src.lib.utils.cloudflare_utils')
    monkeypatch.setattr(cloudflare, 'upload_verification_review_markdown',
                        lambda **kw: {'success': True, 'url': 'https://r2/review.md', 'path': 'x/review.md'})
    return ex, events, seen


def _context(success=True):
    ctx = ScriptExecutionContext('TC_ORDER')
    ctx.script_result_id = 'sr-1'
    ctx.capture_artifacts = False  # no final screenshot / video in this unit
    ctx.overall_success = success
    ctx.selected_device = SimpleNamespace(navigation_context={'script_id': 'sr-1', 'script_name': 'TC_ORDER',
                                                              'script_context': 'testcase'},
                                          device_model='host_vnc', device_id='host', device_name='web')
    return ctx


def _kinds(events):
    return [e if isinstance(e, str) else e[0] for e in events]


def test_head_closes_the_browser_and_writes_the_verdict_before_any_report_work(finalize_world, dom_session):
    ex, events, seen = finalize_world
    ctx = _context()
    ctx.start_stdout_capture()
    print('a line of this run')

    result = ex.finalize_execution_context(ctx, 'ui', success=True, defer_report=True)

    assert _kinds(events) == ['power', 'release', 'close_browser', 'db_outcome'], events
    outcome = events[-1][1]
    assert outcome['success'] is True and outcome['execution_time_ms'] == ctx.baseline_execution_time_ms
    assert result['deferred'] is True and callable(result['report_tail'])
    assert result['report_url'] == '' and result['execution_time_ms'] == ctx.baseline_execution_time_ms
    # Everything owned by the device, not the report, is released before this returns.
    assert ctx.original_stdout is None, 'log capture stopped'
    assert 'script_id' not in ctx.selected_device.navigation_context, 'device script context cleared'
    assert 'report' not in _kinds(events), 'no report work before the caller can say completed'


def test_tail_uploads_this_runs_dom_captures_after_the_next_run_reset_and_overwrote_them(finalize_world, dom_session):
    ex, events, seen = finalize_world
    ctx = _context()
    ctx.start_stdout_capture()
    print('a line of this run')
    result = ex.finalize_execution_context(ctx, 'ui', success=True, defer_report=True)

    # The next run starts: it resets the session and writes its own 01_todos_dom.txt.
    dom_capture.reset_dom_captures()
    dom_session.write_text('<html>run B</html>', encoding='utf-8')

    final = result['report_tail']()

    assert _kinds(events) == ['power', 'release', 'close_browser', 'db_outcome', 'report', 'db_final'], events
    inputs = seen['detached_inputs']
    assert seen['dom_contents'] == ['<html>run A</html>'], 'the copy, not the overwritten original'
    assert os.path.basename(inputs['dom_captures'][0]['path']) == '01_todos_dom.txt', 'same remote name'
    assert 'a line of this run' in inputs['stdout']
    assert not os.path.exists(inputs['dom_dir']), 'the copies are removed after the upload'
    db_final = events[-1][1]
    assert db_final['html_report_r2_path'] == 'reports/x/report.html'
    assert db_final['logs_r2_path'] == 'script-logs/x/execution.txt'
    assert db_final['execution_time_ms'] == ctx.baseline_execution_time_ms
    assert final['report_url'] == 'https://r2/report.html'


def test_without_defer_the_report_runs_inline_as_before(finalize_world, dom_session):
    ex, events, seen = finalize_world
    ctx = _context()

    result = ex.finalize_execution_context(ctx, 'ui', success=True)

    assert _kinds(events) == ['power', 'release', 'close_browser', 'report', 'db_final'], 'no early write'
    assert seen['detached_inputs'] is None
    assert 'report_tail' not in result and result['report_url'] == 'https://r2/report.html'


def test_generate_report_for_context_uses_the_frozen_inputs(monkeypatch):
    """The tail must not read the (next run's) globals, nor re-time the run."""
    ex = ScriptExecutor('TC_FROZEN')
    ctx = _context()
    ctx.baseline_execution_time_ms = 12345
    monkeypatch.setattr(ctx, 'upload_screenshots_to_r2', lambda: {})
    monkeypatch.setattr(ex, '_merge_final_metadata', lambda c: {})
    got = {}

    def fake_upload(**kw):
        got.update(kw)
        return {'success': True, 'report_url': 'u', 'report_path': 'p', 'logs_url': 'l', 'logs_path': 'lp'}

    monkeypatch.setattr(script_executor_mod, 'generate_and_upload_script_report', fake_upload)
    frozen = {'stdout': 'frozen log\n', 'dom_captures': [{'path': '/tmp/copy/01_x_dom.txt'}],
              'ui_dumps': ('', 0), 'dom_dir': ''}

    ex.generate_report_for_context(ctx, {'device_model': 'host_vnc'}, {}, 'ui', detached_inputs=frozen)

    assert got['stdout'] == 'frozen log\n'
    assert got['dom_captures'] == frozen['dom_captures']
    assert got['ui_dumps'] == ('', 0)
    assert got['execution_time'] == 12345


# ---------------------------------------------------------------------------
# Detached output: the tail's prints stay out of the next run's capture
# ---------------------------------------------------------------------------

def test_a_detached_thread_does_not_write_into_another_runs_capture():
    journal = io.StringIO()
    saved = sys.stdout
    sys.stdout = journal
    try:
        run_b = ScriptExecutionContext('TC_B')
        run_b.start_stdout_capture()

        def tail():
            with detached.detached_output():
                print('tail of run A')

        worker = threading.Thread(target=tail)
        worker.start()
        worker.join()
        print('line of run B')
        run_b.stop_stdout_capture()
    finally:
        sys.stdout = saved

    captured = run_b.get_captured_stdout()
    assert 'line of run B' in captured
    assert 'tail of run A' not in captured
    assert 'tail of run A' in journal.getvalue(), 'still in the journal'


def test_a_detached_thread_bypasses_a_blocks_log_buffer():
    block_logs, run_log = io.StringIO(), io.StringIO()
    block_stdout = phase_timing.PhaseLinePassthrough(block_logs, run_log)

    def tail():
        with detached.detached_output():
            block_stdout.write('⏱ fin.video_extract 2364 ms\n')
            block_stdout.write('uploading report\n')

    worker = threading.Thread(target=tail)
    worker.start()
    worker.join()
    block_stdout.write('step line\n')

    assert block_logs.getvalue() == 'step line\n'
    assert run_log.getvalue() == '⏱ fin.video_extract 2364 ms\nuploading report\n'


def test_detached_is_per_thread_and_ends_with_the_block():
    assert detached.is_detached() is False
    with detached.detached_output():
        assert detached.is_detached() is True
        other = []
        t = threading.Thread(target=lambda: other.append(detached.is_detached()))
        t.start()
        t.join()
        assert other == [False]
    assert detached.is_detached() is False


# ---------------------------------------------------------------------------
# script_results: the early write never queues; the final write does, once
# ---------------------------------------------------------------------------

class _Table:
    def __init__(self, log):
        self.log = log

    def update(self, data):
        self.log.append(('update', data))
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return SimpleNamespace(data=[{'script_name': 'TC', 'metadata': {}}])


def test_the_early_outcome_write_does_not_enqueue_and_the_final_one_does(monkeypatch):
    log, queued = [], []
    monkeypatch.setattr(script_results_db, 'get_supabase', lambda: SimpleNamespace(table=lambda _n: _Table(log)))
    redis_queue = types.ModuleType('shared.src.lib.utils.redis_queue')
    redis_queue.get_queue_processor = lambda: SimpleNamespace(add_script_to_queue=lambda sid, data: queued.append(sid))
    monkeypatch.setitem(sys.modules, 'shared.src.lib.utils.redis_queue', redis_queue)

    assert script_results_db.record_script_execution_outcome('sr-1', True, 9000) is True
    assert queued == []
    early = log[-1][1]
    assert early['success'] is True and early['execution_time_ms'] == 9000 and 'completed_at' in early
    assert 'html_report_r2_path' not in early

    script_results_db.update_script_execution_result('sr-1', True, 9000, html_report_r2_path='r/p.html')
    assert queued == ['sr-1']
    assert log[-1][1]['html_report_r2_path'] == 'r/p.html'


# ---------------------------------------------------------------------------
# The async worker: status 'completed' first, then the tail in the background
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,mode', [(None, 'pass'), ('', 'pass'), ('pass', 'pass'), ('on', 'pass'),
                                      ('true', 'pass'), ('ALL', 'all'), ('off', 'off'), ('0', 'off'),
                                      ('false', 'off'), ('bogus', 'pass')])
def test_background_report_mode(monkeypatch, raw, mode):
    if raw is None:
        monkeypatch.delenv('VPT_TESTCASE_BACKGROUND_REPORT', raising=False)
    else:
        monkeypatch.setenv('VPT_TESTCASE_BACKGROUND_REPORT', raw)
    assert testcase_executor.background_report_mode() == mode


class _FakeScriptExecutor:
    """Stands in for ScriptExecutor in the worker: a finalize head, and a tail that blocks
    until the test lets it go, so the test can look at the status while it runs."""
    calls = []
    tail_started = None
    release_tail = None
    tail_threads = []

    def __init__(self, name):
        self.name = name
        self.current_trigger = {}

    def finalize_execution_context(self, context, ui, success=None, error_message=None,
                                   generate_report=True, defer_report=False):
        cls = type(self)
        cls.calls.append({'defer_report': defer_report, 'success': success})
        if not defer_report:
            return {'success': True, 'report_url': 'https://r2/inline.html', 'logs_url': 'https://r2/inline.txt'}

        def tail():
            cls.tail_threads.append(threading.current_thread().name)
            cls.tail_started.set()
            assert cls.release_tail.wait(5)
            print('tail print that must not reach a capture')
            return {'success': True, 'report_url': 'https://r2/late.html', 'logs_url': 'https://r2/late.txt',
                    'report_path': 'reports/late.html'}

        return {'success': True, 'deferred': True, 'report_tail': tail, 'report_url': '', 'logs_url': ''}


@pytest.fixture
def worker_world(monkeypatch):
    _FakeScriptExecutor.calls = []
    _FakeScriptExecutor.tail_threads = []
    _FakeScriptExecutor.tail_started = threading.Event()
    _FakeScriptExecutor.release_tail = threading.Event()
    monkeypatch.setattr(script_executor_mod, 'ScriptExecutor', _FakeScriptExecutor)
    monkeypatch.setattr(testcase_executor, 'record_script_execution_start', lambda **kw: 'sr-1')
    monkeypatch.setattr(testcase_executor, 'resolve_script_identity', lambda *a, **k: {})
    monkeypatch.setattr(testcase_executor, 'emit_execution_event', lambda *a, **k: None)
    device = SimpleNamespace(device_id='host', navigation_context={}, _get_controller=lambda _n: None)
    host = SimpleNamespace(get_devices=lambda: [device], host_name='host-clone-3')
    controller_manager = types.ModuleType('backend_host.src.controllers.controller_manager')
    controller_manager.get_host = lambda device_ids=None: host
    monkeypatch.setitem(sys.modules, 'backend_host.src.controllers.controller_manager', controller_manager)
    device_utils = importlib.import_module('shared.src.lib.utils.device_utils')
    monkeypatch.setattr(device_utils, 'capture_screenshot', lambda *a, **k: None)

    def build(success=True):
        ex = Executor()
        ex.validator = SimpleNamespace(validate_graph=lambda *a, **k: (True, [], []))
        ex._create_start_metadata = lambda **kw: {}
        ex._set_running_log_path = lambda *a, **k: None
        ex._starts_from_entry = lambda device: False
        ex._initialize_script_inputs_and_variables = lambda *a, **k: None
        ex._build_execution_summary = lambda *a, **k: ''

        async def graph(*_a, **_k):
            return {'success': success, 'result_type': 'success' if success else 'failure',
                    'error': None if success else 'reached FAILURE block'}

        ex._execute_graph_with_tracking = graph
        ex._executions['e1'] = {'execution_id': 'e1', 'status': 'running', 'start_time': 0, 'result': None}
        return ex

    return build


def _run_worker(ex):
    ex._execute_testcase_async_worker('e1', {'nodes': [], 'edges': []}, 'team', 'host-clone-3', 'host',
                                      'web', 'host_vnc', 'ui', 'TC_WORKER')


def test_worker_reports_completed_while_the_report_tail_still_runs(worker_world, monkeypatch):
    monkeypatch.delenv('VPT_TESTCASE_BACKGROUND_REPORT', raising=False)
    ex = worker_world(success=True)

    _run_worker(ex)  # returns once the status is set; the tail is still blocked

    assert _FakeScriptExecutor.calls == [{'defer_report': True, 'success': True}]
    assert _FakeScriptExecutor.tail_started.wait(5)
    status = ex.get_execution_status('e1')
    assert status['status'] == 'completed'
    assert status['result']['success'] is True and status['result']['report_url'] == ''
    assert status['report_pending'] is True
    assert _FakeScriptExecutor.tail_threads[0].startswith('report-tail-')

    _FakeScriptExecutor.release_tail.set()
    for t in threading.enumerate():
        if t.name.startswith('report-tail-'):
            t.join(5)

    status = ex.get_execution_status('e1')
    assert status['report_pending'] is False
    assert status['result']['report_url'] == 'https://r2/late.html', 'later polls get the report'


def test_a_failed_run_keeps_the_report_inline_by_default(worker_world, monkeypatch):
    monkeypatch.delenv('VPT_TESTCASE_BACKGROUND_REPORT', raising=False)
    ex = worker_world(success=False)

    _run_worker(ex)

    assert _FakeScriptExecutor.calls == [{'defer_report': False, 'success': False}]
    status = ex.get_execution_status('e1')
    assert status['status'] == 'completed'
    assert status['result']['report_url'] == 'https://r2/inline.html'


@pytest.mark.parametrize('raw,success,deferred', [('all', False, True), ('off', True, False)])
def test_the_switch(worker_world, monkeypatch, raw, success, deferred):
    monkeypatch.setenv('VPT_TESTCASE_BACKGROUND_REPORT', raw)
    ex = worker_world(success=success)
    _FakeScriptExecutor.release_tail.set()

    _run_worker(ex)

    assert _FakeScriptExecutor.calls == [{'defer_report': deferred, 'success': success}]
    for t in threading.enumerate():
        if t.name.startswith('report-tail-'):
            t.join(5)


def test_report_tails_of_one_device_run_one_at_a_time(monkeypatch):
    ex = Executor()
    order, gate, a_started = [], threading.Event(), threading.Event()

    def tail(name, wait=False):
        def run():
            order.append(f'{name} start')
            if wait:
                a_started.set()
                assert gate.wait(5)
            order.append(f'{name} end')
            return {'success': True}
        return run

    first = ex._start_report_tail('a' * 8, 'host', tail('A', wait=True))
    assert a_started.wait(5)
    second = ex._start_report_tail('b' * 8, 'host', tail('B'))
    other_device = ex._start_report_tail('c' * 8, 'device2', tail('C'))
    other_device.join(5)
    assert 'C end' in order, 'another device does not wait'
    assert 'B start' not in order, order
    gate.set()
    first.join(5)
    second.join(5)
    assert order.index('A end') < order.index('B start'), order
