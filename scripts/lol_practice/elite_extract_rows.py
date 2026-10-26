#!/usr/bin/env python3
"""Elite replay frames -> per-frame rows (turns.json), run on the Mac from the repo root:
    python3 scripts/lol_practice/elite_extract_rows.py <game_dir> [...]
Spectator frames (REPLAYS.md): bars are team-coloured (red team = find_bars "enemy" colour, blue team = "ally" colour), and
Garen's own bar is his team colour with 100-HP ticks, so find_bars splits it. Garen is found as the team-coloured row with the
most fill in the follow-camera window; his x = bar left end + 64 (128 px bar), body = bar row + 125. Rows only for frames with
the camera locked on him (rows.json "locked")."""
import json, math, os, sys
from multiprocessing import Pool
import numpy as np
from PIL import Image
sys.path.insert(0, os.getcwd())
from shared.src.lib.game.leagueoflegends import perception as P

WIN = (700, 300, 1220, 560)  # x0, y0, x1, y1: where the follow camera keeps Garen's bar (camera lag included)
CLASH_PX = 260
BLANK = [(140, 560, 760, 820), (0, 140, 180, 720), (1820, 140, 1920, 720)]  # chat log; blue / red portrait columns

def dist(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])

def garen_bar(img, colour):
    x0, y0, x1, y1 = WIN
    m = P._fill_mask(img[y0:y1, x0:x1], colour)
    if colour == "enemy":  # the enemy mask includes the near-black empty part: keep the pink fill only
        sub = img[y0:y1, x0:x1].astype(np.int16)
        m = (sub[..., 0] > 130) & (sub[..., 1] < 115) & (sub[..., 2] < 115) & (sub[..., 0] - sub[..., 1] > 70)
    counts = m.sum(axis=1)
    row = int(counts.argmax())
    if counts[row] < 30:
        return None
    xs = np.nonzero(m[row])[0]
    left = int(xs.min()) + x0
    return {"x": left + 64, "y": row + y0 + 125, "bar_y": row + y0, "hp": round(min(1.0, (int(xs.max()) - int(xs.min()) + 1) / 128), 2)}

def drop_split_champions(bars):
    """A champion bar has 100-HP ticks, so find_bars returns it as 3+ short "minion" pieces on one row within ~140 px."""
    out = []
    for b in bars:
        same = [c for c in bars if abs(c.y - b.y) <= 2 and abs(c.x - b.x) <= 140]
        if len(same) < 3:
            out.append(b)
    return out

def one(args):
    gdir, r, red = args
    img = np.array(Image.open(os.path.join(gdir, r["file"])).convert("RGB"))
    for x0, y0, x1, y1 in BLANK:  # spectator chat (red/blue names read as bars), portrait columns
        img[y0:y1, x0:x1] = 90
    own_c, foe_c = ("enemy", "ally") if red else ("ally", "enemy")
    g = garen_bar(img, own_c)
    own = drop_split_champions([b for b in P.find_bars(img, own_c) if b.kind == "minion"])
    foe = drop_split_champions([b for b in P.find_bars(img, foe_c) if b.kind == "minion"])
    if g:  # drop the pieces of Garen's own split bar
        own = [b for b in own if not (abs(b.y - g["bar_y"]) <= 6 and abs(b.x - g["x"]) <= 80)]
    row = {"t": r["t"], "cs10": (r.get("scores") or {}).get("creepScore"), "level": r.get("level"), "items": r.get("items"), "dead": r.get("dead"),
           "garen": [g["x"], g["y"]] if g else None, "garen_hp": g["hp"] if g else None,
           "own": [[b.x, b.y + 50, b.frac] for b in own], "foe": [[b.x, b.y + 50, b.frac] for b in foe]}
    if g and own and foe:
        gp = (g["x"], g["y"])
        fc = (sum(b.x for b in foe) / len(foe), sum(b.y + 50 for b in foe) / len(foe))
        front = min(dist((b.x, b.y + 50), fc) for b in own)  # our minion closest to the enemy wave
        row["clash"] = min(dist((a.x, a.y), (b.x, b.y)) for a in own for b in foe) < CLASH_PX
        row["behind_px"] = round(dist(gp, fc) - front)       # > 0: Garen is farther from the enemy wave than our front minion
        row["to_foe_px"] = round(min(dist(gp, (b.x, b.y + 50)) for b in foe))
        row["low_foe_near"] = sum(1 for b in foe if b.frac < 0.35 and dist(gp, (b.x, b.y + 50)) < 260)
    return row

def extract(gdir, procs=6):
    meta = json.load(open(os.path.join(gdir, "rows.json")))
    red = meta["team"] == "200"
    todo = [(gdir, r, red) for r in meta["rows"] if r.get("locked", True) and os.path.exists(os.path.join(gdir, r["file"]))]
    with Pool(procs) as pool:
        rows = pool.map(one, todo, chunksize=8)
    json.dump({"gid": meta["gid"], "team": meta["team"], "rows": rows}, open(os.path.join(gdir, "turns.json"), "w"))
    return rows

if __name__ == "__main__":
    for d in sys.argv[1:]:
        rows = extract(d)
        print(d, len(rows), "rows,", sum(1 for r in rows if r["garen"]), "with Garen")
