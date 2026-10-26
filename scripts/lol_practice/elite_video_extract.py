#!/usr/bin/env python3
"""Elite replay video -> per-frame dataset (turns.jsonl, lol-aggro reward-layer shape) at 5 Hz. Run on the Mac from the repo root:
    python3 scripts/lol_practice/elite_video_extract.py <game_dir> [--hz 5] [--limit N]
<game_dir> holds video_<t0>-<t1>.mkv, log_<t0>-<t1>.jsonl, meta_<t0>-<t1>.json, events_<t0>-<t1>.json (elite_box.py video).
Readers: HUD digit templates in elite_hud/ (panel.py, hud.py); bars via perception.find_bars. Spectator bars are team-
coloured: red team = find_bars "enemy" colour, blue team = "ally" colour. A champion bar has 100-HP ticks, so find_bars returns it
as 3+ short pieces on one row: those clusters are champions, the rest minions."""
import glob, json, math, os, sys
import numpy as np
import cv2
from PIL import Image
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "elite_hud"))
from shared.src.lib.game.leagueoflegends import perception as P
from shared.src.lib.game.leagueoflegends.minion_track import IdTracker  # shared with the bot (task121): one tracker
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from elite_bar_classifier import BarClassifier
from shared.src.lib.game.leagueoflegends import bar_frames as BF
import panel, hud

FOUNTAIN = {"100": (400, 400), "200": (14340, 14390)}  # world x, z
CENTRE = (960, 430)  # where the follow camera keeps the selected champion's bar (with lag)
CHAMP_W = 106

def dist(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])

HUD_BLANK = [(330, 0, 1600, 75), (880, 75, 1050, 135), (0, 925, 340, 1200), (1625, 885, 1920, 1200), (0, 140, 95, 720), (1825, 140, 1920, 720),
             (1500, 760, 1760, 885)]  # top bar, clock, panel, minimap, portraits, kill feed (gate 3: its icons read as minion bars)
SCOREBOARD_BLANK = (560, 878, 1380, 1200)  # timeline + scoreboard, only when the scoreboard is on screen
TIMELINE_BLANK = (560, 1080, 1380, 1200)   # timeline only (captures without the scoreboard)

_SB_REF = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "elite_hud", "sb_ref.npy")).astype(np.float32)

def scoreboard_on(a):
    """Scoreboard on screen = its fixed top rows (x 575-1365, y 936-1000: frame, coin icons, first row) match the reference."""
    g = cv2.cvtColor(np.ascontiguousarray(a[936:1000, 575:1365]), cv2.COLOR_RGB2GRAY).astype(np.float32)
    r = _SB_REF
    c = float(((g - g.mean()) * (r - r.mean())).sum() / (np.sqrt(((g - g.mean()) ** 2).sum() * ((r - r.mean()) ** 2).sum()) + 1e-6))
    return c > 0.5

def _team_mask(a, colour):
    r, g, b = a[..., 0].astype(np.int16), a[..., 1].astype(np.int16), a[..., 2].astype(np.int16)
    if colour == "enemy":  # red team fill
        return (r > 130) & (g < 115) & (b < 115) & (r - g > 60)
    return (b > 150) & (r < 120) & (b - r > 50)  # blue team fill

BAR_CLF = BarClassifier(os.path.join(os.path.dirname(os.path.abspath(__file__)), "elite_hud", "bar_clf_v2.npz"))  # minion vs not, threshold 0 (v2: + 325 frame-detector crops)
_LV = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "elite_hud", "lvlbox.npz"))
LV_T, LV_M = _LV["T"].astype(np.uint8), (_LV["M"] * 255).astype(np.uint8)

def champion_boxes(a):
    """Champion level boxes: 26x26 grey ring with a dark inside (template on the ring only; the digit changes)."""
    g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    res = cv2.matchTemplate(g, LV_T, cv2.TM_CCORR_NORMED, mask=LV_M)
    res = np.nan_to_num(res)
    ys, xs = np.nonzero(res > 0.985)
    order = np.argsort(-res[ys, xs]); out = []
    for i in order:
        y, x = int(ys[i]), int(xs[i])
        if any(abs(y - oy) < 20 and abs(x - ox) < 20 for oy, ox in out): continue
        inner = g[y + 4:y + 22, x + 4:x + 22]
        if inner.mean() < 75 and inner.max() > 160:  # dark inside with a light level digit
            out.append((y, x))
    return out

