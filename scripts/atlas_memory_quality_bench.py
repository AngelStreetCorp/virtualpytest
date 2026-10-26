#!/usr/bin/env python3
"""TASK-172 goal 6 — does the memory give a *better* answer, not only a faster one?

The first benchmark (``atlas_memory_bench.py``) measured speed only, and every first answer it
recalled was a non-answer. This harness measures what the owner asked: **ask the same thing twice,
with the memory off and on, and check whether the second answer is right**.

It runs against the deployed server as one real, non-shared user (a test-user JWT: the memory is
refused to shared logins). The three arms are that user's own memory switch, flipped through
``PUT /server/agent/memory`` between arms:

    off      the memory off — Atlas as before
    recall   the memory on, recall mode — a hit answers from the memory, no model call
    context  the memory on, context mode — a hit is a note in the prompt, the model still acts

Per round, per prompt, the arms run one after the other (off → recall → context), so a drift in
the provider's latency lands on all three. Each arm starts from an empty memory
(``DELETE /server/agent/memory``). Every name a prompt creates carries the arm and the round, so
no arm ever finds another arm's artefact.

The prompts and what is checked
-------------------------------
- ``script``  "create a virtual script named SC_BENCH_<tag>_Hello …" — the script must exist after
  ask #1; on ask #2 the answer must name it (and, on a recall, the id it gives must exist).
- ``ui``      "create a user interface named bench_<tag>_ui for an android_tv device" — same, for a
  userinterface.
- ``vague``   the owner's "create a script" and "cap 5" — a turn that produced nothing must NOT be
  remembered: ask #2 must not be answered from the memory.
- ``live``    "press home on Phone slot 1" (the leased device) and the owner's "send cmd to stb" —
  a device command is never answered from the memory: ask #2 must reach the model again.

After ask #2 of the recall arm, the same session says "again": it must run for real (no memory
tier) and the artefact must still exist.

Numbers come from the platform's own records: the turn time from the socket events, tokens and
calls from ``ai_calls`` by ``request_id`` (as in ``atlas_memory_bench.py``).

Run
---
    # a local backend with no hosts (no device can be reached), as the test user
    SERVER_URL=http://127.0.0.1:5213 ATLAS_BENCH_JWT=<test user JWT> \\
        python3 scripts/atlas_memory_quality_bench.py --rounds 3 --out /tmp/memq.jsonl
    python3 scripts/atlas_memory_quality_bench.py --table /tmp/memq.jsonl

Never point it at a live server with devices: Atlas does not stay inside the page context and
acts on any host it can list (a drone and a labox host, 2026-10-25). Run it against a backend
with no hosts; the ``live`` prompts then fail to reach a device, which is enough to check that
the memory never answers them. ``--cleanup`` deletes the SC_BENCH_* scripts and bench_*
userinterfaces the run created, and nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import threading
import time
from pathlib import Path

import requests

SERVER = os.environ.get("SERVER_URL", "https://virtualpytest.angelstreet.io")
TEAM = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
JWT = os.environ.get("ATLAS_BENCH_JWT", "")

PROMPTS = [
    {"id": "script", "kind": "script",
     "text": "create a virtual script named SC_BENCH_{tag}_Hello that only logs hello world",
     "name": "SC_BENCH_{tag}_Hello"},
    {"id": "ui", "kind": "ui",
     "text": "create a user interface named bench_{tag}_ui for an android_tv device",
     "name": "bench_{tag}_ui"},
    {"id": "create a script", "kind": "vague", "text": "create a script"},
    {"id": "cap 5", "kind": "vague", "text": "cap 5"},
    {"id": "press home", "kind": "live", "text": "press home on {device_name}"},
    {"id": "send cmd to stb", "kind": "live", "text": "send cmd to stb"},
]
ARMS = ("off", "recall")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --------------------------------------------------------------------------- the server

def _h() -> dict:
    return {"Authorization": f"Bearer {JWT}"}


def api(method: str, path: str, **kw):
    params = {"team_id": TEAM, **(kw.pop("params", None) or {})}
    r = requests.request(method, f"{SERVER}{path}", params=params, headers=_h(), timeout=30, **kw)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def set_arm(arm: str) -> dict:
    """The user's own switch: off, or on in recall / context mode. Every arm starts empty."""
    api("DELETE", "/server/agent/memory")
    body = {"enabled": arm != "off"}
    _, data = api("PUT", "/server/agent/memory", json=body)
    return data


def memory_entries() -> int:
    _, data = api("GET", "/server/agent/memory")
    return int(data.get("entries") or 0)


