"""TASK-33 phase 3 local prototype: play nebezb.com/floppybird unattended in a local Chromium.

Each tick reads the bird and the next pipe through page JS (the page's own collision maths). It
presses Space when the bird would drop below the next gap's safe line within the lookahead, unless
the jump's ~42 px rise would hit the upper pipe; at most one jump per game frame. On death it prints
the last frames.

Usage (see README.md): DISPLAY=:98 python test_scripts/game/local/flappy_local.py [seconds] [margin_px] [lookahead_frames]
"""
import asyncio, json, statistics, sys, time
from playwright.async_api import async_playwright

URL = "https://nebezb.com/floppybird/"
READ = """() => {
  const box = document.getElementById('player').getBoundingClientRect();
  const boxheight = (24.0 + box.height) / 2;
  const top = ((box.height - boxheight) / 2) + box.top;
  let pipe = null;
  if (pipes[0]) { const u = pipes[0].children('.pipe_upper');
    const pt = u.offset().top + u.height(); const pl = u.offset().left - 2;
    pipe = {top: pt, bottom: pt + pipeheight, left: pl, right: pl + pipewidth}; }
  const fly = $('#flyarea'); const ft = fly.offset().top;
  return {state: currentstate, score, v: velocity, top, bottom: top + boxheight, left: box.left,
          pipe, fly_top: ft, fly_bottom: $('#land').offset().top};
}"""
MARGIN = 14       # px kept between the bird's bottom and the lower pipe
LOOKAHEAD = 2     # frames of fall predicted, covering read + key latency
FRAME_S = 1 / 60    # at most one jump per game frame
JUMP_RISE = 42.3  # 4.6^2 / (2 * 0.25): height a jump gains with the page's physics


async def main(max_s, margin, lookahead):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = await b.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(URL, wait_until="load")
        await page.wait_for_timeout(2500)
        await page.keyboard.press("Space")  # starts the game (and jumps)
        loop_ms, jumps, t0 = [], 0, time.time()
        last = None
        hist = []
        last_jump = 0.0
        while time.time() - t0 < max_s:
            ts = time.perf_counter()
            s = await page.evaluate(READ)
            if s["state"] != 1:
                break
            last = s
            hist.append((round(time.time() - t0, 3), round(s['top']), round(s['bottom']), round(s['v'], 2), s['pipe'] and (round(s['pipe']['top']), round(s['pipe']['bottom']), round(s['pipe']['left']), round(s['pipe']['right'])), round(s['left'])))
            hist = hist[-25:]
            # pipes[0] is always the next pipe (the page drops a pipe once the bird is past it),
            # so aim at its gap right away: a big climb needs the whole distance between pipes.
            pipe = s["pipe"]
            target = pipe["bottom"] - margin if pipe else (s["fly_top"] + s["fly_bottom"]) / 2 + 20
            fall = sum(s["v"] + 0.25 * (k + 1) for k in range(lookahead))
            # A jump resets velocity to -4.6 and lifts the bird ~42 px: never jump into the upper pipe,
            # but do jump again while still rising when the bird is below the target (big climbs).
            peak_ok = not pipe or s["top"] - JUMP_RISE > pipe["top"] + 1
            if s["bottom"] + fall > target and peak_ok and time.perf_counter() - last_jump > FRAME_S:
                await page.keyboard.press("Space")
                jumps += 1
                last_jump = time.perf_counter()
                hist.append(('JUMP',))
            loop_ms.append((time.perf_counter() - ts) * 1000)
        await page.wait_for_timeout(300)
        await page.screenshot(path="flappy_end.png")
        loop_ms.sort()
        print(json.dumps({"pipes": (last or {}).get("score"), "seconds": round(time.time() - t0, 1), "jumps": jumps,
                          "ended": "time_cap" if time.time() - t0 >= max_s else "died",
                          "loop_ms_p50": round(loop_ms[len(loop_ms) // 2], 2),
                          "loop_ms_p95": round(loop_ms[int(len(loop_ms) * .95)], 2), "loop_ms_max": round(loop_ms[-1], 2),
                          "last": last}))
        if time.time() - t0 < max_s:
            print("history (t, top, bottom, v, pipe(top,bottom,left,right), bird_left):")
            for h in hist: print(" ", h)
        await b.close()

a = sys.argv
asyncio.run(main(float(a[1]) if len(a) > 1 else 120, int(a[2]) if len(a) > 2 else MARGIN, int(a[3]) if len(a) > 3 else LOOKAHEAD))
