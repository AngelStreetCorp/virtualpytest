"""CoC hourly run guard (scripts/agent/coc_run_lease.py): the phone lease must outlive the run, and
the run must give the phone back to somebody who is waiting for it.

The guard claims node1-vpt/vpt-pi1/device1 before the hourly CoC run and releases it when the run
is over. The regression these tests pin down: a CoC LLM run lasts 20-60 min, so a fixed 45 min TTL
expired in the middle of the run (lease:expired instead of lease:released, BUG-0717).

The owner rule of 2026-10-20: CoC is LOW priority. The lease is claimed with a 10 min TTL, it is
renewed only while nobody waits for the phone, and the moment somebody waits the run is asked to
stop at its next turn boundary and the lease goes back.

No ssh, no lease service, no platform API: a fake Ops stands in for vpt-lease, the phone (ssh) and
the deployment history.

Run: pytest tests/scripts/test_coc_run_lease.py -v
"""
import importlib.util
import os
from datetime import datetime, timedelta, timezone

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "coc_run_lease", os.path.join(_here, "..", "..", "scripts", "agent", "coc_run_lease.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

BASE = datetime(2026, 10, 20, 10, 59, 5, tzinfo=timezone.utc)      # the claim, one minute before the run


def execution(scheduled, status="running", completed=None, started=None, run_id="r1"):
    return {"scheduled_at": scheduled, "started_at": started or scheduled, "completed_at": completed,
            "status": status, "script_result_id": run_id}


def at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


class FakeOps:
    """A vpt-lease, a phone and a deployment history that the test drives."""

    def __init__(self, executions=None, claim_ok=True, release_ok=True, renew_ok=True, lease="lease001",
                 waiters=None, waiters_after=None, settled_after=None, renew_rc=0,
                 settled_run="r1", reserved_run=None):
        self.executions = executions if executions is not None else []
        self.claim_ok, self.release_ok, self.renew_ok = claim_ok, release_ok, renew_ok
        self.lease_id = lease
        self.calls = []
        self.renewed = 0
        self.renew_ttls = []
        self.polls = 0
        self.waiters = list(waiters or [])      # what the registry says waits for the phone
        self.waiters_after = waiters_after      # the waiter shows up at that poll
        self.settled_after = settled_after      # the ledger says the run stopped at that poll
        self.settled_run = settled_run          # the run id of that settle row
        self.reserved_run = reserved_run        # the run id of the last reserve row
        self.renew_rc = renew_rc                # 7 = the registry wants the phone back
        self.stop_orders = 0
        self.cleared = 0
        self.renew_after_yield = 0

    # ----- lease -----
    def claim(self):
        self.calls.append("claim")
        return self.lease_id if self.claim_ok else None

    def renew(self, lease_id, ttl_min=None):
        self.calls.append("renew")
        self.renewed += 1
        self.renew_ttls.append(ttl_min)
        if self.stop_orders:
            self.renew_after_yield += 1
        return self.renew_rc if self.renew_ok else 1

    def release(self, lease_id):
        self.calls.append("release")
        return self.release_ok

    def waiting_claims(self):
        self.calls.append("waiting_claims")
        if self.waiters_after is not None and self.polls >= self.waiters_after:
            return list(self.waiters)
        return []

    # ----- the phone -----
    def ask_run_to_stop(self):
        self.calls.append("ask_run_to_stop")
        self.stop_orders += 1
        return True

    def clear_stop_flag(self):
        self.calls.append("clear_stop_flag")
        self.cleared += 1
        return True

    def ledger_since(self, since_ts):
        self.calls.append("ledger_since")
        if self.settled_after is not None and self.polls >= self.settled_after:
            return {"settled": self.settled_run, "stop": "yielded", "reserved": self.reserved_run}
        return {"settled": None, "stop": None, "reserved": self.reserved_run}

    # ----- platform -----
    def history(self):
        self.calls.append("history")
        self.polls += 1
        return list(self.executions)

    # ----- state file -----
    def remember(self, lease_id):
        self.calls.append(("remember", lease_id))

    def remembered(self):
        return None

    def forget(self):
        self.calls.append("forget")


class Clock:
    """A clock the test moves forward: sleep() advances it instead of waiting."""

    def __init__(self):
        self.t = BASE.timestamp()

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def at(self):
        return datetime.fromtimestamp(self.t, timezone.utc)


# ---------- the pure decisions ----------

def test_a_run_with_a_result_is_terminal():
    assert C.is_terminal(execution(at(1), "completed", at(52)))
    assert C.is_terminal(execution(at(1), "failed", at(31)))


def test_a_skipped_trigger_is_terminal_the_platform_never_started():
    assert C.is_terminal(execution(at(1), "skipped"))
    assert not C.is_terminal(execution(at(1), "running"))


def test_the_guarded_hour_is_the_hour_the_claim_belongs_to():
    assert C.guarded_hour(at(0)) == at(1).replace(minute=0, second=0, microsecond=0)
    # a claim that lands after the trigger (the phone was busy) still belongs to that hour
    assert C.guarded_hour(at(6)) == at(1).replace(minute=0, second=0, microsecond=0)
    assert C.guarded_hour(at(6.5)) == at(1).replace(minute=0, second=0, microsecond=0)


def test_a_claim_in_mid_hour_belongs_to_the_next_trigger():
    # live bug 2026-10-20 12:53: a guard started by hand took the hour that had just passed as
    # its guarded hour, found the phone free 31 s later and released the lease - the run of the
    # next hour would have gone unguarded.
    since = datetime(2026, 10, 20, 12, 53, 37, tzinfo=timezone.utc)
    assert C.guarded_hour(since) == datetime(2026, 10, 20, 13, 0, 0, tzinfo=timezone.utc)
    # the phone is not free before that trigger had its chance
    assert not C.phone_free([], since + timedelta(minutes=1), since)
    assert C.phone_free([], since + timedelta(minutes=10), since)


def test_a_running_execution_is_a_run_on_the_phone():
    now = at(10)
    assert C.running_executions([execution(at(1), "running")], now)
    assert not C.running_executions([execution(at(1), "completed", at(50))], now)
    assert not C.running_executions([execution(at(1), "skipped")], now)


def test_an_orphan_row_is_not_a_run():
    # a row that is still 'running' three hours later is a leftover, not a run on the phone
    now = at(200)
    assert not C.running_executions([execution(at(1), "running")], now)


def test_the_phone_is_not_free_before_the_trigger_of_the_guarded_hour():
    # the trigger fires at 11:00, until then there is nothing to wait for
    assert not C.phone_free([], at(0.5), at(0))
    assert C.phone_free([], at(4), at(0))


def test_the_phone_is_not_free_while_a_run_is_on_it():
    now = at(10)
    assert not C.phone_free([execution(at(1), "running")], now, at(0))
    assert C.phone_free([execution(at(1), "completed", at(9))], now, at(0))


# ---------- the low-priority rule (owner, 2026-10-20) ----------

def test_the_lease_is_claimed_with_a_ten_minute_ttl():
    assert C.TTL_MIN == 10
    assert C.RENEW_EVERY_S < C.TTL_MIN * 60, "the lease must be renewed before the TTL is up"


def test_a_waiting_ticket_on_the_phone_is_seen_as_a_waiting_claim():
    payload = {"tickets": [{"id": "t-1", "state": "waiting", "env": "node1-vpt",
                            "resources": ["device:vpt-pi1/device1"], "agent": "codebox:other",
                            "position": 1}]}
    claims = C.waiting_claims(payload)
    assert len(claims) == 1 and claims[0]["kind"] == "ticket" and claims[0]["agent"] == "codebox:other"


def test_a_ticket_for_another_phone_is_not_our_business():
    payload = {"tickets": [{"id": "t-1", "state": "waiting", "resources": ["device:vpt-pi4/device2"],
                            "agent": "codebox:other"}]}
    assert C.waiting_claims(payload) == []


def test_a_ticket_that_is_already_granted_does_not_make_us_yield():
    payload = {"tickets": [{"id": "t-1", "state": "granted", "resources": ["device:vpt-pi1/device1"]}]}
    assert C.waiting_claims(payload) == []


def test_a_queued_host_deploy_on_our_env_waits_for_the_phone():
    payload = {"deploys": [{"id": "d-1", "env": "node1-vpt", "scope": "host", "state": "queued",
                            "agent": "codebox:deployer", "hosts": ["vpt-pi1"]}]}
    claims = C.waiting_claims(payload)
    assert len(claims) == 1 and claims[0]["kind"] == "deploy"


def test_a_frontend_deploy_does_not_wait_for_the_phone():
    payload = {"deploys": [{"id": "d-1", "env": "node1-vpt", "scope": "frontend", "state": "queued"}]}
    assert C.waiting_claims(payload) == []


def test_the_resource_is_matched_in_both_spellings():
    assert C.resource_matches(["device:vpt-pi1/device1"], "vpt-pi1/device1")
    assert C.resource_matches(["vpt-pi1/device1"], "vpt-pi1/device1")
    assert not C.resource_matches(["device:vpt-pi1/device2"], "vpt-pi1/device1")


def test_the_ledger_says_the_run_stopped():
    lines = ['{"ts": 100.0, "kind": "reserve", "run_id": "r1"}',
             '{"ts": 200.0, "kind": "settle", "run_id": "r1", "stop": "yielded"}']
    led = C.ledger_state(lines, 150.0)
    assert led["settled"] == "r1" and led["stop"] == "yielded"


def test_the_ledger_ignores_what_happened_before_the_yield():
    lines = ['{"ts": 100.0, "kind": "settle", "run_id": "r0", "stop": "max_steps"}']
    assert C.ledger_state(lines, 150.0)["settled"] is None


def test_the_run_gives_the_phone_back_when_somebody_waits():
    """The owner rule: CoC is low priority, a waiting claim ends the run at its next turn."""
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")],
                  waiters=[{"kind": "ticket", "id": "t-1", "agent": "codebox:other"}],
                  waiters_after=3, settled_after=6)

    def history():
        ops.calls.append("history")
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_YIELDED
    assert ops.stop_orders == 1, "the run must be asked to stop"
    assert "release" in ops.calls, "the lease must go back to the waiting agent"


