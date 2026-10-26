"""Idle-device game dispatcher (scripts/agent/game_dispatch.py): job gating, lease handling, one game per small host.
No ssh, no lease service, no server: a fake Ops stands in for vpt-lease and the script API.

Run: pytest tests/scripts/test_game_dispatch.py -v
"""
import importlib.util
import json
import os
from datetime import date

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "game_dispatch", os.path.join(_here, "..", "..", "scripts", "agent", "game_dispatch.py"))
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

TODAY = date(2026, 10, 20)
NOW = 1_792_400_000 - (1_792_400_000 % 3600) + 5 * 60      # minute 5 of an hour: inside the CoC start slot


def job(name):
    return next(j for j in G.JOBS if j["name"] == name)


class FakeOps:
    def __init__(self, leased=(), tickets=(), offline=(), refuse_claim=(), refuse_exec=()):
        self.leased, self.tickets, self.offline = set(leased), list(tickets), set(offline)
        self.refuse_claim, self.refuse_exec = set(refuse_claim), set(refuse_exec)
        self.calls, self.status, self.n, self.rows = [], {}, 0, []
        self.timeouts, self.aborted, self.rows_closed = [], [], []

    def lease_free(self, res):
        return res not in self.leased

    def ticket_waiting(self, res):
        return G.waiting_for(self.tickets, res)

    def host_online(self, server, host, device):
        return host not in self.offline

    def lease_claim(self, res, jb, ttl):
        if res in self.refuse_claim:
            return None
        self.calls.append(("claim", res, jb["name"], ttl))
        self.leased.add(res)
        self.n += 1
        return f"lease{self.n:03d}"

    def lease_renew(self, lease_id, ttl):
        self.calls.append(("renew", lease_id))

    def lease_release(self, lease_id):
        self.calls.append(("release", lease_id))

    def execute(self, server, host, device, script, params, timeout_seconds=None):
        if host in self.refuse_exec:
            raise RuntimeError("execute refused: HTTP 409")
        self.calls.append(("execute", host, device, script, params))
        self.timeouts.append(timeout_seconds)
        return f"task{len(self.calls)}"

    def abort_run(self, server, host, device, task_id):
        """Kill the run. The host's completion callback closes the execution row (E50)."""
        self.calls.append(("abort", host, device, task_id))
        self.aborted.append(task_id)
        self.rows_closed.append(task_id)
        return True

    def task_status(self, server, task_id):
        return self.status.get(task_id, "started")

    def task_result(self, server, task_id):
        return {"script_result_id": "sr-" + task_id, "error": ""}

    def record(self, row):
        self.rows.append(row)

    def kinds(self):
        return [c[0] for c in self.calls]


def jobs(*names):
    return [job(n) for n in names]


def test_default_jobs_are_coc_and_tetris_only():
    assert [j["name"] for j in G.enabled_jobs(G.JOBS, None)] == ["coc-flash", "tetris-web"]


def test_the_coc_flash_job_has_no_end_date():
    """The Flash plan is unlimited and free (owner, 2026-10-23): the lane plays as long as it is enabled.

    The gate date 2026-10-25 switched the job off and turned the `auto` model choice into the paid Haiku, so the
    lane stopped playing and spent the owner's money instead (BUG-0918)."""
    assert job("coc-flash")["until"] is None
    assert G.expired(job("coc-flash"), date(2026, 10, 25)) is False
    assert G.expired(job("coc-flash"), date(2027, 6, 1)) is False
    # And the job really starts on a day far past the old gate date.
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("coc-flash"), date(2027, 6, 1))
    assert st["coc-flash"]["phase"] == "running" and "--model_choice flash" in ops.calls[1][4]
    assert [j["name"] for j in G.enabled_jobs(G.JOBS, "flappy-web")] == ["flappy-web"]


def test_small_hosts_lease_the_whole_host_and_pi_leases_the_device():
    assert G.lease_for({"host": "host-clone-1", "device": "host", "lease": "host-clone-1"}) == "host-clone-1"
    assert G.lease_for({"host": "vpt-pi1", "device": "device1", "lease": "vpt-pi1/device1"}) == "vpt-pi1/device1"
    assert G.host_cpus("some-unknown-host") <= 2    # unknown = small, the safe side


def test_start_claims_one_lease_executes_and_tags_the_run():
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    s = st["tetris-web"]
    assert s["phase"] == "running" and s["host"] == "host-clone-2" and s["lease_id"] == "lease001"
    assert ops.kinds() == ["claim", "execute"] and ops.calls[0][1] == "host-clone-2"
    assert ops.calls[1][3:] == ("game/game_tetris.py", job("tetris-web")["params"])
    assert s["tags"]["model"] == "none"


def test_coc_run_is_tagged_with_flash_and_a_prompt_hash():
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("coc-flash"), TODAY)
    t = st["coc-flash"]["tags"]
    assert t["model"] == "MiniMax-M3.1-Flash-Preview" and t["prompt_version"].startswith("coc-play-strict-grid@")
    assert len(t["prompt_version"].split("@")[1]) == 12
    assert "--model_choice flash" in ops.calls[1][4] and ops.calls[0][1] == "vpt-pi1/device1"


