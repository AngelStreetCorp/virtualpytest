#!/usr/bin/env python3
"""Capture the APPS tile row live and assemble a focus-grid DISPATCH run (single-key focus moves —
tiles share one image, told apart by the focus box). Then graft into example_tv_autobuild for review.

    apps (head = leftmost tile; menu, has_subtree ⇒ dispatch)
       ↔ apps_<tile> ↔ apps_<tile> ↔ …   forward [RIGHT] · reverse [LEFT] · + wrap (no_layout)
    each node keeps its data.fingerprint (focus box is the localize key). OK would LAUNCH the app,
    so it is NOT part of the row navigation.

  python3 build_apps_dispatch.py            # writes live_runs/apps_dispatch
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

HOST, DEVICE, NAME, UI = "host1", "device4", "blestbv1", "example_tv"
ENTER_APPS = ["RIGHT", "RIGHT", "OK"]
OUT = HERE / "live_runs" / "apps_dispatch"


def fxy(fp):
    f = fp.get("focus") or {}
    return float(f.get("x") or 0), float(f.get("y") or 0)


# clean up noisy OCR'd focus labels to the real app names
LABEL_FIX = {"ans": "netflix", "gpvoutube": "youtube", "gvoutube": "youtube",
             "youtubz": "youtube", "primevidez": "primevideo"}


def tile_label(fp, i):
    lbl = ((fp.get("focus") or {}).get("label") or "").strip().lower()
    lbl = re.sub(r"[^a-z0-9]", "", lbl)
    return LABEL_FIX.get(lbl, lbl) or f"tile{i}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()

    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)
    (OUT / "captures").mkdir(parents=True, exist_ok=True)
    state = {"next_capture": 0}

    def cap(prefix, keys):
        return ab._settled_capture(client, OUT, state, prefix, host=HOST, device=DEVICE, keys=keys)

    def enter():
        client.goto_home(HOST, DEVICE, UI)
        for k in ENTER_APPS:
            cap("enter", [k])

    def to_left_edge():
        prev = fxy(cap("nav", [])[1])[0]
        for _ in range(12):
            x = fxy(cap("nav", ["LEFT"])[1])[0]
            if x > prev + 0.02:
                cap("nav", ["RIGHT"]); return
            if abs(x - prev) < 0.02:
                return
            prev = x

    print("capturing apps tile row …", flush=True)
    enter(); to_left_edge()
    tiles = []                                   # list of (shot, fp, label)
    seen = []
    shot, fp = cap("tile", [])
    tiles.append((shot, fp, tile_label(fp, 0))); seen.append(fxy(fp))
    for i in range(1, 13):
        shot, fp = cap("tile", ["RIGHT"])
        x, y = fxy(fp)
        if any(abs(x - sx) < 0.03 and abs(y - sy) < 0.03 for sx, sy in seen):
            break                                # wrapped onto a known tile
        tiles.append((shot, fp, tile_label(fp, i))); seen.append((x, y))
    labels = [t[2] for t in tiles]
    print(f"  row tiles: {labels}", flush=True)
    if len(tiles) < 2:
        raise SystemExit("could not capture an apps row")

    # HEAD = the menu copy 'apps' (maps to the parent menu node id); EVERY tile — incl. the leftmost
    # = apps_<firsttile> — is its OWN distinct child (a renamed head collapses to the parent's
    # canonical label in the graph). The head shares the first tile's frame; the tile RING is the
    # children, the head is the dispatch entry.
    nodes, ids = {}, {}
    order = ["apps"] + [f"apps_{lbl}" for _s, _f, lbl in tiles]
    for i, node_lbl in enumerate(order):
        src = tiles[0] if i == 0 else tiles[i - 1]
        shot, fp, _lbl = src
        nid = f"node_{i+1:04d}"; ids[node_lbl] = nid
        nodes[nid] = {"node_id": nid, "label": node_lbl,
                      "kind": "root" if i == 0 else "sibling", "depth": 1,
                      "path": [] if i == 0 else ["RIGHT"] * i,
                      "subtree_root": ids["apps"],
                      "screenshot": shot, "fingerprint": fp, "capture_fp": dict(fp),
                      "dom": None, "tried": []}
    edges = []
    for i in range(len(order) - 1):              # apps->apps_netflix + tile ring, single-key moves
        a, b = ids[order[i]], ids[order[i + 1]]
        edges.append({"source": a, "keys": ["RIGHT"], "target": b})
        edges.append({"source": b, "keys": ["LEFT"], "target": a})
    a, b = ids[order[1]], ids[order[-1]]         # wrap closes the TILE ring (not the head)
    edges.append({"source": b, "keys": ["RIGHT"], "target": a, "no_layout": True})
    edges.append({"source": a, "keys": ["LEFT"], "target": b, "no_layout": True})

    out_state = {"version": 4, "userinterface_name": "apps_dispatch",
                 "nodes": nodes, "edges": edges, "next_capture": state["next_capture"]}
    (OUT / "state.json").write_text(json.dumps(out_state, indent=1))
    print(f"wrote {OUT/'state.json'}: {len(nodes)} nodes, {len(edges)} edges", flush=True)
    print("nodes:", ", ".join(order), flush=True)


if __name__ == "__main__":
    main()
