"""Enemy champion identity from the name tag above each champion bar (30 fps, every 3rd frame).
Writes one JSON line per frame: {"n", "t", "bars": [{"x0","bar_y","colour","text","name","hp_frac"}]}.
Enemies (opposing team) are the bars of the colour find_bars calls "ally" when Garen is on the red team."""
import sys, os, json, subprocess, difflib
import numpy as np, cv2, pytesseract
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "elite_hud"))
import elite_video_extract as EV
VIDEO = os.path.expanduser("~/vpt-deliverables/lol-elite/video30/8018174981/video_60-480.mkv")
OUT = os.path.expanduser("~/vpt-deliverables/lol-elite/events/enemy_names30.jsonl")
FR0 = 52.633; W, H = 1920, 1200; STEP = 6
ENEMY_NAMES = ["Janna", "Viego", "Vladimir", "Yunara", "Thresh"]   # roster, ORDER team (opposing Garen)
def tag(img, x0, bar_y):
    c = img[max(0, bar_y - 32):bar_y - 12, max(0, x0 - 12):x0 + EV.CHAMP_W + 12]
    if c.size == 0: return ""
    c = cv2.resize(c, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(c, cv2.COLOR_RGB2GRAY)
    _, th = cv2.threshold(g, 170, 255, cv2.THRESH_BINARY)
    return pytesseract.image_to_string(th, config="--psm 7").strip()
def match(text):
    m = difflib.get_close_matches(text, ENEMY_NAMES, n=1, cutoff=0.6)
    return m[0] if m else None
T0, T1 = float(sys.argv[1]), float(sys.argv[2])          # game seconds of this chunk
pts = [float(x.strip().rstrip(",")) for x in open("/tmp/_pts30.txt") if x.strip().rstrip(",")]
n0 = next(i for i, x in enumerate(pts) if FR0 + x >= T0)   # first frame index of the chunk
cnt = sum(1 for x in pts if T0 <= FR0 + x < T1)
p = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{T0 - FR0:.3f}", "-i", VIDEO, "-frames:v", str(cnt), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
fs = W * H * 3; n = n0
with open(OUT, "a") as f:
    while True:
        buf = p.stdout.read(fs)
        if len(buf) < fs: break
        if n % STEP == 0:
            img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            t = round(FR0 + pts[n], 3)
            if T0 <= t < T1:
                bars = []
                for c in EV.champion_bars(img, "ally"):
                    text = tag(img, c["x0"], c["bar_y"])
                    bars.append({"x0": c["x0"], "bar_y": c["bar_y"], "colour": "ally", "text": text, "name": match(text)})
                f.write(json.dumps({"n": n, "t": t, "bars": bars}) + "\n")
        n += 1
print("chunk", T0, T1, "frames", n - n0, "expected", cnt, flush=True)
