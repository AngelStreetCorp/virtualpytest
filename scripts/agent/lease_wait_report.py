#!/usr/bin/env python3
"""How long do agents wait for leases and deploys? (TASK-129 item B)

Reads, over the `proxmox` ssh alias unless files are given:
  - the central lease service events (`vpt-lease events --json`): ticket waiting -> granted/ended, per resource
  - the deploy queue (`~/agent-leases/deploys.jsonl`): request -> start

Prints median / p90 / max wait and the count over 5 minutes, per kind and for the last N days.
A claim refused at once (exit 3, no ticket) is not an event in the service, so it is not counted here.

  python3 scripts/agent/lease_wait_report.py [--days 7]
  python3 scripts/agent/lease_wait_report.py --events-file ev.json --deploys-file deploys.jsonl
"""
import argparse, json, subprocess, sys, time
from collections import defaultdict


def fetch(cmd):
    return subprocess.run(["ssh", "-o", "ConnectTimeout=10", "proxmox", cmd], capture_output=True, text=True, check=True).stdout


def stats(name, waits):
    if not waits:
        print(f"{name:34s} n=0")
        return
    w = sorted(waits)
    p90 = w[min(len(w) - 1, int(len(w) * 0.9))]
    print(f"{name:34s} n={len(w):4d} median={w[len(w)//2]/60:6.1f}m p90={p90/60:6.1f}m max={w[-1]/60:6.1f}m over5m={sum(1 for x in w if x > 300)}")


def ticket_waits(events):
    start, out = {}, defaultdict(list)
    for e in events:
        if e.get("event") != "ticket":
            continue
        tid, st, ts = e.get("ticket"), e.get("state"), e.get("ts")
        if tid is None or ts is None:
            continue
        if st == "waiting":
            start[tid] = (ts, ",".join(e.get("resources") or []), e.get("agent", ""))
        elif tid in start and st in ("granted", "missed", "expired", "cancelled"):
            t0, res, _ = start.pop(tid)
            out[res.split("/")[0] or "?"].append(ts - t0)
    return out


def deploy_waits(lines, cut=0):
    rq, waits = {}, defaultdict(list)
    for l in lines:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if d.get("event") == "request" and d.get("ts", 0) >= cut:
            rq[d["id"]] = d
        elif d.get("event") == "start" and d.get("id") in rq:
            waits[rq[d["id"]].get("scope", "?")].append(d["ts"] - rq[d["id"]]["ts"])
    return waits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--events-file")
    ap.add_argument("--deploys-file")
    a = ap.parse_args()
    cut = time.time() - a.days * 86400
    ev_raw = open(a.events_file).read() if a.events_file else fetch("~/bin/vpt-lease events --json --limit 100000")
    events = [e for e in json.loads(ev_raw).get("events", []) if e.get("ts", 0) >= cut]
    dep_raw = open(a.deploys_file).read() if a.deploys_file else fetch("cat ~/agent-leases/deploys.jsonl")
    dep_lines = [l for l in dep_raw.splitlines() if l.strip()]
    print(f"== last {a.days:g} days ==")
    tw = ticket_waits(events)
    for k in sorted(tw):
        stats(f"claim wait: {k}", tw[k])
    if not tw:
        print("claim waits: no ticket events in the window")
    dw = deploy_waits(dep_lines, cut)
    for k in sorted(dw):
        stats(f"deploy queue wait: {k}", dw[k])


if __name__ == "__main__":
    sys.exit(main())
