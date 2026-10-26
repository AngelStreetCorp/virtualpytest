"""BUG-0089 — a run that dies on a library the platform could not fetch must say so.

The platform resolves a virtual script's `_script_libs` best-effort: a declared
library it cannot fetch is SKIPPED, on purpose (a declared library may be
optional), and the run still fails with a bare import error. What was missing was
legibility: the run blamed the author's file ("the file is likely corrupted or
has a syntax/import error") or said nothing at all, and never named the library
the platform could not find.

Covers:
  - the resolver still SKIPS a missing library (never raises) and reports it;
  - the startup-crash error names the library and says the PLATFORM could not
    find it, in the error message, in the row's error_msg and in the run's log;
  - the in-body import path names it in the log and in the row's error_msg;
  - an unrelated failure is NOT blamed on a skipped library;
  - a run whose libraries all resolve says nothing about missing libraries.

Pure unit tests: no DB, no device, no HTTP. The report and script_results
writers the executor calls are replaced by local fakes.
"""
import inspect
import os
import sys
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


# The child's output when the script imports a library at the top of its file:
# the child dies before the @script decorator runs, so the traceback is all the
# parent has. stderr is merged into stdout by the executor.
STARTUP_CRASH_OUTPUT = (
    "Traceback (most recent call last):\n"
    '  File "/app/test_scripts/.vs_0f0f.py", line 1, in <module>\n'
    "    import shared_helper\n"
    "ModuleNotFoundError: No module named 'shared_helper'\n"
)

# The child's output when the script fails for a reason that has nothing to do
# with the libraries it declared.
UNRELATED_CRASH_OUTPUT = (
    "Traceback (most recent call last):\n"
    '  File "/app/test_scripts/.vs_0f0f.py", line 9, in <module>\n'
    "    raise ValueError('something else went wrong')\n"
    "ValueError: something else went wrong\n"
)

MISSING_LIB = 'shared_helper'


def _missing_env_var() -> str:
    """The env var the parent hands the skipped library names to the child in."""
    from shared.src.lib.executors import script_executor
    return getattr(script_executor, 'MISSING_LIBRARY_ENV_VAR', 'VPT_MISSING_SCRIPT_LIBS')


def _executor():
    """A ScriptExecutor with nothing set up: only the reporting path is used."""
    from shared.src.lib.executors.script_executor import ScriptExecutor
    executor = ScriptExecutor.__new__(ScriptExecutor)
    executor.device_id = 'device-under-test'
    executor.device_model = 'model-under-test'
    executor.host_name = 'host-under-test'
    executor.script_name = 'a_virtual_script'
    return executor


def _patch_report_and_db(monkeypatch) -> dict:
    """Replace the report upload and the script_results writers with local fakes.

    The executor imports them inside the function it calls, so patching the
    module attributes is what the call picks up.
    """
    import shared.src.lib.database.script_results_db as db_mod
    import shared.src.lib.utils.report_generation_utils as report_mod

    calls = {}

    def fake_report(**kwargs):
        calls['report'] = kwargs
        return {
            'report_url': 'https://example.invalid/report',
            'report_path': 'report/path-under-test',
            'logs_url': 'https://example.invalid/logs',
            'logs_path': 'logs/path-under-test',
        }

    def fake_start(**kwargs):
        calls['start'] = kwargs
        return 'script-result-id-under-test'

    def fake_update(**kwargs):
        calls['update'] = kwargs
        return None

    monkeypatch.setattr(report_mod, 'generate_and_upload_script_report', fake_report)
    monkeypatch.setattr(db_mod, 'record_script_execution_start', fake_start)
    monkeypatch.setattr(db_mod, 'update_script_execution_result', fake_update)
    return calls


def _resolve(root_source: str, sources: dict):
    """Resolve libs and collect the names the platform could not fetch.

    `sources` is a fake DB: a name that is not in it cannot be fetched.
    """
    from shared.src.lib.executors.script_executor import resolve_virtual_script_libs
    missing = []
    if 'missing' in inspect.signature(resolve_virtual_script_libs).parameters:
        resolved = resolve_virtual_script_libs(
            root_source, lambda name: sources.get(name), missing=missing)
    else:
        resolved = resolve_virtual_script_libs(root_source, lambda name: sources.get(name))
    return resolved, missing


# --- the resolver: the skip stays a skip, and it is reported -----------------

def test_missing_library_is_skipped_not_raised_and_is_reported():
    """The skip stays a skip (never fatal), and the platform says which one."""
    sources = {'present_lib': "PRESENT = 1\n"}
    resolved, missing = _resolve('_script_libs = ["present_lib", "absent_lib"]\n', sources)

    # The skip stays a skip: the library the platform could not fetch is simply
    # absent from what got materialized.
    assert resolved == {'present_lib': "PRESENT = 1\n"}
    # ... and it is reported, so the run can name it.
    assert missing == ['absent_lib']


def test_skipped_library_is_still_logged(capsys):
    """The line that records the skip must stay: it is the record of the skip."""
    _resolve('_script_libs = ["absent_lib"]\n', {})
    printed = capsys.readouterr().out
    assert "library 'absent_lib' not found" in printed


def test_all_libraries_resolve_leaves_nothing_missing():
    """A script whose libraries all resolve is untouched."""
    sources = {'a': "A = 1\n", 'b': "B = 2\n"}
    resolved, missing = _resolve('_script_libs = ["a", "b"]\n', sources)
    assert resolved == sources
    assert missing == []


# --- the startup crash (the import at the top of the file) ------------------

