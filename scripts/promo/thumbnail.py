"""YouTube thumbnail in the series style: 1280x720, product screen tinted navy, big two-line
claim on the left, gold pills. Same look for every video so the channel reads as one set.

    python scripts/promo/thumbnail.py <source.png> <out.jpg> "Line one" "Line two" "subtitle" \
        [--pill "OPEN SOURCE  ·  FREE"] [--pill "MCP  ·  63 TOOLS"] [--crop x0,y0,x1,y1]

The source is any 16:9-ish screenshot from the video (raw captures, not frames with burned-in
captions). Keep the claim different from the YouTube title: both show side by side.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import build  # sibling module: colours and fonts

W, H = 1280, 720


def thumbnail(src, out, line1, line2, subtitle, pills, crop=None):
    im = Image.open(src).convert("RGB")
    if crop:
        im = im.crop(crop)
    im = im.resize((W, H), Image.LANCZOS)
    # global navy tint so a white UI reads as a dark card, stronger on the left for the text
    base = Image.new("RGB", (W, H), build.NAVY)
    grad = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grad)
    for x in range(W):
        a = int(255 * min(1, 0.62 + 0.38 * max(0, 1 - (x / W) / 0.62)))
        gd.line([(x, 0), (x, H)], fill=a)
    im = Image.composite(base, im, grad)
    d = ImageDraw.Draw(im)
    fb = ImageFont.truetype(build.FONT_BOLD, 96)
    fs = ImageFont.truetype(build.FONT_REG, 36)
    fp = ImageFont.truetype(build.FONT_BOLD, 24)
    logo = Image.open(build.LOGO).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    lh = 70
    lw = int(logo.width * lh / logo.height)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    im.paste(logo, (56, 48), logo)
    d.text((56 + lw + 16, 60), "VirtualPyTest", font=ImageFont.truetype(build.FONT_BOLD, 40), fill=build.WHITE)
    y = 232
    for line in (line1, line2):
        if not line:
            continue
        d.text((60, y + 4), line, font=fb, fill=(0, 0, 0))
        d.text((56, y), line, font=fb, fill=build.WHITE)
        y += 106
    d.text((58, y + 12), subtitle, font=fs, fill=(205, 218, 236))
    x = 56
    for t in pills:
        tw = d.textlength(t, font=fp) + 44
        d.rounded_rectangle([(x, H - 92), (x + tw, H - 48)], radius=22, fill=build.GOLD)
        d.text((x + 22, H - 84), t, font=fp, fill=build.NAVY)
        x += tw + 16
    im.save(out, quality=92, optimize=True)
    print(out, Path(out).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("line1"); ap.add_argument("line2"); ap.add_argument("subtitle")
    ap.add_argument("--pill", action="append", default=None)
    ap.add_argument("--crop", help="x0,y0,x1,y1 on the source image")
    a = ap.parse_args()
    crop = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    thumbnail(a.src, a.out, a.line1, a.line2, a.subtitle, a.pill or ["OPEN SOURCE  ·  FREE"], crop)
