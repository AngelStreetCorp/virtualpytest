"""
Step mosaic: one compressed JPEG that shows a test run at a glance.

Each top-level step contributes ONE tile — the screenshot the report already
uses as that step's thumbnail (step_end when present, otherwise the last
frame captured during the step). Tiles are laid out in reading order on a
grid, each with a status-coloured header "OK N message" / "FAIL N message".

Built from the LOCAL screenshot files at report time (before they are
cleaned up), so it costs no extra download. Sizing is deliberately small:
320-px-wide tiles, JPEG q=60, progressive — a 10-step run is ~100 KB. The
file is uploaded next to report.html (see report_generation_utils) and its
URL is kept in script_results.metadata.mosaic_r2_url so Grafana / notifs
can show it later without another round trip through the HTML.

Never raises: any problem returns None and the report is generated without
a mosaic.
"""

import os
from typing import Dict, List, Optional, Tuple

TILE_WIDTH = 320          # px; keeps a 10-step mosaic under ~150 KB
JPEG_QUALITY = 60
MAX_TILES = 60            # beyond this the mosaic stops being "a glance"
HEADER_H = 22             # px status strip above each tile
GAP = 6                   # px between tiles
MARGIN = 8                # px around the grid

_OK = (34, 139, 34)       # green
_KO = (200, 40, 40)       # red
_BG = (24, 24, 28)        # dark grid background
_TXT = (255, 255, 255)


def pick_step_screenshot(step: Dict) -> Optional[str]:
    """Representative LOCAL screenshot for a step (mirrors the report thumbnail rule)."""
    end = step.get('step_end_screenshot_path')
    if end and _is_local_file(end):
        return end
    candidates: List[str] = []
    if step.get('step_start_screenshot_path'):
        candidates.append(step['step_start_screenshot_path'])
    candidates.extend(step.get('action_screenshots') or [])
    candidates.extend(step.get('verification_screenshots') or [])
    if step.get('screenshot_path'):
        candidates.append(step['screenshot_path'])
    for path in reversed(candidates):
        if path and _is_local_file(path):
            return path
    return None


def _is_local_file(path: str) -> bool:
    return bool(path) and not str(path).startswith('http') and os.path.isfile(path)


def _step_label(step: Dict, index: int) -> str:
    number = step.get('step_number', index + 1)
    message = (step.get('message') or '').strip()
    if not message:
        frm, to = step.get('from_node'), step.get('to_node')
        message = f"{frm} → {to}" if frm and to else ''
    return f"{number}  {message}".strip()


def _grid_columns(n: int) -> int:
    if n <= 4:
        return max(n, 1)
    if n <= 16:
        return 4
    return 5


def _load_font(size: int):
    from PIL import ImageFont
    for name in ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf', 'Arial.ttf', 'Helvetica.ttc'):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1: scalable fallback
    except Exception:
        return ImageFont.load_default()


def _fit_text(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + '…', font=font) > max_w:
        text = text[:-1]
    return text + '…'


def build_step_mosaic(step_results: List[Dict], output_path: str,
                      tile_width: int = TILE_WIDTH, quality: int = JPEG_QUALITY) -> Optional[Dict]:
    """Tile one screenshot per step into `output_path` (JPEG).

    Returns {'path', 'width', 'height', 'tiles', 'bytes'} or None when there is
    nothing to draw (no step has a local screenshot) or Pillow is unavailable.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception as e:  # pragma: no cover - Pillow missing on host
        print(f"[@report_mosaic] Pillow unavailable, skipping mosaic: {e}")
        return None

    tiles: List[Tuple[str, bool, str]] = []
    for idx, step in enumerate(step_results or []):
        path = pick_step_screenshot(step)
        if path:
            tiles.append((path, bool(step.get('success', False)), _step_label(step, idx)))
    if not tiles:
        print("[@report_mosaic] No local step screenshots, skipping mosaic")
        return None
    if len(tiles) > MAX_TILES:
        print(f"[@report_mosaic] {len(tiles)} steps, keeping first {MAX_TILES}")
        tiles = tiles[:MAX_TILES]

    try:
        # Tile height follows the first screenshot's aspect ratio (all frames of a
        # run share the capture resolution), so the grid stays uniform.
        with Image.open(tiles[0][0]) as probe:
            aspect = probe.height / max(probe.width, 1)
        tile_h = max(int(tile_width * aspect), 60)

        cols = _grid_columns(len(tiles))
        rows = (len(tiles) + cols - 1) // cols
        cell_w, cell_h = tile_width, HEADER_H + tile_h
        width = MARGIN * 2 + cols * cell_w + (cols - 1) * GAP
        height = MARGIN * 2 + rows * cell_h + (rows - 1) * GAP

        canvas = Image.new('RGB', (width, height), _BG)
        draw = ImageDraw.Draw(canvas)
        font = _load_font(13)

        for i, (path, ok, label) in enumerate(tiles):
            x = MARGIN + (i % cols) * (cell_w + GAP)
            y = MARGIN + (i // cols) * (cell_h + GAP)
            draw.rectangle([x, y, x + cell_w - 1, y + HEADER_H - 1], fill=_OK if ok else _KO)
            # Plain ASCII marker: ✓/✗ render as boxes on fonts lacking the glyphs.
            text = _fit_text(draw, ('OK ' if ok else 'FAIL ') + label, font, cell_w - 10)
            draw.text((x + 5, y + 4), text, fill=_TXT, font=font)
            try:
                with Image.open(path) as img:
                    img = img.convert('RGB')
                    img.thumbnail((cell_w, tile_h))
                    # Centre when the frame's aspect differs from the probe.
                    ox = x + (cell_w - img.width) // 2
                    oy = y + HEADER_H + (tile_h - img.height) // 2
                    canvas.paste(img, (ox, oy))
            except Exception as tile_error:
                print(f"[@report_mosaic] Tile {i + 1} unreadable ({path}): {tile_error}")
                draw.text((x + 5, y + HEADER_H + 5), 'no image', fill=(160, 160, 160), font=font)

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        canvas.save(output_path, 'JPEG', quality=quality, optimize=True, progressive=True)
        size = os.path.getsize(output_path)
        print(f"[@report_mosaic] Built {len(tiles)} tiles {width}x{height} → {output_path} ({size // 1024} KB)")
        return {'path': output_path, 'width': width, 'height': height, 'tiles': len(tiles), 'bytes': size}
    except Exception as e:
        print(f"[@report_mosaic] Failed to build mosaic: {e}")
        return None
