#!/usr/bin/env python3
"""TASK-175 — agent routing bench: who answers, through which tier, at what cost.

Every prompt goes to **Atlas** (agent_id ``assistant``) in a fresh session, as a test user, the way the chat
page sends it. Per prompt the harness records which agent answered (the ``agent`` field of the events), the
events that say the turn was handed off, suggested another agent or asked a clarifying question, the tools
called, and the model calls and tokens from ``ai_calls`` (by ``request_id`` = the session id).

The same harness runs before and after the TASK-175 changes, on the same isolated backend, so the two tables
compare like with like.

Run (against a backend with NO hosts — or, once the BUG-0914 guard is live, on a live server with
``--host/--device`` = one leased device, which is then the only device in the chat):

    SERVER_URL=http://127.0.0.1:5213 ATLAS_BENCH_JWT=<test user JWT> \\
        python3 scripts/agent_routing_bench.py --label before --rounds 2 --out /tmp/route-before.jsonl
    python3 scripts/agent_routing_bench.py --table /tmp/route-before.jsonl /tmp/route-after.jsonl

``--cleanup-since <iso>`` deletes the virtual scripts Atlas or Forge created after that time that did not
exist when the run started (the run prints the command), and nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

import requests

SERVER = os.environ.get("SERVER_URL", "http://127.0.0.1:5213")
TEAM = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
JWT = os.environ.get("ATLAS_BENCH_JWT", "")

# (category, prompt, expectation after TASK-175)
PROMPTS = [
    ("create", "create a script", "forge"),
    ("create", "create a virtual script that logs hello world", "forge"),
    ("create", "write a testcase that checks the home screen loads", "forge"),
    ("create", "edit the script SC_RBENCH_01_Missing to log twice", "forge"),
    ("run", "run the script goto_live", "atlas"),
    ("list", "list my test cases", "quick"),
    ("list", "list the scripts", "quick"),
    ("list", "list the campaigns", "quick"),
    ("list", "list the user interfaces", "quick"),
    ("device read", "list the remote keys of phone slot 1", "quick"),
    ("device read", "dump the ui elements of phone slot 1", "quick"),
    ("device read", "is phone slot 1 free or in use?", "quick"),
    ("device read", "is phone slot 1 awake?", "atlas"),  # a screen question: a screenshot, not one lock read
    ("fleet", "which devices are online?", "quick"),
    ("fleet", "show me the open alerts", "quick"),
    ("vague", "cap 5", "clarify"),
    ("vague", "a", "clarify"),
    ("vague", "r", "clarify"),
    ("short real", "heatmap", "not_clarify"),
    ("short real", "alerts", "not_clarify"),
    ("ops", "restart vpt-stream on host-clone-1", "suggest_masterchief"),
    ("ops", "reboot the server", "suggest_masterchief"),
    ("results", "why did the last run on host-clone-1 fail?", "suggest_sherlock"),
]


def _h() -> dict:
    return {"Authorization": f"Bearer {JWT}"}


def api(method: str, path: str, **kw):
    params = {"team_id": TEAM, **(kw.pop("params", None) or {})}
    r = requests.request(method, f"{SERVER}{path}", params=params, headers=_h(), timeout=30, **kw)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def calls_for(session_id: str, wait_s: float = 15.0) -> list[dict]:
    deadline = time.time() + wait_s
    while True:
        _, data = api("GET", "/server/ai/usage/calls",
                      params={"source": "calls", "hours": 1, "scope": "mine", "request_id": session_id, "limit": 80})
        rows = data.get("calls") or []
        if rows or time.time() > deadline:
            return rows
        time.sleep(1.0)


CONTEXT: dict = {}


def device_context(host: str, device: str) -> dict:
    """Only the leased device in the chat context: with the BUG-0914 guard an action on any other device is
    refused, so a live run cannot leave the lease."""
    _, data = api("GET", "/server/system/getAllHosts")
    for h in data.get("hosts") or []:
        for d in (h.get("devices") or []) if h.get("host_name") == host else []:
            if d.get("device_id") == device:
                return {"available_devices": [{"host_name": host, "device_id": device,
                                               "device_name": d.get("device_name"),
                                               "device_model": d.get("device_model")}],
                        "selected_server_hosts": [host]}
    raise SystemExit(f"{host}/{device} is not online on {SERVER}")


def ask(prompt: str, timeout: int) -> dict:
    """One prompt to Atlas in a fresh session. Records what came over the socket."""
    import socketio
    _, created = api("POST", "/server/agent/sessions", json={})
    session_id = created["session"]["id"]
    obs = {"session_id": session_id, "agents": [], "types": [], "called": [], "answer": "",
           "handoff": None, "suggest": None, "clarify": False, "errored": False}
    done = threading.Event()

    def on_event(ev):
        kind = ev.get("type")
        obs["types"].append(kind)
        if ev.get("agent"):
            obs["agents"].append(ev["agent"])
        metrics = ev.get("metrics") or {}
        if kind == "handoff" or metrics.get("handoff_to"):
            obs["handoff"] = metrics.get("handoff_to") or ev.get("content")
        if metrics.get("suggest_agent"):
            obs["suggest"] = metrics["suggest_agent"]
        if metrics.get("match_source") == "clarify":
            obs["clarify"] = True
        if kind == "tool_call" and ev.get("tool_name"):
            obs["called"].append(ev["tool_name"])
        elif kind in ("message", "result"):
            content = ev.get("content")
            obs["answer"] += (content if isinstance(content, str) else json.dumps(content, default=str)) + "\n"
        elif kind == "error":
            obs["errored"] = True
        elif kind == "session_ended":
            done.set()

    sio = None
    for attempt in range(3):
        sio = socketio.Client(reconnection=False)
        sio.on("agent_event", on_event, namespace="/agent")
        try:
            sio.connect(SERVER, namespaces=["/agent"], wait_timeout=20, auth={"token": JWT})
            break
        except Exception:  # noqa: BLE001 - a transient engine.io handshake glitch
            if attempt == 2:
                raise
            time.sleep(3)
    sio.emit("join_session", {"session_id": session_id}, namespace="/agent")
    time.sleep(0.3)
    started = time.time()
    sio.emit("send_message", {
        "session_id": session_id, "message": prompt, "team_id": TEAM, "agent_id": "assistant",
        "allow_auto_navigation": False, "current_page": "/ai-agent",
        "host_name": "", "device_id": "", "userinterface_name": "", **CONTEXT,
    }, namespace="/agent")
    if not done.wait(timeout=timeout):
        obs["answer"] += f"[timeout {timeout}s]"
    obs["turn_s"] = round(time.time() - started, 3)
    sio.disconnect()
    return obs


def tier(calls: list[dict]) -> str:
    keys = [str(c.get("usage_key") or "") for c in calls]
    if not keys:
        return "no_model_call"
    if all(k.endswith("agent.atlas.quick") for k in keys):
        return "quick_step"
    return "full_loop"


def answered_by(obs: dict) -> str:
    names = [a.lower() for a in obs["agents"] if a and a.lower() not in ("system",)]
    return names[-1] if names else "-"


def verdict(expect: str, rec: dict) -> bool:
    if expect == "forge":
        return rec["answered_by"] == "forge" and rec["atlas_model_calls"] == 0
    if expect == "atlas":
        return rec["answered_by"] == "atlas"
    if expect == "quick":
        return rec["tier"] in ("quick_step", "no_model_call") and rec["calls"] <= 2
    if expect == "clarify":
        return rec["clarify"] and not rec["called"] and rec["calls"] == 0
    if expect == "not_clarify":
        return not rec["clarify"]
    if expect.startswith("suggest_"):
        # the event carries the agent id: Sherlock is "analyzer"
        return rec["suggest"] == {"sherlock": "analyzer"}.get(expect.split("_", 1)[1], expect.split("_", 1)[1])
    return False


def run(args) -> int:
    if not JWT:
        raise SystemExit("ATLAS_BENCH_JWT is not set")
    if args.host:
        CONTEXT.update(device_context(args.host, args.device))
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    _, before = api("GET", "/server/virtual-script/list")
    known = {s["id"] for s in before.get("scripts") or []}
    Path(args.out + ".known").write_text(json.dumps(sorted(known)))
    out = open(args.out, "a")
    prompts = [p for p in PROMPTS if not args.only or p[0] in args.only.split(",")]
    for rnd in range(1, args.rounds + 1):
        for cat, prompt, expect in prompts:
            obs = ask(prompt, args.timeout)
            calls = calls_for(obs["session_id"])
            rec = {
                "label": args.label, "round": rnd, "category": cat, "prompt": prompt, "expect": expect,
                "answered_by": answered_by(obs), "tier": tier(calls), "calls": len(calls),
                "atlas_model_calls": sum(1 for c in calls if "agent.atlas" in str(c.get("usage_key") or "")),
                "tokens": sum(int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0) for c in calls),
                "turn_s": obs["turn_s"], "called": obs["called"], "handoff": obs["handoff"],
                "suggest": obs["suggest"], "clarify": obs["clarify"], "errored": obs["errored"],
                "usage_keys": sorted({str(c.get("usage_key") or "") for c in calls}),
                "session_id": obs["session_id"], "ts": time.time(),
            }
            rec["ok"] = verdict(expect, rec)
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(f"[route] {args.label} r{rnd} {cat:<11} {prompt[:40]:<40} by={rec['answered_by']:<7} "
                  f"tier={rec['tier']:<13} calls={rec['calls']:<2} tok={rec['tokens']:<6} "
                  f"{'ok' if rec['ok'] else 'NO'}", file=sys.stderr)
            time.sleep(args.pause)
    out.close()
    print(f"[route] cleanup: python3 scripts/agent_routing_bench.py --cleanup-since {start_iso} "
          f"--known {args.out}.known", file=sys.stderr)
    table([args.out])
    return 0


def cleanup(since: str, known_path: str) -> int:
    """Delete virtual scripts created by an agent after ``since`` that were not there at the start."""
    known = set(json.loads(Path(known_path).read_text()))
    _, data = api("GET", "/server/virtual-script/list")
    removed = 0
    for s in data.get("scripts") or []:
        if s["id"] in known or str(s.get("created_at") or "") < since or s.get("created_by") not in ("atlas", "forge", "sherlock", "nightwatch", "masterchief"):
            continue
        code, _ = api("DELETE", f"/server/virtual-script/{s['id']}")
        print(f"[route] deleted {s.get('name')} ({code})", file=sys.stderr)
        removed += code == 200
    print(f"[route] cleanup: {removed} scripts deleted", file=sys.stderr)
    return 0


def table(paths: list[str]) -> None:
    rows = [json.loads(line) for p in paths for line in Path(p).read_text().splitlines() if line.strip()]
    labels = list(dict.fromkeys(r["label"] for r in rows))
    print("\n| Category | Prompt | " + " | ".join(f"{lb}: by / tier / calls / tokens / ok" for lb in labels) + " |")
    print("|---|---|" + "---|" * len(labels))
    for cat, prompt, _ in PROMPTS:
        cells = []
        for lb in labels:
            rs = [r for r in rows if r["label"] == lb and r["prompt"] == prompt]
            if not rs:
                cells.append("-")
                continue
            by = "/".join(sorted({r["answered_by"] for r in rs}))
            tiers = "/".join(sorted({r["tier"] for r in rs}))
            calls = statistics.median(r["calls"] for r in rs)
            tok = int(statistics.median(r["tokens"] for r in rs))
            ok = sum(r["ok"] for r in rs)
            cells.append(f"{by} / {tiers} / {calls:g} / {tok} / {ok}/{len(rs)}")
        print(f"| {cat} | {prompt} | " + " | ".join(cells) + " |")
    for lb in labels:
        rs = [r for r in rows if r["label"] == lb]
        print(f"\n{lb}: {len(rs)} asks · expected {sum(r['ok'] for r in rs)}/{len(rs)} · "
              f"tokens total {sum(r['tokens'] for r in rs)} · median {int(statistics.median(r['tokens'] for r in rs))} · "
              f"model calls total {sum(r['calls'] for r in rs)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="run")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--only", default="", help="comma-separated categories")
    ap.add_argument("--host", default="", help="live run: the leased device's host (only that device in the chat)")
    ap.add_argument("--device", default="", help="live run: the leased device id")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--pause", type=float, default=1.5)
    ap.add_argument("--out", default="agent_routing_bench.jsonl")
    ap.add_argument("--table", nargs="+")
    ap.add_argument("--cleanup-since", dest="cleanup_since")
    ap.add_argument("--known")
    args = ap.parse_args()
    if args.table:
        table(args.table)
        return 0
    if args.cleanup_since:
        return cleanup(args.cleanup_since, args.known)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
