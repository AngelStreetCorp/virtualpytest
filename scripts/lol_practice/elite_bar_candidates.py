#!/usr/bin/env python3
"""Dump minion-bar candidates for labelling (bar classifier). python3 elite_bar_candidates.py <out_dir> <n_per_game> <split>:<game_dir> ...
Candidates = every find_bars 'minion' run kept by bars() (both team colours), from frames NOT in any gate set. Oversamples the hard
cases (not bordered, near Garen, low fill, near another bar on the same row). Writes crops/<id>_ctx.png (labelling view),
crops/<id>_bar.png (model input) and candidates.jsonl (features + source)."""
import glob, json, math, os, random, sys
import cv2, numpy as np
from PIL import Image, ImageDraw

def frame_img(gdir, meta, t, t0=None, cap=None):
    if meta.get("log") == "rows.json":
        r = next(x for x in json.load(open(os.path.join(gdir, "rows.json")))["rows"] if abs(x["t"] - t) < 1e-3)
        return Image.open(os.path.join(gdir, r["file"])).convert("RGB")
    cap.set(cv2.CAP_PROP_POS_FRAMES, round((t - t0) * cap.get(cv2.CAP_PROP_FPS))); ok, fr = cap.read()
    return Image.fromarray(fr[:, :, ::-1])

def gate_times(gdir):
    ts = set()
    for sheet in glob.glob(os.path.expanduser("~/vpt-deliverables/lol-elite/validation/**/sheet.json"), recursive=True):
        ts.update(round(s["t"], 1) for s in json.load(open(sheet)))
    return ts  # times only: games differ in their own timelines but excluding a time in every game is harmless

def main(out, n, specs):
    os.makedirs(os.path.join(out, "crops"), exist_ok=True)
    gt = gate_times(None); random.seed(20261019)
    outf = open(os.path.join(out, "candidates.jsonl"), "a")
    for spec in specs:
        split, gdir = spec.split(":", 1)
        meta = json.load(open(glob.glob(os.path.join(gdir, "meta_*.json"))[0]))
        rows = [json.loads(l) for l in open(os.path.join(gdir, "raw_rows.jsonl"))]
        turns = {round(json.loads(l)["t"], 2): json.loads(l) for l in open(os.path.join(gdir, "turns.jsonl"))}
        cands = []
        for r in rows:
            if round(r["t"], 1) in gt: continue
            g = (turns.get(round(r["t"], 2)) or {}).get("state", {}).get("screen_pos")
            for side in ("own_m", "foe_m"):
                bs = r["_raw"][side]
                for u in bs:
                    sib = sum(1 for v in bs if v is not u and abs(v["bar_y"] - u["bar_y"]) <= 8 and abs(v["x"] - u["x"]) <= 140)
                    d = math.hypot(u["x"] - g[0], u["y"] - g[1]) if g else 9999
                    hard = (not u.get("bordered")) or d < 160 or u["hp_frac"] < 0.3 or sib > 0
                    cands.append({"t": r["t"], "side": side, "u": u, "sib": sib, "dist_garen": round(d), "hard": hard})
        hard = [c for c in cands if c["hard"]]; easy = [c for c in cands if not c["hard"]]
        pick = random.sample(hard, min(len(hard), int(n * 0.7))) + random.sample(easy, min(len(easy), n - int(n * 0.7)))
        cap = None if meta.get("log") == "rows.json" else cv2.VideoCapture(os.path.join(gdir, meta["video"]))
        t0 = None
        if cap is not None:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import elite_video_extract as E
            t0 = E.align(cap, 10 ** 6, cap.get(cv2.CAP_PROP_FPS))
        for c in sorted(pick, key=lambda c: c["t"]):
            img = frame_img(gdir, meta, c["t"], t0, cap); u = c["u"]; x, by = int(u["x"]), int(u["bar_y"])
            cid = f"{meta['gid']}_{c['t']:07.2f}_{c['side']}_{x}_{by}"
            bar = img.crop((x - 36, by - 8, x + 36, by + 8)); bar.save(os.path.join(out, "crops", cid + "_bar.png"))
            ctx = img.crop((x - 120, by - 70, x + 120, by + 90)).resize((480, 320), Image.LANCZOS)
            d = ImageDraw.Draw(ctx); d.rectangle([2 * 84, 2 * 62, 2 * 156, 2 * 78], outline=(0, 255, 255), width=2)
            ctx.save(os.path.join(out, "crops", cid + "_ctx.png"))
            rec = {"id": cid, "game": str(meta["gid"]), "split": split, "t": c["t"], "colour": "own" if c["side"] == "own_m" else "foe",
                   "team_colour": ("red" if (meta["team"] == "200") == (c["side"] == "own_m") else "blue"),
                   "x": x, "bar_y": by, "hp_frac": u["hp_frac"], "bordered": bool(u.get("bordered")), "siblings": c["sib"],
                   "dist_garen": c["dist_garen"], "hud_edge": min(x, 1920 - x, by, 1200 - by)}
            outf.write(json.dumps(rec) + "\n")
        print(spec, len(cands), "candidates,", len(pick), "picked")

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3:])
