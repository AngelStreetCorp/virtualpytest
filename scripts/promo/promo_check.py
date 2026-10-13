"""Quality gate for a built promo video: counters that must all read 0 before it is reviewed or uploaded.

  python3 promo_check.py <mp4> [--srt <srt>] [--allow <regex> ...] [--json]
  -> a counters table (and each hit with its time); exit 1 unless every counter is 0.

Counters
  banned_text       OCR (tesseract) of a frame every 0.5 s: error text (ERROR, failed, NO CAPTURE, 401,
                    still processing, No Image, with care), an IPv4 address or "ip=", FARM_KEY=<a key> (a masked
                    •••••• value passes), a login form, and every term of the private deny-list (operator/customer names: one per line, file named
                    by $PROMO_DENYLIST, default scripts/promo/.promo_denylist - gitignored, never commit names).
                    The same text on consecutive frames counts once; text under 8 px high is ignored (unreadable).
                    --allow <regex> drops a hit the video means to show (e.g. a deliberately failed test).
  black_frames      ffmpeg blackdetect, runs >= 0.5 s (the 0.35-0.6 s scene fades stay under it), plus OCR
                    "Loading stream" (a player that never drew).
  dark_tiles        >= 1 s where over 30 % of the page (below the header, above the caption band) is pure black:
                    stream tiles that are not playing yet (a layout switch, a page load). A light page with live
                    tiles sits near 15 % (letterboxing), black tiles near 40 %. --allow-dark <t0>-<t1> (seconds)
                    waives a run the video means to show (video 13's black-screen incident).
  flashes           runs of 1-4 frames whose page header differs from the frames around them (the outlier
                    test of frames_to_mp4.py, here on the finished video).
  caption_overflow  SRT lines wider than the caption box (Inter Bold at the build size, build.CAPTION_MAX_W).
  duration_over_90s the video is longer than 90 s.
  voice_mismatch    the audio track (if any) is more than 1 s shorter or longer than the picture (decoded length,
                    not the container's: 25a's container said 67.6 s while its audio decoded to 81.6 s).
  voice_silent      a voice line with no speech in the audio: voiceover.py writes <voiced>.voice.json (every line's
                    start, length, text); each line's loudest 0.5 s must reach -45 dBFS. A voiced take
                    (<name>_voice-<voice>.mp4) without that map counts as one hit. 25a/25b shipped lines that
                    ffmpeg's amix had dropped while every other counter read 0.
The SRT defaults to the one next to the mp4 (a voiced take <name>_voice-<voice>.mp4 uses <name>.srt).
Each banned_text hit prints its box (video pixels). --blur-to <out.mp4> writes a copy with those boxes blurred:
the fix for a take that cannot be re-recorded (the capture scrub, promo_lib scrubSecrets, is the first defence).
youtube_upload.py runs this before every upload.
"""
import argparse
import array
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import ImageFont

from build import FONT_BOLD, CAPTION_SIZE, CAPTION_MAX_W
from frames_to_mp4 import flash_runs

HERE = Path(__file__).resolve().parent
OCR_STEP = 0.5
MIN_TEXT_H = 8   # px: smaller text is unreadable on screen, so not a banned_text finding
MAX_DURATION = 90.0
IPV4 = r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
BANNED = [r"\bERROR\b", r"\bfailed\b(?!\s*[=:]\s*0\b)", r"NO CAPTURE", r"\b401\b", r"still processing", r"No Image", r"with care",
          r"\bip\s*=\s*\d", IPV4, r"FARM_KEY\s*=\s*[A-Za-z0-9_-]{8,}", r"\bSign in\b", r"\bLog in\b", r"Forgot (your )?password", r"\bPassword\b"]
LOADING = r"Loading stream"


def denylist():
    p = Path(os.environ.get("PROMO_DENYLIST") or HERE / ".promo_denylist")
    if not p.exists():
        return []
    terms = [t.strip() for t in p.read_text().splitlines() if t.strip() and not t.startswith("#")]
    return [r"\b" + re.escape(t) + r"\b" for t in terms]