def test_the_run_keeps_the_phone_while_nobody_waits():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")])

    def history():
        ops.polls += 1
        if ops.polls >= 4:
            ops.executions = [execution(at(1), "running", at(50))]
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert ops.stop_orders == 0, "nobody waits: the run keeps playing"
    assert ops.cleared >= 1, "a stop order of an earlier yield must not kill this run"


def test_the_lease_is_claimed_with_the_background_priority():
    """Owner rule (2026-10-20): CoC is a background job - the lease is claimed with P3."""
    ops = C.Ops()
    seen = {}

    def fake_lease(args):
        seen["args"] = args
        return 0, "a1b2c3d4\n"

    ops._lease = fake_lease
    assert ops.claim() == "a1b2c3d4"
    args = seen["args"]
    assert args[args.index("--priority") + 1] == "P3"
    assert args[args.index("--ttl") + 1] == "10", "a P3 lease is capped at 10 min per claim"
    assert args[args.index("--agent") + 1] == C.AGENT


def test_the_registrys_yield_order_stops_the_renewal_and_releases_the_lease():
    """`vpt-lease renew` answers 7 (E_YIELD_REQUIRED): log it, stop renewing, release at the end of
    the turn, no retry (owner, 2026-10-20)."""
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")], renew_rc=C.YIELD_REQUIRED_RC, settled_after=8)

    def history():
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_YIELDED
    assert ops.stop_orders == 1, "the run must be asked to stop"
    assert ops.renewed == 1, "the refused renewal is not retried"
    assert "release" in ops.calls


