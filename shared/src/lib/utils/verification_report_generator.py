#!/usr/bin/env python3
"""
Verification Report Generator

Generates minimal HTML debug reports for verifications, plus a single-PNG
evidence composite for AI analysis. Failure reports diagnose why a check
didn't match; success reports (manual verifications only) capture passing
evidence so false positives can be reviewed.
Pattern: Same as KPI failure report (simple HTML with file:// URLs)
"""
import os
import time
from typing import Dict, Optional
from shared.src.lib.utils.cloudflare_utils import convert_to_signed_url


def ensure_signed_url(url: str) -> str:
    """Ensure URL is signed if it's an R2 URL (same pattern as report_step_formatter)."""
    if not url:
        return url
    if 'r2.dev' in url or 'r2.cloudflarestorage.com' in url or url.startswith('reference-images/') or url.startswith('verification/'):
        return convert_to_signed_url(url)
    return url


def _strip_score_text(message: str) -> str:
    """Drop the trailing 'Match score: … (required: …), focus: …' numbers from a
    verification message. The report shows those in dedicated badges, so repeating
    them in the message line is noise. Keeps the descriptive part (which
    reference, which source, and 'but element is NOT focused' on focus failures)."""
    if not message:
        return message
    import re
    msg = re.sub(r'\.?\s*Match score:.*$', '', message, flags=re.IGNORECASE)
    msg = re.sub(r'\s*\(score:[^)]*\)', '', msg, flags=re.IGNORECASE)
    msg = re.sub(r'\s*[—–-]\s*focus:.*$', '', msg, flags=re.IGNORECASE)
    msg = re.sub(r',?\s*focus:.*$', '', msg, flags=re.IGNORECASE)
    return msg.strip()


def _format_box(area: dict, keys) -> str:
    """Format a box as 'x=.., y=.., w=.., h=..' from the given 4 keys, or '' if any missing."""
    kx, ky, kw, kh = keys
    if not isinstance(area, dict) or any(area.get(k) is None for k in keys):
        return ''
    return f"x={int(area[kx])}, y={int(area[ky])}, w={int(area[kw])}, h={int(area[kh])}"


def _fetch_url_as_cv2(url: str):
    """Fetch a remote image (typically R2 signed) and decode it to a BGR ndarray.
    Returns None on failure. Used as a fallback when a panel doesn't have a
    local file path (e.g. reference images that only live on R2).

    Only http/https are allowed: a reference URL can originate from an imported
    .vptree bundle (untrusted), so a `file://` or `http://169.254.169.254/…`
    scheme would otherwise turn this into an SSRF / local-file-read primitive."""
    try:
        import urllib.request
        from urllib.parse import urlparse
        import numpy as np
        import cv2
        if urlparse(url).scheme not in ('http', 'https'):
            print(f"[@verification_report_generator] _fetch_url_as_cv2 refused non-http(s) URL: {url[:80]}")
            return None
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - scheme allowlisted above
            buf = resp.read()
        arr = np.frombuffer(buf, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"[@verification_report_generator] _fetch_url_as_cv2 failed for {url[:80]}: {e}")
        return None


