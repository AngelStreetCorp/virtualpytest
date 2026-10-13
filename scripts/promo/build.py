"""Assemble the VirtualPyTest promo video from captured stills + clips.

Pipeline: each scene -> its own 1920x1080 30fps H.264 segment (zoompan / crop-pan for
stills, trimmed + sped-up for clips), captions burned in with drawtext, fade in/out,
then concat (stream copy). ffmpeg 4.2.3 has no xfade, so scenes cut through a short
fade to a dark frame, which reads as a deliberate "beat" between features.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).parent
RAW = HERE / "raw"
WORK = HERE / "work"
OUT = HERE / "out"
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

FFMPEG = "ffmpeg"
W, H, FPS = 1920, 1080, 30
# Inter (SIL OFL, fonts/OFL.txt) is committed next to the scripts so every video renders the same
# on Windows, macOS and Linux. Never point these at a system font.
FONT_REG = str(HERE / "fonts/Inter-Regular.ttf")
FONT_BOLD = str(HERE / "fonts/Inter-Bold.ttf")
# the caption: one line of Inter Bold, centred; promo_check.py fails a line wider than CAPTION_MAX_W
CAPTION_SIZE = 46
CAPTION_MAX_W = W - 2 * 80
LOGO = Path(__file__).resolve().parents[2] / "frontend/public/brand/logo.png"

NAVY = (11, 31, 58)
BLUE = (25, 118, 210)
GOLD = (255, 200, 40)
WHITE = (255, 255, 255)

ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
       "-r", str(FPS), "-an", "-movflags", "+faststart"]


def ff_path(p: Path) -> str:
    """Escape a path (Windows drive colon, backslashes) for use inside an ffmpeg filter option."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd)[:300])
    subprocess.run([str(c) for c in cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def check(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed: {cmd[:4]}")


# ----------------------------------------------------------------------------- captions
def caption_overlay(idx: int, title: str, text: str, path: Path):
    """Transparent 1920x1080 PNG with a bottom caption bar + top-left step pill."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f_cap = ImageFont.truetype(FONT_BOLD, CAPTION_SIZE)
    f_pill = ImageFont.truetype(FONT_BOLD, 26)

    # Bottom gradient band so the caption is readable over any UI.
    band = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(260):
        a = int(210 * (y / 260) ** 1.4)
        bd.line([(0, y), (W, y)], fill=(8, 18, 34, a))
    im.alpha_composite(band, (0, H - 260))

    # Caption text, centered, with a subtle shadow.
    tw = d.textlength(text, font=f_cap)
    x = (W - tw) / 2
    y = H - 118
    d.text((x + 2, y + 3), text, font=f_cap, fill=(0, 0, 0, 160))
    d.text((x, y), text, font=f_cap, fill=WHITE + (255,))
    # Gold accent bar above the caption.
    d.rounded_rectangle([(W / 2 - 40, y - 22), (W / 2 + 40, y - 16)], radius=3, fill=GOLD + (255,))

    # Top-left pill: "02  DEVICES"
    label = f"{idx:02d}   {title.upper()}"
    pw = d.textlength(label, font=f_pill) + 44
    px, py = 40, 92
    d.rounded_rectangle([(px, py), (px + pw, py + 46)], radius=23, fill=NAVY + (215,))
    d.rounded_rectangle([(px, py), (px + 8, py + 46)], radius=4, fill=GOLD + (255,))
    d.text((px + 26, py + 8), label, font=f_pill, fill=WHITE + (255,))
    im.save(path)


def card(path: Path, big: str, small: str, tag=None, url: str | None = None, big_size: int = 96):
    """Intro / outro card on a navy gradient with the logo."""
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    # Diagonal gradient glow.
    glow = Image.new("RGB", (W, H), NAVY)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([(-300, -200), (1100, 900)], fill=(20, 70, 140))
    gd.ellipse([(1300, 500), (2300, 1400)], fill=(30, 50, 100))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    im = Image.blend(im, glow, 0.85)
    d = ImageDraw.Draw(im)

    logo = Image.open(LOGO).convert("RGBA")
    lh = 260
    lw = int(logo.width * lh / logo.height)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    im.paste(logo, ((W - lw) // 2, 200), logo)

    f_big = ImageFont.truetype(FONT_BOLD, big_size)
    f_small = ImageFont.truetype(FONT_REG, 44)
    f_tag = ImageFont.truetype(FONT_BOLD, 30)
    tw = d.textlength(big, font=f_big)
    d.text(((W - tw) / 2, 500), big, font=f_big, fill=WHITE)
    tw = d.textlength(small, font=f_small)
    d.text(((W - tw) / 2, 630), small, font=f_small, fill=(200, 215, 235))
    tags = [tag] if isinstance(tag, str) else (tag or [])
    if tags:
        gap = 28
        widths = [d.textlength(t, font=f_tag) + 60 for t in tags]
        x = (W - (sum(widths) + gap * (len(widths) - 1))) / 2
        for t, tw in zip(tags, widths):
            d.rounded_rectangle([(x, 740), (x + tw, 800)], radius=30, fill=GOLD)
            d.text((x + 30, 752), t, font=f_tag, fill=NAVY)
            x += tw + gap
    if url:
        f_url = ImageFont.truetype(FONT_BOLD, 40)
        tw = d.textlength(url, font=f_url)
        d.text(((W - tw) / 2, 850), url, font=f_url, fill=GOLD)
    im.save(path)


# ----------------------------------------------------------------------------- scenes
def fade(dur: float, fin=0.35, fout=0.35):
    parts = ([f"fade=t=in:st=0:d={fin}"] if fin else []) + ([f"fade=t=out:st={dur - fout:.2f}:d={fout}"] if fout else [])
    return ",".join(parts) or "null"


def still_scene(name, src: Path, dur: float, overlay: Path, out: Path,
                zoom_from=1.0, zoom_to=1.12, focus=(0.5, 0.5), pan_y=None, fin=0.35, fout=0.35):
    """Ken Burns on a still. focus = (fx, fy) fraction of the image to zoom toward.
    pan_y = (y0, y1) crop offsets for a tall (full-page) image instead of zooming."""
    frames = int(dur * FPS)
    im = Image.open(src)
    iw, ih = im.size
    if pan_y is not None:
        y0, y1 = pan_y
        # Vertical pan over a full-page screenshot, smooth ease in/out.
        vf = (f"scale={W}:-2,"
              f"crop={W}:{H}:0:'({y0})+(({y1})-({y0}))*(0.5-0.5*cos(PI*min(t/{dur:.3f},1)))'")
    else:
        # Upscale first so zoompan does not jitter, then zoom toward the focus point.
        fx, fy = focus
        up = 4
        vf = (f"scale={W * up}:{H * up},"
              f"zoompan=z='{zoom_from}+({zoom_to}-{zoom_from})*on/{frames}':"
              f"x='iw*{fx}-(iw/zoom)*{fx}':y='ih*{fy}-(ih/zoom)*{fy}':"
              f"d={frames}:s={W}x{H}:fps={FPS}")
    filt = (f"[0:v]{vf},format=rgba[base];"
            f"[base][1:v]overlay=0:0:format=auto,format=yuv420p,{fade(dur, fin, fout)}[v]")
    cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", src,
           "-i", overlay, "-filter_complex", filt, "-map", "[v]", "-t", f"{dur:.3f}", *ENC, out]
    check(cmd)


def clip_scene(name, src: Path, start: float, end: float, speed: float, overlay: Path, out: Path,
               dur_cap: float | None = None, crop=None, fin=0.35, fout=0.35, badge=False, clock=None, blur=None):
    """Trim [start,end] of a recorded webm, speed it up, overlay caption, fade.
    crop = (x, y, w, h) in source pixels, 16:9, applied before the scale (hides a panel).
    fin/fout = 0 drops that fade (a clip continuing the previous one on the same page).
    badge = True draws a gold "×<speed>" pill top right, so a fast-forward reads as one.
    clock = real seconds elapsed at `start` (e.g. since the run began): draws H:MM:SS under the
    badge, counting at real speed while the clip plays faster.
    blur = [(x, y, w, h, t0, t1), ...] in source pixels and source seconds: that box is blurred
    between t0 and t1 (hides a brand on a device screen)."""
    real = (end - start) / speed
    dur = min(real, dur_cap) if dur_cap else real
    cropf = f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else ""
    marks = ""
    if badge:
        label = f"×{speed:g}"
        marks += (f",drawtext=fontfile='{FONT_BOLD}':text='{label}':fontsize=54:fontcolor=0x0B1F3A"
                  f":box=1:boxcolor=0xFFC828:boxborderw=18:x=w-tw-60:y=48")
    if clock is not None:
        e = f"({clock:.3f}+t*{speed:g})"
        txt = (f"%{{eif\\:floor({e}/3600)\\:d}}\\:%{{eif\\:mod(floor({e}/60)\\,60)\\:d\\:2}}"
               f"\\:%{{eif\\:mod(floor({e})\\,60)\\:d\\:2}}")
        marks += (f",drawtext=fontfile='{FONT_BOLD}':text='{txt}':fontsize=40:fontcolor=white"
                  f":box=1:boxcolor=0x0B1F3A@0.85:boxborderw=14:x=w-tw-60:y={150 if badge else 48}")
    vin, pre = "[0:v]", ""
    for i, (bx, by, bw, bh, b0, b1) in enumerate(blur or []):
        pre += (f"{vin}split[bs{i}][bk{i}];[bk{i}]crop={bw}:{bh}:{bx}:{by},boxblur=28:3[bb{i}];"
                f"[bs{i}][bb{i}]overlay={bx}:{by}:enable='between(t,{b0},{b1})'[bo{i}];")
        vin = f"[bo{i}]"
    filt = (pre + f"{vin}trim=start={start}:end={end},setpts=(PTS-STARTPTS)/{speed},"
            f"fps={FPS},{cropf}scale={W}:{H},format=rgba[base];"
            f"[base][1:v]overlay=0:0:format=auto{marks},format=yuv420p,{fade(dur, fin, fout)}[v]")
    cmd = [FFMPEG, "-y", "-v", "error", "-i", src, "-i", overlay,
           "-filter_complex", filt, "-map", "[v]", "-t", f"{dur:.3f}", *ENC, out]
    check(cmd)
    return dur


def card_scene(src: Path, dur: float, out: Path):
    filt = f"scale={W}:{H},format=yuv420p,{fade(dur, 0.6, 0.6)}"
    cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", src,
           "-vf", filt, "-t", f"{dur:.3f}", *ENC, out]
    check(cmd)


def main():
    marks = {}
    for n in ("devices", "run-tests", "incidents"):
        p = RAW / f"{n}.marks.json"
        marks[n] = {m["label"]: m["t"] for m in json.load(open(p))} if p.exists() else {}
    print("marks:", marks)

    segs = []
    srt = []
    t_cursor = 0.0

    def add(seg_path, dur, caption=None):
        nonlocal t_cursor
        segs.append(seg_path)
        if caption:
            srt.append((t_cursor + 0.3, t_cursor + dur - 0.3, caption))
        t_cursor += dur

    # 1. Intro card
    card(WORK / "intro.png", "VirtualPyTest", "Automated testing for TV, set-top box, mobile and web", ["OPEN SOURCE  ·  FREE", "SELF-HOSTED  OR  CLOUD"], url="virtualpytest.com")
    card_scene(WORK / "intro.png", 3.6, WORK / "s01.mp4"); add(WORK / "s01.mp4", 3.6)

    # 2. Dashboard
    ov = WORK / "ov02.png"; caption_overlay(1, "Dashboard", "One dashboard for every host and device", ov)
    still_scene("dashboard", RAW / "dashboard.png", 6.0, ov, WORK / "s02.mp4", 1.0, 1.15, (0.5, 0.42))
    add(WORK / "s02.mp4", 6.0, "One dashboard for every host and device")

    # 3. Devices: recorded clip (fallback to still)
    ov = WORK / "ov03.png"; caption_overlay(2, "Devices", "Live stream and remote control of real hardware", ov)
    m = marks.get("devices", {})
    if (RAW / "devices.webm").exists() and "modal" in m:
        s = max(m["loaded"] - 0.8, 0); e = m.get("end", m["modal"] + 8)
        d = clip_scene("devices", RAW / "devices.webm", s, e, 1.35, ov, WORK / "s03.mp4", dur_cap=8.0)
    else:
        d = 6.0; still_scene("devices", RAW / "devices.png", d, ov, WORK / "s03.mp4", 1.0, 1.18, (0.3, 0.3))
    add(WORK / "s03.mp4", d, "Live stream and remote control of real hardware")

    # 4. Run tests: recorded clip
    ov = WORK / "ov04.png"; caption_overlay(3, "Run tests", "Pick a device, pick a test, run it in one click", ov)
    m = marks.get("run-tests", {})
    if (RAW / "run-tests.webm").exists() and "run" in m:
        s = max(m["loaded"] - 0.6, 0); e = min(m["run"] + 5.5, m.get("end", m["run"] + 6))
        d = clip_scene("run-tests", RAW / "run-tests.webm", s, e, 1.5, ov, WORK / "s04.mp4", dur_cap=8.5)
    else:
        d = 6.0; still_scene("run-tests", RAW / "run-tests.png", d, ov, WORK / "s04.mp4", 1.0, 1.15, (0.35, 0.35))
    add(WORK / "s04.mp4", d, "Pick a device, pick a test, run it in one click")

    # 5. Report (full-page, vertical pan)
    ov = WORK / "ov05.png"; caption_overlay(4, "Report", "Every run ships a report: screenshots, video, step-by-step evidence", ov)
    rep = RAW / "report-smoke_video_stream.png"
    ih = Image.open(rep).height
    still_scene("report", rep, 5.5, ov, WORK / "s05.mp4", pan_y=(0, max(ih - H, 0)))
    add(WORK / "s05.mp4", 5.5, "Every run ships a report: screenshots, video, step-by-step evidence")

    # 6. KPI measurement (speedtest report, zoom on the numbers)
    ov = WORK / "ov06.png"; caption_overlay(5, "KPI measurement", "Measure what matters: throughput, latency, zap and boot time", ov)
    still_scene("kpi-report", RAW / "report-ookla_speedtest.png", 6.0, ov, WORK / "s06.mp4", 1.0, 1.35, (0.25, 0.36))
    add(WORK / "s06.mp4", 6.0, "Measure what matters: throughput, latency, zap and boot time")

    # 7. Results / analytics
    ov = WORK / "ov07.png"; caption_overlay(6, "Results", "Pass rate and trends across thousands of runs", ov)
    still_scene("analytics", RAW / "analytics-kpi.png", 6.0, ov, WORK / "s07.mp4", 1.0, 1.14, (0.5, 0.35))
    add(WORK / "s07.mp4", 6.0, "Pass rate and trends across thousands of runs")

    # 8. Heatmap
    ov = WORK / "ov08.png"; caption_overlay(7, "Heatmap", "24h heatmap: blackscreen, freeze and audio loss across the fleet", ov)
    still_scene("heatmap", RAW / "heatmap.png", 5.5, ov, WORK / "s08.mp4", 1.0, 1.2, (0.5, 0.45))
    add(WORK / "s08.mp4", 5.5, "24h heatmap: blackscreen, freeze and audio loss across the fleet")

    # 9. Incidents: recorded clip expanding a freeze incident (fallback to still)
    ov = WORK / "ov09.png"; caption_overlay(8, "Incidents", "Freeze, blackscreen, audio loss: every incident keeps its evidence", ov)
    m = marks.get("incidents", {})
    if (RAW / "incidents.webm").exists() and "expand" in m:
        s = max(m["loaded"] - 0.5, 0); e = m.get("end", m["expand"] + 8)
        d = clip_scene("incidents", RAW / "incidents.webm", s, e, 1.4, ov, WORK / "s09.mp4", dur_cap=7.0)
    else:
        d = 5.5; still_scene("incidents", RAW / "incidents.png", d, ov, WORK / "s09.mp4", 1.0, 1.15, (0.5, 0.3))
    add(WORK / "s09.mp4", d, "Freeze, blackscreen, audio loss: every incident keeps its evidence")

    # 10. Outro
    card(WORK / "outro.png", "virtualpytest.com", "Any screen. Any device. Fully automated.", "OPEN SOURCE  ·  FREE", url="github.com/AngelStreetCorp/virtualpytest")
    card_scene(WORK / "outro.png", 3.8, WORK / "s10.mp4"); add(WORK / "s10.mp4", 3.8)

    # Concat
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    final = OUT / "virtualpytest_promo_60s.mp4"
    check([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final])

    # SRT sidecar (same captions) for platforms that prefer their own subtitles.
    def ts(t):
        h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    with open(OUT / "virtualpytest_promo_60s.srt", "w", encoding="utf-8") as f:
        for i, (a, b, c) in enumerate(srt, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{c}\n\n")

    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                       capture_output=True, text=True)
    print(f"\nDONE {final}  duration={float(r.stdout.strip()):.1f}s  size={final.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