def probe(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
                        "-of", "json", str(mp4)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    fmt = float(d["format"]["duration"])
    st = {s["codec_type"]: float(s.get("duration") or fmt) for s in d["streams"]}
    return st.get("video", fmt), st.get("audio")


def audio_pcm(mp4, rate=16000):
    """The decoded audio as mono 16-bit samples (None when there is no audio track)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-map", "0:a:0", "-ac", "1", "-ar", str(rate),
                        "-f", "s16le", "-"], capture_output=True)
    return array.array("h", r.stdout) if r.returncode == 0 and r.stdout else None


def voice_map(mp4):
    p = Path(str(mp4) + ".voice.json")
    return json.loads(p.read_text()) if p.exists() else None


def silent_lines(pcm, lines, rate=16000, floor_db=-45.0):
    """[(at, text, loudest dBFS)] for every voice line whose loudest 0.5 s window stays under floor_db."""
    out, win = [], rate // 2
    for ln in lines:
        a, b = int((ln["at"] + 0.1) * rate), int((ln["at"] + ln["dur"] - 0.1) * rate)
        best = -120.0
        for i in range(a, max(a + 1, b - win), win // 2):
            seg = pcm[i:i + win]
            if seg:
                best = max(best, 20 * math.log10(math.sqrt(sum(x * x for x in seg) / len(seg)) / 32768 + 1e-9))
        if best < floor_db:
            out.append((ln["at"], ln["text"], best))
    return out


def ocr_frames(mp4, tmp):
    """[(t, text, words)] per OCR frame; words = [(start, end, (x, y, w, h))] offsets into text, video pixels."""
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"fps=1/{OCR_STEP}", str(Path(tmp) / "%05d.png")],
                   check=True)
    files = sorted(Path(tmp).glob("*.png"))
    # one thread per tesseract: we already run several in parallel, and its own OpenMP threads on top of that
    # overloaded a busy 6-core box (codebox, load 19: ~60 s per frame instead of ~1 s)
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    run = lambda f: subprocess.run(["tesseract", str(f), "stdout", "--psm", "11", "tsv"],
                                   capture_output=True, text=True, env=env).stdout
    with ThreadPoolExecutor(max(1, (os.cpu_count() or 2) // 2)) as ex:
        tsvs = list(ex.map(run, files))
    out = []
    for i, tsv in enumerate(tsvs):
        text, words = "", []
        for row in tsv.splitlines()[1:]:
            c = row.split("\t")
            if len(c) < 12 or not c[11].strip():
                continue
            if text:
                text += " "
            words.append((len(text), len(text) + len(c[11].strip()), tuple(int(v) for v in c[6:10])))
            text += c[11].strip()
        # frame k of fps=1/0.5 covers [k*0.5, (k+1)*0.5): report its middle
        out.append(((i + 0.5) * OCR_STEP, text, words))
    return out


def union(a, b):
    if not a:
        return b
    x, y = min(a[0], b[0]), min(a[1], b[1])
    return (x, y, max(a[0] + a[2], b[0] + b[2]) - x, max(a[1] + a[3], b[1] + b[3]) - y)


def text_hits(ocr, patterns, allow):
    """One hit per episode: the same text on consecutive OCR frames counts once, as "t0-t1", with the box
    (x, y, w, h in video pixels) that holds it over the episode."""
    hits, open_ = [], {}
    for k, (t, flat, words) in enumerate(ocr):
        seen = set()
        for p in patterns:
            for m in re.finditer(p, flat, re.IGNORECASE):
                ctx = flat[max(0, m.start() - 25): m.end() + 25]
                if any(re.search(a, ctx, re.IGNORECASE) for a in allow):
                    continue
                key = m.group(0).lower()
                if key in seen:
                    continue
                seen.add(key)
                box = None
                for s0, s1, b in words:
                    if s0 < m.end() and s1 > m.start():
                        box = union(box, b)
                h = open_.get(key)
                if h and h["k"] == k - 1:
                    h["k"], h["t1"], h["box"] = k, t, union(h["box"], box) if box else h["box"]
                else:
                    open_[key] = h = {"k": k, "t0": t, "t1": t, "what": m.group(0), "ctx": ctx, "box": box}
                    hits.append(h)
    # text under 8 px high in a 1080p frame cannot be read by a viewer: OCR noise in a stream picture (a test
    # pattern's frame counter read as "401") is not a finding
    hits = [h for h in hits if not h["box"] or h["box"][3] >= MIN_TEXT_H]
    return [(h["t0"] if h["t0"] == h["t1"] else f"{h['t0']:.1f}-{h['t1']:.1f}s",
             h["what"] + (" @ box %d,%d,%d,%d" % h["box"] if h["box"] else ""), h["ctx"], h) for h in hits]


def blur_hits(mp4, hits, out, pad=14):
    """Copy of the video with every banned_text box blurred over its episode (+-0.5 s): the last-resort fix
    for a take that cannot be re-recorded. Re-run the check on the copy."""
    vin, pre = "[0:v]", ""
    for i, (*_, h) in enumerate(x for x in hits if x[3]["box"]):
        x, y, w, hh = h["box"]
        x, y = max(0, x - pad) // 2 * 2, max(0, y - pad) // 2 * 2; w, hh = (w + 2 * pad + 1) // 2 * 2, (hh + 2 * pad + 1) // 2 * 2
        t0, t1 = max(0, h["t0"] - OCR_STEP), h["t1"] + OCR_STEP
        pre += (f"{vin}split[s{i}][k{i}];[k{i}]crop={w}:{hh}:{x}:{y},gblur=sigma=12:steps=3[b{i}];"
                f"[s{i}][b{i}]overlay={x}:{y}:enable='between(t,{t0:.2f},{t1:.2f})'[o{i}];")
        vin = f"[o{i}]"
    if not pre:
        raise SystemExit("no banned_text box to blur")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-filter_complex", pre.rstrip(";"),
                    "-map", vin, "-map", "0:a?", "-c:a", "copy", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"{out}: {pre.count('gblur')} box(es) blurred; run promo_check.py on it again")


def black_runs(mp4):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(mp4), "-vf", "blackdetect=d=0.5:pix_th=0.05", "-an",
                        "-f", "null", "-"], capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]


def dark_tiles(mp4, limit=0.30, step=0.5):
    """(t0, t1, worst fraction) for every run >= 1 s where pure black (< 12) covers more than `limit` of the
    page area between the header and the caption band (scaled 192x108 grey, rows 16-80)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"fps=1/{step},scale=192:108,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    frac = (np.frombuffer(r.stdout, np.uint8).reshape(-1, 108, 192)[:, 16:81, :] < 12).mean(axis=(1, 2))
    runs, start = [], None
    for i, f in enumerate(list(frac) + [0.0]):
        if f > limit and start is None:
            start = i
        elif f <= limit and start is not None:
            if i - start >= 2:
                runs.append((start * step, i * step, float(frac[start:i].max())))
            start = None
    return runs


def flashes(mp4):
    # the same signature frames_to_mp4.py takes per frame: the top eighth of the page, grey, 96x12
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", "crop=iw:ih/8:0:0,scale=96:12,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    sig = list(np.frombuffer(r.stdout, np.uint8).reshape(-1, 12, 96).astype(np.int16))
    fps = len(sig) / max(probe(mp4)[0], 0.001)
    level = [float(x.mean()) for x in sig]
    # a scene cut fades through a dark frame (build.fade): a run that dips below a third of the frame before is
    # that fade, not a flash
    return [(i / fps, j - i) for i, j in flash_runs(sig) if min(level[i:j]) > level[i - 1] / 3]


def caption_overflow(srt):
    if not srt or not Path(srt).exists():
        return []
    font = ImageFont.truetype(FONT_BOLD, CAPTION_SIZE)
    out = []
    for block in re.split(r"\n\s*\n", Path(srt).read_text().strip()):
        rows = block.strip().splitlines()
        if len(rows) < 3:
            continue
        for line in rows[2:]:
            w = font.getlength(line)
            if w > CAPTION_MAX_W:
                out.append((rows[1].split(" --> ")[0], f"{w:.0f}px > {CAPTION_MAX_W}px", line))
    return out


def default_srt(mp4):
    mp4 = Path(mp4)
    for stem in (mp4.stem, re.sub(r"_voice-.*$", "", mp4.stem)):
        if (mp4.parent / f"{stem}.srt").exists():
            return mp4.parent / f"{stem}.srt"
    return None


def check(mp4, srt=None, allow=(), allow_dark=()):
    """Every counter with its hits: {name: [hit, ...]}. All empty = the video passes."""
    srt = srt or default_srt(mp4)
    vdur, adur = probe(mp4)
    pcm = audio_pcm(mp4) if adur is not None else None
    if pcm is not None:
        adur = len(pcm) / 16000
    voiced = "_voice-" in Path(mp4).name
    vmap = voice_map(mp4) if voiced else None
    with tempfile.TemporaryDirectory() as tmp:
        ocr = ocr_frames(mp4, tmp)
    res = {
        "banned_text": text_hits(ocr, BANNED + denylist(), allow),
        "black_frames": [(a, f"black {b - a:.2f}s", "") for a, b in black_runs(mp4)]
                        + text_hits(ocr, [LOADING], allow),
        "dark_tiles": [(f"{a:.1f}-{b:.1f}s", f"{w:.0%} of the page black", "") for a, b, w in dark_tiles(mp4)
                       if not any(a < y and b > x for x, y in allow_dark)],
        "flashes": [(t, f"{n} frame(s)", "") for t, n in flashes(mp4)],
        "caption_overflow": caption_overflow(srt),
        "duration_over_90s": [(0, f"{vdur:.1f}s", "")] if vdur > MAX_DURATION else [],
        "voice_mismatch": [(0, f"audio {adur:.1f}s vs video {vdur:.1f}s", "")]
                          if adur is not None and abs(adur - vdur) > 1.0 else [],
        "voice_silent": ([(0, "no voice map (re-run voiceover.py)", "")] if voiced and vmap is None else
                         [(at, f"silent ({db:.0f} dBFS): {text}", "") for at, text, db in silent_lines(pcm, vmap)]
                         if vmap and pcm is not None else []),
    }
    return res, {"video": str(mp4), "srt": str(srt) if srt else None, "duration": round(vdur, 2),
                 "audio": round(adur, 2) if adur is not None else None}


def passed(res):
    return all(not v for v in res.values())


def report(res, info):
    print(f"{info['video']}  ({info['duration']}s, audio {info['audio']}, srt {info['srt']})")
    print(f"{'counter':<20}{'count':>6}")
    for k, v in res.items():
        print(f"{k:<20}{len(v):>6}")
    for k, v in res.items():
        for t, what, ctx, *_ in v[:20]:
            ts = t if isinstance(t, str) else f"{t:6.1f}s"
            print(f"  {k}: {ts}  {what}  {ctx}".rstrip())
        if len(v) > 20:
            print(f"  {k}: ... {len(v) - 20} more")
    print("PASS" if passed(res) else "FAIL")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp4"); ap.add_argument("--srt"); ap.add_argument("--allow", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-dark", action="append", default=[], metavar="T0-T1",
                    help="waive a dark_tiles run inside this time range (seconds), e.g. 21-30")
    ap.add_argument("--blur-to", metavar="OUT_MP4", help="write a copy with every banned_text box blurred")
    a = ap.parse_args()
    res, info = check(a.mp4, a.srt, a.allow, [tuple(float(v) for v in r.split("-")) for r in a.allow_dark])
    if a.blur_to and res["banned_text"]:
        blur_hits(a.mp4, res["banned_text"], a.blur_to)
    if a.json:
        print(json.dumps({"info": info, "counters": {k: len(v) for k, v in res.items()},
                          "hits": {k: [x[:3] for x in v] for k, v in res.items()}}, indent=1))
    else:
        report(res, info)
    sys.exit(0 if passed(res) else 1)


if __name__ == "__main__":
    main()
