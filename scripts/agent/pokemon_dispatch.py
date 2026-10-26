#!/usr/bin/env python3
"""Play the Pokémon long-play save on any free web host (TASK-33, "Any host").

The save lives in ONE canonical store on codebox (~/vpt-private/pokemon/canonical: ROM, state, memory, backups,
stall reports, stall lock, run segments). A host's /var/lib/vpt-private/pokemon is only a cache for one run.
A systemd timer on codebox runs `pokemon_dispatch.py tick` every minute; each tick moves one state machine one step:

  idle     the canonical lock is set (a stall not yet fixed) -> wait; the last run started < INTERVAL ago -> wait;
           else pick the first host of POKEMON_HOSTS that is lease-FREE and online, claim its lease, push ROM + state +
           memory (+ the lock when a clear is pending) to it, start game/game_pokemon there through the server
           script API -> running
  running  renew the lease while the task runs; once it ended (or is overdue) release the lease -> pull
  pull     copy state, memory, new backups, stall reports, the lock and the run segment back into the canonical store
           -> idle. A pull that fails keeps the canonical save untouched and retries from the same host next tick:
           never two runs of the same save, never a run on a stale save.

  pokemon_dispatch.py tick                 one step (what the timer runs)
  pokemon_dispatch.py status               the state, the canonical save and the last runs
  pokemon_dispatch.py clear-stall          the next run starts with --clear_stall yes (after the stall's fix is deployed)
  pokemon_dispatch.py clear-stall --save second   the same for the other save's lane (it plays that save)
  pokemon_dispatch.py seed <host>          copy a host's cache into the canonical store (first set-up, or a move by hand)

Env: POKEMON_HOSTS (default host-clone-1,host-clone-2), POKEMON_CANON, POKEMON_INTERVAL_MIN (15), VPT_SERVER_URL.
The saves are the owner's: files stay mode 600, nothing is printed but names and sizes.
"""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone

HOSTS = [h for h in os.environ.get("POKEMON_HOSTS", "host-clone-1,host-clone-2").split(",") if h]
CANON = os.path.expanduser(os.environ.get("POKEMON_CANON", "~/vpt-private/pokemon/canonical"))
STATE_DIR = os.path.expanduser(os.environ.get("POKEMON_STATE_DIR", "~/.cache/pokemon-dispatch"))
REMOTE_DIR = "/var/lib/vpt-private/pokemon"
SERVER = os.environ.get("VPT_SERVER_URL", "https://virtualpytest.angelstreet.io")
TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
ENV = "node1-vpt"
DEVICE = "host"
SCRIPT = "game/game_pokemon.py"
SAVE = os.environ.get("POKEMON_SAVE", "latest")
ROM = "pokemon_blue_fr_owner_cartridge.zip"
MAX_DURATION_S = 2000
# The battle chooser of the run. "flash" (MiniMax M3.1 Flash) is the default of the volume lane: it is free
# and unlimited, so a run costs $0. "jev" is the paid decision model of the dataset deployment.
CHOOSER = os.environ.get("POKEMON_CHOOSER", "flash")
PARAMS = f"--save {SAVE} --userinterface pokemon-blue-web --max_duration {MAX_DURATION_S} --chooser {CHOOSER}"
INTERVAL_MIN = float(os.environ.get("POKEMON_INTERVAL_MIN", "15"))
OVERDUE_S = MAX_DURATION_S + 900      # a task still "started" after this is treated as ended (watchdog margin + upload)
# The lease: a 10 min TTL renewed every 3 min (the CoC hourly guard does the same). The registry caps a low-priority
# lease at 10 min per claim, so a longer TTL is only a wish: asking for 45 min and renewing every 10 min meant the
# lease died exactly at the renewal moment (2026-10-23).
LEASE_TTL_MIN = 10
LEASE_RENEW_S = 180
# The holder name of the lease. It must be a name NO tmux session ever had: the lease watcher (ghosty-sessions/
# lease-watch.js, TASK-58 C1) releases the lease of a holder whose session ENDED (a session that existed and is
# gone) two minutes after the claim. "codebox:TASK33-pokemon" named a session that is long over, so every claim
# was released after 2 min and the host ran a second game next to ours on a 2-core box (2026-10-23).
AGENT = os.environ.get("POKEMON_AGENT", "codebox:pokemon-dispatch")
MARKER = ".pushed"                      # touched on the host after a push: what is newer than it came from the run
HISTORY = 30