def _build_composite_timeline(frames, width, reader):
    """Horizontal First/Best/Last full-frame strip prepended to the AI composite PNG.

    `frames` is the controller's wait-timeline list (each with a local `full_path`);
    `reader` decodes a path to BGR (the caller's `_read_local`). Each cell is a scaled
    thumbnail captioned 'Label elapsed / score'. Returns a BGR strip of the given width,
    or None when no frame image could be read."""
    import cv2
    import numpy as np

    bg = np.array([21, 17, 14], dtype=np.uint8)
    n = max(1, len(frames))
    pad = 12
    cell_w = max(1, (width - pad * (n + 1)) // n)
    cell_h = 150
    cap_h = 26

    any_img = False
    cells = []
    for fr in frames:
        cell = np.full((cell_h + cap_h, cell_w, 3), bg, dtype=np.uint8)
        img = reader(fr.get('full_path'))
        if img is not None:
            any_img = True
            ih, iw = img.shape[:2]
            s = min(cell_w / iw, cell_h / ih)
            nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
            resized = cv2.resize(img, (nw, nh))
            ox, oy = (cell_w - nw) // 2, cap_h + (cell_h - nh) // 2
            cell[oy:oy + nh, ox:ox + nw] = resized
        cap = (fr.get('label') or '').capitalize()
        elapsed, score = fr.get('elapsed_s'), fr.get('score')
        if isinstance(elapsed, (int, float)):
            cap += f" {elapsed:.1f}s"
        if isinstance(score, (int, float)):
            cap += f" / {score:.2f}"
        cv2.putText(cell, cap, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (230, 230, 230), 1, cv2.LINE_AA)
        cells.append(cell)

    if not any_img:
        return None

    pad_strip = np.full((cell_h + cap_h, pad, 3), bg, dtype=np.uint8)
    row = [pad_strip]
    for c in cells:
        row.extend([c, pad_strip])
    strip = cv2.hconcat(row)
    if strip.shape[1] < width:
        strip = cv2.hconcat([strip, np.full((strip.shape[0], width - strip.shape[1], 3), bg, dtype=np.uint8)])
    elif strip.shape[1] > width:
        strip = strip[:, :width]
    vpad = np.full((pad, width, 3), bg, dtype=np.uint8)
    return cv2.vconcat([strip, vpad])


def _compose_report_image(full, source, reference, overlay,
                          score, threshold, message, search_area,
                          verification_type, searched_text=None,
                          extracted_text=None, focus_score=None,
                          focus_threshold=None, is_success=False):
    """Build the single-PNG analysis composite.

    Used for both failure and success reports — `is_success` only flips the
    leading "Result: PASS/FAIL" footer line so a passing capture (kept for
    false-positive review) is distinguishable at a glance.

    Layout:
        ┌──────────────────────────────────────────────┐
        │  Full screenshot (red rect = search area)    │
        ├────────────┬────────────┬───────────────────┤
        │ Cropped    │ Reference  │ Pixel-diff        │
        │ source     │            │ overlay           │
        └────────────┴────────────┴───────────────────┘
        │  Score / threshold / search area / message   │
        └──────────────────────────────────────────────┘

    Each input is a BGR ndarray or None; missing panels become "(not available)" placeholders.
    """
    import cv2
    import numpy as np

    canvas_w = 1280
    pad = 16
    label_h = 32
    bg = np.array([21, 17, 14], dtype=np.uint8)  # BGR equivalent of #0f1115

    def _label(img, text, w):
        h = img.shape[0]
        padded = np.full((h + label_h, w, 3), bg, dtype=np.uint8)
        x = (w - img.shape[1]) // 2
        padded[label_h:label_h + h, x:x + img.shape[1]] = img
        cv2.putText(padded, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (230, 230, 230), 1, cv2.LINE_AA)
        return padded

    def _placeholder(text, w, h):
        ph = np.full((h, w, 3), bg, dtype=np.uint8)
        cv2.putText(ph, text, (8, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (120, 120, 120), 1, cv2.LINE_AA)
        return ph

    # Row 1 — full screenshot, scaled to canvas_w.
    if full is not None:
        scale = canvas_w / full.shape[1]
        full_resized = cv2.resize(full, (canvas_w, int(full.shape[0] * scale)))
    else:
        full_resized = _placeholder("(no full screenshot)", canvas_w, 360)
    full_panel = _label(full_resized,
                        "Legend : red = crop area, yellow = fuzzy search area",
                        canvas_w)

    # Row 2 — three equal-width panels (source / reference / overlay).
    panel_w = (canvas_w - 2 * pad) // 3
    panel_h = 260

    def _fit(img, label, w, h):
        if img is None:
            return _label(_placeholder("(not available)", w, h), label, w)
        ih, iw = img.shape[:2]
        s = min(w / iw, h / ih)
        nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
        resized = cv2.resize(img, (nw, nh))
        bgcell = np.full((h, w, 3), bg, dtype=np.uint8)
        ox, oy = (w - nw) // 2, (h - nh) // 2
        bgcell[oy:oy + nh, ox:ox + nw] = resized
        return _label(bgcell, label, w)

    src_panel = _fit(source, "Cropped source", panel_w, panel_h)
    ref_panel = _fit(reference, "Reference", panel_w, panel_h)
    ovl_panel = _fit(overlay, "Pixel-diff overlay", panel_w, panel_h)
    pad_strip_h = np.full((panel_h + label_h, pad, 3), bg, dtype=np.uint8)
    row2 = cv2.hconcat([src_panel, pad_strip_h, ref_panel, pad_strip_h, ovl_panel])

    # Footer — metadata text.
    # Image and text both surface "Score / Required" identically (text scoring
    # mirrors image since the OCR matcher returns 0.0-1.0 with 1.0 = exact
    # substring). Text additionally lists searched/extracted to make the OCR
    # miss visually inspectable without opening the HTML report.
    footer_lines = []
    footer_lines.append(f"Result: {'PASS' if is_success else 'FAIL'}")
    if verification_type in ('image', 'text') and (score is not None or threshold is not None):
        s_str = f"{score:.3f}" if score is not None else "n/a"
        t_str = f"{threshold:.3f}" if threshold is not None else "n/a"
        footer_lines.append(f"Score: {s_str}   Required: {t_str}   Type: {verification_type}")
    elif verification_type == 'text':
        footer_lines.append("Type: text")
    # Focus detection line (only when the reference was captured with Focus).
    # A focus failure is the "matched but not selected" case — show it explicitly.
    if focus_score is not None:
        ft_str = f"{focus_threshold:.3f}" if focus_threshold is not None else "n/a"
        footer_lines.append(f"Focus: {focus_score:.3f}   Required: {ft_str}")
    if verification_type == 'text':
        if searched_text:
            footer_lines.append(f"Searched: {searched_text[:140]}")
        if extracted_text is not None:
            ex = extracted_text if extracted_text else "(empty)"
            footer_lines.append(f"Extracted: {ex[:140]}")
    # Search area split into clear lines: Crop area (exact box) + Search (fuzzy).
    if isinstance(search_area, dict):
        crop_box = _format_box(search_area, ('x', 'y', 'width', 'height'))
        if crop_box:
            footer_lines.append(f"Crop area: {crop_box}")
        fuzzy_box = _format_box(search_area, ('fx', 'fy', 'fwidth', 'fheight'))
        if fuzzy_box:
            footer_lines.append(f"Search (fuzzy): {fuzzy_box}")
    elif search_area:
        footer_lines.append(f"Search area: {search_area}")
    if message and verification_type != 'text':
        m = message if len(message) <= 160 else message[:157] + '...'
        footer_lines.append(m)

    footer_lines = footer_lines[:7]
    footer_h = 24 + 24 * max(1, len(footer_lines))
    footer = np.full((footer_h, canvas_w, 3), bg, dtype=np.uint8)
    for i, line in enumerate(footer_lines):
        cv2.putText(footer, line, (8, 24 + i * 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)

    # Stack rows. Pad widths defensively in case row2 doesn't divide evenly.
    rows = [full_panel, row2, footer]
    max_w = max(r.shape[1] for r in rows)
    rows_p = []
    for r in rows:
        if r.shape[1] < max_w:
            extra = np.full((r.shape[0], max_w - r.shape[1], 3), bg, dtype=np.uint8)
            r = cv2.hconcat([r, extra])
        rows_p.append(r)
    pad_strip_v = np.full((pad, max_w, 3), bg, dtype=np.uint8)
    return cv2.vconcat([rows_p[0], pad_strip_v, rows_p[1], pad_strip_v, rows_p[2]])


def generate_verification_composite(verification_config: Dict,
                                    verification_result: Dict,
                                    cold_base: str,
                                    timestamp_ms: str,
                                    is_success: bool = False) -> Optional[str]:
    """Save a single PNG composite next to the HTML report.

    Designed for AI consumption: one Read call returns the entire evidence
    pack (full screenshot with the search-area outline, cropped source,
    reference, pixel-diff overlay, plus score / threshold / search-area
    metadata). The HTML report stays the canonical link for human reviewers.

    `is_success` selects the filename prefix and the PASS/FAIL footer line —
    success composites exist so false positives (a verification that passed
    but shouldn't have) can be inspected with the same evidence pack.

    Output path: `<cold_base>/verification_<success|failure>_<timestamp_ms>.png`.
    Returns the local path, or None if the composite couldn't be built.
    """
    try:
        import os
        import cv2

        details = verification_result.get('details') or {}
        verification_type = verification_config.get('verification_type', 'unknown')

        # Local paths first; fall back to fetching R2 when a panel is missing.
        original_path = (verification_config.get('original_image_path')
                         or details.get('original_image_path'))
        source_path = (verification_config.get('source_image_path')
                       or details.get('source_image_path'))
        reference_path = (details.get('reference_image_path')
                          or verification_config.get('reference_image_path'))
        overlay_path = details.get('result_overlay_path')

        def _read_local(path):
            if not path:
                return None
            try:
                if not os.path.exists(path):
                    return None
                return cv2.imread(path)
            except Exception:
                return None

        full = _read_local(original_path)
        source = _read_local(source_path)
        reference = _read_local(reference_path)
        overlay = _read_local(overlay_path)

        # Reference often only lives on R2 — fetch when needed.
        if reference is None:
            ref_url = details.get('reference_image_url')
            if ref_url:
                reference = _fetch_url_as_cv2(ensure_signed_url(ref_url))

        # Bail if we have effectively nothing to show.
        if full is None and source is None and reference is None and overlay is None:
            print("[@verification_report_generator] Composite skipped: no panels available")
            return None

        # Draw the search-area rectangles on the full screenshot for context.
        # Red = exact crop area (x/y/width/height). Yellow = fuzzy search area
        # (fx/fy/fwidth/fheight) when defined — this is the larger region OpenCV
        # actually scanned for the template match.
        params = verification_config.get('params') or {}
        resolved_area = (verification_config.get('resolved_area')
                         or details.get('resolved_area')
                         or params.get('area'))
        if full is not None and isinstance(resolved_area, dict):
            from shared.src.lib.utils.image_overlay_utils import draw_search_area_rectangles
            draw_search_area_rectangles(full, resolved_area)

        composite = _compose_report_image(
            full, source, reference, overlay,
            score=verification_result.get('matching_result'),
            threshold=verification_result.get('threshold'),
            message=_strip_score_text(verification_result.get('message', '')),
            search_area=resolved_area,
            verification_type=verification_type,
            searched_text=verification_result.get('searchedText'),
            extracted_text=verification_result.get('extractedText'),
            focus_score=details.get('focus_score', verification_result.get('focusScore')),
            focus_threshold=details.get('focus_threshold', verification_result.get('focusThreshold')),
            is_success=is_success,
        )

        # Prepend a wait-timeline thumbnail strip (first/best/last) for polled failures,
        # so a single Read of the composite shows how the screen evolved during the wait.
        frames = details.get('frames') if isinstance(details, dict) else None
        if isinstance(frames, list) and len(frames) >= 2:
            try:
                strip = _build_composite_timeline(frames, composite.shape[1], _read_local)
                if strip is not None:
                    composite = cv2.vconcat([strip, composite])
            except Exception as tl_err:
                print(f"[@verification_report_generator] Composite timeline strip skipped: {tl_err}")

        outcome = 'success' if is_success else 'failure'
        composite_path = os.path.join(cold_base, f'verification_{outcome}_{timestamp_ms}.png')
        cv2.imwrite(composite_path, composite, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        print(f"[@verification_report_generator] Composite PNG written: {composite_path}")
        return composite_path
    except Exception as e:
        print(f"[@verification_report_generator] Composite generation failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def _generate_verification_report(
    verification_config: Dict,
    verification_result: Dict,
    device_folder: str,
    host_info: Dict,
    is_success: bool = False
) -> Optional[str]:
    """
    Generate HTML report for a verification with images and processing details.

    Shared by `generate_verification_failure_report` and
    `generate_verification_success_report`. `is_success` flips the title,
    accent colour (red→green), filename prefix and the PASS/FAIL composite —
    everything else (layout, image panels, chips) is identical so both reports
    read the same way. Success reports exist to inspect false positives: a
    verification that passed but whose evidence looks wrong.

    Args:
        verification_config: Verification config (command, params, type, source_image_path)
        verification_result: Verification result (success, threshold, matching_score, etc.)
        device_folder: Device folder name (e.g., 'capture4')
        host_info: Host information dict for URL building (from get_host_info_for_report)
        is_success: True for a passing-verification report, False for a failure report.

    Returns:
        Local path to report HTML file, or None if generation failed.
        Frontend will convert local path to HTTP URL using buildHostImageUrl().
    """
    try:
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
        from shared.src.lib.utils.build_url_utils import buildHostImageUrl

        outcome = 'success' if is_success else 'failure'
        outcome_title = 'Verification Success' if is_success else 'Verification Failure'
        # Accent colour drives the header message banner + the "Match" score badge.
        accent = '#51cf66' if is_success else '#ff6b6b'
        accent_rgba = 'rgba(81,207,102,0.08)' if is_success else 'rgba(255,107,107,0.08)'
        msg_text_color = '#d0f0d6' if is_success else '#f0d0d0'

        # Save report under reports/ subfolder so it's served by host_stream_routes
        cold_base = get_cold_storage_path(device_folder, 'reports')
        os.makedirs(cold_base, exist_ok=True)
        timestamp = str(int(time.time() * 1000))
        report_filename = f'verification_{outcome}_{timestamp}.html'
        report_path = os.path.join(cold_base, report_filename)

        print(f"[@verification_report_generator] Generating {outcome} report: {report_path}")
        
        # Get details
        details = verification_result.get('details', {})
        verification_type = verification_config.get('verification_type', 'unknown')
        command = verification_config.get('command', 'unknown')
        
        # Get image URLs - all uploaded to R2 by verification_executor before calling this function
        # Runtime-truth values: what the matcher actually used (from details), not the
        # potentially-stale params.area in the navigation edge config.
        resolved_area = verification_config.get('resolved_area') or details.get('resolved_area')
        match_location = verification_config.get('match_location') or details.get('match_location')

        # Source image (cropped): R2 URL from details
        source_image_url = details.get('source_image_url')
        if source_image_url:
            print(f"[@verification_report_generator] Source: Using R2 URL: {source_image_url}")
        else:
            # Fallback to local path conversion (should rarely happen)
            source_image_path = verification_config.get('source_image_path') or details.get('source_image_path')
            source_image_url = buildHostImageUrl(host_info, source_image_path) if source_image_path else None
            print(f"[@verification_report_generator] Source: Using host-served URL (R2 upload may have failed)")
        
        # Original image (with crop rectangle overlay): R2 URL from details
        original_image_url = details.get('original_image_url')
        crop_area = verification_config.get('crop_area')
        if original_image_url:
            print(f"[@verification_report_generator] Original: Using R2 URL: {original_image_url}")
        else:
            # Fallback to local path conversion (should rarely happen)
            original_image_path = verification_config.get('original_image_path')
            original_image_url = buildHostImageUrl(host_info, original_image_path) if original_image_path else None
            print(f"[@verification_report_generator] Original: Using host-served URL (R2 upload may have failed)")
        
        # Reference image: R2 URL from details
        reference_image_url = details.get('reference_image_url')
        if reference_image_url:
            print(f"[@verification_report_generator] Reference: Using R2 URL: {reference_image_url}")
        
        # Result overlay image: R2 URL from details
        result_overlay_url = details.get('result_overlay_url')
        if result_overlay_url:
            print(f"[@verification_report_generator] Overlay: Using R2 URL: {result_overlay_url}")
        else:
            # Fallback to local path conversion (should rarely happen)
            result_overlay_path = details.get('result_overlay_path')
            result_overlay_url = buildHostImageUrl(host_info, result_overlay_path) if result_overlay_path else None
            if result_overlay_url:
                print(f"[@verification_report_generator] Overlay: Using host-served URL (R2 upload may have failed)")
        
        # Sign URLs for HTML report that are not already signed when uploaded
        # Reference images come from reference-images/ folder with public URLs
        # Original image may also need signing
        if reference_image_url:
            reference_image_url = ensure_signed_url(reference_image_url)
            print(f"[@verification_report_generator] Reference image URL signed for HTML report")
        if original_image_url:
            original_image_url = ensure_signed_url(original_image_url)
            print(f"[@verification_report_generator] Original image URL signed for HTML report")
        
        # Pre-compute score data for hero banner
        threshold = verification_result.get('threshold')
        matching_score = verification_result.get('matching_result')
        # Focus detection (present only when the reference was captured with Focus).
        focus_score = details.get('focus_score', verification_result.get('focusScore'))
        focus_threshold = details.get('focus_threshold', verification_result.get('focusThreshold'))
        params = verification_config.get('params', {})
        # Strip the score/focus numbers — they're shown in the badges (top-right).
        message = _strip_score_text(verification_result.get('message', '')) or 'N/A'

        # Format timestamp as readable datetime (timestamp is ms-since-epoch as string)
        try:
            from datetime import datetime
            time_display = datetime.fromtimestamp(int(timestamp) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            time_display = timestamp

        # Build modern side-by-side comparison HTML
        html = ['<!DOCTYPE html><html><head><meta charset="UTF-8">']
        html.append(f'<title>{outcome_title} Report</title>')
        html.append('<style>')
        html.append('*{box-sizing:border-box}')
        html.append('body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:12px 24px 24px 24px;background:#0f1115;color:#e6e6e6;max-width:1600px;margin:0 auto}')
        # 3-column header: title (left), failure message (middle), score badges (right) — all vertically centered.
        html.append('.header{display:grid;grid-template-columns:auto 1fr auto;gap:20px;align-items:center;margin-bottom:10px}')
        html.append('.header h1{font-size:22px;margin:0 0 4px 0;font-weight:600}')
        html.append('.header .subtitle{color:#888;font-size:13px}')
        html.append(f'.header-msg{{font-size:13px;line-height:1.4;color:{msg_text_color};background:{accent_rgba};border-left:3px solid {accent};padding:8px 14px;border-radius:6px}}')
        html.append('.score-grid{display:flex;gap:10px}')
        html.append('.score-card{background:#1a1d24;border:1px solid #2a2f38;padding:8px 14px;border-radius:8px;text-align:center;min-width:80px}')
        html.append('.score-card .label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:2px}')
        html.append('.score-card .value{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}')
        html.append('.score-required .value{color:#888}')
        html.append(f'.score-actual .value{{color:{accent}}}')
        html.append('.score-focus .value{color:#ab47bc}')
        # Per-metric pass/fail colouring: a measured value (Match / Focus) is green
        # when it clears its own threshold, red when it doesn't — independent of the
        # overall result accent (e.g. Match can pass while Focus fails the verify).
        html.append('.score-pass .value{color:#4caf50}')
        html.append('.score-fail .value{color:#ff3b3b}')
        html.append('.meta-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}')
        html.append('.chip{background:#1a1d24;border:1px solid #2a2f38;padding:6px 12px;border-radius:16px;font-size:12px;color:#bbb}')
        html.append('.chip b{color:#fff;font-weight:500}')
        # Two-column layout: left = full screenshot (scaled), right = stacked native-size comparison rows.
        # Right column is a FIXED width so the report layout doesn't jump around with the
        # cropped-source size; oversized crops scroll inside their cell (img-wrap:overflow:auto).
        html.append('.layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:20px;align-items:start;margin-bottom:24px}')
        html.append('.layout .right{display:flex;flex-direction:column;gap:12px}')
        html.append('.cell{background:#1a1d24;border:1px solid #2a2f38;border-radius:8px;padding:12px;display:flex;flex-direction:column}')
        html.append('.cell .cap{font-size:11px;color:#bbb;margin-bottom:8px;font-weight:500;text-transform:uppercase;letter-spacing:1px}')
        html.append('.cell .img-wrap{display:flex;align-items:flex-start;justify-content:flex-start;background:#000;border-radius:4px;overflow:auto}')
        html.append('.cell img{display:block;cursor:zoom-in}')
        html.append('.cell.empty .img-wrap{color:#555;font-size:12px;font-style:italic;min-width:120px;min-height:60px;align-items:center;justify-content:center;padding:16px}')
        # Right column: native pixel size so the red rectangle on the full screenshot maps 1:1 to the cropped/reference content.
        html.append('.layout .right .cell img{max-width:none;max-height:none;width:auto;height:auto;image-rendering:pixelated}')
        # Left column: full screenshot scaled to fit its column width (1080p capture won't fit otherwise).
        html.append('.layout .left .cell .img-wrap{align-items:center;justify-content:center;min-height:160px}')
        html.append('.layout .left .cell img{max-width:100%;height:auto}')
        html.append('.details{background:#1a1d24;border:1px solid #2a2f38;border-radius:8px;padding:16px 20px}')
        html.append('.details dt{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-top:12px}')
        html.append('.details dt:first-child{margin-top:0}')
        html.append('.details dd{margin:4px 0 0 0;font-size:13px;color:#e6e6e6;font-variant-numeric:tabular-nums}')
        html.append('.details dd code{background:#0f1115;padding:2px 6px;border-radius:3px;font-size:12px;color:#7fc7f5}')
        # Wait-timeline strip (only rendered for polled waitFor* failures with >=2 frames).
        html.append('.timeline{display:flex;gap:12px;margin:0 0 16px}')
        html.append('.tl-item{flex:1;background:#1a1d24;border:1px solid #2a2f38;border-radius:8px;padding:8px;cursor:pointer}')
        html.append('.tl-item.sel{border-color:#3d6ea5;box-shadow:0 0 0 1px #3d6ea5 inset}')
        html.append('.tl-item .hd{display:flex;justify-content:space-between;font-size:11px;color:#9aa3b2;margin-bottom:6px}')
        html.append('.tl-item .hd .sc{font-weight:700}')
        html.append('.tl-item.best .hd .sc{color:#ffd13b}')
        html.append('.tl-item img{display:block;width:100%;height:auto;border-radius:4px;background:#000}')
        html.append('.tl-empty{font-size:11px;color:#555;font-style:italic;padding:18px 4px;text-align:center}')
        html.append('.legend{font-size:11px;color:#7f8896;margin-top:6px}')
        html.append('.legend .r{color:#ff3b3b}.legend .y{color:#ffd13b}')
        html.append('.extracted{font-size:13px;color:#e6e6e6;background:#0f1115;border:1px solid #2a2f38;border-radius:4px;padding:8px 10px;word-break:break-word;min-height:20px;font-variant-numeric:tabular-nums}')
        html.append('@media (max-width:900px){.layout{grid-template-columns:1fr}.header{grid-template-columns:1fr}}')
        html.append('</style></head><body>')

        # Header: title left · result message middle · score badges right (single row, vertically centered)
        html.append('<div class="header">')
        html.append('<div>')
        html.append(f'<h1>{outcome_title}</h1>')
        html.append(f'<div class="subtitle">{verification_type} · {command}</div>')
        html.append('</div>')
        # Middle: the failure message (replaces the standalone banner row)
        if message and message != 'N/A':
            html.append(f'<div class="header-msg">{message}</div>')
        else:
            html.append('<div></div>')  # placeholder so the score-grid stays right-aligned
        # Score badges render for both image and text — text scoring uses the
        # same 0.0-1.0 scale (1.0 = exact substring after normalization), so
        # "Match X / Required Y" reads identically in both reports.
        if verification_type in ('image', 'text') and (threshold is not None or matching_score is not None):
            # Scores are 0.0-1.0 (1.0 = exact). Show as percent and colour each
            # measured value by whether it clears its own threshold.
            def _pct(v):
                return f"{v * 100:.0f}%"
            html.append('<div class="score-grid">')
            if matching_score is not None:
                # Green when the match clears Required; red otherwise. Fall back to
                # the result accent when there's no threshold to compare against.
                match_cls = ('score-pass' if matching_score >= threshold else 'score-fail') \
                    if threshold is not None else 'score-actual'
                html.append(f'<div class="score-card {match_cls}"><div class="label">Match</div><div class="value">{_pct(matching_score)}</div></div>')
            if threshold is not None:
                html.append(f'<div class="score-card score-required"><div class="label">Required</div><div class="value">{_pct(threshold)}</div></div>')
            # Focus badges — surface "matched but not selected" failures explicitly.
            if focus_score is not None:
                focus_cls = ('score-pass' if (focus_threshold is not None and focus_score >= focus_threshold)
                             else 'score-fail')
                html.append(f'<div class="score-card {focus_cls}"><div class="label">Focus</div><div class="value">{_pct(focus_score)}</div></div>')
                if focus_threshold is not None:
                    html.append(f'<div class="score-card score-required"><div class="label">Focus Req</div><div class="value">{_pct(focus_threshold)}</div></div>')
            html.append('</div>')
        html.append('</div>')

        # Meta chips
        html.append('<div class="meta-row">')
        html.append(f'<span class="chip"><b>Time:</b> {time_display}</span>')
        # Timeout — only meaningful for waitFor* polling verifications (image
        # AND text). `params['timeout']` is milliseconds, with `0` meaning
        # "single-shot, no polling". Showing it makes it obvious whether a
        # verification failure was given enough time to observe the screen
        # transition, which is the #1 diagnostic question when a navigation
        # step's verify_node says "Text pattern X not found (score 0.400)":
        # did we even wait, or did we fire the OCR a frame too early?
        if verification_type in ('image', 'text'):
            timeout_ms = params.get('timeout')
            try:
                timeout_ms_int = int(timeout_ms) if timeout_ms is not None else 0
            except (TypeError, ValueError):
                timeout_ms_int = 0
            if timeout_ms_int > 0:
                timeout_label = (
                    f"{timeout_ms_int / 1000:.1f}s"
                    if timeout_ms_int >= 1000 else f"{timeout_ms_int}ms"
                )
                html.append(f'<span class="chip"><b>Timeout:</b> {timeout_label}</span>')
            else:
                # Distinguish "no polling configured" from "polled and gave up"
                # — same diagnostic question, different answer.
                html.append('<span class="chip"><b>Timeout:</b> single-shot (no polling)</span>')
        if verification_type == 'image':
            html.append(f'<span class="chip"><b>Filter:</b> {details.get("image_filter", "none")}</span>')
            area_dict = resolved_area or params.get('area') or {}
            # Crop area — the exact reference box.
            crop_box = _format_box(area_dict, ('x', 'y', 'width', 'height'))
            if crop_box:
                html.append(f'<span class="chip"><b>Crop area:</b> {crop_box}</span>')
            # Search area (fuzzy) — the larger region OpenCV actually scanned.
            fuzzy_box = _format_box(area_dict, ('fx', 'fy', 'fwidth', 'fheight'))
            if fuzzy_box:
                html.append(f'<span class="chip"><b>Search area (fuzzy):</b> {fuzzy_box}</span>')
            # Focus — the learned "selected" accent params.
            focus_cfg = area_dict.get('focus') if isinstance(area_dict, dict) else None
            if isinstance(focus_cfg, dict):
                html.append(
                    f'<span class="chip"><b>Focus:</b> hue={focus_cfg.get("hue")}, '
                    f'threshold={focus_cfg.get("threshold")}, band={focus_cfg.get("band_frac")}</span>'
                )
            # Matched at — where the template actually landed (fuzzy match can shift).
            if match_location:
                matched_box = _format_box(match_location, ('x', 'y', 'width', 'height'))
                html.append(f'<span class="chip"><b>Matched at:</b> {matched_box or match_location}</span>')
        elif verification_type == 'text':
            if verification_result.get('detected_language'):
                html.append(f'<span class="chip"><b>Language:</b> {verification_result.get("detected_language")}</span>')
            lang_confidence = verification_result.get("language_confidence")
            if lang_confidence is not None:
                html.append(f'<span class="chip"><b>Lang Confidence:</b> {lang_confidence:.2f}</span>')
        html.append('</div>')

        # Full analysed-window mosaic (failures with a polled window of >=5 frames).
        # Built + uploaded by the executor and stashed on details; rendered here so the
        # report shows EVERY frame the verifier checked, not just first/best/last.
        _mosaic_section = details.get('scan_mosaic_section', '') if isinstance(details, dict) else ''
        if _mosaic_section:
            html.append(_mosaic_section)

        def _esc(s):
            """Minimal HTML-escape for text rendered server-side into a cell."""
            return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        has_any_image = any([source_image_url, original_image_url, reference_image_url, result_overlay_url])

        # Wait-timeline frames: present only for polled waitFor* verifications. Each
        # carries its own full frame + crop (+ overlay for image, extracted text for
        # text). When we have >=2, render Layout A — a First/Best/Last strip above a
        # synced hero — instead of the single-frame comparison.
        import json
        raw_frames = details.get('frames') if isinstance(details, dict) else None
        tl_frames = []
        if isinstance(raw_frames, list) and len(raw_frames) >= 2:
            for fr in raw_frames:
                tl_frames.append({
                    'label': fr.get('label'),
                    # Full frame is signed like the single-frame original; crop/overlay
                    # come from the same uploader and are used as-is (mirrors below).
                    'full': ensure_signed_url(fr.get('full_url')) if fr.get('full_url') else '',
                    'source': fr.get('source_url') or '',
                    'overlay': fr.get('overlay_url') or '',
                    'score': fr.get('score'),
                    'elapsed_s': fr.get('elapsed_s'),
                    'text': fr.get('extracted_text'),
                })
        use_timeline = bool(tl_frames) and any(f['full'] or f['source'] for f in tl_frames)

        if use_timeline:
            sel_idx = next((i for i, f in enumerate(tl_frames) if f['label'] == 'best'), 0)

            # Timeline strip — First / Best / Last full-frame thumbnails, click to load.
            html.append('<div class="timeline">')
            for i, f in enumerate(tl_frames):
                cls = 'tl-item'
                if f['label'] == 'best':
                    cls += ' best'
                if i == sel_idx:
                    cls += ' sel'
                lbl = (f['label'] or '').capitalize()
                sc = f"{f['score']:.2f}" if isinstance(f['score'], (int, float)) else 'n/a'
                el = f"{f['elapsed_s']:.1f}s" if isinstance(f['elapsed_s'], (int, float)) else ''
                html.append(f'<div class="{cls}" id="tl-{i}" onclick="selFrame({i})">')
                html.append(f'<div class="hd"><span>{lbl} · {el}</span><span class="sc">{sc}</span></div>')
                thumb = f['full'] or f['source']
                if thumb:
                    html.append(f'<img src="{thumb}" alt="{lbl} frame">')
                else:
                    html.append('<div class="tl-empty">no image</div>')
                html.append('</div>')
            html.append('</div>')

            # Synced hero — full frame (left) + crop / reference / overlay-or-text (right).
            html.append('<div class="layout">')
            html.append('<div class="left"><div class="cell">')
            html.append('<div class="cap" id="hero-cap">Full frame</div>')
            html.append('<div class="img-wrap"><a id="hero-full-link" href="#" target="_blank"><img id="hero-full" src="" alt="Full frame"></a></div>')
            html.append('<div class="legend">Legend: <span class="r">red</span> = exact crop area &nbsp; <span class="y">yellow</span> = fuzzy search area</div>')
            html.append('</div></div>')
            html.append('<div class="right">')
            html.append('<div class="cell"><div class="cap">Cropped source</div><div class="img-wrap"><a id="hero-src-link" href="#" target="_blank"><img id="hero-src" src="" alt="Cropped source"></a></div></div>')
            if reference_image_url:
                html.append(f'<div class="cell"><div class="cap">Reference</div><div class="img-wrap"><a href="{reference_image_url}" target="_blank"><img src="{reference_image_url}" alt="Reference"></a></div></div>')
            if verification_type == 'text':
                # No reference image / pixel-diff for text — show the searched pattern
                # (constant) and the text found in THIS frame (swapped by the timeline).
                html.append(f'<div class="cell"><div class="cap">Searched text</div><div class="extracted">{_esc(verification_result.get("searchedText", "") or "(none)")}</div></div>')
                html.append('<div class="cell"><div class="cap">Found text (this frame)</div><div class="extracted" id="hero-extracted"></div></div>')
            else:
                html.append('<div class="cell"><div class="cap">Pixel-diff overlay</div><div class="img-wrap"><a id="hero-ovl-link" href="#" target="_blank"><img id="hero-ovl" src="" alt="Match overlay"></a></div></div>')
            html.append('</div>')  # /.right
            html.append('</div>')  # /.layout

            # Hero-swap JS — reads the embedded frame data.
            html.append('<script>')
            # Escape "</" so OCR/extracted text in the payload can't close the <script> tag.
            frames_json = json.dumps(tl_frames).replace('</', '<\\/')
            html.append(f'const FRAMES={frames_json};const VTYPE={json.dumps(verification_type)};')
            html.append('function setImg(imgId,linkId,url){var img=document.getElementById(imgId),link=document.getElementById(linkId);if(!img)return;'
                         'if(url){img.src=url;img.style.display="block";if(link)link.href=url;}else{img.removeAttribute("src");img.style.display="none";if(link)link.removeAttribute("href");}}')
            html.append('function selFrame(i){var f=FRAMES[i];if(!f)return;'
                         'var items=document.querySelectorAll(".tl-item");for(var j=0;j<items.length;j++){items[j].classList.toggle("sel",j===i);}'
                         'var cap=(f.label||"").charAt(0).toUpperCase()+(f.label||"").slice(1);'
                         'var sc=(typeof f.score==="number")?f.score.toFixed(2):"n/a";'
                         'var el=(typeof f.elapsed_s==="number")?f.elapsed_s.toFixed(1)+"s":"";'
                         'document.getElementById("hero-cap").textContent="Full frame — "+cap+" · "+el+" · score "+sc;'
                         'setImg("hero-full","hero-full-link",f.full);setImg("hero-src","hero-src-link",f.source);'
                         'if(VTYPE==="text"){var e=document.getElementById("hero-extracted");if(e)e.textContent=f.text||"(empty)";}'
                         'else{setImg("hero-ovl","hero-ovl-link",f.overlay);}}')
            html.append(f'selFrame({sel_idx});')
            html.append('</script>')

        elif has_any_image:
            # Two-column layout: full screenshot on the left, stacked comparison on the right.
            html.append('<div class="layout">')

            # LEFT: full captured screenshot (scaled to column width).
            html.append('<div class="left">')
            if original_image_url:
                html.append('<div class="cell">')
                html.append(f'<div class="img-wrap"><a href="{original_image_url}" target="_blank"><img src="{original_image_url}" alt="Full screenshot"></a></div>')
                html.append('</div>')
            elif verification_type == 'image':
                html.append('<div class="cell empty"><div class="img-wrap">not available</div></div>')
            html.append('</div>')

            # RIGHT: stacked native-size comparison (cropped source / reference / overlay).
            html.append('<div class="right">')
            # Cropped source
            if source_image_url:
                html.append('<div class="cell">')
                html.append('<div class="cap">Cropped source</div>')
                html.append(f'<div class="img-wrap"><a href="{source_image_url}" target="_blank"><img src="{source_image_url}" alt="Cropped source"></a></div>')
                html.append('</div>')
            else:
                html.append('<div class="cell empty"><div class="cap">Cropped source</div><div class="img-wrap">not available</div></div>')
            if verification_type == 'text':
                # Text has no reference image / pixel-diff overlay — show the searched
                # pattern and the text we actually found instead of empty image cells.
                html.append(f'<div class="cell"><div class="cap">Searched text</div><div class="extracted">{_esc(verification_result.get("searchedText", "") or "(none)")}</div></div>')
                html.append(f'<div class="cell"><div class="cap">Found text</div><div class="extracted">{_esc(verification_result.get("extractedText", "") or "(empty)")}</div></div>')
            else:
                # Reference
                if reference_image_url:
                    html.append('<div class="cell">')
                    html.append('<div class="cap">Reference</div>')
                    html.append(f'<div class="img-wrap"><a href="{reference_image_url}" target="_blank"><img src="{reference_image_url}" alt="Reference"></a></div>')
                    html.append('</div>')
                else:
                    html.append('<div class="cell empty"><div class="cap">Reference</div><div class="img-wrap">not available</div></div>')
                # Pixel-diff overlay
                if result_overlay_url:
                    html.append('<div class="cell">')
                    html.append('<div class="cap">Pixel-diff overlay</div>')
                    html.append(f'<div class="img-wrap"><a href="{result_overlay_url}" target="_blank"><img src="{result_overlay_url}" alt="Match overlay"></a></div>')
                    html.append('</div>')
                else:
                    html.append('<div class="cell empty"><div class="cap">Pixel-diff overlay</div><div class="img-wrap">not available</div></div>')
            html.append('</div>')

            html.append('</div>')  # /.layout

        # Searched/found text now render in the top-right comparison column for text
        # verifications (both timeline and single-shot), so no separate section here.

        html.append('</body></html>')
        
        # Write file
        with open(report_path, 'w') as f:
            f.write('\n'.join(html))

        # Build HTTP URL for the report (for logging)
        report_url = buildHostImageUrl(host_info, report_path)

        print(f"[@verification_report_generator] {outcome.capitalize()} report generated: {report_path}")
        print(f"[@verification_report_generator] Report URL: {report_url}")

        # Also drop a single PNG composite next to the HTML for AI analysis.
        # Best-effort: a composite failure must never block the HTML report.
        try:
            generate_verification_composite(
                verification_config=verification_config,
                verification_result=verification_result,
                cold_base=cold_base,
                timestamp_ms=timestamp,
                is_success=is_success,
            )
        except Exception as composite_err:
            print(f"[@verification_report_generator] Composite (non-fatal) error: {composite_err}")

        # Return local path only - frontend will convert to HTTP URL
        return report_path

    except Exception as e:
        print(f"[@verification_report_generator] Failed to generate verification {('success' if is_success else 'failure')} report: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_verification_failure_report(
    verification_config: Dict,
    verification_result: Dict,
    device_folder: str,
    host_info: Dict
) -> Optional[str]:
    """Generate the HTML failure report (thin wrapper, see _generate_verification_report)."""
    return _generate_verification_report(
        verification_config, verification_result, device_folder, host_info,
        is_success=False,
    )


def generate_verification_success_report(
    verification_config: Dict,
    verification_result: Dict,
    device_folder: str,
    host_info: Dict
) -> Optional[str]:
    """Generate the HTML success report — same layout as the failure report,
    used to inspect false positives (a verification that passed but whose
    captured evidence looks wrong)."""
    return _generate_verification_report(
        verification_config, verification_result, device_folder, host_info,
        is_success=True,
    )

