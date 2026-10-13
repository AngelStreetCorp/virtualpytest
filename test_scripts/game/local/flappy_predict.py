#!/usr/bin/env python3
"""
Flappy Bird with host-like latency, locally (TASK-33 phase 3c trial).

Every page call is followed by --action-ms (+ up to --jitter-ms) of sleep, standing in for the
executor overhead of one action on a host (~25 ms measured).

  --mode two  read the state in one call, decide in Python, press Space in a second call
              (two executor actions per step, the decision is ~1 call old when the key lands)
  --mode one  one call per step: Python sends the margin and the lookahead (the measured loop
              time in game frames); the call reads the bird, predicts its fall over the lookahead
              with the game's physics, and presses Space in the same call when waiting for the
              next call would be too late. Same rule, applied at read time.

  --mode plan as one, but the call works out WHEN the jump is due: it simulates the next frames
              with the game's physics, finds the frame where the bird would cross the line, and
              schedules Space for the frame before it (setTimeout). The next call cancels and
              replaces any pending press, so each call's plan is based on the freshest reading.

Rule (all modes): aim at the next gap's bottom minus the margin; jump when the bird would be
below it within the lookahead, unless the jump's ~42 px rise would hit the upper pipe; at most one
jump per game frame.

Usage: DISPLAY=:98 python test_scripts/game/local/flappy_predict.py --mode one --seconds 300
"""

import argparse
import json
import random
import time

from playwright.sync_api import sync_playwright

URL = "https://nebezb.com/floppybird/"
FRAME_MS = 1000 / 60

# The bird box and next gap exactly as the page's gameloop computes them.
JS_STATE = """
  const box = document.getElementById('player').getBoundingClientRect();
  const boxheight = (24.0 + box.height) / 2;
  const top = ((box.height - boxheight) / 2) + box.top;
  const bottom = top + boxheight;
  let pipe = null;
  if (pipes[0]) { const u = pipes[0].children('.pipe_upper');
    const pt = u.offset().top + u.height(); pipe = {top: pt, bottom: pt + pipeheight}; }
  const fly = $('#flyarea').offset().top, land = $('#land').offset().top;
"""
JS_READ = "() => {" + JS_STATE + "return {state: currentstate, score, v: velocity, top, bottom, pipe, fly, land}; }"
JS_SPACE = "() => document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 32, bubbles: true}))"
JS_PLAN = """(p) => {""" + JS_STATE + """
  const target = pipe ? pipe.bottom - p.margin : (fly + land) / 2 + 20;
  clearTimeout(window.__vptTimer);
  let fire = -1, b = bottom, t = top, v = velocity;
  for (let f = 0; f <= p.lookahead; f++) {          // frame f: state after f more game frames
    if (b > target) { fire = Math.max(0, f - 1); break; }
    v += 0.25; b += v; t += v;
  }
  let planned = null;
  if (currentstate === 1 && fire >= 0) {
    const peakOk = !pipe || (t - v) - 42.3 > pipe.top + 1;   // top at the firing frame, minus the rise
    if (peakOk) {
      const press = () => { if (performance.now() - (window.__vptJump || 0) > 16.7) {
        document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 32, bubbles: true}));
        window.__vptJump = performance.now(); window.__vptJumps = (window.__vptJumps || 0) + 1; } };
      if (fire === 0) press(); else window.__vptTimer = setTimeout(press, fire * 16.7);
      planned = fire;
    }
  }
  return {state: currentstate, score, v: velocity, top, bottom, pipe, planned, jumps: window.__vptJumps || 0};
}"""
JS_ONE = """(p) => {""" + JS_STATE + """
  const target = pipe ? pipe.bottom - p.margin : (fly + land) / 2 + 20;
  let fall = 0; for (let k = 1; k <= p.lookahead; k++) fall += velocity + 0.25 * k;
  const peakOk = !pipe || top - 42.3 > pipe.top + 1;
  const now = performance.now();
  let jumped = false;
  if (currentstate === 1 && bottom + fall > target && peakOk && now - (window.__vptJump || 0) > 16.7) {
    document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 32, bubbles: true}));
    window.__vptJump = now; jumped = true;
  }
  return {state: currentstate, score, v: velocity, top, bottom, pipe, jumped};
}"""


def pause(a):
    time.sleep((a.action_ms + random.uniform(0, a.jitter_ms)) / 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("plan", "one", "two"), default="plan")
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--action-ms", type=float, default=25)
    ap.add_argument("--jitter-ms", type=float, default=10)
    ap.add_argument("--margin", type=int, default=6)
    ap.add_argument("--url", default=URL, help="the game page; a local copy of github.com/nebez/floppybird works too")
    a = ap.parse_args()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto(a.url, wait_until="load")
        page.wait_for_timeout(2500)
        page.keyboard.press("Space")
        loops, jumps, last, t0 = [], 0, {}, time.time()
        loop_ms, last_jump, hist = 2 * a.action_ms, 0.0, []
        while time.time() - t0 < a.seconds:
            ts = time.perf_counter()
            if a.mode == "plan":
                lookahead = max(1, round(loop_ms / FRAME_MS)) + 2  # until the next call has replanned
                s = page.evaluate(JS_PLAN, {"margin": a.margin, "lookahead": lookahead})
                pause(a)
                jumps = s["jumps"]
            elif a.mode == "one":
                lookahead = max(1, round(loop_ms / FRAME_MS)) + 1  # until the next call lands, plus a frame
                s = page.evaluate(JS_ONE, {"margin": a.margin, "lookahead": lookahead})
                pause(a)
                jumps += s["jumped"]
            else:
                s = page.evaluate(JS_READ)
                pause(a)
                if s["state"] == 1:
                    lookahead = max(1, round(loop_ms / FRAME_MS)) + 1
                    target = s["pipe"]["bottom"] - a.margin if s["pipe"] else (s["fly"] + s["land"]) / 2 + 20
                    fall = sum(s["v"] + 0.25 * (k + 1) for k in range(lookahead))
                    peak_ok = not s["pipe"] or s["top"] - 42.3 > s["pipe"]["top"] + 1
                    if s["bottom"] + fall > target and peak_ok and time.perf_counter() - last_jump > FRAME_MS / 1000:
                        page.evaluate(JS_SPACE)
                        pause(a)
                        jumps += 1
                        last_jump = time.perf_counter()
            if s["state"] != 1:
                break
            last = s
            hist = (hist + [(round(time.time() - t0, 2), round(s["top"]), round(s["bottom"]), round(s["v"], 2),
                             s["pipe"] and (round(s["pipe"]["top"]), round(s["pipe"]["bottom"])), s.get("planned"))])[-12:]
            dt = (time.perf_counter() - ts) * 1000
            loops.append(dt)
            loop_ms = 0.8 * loop_ms + 0.2 * dt
        loops.sort()
        print(json.dumps({
            "mode": a.mode, "action_ms": a.action_ms, "jitter_ms": a.jitter_ms, "margin": a.margin,
            "pipes": last.get("score"), "seconds": round(time.time() - t0, 1), "jumps": jumps,
            "ended": "time_cap" if time.time() - t0 >= a.seconds else "died",
            "loop_ms_p50": round(loops[len(loops) // 2], 1), "loop_ms_p95": round(loops[int(len(loops) * .95)], 1),
            "loop_ms_max": round(loops[-1], 1)}))
        if time.time() - t0 < a.seconds:
            print("last readings (t, top, bottom, v, gap(top,bottom), planned_frame):")
            for h in hist:
                print(" ", h)
        b.close()


if __name__ == "__main__":
    main()