# what a run writes into the private folder, relative to it (runs/ = the segments of the long game)
_PULL = [re.compile(p) for p in (
    rf"state_{SAVE}\.json", rf"memory_{SAVE}\.json",
    rf"(state|memory)_{SAVE}\.\d{{8}}-\d{{6}}\.json",
    rf"stall_{SAVE}_\d{{8}}-\d{{6}}\.json", rf"stall_{SAVE}\.lock\.json",
    r"runs/\d{8}-\d{6}\.(json|webm)")]


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}", flush=True)


def lock_name(save: str = SAVE) -> str:
    return f"stall_{save}.lock.json"


def clear_request_name(save: str = SAVE) -> str:
    """The request that asks a lane to clear the lock of one save.

    The canonical store is the one place both lanes share, so a request for the *other* save is written
    there and picked up by the lane that plays that save (2026-10-26: the fixer's brief named the plain
    `clear-stall`, which only ever cleared the first lane - the second save stayed locked for 5 h 30).
    """
    return f"clear_{save}.request"


def take_clear_request(canon: str, save: str = SAVE) -> bool:
    """True when a request to clear this save's lock was waiting. The request is consumed."""
    path = os.path.join(canon, clear_request_name(save))
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True


# ---------- pure bookkeeping (unit-tested) ----------

def pull_names(listing: Iterable[str]) -> list[str]:
    """Of the files a host lists as new since the push, the ones that belong in the canonical store."""
    return sorted({n.strip() for n in listing if any(p.fullmatch(n.strip()) for p in _PULL)})


def is_new_save(canon: str) -> bool:
    """True when the canonical store has no save for this name yet: the first run of a second save starts a new
    game (the parallel lane, TASK-164) and the save it writes comes back with the first pull."""
    return not os.path.exists(os.path.join(canon, f"state_{SAVE}.json"))


def push_names(canon: str, clear_stall: bool) -> list[str]:
    """What a host needs for one run: the ROM, the save, its memory, and the lock only when the run is to clear it
    (an uncleared lock never travels: the dispatcher does not start a locked save at all). A save the canonical
    store does not have yet travels as the ROM alone: the run starts a new game."""
    if is_new_save(canon):
        if not os.path.exists(os.path.join(canon, ROM)):
            raise FileNotFoundError(f"canonical store lacks {ROM}")
        return [ROM]
    names = [ROM, f"state_{SAVE}.json", f"memory_{SAVE}.json"]
    missing = [n for n in names if not os.path.exists(os.path.join(canon, n))]
    if missing:
        raise FileNotFoundError(f"canonical store lacks {', '.join(missing)}")
    if clear_stall and os.path.exists(os.path.join(canon, lock_name())):
        names.append(lock_name())
    return names


def apply_pull(staging: str, canon: str, names: list[str]) -> dict:
    """Move a pulled run into the canonical store, the save last. Refuses (and changes nothing) unless the pulled state
    and memory parse: a half-copied save must never replace a good one. The lock follows the host: present there ->
    copied, absent there -> removed here (the run cleared it)."""
    state, memory = f"state_{SAVE}.json", f"memory_{SAVE}.json"
    for n in (state, memory):
        if n not in names:
            raise ValueError(f"pull lacks {n}")
        with open(os.path.join(staging, n)) as f:
            json.load(f)
    os.makedirs(os.path.join(canon, "runs"), mode=0o700, exist_ok=True)
    order = [n for n in names if n not in (state, memory)] + [memory, state]
    for n in order:
        dst = os.path.join(canon, n)
        tmp = dst + ".tmp"
        shutil.copyfile(os.path.join(staging, n), tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dst)
    lock = os.path.join(canon, lock_name())
    if lock_name() not in names and os.path.exists(lock):
        os.unlink(lock)
    return {"files": len(order), "locked": lock_name() in names}


def milestones_done(canon: str) -> int | None:
    """Milestones completed in the canonical memory: the number that must carry over from host to host."""
    try:
        with open(os.path.join(canon, f"memory_{SAVE}.json")) as f:
            memo = json.load(f).get("memo", {})
        return len(memo.get("done", []))
    except (OSError, ValueError):
        return None


