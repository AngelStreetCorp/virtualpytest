"""Review images for ui_shots.cjs output (TASK-56). Needs Pillow.

  python3 scripts/ui/ui_images.py pair <dir> <name>...          -> <dir>/pair-<name>.png (dark | light, 60 %)
  python3 scripts/ui/ui_images.py grid <out.png> <img>...        -> 2-column contact sheet at 50 %, labelled
  python3 scripts/ui/ui_images.py summary <audit.txt>             -> one line per page/theme from AUDIT output

A pair or a grid costs far fewer tokens to look at than separate full screenshots.
"""
import json
import sys

from PIL import Image, ImageDraw


def pair(d, names):
    for n in names:
        a, b = Image.open(f'{d}/{n}.dark.png'), Image.open(f'{d}/{n}.light.png')
        w, h = int(a.width * .6), int(a.height * .6)
        out = Image.new('RGB', (w * 2 + 6, h), (255, 0, 0))
        out.paste(a.resize((w, h)), (0, 0))
        out.paste(b.resize((w, h)), (w + 6, 0))
        out.save(f'{d}/pair-{n}.png')


def grid(out, paths, w=750, h=450):
    rows = (len(paths) + 1) // 2
    g = Image.new('RGB', (w * 2 + 4, (h + 4) * rows), (255, 0, 0))
    for i, p in enumerate(paths):
        t = Image.open(p).resize((w, h))
        d = ImageDraw.Draw(t)
        d.rectangle([0, 0, 320, 14], fill=(0, 0, 0))
        d.text((2, 1), p.split('/')[-1], fill=(255, 255, 0))
        g.paste(t, ((i % 2) * (w + 4), (i // 2) * (h + 4)))
    g.save(out)


def summary(path):
    for line in open(path):
        if not line.startswith('AUDIT'):
            continue
        _, theme, name, js = line.split(' ', 3)
        a = {k: v for k, v in json.loads(js).items() if not k.startswith('?')}
        if a:
            print(theme[0], name.ljust(18), ', '.join(f"{k}:{v['n']} {v['ex'][0][:50]}" for k, v in sorted(a.items(), key=lambda x: -x[1]['n'])[:3]))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'pair':
        pair(sys.argv[2], sys.argv[3:])
    elif cmd == 'grid':
        grid(sys.argv[2], sys.argv[3:])
    elif cmd == 'summary':
        summary(sys.argv[2])
    else:
        sys.exit(__doc__)
