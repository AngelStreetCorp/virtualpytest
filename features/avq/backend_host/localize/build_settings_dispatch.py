#!/usr/bin/env python3
"""Construct the settings DISPATCH ring run from the already-captured example_tv_settings content
leaves (no re-capture), in the shape push_autobuild_to_db.py consumes. Then graft it into
example_tv_autobuild for review:

    settings (head = Profiles content; menu, has_subtree ⇒ dispatch)
       ↔ settings_accessibility ↔ settings_parentalcontrol ↔ settings_soundimage ↔ settings_system ↔ settings_info
          forward [RIGHT,OK]  ·  reverse [LEFT,OK]  ·  + wrap edge settings ↔ settings_info ([LEFT,OK]/[RIGHT,OK], no_layout)
    each node keeps its data.fingerprint (the localize key); 'settings' has_subtree marks the dispatch.

  python3 build_settings_dispatch.py                 # writes live_runs/settings_dispatch
  # then: push_autobuild_to_db.py --run-dir live_runs/settings_dispatch --graft-into example_tv_autobuild --graft-under settings
"""
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "live_runs" / "example_tv_settings"
OUT = HERE / "live_runs" / "settings_dispatch"

# (example_tv_settings content-leaf label, dispatch node label). The subtree HEAD is the menu copy
# 'settings' (maps to the parent menu node id), and EVERY tab — incl. Profiles = settings_profile —
# is its OWN distinct child node. (A renamed head collapses back to the parent's canonical label in
# the graph, which is why settings_profile vanished before.) settings + settings_profile share the
# Profiles frame; the tab RING is settings_profile..settings_info (the head is the entry, not a tab).
RING = [("settings", "settings"),            # head = the menu (Profiles frame, = node_0052 copy)
        ("settings", "settings_profile"),    # Profiles tab — distinct node, same frame
        ("accessibility", "settings_accessibility"),
        ("parentalcontrol", "settings_parentalcontrol"),
        ("soundimage", "settings_soundimage"),
        ("system", "settings_system"),
        ("info", "settings_info")]


def main():
    src = json.loads((SRC / "state.json").read_text())
    by_label = {v.get("label"): v for v in src["nodes"].values()}
    (OUT / "captures").mkdir(parents=True, exist_ok=True)

    order = [lbl for _s, lbl in RING]
    head = order[0]
    nodes, ids = {}, {}
    for i, (src_lbl, lbl) in enumerate(RING):
        n = by_label[src_lbl]
        shot_src = Path(n["screenshot"])
        shot_dst = OUT / "captures" / shot_src.name
        if shot_src.exists():
            shutil.copy(shot_src, shot_dst)
        nid = f"node_{i+1:04d}"; ids[lbl] = nid
        nodes[nid] = {
            "node_id": nid, "label": lbl,
            "kind": "root" if i == 0 else "sibling",
            "depth": 1, "path": [] if i == 0 else ["RIGHT"] * i,
            "subtree_root": nid if i == 0 else ids[head],
            "screenshot": str(shot_dst), "fingerprint": n["fingerprint"],
            "capture_fp": dict(n["fingerprint"]), "dom": None, "tried": [],
        }

    edges = []
    for i in range(len(order) - 1):                       # adjacent ring links (both directions)
        a, b = ids[order[i]], ids[order[i + 1]]
        edges.append({"source": a, "keys": ["RIGHT", "OK"], "target": b})
        edges.append({"source": b, "keys": ["LEFT", "OK"], "target": a})
    # wrap closes the TAB ring (settings_profile <-> settings_info); the head 'settings' is the
    # dispatch entry, not part of the tab ring. no_layout so it doesn't shift the row.
    a, b = ids[order[1]], ids["settings_info"]
    edges.append({"source": b, "keys": ["RIGHT", "OK"], "target": a, "no_layout": True})  # info -> settings (wrap right)
    edges.append({"source": a, "keys": ["LEFT", "OK"], "target": b, "no_layout": True})   # settings -> info (wrap left)

    state = {"version": 4, "userinterface_name": "settings_dispatch",
             "nodes": nodes, "edges": edges, "next_capture": 0}
    (OUT / "state.json").write_text(json.dumps(state, indent=1))
    print(f"wrote {OUT/'state.json'}: {len(nodes)} nodes, {len(edges)} edges (ring + wrap)")
    print("nodes:", ", ".join(order))


if __name__ == "__main__":
    main()