def pick_host(hosts: list[str], ops) -> dict | None:
    """First host that is lease-free, free of another game, online and accepts a lease claim:
    {"host", "lease_id"}, or None."""
    for host in hosts:
        if not ops.lease_free(host):
            log(f"{host}: leased, next")
            continue
        if ops.host_busy(host):
            log(f"{host}: another game runs on it, next")
            continue
        if not ops.host_online(host):
            log(f"{host}: not online on the server, next")
            continue
        lease_id = ops.lease_claim(host)
        if not lease_id:
            log(f"{host}: lease claim refused, next")
            continue
        return {"host": host, "lease_id": lease_id}
    return None


def tick(st: dict, ops, now: float, canon: str = CANON, hosts: list[str] | None = None) -> dict:
    """One step of the state machine. `st` is the persisted state; returns it updated."""
    hosts = hosts or HOSTS
    phase = st.get("phase", "idle")
    if phase == "running":
        status = ops.task_status(st["task_id"])
        age = now - st["started"]
        if status in ("started", None) and age < OVERDUE_S:
            # The server does not always get the verdict (the run ends, the verdict does not arrive). The host
            # itself is asked: when the game is over there, the device must not idle until the overdue mark
            # (20 min of a leased host doing nothing, 2026-10-23).
            if age > 120 and not ops.host_running(st["host"]):
                log(f"the run on {st['host']} is over (no game process) although the server still says started: "
                    f"pulling now instead of waiting for the overdue mark")
                status = "ended"
            else:
                # an unknown task (server restarted) waits for the overdue mark too: the run may still be going
                if now - st.get("renewed", st["started"]) > LEASE_RENEW_S:
                    if ops.lease_renew(st["lease_id"]):
                        st["renewed"] = now
                        st.pop("lease_lost", None)
                    elif not st.get("lease_lost"):
                        st["lease_lost"] = now
                        log(f"lease {st['lease_id']} could not be renewed: it is lost, {st['host']} may be taken by another agent")
                return st
        ops.lease_release(st["lease_id"])
        st.update(phase="pull", ended=now, task_status=status or "unknown",
                  result=ops.task_result(st["task_id"]) if status else {})
        log(f"run on {st['host']} ended ({st['task_status']}), lease released")
        phase = "pull"
    if phase == "pull":
        try:
            res = ops.pull(st["host"], canon)
        except Exception as e:   # noqa: BLE001 - any failure keeps the canonical save and retries next tick
            st["pull_error"] = str(e)[:300]
            if "pull lacks" in st["pull_error"]:
                # The run produced nothing to pull (it died before it wrote its save: the emulator froze on the
                # intro or on a menu). Retrying the same pull would never succeed: the run is recorded and the
                # lane goes back to its slots (2026-10-23: the second lane pulled for ever).
                why = st["pull_error"]
                entry = {k: st.get(k) for k in ("host", "task_id", "started", "ended", "task_status")}
                entry.update(files=0, milestones=milestones_done(canon), script_result_id=None, error=why)
                st["history"] = (st.get("history", []) + [entry])[-HISTORY:]
                for k in ("host", "task_id", "lease_id", "started", "ended", "task_status", "result", "pull_error",
                          "renewed", "lease_lost"):
                    st.pop(k, None)
                st["phase"] = "idle"
                log(f"the run on {entry['host']} wrote no save to pull ({why}): recorded, back to the slots")
                return st
            log(f"pull from {st['host']} failed, canonical save untouched, retry next tick: {st['pull_error']}")
            return st
        entry = {k: st.get(k) for k in ("host", "task_id", "started", "ended", "task_status")}
        entry.update(res, milestones=milestones_done(canon), script_result_id=(st.get("result") or {}).get("script_result_id"),
                     error=((st.get("result") or {}).get("error") or "")[:300])
        st["history"] = (st.get("history", []) + [entry])[-HISTORY:]
        for k in ("host", "task_id", "lease_id", "started", "ended", "task_status", "result", "pull_error", "renewed",
                  "lease_lost"):
            st.pop(k, None)
        st["phase"] = "idle"
        log(f"pulled {res['files']} files from {entry['host']} into the canonical store, milestones={entry['milestones']}")
        return st
    # idle
    locked = os.path.exists(os.path.join(canon, lock_name()))
    if take_clear_request(canon):
        st["clear_stall"] = True   # asked from the outside (the stall fixer), for this save
        log("a clear was asked for this save: the next run clears the stall lock")
    if st.get("clear_stall") and not locked:
        st.pop("clear_stall")   # a clear asked twice, or a run already cleared it: nothing to clear (it would reset the counters again)
        log("clear-stall dropped: the save is not locked")
    clear = bool(st.get("clear_stall"))
    if locked and not clear:
        log("save locked by a stall; waiting for the fix (then: pokemon_dispatch.py clear-stall)")
        return st
    if st.get("last_start") is not None and now - st["last_start"] < INTERVAL_MIN * 60:
        return st
    picked = pick_host(hosts, ops)
    if not picked:
        log("no free host this slot")
        return st
    host, lease_id = picked["host"], picked["lease_id"]
    try:
        new_save = is_new_save(canon)
        ops.push(host, canon, push_names(canon, clear))
        params = PARAMS + (" --clear_stall yes" if clear else "") + (" --start new" if new_save else "")
        task_id = ops.execute(host, params)
    except Exception as e:   # noqa: BLE001 - this host failed; release it, the next slot tries again
        ops.lease_release(lease_id)
        log(f"{host}: could not start ({str(e)[:300]}); lease released")
        return st
    st.update(phase="running", host=host, lease_id=lease_id, task_id=task_id, started=now, last_start=now)
    if clear:
        st.pop("clear_stall", None)
    log(f"started {SCRIPT} on {host} (task {task_id}, lease {lease_id}){' clearing the stall lock' if clear else ''}")
    return st


