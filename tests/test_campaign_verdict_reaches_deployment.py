"""BUG-0899: a campaign whose every check failed must not be recorded as a success.

`_build_success_result` hard-coded `"success": True`, and the deployment row and the
async route's final_status both read that key. These tests drive the real executor
(everything around it is stubbed; no network, host, device or database) and check
the verdict the consumers read.

    timeout 300 python3 -m pytest tests/test_campaign_verdict_reaches_deployment.py -q
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

TEAM_ID = "team-1"
SCHEDULER = Path(_repo_root) / "backend_host/src/services/deployment_scheduler.py"


def _run(monkeypatch, outcomes, abort=False):
    from shared.src.lib.executors import campaign_executor as ce

    monkeypatch.setattr(ce, "record_campaign_execution_start", lambda **kw: "ce-1")
    monkeypatch.setattr(ce, "update_campaign_execution_result", lambda **kw: True)
    monkeypatch.setattr(ce, "add_script_result_to_campaign", lambda *a, **k: None)

    def _setup(self, context, cfg):
        context.host = MagicMock(host_name="placeholder-host")
        context.team_id = TEAM_ID
        context.current_os = "linux"
        return True

    def _exec(self, context, cfg, script_cfg, order):
        return {"script_name": script_cfg["script_name"], "script_type": "x",
                "execution_order": order, "success": outcomes[order - 1],
                "script_result_id": None, "execution_time_ms": 1}

    monkeypatch.setattr(ce.CampaignExecutor, "_setup_campaign_environment", _setup)
    monkeypatch.setattr(ce.CampaignExecutor, "_generate_orchestrator_artifacts",
                        lambda self, c, cfg: None)
    monkeypatch.setattr(ce.CampaignExecutor, "_execute_single_script", _exec)

    executor = ce.CampaignExecutor()
    if abort:
        # The abort lands while the run is still going, so it ends "aborted".
        orig = _exec

        def _exec_abort(self, context, cfg, script_cfg, order):
            self._abort_requested = True
            return orig(self, context, cfg, script_cfg, order)

        monkeypatch.setattr(ce.CampaignExecutor, "_execute_single_script", _exec_abort)
    cfg = {
        "campaign_id": "c", "name": "c", "device": "auto", "device_id": "d1",
        "host": "placeholder-host", "userinterface_name": "ui", "team_id": TEAM_ID,
        "execution_config": {"continue_on_failure": True},
        "script_configurations": [{"script_name": f"s{i}", "script_type": "s"}
                                  for i in range(len(outcomes))],
    }
    return executor.execute_campaign(cfg)


def _async_status(monkeypatch, result):
    # The route module pulls in an ML package this test has no use for.
    for mod in ("sklearn", "sklearn.feature_extraction", "sklearn.feature_extraction.text",
                "sklearn.metrics", "sklearn.metrics.pairwise"):
        try:
            __import__(mod)
        except ImportError:
            monkeypatch.setitem(sys.modules, mod, MagicMock())
    from backend_host.src.routes import host_campaign_routes as routes

    executor = MagicMock()
    executor.execute_campaign.return_value = result
    routes.running_campaigns["x1"] = {"status": "running"}
    routes.execute_campaign_async({"campaign_id": "c"}, "x1", None, executor)
    return routes.running_campaigns.pop("x1")["status"]


def _deployment_row(result):
    """Run the scheduler's own verdict statements on `result` and return the row it writes."""
    src = SCHEDULER.read_text()
    verdict = re.search(r"^\s*(script_success = campaign_result\.get\(.*\))$", src, re.M).group(1)
    status = re.search(r"'status': ('completed' if script_success else 'failed'),", src).group(1)
    ns = {"campaign_result": result}
    exec(verdict, ns)
    return {"status": eval(status, ns), "success": ns["script_success"]}


def test_all_checks_failed_result_verdict_is_false(monkeypatch):
    result = _run(monkeypatch, [False, False])
    assert result["success"] is False, f"result['success']={result['success']!r}"
    assert result["success"] == result["overall_success"]


def test_all_checks_failed_deployment_row_says_failed(monkeypatch):
    row = _deployment_row(_run(monkeypatch, [False, False]))
    assert row == {"status": "failed", "success": False}, row


def test_all_checks_failed_async_status_is_not_completed(monkeypatch):
    status = _async_status(monkeypatch, _run(monkeypatch, [False, False]))
    assert status == "failed", status


def test_all_checks_passed_stays_completed(monkeypatch):
    result = _run(monkeypatch, [True, True])
    assert result["success"] is True and result["overall_success"] is True
    assert _deployment_row(result) == {"status": "completed", "success": True}
    assert _async_status(monkeypatch, result) == "completed"


def test_aborted_campaign_keeps_aborted_reading(monkeypatch):
    result = _run(monkeypatch, [True, True], abort=True)
    assert result["success"] is False
    assert result.get("aborted") is True, result.get("aborted")
    assert _async_status(monkeypatch, result) == "aborted"
