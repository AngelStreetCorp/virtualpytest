#!/usr/bin/env python3
"""Guard the CoC hourly run with a vpt-lease on the phone, and release it when the run is over.

The CoC LLM hourly deployment ("CoC LLM hourly", cron 0 * * * *, host vpt-pi1, device device1) plays
Clash of Clans on the shared phone. While it plays, no other agent may touch that phone, so the run
is guarded by a vpt-lease on node1-vpt/vpt-pi1/device1, claimed one minute before the trigger.

CoC is LOW priority (owner, 2026-10-20): the phone is a shared resource and the run must never hog
it. The guard therefore works like this:

  * the lease is claimed with the **background priority P3** and a 10 min TTL. The registry caps a
    P2/P3 lease at 10 min per claim and renewal, and refuses the renewal while a claim of higher
    priority (P0-P2) waits on the phone: the CLI answers that with exit code 7 (E_YIELD_REQUIRED);
  * every minute the guard asks the registry who waits for the phone anyway: a queued claim (a
    ticket) or a queued host deploy on the same resource. That catches the waiters the registry's
    priority rule does not see (a deploy is not a ticket);
  * while nobody waits, the run keeps its lease and the guard renews it (every 3 min; each renewal
    gives the lease 10 more minutes);
  * the moment somebody waits - the registry says so (exit 7) or the guard sees it - the guard
    **stops renewing** and asks the run to stop: it writes a flag file on the phone
    (`/tmp/vpt-coc-run-stop`, plus a copy in `/var/lib/vpt/coc_frames/llm/STOP`), which the player
    reads at every turn boundary (`llm_player.stop_requested()`), so the run ends cleanly with
    `stop=yielded` at its next turn - never killed in the middle of a step. The run then gives the
    phone back (the guard releases the lease) and the next hourly run tries again: the phone is
    never held more than one turn (~10 min) past a waiting claim;
  * the lease is always RELEASED, never left to expire (BUG-0717).

The lease has to outlive the run. A CoC LLM run lasts 20-60 min (60-90 model steps at ~35 s each),
so the old guard (a fixed 45 min TTL and a 45 min wait) let the lease expire in the middle of the
run: the registry recorded lease:expired instead of lease:released, and the phone stayed in use for
the rest of the run without any lease (BUG-0717). A lease left behind by a dead guard is released at
the next start.

"Free again" means: no execution of the deployment is running any more. That covers the three ways
an hour ends - the run finished (completed_at), the platform skipped the trigger (the device was
busy), and the trigger never fired at all (the scheduler drops it when the previous run is still
going: APScheduler runs the whole script inside the job, with max_instances=1).

  coc_run_lease.py guard   claim, wait for the run, release (what the systemd timer runs)
  coc_run_lease.py status  what the guard sees now: the lease, the state file, the last run

Env: COC_RUN_LEASE_BIN (the vpt-lease CLI, default /home/jndoye/bin/vpt-lease), COC_RUN_LEASE_STATE
(default ~/.coc-run-lease.id), COC_RUN_SERVER (the platform API, default https://virtualpytest.
angelstreet.io), COC_RUN_TEAM_ID, COC_RUN_DEPLOYMENT_ID, COC_PI_HOST (the phone's host, default
vpt-pi1), COC_STOP_FILE (the flag file the player reads, default /tmp/vpt-coc-run-stop).
Exit: 0 the run is over and the lease was released; 3 the lease was refused (someone else holds or
waits for the phone: the run is asked to give the phone back instead of playing unguarded);
4 the run did not finish in time (the lease was released anyway); 5 the lease could not be released
(it expires by itself); 6 the run yielded the phone to somebody who was waiting for it (the lease was
released).
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

ENV = "node1-vpt"
RESOURCE = "vpt-pi1/device1"
AGENT = "codebox:coc-hourly-run"
PURPOSE = "CoC hourly run"
PROVIDER = "claude"

TTL_MIN = 10          # the lease TTL: CoC is low priority, the phone is never held long without a check
PRIORITY = "P3"       # background, lowest: the registry caps this lease at 10 min and makes it yield
                      # to any P0-P2 waiter (owner, 2026-10-20)
RENEW_EVERY_S = 180   # renew every 3 min: each renewal gives the lease 10 more minutes, so the lease
                      # still has 7-10 min of life when a higher-priority claim asks for the phone
WAITER_CHECK_S = 60   # every minute: who waits for the phone?
YIELD_STOP_TIMEOUT_S = 900   # 15 min: after the stop request the run must be off the phone
YIELD_REQUIRED_RC = 7  # the lease CLI's exit code for E_YIELD_REQUIRED: a claim of higher priority waits
POLL_S = 30           # how often the deployment history is read
MAX_WAIT_S = 10800    # 180 min: longer than the longest observed CoC run (60 min) and than two of
                      # them back to back (the guard holds the phone while runs keep coming)
CLAIM_WAIT_S = 600    # 10 min: the phone may be busy (another agent's lease) when the trigger fires
TRIGGER_GRACE_S = 120 # 2 min: the trigger of the guarded hour fires at the top of the hour
MAX_RUN_WINDOW_S = 10800   # 3 h: a row that is still 'running' after that is an orphan, not a run
SERVER = "https://virtualpytest.angelstreet.io"
TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
DEPLOYMENT_ID = "b1238a96-481c-4157-a5d3-5594cb1bd6d6"
PI_HOST = "vpt-pi1"   # the phone's host: the stop flag and the run's ledger live there
LEDGER = "/var/lib/vpt/coc_frames/llm/ledger.jsonl"
# The flag the player reads between two turns. /tmp works for both users (the run runs as vpt_user,
# the guard as the ssh user of the Pi); the second path is the frames dir (sudo), a belt-and-braces copy.
STOP_FILES = (os.environ.get("COC_STOP_FILE", "/tmp/vpt-coc-run-stop"),
              "/var/lib/vpt/coc_frames/llm/STOP")

EXIT_OK = 0
EXIT_REFUSED = 3      # somebody else holds the phone: the run goes unguarded
EXIT_TIMEOUT = 4      # the run is still going, the lease is released anyway
EXIT_RELEASE_FAILED = 5   # the lease could not be released, it expires by itself
EXIT_YIELDED = 6      # the run gave the phone to somebody who was waiting for it


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}", flush=True)


# ---------- pure decisions (unit-tested) ----------

def parse_ts(value) -> datetime | None:
    """An ISO timestamp from the platform as an aware datetime (None when it is missing or broken)."""
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def is_terminal(ex: dict) -> bool:
    """The run is over: the platform wrote a result, or it skipped the trigger."""
    if ex.get("completed_at"):
        return True
    return str(ex.get("status") or "").lower() == "skipped"


def scheduled_at(ex: dict) -> datetime:
    return parse_ts(ex.get("scheduled_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)


def guarded_hour(since: datetime) -> datetime:
    """The hour whose run the guard waits for: the trigger the claim belongs to.

    The platform triggers the deployment at the top of the hour and the guard claims one minute
    before it, so the guarded hour is the next top of the hour. A claim that lands within the
    claim window after a trigger (the phone was busy, the claim was refused and retried) still
    belongs to that hour: its run is on the phone right now and has to be guarded.

    Live bug 2026-10-20 12:53: a guard started by hand at 12:53 computed the guarded hour as
    12:00, whose trigger had already passed, so it found the phone free 31 s later and released
    the lease - the run of 13:00 would have gone unguarded. A claim belongs to the hour whose
    trigger is still ahead of it, unless the trigger of the current hour fired so recently that
    its run is the one on the phone.
    """
    hour = since.replace(minute=0, second=0, microsecond=0)
    if (since - hour) <= timedelta(seconds=CLAIM_WAIT_S):
        return hour            # the trigger of this hour fired within the claim window
    return hour + timedelta(hours=1)


def running_executions(executions: list[dict], now: datetime, window_s: int = MAX_RUN_WINDOW_S) -> list[dict]:
    """The executions that are still on the phone: not finished and started inside the window.

    A run is finished when the platform wrote a result (completed_at) or skipped the trigger. A
    row that is still 'running' after the window is an orphan (the result save failed), not a run.
    """
    out = []
    for ex in executions or []:
        if is_terminal(ex):
            continue
        started = parse_ts(ex.get("started_at")) or parse_ts(ex.get("scheduled_at"))
        if started is None:
            continue
        if (now - started).total_seconds() <= window_s:
            out.append(ex)
    return out


def phone_free(executions: list[dict], now: datetime, since: datetime, grace_s: int = TRIGGER_GRACE_S) -> bool:
    """True when nothing runs on the phone any more and the guarded hour had its chance.

    The trigger of the guarded hour fires at the top of the hour; before that there is nothing to
    wait for. After it, the phone is free when no execution is running: the run finished, the
    platform skipped the trigger, or the trigger never fired (the scheduler drops it when the
    previous run is still going - APScheduler max_instances=1).
    """
    if now < guarded_hour(since) + timedelta(seconds=grace_s):
        return False
    return not running_executions(executions, now)


def norm_resource(value) -> str:
    """'device:vpt-pi1/device1' -> 'vpt-pi1/device1': the type prefix is dropped, the tail is the resource.

    The registry stores the canonical spelling ('device:host/device'), the legacy CLI prints the
    plain one ('host/device'); both mean the same phone.
    """
    s = str(value or "").strip().lower()
    if ":" in s:
        head, _, tail = s.partition(":")
        if head in ("device", "host", "server"):
            s = tail
    return s


def resource_matches(resources, resource: str = RESOURCE) -> bool:
    """True when one of the resources is ours (the registry spells it 'device:vpt-pi1/device1')."""
    want = norm_resource(resource)
    for r in resources or []:
        if isinstance(r, str):
            if norm_resource(r) == want:
                return True
        elif isinstance(r, dict):
            if norm_resource(r.get("resource") or r.get("name") or "") == want:
                return True
    return False


def waiting_claims(payload: dict, resource: str = RESOURCE) -> list[dict]:
    """The claims that wait for our phone, read from `vpt-lease list --json`.

    The registry answers with the leases, the queued deploys, the deploy waiters and the tickets
    (the queued claims). A waiting ticket on our resource is somebody queueing for the phone; a
    queued host deploy on our env waits for our lease too (a host deploy cannot run while the
    phone is leased, so it defers).
    """
    out = []
    for t in payload.get("tickets") or []:
        if str(t.get("state") or "") != "waiting":
            continue
        if resource_matches(t.get("resources") or [], resource):
            out.append({"kind": "ticket", "id": t.get("id"), "agent": t.get("agent"),
                        "position": t.get("position"), "eta": t.get("eta")})
    host_part = norm_resource(resource).split("/")[0]
    deploys = payload.get("deploys") or []
    for d in deploys:
        if str(d.get("state") or "") not in ("queued", "running", "pending"):
            continue
        scope = str(d.get("scope") or "").lower()
        if "host" not in scope and "full" not in scope:
            continue
        if str(d.get("env") or "").lower() != ENV:
            continue
        hosts = [str(h).split(".")[0].lower() for h in (d.get("hosts") or [])]
        if hosts and host_part not in hosts:
            continue
        out.append({"kind": "deploy", "id": d.get("id"), "agent": d.get("agent"),
                    "position": None, "eta": None})
    for w in payload.get("waiters") or []:
        did = w.get("deployId") or w.get("deploy_id")
        if any(c.get("kind") == "deploy" and c.get("id") == did for c in out):
            out.append({"kind": "waiter", "id": did, "agent": w.get("agent"),
                        "position": None, "eta": None})
    return out


def ledger_state(lines, since_ts: float) -> dict:
    """What the run's ledger on the phone says since a moment in time.

    The ledger records a 'reserve' when a run starts and a 'settle' when it ends (with the reason
    it ended). The platform's own history lags by minutes, so the ledger is the fast signal that
    the run is really off the phone.
    """
    out = {"settled": None, "stop": None, "reserved": None}
    for line in lines or []:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        try:
            ts = float(rec.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= since_ts:
            continue
        kind = rec.get("kind")
        if kind == "settle":
            out["settled"], out["stop"] = rec.get("run_id"), rec.get("stop")
        elif kind == "reserve":
            out["reserved"] = rec.get("run_id")
    return out


# ---------- real operations (ssh, lease, platform API) ----------

def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


class Ops:
    def __init__(self, lease_bin: str | None = None, server: str | None = None, token_script: str | None = None,
                 team_id: str | None = None, deployment_id: str | None = None, state_path: str | None = None,
                 pi_host: str | None = None, stop_files=None):
        self.lease_bin = lease_bin or os.environ.get("COC_RUN_LEASE_BIN", "/home/jndoye/bin/vpt-lease")
        self.server = (server or os.environ.get("COC_RUN_SERVER", SERVER)).rstrip("/")
        self.token_script = token_script or os.path.join(HERE, "auto_sign_token.sh")
        self.team_id = team_id or os.environ.get("COC_RUN_TEAM_ID", TEAM_ID)
        self.deployment_id = deployment_id or os.environ.get("COC_RUN_DEPLOYMENT_ID", DEPLOYMENT_ID)
        self.state_path = state_path or os.path.expanduser(
            os.environ.get("COC_RUN_LEASE_STATE", "~/.coc-run-lease.id"))
        self.pi_host = pi_host or os.environ.get("COC_PI_HOST", PI_HOST)
        self.stop_files = tuple(stop_files or STOP_FILES)
        self._token = None

    # ----- the lease registry -----

    def _lease(self, args: list[str]) -> tuple[int, str]:
        r = _run([self.lease_bin] + args, 60)
        out = (r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")).strip()
        return r.returncode, out

    def claim(self) -> str | None:
        code, out = self._lease(["claim", ENV, RESOURCE, "--agent", AGENT, "--provider", PROVIDER,
                                  "--purpose", PURPOSE, "--ttl", str(TTL_MIN), "--kind", "host",
                                  "--priority", PRIORITY])
        if code != 0:
            return None
        for line in out.splitlines():
            m = re.fullmatch(r"([0-9a-f]{8})", line.strip())
            if m:
                return m.group(1)
        return None

    def renew(self, lease_id: str, ttl_min: int | None = None) -> int:
        """Renew the lease. The exit code says it all: 0 ok, 7 = a higher-priority claim waits
        (E_YIELD_REQUIRED: stop at the next turn boundary and release), anything else = the lease
        may be gone."""
        code, _out = self._lease(["renew", lease_id, "--ttl", str(ttl_min or TTL_MIN)])
        return code

    def release(self, lease_id: str) -> bool:
        code, _out = self._lease(["release", lease_id])
        return code == 0

    def lease_list(self) -> dict:
        code, out = self._lease(["list", "--json", ENV])
        if code != 0:
            return {}
        try:
            data = json.loads(out)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def lease_state(self) -> dict:
        for row in self.lease_list().get("leases") or []:
            res = row.get("resource") or ",".join(row.get("legacy") or [])
            if RESOURCE in res or RESOURCE in json.dumps(row.get("resources") or []):
                return row
        return {}

    def waiting_claims(self) -> list[dict]:
        """Who waits for the phone right now."""
        return waiting_claims(self.lease_list())

    # ----- the phone (ssh) -----

    def _ssh(self, command: str, timeout: int = 30) -> tuple[int, str]:
        r = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.pi_host, command], timeout)
        out = (r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")).strip()
        return r.returncode, out

    def ask_run_to_stop(self) -> bool:
        """Ask the running CoC run to stop at its next turn boundary (a flag file on the phone)."""
        ok = False
        for path in self.stop_files:
            cmd = f"touch {path}" if path.startswith("/tmp/") else f"sudo -n touch {path}"
            code, _out = self._ssh(cmd)
            if code == 0:
                ok = True
        return ok

    def clear_stop_flag(self) -> bool:
        """Remove a stop flag of an earlier yield: this run must not start with a stop order."""
        ok = True
        for path in self.stop_files:
            cmd = f"rm -f {path}" if path.startswith("/tmp/") else f"sudo -n rm -f {path}"
            code, _out = self._ssh(cmd)
            if code != 0:
                ok = False
        return ok

    def ledger_since(self, since_ts: float) -> dict:
        """What the run's ledger on the phone says since a moment in time."""
        code, out = self._ssh(f"tail -n 40 {LEDGER}")
        if code != 0:
            return {}
        return ledger_state(out.splitlines(), since_ts)

    # ----- the platform -----

    def _api_token(self) -> str:
        if self._token is None:
            self._token = _run([self.token_script], 30).stdout.decode().strip()
            if not self._token:
                raise RuntimeError("no auto-sign token")
        return self._token

    def history(self) -> list[dict]:
        url = f"{self.server}/server/deployment/history/{self.deployment_id}?team_id={self.team_id}"
        req = urllib.request.Request(url, headers={"X-Auto-Sign": self._api_token(),
                                                   "User-Agent": "vpt-coc-run-lease/1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        return data.get("executions") or []

    # ----- the state file (a lease a dead guard left behind) -----

    def remember(self, lease_id: str) -> None:
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w") as f:
            f.write(lease_id + "\n")

    def remembered(self) -> str | None:
        try:
            with open(self.state_path) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def forget(self) -> None:
        try:
            os.remove(self.state_path)
        except OSError:
            pass


def guard(ops: Ops, now_fn=time.time, sleep_fn=time.sleep) -> int:
    """Claim the phone, wait for the run, release. Returns the exit code."""
    # a lease a dead guard left behind is released first: it would block the phone until it expires
    stale = ops.remembered()
    if stale:
        log(f"found the lease {stale} of a previous guard, releasing it")
        if ops.release(stale):
            ops.forget()
            log(f"released the stale lease {stale}")
        else:
            log(f"could not release the stale lease {stale}, it expires by itself")

    # a stop order of an earlier yield must not kill this run
    if ops.clear_stop_flag():
        log("the stop flag of an earlier yield is cleared")

    since_ts = now_fn()
    since = datetime.fromtimestamp(since_ts, timezone.utc)
    lease_id = None
    claim_deadline = now_fn() + CLAIM_WAIT_S
    while lease_id is None:
        lease_id = ops.claim()
        if lease_id:
            break
        if now_fn() >= claim_deadline:
            # somebody else holds the phone or waits for it: the CoC run must not play on it
            log("claim refused (someone holds the phone or waits for it): the run is asked to give the phone back")
            if ops.ask_run_to_stop():
                log("the stop order is written on the phone: the run gives it back at its first turn")
            else:
                log("could not write the stop order on the phone")
            return EXIT_REFUSED
        sleep_fn(15)
    ops.remember(lease_id)
    log(f"claimed {lease_id} on {ENV}/{RESOURCE} (ttl {TTL_MIN} min, priority {PRIORITY}, "
        f"renewed every {RENEW_EVERY_S // 60} min), guarding the run of {guarded_hour(since):%H:%M} UTC")

    started = now_fn()
    last_renew = started
    last_wait_check = started
    yielding = False
    yield_since = 0.0
    finished = False

    def _yield(reason: str) -> None:
        """Give the phone back: stop renewing, ask the run to stop at its next turn, release after."""
        nonlocal yielding, yield_since
        yielding = True
        yield_since = now_fn()
        log(f"{reason}: the lease is not renewed any more, the run gives the phone back at its next turn")
        if ops.ask_run_to_stop():
            log("the stop order is written on the phone")
        else:
            log("could not write the stop order on the phone")

    try:
        while now_fn() - started < MAX_WAIT_S:
            sleep_fn(POLL_S)
            now = datetime.fromtimestamp(now_fn(), timezone.utc)

            # 1. does somebody wait for the phone? CoC is low priority: it yields.
            if not yielding and now_fn() - last_wait_check >= WAITER_CHECK_S:
                last_wait_check = now_fn()
                claims = ops.waiting_claims()
                if claims:
                    who = ", ".join(f"{c.get('kind')} {c.get('id')} by {c.get('agent')}" for c in claims)
                    _yield(f"somebody waits for {RESOURCE} ({who})")

            # 2. keep the lease alive - 10 min at a time, only while nobody waits
            if not yielding and now_fn() - last_renew >= RENEW_EVERY_S:
                rc = ops.renew(lease_id, ttl_min=TTL_MIN)
                if rc == 0:
                    last_renew = now_fn()
                elif rc == YIELD_REQUIRED_RC:
                    _yield("the registry wants the phone back (E_YIELD_REQUIRED): a claim of higher "
                           "priority waits on it")
                else:
                    log("renew failed, the lease may be gone")

            # 3. the run must be off the phone before the lease goes back
            if yielding and now_fn() - yield_since >= YIELD_STOP_TIMEOUT_S:
                log("the run did not stop in time, the lease is released anyway")
                break

            # 4. the run's own ledger says whether it is really over. It is the fast signal (the
            #    platform's own history lags by minutes) and it is what tells the waiting agent how
            #    long it still has to wait.
            if yielding:
                led = ops.ledger_since(yield_since)
                if led.get("settled"):
                    finished = True
                    log(f"the run stopped on the phone (stop={led.get('stop')}), the lease goes back now")
                    break
            else:
                led = ops.ledger_since(since_ts)
                # Only the run this guard watches may free the phone. A run that ended LATE (the
                # one of 19:00 settling at 20:05, after the guard of 20:00 started) must not free
                # the phone while the run of 20:00 is still on it: the ledger's last reserve says
                # which run is the current one.
                if led.get("settled") and (not led.get("reserved") or led["settled"] == led["reserved"]):
                    finished = True
                    log(f"the run stopped on the phone (stop={led.get('stop')}), the lease goes back now")
                    break

            # 5. is the run still on the phone?
            try:
                executions = ops.history()
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as e:   # noqa: BLE001
                log(f"cannot read the deployment history ({str(e)[:120]}), retrying")
                continue
            busy = running_executions(executions, now)
            if busy:
                ex = busy[0]
                log(f"the run of {scheduled_at(ex):%H:%M} UTC is still on the phone ({ex.get('status')})")
                continue
            if phone_free(executions, now, since):
                finished = True
                log("no run on the phone any more")
                break
        else:
            log(f"timeout after {MAX_WAIT_S // 60} min, the run is still going")
    finally:
        released = ops.release(lease_id)
        if released:
            ops.forget()
            log(f"released {lease_id}")
        else:
            log(f"could not release {lease_id}, it expires by itself")
    if not released:
        return EXIT_RELEASE_FAILED
    if yielding:
        # the stop order has done its job (or the run was never there): it must not kill the next run
        ops.clear_stop_flag()
        return EXIT_YIELDED
    return EXIT_OK if finished else EXIT_TIMEOUT


def status(ops: Ops) -> int:
    lease = ops.lease_state()
    print(json.dumps({"lease": lease, "state_file": ops.remembered(), "resource": f"{ENV}/{RESOURCE}",
                      "agent": AGENT, "waiting_claims": ops.waiting_claims()}, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["guard", "status"], nargs="?", default="guard")
    a = ap.parse_args()
    ops = Ops()
    if a.cmd == "status":
        return status(ops)
    # a signal must not skip the release: the finally block in guard() frees the lease
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    return guard(ops)


if __name__ == "__main__":
    sys.exit(main())