# ---------- real operations (ssh, lease, server API) ----------

def _run(cmd: list[str], stdin=None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout, check=False)


def _ssh(host: str, remote: str, stdin: bytes | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote], stdin, timeout)


class Ops:
    def __init__(self):
        self._token = None

    def _lease(self, args: str) -> str:
        return _ssh("proxmox", f"~/bin/vpt-lease {args}", timeout=60).stdout.decode(errors="replace")

    def lease_free(self, host: str) -> bool:
        return self._lease(f"check {ENV} {host}").startswith("FREE")

    def lease_claim(self, host: str) -> str | None:
        out = self._lease(f"claim {ENV} {host} --kind host --ttl {LEASE_TTL_MIN} --purpose 'TASK-33 Pokemon run' --agent {AGENT}")
        m = re.search(r"\b[0-9a-f]{8}\b", out)
        return m.group(0) if m and "TICKET" not in out else None

    def lease_renew(self, lease_id: str) -> bool:
        """Renew the lease. False when the lease is gone (expired, released or lost): the holder must know."""
        out = self._lease(f"renew {lease_id} --ttl {LEASE_TTL_MIN}")
        return "renewed" in out.lower()

    def lease_release(self, lease_id: str) -> None:
        if lease_id:
            self._lease(f"release {lease_id}")

    def _api(self, method: str, path: str, body: dict | None = None):
        if not self._token:
            here = os.path.dirname(os.path.abspath(__file__))
            self._token = _run([os.path.join(here, "auto_sign_token.sh")], timeout=60).stdout.decode().strip()
            if not self._token:
                raise RuntimeError("no auto-sign token")
        req = urllib.request.Request(SERVER + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"X-Auto-Sign": self._token, "Content-Type": "application/json",
                                              "User-Agent": "vpt-pokemon-dispatch/1"})   # Cloudflare refuses urllib's default
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except ValueError:
                return e.code, {}

    def host_online(self, host: str) -> bool:
        _code, data = self._api("GET", "/server/system/getAllHosts")
        for h in (data.get("hosts", []) if isinstance(data, dict) else []):
            if h.get("host_name") == host:
                return h.get("status") == "online" and any(d.get("device_id") == DEVICE for d in h.get("devices", []))
        return False

    def host_running(self, host: str) -> bool:
        """True when the game is still running on the host. The server's verdict is not always written (the run
        ends, the verdict does not arrive), so the host itself is asked before the device is left idle.

        The pattern is written ``[g]ame_pokemon.py`` on purpose: ``pgrep -f game_pokemon.py`` matches the shell
        that runs it (its own command line holds the pattern), so it would always answer "running"."""
        r = _ssh(host, "pgrep -f '[g]ame_pokemon.py' >/dev/null 2>&1 && echo running || echo gone", timeout=30)
        return "running" in r.stdout.decode(errors="replace")

    def host_busy(self, host: str) -> bool:
        """True when ANOTHER game script runs on the host.

        A lease is the promise that a host is free, but the promise expires: a run that hangs keeps its
        process on the box long after its lease is gone, and the registry then says the host is free. Two
        games on the same 2-core box starve each other and the page stops answering (seen on 2026-10-19,
        again on 2026-10-23 with a tetris run that had outlived its 15-minute budget by 28 minutes).

        The pattern is written ``[g]ame_[a-z0-9_]*.py`` so it does not match the shell that runs it, and it
        catches every game script of the platform (``game_pokemon.py``, ``game_tetris.py``, ...)."""
        r = _ssh(host, "pgrep -f '[g]ame_[a-z0-9_]*\\.py' >/dev/null 2>&1 && echo busy || echo free", timeout=30)
        return "busy" in r.stdout.decode(errors="replace")

    def execute(self, host: str, params: str) -> str:
        code, data = self._api("POST", f"/server/script/execute?team_id={TEAM_ID}",
                               {"host_name": host, "device_id": DEVICE, "script_name": SCRIPT, "parameters": params})
        if code not in (200, 202) or not data.get("task_id"):
            raise RuntimeError(f"execute refused: HTTP {code} {str(data.get('error') or data)[:200]}")
        return data["task_id"]

    def _task(self, task_id: str) -> dict | None:
        code, data = self._api("GET", f"/server/script/status/{task_id}")
        return data.get("task") if code == 200 else None

    def task_status(self, task_id: str) -> str | None:
        t = self._task(task_id)
        return t.get("status") if t else None

    def task_result(self, task_id: str) -> dict:
        t = self._task(task_id) or {}
        r = t.get("result") or {}
        return {"script_result_id": r.get("script_result_id"), "error": r.get("error") or t.get("error") or ""}

    def push(self, host: str, canon: str, names: list[str]) -> None:
        with tempfile.TemporaryFile() as buf:
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for n in names:
                    tar.add(os.path.join(canon, n), arcname=n)
            buf.seek(0)
            d, lock = REMOTE_DIR, f"{REMOTE_DIR}/{lock_name()}"
            remote = (f"set -e; u=$(systemctl show -p User --value vpt-host); u=${{u:-vpt_user}}; "
                      f"sudo -n install -d -m 700 -o $u -g $u {d} {d}/runs; sudo -n rm -f {lock}; "
                      f"sudo -n tar -C {d} -xf - --no-same-owner; "
                      f"cd /; sudo -n chown $u:$u {' '.join(f'{d}/{n}' for n in names)}; "
                      f"sudo -n chmod 600 {' '.join(f'{d}/{n}' for n in names)}; "
                      f"sudo -n touch {d}/{MARKER}")
            r = _ssh(host, remote, stdin=buf.read(), timeout=180)
        if r.returncode:
            raise RuntimeError(f"push to {host} failed: {r.stderr.decode(errors='replace')[-300:]}")

    def pull(self, host: str, canon: str) -> dict:
        d = REMOTE_DIR
        r = _ssh(host, f"sudo -n find {d} -maxdepth 2 -type f -cnewer {d}/{MARKER} -printf '%P\\n'; "
                       f"sudo -n test -f {d}/state_{SAVE}.json && echo state_{SAVE}.json; "
                       f"sudo -n test -f {d}/memory_{SAVE}.json && echo memory_{SAVE}.json; "
                       f"sudo -n test -f {d}/{lock_name()} && echo {lock_name()}; true")
        if r.returncode:
            raise RuntimeError(f"listing {host} failed: {r.stderr.decode(errors='replace')[-200:]}")
        names = pull_names(r.stdout.decode().splitlines())
        with tempfile.TemporaryDirectory(dir=os.path.dirname(canon)) as staging:
            os.chmod(staging, 0o700)
            t = _ssh(host, f"sudo -n tar -C {d} -cf - {' '.join(names)}", timeout=600)
            if t.returncode:
                raise RuntimeError(f"tar on {host} failed: {t.stderr.decode(errors='replace')[-200:]}")
            x = _run(["tar", "-C", staging, "-xf", "-", "--no-same-owner"], stdin=t.stdout, timeout=300)
            if x.returncode:
                raise RuntimeError(f"untar failed: {x.stderr.decode(errors='replace')[-200:]}")
            return apply_pull(staging, canon, names)


