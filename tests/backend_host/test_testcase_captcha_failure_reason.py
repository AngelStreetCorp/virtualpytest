"""
tests/backend_host/test_testcase_captcha_failure_reason.py -- a web testcase that fails on a captcha says so.

Measured 2026-10-19 (sauce-demo.myshopify.com on host-clone-1): TC_SAUCEDEMO_01_login_valid, 03_logout and
14_full_purchase failed on every hourly run with only "Test case reached FAILURE block". The store's customer
login shows an hCaptcha, so the login never completes for an automated browser; nothing in the report said so.
Now the failed step records why, the step's error names the captcha when one is on the page, and the run's
error names the step.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.backend_host.test_testcase_fresh_start import _load_executor_module  # noqa: E402

testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor


def _executor(page_value):
    ex = Executor()
    web = SimpleNamespace(execute_javascript=AsyncMock(return_value={'success': True, 'result': page_value}))
    ex.device = SimpleNamespace(get_controllers=lambda kind: [web] if kind == 'web' else [])
    return ex, web


def _fail(ex, ctx, error='verification failed'):
    node = {'id': 'nav-dashboard', 'data': {'label': 'Login and reach Dashboard'}}
    result = {'success': False, 'error': error}
    asyncio.run(ex._explain_block_failure(node, result, ctx))
    return result


def test_failed_step_on_a_captcha_page_names_the_captcha():
    ex, _ = _executor('hCaptcha')
    ctx = SimpleNamespace()
    result = _fail(ex, ctx)
    assert 'hCaptcha' in result['error'] and 'automated test cannot pass' in result['error']
    assert Executor._failure_terminal_error(ctx).startswith("Blocked by hCaptcha captcha at step 'Login and reach Dashboard'")


def test_failed_step_without_captcha_names_the_step_and_error():
    ex, _ = _executor('')
    ctx = SimpleNamespace()
    result = _fail(ex, ctx, 'element not found')
    assert result['error'] == 'element not found'
    assert Executor._failure_terminal_error(ctx) == "Failed at step 'Login and reach Dashboard': element not found"


def test_run_without_a_failed_block_keeps_the_old_message():
    assert Executor._failure_terminal_error(SimpleNamespace()) == 'Test case reached FAILURE block'


def test_passing_block_is_not_probed_and_probe_errors_are_swallowed():
    ex, web = _executor('hCaptcha')
    asyncio.run(ex._explain_block_failure({'id': 'a'}, {'success': True}, SimpleNamespace()))
    web.execute_javascript.assert_not_awaited()
    web.execute_javascript.side_effect = RuntimeError('page closed')
    assert asyncio.run(ex._detect_captcha()) == ''
