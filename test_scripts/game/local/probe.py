"""TASK-33 phase 3a local probe: open both pages in a real Chromium at 1280x720 (the VNC screen size),
read their state globals, try real and synthetic keys, and time a read-then-press loop.

Usage (see README.md): DISPLAY=:97 python test_scripts/game/local/probe.py
"""
import asyncio, json, statistics, time
from playwright.async_api import async_playwright

OUT = "."  # screenshots land in the current directory


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 1)


async def loop_latency(page, read_js, key, n=300):
    """read state then press a key, n times: the Flappy control loop."""
    reads, presses, total = [], [], []
    for _ in range(n):
        t0 = time.perf_counter()
        await page.evaluate(read_js)
        t1 = time.perf_counter()
        await page.keyboard.press(key)
        t2 = time.perf_counter()
        reads.append((t1 - t0) * 1000); presses.append((t2 - t1) * 1000); total.append((t2 - t0) * 1000)
    return {k: {"p50": pct(v, .5), "p95": pct(v, .95), "max": round(max(v), 1)}
            for k, v in (("read", reads), ("press", presses), ("loop", total))}


async def tetris(page):
    await page.goto("https://jakesgordon.com/games/tetris/", wait_until="load")
    await page.wait_for_timeout(1000)
    info = {"court_px": await page.evaluate("() => { const c = document.getElementById('canvas'); const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, c.width, c.height]; }")}
    await page.keyboard.press("Space")
    await page.wait_for_timeout(300)
    read = "() => ({playing, score, rows, step, cur: {t: current.type.color, x: current.x, y: current.y, d: current.dir}, next: next.type.color})"
    info["state_after_start"] = await page.evaluate(read)
    # real key: does LEFT move the piece?
    x0 = await page.evaluate("() => current.x")
    await page.keyboard.press("ArrowLeft"); await page.wait_for_timeout(100)
    info["real_left"] = [x0, await page.evaluate("() => current.x")]
    # synthetic event through JS: does the page's keydown handler take it?
    x0 = await page.evaluate("() => current.x")
    await page.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {keyCode: 39, bubbles: true}))")
    await page.wait_for_timeout(100)
    info["synthetic_right"] = [x0, await page.evaluate("() => current.x")]
    # burst: 10 keys in a row, how long, and are all handled (one per frame)?
    x0 = await page.evaluate("() => current.x")
    t0 = time.perf_counter()
    for _ in range(3):
        await page.keyboard.press("ArrowLeft")
    info["burst3_left_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    await page.wait_for_timeout(150)
    info["burst3_left_x"] = [x0, await page.evaluate("() => current.x")]
    await page.screenshot(path=f"{OUT}/tetris.png")
    info["loop"] = await loop_latency(page, read, "Shift", 200)
    return info


async def flappy(page):
    await page.goto("https://nebezb.com/floppybird/", wait_until="load")
    await page.wait_for_timeout(2500)
    read = "() => ({state: currentstate, position, velocity, score, pipes: pipes.length})"
    info = {"before": await page.evaluate(read)}
    await page.keyboard.press("Space")
    await page.wait_for_timeout(200)
    info["after_space"] = await page.evaluate(read)
    full = """() => { const p = pipes[0]; let pipe = null;
        if (p) { const u = p.children('.pipe_upper'); pipe = {left: u.offset().left, gap_top: u.offset().top + u.height()}; }
        return {position, velocity, state: currentstate, pipe, fly: $('#flyarea').offset().top}; }"""
    await page.wait_for_timeout(1600)
    info["with_pipe"] = await page.evaluate(full)
    info["loop"] = await loop_latency(page, full, "Shift", 200)
    await page.screenshot(path=f"{OUT}/flappy.png")
    return info


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = await b.new_page(viewport={"width": 1280, "height": 720})
        res = {}
        for name, fn in (("tetris", tetris), ("flappy", flappy)):
            try:
                res[name] = await fn(page)
            except Exception as e:
                res[name] = {"error": repr(e)[:400]}
        print(json.dumps(res, indent=1))
        await b.close()

asyncio.run(main())
