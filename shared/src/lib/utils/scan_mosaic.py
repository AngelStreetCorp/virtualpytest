#!/usr/bin/env python3
"""
Scan Mosaic Builder — shared by KPI and verification reports.

Both the KPI scan (kpi_report_generator) and windowed verifications
(verification_report_generator) analyse a *window* of frames over time, but
their reports historically showed only a few sampled thumbnails — so when a
scan/verification fails you can't see what was actually on screen and can't tell
*why* it failed. This module renders the WHOLE analysed window into one (or
more, paginated) mosaic image(s) that the report links, click-to-enlarge.

Design (agreed 2026-06-18):
- Keep native fps (no downsampling). Collapse only CONSECUTIVE near-duplicate
  frames via an 8x8 average-hash (Hamming < DEDUP_HAMMING vs the last kept tile),
  so static stretches (black / "no signal" / steady menu) collapse to one
  representative while every distinct frame and every transition survives.
- Paginate at cols x rows tiles per page; overflow spills to `<prefix>_scan_2`,
  `_scan_3`, … so nothing is ever silently dropped.
- Each tile carries a label (capture name) + sublabel (offset from action) and a
  border whose colour the caller chooses per frame (match / fail / probe / none).

Pure: PIL only, no network, no numpy. Callers upload the returned page files and
embed `render_mosaic_section()` in their report HTML (both report templates use
the same `openModal(src)` zoom handler, so the section markup is shared too).
"""

import os
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Defaults (confirmed): 256x144 (16:9, matches strip thumbnails) at 8x10 = 80
# tiles/page; collapse frames within Hamming 8 of the previous kept tile.
TILE_W, TILE_H = 256, 144
COLS, ROWS = 8, 10
DEDUP_HAMMING = 8
# Average-hash is blind to flat (texture-less) frames — black, a solid "no signal"
# colour and blue all hash to 0 — so it would wrongly collapse a black→colour→boot
# transition. Also keep a frame when its mean luma shifts by more than this, which
# catches those flat-frame transitions cheaply.
DEDUP_LUMA_DELTA = 10
# The 8x8 hash is coarse — on live video genuinely different frames can stay within
# the Hamming threshold, so unbounded collapse drops too much (150 → 14). Cap how
# many CONSECUTIVE near-duplicates we may skip: after this many, keep one anyway.
# So a fully static run still thins out, but we never show fewer than ~1 of every
# (MAX_COLLAPSE_RUN+1) frames — at 5 fps that's ≈1.7 frames/s kept on a static stretch.
MAX_COLLAPSE_RUN = 2
MAX_PAGES = 12  # hard backstop so a pathological window can't make hundreds of pages

# Per-frame border colours. Caller sets frame['border'] to one of these keys.
_BORDER_COLORS = {
    'match':  (0, 200, 0),     # the frame the scan matched on
    'fail':   (210, 45, 45),   # a frame the verifier checked and rejected
    'probe':  (60, 140, 255),  # a frame the verifier actually ran on (KPI coarse scan)
    'anchor': (255, 165, 0),   # action / before-match / after-match — always shown, not probed
    None:     (60, 60, 60),    # context frame (collapsed run / not probed)
}
_BG = (12, 12, 12)


def format_offset(seconds: float) -> str:
    """Human-readable offset from the action, e.g. 182.567 -> '3m 2s 567ms',
    12.34 -> '12s 340ms', 0.567 -> '567ms'. Negative (pre-action) keeps a '-'.
    Shared by both report callers so tile labels read identically."""
    neg = seconds < 0
    ms_total = int(round(abs(seconds) * 1000))
    m, rem = divmod(ms_total, 60000)
    s, ms = divmod(rem, 1000)
    parts = []
    if m:
        parts.append(f"{m}m")
    if s or m:
        parts.append(f"{s}s")
    parts.append(f"{ms}ms")
    out = " ".join(parts)
    return ("-" + out) if neg else out


def _signature(path: str) -> Optional[Tuple[int, float]]:
    """(8x8 average-hash, mean luma) for a frame. PIL-only (~1ms). None on error."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            px = list(im.convert('L').resize((8, 8), Image.BOX).getdata())
        avg = sum(px) / len(px)
        bits = 0
        for i, p in enumerate(px):
            if p > avg:
                bits |= (1 << i)
        return bits, avg
    except Exception:
        return None


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def _collapse_near_duplicates(frames: List[Dict], dedup_hamming: int) -> List[Dict]:
    """Keep a frame only if it differs from the last KEPT frame — by structure
    (aHash Hamming >= dedup_hamming) OR brightness (mean luma > DEDUP_LUMA_DELTA).
    Always keep border-flagged frames so a collapse never hides the matched frame,
    a probed frame, or an 'anchor' frame (action / before-match / after-match —
    see kpi_report_generator._build_scan_mosaic_section). Frames whose image
    can't be read are kept (fail-open)."""
    kept: List[Dict] = []
    last_hash: Optional[int] = None
    last_mean: Optional[float] = None
    run = 0  # consecutive near-duplicates skipped since the last kept frame
    for fr in frames:
        force = fr.get('border') in ('match', 'fail', 'probe', 'anchor')
        sig = _signature(fr.get('path', ''))
        similar = (
            not force and last_hash is not None and sig is not None
            and _hamming(sig[0], last_hash) < dedup_hamming
            and abs(sig[1] - last_mean) <= DEDUP_LUMA_DELTA
        )
        # Collapse only while we haven't skipped too many in a row — this floor
        # keeps the mosaic readable even when the coarse hash over-merges.
        if similar and run < MAX_COLLAPSE_RUN:
            run += 1
            continue
        kept.append(fr)
        run = 0
        if sig is not None:
            last_hash, last_mean = sig
    return kept


