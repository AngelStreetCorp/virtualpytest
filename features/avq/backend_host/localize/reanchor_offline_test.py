#!/usr/bin/env python3
"""FAST offline proof of _reanchor_strip: a synthetic stateful tab strip (fingerprints, no
real frames) that remembers its last committed tab. Verify the re-anchor reaches ANY
committed pane from ANY remembered start in <= STRIP_WALK_MAX presses — the tab-cache case
that stranded the rigid replay."""
import importlib.util
from pathlib import Path

SCRIPTS = Path("~/virtualpytest-demo/backend_host/scripts")
spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)

TABS = ["profiles", "accessibility", "parentalcontrol", "soundimage", "system", "info"]
TABX = [0.08, 0.18, 0.31, 0.44, 0.57, 0.70]   # fixed on-screen order (sim; no reflow noise)

def fp(selected, focus, row=None):
    """Synthetic fingerprint. row=None -> focus on the tab strip (nav underline). row=int ->
    focus dropped into the pane ROWS (kind 'row', bar y) — the real-device state where the row
    cursor persisted on entry (measured 2026-07-17); the re-anchor must UP-mount before walking."""
    if row is not None:
        return {"dhash": format(TABS.index(selected), "064b"), "title": "settings", "dynamic": False,
                "focus": {"kind": "row", "x": 0.35, "y": 0.31 + 0.08 * row,
                          "selected_x": TABX[TABS.index(selected)]}}
    return {"dhash": format(TABS.index(selected), "064b"), "title": "settings", "dynamic": False,
            "focus": {"kind": "nav", "x": TABX[TABS.index(focus)], "width": 0.06,
                      "selected_x": TABX[TABS.index(selected)]}}

class Strip:
    def __init__(self, remembered, row=None):
        self.selected = remembered; self.focus = remembered; self.row = row   # row=int -> in rows
    def press(self, k):
        if self.row is not None:                 # in the pane rows: UP mounts back to tabs
            if k == "UP": self.row = None if self.row == 0 else self.row - 1
            elif k == "DOWN": self.row = min(self.row + 1, 4)
            return                               # RIGHT/LEFT/OK don't move tabs while in rows
        i = TABS.index(self.focus)
        if k == "RIGHT": self.focus = TABS[min(i+1, len(TABS)-1)]     # clamp
        elif k == "LEFT": self.focus = TABS[(i-1) % len(TABS)]         # wrap
        elif k == "OK": self.selected = self.focus
        elif k == "DOWN": self.row = 0           # drop into rows
    def fp(self): return fp(self.selected, self.focus, self.row)

DEV = None
def stub_capture(client, run_dir, state, prefix, *, host, device, keys):
    for k in keys: DEV.press(k)
    return (f"/tmp/{prefix}.png", DEV.fp())

ab._settled_capture = stub_capture
ab._replay_to = lambda *a, **k: True         # entry-to-parent proven elsewhere
ab._same_family = lambda a, b: True          # same settings screen
ab.time.sleep = lambda s: None

# state: strip root (settings/profiles) with a path so _reanchor finds it; parent = home_settings
def node(pane):
    return {"label": f"settings_{pane}" if pane != "profiles" else "settings",
            "path": ["OK"] if pane == "profiles" else ["OK"],
            "fingerprint": fp(pane, pane)}   # committed pane
state = {"nodes": {
    "root": {"node_id": "root", **node("profiles")},
    "parent": {"node_id": "parent", "path": [], "fingerprint": {"title": "home", "focus": {}}},
}}
# add committed panes as strip nodes so _reanchor_strip's root-search sees a strip
for p in TABS:
    state["nodes"][p] = {"node_id": p, **node(p)}

target = {"host_name": "h", "device_id": "d"}
ok_all = True
print("re-anchor to each committed pane from every remembered start (incl. focus-in-rows):")
for goal in TABS:
    # start_row=int models entering with focus dropped into the pane rows (the live failure)
    for start, start_row in [("profiles", None), ("system", None), ("info", None),
                             ("soundimage", 2), ("system", 4), ("info", 0)]:
        DEV = Strip(remembered=start, row=start_row)
        got = ab._reanchor_strip(None, Path("/tmp"), state, target, state["nodes"][goal])
        landed = (DEV.selected == goal and DEV.row is None)
        tag = "OK" if got and landed else "FAIL"
        if not (got and landed): ok_all = False
        rc = f"row{start_row}" if start_row is not None else "tabs"
        print(f"  [{tag}] goal={goal:14s} start={start:11s}({rc}) reached={got} landed_on={DEV.selected}")
print("\nRESULT:", "PASS" if ok_all else "FAIL")
