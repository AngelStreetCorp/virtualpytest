#!/usr/bin/env python3
"""Turn a screenshot PNG/JPG into the two WebP files the docs gallery uses.

    python3 scripts/screenshot_to_webp.py path/to/shot.png [more.png ...]

Writes frontend/public/screenshot/<name>.webp (max 1600 px wide, opened on click) and
<name>.thumb.webp (640 px wide, shown in the grid) and prints the screenshots.json entry to add
(categories required). Rules: docs/screenshots/README.md "Adding a screenshot".
"""
import os
import sys

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False  # a truncated PNG must fail loudly, not ship half-black
OUT = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'public', 'screenshot')


def convert(path):
    name = os.path.splitext(os.path.basename(path))[0]
    im = Image.open(path).convert('RGB')
    w, h = im.size
    full = im.resize((1600, round(h * 1600 / w)), Image.LANCZOS) if w > 1600 else im
    full.save(os.path.join(OUT, name + '.webp'), 'WEBP', quality=80, method=6)
    tw, th = 640, round(h * 640 / w)
    im.resize((tw, th), Image.LANCZOS).save(os.path.join(OUT, name + '.thumb.webp'), 'WEBP', quality=78, method=6)
    print(f'{name}: wrote {name}.webp + {name}.thumb.webp ({tw}x{th}). Add this entry to docs/screenshots/screenshots.json,')
    print('  with 1-2 categories of device|ai|test|scripts|stream (the first is the primary one), then run scripts/gen_readme_screenshots.py:')
    print(f'    {{ "id": "{name}", "title": "<Title>", "file": "{name}", "categories": ["<primary>"] }}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        convert(p)