def _font():
    from PIL import ImageFont
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 11)
    except Exception:
        return ImageFont.load_default()


def _render_tile(fr: Dict, tile_w: int, tile_h: int):
    from PIL import Image, ImageDraw
    cell = Image.new('RGB', (tile_w, tile_h), _BG)
    path = fr.get('path', '')
    try:
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((tile_w, tile_h), Image.LANCZOS)
            cell.paste(im, ((tile_w - im.width) // 2, (tile_h - im.height) // 2))
    except Exception:
        # Missing/rolled frame (verification reads hot storage): leave a marker.
        d = ImageDraw.Draw(cell)
        d.text((6, tile_h // 2 - 6), 'frame gone', fill=(150, 150, 150), font=_font())

    draw = ImageDraw.Draw(cell)
    font = _font()
    is_match = fr.get('border') == 'match'
    is_anchor = fr.get('border') == 'anchor'
    tag = fr.get('tag')
    label = str(fr.get('label', ''))
    sublabel = str(fr.get('sublabel', ''))

    # Header (capture name) + footer (offset) strips. The matched frame gets bright
    # green strips with dark text and a "✓ MATCH" header so it's unmistakable among
    # otherwise similar-looking frames; an anchor frame (action / before-match /
    # after-match — always kept, never collapsed) gets its tag as a prefix instead;
    # everything else uses subtle dark strips.
    strip_bg = (0, 200, 0) if is_match else ((255, 165, 0) if is_anchor else (0, 0, 0))
    name_fg = (0, 0, 0) if (is_match or is_anchor) else (230, 230, 230)
    sub_fg = (0, 0, 0) if (is_match or is_anchor) else (180, 220, 255)
    if is_match:
        header = '✓ MATCH  ' + label
    elif tag:
        header = f'{tag}  {label}'
    else:
        header = label
    if header:
        draw.rectangle([0, 0, tile_w, 15], fill=strip_bg)
        draw.text((3, 1), header[:46], fill=name_fg, font=font)
    if sublabel:
        draw.rectangle([0, tile_h - 15, tile_w, tile_h], fill=strip_bg)
        draw.text((3, tile_h - 14), sublabel[:46], fill=sub_fg, font=font)

    # Border last so it frames the tile (and the strips) cleanly. Thick bright green
    # for the matched frame; thinner accent for other flags; hairline otherwise.
    if is_match:
        border_color, border_w = (0, 230, 0), 6
    elif fr.get('border') in ('fail', 'probe', 'anchor'):
        border_color, border_w = _BORDER_COLORS[fr.get('border')], 4
    else:
        border_color, border_w = _BORDER_COLORS[None], 1
    draw.rectangle([0, 0, tile_w - 1, tile_h - 1], outline=border_color, width=border_w)
    return cell


def build_mosaic_pages(
    frames: List[Dict],
    out_dir: str,
    prefix: str,
    tile: Tuple[int, int] = (TILE_W, TILE_H),
    cols: int = COLS,
    rows: int = ROWS,
    dedup_hamming: int = DEDUP_HAMMING,
) -> Tuple[List[str], Dict]:
    """Render the analysed window into paginated mosaic JPEGs.

    Args:
        frames: ordered list of {'path', 'label', 'sublabel', 'border'} dicts.
        out_dir: directory to write the page JPEGs into (e.g. the /tmp working dir).
        prefix: filename prefix; pages are `<prefix>_scan_1.jpg`, `_scan_2.jpg`, …

    Returns:
        (page_paths, stats) where stats = {'analyzed', 'shown', 'pages', 'truncated'}.
    """
    from PIL import Image

    analyzed = len(frames)
    if analyzed == 0:
        return [], {'analyzed': 0, 'shown': 0, 'pages': 0, 'truncated': False}

    kept = _collapse_near_duplicates(frames, dedup_hamming)
    tile_w, tile_h = tile
    per_page = cols * rows

    truncated = False
    if len(kept) > per_page * MAX_PAGES:
        # Don't silently drop — keep evenly-spaced samples and flag it.
        step = len(kept) / float(per_page * MAX_PAGES)
        kept = [kept[int(i * step)] for i in range(per_page * MAX_PAGES)]
        truncated = True

    page_paths: List[str] = []
    try:
        for page_idx in range(0, len(kept), per_page):
            chunk = kept[page_idx:page_idx + per_page]
            n_rows = (len(chunk) + cols - 1) // cols
            page = Image.new('RGB', (cols * tile_w, n_rows * tile_h), _BG)
            for i, fr in enumerate(chunk):
                r, c = divmod(i, cols)
                page.paste(_render_tile(fr, tile_w, tile_h), (c * tile_w, r * tile_h))
            page_num = page_idx // per_page + 1
            dest = os.path.join(out_dir, f'{prefix}_scan_{page_num}.jpg')
            page.save(dest, 'JPEG', quality=80)
            page_paths.append(dest)
    except Exception as e:
        logger.warning(f"⚠️  Scan mosaic render failed: {e}")

    stats = {'analyzed': analyzed, 'shown': len(kept),
             'pages': len(page_paths), 'truncated': truncated}
    logger.info(f"🧩 Scan mosaic: {analyzed} analyzed → {len(kept)} distinct "
                f"across {len(page_paths)} page(s){' (truncated)' if truncated else ''}")
    return page_paths, stats


# Scroll-viewport height for the expanded mosaic ≈ 3–4 tile rows at typical report
# width (the page image is scaled to 100% width, so a row renders ~70-90px tall).
# Capped + scrollable so even a many-row window never dominates the report.
MOSAIC_VIEWPORT_PX = 320


def render_mosaic_section(page_urls: List[str], stats: Dict) -> str:
    """Return the report HTML block: a COLLAPSED <details> whose body is a
    height-capped (~3-4 rows), scrollable box of the mosaic page(s).

    - Click the summary → expand/collapse the (capped, scrollable) mosaic.
    - Click any page → full-resolution view: in-page modal when the host report
      defines `openModal` (KPI report does; verification report doesn't), else a
      plain new-tab link (the <a target="_blank"> fallback works everywhere).

    Returns '' when there are no pages.
    """
    if not page_urls:
        return ''
    analyzed = stats.get('analyzed', 0)
    shown = stats.get('shown', 0)
    pages = len(page_urls)
    trunc = ' · ⚠️ sampled (window too large to show every frame)' if stats.get('truncated') else ''
    caption = (f"🧩 Scan mosaic — {analyzed} frames analyzed, {shown} shown across "
               f"{pages} page(s){trunc}")
    # Always-visible legend (inside the default-open <details>, so collapsing it
    # doesn't hide the explanation): the mosaic is a SELECTION, not the full
    # capture set — visually-identical consecutive frames are collapsed to keep
    # it readable. This is a report-display choice only; the KPI value itself is
    # computed from every captured frame in the window, not from this subset.
    # The action / before-match / after-match frames are exempted from collapse
    # (orange border) so the exact transition is always visible even when the
    # surrounding frames were static duplicates.
    legend = (
        '<div style="padding:6px 10px;font-size:11px;line-height:1.6;color:#bbb;'
        'background:#1a1a1a;border-bottom:1px solid #333;">'
        'Only a <strong>selection</strong> of captured frames is shown — frames that look '
        'identical to the previous kept frame are collapsed so the mosaic stays readable. '
        'The underlying KPI time is measured from every captured frame in the window, not '
        'just the ones shown here. Always kept, regardless of duplicates: '
        '<span style="color:#2ecc71;">■</span> matched frame, '
        '<span style="color:#3c8cff;">■</span> verified (pass), '
        '<span style="color:#d22d2d;">■</span> verified (fail), '
        '<span style="color:#ffa500;">■</span> action / frame-before-match / frame-after-match. '
        '<span style="color:#3c3c3c;">■</span> plain border = context frame (duplicates of it were hidden).'
        '</div>'
    )
    thumbs = ''.join(
        f'<a href="{url}" target="_blank" style="text-decoration:none;">'
        f'<img src="{url}" '
        f"onclick=\"if(typeof openModal==='function'){{event.preventDefault();openModal(this.src);}}\" "
        f'alt="Scan mosaic page {i + 1}" '
        f'style="width:100%;display:block;margin:0 0 4px;cursor:zoom-in;" /></a>'
        for i, url in enumerate(page_urls)
    )
    return (
        # Open by default so ~4 rows are visible immediately; the summary toggles
        # it closed for anyone who doesn't want it. Click a frame for full res.
        # Legend sits OUTSIDE the scrolling thumbs box (but still inside <details>)
        # so it stays visible regardless of scroll position while the mosaic is open.
        '<details class="scan-mosaic" open style="margin:14px 0;">'
        f'<summary style="cursor:pointer;font-size:13px;color:#555;user-select:none;">'
        f'{caption} — click to collapse; click a frame for full size</summary>'
        f'<div style="border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;margin-top:8px;">'
        f'{legend}'
        f'<div style="max-height:{MOSAIC_VIEWPORT_PX}px;overflow:auto;background:#111;">{thumbs}</div>'
        '</div>'
        '</details>'
    )
