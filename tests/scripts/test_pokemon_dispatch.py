"""Pokémon any-host dispatcher (TASK-33): host picking and the push/pull bookkeeping of the canonical save.
No ssh, no lease service, no server: a fake Ops stands in for them.

Run: pytest tests/scripts/test_pokemon_dispatch.py -v
"""
import importlib.util
import json
import os
import shutil

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pokemon_dispatch", os.path.join(_here, "..", "..", "scripts", "agent", "pokemon_dispatch.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

HOSTS = ["host-clone-1", "host-clone-2"]


def _read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


class FakeOps:
    """Records calls; `remote` is each host's private folder as {name: bytes}, a run writes into it."""

    def __init__(self, leased=(), offline=(), refuse_claim=(), refuse_exec=(), gone=(), busy=()):
        self.leased, self.offline = set(leased), set(offline)
        self.gone = set(gone)          # hosts whose game process is over (the server never got the verdict)
        self.busy = set(busy)          # hosts where ANOTHER game still runs (a lease that expired under it)
        self.refuse_claim, self.refuse_exec = set(refuse_claim), set(refuse_exec)
        self.remote = {h: {} for h in HOSTS}
        self.calls, self.status, self.pull_fails = [], {}, 0

    def lease_free(self, host):
        return host not in self.leased

    def host_online(self, host):
        return host not in self.offline

    def host_busy(self, host):
        """A host where another game script still runs (a lease that expired under a stuck run)."""
        return host in self.busy

    def lease_claim(self, host):
        self.calls.append(("claim", host))
        return None if host in self.refuse_claim else f"lease-{host}"

    def lease_renew(self, lease_id):
        self.calls.append(("renew", lease_id))

    def lease_release(self, lease_id):
        self.calls.append(("release", lease_id))

    def push(self, host, canon, names):
        self.calls.append(("push", host, tuple(names)))
        for n in names:
            self.remote[host][n] = _read(os.path.join(canon, n), "rb")

    def execute(self, host, params):
        self.calls.append(("execute", host, params))
        if host in self.refuse_exec:
            raise RuntimeError("HTTP 423 device locked")
        self.status[f"task-{host}"] = "started"
        return f"task-{host}"

    def task_status(self, task_id):
        return self.status.get(task_id)

    def host_running(self, host):
        self.calls.append(("host_running", host))
        return host not in self.gone

    def task_result(self, task_id):
        return {"script_result_id": "sr-1", "error": ""}

    def pull(self, host, canon):
        if self.pull_fails:
            self.pull_fails -= 1
            raise RuntimeError("ssh: connection timed out")
        staging = os.path.join(os.path.dirname(canon), "staging")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(os.path.join(staging, "runs"))
        names = D.pull_names(self.remote[host])
        for n in names:
            with open(os.path.join(staging, n), "wb") as f:
                f.write(self.remote[host][n])
        return D.apply_pull(staging, canon, names)


def _memory(done):
    return json.dumps({"memo": {"done": done}, "world": {}, "log": []}).encode()


@pytest.fixture
def canon(tmp_path):
    c = tmp_path / "canonical"
    c.mkdir()
    (c / D.ROM).write_bytes(b"rom")
    (c / "state_latest.json").write_text('{"s": 1}')
    (c / "memory_latest.json").write_bytes(_memory(["starter", "pewter"]))
    return str(c)


def _play(ops, host, done, stall=False):
    """What a run on `host` leaves in its private folder."""
    r = ops.remote[host]
    r["state_latest.20261019-120000.json"] = r["state_latest.json"]
    r["state_latest.json"] = b'{"s": 2}'
    r["memory_latest.json"] = _memory(done)
    r["runs/20261019-120000.json"] = b"{}"
    r[".state_latest.new"] = b"tmp"
    if stall:
        r["stall_latest_20261019-120000.json"] = b"{}"
        r["stall_latest.lock.json"] = b'{"reason": "no_progress"}'
    else:
        r.pop("stall_latest.lock.json", None)


