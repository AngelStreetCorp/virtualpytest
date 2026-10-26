#!/usr/bin/env python3
"""TASK-163 — run the Atlas use cases (docs/agent/atlas/USECASES.md) against a live Atlas.

N agents run in parallel, each takes its share of the prompts and asks them one after the other, each prompt in a
fresh Atlas session. Per prompt it records: did it finish, were the expected tools called, any tool failure,
latency, tokens, model. A prompt passes only when it ended cleanly, called every expected tool (``a/b`` = either)
and no tool failure is left unrecovered. The *observable* result (device state, screenshot) is checked separately
(README, "Browser check"); this script is the fast first filter.

  scripts/atlas_usecase_bench.py --vars vars.json --agents 10 --model-label minimax --out /tmp/bench.jsonl
  scripts/atlas_usecase_bench.py --table /tmp/bench.jsonl [/tmp/other.jsonl ...]
  scripts/atlas_usecase_bench.py --dry-run

Rows that act on a device (execute_*, take_control, release_control) run only with --live; without it the
read-only rows run. Claim a lease for the devices in --vars first (deploy skill). Server and auth: same env
variables as scripts/atlas_chat.py (SERVER_URL, AUTO_SIGN_TOKEN, TEAM_ID).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
USECASES = REPO / "docs/agent/atlas/USECASES.md"
ROW = re.compile(r"^\|\s*(UC-\d{3})\s*\|(.*)\|\s*$")
MUTATING = re.compile(r"^(execute_|take_control|release_control)")
FAILURE_TEXT = ("unknown command", "does not exist", "not in your allowed tools")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usecase_contract import contract_rows  # noqa: E402


def parse_usecases(path: Path = USECASES) -> list[dict]:
    """The rows of the contract table — and only those.

    The file also holds the results tables and the browser-verification table, whose
    rows start with a UC- id too. Those are documentation, not contract rows: a
    browser row is graded against a tools cell that holds prose ("list_hosts,
    get_device_info (both ticked)"), so no call can satisfy it and the row can
    never pass — it would only depress the reported pass rate. So the contract table
    is found by its section (scripts/usecase_contract.py), not by scanning the file.
    """
    rows = []
    for row in contract_rows(path.read_text()):
        cells = row["cells"]
        if len(cells) < 4:
            continue
        prompt, tools, expected, verify = cells[0], cells[1], cells[2], cells[3]
        names = [] if tools in ("", "—") else [t.strip().strip("`") for t in tools.split(",")]
        rows.append({"id": row["id"], "prompt": prompt, "tools": names, "expected": expected, "verify": verify})
    return rows


def fill(prompt: str, variables: dict) -> str | None:
    """Substitute {name}; None when a placeholder has no value (the row is skipped, not guessed)."""
    missing = [k for k in re.findall(r"\{(\w+)\}", prompt) if k not in variables]
    if missing:
        return None
    return re.sub(r"\{(\w+)\}", lambda m: str(variables[m.group(1)]), prompt)


def is_mutating(row: dict) -> bool:
    return any(MUTATING.match(t.split("/")[0]) or any(MUTATING.match(a) for a in t.split("/")) for t in row["tools"])


def grade(row: dict, called: list[str], failures: list[str], answer: str, ended: bool, errored: bool) -> dict:
    expected = row["tools"]
    missing = [t for t in expected if not any(alt in called for alt in t.split("/"))]
    unrecovered = bool(failures) and bool(called) and failures[-1] == called[-1]
    bad_text = [w for w in FAILURE_TEXT if w in (answer or "").lower()]
    if not expected:  # safety rows: nothing that changes state may run
        missing = []
        acted = [t for t in called if MUTATING.match(t) or t.startswith(("delete_", "update_"))]
        tools_ok = not acted
    else:
        tools_ok = not missing
    ok = ended and not errored and tools_ok and not unrecovered and not bad_text
    why = []
    if not ended: why.append("no session_ended")
    if errored: why.append("error event")
    if missing: why.append("missing " + ",".join(missing))
    if not expected and not tools_ok: why.append("acted on a refusal case")
    if unrecovered: why.append("last tool failed")
    if bad_text: why.append("reply says " + bad_text[0])
    return {"pass": ok, "why": "; ".join(why)}


def ui_context(server: str, args, chat) -> dict:
    """What the Atlas page sends beside the message: the devices it lists (name, host, id, model) and the hosts.
    Without it Atlas cannot map a device name to host_name + device_id, which the real UI never lacks."""
    import requests
    r = requests.get(f"{server}/server/system/getAllHosts", params={"team_id": args.team_id},
                     headers={**chat._service_headers(), **({"X-Auto-Sign": args.auto_sign} if args.auto_sign else {})},
                     timeout=30)
    hosts = [h for h in r.json().get("hosts", []) if h.get("status", "online") == "online"]
    # The page sends the whole device record (hosts.flatMap(host => host.devices)); the
    # backend reads preferred_userinterface from it to tell the model which tree to
    # navigate. Keep that field or the bench is not what the user gets.
    devices = [{"host_name": h["host_name"], "device_id": d.get("device_id"), "device_name": d.get("device_name"),
                "device_model": d.get("device_model"),
                "preferred_userinterface": d.get("preferred_userinterface")}
               for h in hosts for d in h.get("devices", [])
               if d.get("device_id") not in (None, "host")]
    return {"available_devices": devices, "selected_server_hosts": [h["host_name"] for h in hosts]}


def release_locks(server: str, args, chat, started: float) -> int:
    """A prompt that takes control leaves a lock under Atlas's own tool session. Free the manual locks created while
    this prompt ran (lock age <= elapsed) so the next prompt starts clean. Run it under a lease: nothing else locks then."""
    import requests
    n = 0
    try:
        r = requests.get(f"{server}/server/control/lockedDevices", params={"team_id": args.team_id},
                         headers={**chat._service_headers(), **({"X-Auto-Sign": args.auto_sign} if args.auto_sign else {})},
                         timeout=20)
        locks = (r.json() or {}).get("locked_devices", {}).values()
    except Exception:  # noqa: BLE001
        return 0
    elapsed = time.time() - started
    for lock in locks:
        if lock.get("owner_type") != "manual_control" or float(lock.get("lock_age_seconds") or 1e9) > elapsed + 5:
            continue
        try:
            chat.release_device_control(server, True, args.auto_sign, lock["host_name"], lock["device_id"],
                                        lock["owner_session_id"])
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def reported_model(server: str, args, session_id: str) -> tuple[Optional[str], list[str]]:
    """The model the server actually answered this session with, read from the AI call log
    (``ai_calls`` keeps the session id as ``request_id``). The agent events carry no model, so this
    is the only trustworthy attribution. Returns ``(model, all_models_seen)``."""
    import requests
    try:
        r = requests.get(f"{server}/server/ai/usage/calls",
                         params={"source": "calls", "team_id": args.team_id, "hours": 1, "scope": "mine",
                                 "request_id": session_id, "limit": 50},
                         headers={**chat_headers(args), **({"X-Auto-Sign": args.auto_sign} if args.auto_sign else {})},
                         timeout=25)
        rows = (r.json() or {}).get("calls") or []
    except Exception:  # noqa: BLE001
        return None, []
    rows = sorted(rows, key=lambda x: str(x.get("ts") or ""))
    models = [row.get("model") for row in rows if row.get("model")]
    if not models:
        return None, []
    return models[-1], sorted(set(models))


def chat_headers(args) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import atlas_chat as chat  # noqa: E402
    return chat._service_headers()


def ask(prompt: str, args, sio_mod, chat) -> dict:
    """One prompt in a fresh session; returns the raw observation."""
    server = args.server.rstrip("/")
    started = time.time()
    obs = {"called": [], "failures": [], "answer": "", "ended": False, "errored": False,
           "tokens": 0, "model": None, "first_event_s": None, "events": 0}
    try:
        session_id = chat.create_session(server, True, args.auto_sign)
    except Exception as e:  # noqa: BLE001
        obs["answer"] = f"session failed: {chat._redact(e)}"
        obs["errored"] = True
        obs["latency_s"] = round(time.time() - started, 2)
        return obs
    obs["session_id"] = session_id
    done = threading.Event()
    sio = sio_mod.Client(ssl_verify=True, reconnection=False)

    @sio.on("connect", namespace="/agent")
    def _c():
        sio.emit("join_session", {"session_id": session_id}, namespace="/agent")
        time.sleep(1)
        sio.emit("send_message", {
            "session_id": session_id, "message": prompt, "team_id": args.team_id, "agent_id": "assistant",
            "allow_auto_navigation": False, "current_page": "/ai-agent", "host_name": "", "device_id": "",
            "userinterface_name": "", "pinned_profile_id": args.pinned_profile or "", **args.context}, namespace="/agent")

    @sio.on("agent_event", namespace="/agent")
    def _e(ev):
        obs["events"] += 1
        if obs["first_event_s"] is None:
            obs["first_event_s"] = round(time.time() - started, 2)
        t = ev.get("type")
        if t == "thinking" and "Waiting for another conversation" in str(ev.get("content")):
            obs["queued"] = True
        elif obs.get("queued") and obs.get("run_start") is None and t != "thinking":
            obs["run_start"] = time.time()
        m = ev.get("metrics") or {}
        obs["tokens"] += int(m.get("input_tokens") or 0) + int(m.get("output_tokens") or 0)
        obs["model"] = m.get("model") or obs["model"]
        if t == "tool_call" and ev.get("tool_name"):
            obs["called"].append(ev["tool_name"])
        elif t == "tool_result" and ev.get("success") is False:
            obs["failures"].append(ev.get("tool_name"))
        elif t in ("message", "result"):
            c = ev.get("content")
            obs["answer"] += (c if isinstance(c, str) else json.dumps(c, default=str)) + "\n"
        elif t == "error" and ev.get("tool_name"):  # a tool raised: a failure only if it is the last thing that happened
            obs["failures"].append(ev["tool_name"])
            obs["called_after_error"] = len(obs["called"])
            obs["answer"] += str(ev.get("content")) + "\n"
        elif t == "error":
            obs["errored"] = True
            obs["answer"] += str(ev.get("content")) + "\n"
        elif t == "session_ended":
            obs["ended"] = True
            done.set()

    @sio.on("disconnect", namespace="/agent")
    def _d():
        done.set()

    try:
        sio.connect(server, namespaces=["/agent"], wait_timeout=20, headers=chat._service_headers(),
                    auth={"auto_sign": args.auto_sign} if args.auto_sign else None)
        if not done.wait(timeout=args.timeout):
            obs["answer"] += f"[timeout {args.timeout}s]"
        sio.disconnect()
    except Exception as e:  # noqa: BLE001
        obs["errored"] = True
        obs["answer"] += f"socket: {chat._redact(e)}"
    obs["latency_s"] = round(time.time() - started, 2)
    if args.cleanup:
        obs["released"] = release_locks(server, args, chat, started)
    if obs.get("run_start"):  # Atlas runs one conversation per worker: report the wait in the queue apart
        obs["queue_s"] = round(obs["run_start"] - started, 2)
        obs["latency_s"] = round(time.time() - obs["run_start"], 2)
    return obs


def run(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import atlas_chat as chat  # noqa: E402
    import socketio  # noqa: E402
    args.server = args.server or chat.DEFAULT_SERVER
    args.team_id = args.team_id or chat.DEFAULT_TEAM
    args.auto_sign = args.auto_sign or chat.AUTO_SIGN
    args.context = {} if args.no_context else ui_context(args.server.rstrip("/"), args, chat)
    variables = json.loads(Path(args.vars).read_text()) if args.vars else {}
    rows = parse_usecases()
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted or r["id"][3:] in wanted]
    jobs, skipped = [], []
    for r in rows:
        text = fill(r["prompt"], variables)
        if text is None:
            skipped.append((r["id"], "no value for a placeholder"))
        elif is_mutating(r) and not args.live:
            skipped.append((r["id"], "acts on a device: needs --live"))
        else:
            jobs.append((r, text))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"{len(jobs)} to run, {len(skipped)} skipped", file=sys.stderr)
    if args.dry_run:
        for r, t in jobs:
            print(f"{r['id']}  {t}  -> {r['tools'] or '—'}")
        for i, why in skipped:
            print(f"{i}  SKIP {why}")
        return 0

    out = open(args.out, "a")
    lock = threading.Lock()

    def agent(chunk):
        for r, text in chunk:
            obs = ask(text, args, socketio, chat)
            for _ in range(2):  # provider rate limit: wait and ask again, the limit is not Atlas's routing
                if "rate limit exceeded" not in obs["answer"].lower():
                    break
                time.sleep(30)
                obs = ask(text, args, socketio, chat)
            time.sleep(args.pause)
            g = grade(r, obs["called"], obs["failures"], obs["answer"], obs["ended"], obs["errored"])
            model, models_seen = reported_model(args.server.rstrip("/"), args, obs.get("session_id") or "")
            rec = {"id": r["id"], "prompt": text, "model_label": args.model_label, "model": model or obs["model"],
                   "models_seen": models_seen,
                   "pinned_profile": args.pinned_profile or "",
                   "expected_tools": r["tools"], "called": obs["called"], "tool_failures": obs["failures"],
                   "latency_s": obs["latency_s"], "queue_s": obs.get("queue_s", 0), "first_event_s": obs["first_event_s"], "tokens": obs["tokens"],
                   "pass": g["pass"], "why": g["why"], "answer": obs["answer"][:600], "ts": time.time()}
            with lock:
                out.write(json.dumps(rec) + "\n")
                out.flush()
                print(f"{'PASS' if g['pass'] else 'FAIL'} {r['id']} {obs['latency_s']:>6}s {g['why']}", file=sys.stderr)

    n = max(1, min(args.agents, len(jobs)))
    chunks = [jobs[i::n] for i in range(n)]
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(agent, chunks))
    out.close()
    table([args.out])
    return 0


INFRA = ("session failed", "502", "bad gateway", "[timeout", "rate limit exceeded", "socket:", "temperature",
         # "AI service error: minimax: unreachable" = the endpoint was marked down after one connection error and
         # the hop is skipped. It is the provider, not Atlas' routing (a pinned run has no fallback hop).
         "unreachable", "no credit")


def cause(rec: dict) -> str:
    """Why a prompt failed: infra (server/provider, not Atlas routing) or the Atlas-side reason."""
    if rec["pass"]:
        return "pass"
    a = (rec.get("answer") or "").lower()
    if any(w in a for w in INFRA):
        return "infra (server/provider)"
    if "in use by" in a:
        return "device busy"
    if "not connected" in a or "no signal" in a:
        return "device state"
    if not rec["called"]:
        return "no tool called"
    if "missing" in rec["why"]:
        return "wrong/missing tool"
    return "tool failed"


def table(paths: list[str]) -> None:
    by_model: dict[str, list[dict]] = {}
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                by_model.setdefault(rec.get("model_label") or rec.get("model") or "?", []).append(rec)
    print("| Model | Prompts | Pass | Infra fails | Pass rate (all) | Pass rate (infra excluded) | Median latency | Tokens/prompt |")
    print("|---|---|---|---|---|---|---|---|")
    for m, recs in sorted(by_model.items()):
        n, ok = len(recs), sum(1 for r in recs if r["pass"])
        infra = sum(1 for r in recs if cause(r).startswith("infra"))
        lat = sorted(r["latency_s"] for r in recs)[n // 2]
        tok = sum(r["tokens"] for r in recs) // n
        print(f"| {m} | {n} | {ok} | {infra} | {100 * ok // n}% | {100 * ok // max(1, n - infra)}% | {lat}s | {tok} |")
        causes: dict[str, int] = {}
        for r in recs:
            causes[cause(r)] = causes.get(cause(r), 0) + 1
        print("|  | causes: " + ", ".join(f"{k} {v}" for k, v in sorted(causes.items(), key=lambda kv: -kv[1])) + " | | | | | | |")
    fails = [r for rs in by_model.values() for r in rs if not r["pass"]]
    if fails:
        print("\nFailures:")
        for r in fails:
            print(f"- {r['id']} ({r.get('model_label')}): [{cause(r)}] {r['why']} — {r['prompt']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server"); ap.add_argument("--team-id", dest="team_id"); ap.add_argument("--auto-sign", dest="auto_sign")
    ap.add_argument("--vars", help="JSON file: placeholder -> value")
    ap.add_argument("--agents", type=int, default=2, help="parallel askers; Atlas serves one conversation per server worker, the rest queue")
    ap.add_argument("--timeout", type=int, default=420, help="per prompt, queue wait included")
    ap.add_argument("--model-label", default="default", dest="model_label")
    ap.add_argument("--pinned-profile", dest="pinned_profile", default="",
                    help="profile id to pin this run to (Atlas model picker): one model, no fallback. "
                         "Lets the benchmark score one model without changing the routing table.")
    ap.add_argument("--out", default="atlas_usecase_bench.jsonl")
    ap.add_argument("--only", help="comma list of ids, e.g. UC-001,8")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-context", action="store_true", dest="no_context",
                    help="do not send the device list the Atlas page sends (shows how Atlas does without it)")
    ap.add_argument("--no-cleanup", action="store_false", dest="cleanup", help="keep the locks a prompt took")
    ap.add_argument("--pause", type=float, default=3, help="seconds between prompts of one agent")
    ap.add_argument("--live", action="store_true", help="also run rows that act on a device")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    ap.add_argument("--table", nargs="+", help="print the table of JSONL result files and exit")
    args = ap.parse_args()
    if args.table:
        table(args.table)
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
