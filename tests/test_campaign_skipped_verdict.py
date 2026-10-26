"""BUG-0756 (framework leg, round 2): the campaign's own verdict.

Round 1 gave the `script_results` row a `skipped` flag, so a check that never
ran because it was not configured is not counted as a failure by the reconcile
path. This round gives the campaign the nightly deployment closes through the
executor the same reading: the executor learns the outcome from the row the
run wrote, so a not-configured check ends the campaign `completed` instead of
`failed`.

Run them with:

    timeout 300 python3 -m pytest tests/test_campaign_skipped_verdict.py -q

Nothing here touches the network, a browser, a host, a device or a database:
the row a run would have written is faked, and every call the executor makes
around it is stubbed.

The negative control is the point: the same tests fail against the pre-fix
sources (`ff35a0524`), where the executor never looks at the row at all, so the
campaign ends `failed` where these tests expect `completed` -- a behavioural
failure, not an import error.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
PLACEHOLDER_HOST = "placeholder-host"
CAMPAIGN_EXECUTION_ID = "campaign-execution-1"

# Placeholders only: no real host name, device name, account or URL in here.
NETFLIX_CHECK = "web/netflix_video_check.py"
DAILYMOTION_CHECK = "web/dailymotion_video_check.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _script_config(script_name, **extra):
    config = {"script_name": script_name, "script_type": script_name}
    config.update(extra)
    return config


def _run_result(script_name, *, success, script_result_id=None, error=None,
                skipped=False, skip_reason=None):
    """What one script run hands back to the executor."""
    result = {
        "script_name": script_name,
        "script_type": script_name,
        "execution_order": 0,
        "success": success,
        "script_result_id": script_result_id,
        "execution_time_ms": 100,
        "report_url": None,
        "logs_url": None,
    }
    if error:
        result["error"] = error
    if skipped:
        result["skipped"] = True
        result["skip_reason"] = skip_reason
    return result


def _row(script_name, *, script_result_id, skipped, success=False):
    """The row such a run wrote: the authority on whether it ever ran."""
    return {
        "id": script_result_id,
        "script_name": script_name,
        "success": success,
        "skipped": skipped,
    }


def _run_campaign(monkeypatch, script_configs, *, results=None, rows=None,
                  continue_on_failure=True, real_single_script=False):
    """Drive a campaign through the executor's real verdict.

    `results` is what each script run hands back to the executor, in order.
    `rows` maps a script_result_id to the row that run wrote. The row is faked,
    never read from a database: the test needs no `skipped` column.
    """
    from shared.src.lib.database import script_results_db as script_db
    from shared.src.lib.executors import campaign_executor as ce

    rows = rows or {}
    state = {
        "linked": [],
        "row_reads": [],
        "executed": [],
        "result": None,
        "context": None,
    }

    def _fake_get_script_by_id(script_id):
        state["row_reads"].append(script_id)
        return rows.get(script_id)

    monkeypatch.setattr(script_db, "get_script_by_id", _fake_get_script_by_id)
    monkeypatch.setattr(ce, "record_campaign_execution_start",
                        lambda **kwargs: CAMPAIGN_EXECUTION_ID)
    monkeypatch.setattr(ce, "update_campaign_execution_result", lambda **kwargs: True)
    monkeypatch.setattr(
        ce, "add_script_result_to_campaign",
        lambda campaign_id, script_result_id: state["linked"].append(
            (campaign_id, script_result_id)
        ),
    )

    def _fake_setup(self, context, campaign_config):
        context.host = MagicMock(host_name=PLACEHOLDER_HOST)
        context.team_id = TEAM_ID
        context.current_os = "linux"
        state["context"] = context
        return True

    monkeypatch.setattr(ce.CampaignExecutor, "_setup_campaign_environment", _fake_setup)
    monkeypatch.setattr(ce.CampaignExecutor, "_generate_orchestrator_artifacts",
                        lambda self, context, cfg: None)

    if not real_single_script:
        def _fake_execute(self, context, campaign_config, script_config, order):
            state["executed"].append(script_config.get("script_name"))
            return dict(results[order - 1])

        monkeypatch.setattr(ce.CampaignExecutor, "_execute_single_script", _fake_execute)

    campaign_config = {
        "campaign_id": "nightly-video-check",
        "name": "nightly-video-check",
        "device": "auto",
        "device_id": "device1",
        "host": PLACEHOLDER_HOST,
        "userinterface_name": "video-check",
        "team_id": TEAM_ID,
        "execution_config": {"continue_on_failure": continue_on_failure},
        "script_configurations": script_configs,
    }

    executor = ce.CampaignExecutor()
    state["result"] = executor.execute_campaign(campaign_config)
    return state


# ---------------------------------------------------------------------------
# 1. A campaign whose only check was not configured ends completed
# ---------------------------------------------------------------------------
def test_a_campaign_whose_only_check_was_not_configured_completes(monkeypatch):
    """The row says the check never ran, so the campaign must not read as failed."""
    sid = "row-not-configured"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK)],
        results=[_run_result(NETFLIX_CHECK, success=False, script_result_id=sid,
                             error="Script failed with exit code 2")],
        rows={sid: _row(NETFLIX_CHECK, script_result_id=sid, skipped=True)},
    )
    result = state["result"]

    assert result["overall_success"] is True, (
        f"the campaign verdict is {result['overall_success']!r}: a check that was "
        "never configured is not a failure"
    )
    assert result["skipped_scripts"] == 1, (
        f"the campaign counted {result['skipped_scripts']} skipped scripts, not 1"
    )
    assert result["failed_scripts"] == 0, (
        f"the campaign counted {result['failed_scripts']} failed scripts, not 0"
    )


# ---------------------------------------------------------------------------
# 2. A genuinely failed check still fails the campaign
# ---------------------------------------------------------------------------
def test_a_campaign_with_one_genuinely_failed_check_still_fails(monkeypatch):
    """A video that never played is a failure, and it stays one."""
    sid = "row-real-failure"
    state = _run_campaign(
        monkeypatch,
        [_script_config(DAILYMOTION_CHECK)],
        results=[_run_result(DAILYMOTION_CHECK, success=False, script_result_id=sid,
                             error="Video was not playing during 25s monitoring window")],
        rows={sid: _row(DAILYMOTION_CHECK, script_result_id=sid, skipped=False)},
    )
    result = state["result"]

    assert result["overall_success"] is False, (
        "a genuinely failed check must still fail the campaign"
    )
    assert result["failed_scripts"] == 1
    assert result["skipped_scripts"] == 0


# ---------------------------------------------------------------------------
# 3. A not-configured check does not stop the campaign
# ---------------------------------------------------------------------------
def test_a_not_configured_check_does_not_stop_the_campaign(monkeypatch):
    """A skipped check is not a failure, so it must not stop the campaign."""
    sid = "row-not-configured"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK), _script_config(DAILYMOTION_CHECK)],
        results=[
            _run_result(NETFLIX_CHECK, success=False, script_result_id=sid,
                        error="Script failed with exit code 2"),
            _run_result(DAILYMOTION_CHECK, success=True,
                        script_result_id="row-played"),
        ],
        rows={sid: _row(NETFLIX_CHECK, script_result_id=sid, skipped=True)},
        continue_on_failure=False,
    )
    result = state["result"]

    assert state["executed"] == [NETFLIX_CHECK, DAILYMOTION_CHECK], (
        f"the campaign stopped at the not-configured check: {state['executed']}"
    )
    assert result["overall_success"] is True
    assert result["skipped_scripts"] == 1
    assert result["failed_scripts"] == 0
    assert result["successful_scripts"] == 1


def test_a_real_failure_still_stops_the_campaign(monkeypatch):
    """The other half of the same rule: a real failure still stops the run."""
    sid = "row-real-failure"
    state = _run_campaign(
        monkeypatch,
        [_script_config(DAILYMOTION_CHECK), _script_config(NETFLIX_CHECK)],
        results=[
            _run_result(DAILYMOTION_CHECK, success=False, script_result_id=sid,
                        error="Video was not playing during 25s monitoring window"),
            _run_result(NETFLIX_CHECK, success=True, script_result_id="row-played"),
        ],
        rows={sid: _row(DAILYMOTION_CHECK, script_result_id=sid, skipped=False)},
        continue_on_failure=False,
    )
    result = state["result"]

    assert state["executed"] == [DAILYMOTION_CHECK], (
        f"the campaign did not stop after a real failure: {state['executed']}"
    )
    assert result["overall_success"] is False
    assert result["failed_scripts"] == 1


# ---------------------------------------------------------------------------
# 4. The row of a not-configured check is still linked to the campaign
# ---------------------------------------------------------------------------
def test_the_row_of_a_not_configured_check_is_still_linked(monkeypatch):
    """The poller needs the row, so the skip must not unlink it."""
    sid = "row-not-configured"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK)],
        results=[_run_result(NETFLIX_CHECK, success=False, script_result_id=sid,
                             error="Script failed with exit code 2")],
        rows={sid: _row(NETFLIX_CHECK, script_result_id=sid, skipped=True)},
    )

    assert state["linked"] == [(CAMPAIGN_EXECUTION_ID, sid)], (
        f"the row of the not-configured check was not linked: {state['linked']}"
    )


# ---------------------------------------------------------------------------
# 5. An os-mismatch script is still skipped exactly as before
# ---------------------------------------------------------------------------
def test_an_os_mismatch_script_is_still_skipped_exactly_as_before(monkeypatch):
    """A script that never ran at all keeps its own skip: no row, no failure."""
    state = _run_campaign(
        monkeypatch,
        [_script_config(DAILYMOTION_CHECK, os="windows")],
        real_single_script=True,
    )
    result = state["result"]

    assert result["skipped_scripts"] == 1, (
        f"the os-mismatch script was not counted as skipped: {result['skipped_scripts']}"
    )
    assert result["failed_scripts"] == 0
    assert result["overall_success"] is True
    assert state["row_reads"] == [], (
        f"the os-mismatch case read a row it does not have: {state['row_reads']}"
    )
    assert state["linked"] == [], (
        f"the os-mismatch case linked a row it does not have: {state['linked']}"
    )


# ---------------------------------------------------------------------------
# 6. The outcome record says the not-configured check was skipped
# ---------------------------------------------------------------------------
def test_the_outcome_record_says_the_not_configured_check_was_skipped(monkeypatch):
    """The per-child record must agree with the row, and say why."""
    sid = "row-not-configured"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK)],
        results=[_run_result(NETFLIX_CHECK, success=False, script_result_id=sid,
                             error="Script failed with exit code 2")],
        rows={sid: _row(NETFLIX_CHECK, script_result_id=sid, skipped=True)},
    )

    outcomes = state["context"].metadata["script_outcomes"]
    assert len(outcomes) == 1, f"the run recorded {len(outcomes)} outcomes, not 1"
    assert outcomes[0]["skipped"] is True, (
        "the outcome record does not say the not-configured check was skipped"
    )
    assert "not configured" in (outcomes[0]["skip_reason"] or "").lower(), (
        f"the outcome record does not say it was not configured: "
        f"{outcomes[0]['skip_reason']!r}"
    )


# ---------------------------------------------------------------------------
# The row is the only signal: the exit code and the wording are not
# ---------------------------------------------------------------------------
def test_the_error_text_alone_never_turns_a_failure_into_a_skip(monkeypatch):
    """A usage error that says "not configured" is still a failure.

    Exit code 2 is ambiguous -- argparse exits 2 for a usage error too -- so
    neither the exit code nor the error text may decide this.
    """
    sid = "row-usage-error"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK)],
        results=[_run_result(
            NETFLIX_CHECK, success=False, script_result_id=sid,
            error="Script failed with exit code 2: the check is not configured: missing --email",
        )],
        rows={sid: _row(NETFLIX_CHECK, script_result_id=sid, skipped=False)},
    )
    result = state["result"]

    assert result["overall_success"] is False, (
        "a check that died on a bad command line must not become a skip"
    )
    assert result["failed_scripts"] == 1
    assert result["skipped_scripts"] == 0


def test_a_failed_check_whose_row_cannot_be_read_is_still_a_failure(monkeypatch):
    """No row, no evidence: the fail-safe direction is a failure, not a skip."""
    sid = "row-missing"
    state = _run_campaign(
        monkeypatch,
        [_script_config(NETFLIX_CHECK)],
        results=[_run_result(NETFLIX_CHECK, success=False, script_result_id=sid,
                             error="Script failed with exit code 2")],
        rows={},
    )
    result = state["result"]

    assert result["overall_success"] is False
    assert result["failed_scripts"] == 1
    assert result["skipped_scripts"] == 0


def test_a_successful_check_is_never_counted_as_skipped(monkeypatch):
    """A run that succeeded is not a skip, whatever its row says."""
    sid = "row-played"
    state = _run_campaign(
        monkeypatch,
        [_script_config(DAILYMOTION_CHECK)],
        results=[_run_result(DAILYMOTION_CHECK, success=True, script_result_id=sid)],
        rows={sid: _row(DAILYMOTION_CHECK, script_result_id=sid, skipped=False)},
    )
    result = state["result"]

    assert result["overall_success"] is True
    assert result["successful_scripts"] == 1
    assert result["skipped_scripts"] == 0
    assert result["failed_scripts"] == 0
