#!/usr/bin/env python3
"""LIVE proof that localize-dispatch generalizes to the APPS tile grid — where tiles share identical
content (dHash) and are told apart ONLY by the focus box position.

Unlike settings (content changes per tab, RIGHT+OK commits), apps is a focus grid: RIGHT/LEFT move
the highlight (no commit; OK would LAUNCH the app), and every tile is the same screen image. So the
candidate-localize must use the FOCUS layer (box x,y), exactly as the plan says for dynamic/grid
menus. The harness:
  discover the tile row live (normalize to the left edge, RIGHT until it wraps, record each focus.x)
  then for each target: fresh-enter apps (lands on the remembered tile) → localize by focus →
  pathfind the row (shorter RIGHT/LEFT, wrap-aware) → move focus → verify focus on the target.

  python3 test_dispatch_apps.py
"""
import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

HOST, DEVICE, NAME, UI = "host1", "device4", "blestbv1", "example_tv"
ENTER_APPS = ["RIGHT", "RIGHT", "OK"]   # home -> home_apps -> apps


def fxy(fp):
    f = fp.get("focus") or {}
    return float(f.get("x") or 0), float(f.get("y") or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()

    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)
    run_dir = HERE / "live_runs" / "_dispatch_apps"
    (run_dir / "captures").mkdir(parents=True, exist_ok=True)
    state = {"next_capture": 0}

    def cap(prefix, keys):
        _shot, fp = ab._settled_capture(client, run_dir, state, prefix, host=HOST, device=DEVICE, keys=keys)
        return fp

    def enter():
        client.goto_home(HOST, DEVICE, UI)
        fp = None
        for k in ENTER_APPS:
            fp = cap("enter", [k])
        return fp

    def to_left_edge():
        """Step LEFT until focus.x stops decreasing (or wraps right) — the left tile of the row."""
        prev = fxy(cap("nav", []))[0]
        for _ in range(12):
            x, _y = fxy(cap("nav", ["LEFT"]))
            if x > prev + 0.02:                 # wrapped past the left edge
                cap("nav", ["RIGHT"]); return
            if abs(x - prev) < 0.02:            # didn't move = already at the wall
                return
            prev = x

    # --- discover the horizontal tile row live -------------------------------------------------
    print("discovering apps tile row …", flush=True)
    enter()
    to_left_edge()
    row = [fxy(cap("tile", []))]                # leftmost tile focus (x,y)
    for _ in range(12):
        x, y = fxy(cap("tile", ["RIGHT"]))
        if any(abs(x - rx) < 0.03 and abs(y - ry) < 0.03 for rx, ry in row):
            break                               # wrapped back onto a known tile -> row complete
        row.append((x, y))
    print(f"  row tiles (x,y): {[(round(x,2),round(y,2)) for x,y in row]}", flush=True)
    n = len(row)
    if n < 2:
        raise SystemExit("could not discover an apps row; aborting")

    def localize(fp):
        """Candidate-localize by FOCUS (content is identical across tiles). Nearest tile in (x,y)."""
        x, y = fxy(fp)
        dists = [abs(x - rx) + abs(y - ry) for rx, ry in row]
        i = min(range(n), key=lambda k: dists[k])
        return i, dists

    def ring_path(cur, tgt):
        r = (tgt - cur) % n
        l = (cur - tgt) % n
        return ("RIGHT", r) if r <= l else ("LEFT", l)

    checks = []
    for tgt in [0, n - 1, 2 % n, 1, 0]:        # incl. wrap (0 -> last, last -> ...)
        print(f"\n=== goto tile idx {tgt} (x~{round(row[tgt][0],2)}) — fresh entry ===", flush=True)
        enter()
        cur, d = localize(cap("loc", []))
        print(f"  entered on (localized): idx {cur} (x~{round(row[cur][0],2)})  dists={[round(x,2) for x in d]}", flush=True)
        key, hops = ring_path(cur, tgt)
        print(f"  row path: {key} x{hops}", flush=True)
        for _ in range(hops):
            cap("hop", [key])                  # focus move only — NO OK (OK would launch the app)
        landed, dl = localize(cap("loc", []))
        ok = landed == tgt
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] landed idx {landed} (want {tgt})  dists={[round(x,2) for x in dl]}", flush=True)

    print(f"\n{'ALL PASS' if all(checks) else 'FAILURES'} ({sum(checks)}/{len(checks)})", flush=True)
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