def test_the_lease_is_not_renewed_while_the_run_winds_down():
    """'stop renewing' - the guard gives the lease up instead of fighting for it."""
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")],
                  waiters=[{"kind": "ticket", "id": "t-1", "agent": "codebox:other"}],
                  waiters_after=12, settled_after=20)

    def history():
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_YIELDED
    assert ops.renew_after_yield == 0, "the lease is not renewed once the run gives the phone back"
    assert C.TTL_MIN in ops.renew_ttls, "the normal lease is renewed with the 10 min TTL"


def test_the_yield_gives_up_after_the_turn_deadline():
    """A run that does not stop must not hold the phone for ever."""
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")],
                  waiters=[{"kind": "ticket", "id": "t-1", "agent": "codebox:other"}],
                  waiters_after=2, settled_after=None)

    def history():
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    old = C.YIELD_STOP_TIMEOUT_S
    C.YIELD_STOP_TIMEOUT_S = 300
    try:
        assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_YIELDED
    finally:
        C.YIELD_STOP_TIMEOUT_S = old
    assert "release" in ops.calls
    assert clock.at() < at(30), "the phone must not be held for ever"


def test_the_ledger_signal_ends_the_yield_before_the_platform_catches_up():
    """The platform's history lags by minutes; the run's ledger on the phone is the fast signal.

    The waiting agent must get the phone when the run is really over, not ten minutes later.
    """
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")],      # the platform still says 'running'
                  waiters=[{"kind": "ticket", "id": "t-1", "agent": "codebox:other"}],
                  waiters_after=2, settled_after=6)

    def history():
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_YIELDED
    assert clock.at() < at(10), "the lease must go back as soon as the run is really over"


