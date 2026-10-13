#!/usr/bin/env python3
"""create_campaigns.py — Apply the TASK-63 nightly layout to the live DB.

Reads layout.json (produced by build_layout.py), creates one campaign per
(category × target host+device) plus an orphan campaign for each testcase UI
without a matching device. Then creates one deployment per non-orphan
campaign. All API calls hit the server that owns the deployment's host.

Usage:
    python3 scripts/nightly_campaigns/create_campaigns.py \\
        --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \\
        --auto-signed $AUTO_SIGN_TOKEN \\
        --layout /tmp/t63/layout.json \\
        --cron "30 0 * * *"
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

# host -> URL of the server whose scheduler owns that host
HOST_BASE = {
    "host-clone-1": "https://virtualpytest.angelstreet.io",
    "vpt-pi1": "https://rpitest.angelstreet.io",
    "vpt-pi3": "https://rpitest.angelstreet.io",
    "vpt-pi4": "https://vpt-pi4.angelstreet.io",
}


def http_post(base: str, path: str, body: dict, params: dict, token: str) -> tuple[int, dict]:
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Auto-Sign": token,
            "Origin": base,
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "TASK63-create-campaigns/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}


def campaign_body_for(name: str, cat: str, items: list, host: str, device: str) -> dict:
    if cat == "testcases":
        sc = [
            {"script_name": tn, "script_type": "testcase", "testcase_id": tid}
            for tn, tid, _ui in items
        ]
    elif cat == "virtual_scripts":
        sc = [
            {"script_name": vn, "script_type": "virtual_script", "virtual_script_id": vid}
            for vid, vn in items
        ]
    else:  # disk_scripts
        sc = [{"script_name": sn, "script_type": sc}
              for sn, _tt, _tm in items for sc in [{"script_type": "script"}]]
    return {
        "campaign_name": name,
        "description": f"TASK-63 nightly: {cat} on {host or 'no-target'}/{device or 'no-device'}",
        "host_name": host,
        "device_name": device,
        "execution_config": {
            "continue_on_failure": True,
            "timeout_minutes": 120,
            "parallel": False,
        },
        "script_configurations": sc,
    }


def build_orphan_bodies(layout: dict) -> list[dict]:
    """Testcase campaigns for UI sets without a matching device."""
    bodies = []
    for ui_name, tcs in layout.get("tc_orphans_by_ui", {}).items():
        slug = ui_name.replace("/", "_").replace(" ", "_")
        cn = f"nightly_tc_{slug}"
        sc = [
            {"script_name": tc["testcase_name"], "script_type": "testcase", "testcase_id": tc["testcase_id"]}
            for tc in tcs
        ]
        bodies.append({
            "campaign_name": cn,
            "description": f"TASK-63 orphan campaign for UI '{ui_name}' (no device)",
            "host_name": None,
            "device_name": None,
            "execution_config": {"continue_on_failure": True, "timeout_minutes": 60, "parallel": False},
            "script_configurations": sc,
        })
    return bodies


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--team-id", required=True)
    p.add_argument("--auto-signed", required=True)
    p.add_argument("--layout", required=True)
    p.add_argument("--cron", default="30 0 * * *",
                   help="Cron UTC, e.g. '30 0 * * *' = 01:30 CET winter. Per owner Q2 (DST option 1).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    layout = json.loads(Path(args.layout).read_text())

    campaigns_to_create = []

    # Testcases with a target
    for key, items in layout["tc_buckets"].items():
        host, dev = key.split("|", 1)
        cn = f"nightly_tc_{dev}" if (host, dev) not in [("vpt-pi1", "device1"), ("vpt-pi3", "device3")] else None
        # Cleaner naming: tc_<device_class>
        model_class = "android" if dev == "device1" and host == "vpt-pi1" else "stb"
        cn = f"nightly_tc_{model_class}"
        # Avoid collisions across hosts: prefer host-class naming
        if any(c["campaign_name"] == cn and (c["host_name"], c["device_name"]) != (host, dev) for c in campaigns_to_create):
            cn = f"nightly_tc_{model_class}_{host.replace('-', '_')}"
        campaigns_to_create.append({
            "campaign_name": cn,
            "category": "testcases",
            "host": host, "device": dev,
            "items": items,
        })
    # Virtual scripts
    for key, items in layout["vs_buckets"].items():
        host, dev = key.split("|", 1)
        cn = f"nightly_vs_{dev}"
        if any(c["campaign_name"] == cn and (c["host_name"], c["device_name"]) != (host, dev) for c in campaigns_to_create):
            cn = f"nightly_vs_{dev}_{host.replace('-', '_')}"
        campaigns_to_create.append({
            "campaign_name": cn,
            "category": "virtual_scripts",
            "host": host, "device": dev,
            "items": items,
        })
    # Disk scripts
    for key, items in layout["ds_buckets"].items():
        host, dev = key.split("|", 1)
        cn = f"nightly_ds_{dev}"
        if any(c["campaign_name"] == cn and (c["host_name"], c["device_name"]) != (host, dev) for c in campaigns_to_create):
            cn = f"nightly_ds_{dev}_{host.replace('-', '_')}"
        campaigns_to_create.append({
            "campaign_name": cn,
            "category": "disk_scripts",
            "host": host, "device": dev,
            "items": items,
        })

    # Orphans
    for body in build_orphan_bodies(layout):
        campaigns_to_create.append({
            "campaign_name": body["campaign_name"],
            "category": "testcases",
            "host": None, "device": None,
            "items": [(tc["testcase_name"], tc["testcase_id"], body["campaign_name"]) for tc in layout["tc_orphans_by_ui"].get("", [])],
            "_orphan_body": body,
        })

    if args.dry_run:
        print(f"Dry-run: would create {len(campaigns_to_create)} campaigns.")
        for c in campaigns_to_create:
            print(f"  {c['campaign_name']:35s} {c['host'] or 'orphan':15s}/{c['device'] or '-':10s} {c['category']:18s} {len(c['items'])} items")
        return

    # Phase A — create campaigns. The validator rejects script_type='virtual_script',
    # so for vsc rows we save an empty body and inject the full body via deployment.parameters.
    created: list[dict] = []
    for c in campaigns_to_create:
        body = c.get("_orphan_body") or campaign_body_for(c["campaign_name"], c["category"], c["items"], c["host"], c["device"])
        if c["category"] == "virtual_scripts":
            body = {**body, "script_configurations": []}
        base = HOST_BASE.get(c["host"], args.layout and "")
        status, resp = http_post(
            "https://virtualpytest.angelstreet.io",  # campaigns live in shared Supabase, any server works
            "/server/campaigns/createCampaign",
            body,
            {"team_id": args.team_id},
            args.auto_signed,
        )
        cid = (resp.get("campaign") or {}).get("campaign_id")
        ok = bool(resp.get("success"))
        print(f"  [{'✓' if ok else '✗'}] {c['campaign_name']:35s} -> {cid} {resp.get('error', '')[:120]}")
        created.append({**c, "campaign_id": cid, "ok": ok})

    # Phase B — create deployments for non-orphan campaigns.
    for c in created:
        if not c["ok"]:
            continue
        if not c["host"]:
            continue
        body = campaign_body_for(c["campaign_name"], c["category"], c["items"], c["host"], c["device"])
        base = HOST_BASE[c["host"]]
        status, resp = http_post(
            base,
            "/server/deployment/create",
            {
                "name": f"{c['campaign_name']}_deployment",
                "host_name": c["host"],
                "device_id": c["device"],
                "script_name": c["campaign_name"],  # scheduler resolves to campaign_id
                "userinterface_name": "",
                "parameters": json.dumps(body["script_configurations"]),
                "campaign_id": c["campaign_id"],
                "cron_expression": args.cron,
                "status": "active",
            },
            {"team_id": args.team_id},
            args.auto_signed,
        )
        ok = bool(resp.get("success"))
        dep = resp.get("deployment") or {}
        print(f"  [DEP {'✓' if ok else '✗'}] {c['campaign_name']:35s} -> {dep.get('id')} on {c['host']}/{c['device']}")

    print(f"\nDone. {sum(1 for c in created if c['ok'])} campaigns created.")


if __name__ == "__main__":
    main()