def test_leased_host_is_skipped_for_the_next_one_and_never_touched():
    ops, st = FakeOps(leased={"host-clone-2"}), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    assert st["tetris-web"]["host"] == "host-clone-1"
    assert ("claim", "host-clone-2", "tetris-web", 31) not in ops.calls and "renew" not in ops.kinds()


def test_nothing_free_means_no_run():
    ops, st = FakeOps(leased={"host-clone-1", "host-clone-2"}), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    assert st["tetris-web"] == {} and ops.calls == []


def test_a_waiting_ticket_goes_first_low_priority():
    tickets = [{"env": "node1-vpt", "resources": ["host-clone-2"], "agent": "someone"},
               {"env": "node1-vpt", "resources": ["device:host-clone-1/device3"], "agent": "other"}]
    ops, st = FakeOps(tickets=tickets), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    assert st["tetris-web"] == {} and ops.calls == []      # a ticket on a device of the host also blocks the host
    ops2 = FakeOps(tickets=[{"env": "node1-vpt", "resources": ["vpt-pi1/device3"]}])
    st2 = {}
    G.tick(st2, ops2, NOW, jobs("coc-flash"), TODAY)       # same host, other device: queued -> we wait
    assert st2["coc-flash"] == {}
    assert not G.waiting_for([{"env": "node1-vpt", "resources": ["host-clone-9"]}], "host-clone-1")


def test_one_game_per_small_host_even_across_jobs():
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("tetris-web", "flappy-web"), TODAY)
    hosts = {st[n]["host"] for n in ("tetris-web", "flappy-web") if st[n].get("phase") == "running"}
    assert len(hosts) == 2 and st["flappy-web"]["host"] != st["tetris-web"]["host"]
    # a third small-host game finds both taken
    ops2, st2 = FakeOps(), {}
    G.tick(st2, ops2, NOW, [job("tetris-web"), {**job("flappy-web"), "name": "flappy2"}, {**job("flappy-web"), "name": "flappy3"}], TODAY)
    assert sum(1 for s in st2.values() if s.get("phase") == "running") == 2   # MAX_CONCURRENT and two small hosts


def test_max_concurrent_caps_games(monkeypatch):
    monkeypatch.setattr(G, "MAX_CONCURRENT", 1)
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("tetris-web", "flappy-web"), TODAY)
    assert [n for n in st if st[n].get("phase") == "running"] == ["tetris-web"]


def test_coc_job_waits_for_its_start_slot_and_keeps_playing_after_the_old_gate_date():
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW + 20 * 60, jobs("coc-flash"), TODAY)          # minute 25: the hourly claim is near
    assert st["coc-flash"] == {} and ops.calls == []
    G.tick(st, ops, NOW + 35 * 60, jobs("coc-flash"), TODAY)          # minute 40 = 10 of the half hour: still outside (3..8)
    assert st["coc-flash"] == {}
    G.tick(st, ops, NOW + 33 * 60, jobs("coc-flash"), TODAY)          # minute 38 = 8: inside
    assert st["coc-flash"]["phase"] == "running"
    # The old gate date (2026-10-25) ended the Flash route and the lane with it. The free plan is unlimited, so
    # the job still starts on that day and on any later one (BUG-0918).
    ops2, st2 = FakeOps(), {}
    G.tick(st2, ops2, NOW, jobs("coc-flash"), date(2026, 10, 25))
    assert st2["coc-flash"]["phase"] == "running"


def test_interval_between_runs():
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    ops.status["task2"] = "completed"
    G.tick(st, ops, NOW + 120, js, TODAY)
    assert st["tetris-web"].get("phase") is None
    G.tick(st, ops, NOW + 30 * 60, js, TODAY)
    assert st["tetris-web"].get("phase") is None and ops.kinds().count("execute") == 1
    G.tick(st, ops, NOW + 61 * 60, js, TODAY)
    assert st["tetris-web"]["phase"] == "running" and ops.kinds().count("execute") == 2


def test_running_job_renews_then_ends_releases_and_logs_the_run():
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    G.tick(st, ops, NOW + 60, js, TODAY)
    assert "renew" not in ops.kinds()
    G.tick(st, ops, NOW + 700, js, TODAY)
    assert ("renew", "lease001") in ops.calls
    ops.status["task2"] = "completed"
    G.tick(st, ops, NOW + 900, js, TODAY)
    assert ("release", "lease001") in ops.calls and st["tetris-web"].get("phase") is None
    row = ops.rows[0]
    assert row["job"] == "tetris-web" and row["status"] == "completed" and row["script_result_id"] == "sr-task2"
    assert row["model"] == "none" and "prompt_version" in row and row["host"] == "host-clone-2"


def test_overdue_task_is_released_even_if_the_server_forgot_it():
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    ops.task_status = lambda server, tid: None            # server restarted: unknown task
    G.tick(st, ops, NOW + 600, js, TODAY)
    assert st["tetris-web"]["phase"] == "running"         # may still be going
    G.tick(st, ops, NOW + job("tetris-web")["max_duration_s"] + 901, js, TODAY)
    assert ("release", "lease001") in ops.calls and ops.rows[0]["status"] == "aborted"


