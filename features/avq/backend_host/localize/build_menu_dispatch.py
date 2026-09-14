#!/usr/bin/env python3
"""Generic tab-strip DISPATCH builder: capture any menu's top tab strip live and emit the dispatch
shape settings/apps use — a menu HEAD + one DISTINCT prefixed child per tab (incl. the first, so the
first tab is never absorbed into the parent), a [RIGHT,OK]/[LEFT,OK] ring + wrap, fingerprints.

Handles the same device quirks as build_tabstrip_subtree (remembered tab, wrapping strip, body lags
highlight, batched RIGHT+OK fires OK early). Tab labels come from the OCR band token nearest the
focus underline. Then graft with push_autobuild_to_db.py (--graft-into ... --graft-under <root>),
which links child_tree_id so it's navigable.

  python3 build_menu_dispatch.py --ui-name replay_dispatch --root-label replay --entry-keys "RIGHT*3,OK"
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


def parse_keys(spec_str):
    out = []
    for part in spec_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "*" in part:
            k, n = part.split("*"); out += [k.strip().upper()] * int(n)
        else:
            out.append(part.upper())
    return out


def fx(fp):
    return float((fp.get("focus") or {}).get("x") or 0)


def is_nav(fp):
    """True when the focus underline is on the top tab strip (not a search icon / content box)."""
    return ((fp.get("focus") or {}).get("kind")) == "nav"


def tab_token(fp):
    """The tab label = the top-band OCR token whose x is nearest the focus underline."""
    f = fp.get("focus") or {}
    fxp = (f.get("x") or 0) * 100
    toks = [t for t in (fp.get("text") or []) if t.get("y", 100) < 18 and t.get("token")]
    if not toks:
        return None
    best = min(toks, key=lambda t: abs(t.get("x", 0) - fxp))
    lbl = re.sub(r"[^a-z0-9]", "", str(best["token"]).lower())
    return lbl or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui-name", required=True)
    ap.add_argument("--root-label", required=True)
    ap.add_argument("--entry-keys", required=True)
    ap.add_argument("--max-tabs", type=int, default=10)
    ap.add_argument("--skip-leading", type=int, default=0,
                    help="RIGHT presses after normalize to skip a leading search icon before the first real tab")
    ap.add_argument("--tab-labels", default="",
                    help="comma-separated tab names in order (OCR can't read the strip); overrides auto labels")
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()

    entry = parse_keys(args.entry_keys)
    title_match = args.root_label.lower()
    OUT = HERE / "live_runs" / args.ui_name
    (OUT / "captures").mkdir(parents=True, exist_ok=True)
    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)
    state = {"next_capture": 0}

    def grab(prefix, keys):
        return ab._settled_capture(client, OUT, state, prefix, host=HOST, device=DEVICE, keys=keys)

    def nav(keys):
        return grab("_nav", keys)[1]

    def title(fp):
        return re.sub(r"\W+", " ", str((fp or {}).get("title") or "").lower()).strip()

    def enter():
        client.goto_home(HOST, DEVICE, UI)
        fp = None
        for k in entry:
            fp = nav([k])
        return fp

    def onto_strip():
        """Land the focus on the top nav strip. Content-browse screens (replay/filme/tvshop) open with
        focus on a content tile BELOW the strip — press UP to reach it; fall back to RIGHT past a
        leftmost search icon."""
        fp = grab("_nav", [])[1]
        for _ in range(4):
            if is_nav(fp):
                return fp
            fp = nav(["UP"])
        for _ in range(3):
            if is_nav(fp):
                return fp
            fp = nav(["RIGHT"])
        return fp

    def to_leftmost():
        """Wrap-aware AND icon-aware: from the strip, step LEFT until focus wraps right OR falls off
        the strip (non-nav); then RIGHT back onto the leftmost tab. Carousel — NO OK (OK drills into
        content); moving the highlight previews the tab. Finally auto-skip a leading SEARCH icon: the
        magnifier sits at the far left (x<0.12) and — unreliably — reads as nav on some screens and box
        on others, so a fixed count over/under-skips; x-position is robust."""
        onto_strip()
        prev = fx(grab("_nav", [])[1])
        fp = grab("_nav", [])[1]
        for _ in range(args.max_tabs + 1):
            fp = nav(["LEFT"])
            if (not is_nav(fp)) or fx(fp) > prev + 0.02:
                fp = nav(["RIGHT"]); break
            prev = fx(fp)
        if fx(fp) < 0.12:                                # leading search icon → step onto the first tab
            fp = nav(["RIGHT"])
        return fp

    print(f"home -> {title_match} …", flush=True)
    enter()
    to_leftmost()
    for _ in range(args.skip_leading):                   # step past a leading search icon
        nav(["RIGHT"])
    # explicit tab names cap the walk (OCR can't read the strip; also stops the trailing wrap-icon)
    explicit = [re.sub(r"[^a-z0-9]", "", x.strip().lower()) for x in args.tab_labels.split(",") if x.strip()]
    limit = len(explicit) if explicit else args.max_tabs
    # walk the strip, capturing each committed tab
    tabs = []                                            # (shot, fp, label)
    seen_x = []
    shot, fp = grab("tab", [])
    tabs.append((shot, fp, tab_token(fp) or "tab0")); seen_x.append(fx(fp))
    for i in range(1, args.max_tabs):
        if len(tabs) >= limit:
            break                                        # got all named tabs
        shot, fp = grab("tab", ["RIGHT"])                # carousel: move the highlight (no OK)
        if not is_nav(fp):
            break                                        # fell off the strip (screen title varies per
                                                         # menu — e.g. "Movies & Series" — so we rely on
                                                         # is_nav + wrap + label-count, NOT a title match)
        if any(abs(fx(fp) - sx) < 0.03 for sx in seen_x):
            break                                        # wrapped onto a known tab
        tabs.append((shot, fp, tab_token(fp) or f"tab{i}")); seen_x.append(fx(fp))
    # labels: explicit --tab-labels (OCR can't read the strip) else auto, then de-dup
    raw = explicit[:len(tabs)] if explicit else [t[2] for t in tabs]
    while len(raw) < len(tabs):
        raw.append(f"tab{len(raw)}")
    labels, used = [], {}
    for lbl in raw:
        if lbl in used:
            used[lbl] += 1; lbl = f"{lbl}{used[lbl]}"
        else:
            used[lbl] = 0
        labels.append(lbl)
    print(f"  tabs ({len(tabs)}): {labels}", flush=True)
    if len(tabs) < 2:
        raise SystemExit("could not capture a tab strip")

    R = args.root_label
    order = [R] + [f"{R}_{l}" for l in labels]
    nodes, ids = {}, {}
    for i, nl in enumerate(order):
        src = tabs[0] if i == 0 else tabs[i - 1]
        shot, fp, _l = src
        nid = f"node_{i+1:04d}"; ids[nl] = nid
        nodes[nid] = {"node_id": nid, "label": nl, "kind": "root" if i == 0 else "sibling",
                      "depth": 1, "path": [] if i == 0 else ["RIGHT"] * i, "subtree_root": ids[R],
                      "screenshot": shot, "fingerprint": fp, "capture_fp": dict(fp),
                      "dom": None, "tried": []}
    edges = []
    for i in range(len(order) - 1):                      # carousel: single-key highlight moves
        a, b = ids[order[i]], ids[order[i + 1]]
        edges.append({"source": a, "keys": ["RIGHT"], "target": b})
        edges.append({"source": b, "keys": ["LEFT"], "target": a})
    a, b = ids[order[1]], ids[order[-1]]                 # wrap closes the tab ring
    edges.append({"source": b, "keys": ["RIGHT"], "target": a, "no_layout": True})
    edges.append({"source": a, "keys": ["LEFT"], "target": b, "no_layout": True})

    (OUT / "state.json").write_text(json.dumps(
        {"version": 4, "userinterface_name": args.ui_name, "nodes": nodes, "edges": edges,
         "next_capture": state["next_capture"]}, indent=1))
    print(f"wrote {OUT/'state.json'}: {len(nodes)} nodes, {len(edges)} edges", flush=True)
    print("nodes:", ", ".join(order), flush=True)


if __name__ == "__main__":
    main()
