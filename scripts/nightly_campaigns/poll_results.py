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

# A campaign that never ran — the deployment was skipped because the device was busy,
# locked or its queue was full — is terminal but it is not a failure. The report has to
# say "did not run" (and why), it must never show a ✗ for it, and it must stop waiting
# for it (BUG-0898).
#
# The skip is a FLAG, not a status word: the status column keeps its own meaning, so
# a skipped night is not looked up in TERMINAL_STATUSES but through is_skipped().
TERMINAL_STATUSES = {"completed", "failed", "aborted"}
SKIPPED_FLAG = "skip"


def is_skipped(campaign: dict) -> bool:
    """True when the campaign never ran.

    The skip is carried by a flag: `campaign_executions.skipped`, or the metadata flag
    on a database that has not run the migration that adds the column. The status
    column keeps its own meaning and is never consulted for the skip (BUG-0898).
    """
    flag = campaign.get("skipped")
    if isinstance(flag, str):
        if flag.strip().lower() in {"true", "1", "yes"}:
            return True
    elif flag is True or flag == 1:
        return True
    metadata = campaign.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return False
    if not isinstance(metadata, dict):
        return False
    return metadata.get("skipped") is True


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


def count_states(latest: dict[str, dict]) -> dict[str, int]:
    """Count the watched campaigns per state.

    `done` is every terminal state. A skipped campaign is terminal: the night is over
    and it will not be retried today, so the report must not keep waiting for it. It is
    not counted as a failure — it is not in the failed total anywhere.
    """
    done = sum(
        1 for v in latest.values()
        if v.get("status") in TERMINAL_STATUSES or is_skipped(v)
    )
    running = sum(1 for v in latest.values() if v.get("status") == "running")
    queued = sum(1 for v in latest.values() if v.get("status") in {"queued", "pending"})
    return {"done": done, "running": running, "queued": queued}


def status_flag(campaign: dict) -> str:
    """The flag shown for one campaign.

    A campaign that never ran reads as `skip` — not as a failure (✗) and not as a
    truncated status word. A campaign that ran keeps its old reading: ✓ when it
    succeeded, ✗ when it failed.
    """
    if is_skipped(campaign):
        return SKIPPED_FLAG
    status = campaign.get("status", "?")
    if status == "completed":
        return "✓" if campaign.get("success") else "✗"
    return status[:8]


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
        states = count_states(latest)
        done = states["done"]
        running = states["running"]
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
            flag = status_flag(v)
            reason = v.get("error_message") or ""
            extra = f" reason={reason}" if is_skipped(v) and reason else ""
            print(f"  [{flag:8s}] {cn:35s} dur={str(dur):>5}s pass={passed} fail={failed} skip={skipped}{extra}")
        (out_dir / "poll_state.json").write_text(json.dumps({cn: latest.get(cn, {}) for cn in watched}, indent=2))
        if done + running >= len(watched):
            print("All watched campaigns terminal.")
            return
        time.sleep(args.interval)
    print("Deadline reached.")


if __name__ == "__main__":
    main()
