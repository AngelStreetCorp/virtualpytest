#!/usr/bin/env python3
"""Frame-detector candidates that find_bars does NOT give (dim / empty bars and new false types), for labelling.
python3 elite_frame_candidates.py <out_dir> <n_per_game> <game_dir> ...   (frames used by any gate or label set are excluded)"""
import glob, json, math, os, random, sys
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
from PIL import Image, ImageDraw
from shared.src.lib.game.leagueoflegends import bar_frames as BF, perception as P
import elite_video_extract as E

def used_times():
    ts = set()
    for sh in glob.glob(os.path.expanduser("~/vpt-deliverables/lol-elite/validation/**/sheet.json"), recursive=True):
        ts.update(round(s["t"], 1) for s in json.load(open(sh)))
    for f in glob.glob(os.path.expanduser("~/vpt-deliverables/lol-elite/bar_labels*/candidates.jsonl")):
        ts.update(round(json.loads(l)["t"], 1) for l in open(f))
    return ts

def frames_of(gdir):
    meta = json.load(open(glob.glob(os.path.join(gdir, "meta_*.json"))[0]))
    if meta.get("log") == "rows.json":
        rows = json.load(open(os.path.join(gdir, "rows.json")))["rows"]
        return meta, [(r["t"], (lambda f=r["file"]: np.array(Image.open(os.path.join(gdir, f)).convert("RGB")))) for r in rows]
    cap = cv2.VideoCapture(os.path.join(gdir, meta["video"])); fps = cap.get(cv2.CAP_PROP_FPS); t0 = E.align(cap, 10 ** 6, fps)
    turns = [json.loads(l)["t"] for l in open(os.path.join(gdir, "turns.jsonl"))]
    def grab(t):
        cap.set(1, round((t - t0) * fps)); ok, fr = cap.read(); return fr[:, :, ::-1].copy()
    return meta, [(t, (lambda t=t: grab(t))) for t in turns]

def main(out, n, gdirs):
    os.makedirs(os.path.join(out, "crops"), exist_ok=True); random.seed(1020); used = used_times()
    f = open(os.path.join(out, "candidates.jsonl"), "a")
    for gdir in gdirs:
        meta, frames = frames_of(gdir); frames = [x for x in frames if round(x[0], 1) not in used]
        random.shuffle(frames); got = 0
        for t, load in frames:
            if got >= n: break
            a = load(); b = a.copy()
            sb = E.scoreboard_on(b)
            ex = E.HUD_BLANK + [E.SCOREBOARD_BLANK if sb else E.TIMELINE_BLANK]
            new = BF.find_bar_frames(a, exclude=ex)
            for x0, y0, x1, y1 in ex: b[y0:y1, x0:x1] = 90
            old = [u for c in ("enemy", "ally") for u in P.find_bars(b, c) if u.kind == "minion"]
            for bar in new:
                if any(abs(bar.x - u.x) <= 8 and abs(bar.y - u.y) <= 4 for u in old): continue
                im = Image.fromarray(a); x, y = bar.x, bar.y
                cid = f"{meta['gid']}_{t:07.2f}_{x}_{y}"
                im.crop((x - 36, y - 8, x + 36, y + 8)).save(os.path.join(out, "crops", cid + "_bar.png"))
                ctx = im.crop((x - 120, y - 70, x + 120, y + 90)).resize((480, 320), Image.LANCZOS)
                ImageDraw.Draw(ctx).rectangle([2 * 84, 2 * 62, 2 * 156, 2 * 78], outline=(0, 255, 255), width=2); ctx.save(os.path.join(out, "crops", cid + "_ctx.png"))
                f.write(json.dumps({"id": cid, "game": str(meta["gid"]), "t": t, "x": x, "bar_y": y, "hp_frac": bar.frac, "team_fill": bar.team,
                                    "bordered": True, "siblings": sum(1 for o in new if o is not bar and abs(o.y - y) <= 8 and abs(o.x - x) <= 140),
                                    "dist_garen": 9999, "hud_edge": min(x, 1920 - x, y, 1200 - y), "colour": "unknown", "source": "frame_only"}) + "\n")
                got += 1
        print(gdir, got)

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3:])
