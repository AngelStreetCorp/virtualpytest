"""Unit tests: campaign steps can run virtual scripts.

Covers the deployment-scheduler / Run-Tests campaign path threading a per-step
`virtual_script_id` (and the run's `team_id`) into `ScriptExecutor.execute_script`,
so a scheduled deployment step resolves a DB-stored virtual script (co-materializing
its `_script_libs`) instead of a disk file. Disk steps must stay unchanged.

No DB, no device, no HTTP: `ScriptExecutor`, the testcase lookup, and the device
lookup are stubbed so `CampaignExecutor._execute_single_script` runs offline.
Repo root is 2 levels up from tests/backend_server/ (same bootstrap as the other
unit tests here).
"""
import os
import sys

import pytest
from unittest.mock import MagicMock, patch

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# The executor imports get_device_by_id lazily from backend_host.src.lib.utils.host_utils.
# Importing anything under backend_host.src runs backend_host/src/__init__.py, which pulls
# in every controller and therefore OpenCV. CI runners have no cv2, and patch() must be able
# to import its target, so on such machines register stub packages for that dotted path
# carrying just the symbol the tests replace anyway. No-op where the real import works.
try:
    import backend_host.src.lib.utils.host_utils  # noqa: F401
except ImportError:
    import importlib
    import types
    _parent = importlib.import_module("backend_host")
    for _name in (
        "backend_host.src",
        "backend_host.src.lib",
        "backend_host.src.lib.utils",
        "backend_host.src.lib.utils.host_utils",
    ):
        _mod = sys.modules.get(_name)
        if _mod is None:
            _mod = types.ModuleType(_name)
            _mod.__path__ = []  # behaves as a package for the importer
            sys.modules[_name] = _mod
        setattr(_parent, _name.rsplit(".", 1)[1], _mod)
        _parent = _mod
    _parent.get_device_by_id = lambda device_id: None

pytestmark = pytest.mark.unit  # pure executor test: no live server, no probe

TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"


def _make_context(executor):
    """Minimal ready-to-run campaign context (host + team + os set)."""
    from shared.src.lib.executors.campaign_executor import CampaignExecutionContext
    context = CampaignExecutionContext("camp-1", "sample-app_tv_smoke")
    context.host = MagicMock(host_name="sample-app-dongle")
    context.team_id = TEAM_ID
    context.current_os = "linux"
    return context


def _run_step(script_config):
    """Run one campaign step with all I/O stubbed; return the recorded
    execute_script call kwargs plus whether the testcase lookup was consulted."""
    from shared.src.lib.executors.campaign_executor import CampaignExecutor

    executor = CampaignExecutor()
    context = _make_context(executor)
    campaign_config = {
        "device_id": "device1",
        "device": "device1",
        "host": "sample-app-dongle",
        "userinterface_name": "sample-app",
        "team_id": TEAM_ID,
    }

    fake_script_executor = MagicMock()
    fake_script_executor.execute_script.return_value = {
        "exit_code": 0,
        "script_success": True,
        "stdout": "",
        "report_url": "",
        "logs_url": "",
    }

    testcase_lookup = MagicMock(return_value=None)

    with patch(
        "shared.src.lib.executors.script_executor.ScriptExecutor",
        return_value=fake_script_executor,
    ), patch(
        "shared.src.lib.database.testcase_db.get_testcase_by_name",
        testcase_lookup,
    ), patch(
        "backend_host.src.lib.utils.host_utils.get_device_by_id",
        MagicMock(return_value=None),
    ):
        result = executor._execute_single_script(context, campaign_config, script_config, 1)

    assert fake_script_executor.execute_script.called, "execute_script was not called"
    _args, kwargs = fake_script_executor.execute_script.call_args
    return result, kwargs, testcase_lookup


def test_virtual_script_step_threads_id_and_team():
    """A step carrying virtual_script_id runs it as a virtual script, scoped to the
    run's team, and never falls through to the disk testcase lookup."""
    result, kwargs, testcase_lookup = _run_step({
        "order": 0,
        "parameters": {},
        "script_name": "sample-app_s1_cold_start_picker",
        "virtual_script_id": "vs-123",
    })

    assert result["success"] is True
    assert kwargs.get("virtual_script_id") == "vs-123"
    assert kwargs.get("team_id") == TEAM_ID
    # Virtual steps skip the DB testcase auto-detect entirely.
    testcase_lookup.assert_not_called()


def test_disk_script_step_unchanged():
    """A step with no virtual_script_id keeps disk behavior: execute_script is
    called with virtual_script_id=None (never routed to virtual materialization)."""
    _result, kwargs, _testcase_lookup = _run_step({
        "order": 0,
        "parameters": {},
        "script_name": "sample-app/sample-app_s1_cold_start_picker.py",
    })

    assert kwargs.get("virtual_script_id") is None