def test_startup_crash_error_names_the_library_the_platform_could_not_find(monkeypatch):
    """The run's error message names the library and blames the platform."""
    calls = _patch_report_and_db(monkeypatch)
    executor = _executor()
    executor._missing_virtual_libs = [MISSING_LIB]

    result = executor._persist_startup_crash_artifacts(
        script_name='a_virtual_script',
        parameters='',
        stdout=STARTUP_CRASH_OUTPUT,
        exit_code=1,
        execution_time_ms=12,
    )
    error = result.get('error') or ''

    assert 'could not be found' in error.lower(), error
    assert 'platform' in error.lower(), error
    assert MISSING_LIB in error, error
    # The author's file is fine: the platform could not fetch the library.
    assert 'likely corrupted' not in error, error

    # The row carries the same message...
    row_error = (calls.get('update') or {}).get('error_msg') or ''
    assert MISSING_LIB in row_error, row_error
    assert 'could not be found' in row_error.lower(), row_error

    # ... and so does the run's log.
    log_text = (calls.get('report') or {}).get('stdout') or ''
    assert MISSING_LIB in log_text, log_text
    assert 'could not be found' in log_text.lower(), log_text


def test_startup_crash_for_an_unrelated_reason_keeps_its_own_message(monkeypatch):
    """A skipped library must not be blamed for a failure that is not its fault."""
    calls = _patch_report_and_db(monkeypatch)
    executor = _executor()
    executor._missing_virtual_libs = [MISSING_LIB]

    result = executor._persist_startup_crash_artifacts(
        script_name='a_virtual_script',
        parameters='',
        stdout=UNRELATED_CRASH_OUTPUT,
        exit_code=1,
        execution_time_ms=12,
    )
    error = result.get('error') or ''

    assert 'something else went wrong' in error, error
    assert 'could not be found' not in error.lower(), error
    assert MISSING_LIB not in error, error


def test_startup_crash_without_any_skipped_library_says_nothing_about_libraries(monkeypatch):
    """A run whose libraries all resolved keeps the message it had."""
    _patch_report_and_db(monkeypatch)
    executor = _executor()
    executor._missing_virtual_libs = []

    result = executor._persist_startup_crash_artifacts(
        script_name='a_virtual_script',
        parameters='',
        stdout=UNRELATED_CRASH_OUTPUT,
        exit_code=1,
        execution_time_ms=12,
    )
    error = result.get('error') or ''

    assert 'not found' not in error.lower(), error
    assert 'could not be found' not in error.lower(), error


# --- the in-body import (the decorator already started) ---------------------

def test_unexpected_error_in_the_script_body_names_the_library(monkeypatch, capsys):
    """The run's log says which library the platform could not find."""
    monkeypatch.setenv(_missing_env_var(), MISSING_LIB)
    from shared.src.lib.executors.script_executor import handle_unexpected_error

    with pytest.raises(SystemExit):
        handle_unexpected_error(
            'a_virtual_script',
            ModuleNotFoundError(f"No module named '{MISSING_LIB}'", name=MISSING_LIB),
        )
    printed = capsys.readouterr().out

    assert 'could not be found' in printed.lower(), printed
    assert 'platform' in printed.lower(), printed
    assert MISSING_LIB in printed, printed


def test_unexpected_error_in_the_script_body_reaches_the_row_error_message(monkeypatch):
    """The row's error_msg names the library too, not only the log."""
    monkeypatch.setenv(_missing_env_var(), MISSING_LIB)
    from shared.src.lib.executors.script_executor import handle_unexpected_error

    executor = _executor()
    captured = {}

    def fake_finalize(context, userinterface_name, **kwargs):
        captured['error_message'] = getattr(context, 'error_message', '')

    executor.finalize_execution_context = fake_finalize

    with pytest.raises(SystemExit):
        handle_unexpected_error(
            'a_virtual_script',
            ModuleNotFoundError(f"No module named '{MISSING_LIB}'", name=MISSING_LIB),
        )

    context = SimpleNamespace(overall_success=False, error_message='')
    with pytest.raises(SystemExit):
        executor.cleanup_and_exit(context, None)

    message = captured.get('error_message') or ''
    assert MISSING_LIB in message, message
    assert 'could not be found' in message.lower(), message


def test_unrelated_error_in_the_script_body_is_not_blamed_on_a_skipped_library(monkeypatch, capsys):
    """An unrelated failure keeps its own message: no false attribution."""
    monkeypatch.setenv(_missing_env_var(), MISSING_LIB)
    from shared.src.lib.executors.script_executor import handle_unexpected_error

    with pytest.raises(SystemExit):
        handle_unexpected_error('a_virtual_script', ValueError('something else went wrong'))
    printed = capsys.readouterr().out

    assert 'something else went wrong' in printed, printed
    assert 'could not be found' not in printed.lower(), printed
    assert MISSING_LIB not in printed, printed


def test_import_error_about_another_module_is_not_blamed_on_a_skipped_library(monkeypatch, capsys):
    """A module the platform never had anything to do with keeps its own message."""
    monkeypatch.setenv(_missing_env_var(), MISSING_LIB)
    from shared.src.lib.executors.script_executor import handle_unexpected_error

    with pytest.raises(SystemExit):
        handle_unexpected_error(
            'a_virtual_script',
            ModuleNotFoundError("No module named 'some_other_module'"),
        )
    printed = capsys.readouterr().out

    assert "No module named 'some_other_module'" in printed, printed
    assert 'could not be found' not in printed.lower(), printed
    assert MISSING_LIB not in printed, printed
