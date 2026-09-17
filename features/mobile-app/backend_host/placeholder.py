"""
features/mobile-app/backend_host/placeholder.py — renders the "not paired" / "phone
offline" frame that keeps run_ffmpeg.sh's imagefile source valid before a phone is
connected (docs/tasks/TASK-17-mobile-app-phone-agent.md §1.1: the imagefile branch
waits up to 120s for a readable image then defaults to landscape — writing this at
register() avoids both the wait and the wrong orientation). Pillow only, no bundled
font required (falls back to PIL's built-in bitmap font when no system TTF exists).
"""
import os

from PIL import Image, ImageDraw, ImageFont

_BG = (24, 26, 32)
_FG = (222, 224, 230)
_MUTED = (150, 154, 165)
_ACCENT = (90, 140, 255)


def _load_font(size: int):
    for candidate in (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_placeholder(path: str, title: str, subtitle: str = '', size=(720, 1280)) -> None:
    """Render a portrait placeholder frame and write it atomically to `path`.

    JPEG or PNG is picked from the extension of `path` — run_ffmpeg.sh's imagefile
    source only needs a readable image it can `cat` in a loop, either works.
    """
    w, h = size
    img = Image.new('RGB', size, _BG)
    draw = ImageDraw.Draw(img)

    # A simple phone-outline glyph so an empty slot reads as "a phone slot" at a
    # glance, even with no real device art.
    outline_w, outline_h = int(w * 0.28), int(h * 0.42)
    ox, oy = (w - outline_w) // 2, int(h * 0.18)
    draw.rounded_rectangle([ox, oy, ox + outline_w, oy + outline_h], radius=28, outline=_ACCENT, width=6)
    notch_w = int(outline_w * 0.3)
    draw.rounded_rectangle(
        [ox + (outline_w - notch_w) // 2, oy + 14, ox + (outline_w + notch_w) // 2, oy + 22],
        radius=4, fill=_ACCENT,
    )

    def _centered(y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) / 2, y), text, font=font, fill=fill)

    _centered(oy + outline_h + 60, title, _load_font(44), _FG)
    if subtitle:
        _centered(oy + outline_h + 120, subtitle, _load_font(26), _MUTED)

    _atomic_save(img, path)


def _atomic_save(img: Image.Image, path: str) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f'{path}.tmp'
    ext = os.path.splitext(path)[1].lower()
    fmt = 'PNG' if ext == '.png' else 'JPEG'
    save_kwargs = {} if fmt == 'PNG' else {'quality': 85}
    img.save(tmp_path, fmt, **save_kwargs)
    os.replace(tmp_path, path)
