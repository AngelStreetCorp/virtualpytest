"""Tests for _derive_run_success — the "did this run actually pass?" rule (BUG-0089).

The bug: task_complete read "the host reported no error" as "the run passed". A host
that fails before launching the subprocess (virtual-script materialization denied by
filesystem permissions) returns {'success': False, 'exit_code': 1} and sends it as a
normal, non-error callback — so a script that never executed was recorded green with
no report.

The helper encodes the whole fix, so it is tested directly. Pure function, no server:

Run: pytest tests/shared/test_run_success_derivation.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.routes.server_script_routes import _derive_run_success  # noqa: E402


# --- The marker wins: it is the test's own verdict -------------------------------

@pytest.mark.parametrize("marker", [True, False])
def test_script_success_marker_is_authoritative(marker):
    """SCRIPT_SUCCESS: from the @script decorator outranks every other signal."""
    result = {"script_success": marker, "exit_code": 1 if marker else 0}
    assert _derive_run_success(result, error="something") is marker


# --- Real runs keep their old verdict --------------------------------------------

def test_clean_run_without_marker_still_passes():
    """A script that ran to completion with exit 0 and emitted no marker is a pass."""
    assert _derive_run_success({"exit_code": 0, "script_result_id": "abc"}, None) is True


def test_nonzero_exit_without_marker_fails():
    """A hard crash or kill leaves no marker — the exit code is the evidence."""
    assert _derive_run_success({"exit_code": 137}, None) is False


def test_transport_error_fails():
    assert _derive_run_success({}, "host unreachable") is False


# --- The BUG-0089 shapes ----------------------------------------------------------

def test_executor_early_return_fails():
    """The exact payload a host sends when materialization is denied: success False,
    exit_code 1, no marker, and NO error field — previously recorded as a pass."""
    result = {"success": False, "exit_code": 1, "stderr": "Permission denied"}
    assert _derive_run_success(result, None) is False


def test_empty_callback_fails():
    """No marker, no exit code, no script_result_id, no error. The host never ran
    anything; absence of evidence is not evidence of a pass."""
    assert _derive_run_success({}, None) is False


def test_non_dict_result_fails():
    """A malformed callback is not a pass either."""
    assert _derive_run_success(None, None) is False


def test_result_id_without_exit_code_passes():
    """A run that recorded a script_results row but reported no exit code did happen,
    so it is not caught by the "nothing came back" rule."""
    assert _derive_run_success({"script_result_id": "abc"}, None) is True