def test_pull_names_keeps_the_save_and_drops_temp_files():
    got = D.pull_names(["state_latest.json", "memory_latest.json", ".state_latest.new", ".pushed", "state_share.json",
                        "memory_latest.20261019-120000.json", "stall_latest_20261019-120000.json",
                        "stall_latest.lock.json", "runs/20261019-120000.webm", "pokemon_blue_fr_owner_cartridge.zip"])
    assert got == ["memory_latest.20261019-120000.json", "memory_latest.json", "runs/20261019-120000.webm",
                   "stall_latest.lock.json", "stall_latest_20261019-120000.json", "state_latest.json"]


def test_pick_host_skips_leased_offline_and_refused():
    assert D.pick_host(HOSTS, FakeOps(leased=["host-clone-1"]))["host"] == "host-clone-2"
    assert D.pick_host(HOSTS, FakeOps(offline=["host-clone-1"]))["host"] == "host-clone-2"
    assert D.pick_host(HOSTS, FakeOps(refuse_claim=["host-clone-1"]))["host"] == "host-clone-2"
    assert D.pick_host(HOSTS, FakeOps(leased=HOSTS)) is None
    assert D.pick_host(HOSTS, FakeOps()) == {"host": "host-clone-1", "lease_id": "lease-host-clone-1"}


def test_a_run_on_one_host_then_the_next_carries_the_save(canon):
    ops, st = FakeOps(leased=["host-clone-1"]), {}
    st = D.tick(st, ops, 1000, canon, HOSTS)
    assert st["phase"] == "running" and st["host"] == "host-clone-2"
    assert ("push", "host-clone-2", (D.ROM, "state_latest.json", "memory_latest.json")) in ops.calls
    _play(ops, "host-clone-2", ["starter", "pewter", "mt_moon"])
    ops.status["task-host-clone-2"] = "completed"
    st = D.tick(st, ops, 3000, canon, HOSTS)
    assert st["phase"] == "idle" and ("release", "lease-host-clone-2") in ops.calls
    assert _read(os.path.join(canon, "state_latest.json")) == '{"s": 2}'
    assert os.path.exists(os.path.join(canon, "runs", "20261019-120000.json"))
    assert not os.path.exists(os.path.join(canon, ".state_latest.new"))
    assert st["history"][-1]["milestones"] == 3 and st["history"][-1]["host"] == "host-clone-2"
    # next slot: host-clone-1 is free again and gets the save the host-clone-2 run left
    ops.leased.clear()
    st = D.tick(st, ops, 3000 + D.INTERVAL_MIN * 60, canon, HOSTS)
    assert st["host"] == "host-clone-1"
    assert ops.remote["host-clone-1"]["state_latest.json"] == b'{"s": 2}'
    assert json.loads(ops.remote["host-clone-1"]["memory_latest.json"])["memo"]["done"][-1] == "mt_moon"


def test_no_new_run_while_one_is_in_flight_or_too_soon(canon):
    ops = FakeOps()
    st = D.tick({}, ops, 1000, canon, HOSTS)
    st = D.tick(st, ops, 1060, canon, HOSTS)
    assert st["phase"] == "running" and [c[0] for c in ops.calls].count("execute") == 1
    ops.status["task-host-clone-1"] = "failed"
    _play(ops, "host-clone-1", ["starter"])
    st = D.tick(st, ops, 1200, canon, HOSTS)
    assert st["phase"] == "idle"
    st = D.tick(st, ops, 1260, canon, HOSTS)   # < INTERVAL since the last start
    assert [c[0] for c in ops.calls].count("execute") == 1


def test_overdue_or_unknown_task_ends_after_the_overdue_mark(canon):
    ops = FakeOps()
    st = D.tick({}, ops, 0, canon, HOSTS)
    del ops.status["task-host-clone-1"]               # server restarted: the task is unknown
    _play(ops, "host-clone-1", ["starter"])
    assert D.tick(st, ops, D.MAX_DURATION_S, canon, HOSTS)["phase"] == "running"
    assert D.tick(st, ops, D.OVERDUE_S + 1, canon, HOSTS)["phase"] == "idle"


