"""BUG-0391: a virtual script's report carries the virtual script's name, not the
`@script("…")` name typed inside its source."""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from shared.src.lib.executors.script_executor import ScriptExecutor  # noqa: E402


def test_virtual_run_uses_virtual_script_name(monkeypatch):
    monkeypatch.setenv('VPT_VIRTUAL_SCRIPT_ID', 'abc')
    monkeypatch.setenv('VPT_SCRIPT_REF', 'smoke/smoke_goto_live')
    assert ScriptExecutor('goto_live', 'desc').script_name == 'smoke_goto_live'


def test_disk_run_keeps_decorator_name(monkeypatch):
    monkeypatch.delenv('VPT_VIRTUAL_SCRIPT_ID', raising=False)
    monkeypatch.setenv('VPT_SCRIPT_REF', 'device_get_info')
    assert ScriptExecutor('get_info', 'desc').script_name == 'get_info'


def test_virtual_run_without_ref_keeps_decorator_name(monkeypatch):
    monkeypatch.setenv('VPT_VIRTUAL_SCRIPT_ID', 'abc')
    monkeypatch.delenv('VPT_SCRIPT_REF', raising=False)
    assert ScriptExecutor('goto_live', 'desc').script_name == 'goto_live'