def script_by_name(name: str) -> dict | None:
    _, data = api("GET", "/server/virtual-script/list")
    return next((s for s in data.get("scripts") or [] if s.get("name") == name), None)


def ui_by_name(name: str) -> dict | None:
    code, data = api("GET", f"/server/userinterface/getUserInterfaceByName/{name}")
    return data if code == 200 and data.get("id") else None


def ids_exist(answer: str, kind: str) -> tuple[int, int]:
    """(ids named in the answer, ids that resolve to a live artefact of that kind)."""
    ids = sorted(set(UUID_RE.findall(answer or "")))
    live = 0
    for value in ids:
        path = (f"/server/virtual-script/{value}" if kind == "script"
                else f"/server/userinterface/getUserInterface/{value}")
        code, data = api("GET", path)
        if code == 200 and (data.get("success", True) and (data.get("id") or data.get("script") or data.get("name"))):
            live += 1
    return len(ids), live


def calls_for(session_id: str, wait_s: float = 20.0) -> list[dict]:
    deadline = time.time() + wait_s
    while True:
        _, data = api("GET", "/server/ai/usage/calls",
                      params={"source": "calls", "hours": 1, "scope": "mine", "request_id": session_id, "limit": 50})
        rows = data.get("calls") or []
        if rows or time.time() > deadline:
            return rows
        time.sleep(1.0)


# --------------------------------------------------------------------------- one session

def run_session(messages: list[str], context: dict, timeout: int) -> tuple[str, list[dict]]:
    """Send the messages one after the other in ONE session; one observation per message."""
    import socketio
    _, created = api("POST", "/server/agent/sessions", json={})
    session_id = created["session"]["id"]
    obs: list[dict] = []
    state = {"cur": None}
    turn_done = threading.Event()
    sio = socketio.Client(reconnection=False)

    def _new(msg: str) -> dict:
        return {"message": msg, "answer": "", "called": [], "errored": False, "ended": False,
                "match_source": None, "tier_ms": None, "sent_at": time.time()}

    @sio.on("agent_event", namespace="/agent")
    def _e(ev):
        cur = state["cur"]
        if cur is None:
            return
        metrics = ev.get("metrics") or {}
        if metrics.get("match_source"):
            cur["match_source"] = metrics["match_source"]
            cur["tier_ms"] = metrics.get("duration_ms")
        kind = ev.get("type")
        if kind == "tool_call" and ev.get("tool_name"):
            cur["called"].append(ev["tool_name"])
        elif kind in ("message", "result"):
            content = ev.get("content")
            cur["answer"] += (content if isinstance(content, str) else json.dumps(content, default=str)) + "\n"
        elif kind == "error":
            cur["errored"] = True
            cur["answer"] += str(ev.get("content")) + "\n"
        elif kind == "session_ended":
            cur["ended"] = True
            turn_done.set()

    for attempt in range(3):  # an engine.io handshake glitch ("Invalid empty packet") is transient
        try:
            sio.connect(SERVER, namespaces=["/agent"], wait_timeout=20, auth={"token": JWT})
            break
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(3)
            sio = socketio.Client(reconnection=False)
            sio.on("agent_event", _e, namespace="/agent")
    sio.emit("join_session", {"session_id": session_id}, namespace="/agent")
    time.sleep(0.3)
    for msg in messages:
        cur = _new(msg)
        state["cur"] = cur
        turn_done.clear()
        sio.emit("send_message", {
            "session_id": session_id, "message": msg, "team_id": TEAM, "agent_id": "assistant",
            "allow_auto_navigation": False, "current_page": "/ai-agent",
            "host_name": "", "device_id": "", "userinterface_name": "", **context,
        }, namespace="/agent")
        if not turn_done.wait(timeout=timeout):
            cur["answer"] += f"[timeout {timeout}s]"
        cur["turn_s"] = round(time.time() - cur["sent_at"], 3)
        obs.append(cur)
        time.sleep(1.0)
    sio.disconnect()
    return session_id, obs


def _call_ts(call: dict) -> float:
    value = call.get("ts")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def calls_between(calls: list[dict], start: float, end: float | None) -> list[dict]:
    """The ai_calls rows of one message of a multi-message session, by their timestamp."""
    if end is None and len(calls) and all(_call_ts(c) == 0.0 for c in calls):
        return calls
    return [c for c in calls if _call_ts(c) >= start - 1 and (end is None or _call_ts(c) < end)]