# ---------- the guard itself ----------

def test_the_guard_claims_waits_and_releases():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")])

    def history():
        ops.calls.append("history")
        ops.polls += 1
        # the run ends after 5 polls (2.5 min)
        if ops.polls >= 5:
            ops.executions = [execution(at(1), "running", at(50))]
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert ops.calls.index("claim") < ops.calls.index("release")
    assert "release" in ops.calls


def test_a_run_longer_than_the_ttl_is_still_guarded_and_released():
    """The regression of BUG-0717: the run outlives the 45 min TTL, the lease must not expire.

    The fake clock runs past the TTL while the run is still going: the guard has to renew the
    lease, and it has to release it when the run finally ends.
    """
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")])

    def history():
        ops.calls.append("history")
        ops.polls += 1
        # the run ends after 90 polls (45 min): longer than the TTL, longer than the old wait
        if ops.polls >= 90:
            ops.executions = [execution(at(1), "running", at(60))]
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert ops.renewed >= 1, "the lease must be renewed while the run is on the phone"
    assert "release" in ops.calls


def test_a_dropped_trigger_leaves_the_phone_free_quickly():
    """The scheduler drops the hourly trigger when the previous run is still going.

    No execution for the guarded hour and the previous one is over: there is nothing to guard, the
    lease must go back at once instead of being held for the whole wait budget.
    """
    clock = Clock()
    ops = FakeOps(executions=[execution(at(-59), "completed", at(-50))])
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert clock.at() < at(10), "the lease must not be held for hours when no run happens"
    assert "release" in ops.calls


def test_the_guard_waits_for_the_previous_run_that_is_still_going():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(-59), "running")])

    def history():
        ops.calls.append("history")
        ops.polls += 1
        if ops.polls >= 5:
            ops.executions = [execution(at(-59), "running", at(1))]
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert clock.at() >= at(2), "the lease must be held while the previous run is on the phone"
    assert "release" in ops.calls


