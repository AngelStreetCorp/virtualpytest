#!/usr/bin/env python3
"""Self-match benchmark — each node's OWN stored screenshot vs all node fingerprints.

⚠️ This is a COLLISIONS-ONLY test with ZERO drift: live == the exact stored capture. It shows
whether each node uniquely matches itself and whether v5 ranks like v4 — but it CANNOT show v5's
real advantage (robustness to content churn / language / a different focused tab), because there is
no drift. Use bench_drift.py for the real test.

  python3 bench_self_match.py example_tv      # or example_tv_autobuild
"""
import contextlib
import io
import sys

import cv2

import _bench_common as B


def main():
    uiname = sys.argv[1] if len(sys.argv) > 1 else "example_tv"
    H, _sb, cf, nodes = B.load_nodes(uiname)
    ncrop = B.inject_node_crops(H, cf, nodes)            # v6: focused-crop dHash per node (audit-only)
    cands = [{"node_id": x["node_id"], "label": x["label"], "fingerprint": x["fingerprint"]} for x in nodes]

    loaded = []
    for x in nodes:
        lp = B.stored_image(cf, x.get("screenshot"))
        img = cv2.imread(lp) if lp else None
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        with contextlib.redirect_stdout(io.StringIO()):
            # self-match: the live crop IS the node's own stored crop; keep img for state fallback
            loaded.append((x["label"], g, H._region_dhashes(g), H._focus_signature(img),
                           x["fingerprint"].get("crop"), img))

    print(f"### Self-match — {uiname} ({len(loaded)} nodes, {ncrop} with a focused crop)")
    print("\n_Each node vs its OWN stored screenshot (ZERO drift — collisions only, NOT a live test)._\n")
    print("| Node | v4 → top | v5 → top | v6 → top | agree |")
    print("|---|---|---|---|:--:|")
    v4ok = v5ok = v6ok = 0
    for label, g, regions, focus, live_crop, img in sorted(loaded, key=lambda z: z[0]):
        with contextlib.redirect_stdout(io.StringIO()):
            r4 = H.match_fingerprint(g, focus, cands)
            r5 = H.match_fingerprint_v5(g, regions, focus, cands)
            r6 = H.match_fingerprint_v6(g, regions, focus, live_crop, cands)
        # mirror localize(): matcher top, else special-state (black/no-signal) fallback
        t4, s4 = B.resolve_top(H, r4, img)
        t5, s5 = B.resolve_top(H, r5, img)
        t6, s6 = B.resolve_top(H, r6, img)
        v4ok += B.same_screen(t4, label) or s4
        v5ok += B.same_screen(t5, label) or s5
        v6ok += B.same_screen(t6, label) or s6
        print(f"| `{label}` | {t4} | {t5} | {t6} | {'✅' if t4 == t5 == t6 else '⚠️'} |")
    print(f"\n**Self-match top-correct: v4 {v4ok}/{len(loaded)} · v5 {v5ok}/{len(loaded)} · "
          f"v6 {v6ok}/{len(loaded)}** (zero-drift baseline; near-ceiling for all — NOT evidence of "
          f"which is better, use bench_drift).")


if __name__ == "__main__":
    main()
