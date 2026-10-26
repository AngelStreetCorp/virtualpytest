#!/usr/bin/env python3
"""TASK-172 — the memory benchmark: ask the same thing twice, with the memory off and on.

The owner's test, in their words: *"if I ask something today, tomorrow it should remember; so if I
ask the same thing, it should use its memory to answer … the second time should be way faster,
since it is retrieving info"*, with the prompts *create a script*, *create a user interface*,
*cap 5* and *send cmd to stb*.

What this measures
------------------
For every prompt and every arm, the harness records the **platform's own numbers**, not a
stopwatch impression:

- the wall clock from *send_message* to *session_ended* (the client side);
- the tokens and the per-call latency from ``ai_calls`` — the table the AI-usage page reads —
  fetched by ``request_id`` (= the session id), so the numbers are the ones the product bills and
  shows;
- **which tier answered**: the memory, the Prepared FAQ, the quick step, or the full model loop.
  This is the field that makes the result honest: a "faster" second run that was answered by a
  warm provider cache, or by a tier that was always going to be fast, is not a memory win.

The two arms
------------
Two servers run the same code, side by side, and differ by one environment variable:

    ATLAS_MEMORY=off   → the arm that behaves like today
    ATLAS_MEMORY=on    → the arm with the daily memory

The order of the four asks per prompt is fixed, and it matters:

    OFF #1   ON #1   OFF #2   ON #2

Both arms see their first ask next to each other and their second ask next to each other, so a
drift in the provider's latency lands on both arms instead of on one. The memory tree is wiped
before ``ON #1`` of each prompt, so ``ON #1`` is a true first ask and ``ON #2`` is a true recall.

How to run it
-------------
    # one arm
    python3 scripts/atlas_memory_bench.py --server http://127.0.0.1:5211 --arm off --label off \\
        --out /tmp/memory-bench.jsonl

    # the other arm (same host, same minute, only the env var differs)
    python3 scripts/atlas_memory_bench.py --server http://127.0.0.1:5212 --arm on --label on \\
        --out /tmp/memory-bench.jsonl

    # the table
    python3 scripts/atlas_memory_bench.py --table /tmp/memory-bench.jsonl

The harness must run on the **same host as the server under test**: it wipes the memory tree
between prompts, and the memory tree is a directory on the server's filesystem (``--memory-dir``).

Auth and server: the same environment variables as ``scripts/atlas_chat.py`` (``SERVER_URL``,
``AUTO_SIGN_TOKEN``, ``TEAM_ID``).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_chat as chat  # noqa: E402

# The owner's four prompts, verbatim. "cap 5" is the repo's per-device alert cap (the only cap of
# 5 in the product — docs/bugs/BUG-0299); the prompt is otherwise ambiguous, and the report says so.
PROMPTS = [
    "create a script",
    "create a user interface",
    "cap 5",
    "send cmd to stb",
]

TIER_MEMORY = "memory"
TIER_FAQ = "faq"
TIER_QUICK = "quick_step"
TIER_MODEL = "model"
TIER_NONE = "no_model_call"


def headers(args) -> dict:
    head = dict(chat._service_headers())
    if args.auto_sign:
        head["X-Auto-Sign"] = args.auto_sign
    return head


def ask(prompt: str, args, sio_mod, *, arm: str) -> dict:
    """One prompt in a fresh session. Returns the raw observation.

    The observation is deliberately dumb: it records what came over the socket and when. The
    interpretation (which tier answered) happens in :func:`classify`, on the recorded evidence.
    """
    server = args.server.rstrip("/")
    started = time.time()
    obs = {
        "prompt": prompt, "arm": arm, "label": args.label,
        "called": [], "events": [], "answer": "", "ended": False, "errored": False,
        "tokens": 0, "model": None, "match_source": None, "first_event_s": None,
    }
    try:
        session_id = chat.create_session(server, True, args.auto_sign)
    except Exception as exc:  # noqa: BLE001
        obs["answer"] = f"session failed: {chat._redact(exc)}"
        obs["errored"] = True
        obs["wall_s"] = round(time.time() - started, 3)
        return obs
    obs["session_id"] = session_id
    done = threading.Event()
    sio = sio_mod.Client(ssl_verify=True, reconnection=False)

    @sio.on("connect", namespace="/agent")
    def _c():
        sio.emit("join_session", {"session_id": session_id}, namespace="/agent")
        # The server binds the socket to the room when it handles join_session. The events are
        # ordered on the same socket, so a short pause is enough; the long pause of the earlier
        # harness was pure overhead that landed in every wall clock.
        time.sleep(args.join_pause)
        obs["sent_at"] = time.time()
        sio.emit("send_message", {
            "session_id": session_id, "message": prompt, "team_id": args.team_id,
            "agent_id": "assistant", "allow_auto_navigation": False, "current_page": "/ai-agent",
            "host_name": "", "device_id": "", "userinterface_name": "",
            "pinned_profile_id": args.pinned_profile or "", **args.context,
        }, namespace="/agent")

    @sio.on("agent_event", namespace="/agent")
    def _e(ev):
        obs["events"].append(ev.get("type"))
        if obs["first_event_s"] is None:
            obs["first_event_s"] = round(time.time() - started, 3)
        metrics = ev.get("metrics") or {}
        obs["tokens"] += int(metrics.get("input_tokens") or 0) + int(metrics.get("output_tokens") or 0)
        obs["model"] = metrics.get("model") or obs["model"]
        if metrics.get("match_source"):
            obs["match_source"] = metrics.get("match_source")
            # The tier's own wall clock (the memory lookup, the FAQ cache hit): it is what the
            # product spent answering, without the socket and the session overhead.
            obs["tier_ms"] = metrics.get("duration_ms")
        if ev.get("type") == "tool_call" and ev.get("tool_name"):
            obs["called"].append(ev["tool_name"])
        elif ev.get("type") == "message" or ev.get("type") == "result":
            content = ev.get("content")
            obs["answer"] += (content if isinstance(content, str) else json.dumps(content, default=str)) + "\n"
        elif ev.get("type") == "error":
            obs["errored"] = True
            obs["answer"] += str(ev.get("content")) + "\n"
        elif ev.get("type") == "session_ended":
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
    except Exception as exc:  # noqa: BLE001
        obs["errored"] = True
        obs["answer"] += f"socket: {chat._redact(exc)}"
    ended_at = time.time()
    obs["wall_s"] = round(ended_at - started, 3)
    # The turn itself: from the moment the message left the client to the moment the server
    # closed the turn. ``wall_s`` also carries the harness's own transport overhead (the session
    # call, the socket handshake, the join pause), which is the same for every arm — the turn is
    # the number that says what the product costs.
    sent_at = obs.get("sent_at")
    obs["turn_s"] = round(ended_at - sent_at, 3) if sent_at else None
    obs["overhead_s"] = round(sent_at - started, 3) if sent_at else None
    return obs


def calls_for(server: str, args, session_id: str) -> list[dict]:
    """The platform's own record of the model calls this session made.

    ``ai_calls`` keeps the session id as ``request_id``, so the AI-usage endpoint returns exactly
    the rows of this turn: tokens in/out, the per-call latency, the model and the usage key (which
    says *who* called: the main assistant, the quick step, …).

    The write is asynchronous (a daemon thread batches the rows), so this polls for a short while
    instead of reading once and finding nothing.
    """
    import requests
    deadline = time.time() + args.calls_wait
    rows: list[dict] = []
    while True:
        try:
            r = requests.get(f"{server}/server/ai/usage/calls",
                             params={"source": "calls", "team_id": args.team_id, "hours": 1,
                                     "scope": "mine", "request_id": session_id, "limit": 50},
                             headers=headers(args), timeout=25)
            rows = (r.json() or {}).get("calls") or []
        except Exception:  # noqa: BLE001
            rows = []
        if rows or time.time() > deadline:
            return rows
        time.sleep(1.0)


def classify(obs: dict, calls: list[dict]) -> str:
    """Which tier answered this turn — the field that keeps the result honest.

    The evidence, in order:
    - the event metrics carry ``match_source``: ``memory_recall`` is the daily memory, the
      ``faq_*`` sources are the Prepared FAQ;
    - otherwise the ``usage_key`` of the ``ai_calls`` rows says who called the model:
      ``agent.atlas.quick`` is the quick step, ``agent.atlas`` is the full model loop. The key
      can carry a caller prefix (``eval:agent.atlas.quick``), so the match is on the suffix;
    - no call at all means nothing called a model.
    """
    source = obs.get("match_source")
    if source == "memory_recall":
        return TIER_MEMORY
    if source and str(source).startswith("faq"):
        return TIER_FAQ
    keys = [str(c.get("usage_key") or "") for c in calls]
    if not keys:
        return TIER_NONE
    if all(k.endswith("agent.atlas.quick") for k in keys):
        return TIER_QUICK
    return TIER_MODEL


def classify_record(rec: dict) -> str:
    """Re-classify a stored row from its own evidence.

    The table is printed from the JSONL, so the tier has to be derivable from what was recorded —
    that way a result file stays readable even if the classifier improves later.
    """
    source = rec.get("match_source")
    if source == "memory_recall":
        return TIER_MEMORY
    if source and str(source).startswith("faq"):
        return TIER_FAQ
    keys = [str(k) for k in (rec.get("usage_keys") or [])]
    if not keys:
        return TIER_NONE
    if all(k.endswith("agent.atlas.quick") for k in keys):
        return TIER_QUICK
    return TIER_MODEL


def ui_context(server: str, args) -> dict:
    """What the Atlas page sends beside the message: the devices and the hosts.

    Without it Atlas cannot map a device name to host_name + device_id, which the real UI never
    lacks. Same as ``scripts/atlas_usecase_bench.py``.
    """
    import requests
    r = requests.get(f"{server}/server/system/getAllHosts", params={"team_id": args.team_id},
                     headers=headers(args), timeout=30)
    hosts = [h for h in r.json().get("hosts", []) if h.get("status", "online") == "online"]
    devices = [{"host_name": h["host_name"], "device_id": d.get("device_id"),
                "device_name": d.get("device_name"), "device_model": d.get("device_model"),
                "preferred_userinterface": d.get("preferred_userinterface")}
               for h in hosts for d in h.get("devices", []) if d.get("device_id") not in (None, "host")]
    return {"available_devices": devices, "selected_server_hosts": [h["host_name"] for h in hosts]}


def wipe_memory(memory_dir: str) -> bool:
    """Delete the memory tree so the next ask is a true first ask. Returns True when it ran."""
    if not memory_dir:
        return False
    root = Path(memory_dir)
    if not root.exists():
        return False
    try:
        shutil.rmtree(root)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[bench] memory wipe skipped: {exc}", file=sys.stderr)
        return False


def run(args) -> int:
    import socketio  # noqa: E402
    args.server = args.server or chat.DEFAULT_SERVER
    args.team_id = args.team_id or chat.DEFAULT_TEAM
    args.auto_sign = args.auto_sign or chat.AUTO_SIGN
    args.context = {} if args.no_context else ui_context(args.server.rstrip("/"), args)
    prompts = [p.strip() for p in (args.prompts.split(";") if args.prompts else PROMPTS) if p.strip()]
    out = open(args.out, "a")

    def one(prompt: str, server: str, arm: str, label: str, repeat: int) -> dict:
        saved = args.server
        args.server = server
        try:
            obs = ask(prompt, args, socketio, arm=arm)
            calls = calls_for(server.rstrip("/"), args, obs.get("session_id") or "")
        finally:
            args.server = saved
        tier = classify(obs, calls)
        tokens_in = sum(int(c.get("tokens_in") or 0) for c in calls)
        tokens_out = sum(int(c.get("tokens_out") or 0) for c in calls)
        latency_ms = sum(int(c.get("latency_ms") or 0) for c in calls)
        rec = {
            "prompt": prompt, "repeat": repeat, "arm": arm, "label": label,
            "server": server, "session_id": obs.get("session_id"), "tier": tier,
            "wall_s": obs.get("wall_s"), "first_event_s": obs.get("first_event_s"),
            "turn_s": obs.get("turn_s"), "overhead_s": obs.get("overhead_s"),
            "tier_ms": obs.get("tier_ms"),
            "event_tokens": obs.get("tokens"),
            "db_tokens_in": tokens_in, "db_tokens_out": tokens_out,
            "db_latency_ms": latency_ms,
            "db_calls": len(calls),
            "usage_keys": sorted({str(c.get("usage_key") or "") for c in calls}),
            "models": sorted({str(c.get("model") or "") for c in calls if c.get("model")}),
            "cache_read": sum(int(c.get("tokens_cache_read") or 0) for c in calls),
            "cache_write": sum(int(c.get("tokens_cache_write") or 0) for c in calls),
            "match_source": obs.get("match_source"),
            "called": obs.get("called"), "ended": obs.get("ended"), "errored": obs.get("errored"),
            "answer": (obs.get("answer") or "")[:400], "ts": time.time(),
        }
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(f"[bench] {label:>10} {prompt!r} tier={tier} wall={rec['wall_s']}s "
              f"tier_ms={rec['tier_ms']} tokens={tokens_in + tokens_out} "
              f"db_latency={latency_ms}ms calls={len(calls)}", file=sys.stderr)
        time.sleep(args.pause)
        return rec

    if args.server_off and args.server_on:
        # Pair mode: both arms run here, interleaved, so a drift in the provider's latency lands
        # on both arms instead of on one. The order per prompt is OFF #1, ON #1, OFF #2, ON #2:
        # both arms see their first ask next to each other and their second ask next to each
        # other. The memory tree is wiped before ON #1, so ON #1 is a true first ask.
        for prompt in prompts:
            one(prompt, args.server_off, "off", args.label_off or "off", 1)
            wiped = wipe_memory(args.memory_dir)
            print(f"[bench] {prompt!r}: memory tree wiped={wiped}", file=sys.stderr)
            one(prompt, args.server_on, "on", args.label_on or "on", 1)
            one(prompt, args.server_off, "off", args.label_off or "off", 2)
            one(prompt, args.server_on, "on", args.label_on or "on", 2)
    else:
        for prompt in prompts:
            for repeat in (1, 2):
                if repeat == 1:
                    wiped = wipe_memory(args.memory_dir)
                    print(f"[bench] {prompt!r} ask {repeat}: memory tree wiped={wiped}", file=sys.stderr)
                one(prompt, args.server, args.arm, args.label or args.arm, repeat)
    out.close()
    table([args.out])
    return 0


def table(paths: list[str]) -> None:
    rows: list[dict] = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))

    print("\n| Arm | Prompt | Ask | Tier | Wall clock | Turn (server-side) | ai_calls latency | Tokens in/out | Calls |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        r["tier"] = classify_record(r)
        total = int(r.get("db_tokens_in") or 0) + int(r.get("db_tokens_out") or 0)
        print(f"| {r.get('label')} | {r.get('prompt')} | #{r.get('repeat')} | {r.get('tier')} | "
              f"{r.get('wall_s')} s | {r.get('turn_s')} s | {r.get('db_latency_ms')} ms | "
              f"{r.get('db_tokens_in')}/{r.get('db_tokens_out')} | {r.get('db_calls')} |")

    print("\n### First ask vs second ask, per arm")
    print("| Arm | Prompt | 1st wall | 2nd wall | 1st turn | 2nd turn | 1st tokens | 2nd tokens | 2nd tier |")
    print("|---|---|---|---|---|---|---|---|---|")
    by_arm: dict[tuple[str, str], dict[int, dict]] = {}
    for r in rows:
        by_arm.setdefault((str(r.get("label")), str(r.get("prompt"))), {})[int(r.get("repeat") or 0)] = r
    for (label, prompt), pair in by_arm.items():
        first, second = pair.get(1, {}), pair.get(2, {})
        def _tok(r):
            return int(r.get("db_tokens_in") or 0) + int(r.get("db_tokens_out") or 0)
        print(f"| {label} | {prompt} | {first.get('wall_s')} s | {second.get('wall_s')} s | "
              f"{first.get('turn_s')} s | {second.get('turn_s')} s | {_tok(first)} | {_tok(second)} | "
              f"{second.get('tier')} |")

    # The headline: the second ask, per arm, against the first ask of the same arm.
    print("\n### Second-ask effect (same arm, same prompt)")
    print("| Arm | Prompt | Turn 1st | Turn 2nd | Δ turn | Tokens 1st | Tokens 2nd | Δ tokens | 2nd tier |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, prompt), pair in sorted(by_arm.items()):
        first, second = pair.get(1, {}), pair.get(2, {})
        if not first or not second:
            continue
        w1 = float(first.get("turn_s") or first.get("wall_s") or 0)
        w2 = float(second.get("turn_s") or second.get("wall_s") or 0)
        t1 = int(first.get("db_tokens_in") or 0) + int(first.get("db_tokens_out") or 0)
        t2 = int(second.get("db_tokens_in") or 0) + int(second.get("db_tokens_out") or 0)
        print(f"| {label} | {prompt} | {w1:.2f} s | {w2:.2f} s | {w2 - w1:+.2f} s | {t1} | {t2} | {t2 - t1:+d} | "
              f"{second.get('tier')} |")

    wall = [float(r.get("wall_s") or 0) for r in rows]
    if wall:
        print(f"\nRuns: {len(rows)} · wall median {statistics.median(wall):.2f} s "
              f"· min {min(wall):.2f} s · max {max(wall):.2f} s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", help="the backend under test (default SERVER_URL)")
    ap.add_argument("--server-off", dest="server_off",
                    help="the arm with the memory OFF (pair mode: both arms, interleaved)")
    ap.add_argument("--server-on", dest="server_on",
                    help="the arm with the memory ON (pair mode: both arms, interleaved)")
    ap.add_argument("--label-off", dest="label_off", default="", help="label of the OFF arm")
    ap.add_argument("--label-on", dest="label_on", default="", help="label of the ON arm")
    ap.add_argument("--team-id", dest="team_id")
    ap.add_argument("--auto-sign", dest="auto_sign")
    ap.add_argument("--arm", default="default", help="a label for the arm: off / on / context")
    ap.add_argument("--label", default="", help="the label used in the table (defaults to the arm)")
    ap.add_argument("--prompts", help="semicolon-separated prompts (defaults to the owner's four)")
    ap.add_argument("--pinned-profile", dest="pinned_profile", default="",
                    help="profile id to pin the run to (one model, no fallback)")
    ap.add_argument("--memory-dir", dest="memory_dir", default=os.environ.get("ATLAS_MEMORY_DIR", ""),
                    help="the memory tree on the server's filesystem; wiped between the two asks")
    ap.add_argument("--timeout", type=int, default=420, help="per ask, seconds")
    ap.add_argument("--calls-wait", dest="calls_wait", type=float, default=20.0,
                    help="how long to wait for the ai_calls rows of a turn to be written")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between asks")
    ap.add_argument("--join-pause", dest="join_pause", type=float, default=0.25,
                    help="seconds between joining the socket session and sending the message")
    ap.add_argument("--no-context", action="store_true", dest="no_context",
                    help="do not send the device list the Atlas page sends")
    ap.add_argument("--out", default="atlas_memory_bench.jsonl")
    ap.add_argument("--table", nargs="+", help="print the table of JSONL result files and exit")
    args = ap.parse_args()
    if args.table:
        table(args.table)
        return 0
    if not args.label:
        args.label = args.arm
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
