"""TASK-33 phase 3 local prototype: play jakesgordon.com Tetris unattended in a local Chromium.

State comes from the page globals (prototype only; the VPT version adds a pixel reader checked
against them). One decision per piece: El-Tetris placement heuristic, then a key burst.

Usage (see README.md): DISPLAY=:97 python test_scripts/game/local/tetris_local.py [max_pieces]
"""
import asyncio, json, statistics, sys, time
from playwright.async_api import async_playwright

URL = "https://jakesgordon.com/games/tetris/"
NX, NY = 10, 20
SHAPES = {  # copied from the page: one 16-bit mask per rotation (dir 0..3)
    "cyan": [0x0F00, 0x2222, 0x00F0, 0x4444], "blue": [0x44C0, 0x8E00, 0x6440, 0x0E20],
    "orange": [0x4460, 0x0E80, 0xC440, 0x2E00], "yellow": [0xCC00] * 4,
    "green": [0x06C0, 0x8C40, 0x6C00, 0x4620], "purple": [0x0E40, 0x4C40, 0x4E00, 0x4640],
    "red": [0x0C60, 0x4C80, 0xC600, 0x2640],
}
# El-Tetris weights (Islam El-Ashi): landing height, rows cleared, row/col transitions, holes, wells
W = (-4.500158825082766, 3.4181268101392694, -3.2178882868487753, -9.348695305445199,
     -7.899265427351652, -3.3855972247263626)

READ = """() => ({playing, score, rows, step,
  cur: current ? {t: current.type.color, x: current.x, y: current.y, d: current.dir, seen: !!current.__seen} : null,
  next: next ? next.type.color : null,
  court: Array.from({length: 10}, (_, x) => Array.from({length: 20}, (_, y) => (blocks[x] && blocks[x][y]) ? 1 : 0))})"""
MARK = "() => { if (current) current.__seen = true; }"


def cells(t, d, x, y):
    m, out = SHAPES[t][d], []
    for i in range(16):
        if m & (0x8000 >> i):
            out.append((x + i % 4, y + i // 4))
    return out


def fits(court, t, d, x, y):
    return all(0 <= cx < NX and 0 <= cy < NY and not court[cx][cy] for cx, cy in cells(t, d, x, y))


def features(court, placed, lines):
    land = NY - min(cy for _, cy in placed)  # landing height, from the bottom
    rt = ct = holes = wells = 0
    for y in range(NY):
        prev = 1
        for x in range(NX):
            if court[x][y] != prev: rt += 1
            prev = court[x][y]
        if prev != 1: rt += 1
    for x in range(NX):
        prev, block_seen = 0, False
        for y in range(NY):
            v = court[x][y]
            if v != prev: ct += 1
            prev = v
            if v: block_seen = True
            elif block_seen: holes += 1
        if prev != 1: ct += 1
        depth = 0
        for y in range(NY):
            left = court[x - 1][y] if x > 0 else 1
            right = court[x + 1][y] if x < NX - 1 else 1
            if not court[x][y] and left and right:
                depth += 1; wells += depth
            else:
                depth = 0
    return (land, lines, rt, ct, holes, wells)


def place(court, t, d, x):
    """Drop piece (t, d) at column x from the top: (new_court, placed_cells, lines) or None."""
    y = 0
    if not fits(court, t, d, x, y):
        return None
    while fits(court, t, d, x, y + 1):
        y += 1
    c = [col[:] for col in court]
    placed = cells(t, d, x, y)
    for cx, cy in placed:
        c[cx][cy] = 1
    full = [yy for yy in range(NY) if all(c[xx][yy] for xx in range(NX))]
    for yy in full:  # same as the page's removeLine: shift everything above down
        for xx in range(NX):
            del c[xx][yy]; c[xx].insert(0, 0)
    return c, placed, len(full)


def reachable(court, t, d0, x0, y0, d, x):
    """Rotate in place first (no wall kicks on this page), then shift sideways."""
    dd = d0
    while dd != d:
        dd = (dd + 1) % 4
        if not fits(court, t, dd, x0, y0):
            return False
    step = 1 if x > x0 else -1
    for xx in range(x0, x, step):
        if not fits(court, t, d, xx + step, y0):
            return False
    return True


def best_move(court, cur):
    t, x0, y0, d0 = cur["t"], cur["x"], cur["y"], cur["d"]
    best = None
    for d in range(4):
        for x in range(-3, NX):
            if not reachable(court, t, d0, x0, y0, d, x):
                continue
            r = place(court, t, d, x)
            if r is None:
                continue
            c, placed, lines = r
            score = sum(w * f for w, f in zip(W, features(c, placed, lines)))
            if best is None or score > best[0]:
                best = (score, d, x)
    return best


async def main(max_pieces):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = await b.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(URL, wait_until="load")
        await page.wait_for_timeout(800)
        await page.keyboard.press("Space")
        pieces, decide_ms, spare_rows, t_start = 0, [], [], time.time()
        stop = "max_pieces"
        while pieces < max_pieces:
            s = await page.evaluate(READ)
            if not s["playing"]:
                stop = "game_over"; break
            cur = s["cur"]
            if cur["seen"]:
                await asyncio.sleep(0.005); continue
            await page.evaluate(MARK)
            t0 = time.perf_counter()
            mv = best_move(s["court"], cur)
            decide_ms.append((time.perf_counter() - t0) * 1000)
            if mv is None:
                stop = "no_move"; break
            _, d, x = mv
            keys = ["ArrowUp"] * ((d - cur["d"]) % 4) + (["ArrowRight"] * (x - cur["x"]) if x > cur["x"] else ["ArrowLeft"] * (cur["x"] - x))
            for k in keys:
                await page.keyboard.press(k)
            # wait until the page applied rotation + shift (one input per frame), then drop
            for _ in range(60):
                c = await page.evaluate("() => current && current.__seen ? [current.x, current.dir, current.y] : null")
                if c is None or (c[0] == x and c[1] == d):
                    break
                await asyncio.sleep(0.005)
            if c is not None:
                spare_rows.append(NY - c[2])
            for _ in range(NY + 2):  # extra DOWNs are cleared by the page when the piece lands
                await page.keyboard.press("ArrowDown")
            pieces += 1
            if pieces % 50 == 0:
                print(f"pieces {pieces} rows {s['rows']} score {s['score']} step {s['step']:.3f}s", flush=True)
        s = await page.evaluate(READ)
        await page.screenshot(path="tetris_end.png")
        print(json.dumps({"stop": stop, "pieces": pieces, "rows": s["rows"], "score": s["score"], "step_s": s["step"],
                          "decide_ms_p50": round(statistics.median(decide_ms), 1), "decide_ms_max": round(max(decide_ms), 1),
                          "seconds": round(time.time() - t_start, 1)}))
        await b.close()

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