def test_a_guard_started_in_the_middle_of_the_hour_gives_the_phone_back_when_its_run_is_over():
    """A guard that was started (or restarted) in the middle of the hour must not hold the phone
    until the NEXT trigger.

    The guard was SIGTERMed on 2026-10-20 at 19:03, four minutes into the run of 19:00: the run
    carried on without a lease, and the phone was nobody's. A guard that comes back in the middle
    of the hour belongs to the NEXT trigger, so it would have kept the phone until 20:02 - long
    after the run it watches was over. The run's own ledger says when it is really over.
    """
    clock = Clock()
    clock.t += 35 * 60                          # 11:34: the guarded hour would be 12:00
    ops = FakeOps(executions=[execution(at(-20), "running")], settled_after=3)

    def history():
        ops.calls.append("history")
        ops.polls += 1
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert "release" in ops.calls
    assert clock.at() < at(38), "the phone must go back as soon as the run is really over"


def test_a_run_that_ended_late_does_not_free_the_phone_of_the_run_that_is_on_it():
    """The settle row of the previous run must not free the phone while the next run is on it.

    A run of 60 min that starts at 19:00 ends at 20:00 - after the guard of 20:00 has started.
    Its settle row belongs to that old run, so the phone stays leased for the run of 20:00.
    """
    clock = Clock()
    clock.t += 59 * 60                          # 11:58: the guarded hour is 12:00
    ops = FakeOps(executions=[execution(at(1), "running")], settled_after=2,
                  settled_run="r-old", reserved_run="r-new")

    def history():
        ops.calls.append("history")
        ops.polls += 1
        if ops.polls >= 4:
            ops.executions = [execution(at(1), "completed", at(3))]
        return list(ops.executions)

    ops.history = history
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert clock.at() >= at(63), "the phone must stay with the run that is on it"


def test_the_guard_releases_the_lease_when_the_run_does_not_end_in_time():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "running")])
    old = C.MAX_WAIT_S
    C.MAX_WAIT_S = 600                      # 10 min for the test
    try:
        assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_TIMEOUT
    finally:
        C.MAX_WAIT_S = old
    assert "release" in ops.calls


def test_a_refused_claim_leaves_the_phone_to_its_owner():
    clock = Clock()
    ops = FakeOps(claim_ok=False)
    old = C.CLAIM_WAIT_S
    C.CLAIM_WAIT_S = 0
    try:
        assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_REFUSED
    finally:
        C.CLAIM_WAIT_S = old
    assert "release" not in ops.calls


def test_a_failed_release_is_reported():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "skipped")], release_ok=False)
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_RELEASE_FAILED


def test_a_lease_left_by_a_dead_guard_is_released_first():
    clock = Clock()
    ops = FakeOps(executions=[execution(at(1), "skipped")])
    ops.remembered = lambda: "lease000"
    assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_OK
    assert ops.calls[0] == "release"
    assert ("remember", "lease001") in ops.calls


def test_the_history_is_unreachable_without_giving_up_the_lease():
    clock = Clock()
    ops = FakeOps()

    def boom():
        raise OSError("connection reset")

    ops.history = boom
    old = C.MAX_WAIT_S
    C.MAX_WAIT_S = 120
    try:
        assert C.guard(ops, now_fn=clock.now, sleep_fn=clock.sleep) == C.EXIT_TIMEOUT
    finally:
        C.MAX_WAIT_S = old
    assert "release" in ops.calls


@pytest.mark.parametrize("value,expected", [
    ("2026-10-20T11:00:00.000969+00:00", datetime(2026, 10, 20, 11, 0, 0, 969, tzinfo=timezone.utc)),
    ("2026-10-20T11:00:00Z", datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)),
    ("", None),
    (None, None),
    ("not a date", None),
])
def test_the_platform_timestamps_are_parsed(value, expected):
    assert C.parse_ts(value) == expected
