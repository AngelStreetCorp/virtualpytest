#!/usr/bin/env python3
"""Idle-device game dispatcher: runs AI game jobs (Clash of Clans, Tetris, Flappy ...) on devices nobody uses,
to collect run data (reports, benchmark_log rows, KPIs) for the data pipeline. Modelled on pokemon_dispatch.py.

A systemd timer runs `game_dispatch.py tick` every minute; each tick moves every job's state machine one step:

  idle     the job is enabled, not past its `until` date, not run for `interval_min`, inside its start slot,
           fewer than MAX_CONCURRENT games running, and a candidate resource is lease-FREE, has NO ticket waiting
           (this is low priority: whoever queued for the device goes first), is online on the job's server, and no
           other game of ours runs on that host -> claim ONE lease for the whole run, start the script through the
           server script API -> running
  running  renew the lease while the task runs; when it ended (or is overdue) release the lease, append one line
           to the run log (job, game, host, model, prompt version, task id, script_result_id, status) -> idle
           A run that passed the job's hard limit (`abort_after_s`) is KILLED first: the host kills the process and its
           completion callback closes the execution row (E50). The overdue threshold only says "stop waiting"; it never
           kills a run, because a long job (a CoC LLM run takes 20-60 min) must not lose a nearly finished run.

Hosts with <= 2 CPUs (host-clone-1/2: 2 cores, overloaded by a Pokemon run on 2026-10-19) lease the WHOLE host, so at
most one game runs there; other hosts lease host/device. Another agent's lease is never touched.

  game_dispatch.py tick          one step (what the timer runs)
  game_dispatch.py status        state of every job, the last runs
  game_dispatch.py jobs          the job table (which are enabled)
  game_dispatch.py plan          what a tick would do right now, without claiming or starting anything

Env: GAME_JOBS (comma list of job names to enable; default = every job whose `default` is true), GAME_MAX_CONCURRENT (2),
GAME_STATE_DIR, GAME_RUN_LOG, GAME_SERVER_URL / GAME_PI_SERVER_URL.
The model and the prompt version of a run are the job's tags (see `tags()`), written to the run log and to the lease purpose.
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
STATE_DIR = os.path.expanduser(os.environ.get("GAME_STATE_DIR", "~/.cache/game-dispatch"))
RUN_LOG = os.path.expanduser(os.environ.get("GAME_RUN_LOG", "~/.cache/game-dispatch/runs.jsonl"))
MAIN_SERVER = os.environ.get("GAME_SERVER_URL", "https://virtualpytest.angelstreet.io")
PI_SERVER = os.environ.get("GAME_PI_SERVER_URL", "https://rpitest.angelstreet.io")
TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
ENV = "node1-vpt"
MAX_CONCURRENT = int(os.environ.get("GAME_MAX_CONCURRENT", "2"))
# The lease: a 10 min TTL renewed every 3 min (the CoC hourly guard does the same). The registry caps a low-priority
# lease at 10 min per claim, so a longer TTL is only a wish: asking for 45 min and renewing every 10 min meant the
# lease died exactly at the renewal moment and the device was free again while the game still ran (2026-10-23).
LEASE_TTL_MIN = 10
LEASE_RENEW_S = 180
SMALL_HOST_CPUS = 2
# CPU cores per host (static: the hosts are fixed; an unknown host is treated as small, the safe side).
HOST_CPUS = {"host-clone-1": 2, "host-clone-2": 2, "vpt-pi1": 4, "labox-backend": 2}
HISTORY = 40

# The job table. `until` is the first day the job no longer starts (None = it runs as long as it is enabled).
# `slot` = (lo, hi): a run may start only while minute-of-the-hour % 30 is in [lo, hi] (the hourly CoC run claims
# vpt-pi1/device1 at :29 and :59, so a CoC job starts right after those and must end before them).
# `model` / `prompt` tag the data: model served for the run, and how the prompt version is derived ("-" = no model).
JOBS = [
    {"name": "coc-flash", "game": "clashofclans", "default": True, "server": PI_SERVER,
     "resources": [{"host": "vpt-pi1", "device": "device1", "lease": "vpt-pi1/device1"}],
     "script": "game/game_clashofclans_llm.py",
     "params": "--mode play --max_steps 40 --run_budget_usd 0.05 --model_choice flash clashofclans-android-mobile",
     # No end date: the Flash plan is unlimited and free (owner, 2026-10-23: "M3.1-Flash is unlimited (free)"),
     # and the model is pinned, so a run costs $0. The job ends when the lane is switched off, not on a date:
     # the gate date 2026-10-25 that ended it also turned the `auto` model choice into the paid Haiku, and the
     # lane spent the owner's money instead of playing (BUG-0918).
     "max_duration_s": 780, "interval_min": 45, "slot": (3, 8), "until": None,
     # A CoC LLM run takes 20-60 min: the recorded runs of this job ended at 1079, 1161,
     # 1268 and 1479 s. The host's own grace for a CoC LLM run is 5400 s (BUG-0717), so
     # the dispatcher must not kill one before that - a run that is nearly finished would
     # be destroyed and its data lost.
     "abort_after_s": 5400,
     "model": "MiniMax-M3.1-Flash-Preview", "prompt": "coc-play-strict-grid",
     "purpose": "CoC Flash data run"},
    {"name": "tetris-web", "game": "tetris", "default": True, "server": MAIN_SERVER,
     "resources": [{"host": h, "device": "host", "lease": h} for h in ("host-clone-2", "host-clone-1")],
     "script": "game/game_tetris.py",
     "params": "--max_pieces 300 --max_duration 900",
     "max_duration_s": 1000, "interval_min": 60, "slot": None, "until": None,
     # The script's own stop (900 s) plus the margin the executor gives it to write the
     # result: the same 1020 s ceiling the executor enforces.
     "abort_after_s": 1020,
     "model": "none", "prompt": "-", "purpose": "Tetris data run"},
    {"name": "flappy-web", "game": "flappy", "default": False, "server": MAIN_SERVER,
     "resources": [{"host": h, "device": "host", "lease": h} for h in ("host-clone-2", "host-clone-1")],
     "script": "game/game_flappy.py",
     "params": "--max_pipes 30 --max_duration 180",
     "max_duration_s": 300, "interval_min": 60, "slot": None, "until": None,
     # The script's own stop (180 s) plus the same margin.
     "abort_after_s": 300,
     "model": "none", "prompt": "-", "purpose": "Flappy data run"},
]


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}", flush=True)


# ---------- pure decisions (unit-tested) ----------

def enabled_jobs(jobs: list[dict], env: str | None) -> list[dict]:
    names = [n.strip() for n in (env or "").split(",") if n.strip()]
    return [j for j in jobs if (j["name"] in names if names else j.get("default"))]


def host_cpus(host: str) -> int:
    return HOST_CPUS.get(host, SMALL_HOST_CPUS)


def lease_for(res: dict) -> str:
    """The resource to lease: a small host is leased whole (one game at a time), a bigger one by its device lease."""
    return res["host"] if host_cpus(res["host"]) <= SMALL_HOST_CPUS else res["lease"]


def in_slot(slot, now: float) -> bool:
    if not slot:
        return True
    m = int(now // 60) % 60 % 30
    return slot[0] <= m <= slot[1]


def expired(job: dict, today: date) -> bool:
    return bool(job.get("until")) and today >= date.fromisoformat(job["until"])


def tags(job: dict) -> dict:
    """What the data pipeline joins a run on: the model served and the prompt version."""
    prompt = job["prompt"]
    if job["game"] == "clashofclans":
        try:   # the exact system prompt of the run, hashed like benchmark_log does
            sys.path.insert(0, REPO)
            sys.path.insert(0, os.path.join(REPO, "scripts"))
            import benchmark_log
            from shared.src.lib.game.clashofclans import llm_player
            prompt = f"{prompt}@{benchmark_log.prompt_sha(llm_player.system_prompt('play', True, True))}"
        except Exception:   # noqa: BLE001 - a missing import must not stop a run
            prompt = f"{prompt}@unknown"
    return {"model": job["model"], "prompt_version": prompt}


def waiting_for(tickets: list[dict], lease_res: str) -> bool:
    """True when a queued ticket wants this resource, its host, or a device on it."""
    def norm(x: str) -> str:
        return re.sub(r"^(device|host|server):", "", str(x).lower().strip())
    want = norm(lease_res)
    host = want.split("/")[0]
    for t in tickets:
        if t.get("env") not in (None, "", ENV):
            continue
        for r in t.get("resources") or []:
            r = norm(r)
            if r == want or r.split("/")[0] == host:
                return True
    return False


def due(job: dict, st: dict, now: float, today: date) -> str | None:
    """Why this job does not start now, or None when it may."""
    if expired(job, today):
        return f"past {job['until']}"
    if st.get("last_start") is not None and now - st["last_start"] < job["interval_min"] * 60:
        return "interval"
    if not in_slot(job.get("slot"), now):
        return "outside its start slot"
    return None


def declared_budget_s(params: str) -> int | None:
    """The budget the script declares for itself (`--max_duration <seconds>`), if any.

    The script stops its own work at that budget; the server hands it to the executor,
    which enforces it as the run's hard ceiling. Without it the run gets the flat default
    hour, and a game run declared at 900 s was still alive at 3600 s (E50).
    """
    m = re.search(r"--max_duration(?:=|\s+)(\d+)", params or "")
    return int(m.group(1)) if m else None


def abort_after_s(job: dict) -> int:
    """The hard limit past which the dispatcher kills the run.

    A job declares it from the product's own rules: the script's own `--max_duration`
    plus the margin it needs to write its result (the executor's ceiling), or the host's
    own grace for a long LLM run (5400 s for a CoC LLM run, BUG-0717).

    This is NOT `max_duration_s`: that one drives the lease TTL and the lease `--expect`
    (13 min for the CoC job), and a 90 min lease on a holder that dies is the orphaned
    lease problem (E40).
    """
    limit = job.get("abort_after_s")
    if limit:
        return int(limit)
    # No declared limit: fall back to the old behaviour (the overdue threshold).
    return int(job["max_duration_s"]) + 900


def pick_resource(job: dict, ops, running_hosts: set[str]) -> dict | None:
    """First candidate that is lease-free, has nobody waiting, is online and runs no other game of ours."""
    for res in job["resources"]:
        host, lease_res = res["host"], lease_for(res)
        if host in running_hosts and host_cpus(host) <= SMALL_HOST_CPUS:
            log(f"{job['name']}: {host} already runs a game (<= {SMALL_HOST_CPUS} CPUs), next")
            continue
        if not ops.lease_free(lease_res):
            log(f"{job['name']}: {lease_res} leased, next")
            continue
        if ops.ticket_waiting(lease_res):
            log(f"{job['name']}: someone is queued for {lease_res}, they go first")
            continue
        if not ops.host_online(job["server"], host, res["device"]):
            log(f"{job['name']}: {host}/{res['device']} not online on its server, next")
            continue
        lease_id = ops.lease_claim(lease_res, job, LEASE_TTL_MIN)
        if not lease_id:
            log(f"{job['name']}: lease claim for {lease_res} refused, next")
            continue
        return {**res, "lease_res": lease_res, "lease_id": lease_id}
    return None


def finish(job: dict, st: dict, ops, now: float, status: str | None) -> None:
    """Release the lease, append the run line, go back to idle."""
    ops.lease_release(st["lease_id"])
    result = ops.task_result(job["server"], st["task_id"]) if status else {}
    ops.record({"job": job["name"], "game": job["game"], "host": st["host"], "device": st["device"],
                "task_id": st["task_id"], "started": st["started"], "ended": now,
                "status": status or "unknown", "script_result_id": result.get("script_result_id"),
                "error": (result.get("error") or "")[:300], **st["tags"]})
    log(f"{job['name']}: run on {st['host']} ended ({status or 'unknown'}), lease released")
    st["history"] = (st.get("history", []) + [{"host": st["host"], "task_id": st["task_id"], "ended": now,
                                                "status": status or "unknown"}])[-HISTORY:]
    for k in ("phase", "host", "device", "lease_id", "task_id", "started", "renewed", "tags"):
        st.pop(k, None)


def tick(state: dict, ops, now: float, jobs: list[dict], today: date | None = None) -> dict:
    """One step for every job. `state` = {job name: job state}; returns it updated."""
    today = today or date.fromtimestamp(now)
    # 1. running jobs first (they free hosts and slots)
    for job in jobs:
        st = state.setdefault(job["name"], {})
        if st.get("phase") != "running":
            continue
        status = ops.task_status(job["server"], st["task_id"])
        elapsed = now - st["started"]
        # Two different thresholds, two different jobs:
        #   overdue  - the dispatcher stops WAITING for the run (it releases the lease and
        #              records the run); the run itself is left alone.
        #   past_abort - the run passed the job's hard limit and is KILLED. The limit is
        #              per job: a CoC LLM run takes 20-60 min, so it must not be killed at
        #              the CoC job's 1680 s stop-waiting threshold (E50 follow-up).
        overdue = elapsed > job["max_duration_s"] + 900
        past_abort = elapsed > abort_after_s(job)
        if status in ("started", None) and not overdue and not past_abort:
            if now - st.get("renewed", st["started"]) > LEASE_RENEW_S:
                ops.lease_renew(st["lease_id"], LEASE_TTL_MIN)
                st["renewed"] = now
            continue
        if status in ("started", None) and past_abort:
            # The run passed its hard limit: stop it instead of walking away from it. The
            # host kills the process and its completion callback closes the row, so the
            # host stops reporting a run nobody watches (E50). `finish` below releases
            # the lease and records the run.
            if ops.abort_run(job["server"], st["host"], st["device"], st["task_id"]):
                status = "aborted"
            else:
                log(f"{job['name']}: could not abort the run {st['task_id']} past its "
                    f"{abort_after_s(job)} s limit; it keeps running")
        finish(job, st, ops, now, status)
    # 2. start what is due
    running = [(j, state[j["name"]]) for j in jobs if state[j["name"]].get("phase") == "running"]
    for job in jobs:
        st = state[job["name"]]
        if st.get("phase") == "running":
            continue
        why = due(job, st, now, today)
        if why:
            continue
        if len(running) >= MAX_CONCURRENT:
            log(f"{job['name']}: {len(running)} games already running (max {MAX_CONCURRENT})")
            continue
        picked = pick_resource(job, ops, {s["host"] for _j, s in running})
        if not picked:
            continue
        try:
            task_id = ops.execute(job["server"], picked["host"], picked["device"], job["script"], job["params"],
                                  timeout_seconds=declared_budget_s(job["params"]))
        except Exception as e:   # noqa: BLE001 - this slot failed: release, try again after the interval
            ops.lease_release(picked["lease_id"])
            st["last_start"] = now
            log(f"{job['name']}: could not start on {picked['host']} ({str(e)[:200]}); lease released")
            continue
        st.update(phase="running", host=picked["host"], device=picked["device"], lease_id=picked["lease_id"],
                  task_id=task_id, started=now, last_start=now, tags=tags(job))
        running.append((job, st))
        log(f"{job['name']}: started {job['script']} on {picked['host']} (task {task_id}, lease {picked['lease_id']}) "
            f"model={st['tags']['model']} prompt={st['tags']['prompt_version']}")
    return state


# ---------- real operations (ssh, lease, server API) ----------

def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


class Ops:
    def __init__(self):
        self._token = None
        self._tickets = None

    def _lease(self, args: str) -> str:
        r = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "proxmox", f"~/bin/vpt-lease {args}"], 60)
        return r.stdout.decode(errors="replace")

    def lease_free(self, res: str) -> bool:
        return self._lease(f"check {ENV} {res}").startswith("FREE")

    def ticket_waiting(self, res: str) -> bool:
        if self._tickets is None:
            try:
                self._tickets = json.loads(self._lease(f"list --json {ENV}")).get("tickets") or []
            except ValueError:
                self._tickets = []
        return waiting_for(self._tickets, res)

    def lease_claim(self, res: str, job: dict, ttl_min: int) -> str | None:
        t = tags(job)
        out = self._lease(f"claim {ENV} {res} --kind host --ttl {ttl_min} --expect {int(job['max_duration_s'] / 60)} "
                          f"--purpose '{job['purpose']} ({t['model']})' --agent codebox:game-dispatch-{job['name']}")
        m = re.search(r"\b[0-9a-f]{8}\b", out)
        return m.group(0) if m and "TICKET" not in out else None

    def lease_renew(self, lease_id: str, ttl_min: int) -> None:
        self._lease(f"renew {lease_id} --ttl {ttl_min}")

    def lease_release(self, lease_id: str) -> None:
        if lease_id:
            self._lease(f"release {lease_id}")

    def _api(self, server: str, method: str, path: str, body: dict | None = None):
        if not self._token:
            self._token = _run([os.path.join(HERE, "auto_sign_token.sh")]).stdout.decode().strip()
            if not self._token:
                raise RuntimeError("no auto-sign token")
        req = urllib.request.Request(server + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"X-Auto-Sign": self._token, "Content-Type": "application/json",
                                              "User-Agent": "vpt-game-dispatch/1"})   # Cloudflare refuses urllib's default
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except ValueError:
                return e.code, {}

    def host_online(self, server: str, host: str, device: str) -> bool:
        _code, data = self._api(server, "GET", "/server/system/getAllHosts")
        for h in (data.get("hosts", []) if isinstance(data, dict) else []):
            if h.get("host_name") == host:
                return h.get("status") == "online" and any(d.get("device_id") == device for d in h.get("devices", []))
        return False

    def execute(self, server: str, host: str, device: str, script: str, params: str,
                timeout_seconds: int | None = None) -> str:
        body = {"host_name": host, "device_id": device, "script_name": script, "parameters": params}
        if timeout_seconds:
            # The budget the script declares for itself: the executor enforces it as the
            # run's hard ceiling (E50).
            body["timeout_seconds"] = timeout_seconds
        code, data = self._api(server, "POST", f"/server/script/execute?team_id={TEAM_ID}", body)
        if code not in (200, 202) or not data.get("task_id"):
            raise RuntimeError(f"execute refused: HTTP {code} {str(data.get('error') or data)[:200]}")
        return data["task_id"]

    def abort_run(self, server: str, host: str, device: str, task_id: str) -> bool:
        """Stop a run that overran its budget.

        The host kills the process and its completion callback closes the execution row,
        so the host stops reporting a run that nobody watches (E50).
        """
        try:
            code, data = self._api(server, "POST", "/server/script/abortRunning",
                                   {"host_name": host, "device_id": device, "task_id": task_id})
        except Exception as e:   # noqa: BLE001 - a failed abort must not stop the tick
            log(f"cannot abort the run {task_id}: {str(e)[:120]}")
            return False
        ok = code == 200 and bool(data.get("success"))
        log(f"aborted the run {task_id} on {host}/{device}: {'ok' if ok else f'HTTP {code}'}")
        return ok

    def _task(self, server: str, task_id: str) -> dict | None:
        code, data = self._api(server, "GET", f"/server/script/status/{task_id}")
        return data.get("task") if code == 200 else None

    def task_status(self, server: str, task_id: str) -> str | None:
        t = self._task(server, task_id)
        return t.get("status") if t else None

    def task_result(self, server: str, task_id: str) -> dict:
        t = self._task(server, task_id) or {}
        r = t.get("result") or {}
        return {"script_result_id": r.get("script_result_id"), "error": r.get("error") or t.get("error") or ""}

    def record(self, row: dict) -> None:
        os.makedirs(os.path.dirname(RUN_LOG), exist_ok=True)
        with open(RUN_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")


# ---------- entry ----------

def load_state() -> dict:
    try:
        with open(os.path.join(STATE_DIR, "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    path = os.path.join(STATE_DIR, "state.json")
    with open(path + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(path + ".tmp", path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["tick", "status", "jobs", "plan"])
    a = ap.parse_args()
    jobs = enabled_jobs(JOBS, os.environ.get("GAME_JOBS"))
    if a.cmd == "jobs":
        for j in JOBS:
            print(f"{'ON ' if j in jobs else 'off'} {j['name']:12} {j['game']:13} {j['script']} {j['params']} "
                  f"(<= {j['max_duration_s']}s, killed after {abort_after_s(j)}s, every {j['interval_min']} min, "
                  f"until {j['until'] or '-'}, {','.join(r['host'] for r in j['resources'])})")
        return 0
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "lock"), "w") as lk:
        try:   # a tick skips while another works
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("another dispatcher tick is still working")
            return 0
        st = load_state()
        if a.cmd == "status":
            print(json.dumps({"jobs": [j["name"] for j in jobs], "max_concurrent": MAX_CONCURRENT, "state": st}, indent=1))
        elif a.cmd == "plan":
            now, today = time.time(), date.today()
            for j in jobs:
                s = st.get(j["name"], {})
                print(f"{j['name']}: " + ("running" if s.get("phase") == "running" else (due(j, s, now, today) or "due now")))
        else:
            save_state(tick(st, Ops(), time.time(), jobs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
