"""TASK-109 G3: step 1 asks the database VM agent for a backup and polls the report. Network and clock are mocked."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.platform_update import db_backup as db  # noqa: E402

T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
TOKEN = "s3cret-token-" + "x" * 20
ENV = {"INFRA_VM_AGENTS": "storage=10.0.0.1:9110,database=10.0.0.2:9110", "VM_AGENT_ACTION_TOKEN": TOKEN}


class World:
    """A fake clock that advances with every sleep, a fake agent and a fake report file."""

    def __init__(self, env=None, post=(202, {"request_id": "r1"}), agent_states=None, report_after=None, report_age_h=None,
                 timeout=120):
        self.t = 0.0
        self.calls = []
        self.post = post
        self.states = agent_states or []          # list of (code, body); the last one repeats
        self.report_after = report_after          # seconds after which a fresh report appears
        self.report_age_h = report_age_h          # a stale nightly report that was there before
        self.env = ENV if env is None else env
        self.deps = db.Deps(env=self.env, http=self.http, report=self.report, now=lambda: T0 + timedelta(seconds=self.t),
                            sleep=self.sleep, poll_seconds=5, timeout_seconds=timeout)

    def sleep(self, s):
        self.t += s

    def http(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers)))
        if isinstance(self.post, Exception) and method == "POST":
            raise self.post
        if method == "POST":
            return self.post
        st = self.states[min(len([c for c in self.calls if c[0] == "GET"]) - 1, len(self.states) - 1)] if self.states else (200, {"running": True})
        if isinstance(st, Exception):
            raise st
        return st

    def report(self):
        if self.report_after is not None and self.t >= self.report_after:
            return {"filename": "vpt_postgres_20261015_120030.dump", "size": "45M", "nfs_copy": True,
                    "reported_at": (T0 + timedelta(seconds=self.t)).isoformat().replace("+00:00", "Z"),
                    "timestamp_iso": (T0 + timedelta(seconds=self.t)).isoformat().replace("+00:00", "Z")}
        if self.report_age_h is not None:
            ts = (T0 - timedelta(hours=self.report_age_h)).isoformat()
            return {"filename": "vpt_postgres_old.dump", "size": "40M", "nfs_copy": False, "reported_at": ts, "timestamp_iso": ts}
        return {"status": "error", "detail": "No backup status"}


def test_agent_address_is_the_database_entry():
    assert db.agent_address(ENV) == "10.0.0.2:9110"
    assert db.agent_address({"INFRA_VM_AGENTS": "storage=1.1.1.1:9110"}) == ""
    assert db.agent_address({}) == ""


def test_request_then_poll_until_a_newer_report_success():
    w = World(report_after=20, agent_states=[(200, {"running": True})], report_age_h=3)
    logs = []
    item = db.request_backup(w.deps, logs.append)
    assert item["status"] == "ok" and item["fix"] == ""
    assert item["detail"] == "vpt_postgres_20261015_120030.dump · 45M · NFS copy yes"
    methods = [c[0] for c in w.calls]
    assert methods[0] == "POST" and set(methods[1:]) == {"GET"}
    assert all(c[1] == "http://10.0.0.2:9110/actions/db-backup" and c[2] == {"X-VM-Agent-Token": TOKEN} for c in w.calls)
    assert w.t == 20 and logs                                     # polled every 5 s, the stale report did not count


def test_an_old_report_is_not_accepted_as_the_new_backup():
    w = World(report_age_h=0.5, timeout=30)                      # nightly report from 30 min ago, nothing new ever comes
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and "No fresh backup report" in item["detail"] and w.t >= 30


def test_agent_failure_exit_code_is_a_ko_with_the_log_tail():
    lines = [f"line {i}" for i in range(20)] + ["pg_dump: error: out of disk"]
    w = World(agent_states=[(200, {"running": True}), (200, {"running": False, "exit_code": 1, "log_tail": lines})])
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and "exit 1" in item["detail"] and "out of disk" in item["detail"]
    assert "line 0" not in item["detail"] and item["fix"] and w.t == 5                # fast: no waiting for the timeout


def test_script_exit_zero_but_no_report_is_a_ko_after_a_short_grace():
    w = World(agent_states=[(200, {"running": False, "exit_code": 0, "log_tail": ["WARNING: Could not report status"]})])
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and "report never reached" in item["detail"] and "VPT_API_KEY" in item["fix"]
    assert db.REPORT_GRACE_SECONDS <= w.t < db.REPORT_GRACE_SECONDS + 10


def test_timeout_is_a_ko():
    w = World(timeout=600)
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and "10 minutes" in item["detail"] and w.t >= 600


def test_default_timeout_is_twenty_minutes_polled_every_five_seconds():
    assert db.TIMEOUT_SECONDS == 1200 and db.POLL_SECONDS == 5


@pytest.mark.parametrize("code,word", [(401, "wrong token"), (404, "not enabled")])
def test_agent_refusals_are_a_ko_with_the_setup_fix(code, word):
    w = World(post=(code, {"error": "x"}))
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and word in item["detail"] and "VM_AGENT_ACTION_TOKEN" in item["fix"]
    assert TOKEN not in str(item)


def test_cooldown_429_is_a_ko_that_says_wait():
    item = db.request_backup(World(post=(429, {"retry_after": 120})).deps)
    assert item["status"] == "ko" and "120" in item["detail"] and "Wait" in item["fix"]


def test_already_running_409_waits_for_that_backup():
    w = World(post=(409, {"error": "already running"}), report_after=10)
    assert db.request_backup(w.deps)["status"] == "ok"


def test_agent_down_is_a_ko():
    item = db.request_backup(World(post=OSError("refused")).deps)
    assert item["status"] == "ko" and "does not answer" in item["detail"]


def test_agent_vanishing_mid_run_fails_fast():
    w = World(agent_states=[OSError("gone")])
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and "stopped answering" in item["detail"] and w.t < 30


def test_fallback_uses_a_fresh_nightly_report_and_shows_its_age():
    for env in ({}, {"INFRA_VM_AGENTS": "database=10.0.0.2:9110"}, {"VM_AGENT_ACTION_TOKEN": TOKEN}):
        w = World(env=env, report_age_h=3)
        item = db.request_backup(w.deps)
        assert item["status"] == "ok" and "vpt_postgres_old.dump" in item["detail"] and "3 h ago" in item["detail"]
        assert "NFS copy no" in item["detail"] and w.calls == []


def test_fallback_stale_report_is_a_ko_with_the_manual_command():
    w = World(env={}, report_age_h=30)
    item = db.request_backup(w.deps)
    assert item["status"] == "ko" and item["fix"] == "Run on the database VM: sudo bash /usr/local/bin/vpt-db-backup.sh"
    assert "30 h ago" in item["detail"]


def test_fallback_without_any_report_is_a_ko():
    item = db.request_backup(World(env={}).deps)
    assert item["status"] == "ko" and "never reported" in item["detail"] and item["fix"].startswith("Run on the database VM")


def test_prerequisite_cases():
    ok, detail, log = db.prerequisite(World(report_age_h=40).deps)       # agent answers (GET 200)
    assert ok and "agent answers" in detail and TOKEN not in log
    w = World(report_age_h=2)
    w.deps.http = lambda *a: (401, {})
    assert db.prerequisite(w.deps)[0] is True                                          # token refused but nightly is fresh
    w = World(report_age_h=26)
    w.deps.http = lambda *a: (404, {})
    ok, detail, _ = db.prerequisite(w.deps)
    assert ok is False and "404" in detail
    assert db.prerequisite(World(env={}, report_age_h=1).deps)[0] is True
    assert db.prerequisite(World(env={}).deps)[0] is False
