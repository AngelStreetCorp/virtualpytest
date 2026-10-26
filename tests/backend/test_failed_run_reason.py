"""
tests/backend/test_failed_run_reason.py — a failed test is not a host that said nothing.

BUG-0759. `task_complete` filled in `error = result.get('stderr') or 'host reported no
script result'` whenever a run failed without an error of its own. But a script that ran
and printed `SCRIPT_SUCCESS:false` *did* report: the test failed, which is the outcome the
run exists to produce. Every such run was reported to its consumer as an infrastructure
fault, which sent a debugging detour after a ghost on 2026-10-22.
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

routes = importlib.import_module('backend_server.src.routes.server_script_routes')
_describe = routes._describe_failed_run
_derive = routes._derive_run_success


def _failed_test_result(**overrides):
    """What the host posts back for a test that ran and failed its check."""
    result = {
        'stdout': '❌ [youtube_video_check] Video was not playing during 25s monitoring window\nSCRIPT_SUCCESS:false',
        'stderr': '',                      # the executor merges stderr into stdout
        'exit_code': 0,                   # the process was fine; the test was not
        'script_success': False,          # the script's own verdict
        'script_result_id': '60be7382-4f85-4627-8019-679aa1fc5552',
        'report_url': 'https://…/report.html',
    }
    result.update(overrides)
    return result


# ── the case that was wrong ──────────────────────────────────────────────────────

def test_a_failed_test_is_not_reported_as_a_silent_host():
    assert 'host reported no script result' not in _describe(_failed_test_result())


def test_a_failed_test_says_it_failed_and_points_at_the_report():
    reason = _describe(_failed_test_result())

    assert 'failed' in reason.lower()
    assert 'report.html' in reason, "the consumer needs the report, not a sentence about the host"


def test_a_failed_test_without_a_report_still_says_the_test_failed():
    reason = _describe(_failed_test_result(report_url=None))

    assert 'failed' in reason.lower()
    assert 'host reported no script result' not in reason


def test_a_failed_test_is_derived_as_a_failure():
    """The verdict was already right; only the wording was wrong."""
    assert _derive(_failed_test_result(), None) is False


# ── the case the old wording did describe ────────────────────────────────────────

def test_a_silent_host_still_says_so():
    """No marker, no exit code, nothing: the host really did report nothing."""
    assert _describe({'exit_code': 1}) == 'host reported no script result'


def test_stderr_wins_over_the_generic_message():
    """When the host DID phrase the failure, its words are used."""
    result = _failed_test_result(stderr='Device host-clone-2:host is locked')

    assert _describe(result) == 'Device host-clone-2:host is locked'


def test_a_huge_stderr_is_truncated_rather_than_flooding_the_task():
    assert len(_describe(_failed_test_result(stderr='x' * 5000))) <= 500


# ── the call site ────────────────────────────────────────────────────────────────

def test_the_call_site_uses_the_new_description(monkeypatch):
    """`task_complete` must not keep its own copy of the old rule."""
    import inspect
    source = inspect.getsource(routes.task_complete)

    assert "_describe_failed_run(result)" in source
    assert "'host reported no script result'" not in source


@pytest.mark.parametrize('payload', [None, 'not-a-dict', {}])
def test_a_nonsense_payload_does_not_explode(payload):
    """The fallback has to survive whatever the host sends."""
    assert isinstance(_describe(payload), str)


def test_a_successful_marker_is_never_described():
    """Only failures get a reason; a pass must not acquire one."""
    result = _failed_test_result(script_success=True)

    assert _derive(result, None) is True