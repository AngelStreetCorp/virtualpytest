#!/usr/bin/env python3
"""FAST offline proof of _reanchor_row: a synthetic pane with rows (measured behavior —
DOWN moves the bar down and CLAMPS at the bottom; row identity = (pane selected_x, bar y),
reflow-free). Verify the row re-anchor reaches EVERY row from a pane, in <= ROW_WALK_MAX.
Runs in ~1s."""
import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)

PANE_X = 0.437                       # the committed pane (System) selected_x
ROW_Y = [0.31, 0.38, 0.46, 0.54, 0.62]   # measured row-bar y positions (5 rows)

def nav_fp():
    return {"dhash": "0"*64, "title": "settings",
            "focus": {"kind": "nav", "x": PANE_X, "width": 0.06, "selected_x": PANE_X}}
def row_fp(y):
    return {"dhash": format(int(y*100), "064b"), "title": "settings",
            "focus": {"kind": "row", "x": 0.35, "y": y, "selected_x": PANE_X}}

class Pane:
    """Device: on the nav row (pos -1) or a row (0..n-1). DOWN increments, clamps at bottom."""
    def __init__(self): self.pos = -1     # -1 = nav row focused (pane committed)
    def press(self, k):
        if k == "DOWN": self.pos = min(self.pos + 1, len(ROW_Y) - 1)
        elif k == "UP": self.pos = max(self.pos - 1, -1)
    def fp(self):
        return nav_fp() if self.pos < 0 else row_fp(ROW_Y[self.pos])

DEV = None
def stub_capture(client, run_dir, state, prefix, *, host, device, keys):
    for k in keys: DEV.press(k)
    return (f"/tmp/{prefix}.png", DEV.fp())

ab._settled_capture = stub_capture
ab._reanchor_strip = lambda *a, **k: True     # reaching the pane is proven by the tab harness
ab.time.sleep = lambda s: None

# state: the committed pane + one node per row
state = {"nodes": {"pane": {"node_id": "pane", "label": "system", "fingerprint": nav_fp()}}}
for i, y in enumerate(ROW_Y):
    state["nodes"][f"row{i}"] = {"node_id": f"row{i}", "label": f"system_row{i}",
                                 "fingerprint": row_fp(y)}
target = {"host_name": "h", "device_id": "d"}

ok = True
print("row re-anchor to each row from the pane top:")
for i, y in enumerate(ROW_Y):
    DEV = Pane()                                    # start on the nav row (pane committed)
    got = ab._reanchor_row(None, Path("/tmp"), state, target, state["nodes"][f"row{i}"])
    landed = (DEV.pos == i)
    tag = "OK" if got and landed else "FAIL"
    if not (got and landed): ok = False
    print(f"  [{tag}] row{i} (y={y}) reached={got} landed_pos={DEV.pos}")
print("\nRESULT:", "PASS" if ok else "FAIL")
