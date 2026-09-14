#!/usr/bin/env python3
"""Measure tab DISCRIMINATION for the new carousel dispatch menus (replay / filmeserien / tvshop).

The dispatch's localize half rests ENTIRELY on the nav underline for these menus: their tabs share
chrome AND share one screen title, so image_helpers.match_fingerprint takes the NAV path — dHash is
ignored, the underline x (+width) IS the identity (image_helpers._focus_agreement >= 0.99). This
harness walks each menu's strip live and, at every tab, replicates that exact agreement against the
grafted candidate fingerprints: does the live frame match EXACTLY the right child, uniquely, and with
what x-margin over FP_NAV_X_TOL (0.03)? Pure focus — needs no runtime executor / cache.

(settings + apps are already proven by test_dispatch_goto.py / test_dispatch_apps.py, 5/5.)

  python3 measure_dispatch_localize.py
"""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

HOST, DEVICE, NAME, UI = "host1", "device4", "blestbv1", "example_tv"
FP_NAV_X_TOL = 0.03                                  # image_helpers.FP_NAV_X_TOL

# (run-dir, entry-keys)  — all carousel menus: UP to the strip, search icon at the far left
MENUS = [
    ("replay_dispatch", ["RIGHT"] * 3 + ["OK"]),
    ("filmeserien_dispatch", ["RIGHT"] * 4 + ["OK"]),
    ("tvshop_dispatch", ["RIGHT"] * 6 + ["OK"]),
]


def focus_agreement(a, b):
    """Verbatim mirror of image_helpers._focus_agreement (the production localize discriminator)."""
    if not a or not b:
        return 0.5
    ka, kb = a.get("kind", "none"), b.get("kind", "none")
    if ka == "none" or kb == "none":
        return 0.5
    if ka != kb:
        return 0.3
    if ka == "nav":
        if abs(a.get("x", -1) - b.get("x", -2)) > FP_NAV_X_TOL:
            return 0.0
        wa, wb = a.get("width"), b.get("width")
        if wa is not None and wb is not None and abs(wa - wb) > 0.06:
            return 0.0
        return 1.0
    la, lb = a.get("label", ""), b.get("label", "")
    if la and lb:
        return 1.0 if la == lb else 0.0
    same = abs(a.get("x", -1) - b.get("x", -2)) <= 0.08 and abs(a.get("y", -1) - b.get("y", -2)) <= 0.08
    return 1.0 if same else 0.0


def fx(fp):
    return float((fp.get("focus") or {}).get("x") or 0)


def is_nav(fp):
    return ((fp.get("focus") or {}).get("kind")) == "nav"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()
    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)

    overall = []
    for run_dir_name, entry in MENUS:
        src = json.loads((HERE / "live_runs" / run_dir_name / "state.json").read_text())
        # children = the tab nodes (exclude the head, which shares the first tab's frame)
        nodes = list(src["nodes"].values())
        head = next(n for n in nodes if n.get("kind") == "root")
        kids = [n for n in nodes if n.get("kind") != "root"]
        kids.sort(key=lambda n: fx(n["fingerprint"]))
        cand_focus = [(n["label"], (n["fingerprint"].get("focus") or {})) for n in kids]
        xs = [f.get("x") for _l, f in cand_focus]
        gaps = [round(xs[i + 1] - xs[i], 3) for i in range(len(xs) - 1)]
        menu = run_dir_name.replace("_dispatch", "")
        print(f"\n=== {menu}: {len(kids)} tabs  x={[round(x,3) for x in xs]}  adj-gaps={gaps}  "
              f"(need >{FP_NAV_X_TOL}) ===", flush=True)

        OUT = HERE / "live_runs" / f"_measure_{menu}"
        (OUT / "captures").mkdir(parents=True, exist_ok=True)
        st = {"next_capture": 0}

        def cap(p, keys):
            return ab._settled_capture(client, OUT, st, p, host=HOST, device=DEVICE, keys=keys)

        def nav(keys):
            return cap("_n", keys)[1]

        # enter + reach the strip (UP) + go to the leftmost tab past the search icon
        client.goto_home(HOST, DEVICE, UI)
        for k in entry:
            nav([k])
        fp = nav([])
        for _ in range(4):                                   # UP onto the nav strip
            if is_nav(fp):
                break
            fp = nav(["UP"])
        prev = fx(fp)
        for _ in range(12):                                  # LEFT to the edge (wrap / off-strip)
            fp = nav(["LEFT"])
            if (not is_nav(fp)) or fx(fp) > prev + 0.02:
                fp = nav(["RIGHT"]); break
            prev = fx(fp)
        if fx(fp) < 0.12:                                    # skip the leading search icon
            fp = nav(["RIGHT"])

        # walk the tabs, localize each live frame against the candidates
        results = []
        for i in range(len(kids)):
            live = nav([]) if i == 0 else nav(["RIGHT"])
            lf = live.get("focus") or {}
            fas = [(lbl, round(focus_agreement(lf, cf), 2)) for lbl, cf in cand_focus]
            matched = [lbl for lbl, fa in fas if fa >= 0.99]
            expected = cand_focus[i][0]
            ok = matched == [expected]                       # unique AND correct
            results.append(ok)
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] tab {i} ({expected}): live x={round(lf.get('x',0),3)} kind={lf.get('kind')} "
                  f"-> matched={matched}", flush=True)
        acc = sum(results)
        min_gap = min(gaps) if gaps else None
        overall.append((menu, acc, len(results), min_gap))
        print(f"  {menu}: {acc}/{len(results)} uniquely+correctly localized; min adj-gap={min_gap} "
              f"(margin over tol={round((min_gap or 0)-FP_NAV_X_TOL,3)})", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    allok = True
    for menu, acc, n, gap in overall:
        allok &= (acc == n)
        print(f"  {menu:14} {acc}/{n}  min-gap={gap}", flush=True)
    print("ALL DISCRIMINATED" if allok else "SOME TABS AMBIGUOUS", flush=True)
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