def test_a_run_that_is_over_on_the_host_does_not_idle_the_device_until_the_overdue_mark(canon):
    # 2026-10-23: the run ended on the host but the server never got the verdict, so the dispatcher waited for
    # the overdue mark (20 min) with the device leased and doing nothing.
    ops = FakeOps(gone=("host-clone-1",))
    st = D.tick({}, ops, 0, canon, HOSTS)
    assert st["phase"] == "running"
    _play(ops, "host-clone-1", ["starter"])
    assert D.tick(st, ops, 60, canon, HOSTS)["phase"] == "running"   # too young: the game may still start
    st = D.tick(st, ops, 200, canon, HOSTS)
    assert st["phase"] == "idle"                                   # the host says the game is over: pulled now
    assert ("release", "lease-host-clone-1") in ops.calls


def test_a_run_that_wrote_no_save_is_recorded_and_the_lane_goes_back_to_its_slots(canon):
    # 2026-10-23: the second save's run died before it wrote its save (the emulator froze on the intro), so the
    # pull had nothing to pull - and the lane retried that pull for ever.
    ops = FakeOps(gone=("host-clone-1",))
    st = D.tick({}, ops, 0, canon, HOSTS)
    assert st["phase"] == "running"
    ops.pull_fails = 0
    ops.remote["host-clone-1"].pop("state_latest.json", None)     # the run wrote no save
    st = D.tick(st, ops, 200, canon, HOSTS)
    assert st["phase"] == "idle"
    assert "pull lacks" in st["history"][-1]["error"]
    assert st["history"][-1]["files"] == 0


def test_failed_pull_keeps_the_canonical_save_and_retries_the_same_host(canon):
    ops = FakeOps()
    st = D.tick({}, ops, 0, canon, HOSTS)
    _play(ops, "host-clone-1", ["starter", "pewter", "mt_moon"])
    ops.status["task-host-clone-1"], ops.pull_fails = "completed", 1
    st = D.tick(st, ops, 2100, canon, HOSTS)
    assert st["phase"] == "pull" and st["host"] == "host-clone-1" and "pull_error" in st
    assert _read(os.path.join(canon, "state_latest.json")) == '{"s": 1}'
    st = D.tick(st, ops, 2160 + D.INTERVAL_MIN * 60, canon, HOSTS)   # retries the pull, starts nothing
    assert st["phase"] == "idle" and [c[0] for c in ops.calls].count("execute") == 1
    assert _read(os.path.join(canon, "state_latest.json")) == '{"s": 2}'


def test_a_corrupt_pulled_save_is_refused(canon, tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "state_latest.json").write_text("{trunc")
    (staging / "memory_latest.json").write_bytes(_memory([]))
    with pytest.raises(ValueError):
        D.apply_pull(str(staging), canon, ["memory_latest.json", "state_latest.json"])
    assert _read(os.path.join(canon, "state_latest.json")) == '{"s": 1}'


def test_a_stall_locks_the_store_and_clear_stall_carries_the_lock_once(canon):
    ops = FakeOps()
    st = D.tick({}, ops, 0, canon, HOSTS)
    _play(ops, "host-clone-1", ["starter"], stall=True)
    ops.status["task-host-clone-1"] = "completed"
    st = D.tick(st, ops, 2100, canon, HOSTS)
    assert os.path.exists(os.path.join(canon, "stall_latest.lock.json"))
    st = D.tick(st, ops, 9000, canon, HOSTS)               # locked: no run
    assert [c[0] for c in ops.calls].count("execute") == 1
    st["clear_stall"] = True
    st = D.tick(st, ops, 9000, canon, HOSTS)
    push = [c for c in ops.calls if c[0] == "push"][-1]
    assert "stall_latest.lock.json" in push[2] and "--clear_stall yes" in ops.calls[-1][2]
    assert "clear_stall" not in st
    _play(ops, "host-clone-1", ["starter", "pewter"])     # the run cleared the lock on the host
    ops.status["task-host-clone-1"] = "completed"
    st = D.tick(st, ops, 11000, canon, HOSTS)
    assert not os.path.exists(os.path.join(canon, "stall_latest.lock.json"))


