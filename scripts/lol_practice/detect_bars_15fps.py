#!/usr/bin/env python3
"""Minion bar detection on every frame of a replay capture (15 fps) -> JSON lines for lol_dataset.

    python3 scripts/lol_practice/detect_bars_15fps.py <video.mkv> <out.jsonl> --frame0 52.533 [--procs 3] [--t0 60 --t1 480]

Per frame: find_bars (team-coloured bars) and the frame detector (bar_frames: dark frame, dim or empty bars), the
HUD areas masked as in elite_video_extract, duplicates merged, and the bar classifier v2 (minion vs not) scored on the
original frame. A unit is kept when the classifier says minion (score > 0). Each unit:
  {"fill": "ally"|"enemy" (fill colour), "px": [centre x, bar y], "w": frame width or null (find_bars gives none),
   "h": frame height or null, "hp_frac": 0-1, "src": "find_bars"|"frame", "clf": score}
Run it on the Mac with nice; the classifier and detector come from the repo (elite_hud/, shared perception).
"""
import argparse
import json
import os
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FPS = 15.0


def _init():
    global EV, BF
    import elite_video_extract as EV  # the HUD masks, bars() and the classifier, as used for the 5 Hz turns.jsonl
    from shared.src.lib.game.leagueoflegends import bar_frames as BF


def _frame_units(img_rgb):
    """Minion units of one RGB frame (see module docstring)."""
    a = np.array(img_rgb)
    sb = EV.scoreboard_on(a)
    for x0, y0, x1, y1 in EV.HUD_BLANK + [EV.SCOREBOARD_BLANK if sb else EV.TIMELINE_BLANK]:
        a[y0:y1, x0:x1] = 90
    units = []
    # team-coloured bars, both colours
    found = {}
    for colour in ("ally", "enemy"):
        ms, _champs = EV.bars(a, colour)
        for m in ms:
            found.setdefault(colour, []).append(m)
            units.append({"fill": colour, "px": [m["x"], m["bar_y"]], "w": None, "h": None,
                          "hp_frac": m["hp_frac"], "src": "find_bars", "_bordered": m.get("bordered")})
    # frame detector: dark frame bars, including dim and empty ones
    orig = np.asarray(img_rgb)
    for fb in BF.find_bar_frames_ex(orig, exclude=EV.HUD_BLANK + [EV.SCOREBOARD_BLANK if sb else EV.TIMELINE_BLANK]):
        bar = fb["bar"]
        if any(abs(bar.x - u["px"][0]) <= 8 and abs(bar.y - u["px"][1]) <= 4 for u in units):
            continue
        fx0, fy0, fx1, fy1 = fb["frame"]
        side = bar.team if getattr(bar, "team", "unknown") != "unknown" else EV.body_team(orig, bar.x, bar.y)
        if side not in ("ally", "enemy"):
            continue
        units.append({"fill": side, "px": [bar.x, bar.y], "w": fx1 - fx0, "h": fy1 - fy0,
                      "hp_frac": bar.frac, "src": "frame", "_bordered": True})
    # classifier v2: minion vs not, on the original frame
    kept = []
    for u in units:
        sib = sum(1 for v in units if v is not u and abs(v["px"][1] - u["px"][1]) <= 8 and abs(v["px"][0] - u["px"][0]) <= 140)
        ctx = {"hp_frac": u["hp_frac"], "bordered": u["_bordered"], "siblings": sib, "dist_garen": 9999,
               "hud_edge": min(u["px"][0], 1920 - u["px"][0], u["px"][1], 1200 - u["px"][1]),
               "colour": "unknown" if u["src"] == "frame" else u["fill"]}
        u["clf"] = round(EV.BAR_CLF.score(orig, u["px"][0], u["px"][1], ctx), 3)
        del u["_bordered"]
        if u["clf"] > 0:
            u["hp_frac"] = round(float(u["hp_frac"]), 4)
            kept.append(u)
    return kept


def frame_times(video):
    """Presentation time (s, from the container) of every decoded frame, in decode order. Drops and stalls are real gaps:
    frame i is not at i / fps."""
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                          "-of", "csv=p=0", video], capture_output=True, text=True, check=True).stdout
    return [float(x.strip().rstrip(",")) for x in out.splitlines() if x.strip().rstrip(",")]


def _work(args):
    """Decode with ffmpeg (raw bgr24 pipe): OpenCV's reader drops frames on this recording. Frame i takes pts[i]."""
    import subprocess
    video, start, count, frame0, out_part, fps, pts = args
    W, H = 1920, 1200
    t_start = pts[start] if start < len(pts) else start / fps
    # passthrough: every real frame, the recorder's drops stay as gaps (no forced cfr duplicates); -copyts keeps real times
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t_start:.6f}", "-i", video, "-copyts",
           "-fps_mode", "passthrough", "-frames:v", str(count), "-map", "0:v:0",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    fs = W * H * 3
    n = 0
    with open(out_part, "w", encoding="utf-8") as f:
        for k in range(count):
            buf = proc.stdout.read(fs)
            if len(buf) < fs:
                break
            fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            idx = start + k
            t = round(frame0 + (pts[idx] if idx < len(pts) else idx / fps), 3)
            units = _frame_units(Image.fromarray(fr[:, :, ::-1]))
            f.write(json.dumps({"t": t, "frame": idx, "units": units}) + "\n")
            n += 1
    proc.wait()
    if n != count:  # hard check: a short read fails loudly, never a silent half-video
        raise RuntimeError(f"frame reader short: got {n} of {count} frames from index {start} (rc {proc.returncode})")
    return out_part, n


def fps_of(video):
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    cap.release()
    return fps


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--frame0", type=float, required=True, help="game time of frame 0 (lol_dataset meta)")
    p.add_argument("--t0", type=float, default=60.0)
    p.add_argument("--t1", type=float, default=480.0)
    p.add_argument("--procs", type=int, default=3)
    a = p.parse_args(argv)
    cap = cv2.VideoCapture(a.video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int(420 * FPS)
    cap.release()
    fps = fps_of(a.video)
    pts = frame_times(a.video)
    total = len(pts)
    first = max(0, next((i for i, x in enumerate(pts) if a.frame0 + x >= a.t0 - 1e-6), total))
    last = min(total, next((i for i, x in enumerate(pts) if a.frame0 + x > a.t1 + 1e-6), total))
    chunk = (last - first + a.procs - 1) // a.procs
    jobs = [(a.video, first + k * chunk, min(chunk, last - (first + k * chunk)), a.frame0,
             f"{a.out}.part{k}", fps, pts) for k in range(a.procs) if first + k * chunk < last]
    with Pool(len(jobs), initializer=_init) as pool:
        done = pool.map(_work, jobs)
    with open(a.out, "w", encoding="utf-8") as out:
        for part, n in done:
            with open(part, encoding="utf-8") as f:
                out.write(f.read())
            os.remove(part)
    print(f"{a.out}: frames {sum(n for _, n in done)}")


if __name__ == "__main__":
    main()