def champion_bars(a, colour):
    """Champion bars of one team colour: the bar right of a level box. hp_frac = filled run (ticks bridged) / 106 px."""
    m = _team_mask(a, colour); out = []
    for by, bx in champion_boxes(a):
        y0, x0 = by + 5, bx + 26
        band = m[y0:y0 + 11, x0:x0 + CHAMP_W + 4]
        cols = band.sum(axis=0) >= 3
        if cols[:12].sum() < 6: continue  # not this team's colour (or empty): the other team's pass takes it
        xs = np.nonzero(cols)[0]
        box = cv2.cvtColor(a[by + 4:by + 22, bx + 4:bx + 22], cv2.COLOR_RGB2GRAY).astype(np.float32)
        v = cv2.resize(box, (12, 16), interpolation=cv2.INTER_AREA).flatten(); v = (v - v.mean()) / (v.std() + 1e-6)
        out.append({"x": x0 + CHAMP_W // 2, "y": by + 135, "bar_y": by + 10, "x0": x0, "hp_frac": round(min(1.0, (int(xs.max()) + 1) / CHAMP_W), 2),
                    "lv": [round(float(z), 2) for z in v]})
    return out

def bordered(g, b):
    """A real minion bar has a dark border row above and below across its ~62 px; outline / label fragments usually do not."""
    x0 = int(b.x) - 31; xs = slice(max(0, x0 + 3), x0 + 59)
    def dark_row(rng): return any((g[y, xs] < 50).mean() >= 0.7 for y in rng if 0 <= y < g.shape[0])
    return dark_row(range(b.y - 5, b.y)) and dark_row(range(b.y + 1, b.y + 7))

def bars(img, colour):
    """(minions, champions) of one colour. Minion pieces lying exactly on a champion bar rectangle are dropped; every other bar is
    kept with a 'bordered' flag, filtered in finalize()."""
    champs = champion_bars(img, colour)
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ms = []
    for b in P.find_bars(img, colour):
        if b.kind != "minion": continue
        lo, hi = b.x - 31, b.x + 31  # a minion bar overlapping a champion bar (with its level box) by more than half is a piece of it
        if any(abs(b.y - c["bar_y"]) <= 6 and min(hi, c["x0"] + CHAMP_W) - max(lo, c["x0"] - 28) > 31 for c in champs): continue
        ms.append({"x": b.x, "y": b.y + 50, "bar_y": b.y, "hp_frac": b.frac, "bordered": bordered(g, b)})
    return ms, champs

def body_team(a, x, bar_y):
    """Side of the minion under a bar from its armour colour (box 45x45 below the bar): 'enemy' = red, 'ally' = blue (find_bars names)."""
    reg = a[bar_y + 12:bar_y + 60, max(0, x - 25):x + 25].astype(np.int16)
    if reg.size == 0: return "unknown"
    r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
    red = ((r > 120) & (r > g + 40) & (r > b + 40)).sum(); blue = ((b > 120) & (b > r + 30)).sum()
    if max(red, blue) < 25: return "unknown"
    return "enemy" if red > blue else "ally"

def align(cap, n_frames, fps):
    """Game time of frame 0: find the frame where the HUD clock ticks to the next second (1x playback)."""
    prev, idx = None, 0
    for idx in range(0, min(n_frames, int(fps * 6))):
        ok, fr = cap.read()
        if not ok: break
        c = hud.clock(Image.fromarray(fr[:, :, ::-1]))
        if prev is not None and c is not None and c == prev + 1:
            return c - idx / fps
        prev = c if c is not None else prev
    raise SystemExit("clock alignment failed")

