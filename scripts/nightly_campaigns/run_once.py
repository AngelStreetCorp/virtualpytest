#!/usr/bin/env python3
"""run_once.py — Manually trigger every nightly deployment once.

Useful as a smoke test and as a "kick the lock" helper when the per-host
device lock frees up. Sleeps `wait_seconds` after each call to give the lock
time to release.

Usage:
    python3 scripts/nightly_campaigns/run_once.py \\
        --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \\
        --auto-signed $AUTO_SIGN_TOKEN \\
        --wait-seconds 60
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

HOST_BASE = {
    "host-clone-1": "https://virtualpytest.angelstreet.io",
    "vpt-pi1": "https://vpt-pi1.angelstreet.io",
    "vpt-pi3": "https://vpt-pi1.angelstreet.io",
    "vpt-pi4": "https://vpt-pi4.angelstreet.io",
}


def http_post(base: str, path: str, params: dict, token: str) -> tuple[int, dict]:
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Auto-Sign": token,
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "TASK63-run-once/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--team-id", required=True)
    p.add_argument("--auto-signed", required=True)
    p.add_argument("--wait-seconds", type=int, default=60,
                   help="Sleep this long after each run-now to let the device lock release.")
    p.add_argument("--include-names", nargs="*", default=None,
                   help="If set, only run these campaigns (default: all nightly_)")
    args = p.parse_args()

    # List deployments on Awesomation (shared Supabase list).
    s, resp = http_post(
        "https://virtualpytest.angelstreet.io",
        "/server/deployment/list",
        {"team_id": args.team_id},
        args.auto_signed,
    )
    if s != 200 or "deployments" not in resp:
        print(f"Failed to list deployments: {resp}")
        return
    deps = resp["deployments"]
    if args.include_names:
        deps = [d for d in deps if any(d.get("name", "").startswith(n) for n in args.include_names)]
    else:
        deps = [d for d in deps if d.get("name", "").startswith("nightly_")]
    print(f"Found {len(deps)} deployments to run.")

    for d in deps:
        host = d["host_name"]
        if host not in HOST_BASE:
            print(f"  [skip] {d['name']} host={host} no server mapping")
            continue
        base = HOST_BASE[host]
        s, resp = http_post(
            base,
            f"/server/deployment/run/{d['id']}",
            {"team_id": args.team_id},
            args.auto_signed,
        )
        ok = bool(resp.get("success"))
        print(f"  [{'✓' if ok else '✗'}] {d['name']:35s} host={host:12s} -> {s} {resp.get('error', '')[:120]}")
        if args.wait_seconds:
            time.sleep(args.wait_seconds)


if __name__ == "__main__":
    main()