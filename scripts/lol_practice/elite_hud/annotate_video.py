"""Hand-check sheets for a video-extracted game: python3 annotate_video.py <game_dir> <n> <seed> [out_dir]
Draws Garen (yellow), ally minions (green), enemy minions (magenta), champions (cyan) with HP %, and the readouts."""
import glob, json, os, random, sys
import cv2
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hud
g = sys.argv[1]; n = int(sys.argv[2]); random.seed(int(sys.argv[3])); out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(g, "check")
os.makedirs(out, exist_ok=True)
meta = json.load(open(glob.glob(os.path.join(g, "meta_*.json"))[0]))
rows = [json.loads(l) for l in open(os.path.join(g, "turns.jsonl"))]
JPG = meta.get("log") == "rows.json"  # jpeg-sequence capture
if JPG:
    files = {round(r["t"], 2): r["file"] for r in json.load(open(os.path.join(g, "rows.json")))["rows"]}
else:
    cap = cv2.VideoCapture(os.path.join(g, meta["video"])); fps = cap.get(cv2.CAP_PROP_FPS)
    prev = None; t0 = None  # same alignment as the extractor: clock tick
    for idx in range(int(fps * 6)):
        ok, fr = cap.read(); c = hud.clock(Image.fromarray(fr[:, :, ::-1]))
        if prev is not None and c is not None and c == prev + 1: t0 = c - idx / fps; break
        prev = c if c is not None else prev
font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
COL = {"ally_minion": (0, 255, 0), "enemy_minion": (255, 0, 255), "ally_champion": (0, 255, 255), "enemy_champion": (0, 200, 255)}
excl = set()  # never draw a frame already used: any earlier gate / tuning sheet, any frame that supplied a labelled training crop
if os.environ.get("EXCLUDE_USED"):
    import glob as _g
    gid = str(meta["gid"])
    for sh in _g.glob(os.path.expanduser("~/vpt-deliverables/lol-elite/validation/**/sheet.json"), recursive=True):
        excl.update(round(s["t"], 1) for s in json.load(open(sh)))
    for lab in _g.glob(os.path.expanduser("~/vpt-deliverables/lol-elite/bar_labels*/candidates.jsonl")):
        excl.update(round(json.loads(l)["t"], 1) for l in open(lab) if json.loads(l)["game"] == gid)
pool = [r for r in rows if round(r["t"], 1) not in excl]
pick = sorted(random.sample(pool, n), key=lambda r: r["t"]) if n < len(pool) else pool
sheet = []
for i, r in enumerate(pick):
    if JPG:
        im = Image.open(os.path.join(g, files[round(r["t"], 2)])).convert("RGB")
    else:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round((r["t"] - t0) * fps)); ok, fr = cap.read(); im = Image.fromarray(fr[:, :, ::-1]).convert("RGB")
    d = ImageDraw.Draw(im); s = r["state"]
    for u in r["world"]["units"]:
        x, y = u["px"]; c = COL[u["kind"]]
        bw = 53 if "champion" in u["kind"] else 31; by = y - (125 if "champion" in u["kind"] else 50)
        d.rectangle([x - bw, by - 6, x + bw, by + 6], outline=c, width=3); d.text((x - 22, by - 30), f"{int(u['hp_frac'] * 100)}%", fill=c, font=font)
    if s["screen_pos"]:
        x, y = s["screen_pos"]; d.ellipse([x - 14, y - 14, x + 14, y + 14], outline=(255, 255, 0), width=4); d.text((x + 18, y - 10), "GAREN", fill=(255, 255, 0), font=font)
    sp = s["spells"]
    txt1 = (f"#{i} t={r['t']:.2f}  CS={s['cs']}  KDA={s['kda']}  HP={s['hp']}/{s['hp_max']}  lvl={s['level']}  AD={s['ad']} AS={s['as']} MS={s['ms']} AR={s['armor']}  "
            f"ranks QWER={''.join(str(sp[k]['rank']) for k in 'QWER')}  ready={''.join('1' if sp[k]['ready'] else '0' for k in 'QWER')}  "
            f"cd={[sp[k]['ready_in_s'] for k in 'QWER']}")
    nm = {k: sum(1 for u in r["world"]["units"] if u["kind"] == k) for k in COL}
    txt2 = f"units: ally_min={nm['ally_minion']} enemy_min={nm['enemy_minion']} ally_ch={nm['ally_champion']} enemy_ch={nm['enemy_champion']}  world_pos={s['world_pos'] and [round(v) for v in s['world_pos']]}  events={[e['kind'] for e in r['events']]}"
    d.rectangle([0, 1130, 1920, 1200], fill=(0, 0, 0)); d.text((8, 1136), txt1, fill=(255, 255, 255), font=font); d.text((8, 1166), txt2, fill=(255, 255, 255), font=font)
    im.save(os.path.join(out, f"{i:02d}.jpg"), quality=90)
    sheet.append({"i": i, "t": r["t"], "turn": r["turn"]})
json.dump(sheet, open(os.path.join(out, "sheet.json"), "w"), indent=1)
print("wrote", len(sheet), "excluded", len(excl))
