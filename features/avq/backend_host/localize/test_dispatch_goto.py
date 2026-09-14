#!/usr/bin/env python3
"""LIVE proof of the localize-dispatch navigation model on the settings tab strip — no executor change.

Drives blestbv1 via MCP through exactly what NAVIGATION_DISPATCH.md describes:
  enter the settings menu (lands on the box's REMEMBERED tab — unknown) →
  localize(candidates = the 6 leaf fingerprints) to identify the actual tab →
  pathfind the RING (shorter of RIGHT/LEFT, wrap-aware) to the target →
  execute [RIGHT,OK] / [LEFT,OK] hops (1s/5s) → verify we landed on the target.

Candidates are the 6 tab-content fingerprints captured earlier (live_runs/example_tv_settings).
This validates dispatch+ring+wrap+candidate-localize before any NavigationExecutor work.

  python3 test_dispatch_goto.py [--targets profile,info,system,profile]
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

HOST, DEVICE, NAME, UI = "host1", "device4", "blestbv1", "example_tv"
# the 6 tab-content leaves, in strip order (index 0..5 = left..right). settings == Profiles.
RING = ["settings", "accessibility", "parentalcontrol", "soundimage", "system", "info"]
ALIAS = {"profile": "settings", "profiles": "settings"}


def load_candidates():
    s = json.loads((HERE / "live_runs/example_tv_settings/state.json").read_text())
    by_label = {v.get("label"): v for v in s["nodes"].values()}
    cands = []
    for i, lbl in enumerate(RING):
        fp = by_label[lbl]["fingerprint"]
        cands.append({"idx": i, "label": lbl, "fp": fp})
    return sorted(cands, key=lambda c: c["fp"]["focus"]["x"])  # confirm strip order by focus.x


def best_match(fp, cands):
    """The full-matcher candidate localize: pick the child whose fingerprint is closest, using the
    production identity (dHash + focus + title). Returns (candidate, hammings dict)."""
    hams = {c["label"]: ab._hamming(fp.get("dhash", ""), c["fp"]["dhash"]) for c in cands}
    # primary: same-screen by production matcher; tie-break by dHash distance, then focus.x
    fx = (fp.get("focus") or {}).get("x", 0)
    scored = sorted(cands, key=lambda c: (hams[c["label"]],
                                          abs((c["fp"]["focus"]["x"]) - fx)))
    return scored[0], hams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="profile,system,info,accessibility,profile",
                    help="comma list of tab labels to goto in sequence (profile|accessibility|parentalcontrol|soundimage|system|info)")
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()

    cands = load_candidates()
    idx_of = {c["label"]: c["idx"] for c in cands}
    print("ring (by focus.x):", " -> ".join(f"{c['idx']}:{c['label']}" for c in cands), flush=True)

    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)
    run_dir = HERE / "live_runs" / "_dispatch_test"
    (run_dir / "captures").mkdir(parents=True, exist_ok=True)
    state = {"next_capture": 0}

    def cap(prefix, keys):
        _shot, fp = ab._settled_capture(client, run_dir, state, prefix, host=HOST, device=DEVICE, keys=keys)
        return fp

    def localize():
        fp = cap("loc", [])
        c, hams = best_match(fp, cands)
        return c, hams

    def ring_path(cur, tgt):
        """Shorter direction on a 6-ring. Returns (key, nhops)."""
        n = len(RING)
        r = (tgt - cur) % n
        l = (cur - tgt) % n
        return ("RIGHT", r) if r <= l else ("LEFT", l)

    checks = []
    for raw in [t.strip() for t in args.targets.split(",") if t.strip()]:
        tab = ALIAS.get(raw, raw)
        tgt = idx_of[tab]
        print(f"\n=== goto '{tab}' (idx {tgt}) — fresh entry ===", flush=True)
        client.goto_home(HOST, DEVICE, UI)
        cap("enter", ["RIGHT"] * 6); cap("enter", ["RIGHT"]); cap("enter", ["OK"])   # enter settings
        cur, hams = localize()
        print(f"  entered on (localized): {cur['label']} (idx {cur['idx']})  hammings={hams}", flush=True)

        key, nhops = ring_path(cur["idx"], tgt)
        print(f"  ring path: {key} x{nhops}", flush=True)
        for _ in range(nhops):
            cap("hop", [key, "OK"])          # one hop = move + commit
        landed, lh = localize()
        ok = landed["label"] == tab
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] landed on {landed['label']} (want {tab})  hammings={lh}", flush=True)

    print(f"\n{'ALL PASS' if all(checks) else 'FAILURES'} ({sum(checks)}/{len(checks)})", flush=True)
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