def test_an_overdue_run_is_aborted_and_not_only_released():
    """The dispatcher must not walk away from a live run (E50).

    Releasing the lease and walking away left the process burning the host while the host
    kept a 'running' row for it.
    """
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    ops.task_status = lambda server, tid: None            # the server forgot the task
    G.tick(st, ops, NOW + job("tetris-web")["max_duration_s"] + 901, js, TODAY)

    assert ("abort", "host-clone-2", "host", "task2") in ops.calls
    assert ("release", "lease001") in ops.calls
    assert ops.rows[0]["status"] == "aborted"


def test_a_run_that_is_not_overdue_is_not_aborted():
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    G.tick(st, ops, NOW + 600, js, TODAY)
    assert not any(c[0] == "abort" for c in ops.calls)


def test_a_long_job_is_not_killed_at_its_overdue_threshold():
    """A CoC LLM run takes 20-60 min: it must not be killed at 1680 s (E50 follow-up).

    The recorded runs of this job ended at 1079, 1161, 1268 and 1479 s, and several were
    still going at 1724-1898 s. Killing one at the stop-waiting threshold would destroy a
    run that was nearly finished, and lose its data.
    """
    ops, st = FakeOps(), {}
    js = jobs("coc-flash")
    G.tick(st, ops, NOW + 33 * 60, js, TODAY)             # minute 38 = 8: inside the CoC slot
    assert st["coc-flash"]["phase"] == "running"
    G.tick(st, ops, NOW + 33 * 60 + 1700, js, TODAY)      # past the 1680 s threshold
    # the task still reads "started": the dispatcher moves on and leaves the run alone
    assert not any(c[0] == "abort" for c in ops.calls)
    assert any(c[0] == "release" for c in ops.calls)       # the lease is released
    assert ops.rows[0]["status"] == "started"              # the run is left alone
    assert ops.rows_closed == []


def test_a_run_past_its_abort_limit_is_aborted_and_its_row_closed():
    """Past the job's hard limit the run is killed, the lease freed and the row closed."""
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    G.tick(st, ops, NOW, js, TODAY)
    ops.task_status = lambda server, tid: None             # the server forgot the task
    G.tick(st, ops, NOW + 1021, js, TODAY)                 # past the tetris limit (1020 s)

    assert ("abort", "host-clone-2", "host", "task2") in ops.calls
    assert ("release", "lease001") in ops.calls
    assert ops.rows[0]["status"] == "aborted"
    assert ops.rows_closed == ["task2"]                     # the host's callback closes the row


def test_the_abort_limit_is_per_job_and_does_not_move_the_lease_expect():
    """The lease keeps its own budget: a 90 min lease on a holder that dies is E40."""
    coc = job("coc-flash")
    assert coc["max_duration_s"] == 780                    # unchanged: the lease expect stays 13 min
    assert coc["abort_after_s"] == 5400                    # the host's own CoC grace (BUG-0717)
    assert int(coc["max_duration_s"] / 60) == 13
    assert G.abort_after_s(coc) == 5400

    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW + 33 * 60, jobs("coc-flash"), TODAY)
    assert ("claim", "vpt-pi1/device1", "coc-flash", G.LEASE_TTL_MIN) in ops.calls


def test_the_declared_budget_reaches_the_executor():
    """The budget the script declares for itself is handed to the executor (E50)."""
    assert G.declared_budget_s("--max_pieces 300 --max_duration 900") == 900
    assert G.declared_budget_s("--max_duration=180") == 180
    assert G.declared_budget_s("--mode play --max_steps 40") is None

    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    assert ops.timeouts == [900]          # the tetris script declares 900 s

    ops2, st2 = FakeOps(), {}
    G.tick(st2, ops2, NOW, jobs("coc-flash"), TODAY)
    assert ops2.timeouts == [None]        # the CoC script declares no budget: the default stays


def test_failed_execute_releases_the_lease_and_waits_for_the_interval():
    ops, st = FakeOps(refuse_exec={"host-clone-2"}), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    s = st["tetris-web"]
    assert s.get("phase") is None and ("release", "lease001") in ops.calls and s["last_start"] == NOW


def test_refused_claim_and_offline_host_move_on():
    ops, st = FakeOps(refuse_claim={"host-clone-2"}, offline={"host-clone-1"}), {}
    G.tick(st, ops, NOW, jobs("tetris-web"), TODAY)
    assert st["tetris-web"] == {} and ops.calls == []


def test_only_one_lease_per_run_no_double_claims():
    ops, st = FakeOps(), {}
    js = jobs("tetris-web")
    for i in range(5):
        G.tick(st, ops, NOW + i * 60, js, TODAY)
    assert ops.kinds().count("claim") == 1 and ops.kinds().count("execute") == 1


def test_state_round_trips_through_json():
    ops, st = FakeOps(), {}
    G.tick(st, ops, NOW, jobs("coc-flash", "tetris-web"), TODAY)
    assert json.loads(json.dumps(st)) == st
