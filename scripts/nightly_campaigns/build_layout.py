#!/usr/bin/env python3
"""build_layout.py — Build the TASK-63 nightly campaign layout.

Reads the live platform state (hosts on every server, virtual scripts, test
cases, disk scripts) and emits a JSON file describing one DB campaign per
(category × target device-class) combination, plus one deployment per non-
orphan campaign.

Team ID and AUTO_SIGN_TOKEN come from the runtime environment; the script
calls the same /server/* endpoints that the UI calls. It writes two JSON
files: <out-dir>/layout.json (campaign bodies + target hosts/devices) and
<out-dir>/exclusions.json (the items the platform knows about but cannot run
because no compatible device exists).

Usage:
    python3 scripts/nightly_campaigns/build_layout.py \\
        --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \\
        --auto-signed $AUTO_SIGN_TOKEN \\
        --out-dir /tmp/t63 \\
        --base-urls https://virtualpytest.angelstreet.io https://rpitest.angelstreet.io
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# Hosts we may target — anything else is off-limits (labox-* hosts; QualiAI's
# host-clone-1 duplicates Awesomation's; rtsp_video and cloud_android_mobile
# slots have no real device behind them).
ALLOWED_HOSTS = {"host-clone-1", "vpt-pi1", "vpt-pi3", "vpt-pi4"}
QUALIAI_TOKEN = "qualiai"

# Models a Chromium / Playwright-driven device script can run on.
INTERACTIVE_MODELS = {
    "host_vnc",
    "stb",
    "android_mobile",
    "android_tv",
    "fire_tv_vega",
    "fire_tv_fireos",
    "phone_agent",
    "cloud_android_mobile",
    "android_tablet",
    "nintendo_switch",
}


def http_get(base: str, path: str, params: dict, token: str) -> dict | list | None:
    url = f"{base}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "X-Auto-Sign": token,
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "TASK63-build-layout/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def collect_hosts(base: str, token: str, team_id: str) -> list[dict]:
    """One server per call. Drops QualiAI and per the owner rule.
    On host-clone-1 collisions we keep only the Awesomation copy because
    that is the server the scheduler picks up (cross-server firing would
    double-run the same deployment — see deployment_scheduler.py:507).
    """
    raw = http_get(base, "/server/system/getAllHosts", {"team_id": team_id}, token) or {"hosts": []}
    out = []
    for h in raw.get("hosts", []):
        name = h.get("host_name")
        if name not in ALLOWED_HOSTS:
            continue
        if QUALIAI_TOKEN in base and name == "host-clone-1":
            # Skip QualiAI's host-clone-1 — collides with Awesomation.
            continue
        for d in h.get("devices", []):
            out.append({
                "host": name,
                "server": base,
                "device_id": d.get("device_id"),
                "model": d.get("device_model"),
            })
    return out


def is_real_slot(d: dict) -> bool:
    return d.get("model") != "cloud_android_mobile"


def bucket_script(devices: list[dict], target_type: str | None, target_model: str | None) -> list[tuple[str, str]]:
    """Return the list of (host, device_id) a script fits."""
    if target_model in (None, "?", "all"):
        targets = sorted(INTERACTIVE_MODELS) if target_type == "device" else ["host_vnc"]
    else:
        targets = [t.strip() for t in target_model.split("|")]
    fits = []
    for d in devices:
        if not is_real_slot(d):
            continue
        if d["model"] in targets:
            fits.append((d["host"], d["device_id"]))
    return fits


def fetch_virtuals(base: str, token: str, team_id: str) -> list[dict]:
    out = []
    for v in (http_get(base, "/server/virtual-script/list", {"team_id": team_id}, token) or {}).get("scripts", []):
        v["_server"] = base
        out.append(v)
    return out


def fetch_testcases(base: str, token: str, team_id: str) -> list[dict]:
    return (http_get(base, "/server/testcase/list", {"team_id": team_id}, token) or {}).get("testcases", [])


def fetch_userinterfaces(base: str, token: str, team_id: str) -> dict[str, dict]:
    out = {}
    items = http_get(base, "/server/userinterface/getAllUserInterfaces", {"team_id": team_id}, token) or []
    if isinstance(items, list):
        for u in items:
            out[u["name"]] = u
    return out


def fetch_disk_scripts(root: Path) -> list[dict]:
    """Walk test_scripts/, return @script-decorated files with parsed _target_rules."""
    out = []
    for path, dirs, files in os.walk(root):
        if "/.vs" in path or "/local" in path:
            continue
        for f in files:
            if not f.endswith(".py") or f == "__init__.py":
                continue
            p = Path(path) / f
            src = p.read_text()
            if "@script" not in src:
                continue
            m = re.search(r"_target_rules\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\})", src, re.DOTALL)
            tt = tm = None
            if m:
                t = m.group(1)
                tt_m = re.search(r"""['"]target_type['"]\s*:\s*['"]([^'"]+)['"]""", t)
                dm_m = re.search(r"""['"]device_model['"]\s*:\s*['"]([^'"]+)['"]""", t)
                tt = tt_m.group(1) if tt_m else None
                tm = dm_m.group(1) if dm_m else None
            rel = str(p.relative_to(root)).removesuffix(".py")
            out.append({"rel": rel, "script_name": f"test_scripts/{rel}.py", "target_type": tt, "device_model": tm})
    return out


def default_target(rel: str) -> tuple[str, str]:
    """Infer the target rules for scripts that don't declare _target_rules."""
    if rel.startswith("api/"):
        return ("host", "host_vnc")
    if rel.startswith("vpt/smoke_"):
        return ("host", "host_vnc")
    if rel == "validation":
        return ("device", "host_vnc")
    return ("device", "all")


def filter_virtuals(items: list[dict]) -> list[dict]:
    """Drop labox_*, drone, CI fixtures."""
    out = []
    for v in items:
        if v.get("folder") == "labox" or v.get("name", "").startswith("labox_"):
            continue
        if v.get("folder") == "drone" or v.get("name", "").startswith("drone_"):
            continue
        if v.get("name", "").startswith("zz_ci_vscript"):
            continue
        out.append(v)
    return out


def build_layout(devices: list[dict], virtuals: list[dict], testcases: list[dict], uis: dict[str, dict], disk: list[dict]) -> dict:
    """Return the campaign-body map keyed by campaign_name."""
    layout = {}

    # 1. Testcases: bucket by host/device where the UI fits the device's model.
    # Empty-UI testcases are excluded per the owner Q3 decision — see the task doc.
    tc_by_target = defaultdict(list)
    tc_orphans_by_ui = defaultdict(list)
    for tc in testcases:
        ui_name = (tc.get("userinterface_name") or "").strip()
        if not ui_name:
            continue  # empty-UI testcases — not scheduled (owner Q3)
        ui = uis.get(ui_name)
        if not ui:
            continue
        ui_models = ui.get("models", [])
        matched_any = False
        for d in devices:
            if not is_real_slot(d):
                continue
            if "all" in ui_models or d["model"] in ui_models:
                tc_by_target[(d["host"], d["device_id"])].append((tc, ui_name))
                matched_any = True
        if not matched_any:
            tc_orphans_by_ui[ui_name].append(tc)

    # 2. Virtual scripts: bucket by host/device via their stored target_rules.
    vs_by_target = defaultdict(list)
    for v in filter_virtuals(virtuals):
        t = v.get("target_rules") or {}
        tt = t.get("target_type", "host")
        tm = t.get("device_model", "all")
        for h, dev in bucket_script(devices, tt, tm):
            vs_by_target[(h, dev)].append(v)

    # 3. Disk scripts: parse _target_rules from each test_scripts/*.py file.
    ds_by_target = defaultdict(list)
    for d in disk:
        tt, tm = d["target_type"], d["device_model"]
        if tt is None or tm is None:
            tt, tm = default_target(d["rel"])
        for h, dev in bucket_script(devices, tt, tm):
            ds_by_target[(h, dev)].append(d)

    return {
        "tc_buckets": {f"{k[0]}|{k[1]}": [(t["testcase_name"], t["testcase_id"], ui) for t, ui in v] for k, v in tc_by_target.items()},
        "vs_buckets": {f"{k[0]}|{k[1]}": [(s["id"], s["name"]) for s in v] for k, v in vs_by_target.items()},
        "ds_buckets": {f"{k[0]}|{k[1]}": [(s["script_name"], s.get("target_type"), s.get("device_model")) for s in v] for k, v in ds_by_target.items()},
        "tc_orphans_by_ui": dict(tc_orphans_by_ui),
        "devices": devices,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Build TASK-63 nightly campaign layout.")
    p.add_argument("--team-id", required=True)
    p.add_argument("--auto-signed", required=True, help="AUTO_SIGN_TOKEN shared service value")
    p.add_argument("--out-dir", default="/tmp/t63")
    p.add_argument("--base-urls", nargs="+", required=True, help="Backend server URLs (Awesomation, RPI, ...)")
    p.add_argument("--test-scripts-root", default="test_scripts")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Hosts on every server — de-duped.
    devices: list[dict] = []
    seen = set()
    for base in args.base_urls:
        for d in collect_hosts(base, args.auto_signed, args.team_id):
            key = (d["host"], d["device_id"], d["model"])
            if key in seen:
                continue
            seen.add(key)
            devices.append(d)

    virtuals: list[dict] = []
    for base in args.base_urls:
        virtuals.extend(fetch_virtuals(base, args.auto_signed, args.team_id))
    testcases = fetch_testcases(args.base_urls[0], args.auto_signed, args.team_id)
    uis = fetch_userinterfaces(args.base_urls[0], args.auto_signed, args.team_id)
    disk = fetch_disk_scripts(Path(args.test_scripts_root))

    layout = build_layout(devices, virtuals, testcases, uis, disk)
    (out_dir / "layout.json").write_text(json.dumps(layout, indent=2))
    print(f"Wrote {out_dir/'layout.json'}: {len(layout['tc_buckets'])} TC buckets, "
          f"{len(layout['vs_buckets'])} VS buckets, {len(layout['ds_buckets'])} DS buckets, "
          f"{sum(len(v) for v in layout['tc_orphans_by_ui'].values())} orphan TCs")


if __name__ == "__main__":
    main()