def frame_row(img, t, L, team, own_c, foe_c):
    """Per-frame readings and RAW detections; Garen, filters and units are decided in finalize() (needs neighbouring frames)."""
    a = np.array(img)
    sb = scoreboard_on(a)
    for x0, y0, x1, y1 in HUD_BLANK + [SCOREBOARD_BLANK if sb else TIMELINE_BLANK]:  # HUD icons and text read as bars; mask matched per frame
        a[y0:y1, x0:x1] = 90
    p = panel.read_panel_t(img)  # digit templates: tesseract confuses 3/5 on this font
    cs = hud.sb_cs_digits(img, team, 0); kda = hud.sb_kda(img, team, 0)
    own_m, own_ch = bars(a, own_c); foe_m, foe_ch = bars(a, foe_c)
    # frame detector (bar_frames): dim / empty bars find_bars cannot see; side from the fill colour, else from the minion's armour
    orig0 = np.asarray(img)
    my_fill = "enemy" if team == "200" else "ally"  # find_bars colour name of Garen's team
    for fb in BF.find_bar_frames(orig0, exclude=HUD_BLANK + [SCOREBOARD_BLANK if sb else TIMELINE_BLANK]):
        if any(abs(fb.x - u["x"]) <= 8 and abs(fb.y - u["bar_y"]) <= 4 for u in own_m + foe_m): continue
        if any(abs(fb.y - c["bar_y"]) <= 7 and c["x0"] - 30 <= fb.x <= c["x0"] + CHAMP_W + 6 for c in own_ch + foe_ch): continue
        side_fill = fb.team if fb.team != "unknown" else body_team(orig0, fb.x, fb.y)
        u = {"x": fb.x, "y": fb.y + 50, "bar_y": fb.y, "hp_frac": fb.frac, "bordered": True, "src": "frame", "fill_team": fb.team}
        if side_fill == "unknown": continue
        (own_m if side_fill == my_fill else foe_m).append(u)
    # bar classifier (trained on 520 reviewed crops, 4 games): score every minion candidate on the ORIGINAL frame
    gp = None
    if own_ch:
        c = min(own_ch, key=lambda c: dist((c["x"], c["bar_y"]), CENTRE)); gp = (c["x"], c["y"])
    orig = np.asarray(img)
    for side, lst in (("own", own_m), ("foe", foe_m)):
        for u in lst:
            sib = sum(1 for v in lst if v is not u and abs(v["bar_y"] - u["bar_y"]) <= 8 and abs(v["x"] - u["x"]) <= 140)
            ctx = {"hp_frac": u["hp_frac"], "bordered": u["bordered"], "siblings": sib, "dist_garen": round(dist(gp, (u["x"], u["y"]))) if gp else 9999,
                   "hud_edge": min(u["x"], 1920 - u["x"], u["bar_y"], 1200 - u["bar_y"]), "colour": "unknown" if u.get("src") == "frame" else side}
            u["clf"] = round(BAR_CLF.score(orig, u["x"], u["bar_y"], ctx), 3)
    cam = L.get("camera") or {}
    return {"t": t, "state": {"hp": p["hp"], "hp_max": p["hp_max"], "hp_bar": p["hp_bar"], "garen_bar_frac": None,
                              "cs": cs, "kda": kda, "ad": p["ad"], "as": p["as"], "ms": p["ms"], "armor": p["armor"],
                              "level": L.get("level"), "items": L.get("items"), "dead": L.get("dead"),
                              "world_pos": [cam.get("x"), cam.get("z")] if cam else None, "screen_pos": None,
                              "spells": {k: {"rank": p["rank_" + k], "ready": p["ready_" + k], "ready_in_s": p["cd_" + k]} for k in "QWER"}},
            "decision": {"choice": "unknown", "zones": {"standing_in": []}}, "inputs": [], "world": {"units": []}, "events": [],
            "_raw": {"own_m": own_m, "foe_m": foe_m, "own_ch": own_ch, "foe_ch": foe_ch}}

