#!/usr/bin/env python3
"""Offline reproduction of the settings-strip node-creation behavior, with REFLOW.

Models a 6-tab commit strip where the tab x-positions REFLOW with the bold (selected) tab,
then replays a realistic explore walk (RIGHT sweep + LEFT sweep, visiting panes in varying
orders) through the REAL node-identity logic (_find_node / _same_screen), counting how many
nodes get created — WITHOUT the fix (hover nodes leak) vs WITH the fix (only committed panes
are nodes). Pure fingerprints, no device, runs in ~1s."""
import importlib.util
from pathlib import Path

SCRIPTS = Path("~/virtualpytest-demo/backend_host/scripts")
spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)

TABS = ["profiles", "accessibility", "parental", "soundimage", "system", "info"]

def tab_x(selected, tab):
    """Tab x REFLOWS: the bold (selected) tab widens, shifting tabs to its right.
    Base positions, plus a small rightward shift for every tab right of the selected one —
    this is the measured behavior (System 0.437 selected vs ~0.54 when another is selected)."""
    base = [0.08, 0.18, 0.30, 0.43, 0.54, 0.63]
    si, ti = TABS.index(selected), TABS.index(tab)
    x = base[ti] + (0.03 if ti > si else 0.0)      # reflow shift
    if ti == si:
        x = base[ti]                               # committed tab at its base slot
    return round(x, 3)

def fp(selected, focus):
    """Fingerprint of the strip state. dHash keyed by DISPLAYED pane (content); focus = tab x."""
    committed = (focus == selected)
    return {"dhash": format(TABS.index(selected), "064b"), "title": "settings", "dynamic": False,
            "regions": {"top": "0"*64, "center": format(TABS.index(selected), "064b"),
                        "bottom": "0"*64, "left": "0"*64, "full": format(TABS.index(selected), "064b")},
            "focus": {"kind": "nav", "x": tab_x(selected, focus), "width": 0.06,
                      "selected_x": tab_x(selected, selected)}}

def walk():
    """A realistic explore walk: from Profiles, RIGHT+OK across all tabs (RIGHT sweep),
    then LEFT+OK back (LEFT sweep) — the reflow means the SAME tab is hovered at different x
    on the two sweeps, which is what leaks hover variants."""
    frames = []
    sel = "profiles"
    # RIGHT sweep: hover next, commit it
    for i in range(len(TABS)-1):
        nxt = TABS[TABS.index(sel)+1]
        frames.append(("hover", fp(sel, nxt)))       # RIGHT -> hover next tab
        frames.append(("commit", fp(nxt, nxt)))      # OK -> commit it
        sel = nxt
    # LEFT sweep back: hover prev, commit it
    for i in range(len(TABS)-1):
        prv = TABS[TABS.index(sel)-1]
        frames.append(("hover", fp(sel, prv)))       # LEFT -> hover prev tab
        frames.append(("commit", fp(prv, prv)))      # OK -> commit it
        sel = prv
    return frames

def count_nodes(frames, drop_hovers):
    """Replay the walk through _find_node, creating a node when nothing matches.
    drop_hovers=True models the fix: a hover (focus != selected) is never a node."""
    state = {"nodes": {}, "edges": []}
    created = 0
    for kind, f in frames:
        if drop_hovers and kind == "hover":
            continue                                 # FIX: hovers are transient, not nodes
        node_fp = {"fingerprint": f}
        # does it match an existing node?
        match = None
        for nid, n in state["nodes"].items():
            if ab._same_screen(n["fingerprint"], f):
                match = nid; break
        if match is None:
            nid = f"n{created}"
            state["nodes"][nid] = node_fp
            created += 1
    return created

frames = walk()
print(f"walk has {len(frames)} frames ({sum(1 for k,_ in frames if k=='hover')} hovers, "
      f"{sum(1 for k,_ in frames if k=='commit')} commits) across 6 tabs")
no_fix = count_nodes(frames, drop_hovers=False)
with_fix = count_nodes(frames, drop_hovers=True)
print(f"\nWITHOUT fix (hovers become nodes): {no_fix} nodes  (clean strip = 6 committed panes)")
print(f"WITH fix    (hovers dropped)       : {with_fix} nodes")
print("\nRESULT:", "FIX WORKS — converges to 6 committed panes" if with_fix == 6
      else f"unexpected: with_fix={with_fix}")
print("(no_fix > 6 reproduces the leak)" if no_fix > 6 else "(leak not reproduced)")
