#!/usr/bin/env python3
"""Drift benchmark — THE REAL TEST. v4 vs v5 on LOCAL exploration captures, which are DIFFERENT frames
than the screenshots the fingerprints were built from. Unlike self-match (zero drift), these frames
differ in time / content / focus — so this is the test that actually reveals whether v5 is more robust.

For each capture whose label EXISTS in the current UI's node set, run v4 + v5 against the current node
fingerprints; correct = top label == the capture's label.

  python3 bench_drift.py example_tv <run_dir> [run_dir ...]

Each run_dir has state.json (nodes with `label` + `screenshot` abspath) + a captures/ subdir; the
capture for a node is captures/<basename(screenshot)>. Local exploration runs live in
features/avq/backend_host/localize/live_runs/ on the DEV machine — to run on a host, rsync the chosen run dirs there
first (see README.md).
"""
import contextlib
import io
import json
import os
import sys

import cv2

import _bench_common as B


def main():
    if len(sys.argv) < 3:
        print("usage: bench_drift.py <ui> <run_dir> [run_dir ...]")
        sys.exit(1)
    uiname = sys.argv[1]
    runs = sys.argv[2:]
    H, _sb, _cf, nodes = B.load_nodes(uiname)
    ncrop = B.inject_node_crops(H, _cf, nodes)          # v6: focused-crop dHash per node (audit-only)
    cands = [{"node_id": x["node_id"], "label": x["label"], "fingerprint": x["fingerprint"]} for x in nodes]
    curlabels = {x["label"] for x in nodes}

    rows = []
    v4ok = v5ok = v6ok = 0
    for run in runs:
        sj = os.path.join(run, "state.json")
        if not os.path.exists(sj):
            continue
        s = json.load(open(sj))
        ns = s.get("nodes", {})
        ns = list(ns.values()) if isinstance(ns, dict) else ns
        for n in ns:
            lbl, shot = n.get("label"), n.get("screenshot")
            if not (lbl in curlabels and shot):
                continue
            cap = os.path.join(run, "captures", os.path.basename(shot))
            if not os.path.exists(cap):
                continue
            img = cv2.imread(cap)
            if img is None:
                continue
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            with contextlib.redirect_stdout(io.StringIO()):
                regions = H._region_dhashes(g)
                focus = H._focus_signature(img)
                live_crop = B.focus_crop_hex(H, img)            # v6: live focused-tile crop dHash
                r4 = H.match_fingerprint(g, focus, cands)
                r5 = H.match_fingerprint_v5(g, regions, focus, cands)
                r6 = H.match_fingerprint_v6(g, regions, focus, live_crop, cands)
            # mirror localize(): matcher top, else special-state (black/no-signal) fallback
            t4, s4 = B.resolve_top(H, r4, img)
            t5, s5 = B.resolve_top(H, r5, img)
            t6, s6 = B.resolve_top(H, r6, img)
            # correct = right screen (parent≡child credited) OR a correctly-named special state
            ok4 = B.same_screen(t4, lbl) or s4
            ok5 = B.same_screen(t5, lbl) or s5
            ok6 = B.same_screen(t6, lbl) or s6
            v4ok += ok4
            v5ok += ok5
            v6ok += ok6
            rows.append((os.path.basename(run), lbl, (t4, ok4), (t5, ok5), (t6, ok6)))

    tot = len(rows)
    print(f"### Drift — {uiname} ({tot} local-capture frames, DIFFERENT from the stored fingerprints)\n")
    print(f"_Real drift: each capture is a different frame than the one its fingerprint was built from. "
          f"v6 = v5 + focused-crop tie-break ({ncrop} nodes carry a crop)._\n")
    print("| Run | Expected | v4 → top | v5 → top | v6 → top |")
    print("|---|---|---|---|---|")
    for run, lbl, (t4, ok4), (t5, ok5), (t6, ok6) in rows:
        print(f"| {run} | `{lbl}` | {t4} {'✅' if ok4 else '❌'} | "
              f"{t5} {'✅' if ok5 else '❌'} | {t6} {'✅' if ok6 else '❌'} |")
    if tot:
        print(f"\n**Drift correct (REAL test): v4 {v4ok}/{tot} ({100 * v4ok // tot}%) · "
              f"v5 {v5ok}/{tot} ({100 * v5ok // tot}%) · "
              f"v6 {v6ok}/{tot} ({100 * v6ok // tot}%)**")
        # The decision question: is v6 BETTER with NO regression vs v4/v5?
        def delta(base_idx):
            gains, regr = [], []
            for run, lbl, *vs in rows:          # vs = [(t4,ok4),(t5,ok5),(t6,ok6)]
                ob, t6, o6 = vs[base_idx][1], vs[2][0], vs[2][1]
                if o6 and not ob:
                    gains.append((run, lbl, vs[base_idx][0]))
                elif ob and not o6:
                    regr.append((run, lbl, vs[base_idx][0], t6))
            return gains, regr
        for name, idx in (("v4", 0), ("v5", 1)):
            g, r = delta(idx)
            print(f"\n**v6 vs {name}: +{len(g)} gained, {len(r)} regressed.**"
                  f"{'  ✅ NO REGRESSION' if not r else '  ⚠️ REGRESSIONS:'}")
            for run, lbl, was in g:
                print(f"  + {run} `{lbl}`: {name} wrong → v6 correct")
            for run, lbl, was, now in r:
                print(f"  - {run} `{lbl}`: {name} correct ({was}) → v6 {now}")
    else:
        print("\n**No drift-testable captures found** (no capture label matched the current node set).")


if __name__ == "__main__":
    main()
