"""A repeat_until condition may WAIT for the frame that shows the effect of the key.

The operator's set-top box applies every key at once but redraws the focus underline
7-13 s later (measured on stb4, 2026-10-23: 7.1, 8.3, 10.3, 10.3, 10.5, 12.4, 13.3 s).
A check that scores ONE frame right after the press therefore reads the screen from
BEFORE the key: the walk believes the focus did not move, presses again, and ends up
two columns too far. That is the failure the Settings chain kept hitting until the
tree had to settle every observed key for 20 s.

So the check AFTER a press honours the leg's own `timeout`: the image controller then
polls the capture directory for a frame NEWER than the one the check started from, and
the wait is spent on the device's own redraw instead of on a blind sleep.

Two things must NOT change:
  - the PRECONDITION check (before the first press) stays a one-frame check: it asks
    "is the device already there?", so it must be cheap and must never wait;
  - a leg that declares no timeout (or timeout=0) keeps the one-frame behaviour, so
    every rule that never opted in behaves exactly as before.

Pure-CPU: a fake verification executor records the params the controller receives.
"""
import asyncio
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


class _FakeVerificationExecutor:
    """Records what the action executor hands to the verification path.

    `fail_first` makes the FIRST call fail: in a repeat_until action the first
    call is the precondition ("is the device already there?"), so a fake that
    always succeeds would skip the whole loop.
    """

    def __init__(self, success=True, fail_first=False):
        self.calls = []
        self.success = success
        self.fail_first = fail_first

    async def _execute_single_verification(self, verification=None, userinterface_name=None,
                                           image_source_url=None, context=None, team_id=None):
        self.calls.append({
            "command": (verification or {}).get("command"),
            "params": dict(((verification or {}).get("params") or {})),
            "userinterface_name": userinterface_name,
        })
        if self.fail_first and len(self.calls) == 1:
            return {"success": False, "message": "not there yet"}
        return {"success": self.success, "message": "fake"}


class _FakeDevice:
    def __init__(self, verification_executor=None):
        self.host_name = "test-host"
        self.device_id = "device-test"
        self.device_model = "stb-testop"
        self.device_name = "stb-test"
        self.navigation_context = {}
        self.verification_executor = verification_executor
        self.get_capture_dir = lambda subfolder="": "/tmp"

    def _get_controller(self, name):
        return None


def _executor(device):
    from backend_host.src.services.actions.action_executor import ActionExecutor
    return ActionExecutor(device, _from_device_init=True)


def _rule(timeout=20000, command="waitForNavTabIndex", poll_wait_ms=None):
    params = {"tab_index": 0, "direction": "right"}
    if timeout is not None:
        params["timeout"] = timeout
    rule = {
        "condition": "appears",
        "match": "all",
        "max_iterations": 7,
        "verifications": [
            {"command": command, "params": params, "verification_type": "image"},
        ],
    }
    if poll_wait_ms is not None:
        rule["poll_wait_ms"] = poll_wait_ms
    return rule


def test_the_precondition_check_is_always_one_frame():
    """It asks 'is the device already there?' — it must not wait."""
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=20000), poll=False))
    assert ve.calls[0]["params"]["timeout"] == 0


def test_the_check_after_a_press_keeps_the_legs_own_timeout():
    """The leg's timeout is its 'how long may I wait for this condition' window."""
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=20000), poll=True))
    assert ve.calls[0]["params"]["timeout"] == 20000
    assert ve.calls[0]["params"]["tab_index"] == 0
    assert ve.calls[0]["params"]["direction"] == "right"


def test_a_leg_without_a_timeout_stays_one_frame():
    """Nothing that never opted in changes behaviour."""
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=None), poll=True))
    assert ve.calls[0]["params"]["timeout"] == 0


def test_a_leg_with_timeout_zero_stays_one_frame():
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=0), poll=True))
    assert ve.calls[0]["params"]["timeout"] == 0


def test_the_leg_params_are_not_mutated():
    """The rule keeps its own timeout: the executor must not rewrite the tree's data."""
    rule = _rule(timeout=20000)
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(rule, poll=True))
    asyncio.run(exe._evaluate_until_condition(rule, poll=False))
    assert rule["verifications"][0]["params"]["timeout"] == 20000


def test_the_condition_result_is_the_legs_own_verdict():
    """A failing leg means 'not met' — the loop keeps pressing."""
    ve = _FakeVerificationExecutor(success=False)
    exe = _executor(_FakeDevice(ve))
    met, evidence = asyncio.run(exe._evaluate_until_condition(_rule(timeout=20000), poll=True))
    assert met is False
    assert evidence is not None


class _FakeRemoteController:
    """A press_key that always succeeds."""

    def __init__(self):
        self.calls = []

    def execute_command(self, command=None, params=None):
        self.calls.append({"command": command, "params": dict(params or {})})
        return {"success": True, "message": "pressed"}


def _settle_of(monkeypatch, action):
    """Run one repeat_until action and return the settle it slept (ms).

    The first sleep is the settle between the press and the check; the action's
    wait_time is slept AGAIN after the loop (unchanged behaviour), so only the
    first one is the settle.
    """
    import backend_host.src.services.actions.action_executor as ax

    slept = []
    monkeypatch.setattr(ax.time, "sleep", lambda s: slept.append(s))
    ve = _FakeVerificationExecutor(success=True, fail_first=True)
    device = _FakeDevice(ve)
    device._get_controller = lambda name: _FakeRemoteController() if name == "remote" else None
    exe = _executor(device)
    asyncio.run(exe.execute_actions(actions=[action], capture_before_action_screenshot=False))
    return slept[0] if slept else None


def test_the_settle_is_the_actions_wait_time(monkeypatch):
    """Unchanged: the action's wait_time is the settle before the check."""
    action = {
        "action_type": "remote",
        "command": "press_key",
        "params": {"key": "RIGHT", "wait_time": 5000},
        "repeat_until": _rule(timeout=20000),
    }
    assert _settle_of(monkeypatch, action) == 5.0


def test_poll_wait_ms_raises_the_settle(monkeypatch):
    """The rule's poll_wait_ms is the floor for the settle — it is now read."""
    action = {
        "action_type": "remote",
        "command": "press_key",
        "params": {"key": "RIGHT", "wait_time": 100},
        "repeat_until": _rule(timeout=20000, poll_wait_ms=2000),
    }
    assert _settle_of(monkeypatch, action) == 2.0


def test_a_longer_wait_time_wins_over_poll_wait_ms(monkeypatch):
    action = {
        "action_type": "remote",
        "command": "press_key",
        "params": {"key": "RIGHT", "wait_time": 5000},
        "repeat_until": _rule(timeout=20000, poll_wait_ms=500),
    }
    assert _settle_of(monkeypatch, action) == 5.0



def test_the_check_after_a_press_says_when_the_key_went_out():
    """A check that has to spot a movement needs the state from BEFORE the key.

    The frame the check is handed is a fresh screenshot, and on a busy host the
    screenshot itself can be taken after the device already redrew — then the
    check has no "before" to compare against. The executor therefore tells the
    leg when the key went out.
    """
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=20000), poll=True,
                                              pressed_at=1730000000.5))
    assert ve.calls[0]["params"]["pressed_at"] == 1730000000.5


def test_the_precondition_check_says_nothing_about_a_press():
    """Before the first press there is no key to compare against."""
    ve = _FakeVerificationExecutor()
    exe = _executor(_FakeDevice(ve))
    asyncio.run(exe._evaluate_until_condition(_rule(timeout=20000), poll=False,
                                              pressed_at=1730000000.5))
    assert "pressed_at" not in ve.calls[0]["params"]
