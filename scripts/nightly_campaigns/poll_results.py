#!/usr/bin/env python3
"""poll_results.py — Watch nightly campaign executions to completion.

Polls /server/campaign-results/getAllCampaignResults every `interval`
seconds, prints a status table for every campaign matching the nightly_
prefix, and writes the latest snapshot to <out-dir>/poll_state.json.

The script exits once every watched campaign is in a terminal state, or
once `deadline_seconds` has elapsed.

Usage:
    python3 scripts/nightly_campaigns/poll_results.py \\
        --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \\
        --auto-signed $AUTO_SIGN_TOKEN \\
        --interval 600 \\
        --deadline 3600 \\
        --out-dir /tmp/t63
"""
from __future__ import annotations

import argparse
import datetime
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


def http_get(base: str, path: str, params: dict, token: str) -> tuple[int, object]:
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "X-Auto-Sign": token,
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "TASK63-poll/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}


def summarise(results: list[dict], watched: set[str]) -> dict[str, dict]:
    """Return the latest execution per watched campaign."""
    latest: dict[str, dict] = {}
    for r in results:
        cn = r.get("campaign_name", "")
        if cn not in watched:
            continue
        prev = latest.get(cn)
        if prev is None or (r.get("started_at") or "") > (prev.get("started_at") or ""):
            latest[cn] = r
    return latest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--team-id", required=True)
    p.add_argument("--auto-signed", required=True)
    p.add_argument("--interval", type=int, default=600)
    p.add_argument("--deadline", type=int, default=3600)
    p.add_argument("--out-dir", default="/tmp/t63")
    p.add_argument("--prefix", default="nightly_")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # First page — figure out the set of nightly campaigns.
    s, resp = http_get(
        "https://virtualpytest.angelstreet.io",
        "/server/campaign-results/getAllCampaignResults",
        {"team_id": args.team_id, "limit": 500},
        args.auto_signed,
    )
    if s != 200 or not isinstance(resp, list):
        print(f"First fetch failed: {resp}")
        return
    watched = {r.get("campaign_name", "") for r in resp if r.get("campaign_name", "").startswith(args.prefix)}
    print(f"Watching {len(watched)} campaigns matching prefix '{args.prefix}'.")

    deadline = time.time() + args.deadline
    while time.time() < deadline:
        s, resp = http_get(
            "https://virtualpytest.angelstreet.io",
            "/server/campaign-results/getAllCampaignResults",
            {"team_id": args.team_id, "limit": 500},
            args.auto_signed,
        )
        if s != 200 or not isinstance(resp, list):
            print(f"Poll failed: {resp}")
            time.sleep(args.interval)
            continue
        latest = summarise(resp, watched)
        now = datetime.datetime.now().strftime("%H:%M:%S")
        done = sum(1 for v in latest.values() if v.get("status") in {"completed", "failed", "aborted"})
        running = sum(1 for v in latest.values() if v.get("status") == "running")
        queued = sum(1 for v in latest.values() if v.get("status") in {"queued", "pending"})
        print(f"\n[{now}] watched={len(watched)} done={done} running={running} queued_or_unknown={len(watched)-done-running}")
        for cn in sorted(watched):
            v = latest.get(cn)
            if v is None:
                print(f"  [?] {cn:35s} (no execution yet)")
                continue
            status = v.get("status", "?")
            ms = v.get("execution_time_ms")
            dur = (ms // 1000) if ms else None
            sr = v.get("script_results", [])
            passed = sum(1 for x in sr if x.get("success"))
            failed = sum(1 for x in sr if not x.get("success") and not x.get("skipped"))
            skipped = sum(1 for x in sr if x.get("skipped"))
            flag = "✓" if status == "completed" and v.get("success") else ("✗" if status == "completed" else status[:8])
            print(f"  [{flag:8s}] {cn:35s} dur={str(dur):>5}s pass={passed} fail={failed} skip={skipped}")
        (out_dir / "poll_state.json").write_text(json.dumps({cn: latest.get(cn, {}) for cn in watched}, indent=2))
        if done + running >= len(watched):
            print("All watched campaigns terminal.")
            return
        time.sleep(args.interval)
    print("Deadline reached.")


if __name__ == "__main__":
    main()