def finalize(rows):
    """Pick Garen per frame among his team's champion bars: level digit matching his level (template learnt on frames with one
    candidate near the centre) + continuity with his last position; carry his position up to 1 s when his bar is hidden (banner,
    effects). Then drop false minions on his body / name label and build world.units with distances."""
    own = lambda r: r["_raw"]["own_ch"]
    tmpl = {}
    for r in rows:  # level templates from unambiguous frames
        cands = [c for c in own(r) if dist((c["x"], c["bar_y"]), CENTRE) < 140]
        if len(cands) == 1 and len(own(r)) <= 2 and r["state"]["level"]:
            tmpl.setdefault(r["state"]["level"], []).append(np.array(cands[0]["lv"]))
    tmpl = {lv: np.mean(v, axis=0) for lv, v in tmpl.items()}
    prev, prev_t = None, None
    for r in rows:
        lv = r["state"]["level"]; best, score = None, -1e9
        for c in own(r):
            s = 0.0
            if lv in tmpl: s += 2.0 * float(np.dot(tmpl[lv], np.array(c["lv"])) / len(c["lv"]))
            if prev is not None: s -= dist((c["x"], c["bar_y"]), prev) / 120.0
            else: s -= dist((c["x"], c["bar_y"]), CENTRE) / 300.0
            if s > score: best, score = c, s
        if best is not None and prev is not None and dist((best["x"], best["bar_y"]), prev) > 220 and score < 0.8:
            best = None  # an implausible jump with a weak digit match: not Garen
        g = None
        if best is not None:
            g = best; prev, prev_t = (best["x"], best["bar_y"]), r["t"]
            r["state"]["garen_bar_frac"] = best["hp_frac"]
        elif prev is not None and r["t"] - prev_t <= 3.0:  # kill banners / effects hide his bar for up to ~3 s; the camera keeps him in place
            g = {"x": prev[0], "y": prev[1] + 125, "bar_y": prev[1], "x0": prev[0] - CHAMP_W // 2, "carried": True}
        gp = (g["x"], g["y"]) if g else None
        r["state"]["screen_pos"] = list(gp) if gp else None
        if g and g.get("carried"): r["state"]["screen_pos_carried"] = True
        r["_garen"], r["_best"] = g, best
    minions = {k: track_minions(rows, k) for k in ("own_m", "foe_m")}
    for i, r in enumerate(rows):
        g, best = r.pop("_garen"), r.pop("_best"); gp = (g["x"], g["y"]) if g else None
        units = []
        others = [c for c in own(r) if c is not best]
        for kind, lst in (("ally_minion", minions["own_m"][i]), ("enemy_minion", minions["foe_m"][i]), ("ally_champion", others), ("enemy_champion", r["_raw"]["foe_ch"])):
            for u in lst:
                d = round(dist(gp, (u["x"], u["y"]))) if gp else None
                un = {"kind": kind, "hp_frac": u["hp_frac"], "x": round(u["x"] / 1920, 4), "y": round(u["y"] / 1200, 4), "px": [u["x"], u["y"]],
                      "dist_px": d, "in_attack_range": (d is not None and d <= 210)}
                if "id" in u: un["id"] = u["id"]
                if u.get("carried"): un["carried"] = True
                units.append(un)
        r["world"]["units"] = units

def clean_bars(bs):
    """Drop non-minion 'bars' (round 4, from the fresh-set misses): turret crystals give TWIN detections (same x +-6, 3-8 px apart
    vertically), a real minion bar gives one; spell areas (Rengar R) give dense clusters of tiny low-fill pieces."""
    twin = set()
    for i, a in enumerate(bs):
        for j, b in enumerate(bs):
            if i < j and abs(a["x"] - b["x"]) <= 6 and 3 <= abs(a["bar_y"] - b["bar_y"]) <= 8:
                twin.update((i, j))
    keep = [u for i, u in enumerate(bs) if i not in twin]
    out = []
    for u in keep:
        near = [v for v in keep if abs(v["x"] - u["x"]) <= 60 and abs(v["bar_y"] - u["bar_y"]) <= 60]
        if len(near) >= 4 and all(v["hp_frac"] <= 0.2 for v in near): continue
        out.append(u)
    return out

def track_minions(rows, key, keep_s=0.6):
    """Minion bars the bar classifier accepts (score > 0) -> stable ids (shared IdTracker). One-frame tracks are dropped; frames where a
    live track was missed (<= keep_s) are filled with its last state (carried)."""
    tr = IdTracker(keep_s=keep_s)
    for r in rows:
        bs = [SimpleNamespace(x=u["x"], y=u["bar_y"], body=(u["x"], u["y"]), frac=u["hp_frac"], kind="minion", kill_mark=0.0)
              for u in r["_raw"][key] if u.get("clf", -1) > 0]
        tr.update(r["t"], bs)
    out = [[] for _ in rows]
    by_t = {round(r["t"], 3): r for r in rows}
    for trk in tr.tracks:
        ts = [s[0] for s in trk.samples]
        if len(ts) < 2: continue  # one frame: noise
        si = 0
        for i, r in enumerate(rows):
            t = r["t"]
            if t < ts[0] - 1e-6 or t > ts[-1] + 1e-6: continue
            while si + 1 < len(ts) and ts[si + 1] <= t + 1e-6: si += 1
            tt, f, km, x, y = trk.samples[si]
            carried = abs(tt - t) > 1e-6
            if carried and t - tt > keep_s: continue
            out[i].append({"x": x, "y": y, "hp_frac": f, "id": trk.id, "carried": carried})
    return out

def worker(args):
    gdir, video, f0, f1, step, fps, t_frame0, t_start, t_end, team, logs = args
    own_c, foe_c = ("enemy", "ally") if team == "200" else ("ally", "enemy")
    cap = cv2.VideoCapture(os.path.join(gdir, video)); cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    rows, li = [], 0
    for idx in range(f0, f1):
        ok, fr = cap.read()
        if not ok: break
        if idx % step: continue
        t = round(t_frame0 + idx / fps, 2)
        if t < t_start or t > t_end: continue
        while li + 1 < len(logs) and logs[li + 1]["t"] <= t: li += 1
        rows.append(frame_row(Image.fromarray(fr[:, :, ::-1]), t, logs[li], team, own_c, foe_c))
    return rows

def clean_cs(rows):
    """Scoreboard CS: only goes up, by small steps. A higher reading is taken when the next 2 readings confirm it (>= it);
    lower readings and isolated jumps are OCR misreads. Raw value kept as cs_raw."""
    raw = [r["state"]["cs"] for r in rows]; cur = None
    for i, r in enumerate(rows):
        c = raw[i]; nxt = [x for x in raw[i + 1:i + 8] if x is not None][:2]
        if c is not None and (cur is None or (cur < c <= cur + 4)) and len(nxt) == 2 and all(x >= c for x in nxt) and all(x <= c + 4 for x in nxt):
            cur = c
        r["state"]["cs_raw"] = c; r["state"]["cs"] = cur

def add_events(rows, team, ev, my_name):
    last = {"cs": None, "level": None, "items": None, "cam": None}
    for i, r in enumerate(rows):
        r["turn"] = i; s = r["state"]; e = r["events"]
        if s["cs"] is not None and last["cs"] is not None and s["cs"] > last["cs"]: e.append({"kind": "last_hit", "n": s["cs"] - last["cs"]})
        if s["level"] and last["level"] and s["level"] > last["level"]: e.append({"kind": "level_up", "level": s["level"]})
        if s["items"] is not None and last["items"] is not None and sorted(s["items"]) != sorted(last["items"]): e.append({"kind": "items_changed", "items": s["items"]})
        wp = s["world_pos"]
        if wp and last["cam"] and dist(wp, FOUNTAIN[team]) < 1500 and dist(last["cam"], FOUNTAIN[team]) > 4000: e.append({"kind": "recall_or_respawn"})
        t0 = rows[i - 1]["t"] if i else r["t"] - 0.2
        for x in ev:
            if x.get("EventName") == "ChampionKill" and t0 < x.get("EventTime", -99) <= r["t"]:
                if x.get("KillerName") == my_name: e.append({"kind": "champion_kill"})
                if x.get("VictimName") == my_name: e.append({"kind": "death"})
                if my_name in x.get("Assisters", []): e.append({"kind": "assist"})
        if s["cs"] is not None and (last["cs"] is None or s["cs"] >= last["cs"]): last["cs"] = s["cs"]  # CS only goes up: ignore a lower misread
        last["level"] = s["level"] or last["level"]; last["items"] = s["items"] if s["items"] is not None else last["items"]; last["cam"] = wp or last["cam"]

def main(gdir, hz=5.0, limit=None, procs=8):
    from multiprocessing import Pool
    meta = json.load(open(glob.glob(os.path.join(gdir, "meta_*.json"))[0]))
    team = meta["team"]
    logs = [json.loads(l) for l in open(os.path.join(gdir, meta["log"]))]
    evp = os.path.join(gdir, meta["video"].replace("video_", "events_").replace(".mkv", ".json"))
    ev = json.load(open(evp)).get("Events", []) if os.path.exists(evp) else []
    players = json.load(open(os.path.join(gdir, "players_start.json")))
    me = next(p for p in players if p.get("championName") == "Garen"); my_name = me.get("riotIdGameName") or me.get("summonerName")
    cap = cv2.VideoCapture(os.path.join(gdir, meta["video"])); fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int((meta["t_end"] - meta["t_start"] + 20) * fps)
    t_frame0 = align(cap, n, fps); cap.release()
    step = max(1, round(fps / hz))
    if limit: n = min(n, limit * step + int(fps * 10))
    chunk = (n + procs - 1) // procs
    jobs = [(gdir, meta["video"], k * chunk, min(n, (k + 1) * chunk), step, fps, t_frame0, meta["t_start"], meta["t_end"], team, logs) for k in range(procs)]
    with Pool(procs) as pool:
        rows = [r for part in pool.map(worker, jobs) for r in part]
    rows.sort(key=lambda r: r["t"])
    if limit: rows = rows[:limit]
    with open(os.path.join(gdir, "raw_rows.jsonl"), "w") as f:  # cache: finalize() can be re-run without decoding the video
        for r in rows: f.write(json.dumps(r) + "\n")
    post(gdir, rows, team, ev, my_name)
    print(gdir, len(rows), "rows; frame0 game time", round(t_frame0, 2))

def _jpg_worker(args):
    gdir, chunk, team = args
    own_c, foe_c = ("enemy", "ally") if team == "200" else ("ally", "enemy")
    return [frame_row(Image.open(os.path.join(gdir, r["file"])).convert("RGB"), r["t"], r, team, own_c, foe_c) for r in chunk]

def main_jpg(gdir, procs=8):
    """Same extraction on a JPEG-sequence capture (lasthit_block.py: rows.json with the game time and Live Client Data per frame)."""
    from multiprocessing import Pool
    import shutil
    meta = json.load(open(os.path.join(gdir, "rows.json"))); team = meta["team"]
    rows_in = [r for r in meta["rows"] if os.path.exists(os.path.join(gdir, r["file"]))]
    json.dump({"gid": meta["gid"], "team": team, "t_start": rows_in[0]["t"], "t_end": rows_in[-1]["t"], "video": "video_jpg.mkv", "log": "rows.json",
               "source": "jpeg sequence, 2 Hz game time, 2x playback, no scoreboard"}, open(os.path.join(gdir, "meta_jpg.json"), "w"))
    if os.path.exists(os.path.join(gdir, "events.json")): shutil.copy(os.path.join(gdir, "events.json"), os.path.join(gdir, "events_jpg.json"))
    chunks = [rows_in[k::procs] for k in range(procs)]
    with Pool(procs) as pool:
        rows = [r for part in pool.map(_jpg_worker, [(gdir, c, team) for c in chunks]) for r in part]
    rows.sort(key=lambda r: r["t"])
    with open(os.path.join(gdir, "raw_rows.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    refinalize(gdir)
    print(gdir, len(rows), "rows (jpeg sequence)")

def post(gdir, rows, team, ev, my_name):
    finalize(rows)
    for r in rows: r.pop("_raw", None)
    clean_hp(rows); clean_cs(rows); add_events(rows, team, ev, my_name); smooth_ranks(rows); write(gdir, rows)

def clean_hp(rows):
    """HP from the panel text as read (max HP changes with runes and items between level-ups, so it is not smoothed). An impossible
    reading (current > max, or none) falls back to Garen's own bar fill x the last valid max."""
    last_max = None
    for r in rows:
        s = r["state"]
        if s["hp_max"] and (last_max is None or abs(s["hp_max"] - last_max) <= 400): last_max = s["hp_max"]
        else: s["hp_max_raw"], s["hp_max"] = s["hp_max"], last_max  # unreadable text (low-quality JPEG): carry the last max
        if s["hp_max"] and (s["hp"] is None or s["hp"] > s["hp_max"]):
            s["hp_raw"] = s["hp"]; f = s.get("garen_bar_frac") or s.get("hp_bar")
            s["hp"] = round(f * s["hp_max"]) if f is not None else None

def smooth_ranks(rows):
    """Ability ranks: the most common reading per level segment, then forced monotone with Q+W+E+R == level."""
    from collections import Counter
    by = {}
    for r in rows:
        lv = r["state"]["level"]
        if lv: by.setdefault(lv, []).append(r)
    prev = {k: 0 for k in "QWER"}
    for lv in sorted(by):
        seg = by[lv]
        mode = {k: Counter(x["state"]["spells"][k]["rank"] for x in seg if x["state"]["spells"][k]["rank"] is not None).most_common(1) for k in "QWER"}
        rk = {k: max(prev[k], mode[k][0][0] if mode[k] else prev[k]) for k in "QWER"}
        while sum(rk.values()) > lv:  # too many points: drop from the one that grew most recently vs prev
            k = max("QWER", key=lambda k: rk[k] - prev[k]); rk[k] -= 1
        while sum(rk.values()) < lv:  # a missed point: give it to the ability whose reading was most often above its current rank
            k = max("QWER", key=lambda k: sum(1 for x in seg if (x["state"]["spells"][k]["rank"] or 0) > rk[k])); rk[k] += 1
        for x in seg:
            for k in "QWER":
                x["state"]["spells"][k]["rank_raw"] = x["state"]["spells"][k]["rank"]; x["state"]["spells"][k]["rank"] = rk[k]
        prev = rk

def write(gdir, rows):
    with open(os.path.join(gdir, "turns.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")

def redo_cs(gdir):
    """Re-read Garen's scoreboard CS on an existing turns.jsonl (sequential decode), then clean + events again."""
    meta = json.load(open(glob.glob(os.path.join(gdir, "meta_*.json"))[0])); team = meta["team"]
    rows = [json.loads(l) for l in open(os.path.join(gdir, "turns.jsonl"))]
    cap = cv2.VideoCapture(os.path.join(gdir, meta["video"])); fps = cap.get(cv2.CAP_PROP_FPS)
    t_frame0 = align(cap, 10 ** 6, fps); cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    want = {round((r["t"] - t_frame0) * fps): r for r in rows}; idx = -1; last = max(want)
    while idx < last:
        ok, fr = cap.read(); idx += 1
        if not ok: break
        r = want.get(idx)
        if r: r["state"]["cs"] = hud.sb_cs_digits(Image.fromarray(fr[:, :, ::-1]), team, 0)
    for r in rows: r["events"] = [e for e in r["events"] if e["kind"] not in ("last_hit", "level_up", "items_changed", "recall_or_respawn", "champion_kill", "death", "assist")]
    evp = os.path.join(gdir, meta["video"].replace("video_", "events_").replace(".mkv", ".json"))
    ev = json.load(open(evp)).get("Events", []) if os.path.exists(evp) else []
    me = next(p for p in json.load(open(os.path.join(gdir, "players_start.json"))) if p.get("championName") == "Garen")
    clean_cs(rows); add_events(rows, team, ev, me.get("riotIdGameName") or me.get("summonerName")); write(gdir, rows)

def refinalize(gdir):
    """Re-run the post-processing from raw_rows.jsonl (no video decode)."""
    meta = json.load(open(glob.glob(os.path.join(gdir, "meta_*.json"))[0]))
    rows = [json.loads(l) for l in open(os.path.join(gdir, "raw_rows.jsonl"))]
    evp = os.path.join(gdir, meta["video"].replace("video_", "events_").replace(".mkv", ".json"))
    ev = json.load(open(evp)).get("Events", []) if os.path.exists(evp) else []
    me = next(p for p in json.load(open(os.path.join(gdir, "players_start.json"))) if p.get("championName") == "Garen")
    post(gdir, rows, meta["team"], ev, me.get("riotIdGameName") or me.get("summonerName"))

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--refinalize" in a: refinalize(a[0]); sys.exit(0)
    if "--redo-cs" in a: redo_cs(a[0]); sys.exit(0)
    if "--jpg" in a: main_jpg(a[0]); sys.exit(0)
    main(a[0], float(a[a.index("--hz") + 1]) if "--hz" in a else 5.0, int(a[a.index("--limit") + 1]) if "--limit" in a else None)