def tier_of(o: dict, calls: list[dict]) -> str:
    if o.get("match_source") == "memory_recall":
        return "memory"
    if str(o.get("match_source") or "").startswith("faq"):
        return "faq"
    keys = [str(c.get("usage_key") or "") for c in calls]
    if not keys:
        return "no_model_call"
    return "quick_step" if all(k.endswith("agent.atlas.quick") for k in keys) else "model"


# --------------------------------------------------------------------------- the checks

def judge(prompt: dict, arm: str, ask: int, tier: str, answer: str, name: str | None,
          entries_before: int, entries_after: int) -> dict:
    """Is this answer right? One verdict per ask, with the evidence that decided it."""
    kind = prompt["kind"]
    out = {"verdict": "ok", "why": ""}

    def bad(why: str):
        out.update(verdict="bad", why=why)

    if kind in ("script", "ui"):
        found = script_by_name(name) if kind == "script" else ui_by_name(name)
        out["artefact_exists"] = bool(found)
        out["artefact_id"] = (found or {}).get("id")
        named = bool(name and name.lower() in (answer or "").lower())
        n_ids, live_ids = ids_exist(answer, kind)
        out.update(answer_names_it=named, ids_in_answer=n_ids, ids_live=live_ids)
        if not found:
            bad("artefact missing")
        elif ask == 2 and not named and not (out["artefact_id"] and out["artefact_id"] in (answer or "")):
            bad("second answer does not name the artefact")
        elif n_ids and not live_ids and out["artefact_id"] not in (answer or ""):
            # Other ids (a tree, a node) may sit next to it; wrong is naming ids and none of them
            # the artefact.
            bad("answer gives ids, none of them the artefact")
    elif kind == "vague":
        if arm != "off" and entries_after > entries_before:
            bad("a non-answer was remembered")
        if ask == 2 and tier == "memory":
            bad("a non-answer was recalled")
    elif kind == "live":
        if ask == 2 and tier == "memory":
            bad("a device command was answered from the memory")
    return out


# --------------------------------------------------------------------------- the run

def context_for(host: str, device: str) -> tuple[dict, str]:
    """Only the leased device goes in the page context.

    With ``--host ''`` the run uses no device at all: the right setting for a backend that has no
    hosts. Atlas does NOT stay inside the page context (2026-10-25: a "cap 5" turn listed the hosts
    and acted on a drone and a labox host), so a live server's devices are only safe when the
    whole server is yours.
    """
    if not host:
        return {}, "Phone slot 1"
    _, data = api("GET", "/server/system/getAllHosts")
    for h in data.get("hosts") or []:
        if h.get("host_name") != host:
            continue
        for d in h.get("devices") or []:
            if d.get("device_id") == device:
                dev = {"host_name": host, "device_id": device, "device_name": d.get("device_name"),
                       "device_model": d.get("device_model"),
                       "preferred_userinterface": d.get("preferred_userinterface")}
                return {"available_devices": [dev], "selected_server_hosts": [host]}, d.get("device_name") or device
    raise SystemExit(f"{host}/{device} is not online on {SERVER}")