def test_a_host_that_refuses_the_run_gives_its_lease_back(canon):
    ops = FakeOps(refuse_exec=["host-clone-1"])
    st = D.tick({}, ops, 0, canon, HOSTS)
    assert st.get("phase", "idle") == "idle" and ("release", "lease-host-clone-1") in ops.calls


def test_a_clear_on_an_unlocked_save_is_dropped(canon):
    ops = FakeOps()
    st = D.tick({"clear_stall": True}, ops, 0, canon, HOSTS)
    assert "clear_stall" not in st and "--clear_stall yes" not in ops.calls[-1][2]


def test_a_clear_asked_for_another_save_reaches_that_lane(canon):
    """The plain clear command only clears this lane's save. A clear for the other save travels through
    the canonical store, and the lane that plays that save picks it up (2026-10-26: the second lane
    waited 5 h 30 for a lock that was cleared on the first lane)."""
    assert D.clear_request_name("second") == "clear_second.request"
    request = os.path.join(canon, D.clear_request_name("second"))
    with open(request, "w") as f:
        f.write("{}\n")
    # The lane of the *other* save does not touch it.
    assert D.take_clear_request(canon, "latest") is False
    assert os.path.exists(request)
    # The lane that plays that save takes it, and the request is consumed.
    assert D.take_clear_request(canon, "second") is True
    assert not os.path.exists(request)
    assert D.take_clear_request(canon, "second") is False


def test_a_request_in_the_store_clears_the_lock_on_the_next_tick(canon):
    ops = FakeOps()
    st = D.tick({}, ops, 0, canon, HOSTS)
    _play(ops, "host-clone-1", ["starter"], stall=True)
    ops.status["task-host-clone-1"] = "completed"
    st = D.tick(st, ops, 2100, canon, HOSTS)
    assert os.path.exists(os.path.join(canon, "stall_latest.lock.json"))
    st = D.tick(st, ops, 9000, canon, HOSTS)               # locked: no run
    assert [c[0] for c in ops.calls].count("execute") == 1
    with open(os.path.join(canon, D.clear_request_name("latest")), "w") as f:
        f.write("{}\n")
    st = D.tick(st, ops, 9000, canon, HOSTS)
    push = [c for c in ops.calls if c[0] == "push"][-1]
    assert "stall_latest.lock.json" in push[2] and "--clear_stall yes" in ops.calls[-1][2]


def test_a_host_where_another_game_still_runs_is_not_taken(canon):
    """A lease expires under a run that hangs: the registry says the host is free, the box is not.
    The lane asks the host, so the two games do not starve each other."""
    ops = FakeOps(busy=["host-clone-1"])
    st = D.tick({}, ops, 0, canon, HOSTS)
    assert st.get("host") == "host-clone-2"
    assert ("claim", "host-clone-2") in ops.calls and ("claim", "host-clone-1") not in ops.calls


def test_the_volume_lane_plays_with_the_free_chooser(monkeypatch):
    """A free run must cost $0: the battle decisions go to MiniMax M3.1 Flash, not to the paid jev
    model (the chooser of the dataset deployment)."""
    assert "--chooser flash" in D.PARAMS
    assert D.CHOOSER == "flash"
    # the dataset deployment can still ask for jev
    monkeypatch.setenv("POKEMON_CHOOSER", "jev")
    reloaded = _reload_dispatcher()
    assert reloaded.CHOOSER == "jev" and "--chooser jev" in reloaded.PARAMS


def _reload_dispatcher():
    """Load the dispatcher again, so a new POKEMON_CHOOSER is read (the module reads it at import)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pokemon_dispatch_reload", os.path.join(_here, "..", "..", "scripts", "agent", "pokemon_dispatch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
