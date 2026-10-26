"""run_vpt_smoke must not go red because a neighbour aborted a run on the shared device."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import run_vpt_smoke as smoke  # noqa: E402


def _task(result=None, error=None):
    return {"status": "failed", "result": result or {}, "error": error}


def test_killed_run_is_interrupted_not_a_verdict():
    # Forge's force_unlock SIGTERMs the script: no marker, exit_code -15.
    ok, detail, interrupted = smoke.judge_task(
        _task({"exit_code": -15}, "host reported no script result"))
    assert (ok, interrupted) == (False, True)
    assert "killed" in detail


def test_killed_deployment_run_with_defaulted_script_success_false():
    # The scheduler path defaults script_success to False when the marker is missing.
    ok, detail, interrupted = smoke.judge_task(
        _task({"script_success": False, "exit_code": -15}, "Deployment script failed"))
    assert (ok, interrupted) == (False, True)


def test_real_script_failure_is_final_and_has_a_reason():
    ok, detail, interrupted = smoke.judge_task(
        _task({"script_success": False, "exit_code": 1}))
    assert (ok, interrupted) == (False, False)
    assert detail == "exit_code=1"


def test_pass_returns_report_url():
    ok, detail, interrupted = smoke.judge_task(
        {"status": "completed", "result": {"script_success": True, "report_url": "http://r"}})
    assert (ok, detail, interrupted) == (True, "http://r", False)


def test_empty_result_is_interrupted():
    assert smoke.judge_task(_task())[::2] == (False, True)


def test_run_one_retries_an_interrupted_run(monkeypatch):
    monkeypatch.setattr(smoke, "INTERRUPT_WAIT_SECONDS", 0)
    outcomes = iter([(False, "killed", True), (True, "http://r", False)])
    monkeypatch.setattr(smoke, "_run_once", lambda *a: next(outcomes))
    assert smoke.run_one("vpt/smoke_x", "h", "d", 1) == (True, "http://r")


def test_run_one_gives_up_after_bounded_retries(monkeypatch):
    monkeypatch.setattr(smoke, "INTERRUPT_WAIT_SECONDS", 0)
    calls = []
    monkeypatch.setattr(smoke, "_run_once", lambda *a: calls.append(1) or (False, "killed", True))
    assert smoke.run_one("vpt/smoke_x", "h", "d", 1) == (False, "killed")
    assert len(calls) == smoke.INTERRUPT_RETRIES + 1


def test_run_one_does_not_retry_a_real_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(smoke, "_run_once", lambda *a: calls.append(1) or (False, "exit_code=1", False))
    assert smoke.run_one("vpt/smoke_x", "h", "d", 1) == (False, "exit_code=1")
    assert len(calls) == 1


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.content = status, data, b"x"

    def json(self):
        return self._data


def test_device_under_take_control_is_skipped_not_queued(monkeypatch):
    # TASK-135: a smoke drove a benchmark's browser under its take-control lock; now it skips at once.
    sent = []

    def api(method, path, json=None):
        sent.append(json)
        return _Resp(423, {"success": False, "errorType": "device_locked", "owner_type": "manual_control"})
    monkeypatch.setattr(smoke, "_api", api)
    ok, detail, interrupted = smoke._run_once("vpt/smoke_ui", "host-clone-1", "host", 1)
    assert ok is None and "Take Control" in detail and not interrupted
    assert sent == [{"host_name": "host-clone-1", "device_id": "host", "script_name": "vpt/smoke_ui",
                     "queue_if_locked": False}]


def test_skipped_run_is_returned_by_run_one(monkeypatch):
    monkeypatch.setattr(smoke, "_run_once", lambda *a: (None, "skipped: held", False))
    assert smoke.run_one("vpt/smoke_x", "h", "d", 1) == (None, "skipped: held")


# ── pick_target: skip devices held by someone else ────────────────────────────
#
# CI run 3560 (2026-10-19) picked host-clone-1 because the smoke ran the
# *first* online host, but that host's device was under another session's
# `script_execution` lock (not manual_control, so the existing take-control
# skip does not fire) — every smoke in the suite hit "stayed locked".
# pick_target must read the public locks list and prefer a free host.

class _HostsResp(_Resp):
    """getAllHosts shapes its payload under a ``hosts`` key; the smoke needs that path."""

    def __init__(self, hosts):
        super().__init__(200, {"hosts": hosts})


def _stub_locks_call(api_log, locked_keys=()):
    """Pre-load the api stub with the lockedDevices response."""
    api_log["locked_devices"] = {"locked_devices": {k: {} for k in locked_keys}}


def test_pick_target_skips_a_locked_host(monkeypatch, capsys):
    api_log = {}

    def api(method, path, **kwargs):
        api_log.setdefault("calls", []).append(path)
        if path == "/server/system/getAllHosts":
            return _HostsResp([
                {"host_name": "host-locked", "devices": [{"device_id": "host"}]},
                {"host_name": "host-free", "devices": [{"device_id": "host"}]},
            ])
        if path == "/server/control/lockedDevices":
            _stub_locks_call(api_log, ["host-locked:host"])
            return _Resp(200, api_log["locked_devices"])
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", lambda n: True)
    host, device = smoke.pick_target(None, None)
    assert (host, device) == ("host-free", "host")
    out = capsys.readouterr().out
    assert "host-locked" not in out   # skip was silent when a free host came up
    assert "/server/control/lockedDevices" in api_log["calls"]


def test_pick_target_warns_and_falls_back_when_all_locked(monkeypatch, capsys):
    api_log = {}

    def api(method, path, **kwargs):
        if path == "/server/system/getAllHosts":
            return _HostsResp([
                {"host_name": "host-a", "devices": [{"device_id": "host"}]},
                {"host_name": "host-b", "devices": [{"device_id": "host"}]},
            ])
        if path == "/server/control/lockedDevices":
            return _Resp(200, {"locked_devices": {
                "host-a:host": {}, "host-b:host": {},
            }})
        raise AssertionError(path)

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", lambda n: True)
    host, device = smoke.pick_target(None, None)
    # Fall back to the first locked host so the suite can still run.
    assert (host, device) == ("host-a", "host")
    out = capsys.readouterr().out
    assert "WARNING" in out and "locked" in out and "host-a" in out and "host-b" in out


def test_pick_target_skips_unreachable_then_locked_free(monkeypatch, capsys):
    """An unreachable host is dropped before the lock check, and the lock of
    the next host is reported. Free reachable host wins."""

    def api(method, path, **kwargs):
        if path == "/server/system/getAllHosts":
            return _HostsResp([
                {"host_name": "dead-host", "devices": [{"device_id": "host"}]},
                {"host_name": "busy-host", "devices": [{"device_id": "host"}]},
                {"host_name": "live-host", "devices": [{"device_id": "host"}]},
            ])
        if path == "/server/control/lockedDevices":
            return _Resp(200, {"locked_devices": {"busy-host:host": {}}})
        raise AssertionError(path)

    def probe(name):
        return name != "dead-host"

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", probe)
    host, device = smoke.pick_target(None, None)
    assert (host, device) == ("live-host", "host")
    # No "unreachable" or "all locked" banner when a free reachable host
    # wins — silence is the success signal here.
    out = capsys.readouterr().out
    assert "WARNING" not in out and "dead-host" not in out


def test_pick_target_skip_host_arg_picks_next_free(monkeypatch):
    """The retry path passes ``skip_host=`` so the runner tries the *next*
    candidate instead of bouncing back to the host that just failed."""

    def api(method, path, **kwargs):
        if path == "/server/system/getAllHosts":
            return _HostsResp([
                {"host_name": "first", "devices": [{"device_id": "host"}]},
                {"host_name": "second", "devices": [{"device_id": "host"}]},
            ])
        if path == "/server/control/lockedDevices":
            return _Resp(200, {"locked_devices": {}})
        raise AssertionError(path)

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", lambda n: True)
    host, device = smoke.pick_target(None, None, skip_host="first")
    assert (host, device) == ("second", "host")


# ── run_one: try the next free host when the first stayed locked ────────────


def test_run_one_retries_stayed_lock_on_next_free_host(monkeypatch, capsys):
    """First _run_once fails with 'stayed locked' (script lock on a neighbour);
    pick_target hands back a second host; the second _run_once returns a pass.
    The retry must happen on a *different* host, not bounce on the same one."""

    outcomes = iter([
        (False, "device first:host stayed locked", False),  # first host held
        (True, "http://r", False),                           # second host free
    ])
    seen = []

    def run_once(script, host, device, timeout):
        seen.append((host, device))
        return next(outcomes)

    def api(method, path, **kwargs):
        if path == "/server/system/getAllHosts":
            return _HostsResp([
                {"host_name": "first", "devices": [{"device_id": "host"}]},
                {"host_name": "second", "devices": [{"device_id": "host"}]},
            ])
        if path == "/server/control/lockedDevices":
            return _Resp(200, {"locked_devices": {}})
        raise AssertionError(path)

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", lambda n: True)
    monkeypatch.setattr(smoke, "_run_once", run_once)
    monkeypatch.setattr(smoke, "INTERRUPT_WAIT_SECONDS", 0)
    assert smoke.run_one("vpt/smoke_ui", "first", "host", 1) == (True, "http://r")
    assert seen == [("first", "host"), ("second", "host")]
    out = capsys.readouterr().out
    assert "stayed locked" in out and "second" in out


def test_run_one_does_not_bounce_back_to_same_locked_host(monkeypatch, capsys):
    """If no other reachable host exists, the first failure is returned
    without a useless retry on the same (locked) host."""

    seen = []

    def run_once(script, host, device, timeout):
        seen.append((host, device))
        return (False, f"device {host}:{device} stayed locked", False)

    def api(method, path, **kwargs):
        if path == "/server/system/getAllHosts":
            return _HostsResp([{"host_name": "only", "devices": [{"device_id": "host"}]}])
        if path == "/server/control/lockedDevices":
            return _Resp(200, {"locked_devices": {}})
        raise AssertionError(path)

    monkeypatch.setattr(smoke, "_api", api)
    monkeypatch.setattr(smoke, "_probe_host_forwarder", lambda n: True)
    monkeypatch.setattr(smoke, "_run_once", run_once)
    monkeypatch.setattr(smoke, "INTERRUPT_WAIT_SECONDS", 0)
    assert smoke.run_one("vpt/smoke_ui", "only", "host", 1) == (
        False, "device only:host stayed locked")
    # Exactly one attempt: no next host to retry on.
    assert seen == [("only", "host")]
    assert "stayed locked" not in capsys.readouterr().out  # no retry banner


class _Code:
    def __init__(self, code):
        self.status_code = code
        self.text = ""


def test_get_all_hosts_retries_5xx_until_the_server_is_back(monkeypatch):
    seq = [_Code(500), _Code(502), _Code(200)]
    monkeypatch.setattr(smoke, "_api", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)
    assert smoke._get_all_hosts().status_code == 200
    assert not seq


def test_get_all_hosts_retries_connection_errors(monkeypatch):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise smoke.requests.ConnectionError("down")
        return _Code(200)
    monkeypatch.setattr(smoke, "_api", fake)
    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)
    assert smoke._get_all_hosts().status_code == 200


def test_get_all_hosts_returns_last_5xx_after_budget_and_4xx_at_once(monkeypatch):
    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)
    n = []
    monkeypatch.setattr(smoke, "_api", lambda *a, **k: (n.append(1), _Code(500))[1])
    assert smoke._get_all_hosts().status_code == 500
    assert len(n) == smoke.HOSTS_RETRIES + 1
    n.clear()
    monkeypatch.setattr(smoke, "_api", lambda *a, **k: (n.append(1), _Code(403))[1])
    assert smoke._get_all_hosts().status_code == 403 and len(n) == 1