def run(args) -> int:
    if not JWT:
        raise SystemExit("ATLAS_BENCH_JWT is not set (a test user's JWT: shared logins get no memory)")
    context, device_name = context_for(args.host, args.device)
    prompts = [p for p in PROMPTS if not args.only or p["id"] in args.only.split(",")]
    out = open(args.out, "a")
    try:
        for rnd in range(1, args.rounds + 1):
            for prompt in prompts:
                for arm in ARMS:
                    switch = set_arm(arm)
                    if arm != "off" and not switch.get("enabled"):
                        raise SystemExit(f"could not switch the memory on: {switch}")
                    tag = f"{arm[:3].upper()}{rnd}"
                    text = prompt["text"].format(tag=tag, device_name=device_name)
                    name = prompt.get("name", "").format(tag=tag) or None
                    # ask #1 in its own session; ask #2 (and "again" on the recall arm) in a new one,
                    # as a user coming back later would.
                    plan = [[text], [text, "again"] if arm == "recall" else [text]]
                    for ask, messages in enumerate(plan, start=1):
                        before = memory_entries()
                        sid, observations = run_session(messages, context, args.timeout)
                        calls = calls_for(sid)
                        after = memory_entries()
                        for step, o in enumerate(observations):
                            nxt = observations[step + 1]["sent_at"] if step + 1 < len(observations) else None
                            step_calls = [] if o.get("match_source") == "memory_recall" else \
                                calls_between(calls, o["sent_at"], nxt)
                            tier = tier_of(o, step_calls)
                            label = "again" if step == 1 else f"#{ask}"
                            verdict = judge(prompt, arm, ask, tier, o["answer"], name, before, after)
                            if label == "again" and tier == "memory":
                                verdict.update(verdict="bad", why="'again' was answered from the memory")
                            rec = {
                                "round": rnd, "prompt": prompt["id"], "kind": prompt["kind"], "arm": arm,
                                "ask": label, "session_id": sid, "tier": tier, "turn_s": o.get("turn_s"),
                                "tier_ms": o.get("tier_ms"),
                                "tokens_in": sum(int(c.get("tokens_in") or 0) for c in step_calls),
                                "tokens_out": sum(int(c.get("tokens_out") or 0) for c in step_calls),
                                "cache_read": sum(int(c.get("tokens_cache_read") or 0) for c in step_calls),
                                "calls": len(step_calls), "called": o["called"], "errored": o["errored"],
                                "memory_entries": after, **verdict,
                                "answer": (o["answer"] or "")[:300], "ts": time.time(),
                            }
                            out.write(json.dumps(rec) + "\n")
                            out.flush()
                            print(f"[memq] r{rnd} {arm:>7} {prompt['id']:<16} {label:<5} tier={tier:<13} "
                                  f"turn={rec['turn_s']}s calls={len(step_calls)} {rec['verdict']} {rec['why']}",
                                  file=sys.stderr)
                        time.sleep(args.pause)
    finally:
        out.close()
        set_arm("off")
    table([args.out])
    return 0


def cleanup() -> int:
    """Delete what the run created: SC_BENCH_* scripts and bench_*_ui userinterfaces. Nothing else."""
    removed = 0
    _, data = api("GET", "/server/virtual-script/list")
    for s in data.get("scripts") or []:
        if re.fullmatch(r"SC_BENCH_[A-Z]{3}\d+_Hello", s.get("name") or ""):
            code, _ = api("DELETE", f"/server/virtual-script/{s['id']}")
            removed += code == 200
    _, data = api("GET", "/server/userinterface/getAllUserInterfaces")
    items = data if isinstance(data, list) else data.get("userinterfaces") or data.get("interfaces") or []
    for ui in items:
        if re.fullmatch(r"bench_[a-z]{3}\d+_ui", (ui.get("name") or "").lower()):
            code, _ = api("DELETE", f"/server/userinterface/deleteUserInterface/{ui['id']}")
            removed += code == 200
    print(f"[memq] cleanup: {removed} artefacts deleted", file=sys.stderr)
    return 0


def table(paths: list[str]) -> None:
    rows = [json.loads(line) for p in paths for line in Path(p).read_text().splitlines() if line.strip()]
    print("\n| Arm | Prompt | Ask | Rounds | Right | Tiers | Turn median | Tokens median |")
    print("|---|---|---|---|---|---|---|---|")
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["arm"], r["prompt"], r["ask"]), []).append(r)
    order = {a: i for i, a in enumerate(ARMS)}
    for (arm, prompt, ask), rs in sorted(groups.items(), key=lambda k: (k[0][1], order.get(k[0][0], 9), k[0][2])):
        right = sum(r["verdict"] == "ok" for r in rs)
        tiers = ", ".join(sorted({r["tier"] for r in rs}))
        turns = [float(r["turn_s"] or 0) for r in rs]
        toks = [int(r["tokens_in"] or 0) + int(r["tokens_out"] or 0) for r in rs if r.get("tokens_in") is not None]
        print(f"| {arm} | {prompt} | {ask} | {len(rs)} | {right}/{len(rs)} | {tiers} | "
              f"{statistics.median(turns):.2f} s | {int(statistics.median(toks)) if toks else '-'} |")
    bad = [r for r in rows if r["verdict"] != "ok"]
    print(f"\nAsks: {len(rows)} · right: {len(rows) - len(bad)} · wrong: {len(bad)}")
    for r in bad:
        print(f"- r{r['round']} {r['arm']} {r['prompt']} {r['ask']}: {r['why']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--host", default="", help="device host to put in the page context ('' = none)")
    ap.add_argument("--device", default="device2")
    ap.add_argument("--only", default="", help="comma-separated prompt ids")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--pause", type=float, default=2.0)
    ap.add_argument("--out", default="atlas_memory_quality.jsonl")
    ap.add_argument("--table", nargs="+")
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()
    if args.table:
        table(args.table)
        return 0
    if args.cleanup:
        return cleanup()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