# ---------- entry ----------

def load_state() -> dict:
    try:
        with open(os.path.join(STATE_DIR, "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"phase": "idle"}


def save_state(st: dict) -> None:
    path = os.path.join(STATE_DIR, "state.json")
    with open(path + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(path + ".tmp", path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["tick", "status", "clear-stall", "seed"])
    ap.add_argument("host", nargs="?")
    ap.add_argument("--save", default="", help="the save to clear (default: this dispatcher's own)")
    a = ap.parse_args()
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(CANON, mode=0o700, exist_ok=True)
    with open(os.path.join(STATE_DIR, "lock"), "w") as lk:
        try:   # a tick skips while another works; the other commands wait for it
            fcntl.flock(lk, fcntl.LOCK_EX | (fcntl.LOCK_NB if a.cmd == "tick" else 0))
        except OSError:
            log("another dispatcher tick is still working")
            return 0
        st = load_state()
        if a.cmd == "status":
            files = {n: os.path.getsize(os.path.join(CANON, n)) for n in sorted(os.listdir(CANON)) if not n.startswith((".", "runs"))
                     and not re.search(r"\.\d{8}-\d{6}\.json$", n)}
            print(json.dumps({"state": {k: v for k, v in st.items() if k != "history"}, "hosts": HOSTS,
                              "canonical": CANON, "files": files, "milestones": milestones_done(CANON),
                              "locked": os.path.exists(os.path.join(CANON, lock_name())),
                              "last_runs": st.get("history", [])[-5:]}, indent=1))
            return 0
        if a.cmd == "clear-stall":
            save = a.save or SAVE
            if save != SAVE:
                # The other save's lock: the request goes into the canonical store, the lane that plays
                # that save picks it up on its next tick (the plain command only ever clears this lane).
                path = os.path.join(CANON, clear_request_name(save))
                with open(path, "w") as f:
                    f.write(json.dumps({"save": save, "asked_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                log(f"the {save} lane was asked to clear its stall lock ({path})")
            else:
                st["clear_stall"] = True
                if st.get("phase", "idle") == "idle":
                    st.pop("last_start", None)   # play at once; a run in flight keeps its slot
                log("the next run clears the stall lock (--clear_stall yes)")
        elif a.cmd == "seed":
            if not a.host or st.get("phase", "idle") != "idle":
                sys.exit("seed needs a host and an idle dispatcher")
            r = _ssh(a.host, f"sudo -n ls {REMOTE_DIR}")
            names = [n for n in r.stdout.decode().split() if n == ROM] + pull_names(
                n for n in r.stdout.decode().split() if not re.search(r"\.\d{8}-\d{6}\.json$", n))
            with tempfile.TemporaryDirectory(dir=os.path.dirname(CANON)) as staging:
                os.chmod(staging, 0o700)
                t = _ssh(a.host, f"sudo -n tar -C {REMOTE_DIR} -cf - {' '.join(names)}", timeout=600)
                if t.returncode or _run(["tar", "-C", staging, "-xf", "-", "--no-same-owner"], stdin=t.stdout).returncode:
                    sys.exit(f"copy from {a.host} failed; canonical store untouched")
                if ROM in names:
                    shutil.copyfile(os.path.join(staging, ROM), os.path.join(CANON, ROM))
                    os.chmod(os.path.join(CANON, ROM), 0o600)
                res = apply_pull(staging, CANON, [n for n in names if n != ROM])
            log(f"seeded the canonical store from {a.host}: {res['files']} files, milestones={milestones_done(CANON)}")
        else:
            st = tick(st, Ops(), time.time())
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
