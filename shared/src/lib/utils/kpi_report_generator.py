#!/usr/bin/env python3
"""
KPI Report Generator Utilities

Handles generation of both success and failure KPI reports.
Extracted from kpi_executor.py to reduce file size and improve maintainability.
"""

import os
import json
import time
import shutil
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# The frame selector caps how many analyzed frames get full evidence uploads
# (source crop + search-area overlay per reference, per frame). kpi_executor
# already samples probes to MAX_REPORTED_PROBES=16 for the mosaic; evidence
# images are heavier than mosaic tiles, so the selector re-samples down to 8 —
# always keeping the most recent frame and every passing frame.
MAX_EVIDENCE_FRAMES = 8


def _build_verification_section(request, evidence_list, working_dir, timestamp,
                                default_overlay_frame=None, placeholder=''):
    """Build the report's "Verification (N)" section HTML.

    Returns ``(section_html, verification_count)`` where the count is the
    number of references (card slots), not frames.

    Two shapes, decided by the evidence annotations kpi_executor attached:

    - Single-frame evidence (no ``frame_index`` on the items — e.g. the
      legacy match-frame-only list, or an early failure's last attempt):
      renders one card per reference, exactly as before.

    - Multi-frame evidence (the scan probed several captures, each item
      tagged with frame_index/frame_offset/capture_path/frame_success):
      renders one card SLOT per reference plus a frame-selector chip strip —
      most recent frame LEFTMOST and pre-selected. Every frame's cards are
      pre-rendered server-side with the same ``create_verification_card``
      renderer and embedded as JSON; an inline script swaps slot contents on
      chip click. The search-area overlay is drawn on each frame's OWN
      capture (``capture_path``), falling back to ``default_overlay_frame``.
      Overlays are written as JPEG (captures are video frames — PNG would be
      ~5-10x larger for no benefit at this size).
    """
    from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails
    from shared.src.lib.utils.image_overlay_utils import render_search_area_overlay
    from shared.src.lib.utils.kpi_report_template import (
        create_verification_card, create_frame_selector_section,
    )

    if not evidence_list:
        return '', 0

    # Group items by the frame they were probed on. Unannotated items all land
    # under None → single-frame mode.
    by_frame: Dict = {}
    for ev in evidence_list:
        by_frame.setdefault(ev.get('frame_index'), []).append(ev)
    if len(by_frame) > 1:
        by_frame.pop(None, None)  # drop unannotated strays in multi mode

    def _frame_ok(items) -> bool:
        return bool(items and items[0].get('frame_success', items[0].get('success')))

    frame_ids = sorted(k for k in by_frame if k is not None)
    if not frame_ids:  # single-frame legacy list
        frames = [(None, evidence_list)]
    else:
        # Cap the selector: evenly sample, force-keep the most recent frame and
        # every passing frame (a dropped pass would hide the money shot).
        if len(frame_ids) > MAX_EVIDENCE_FRAMES:
            step = len(frame_ids) / float(MAX_EVIDENCE_FRAMES)
            kept = {frame_ids[int(k * step)] for k in range(MAX_EVIDENCE_FRAMES)}
            kept.add(frame_ids[-1])
            kept.update(i for i in frame_ids if _frame_ok(by_frame[i]))
            frame_ids = sorted(kept)
            logger.info(f"📎 Frame selector: sampled {len(frame_ids)} of {len(by_frame)} "
                        f"probed frames (cap {MAX_EVIDENCE_FRAMES})")
        # Most recent FIRST — leftmost chip, pre-selected.
        frames = [(i, by_frame[i]) for i in reversed(frame_ids)]

    # ── Collect uploads ──────────────────────────────────────────────────
    # Reference crops are frame-independent (same stored reference every
    # probe) → upload once per reference slot. Source crops + overlays are
    # per (frame, reference).
    verification_images: Dict[str, str] = {}
    n_slots = max(len(items) for _, items in frames)
    for j in range(n_slots):
        for _, items in frames:
            if j < len(items):
                ref_path = items[j].get('reference_image_path')
                if ref_path and os.path.exists(ref_path):
                    verification_images[f'verif_r{j}_reference'] = ref_path
                    break

    for fpos, (fidx, items) in enumerate(frames):
        for j, ev in enumerate(items):
            src_path = ev.get('source_image_path')
            if src_path and os.path.exists(src_path):
                verification_images[f'verif_f{fpos}_{j}_source'] = src_path
            overlay_src = ev.get('capture_path')
            if not (overlay_src and os.path.exists(overlay_src)):
                overlay_src = default_overlay_frame
            if overlay_src and working_dir and os.path.isdir(working_dir):
                area = ev.get('search_area') or ev.get('area')
                overlay_dest = os.path.join(working_dir, f'_verif_f{fpos}_{j}_full.jpg')
                if render_search_area_overlay(overlay_src, area, overlay_dest):
                    verification_images[f'verif_f{fpos}_{j}_full'] = overlay_dest

    verif_urls: Dict = {}
    if verification_images:
        logger.info(f"📦 Uploading {len(verification_images)} verification evidence images "
                    f"({len(frames)} frames × {n_slots} references)...")
        verif_urls = upload_kpi_thumbnails(verification_images, request.execution_result_id, timestamp) or {}

    # ── Render every frame's cards with the one shared card renderer ────
    frame_cards = []
    frames_meta = []
    for fpos, (fidx, items) in enumerate(frames):
        cards = []
        for j, ev in enumerate(items):
            e = ev.copy()
            e['reference_url'] = verif_urls.get(f'verif_r{j}_reference', placeholder)
            e['source_url'] = verif_urls.get(f'verif_f{fpos}_{j}_source', placeholder)
            e['full_url'] = verif_urls.get(f'verif_f{fpos}_{j}_full', '')
            cards.append(create_verification_card(j + 1, e))
        frame_cards.append(cards)
        offset = items[0].get('frame_offset') if items else None
        if isinstance(offset, (int, float)):
            label = f"{'+' if offset >= 0 else '−'}{abs(offset):.1f}s"
        else:
            label = items[0].get('frame_label', '?') if items else '?'
        frames_meta.append({'label': label, 'ok': _frame_ok(items)})

    if len(frames) == 1:
        return ''.join(frame_cards[0]), len(frame_cards[0])
    return create_frame_selector_section(frames_meta, frame_cards), n_slots


def _escape_measurement_log(log_text: str) -> str:
    """HTML-escape the captured measurement log for embedding in a <pre>.

    Returns a placeholder when empty so the collapsible section reads cleanly
    instead of showing a blank box.
    """
    import html
    if not log_text:
        return '(no log captured for this measurement)'
    return html.escape(log_text)


def _kpi_diag_strings(request) -> tuple:
    """Human-readable (pass_condition, kpi_source) for the report header.

    Both success and failure reports surface these so a "wrong reference set"
    can be diagnosed at a glance:
      - pass_condition: 'any can pass' vs 'all must pass' (how the batch verdict
        was computed).
      - kpi_source: whether the references came from the destination node's live
        verifications (use_verifications_for_kpi=True → editing the node
        propagates) or the action_set's frozen kpi_references snapshot (False →
        node edits do NOT propagate; the edge's list is authoritative).
    """
    pc = (getattr(request, 'verification_pass_condition', 'all') or 'all').lower()
    pass_condition = 'any can pass' if pc == 'any' else 'all must pass'
    kpi_source = (
        'target node verifications (use_verifications_for_kpi=true)'
        if getattr(request, 'use_verifications_for_kpi', False)
        else 'edge kpi_references snapshot (use_verifications_for_kpi=false)'
    )
    return pass_condition, kpi_source


def _kpi_display_label_line(request) -> str:
    """Header meta-line for the optional run-level display name, or '' when unset.

    `kpi_display_label` is set by a script via device.navigation_context (e.g.
    standby_measurement forwards the standby mode's friendly name). The measured
    edge is identical across modes, so the name has to ride in on the request
    rather than be derived from the edge. Returns a ready-to-inject HTML fragment
    (mirrors how late_scan_banner / disappear_card are passed into the template);
    empty string keeps the header unchanged for every other run.
    """
    label = (getattr(request, 'kpi_display_label', None) or '').strip()
    if not label:
        return ''
    # html-escape so a label with <, >, & can't break the page.
    from html import escape
    return f'<div class="meta-line"><strong>Display Name:</strong> {escape(label)}</div>'


def _img_data_uri(path: str, max_size: tuple = (640, 360)) -> Optional[str]:
    """Read an image and return a downscaled JPEG base64 ``data:`` URI.

    Failure reports are uploaded to MinIO/R2 and viewed off-host, so their
    images cannot be ``file://`` links to host-local captures (those only
    resolve when the browser runs ON the host). Inlining as base64 makes the
    report fully self-contained — the established convention for shareable
    failure reports. Images are thumbnailed to keep the HTML small (a handful
    of 1280x720 captures would otherwise bloat the report to multiple MB).
    Returns None on read errors so the caller can show a "not found" note.
    """
    try:
        import io
        import base64
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail(max_size, Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        return f'data:image/jpeg;base64,{b64}'
    except Exception as e:
        logger.warning(f"⚠️  Could not inline image {os.path.basename(path)}: {e}")
        return None


def make_thumbnail_from_full(full_path: str, dest_path: str) -> bool:
    """Downscale a full-resolution capture into a strip thumbnail.

    The report's strip thumbnails are generated on-the-fly from the exact
    full-resolution frame each slot displays — never from the separately-
    numbered FFmpeg hot/thumbnails files. Those thumbnail files share an
    index with the captures but are written with an independent
    `-start_number`, so after restarts where the two dirs were cleaned
    unequally the index can point at a different moment — which showed up as
    a "Match thumbnail ≠ click-to-view original" mismatch. Sourcing the
    thumbnail from the same JPG we link as the original makes them identical
    by construction. ~30 ms per call.
    """
    try:
        from PIL import Image
        with Image.open(full_path) as im:
            im.thumbnail((256, 144), Image.LANCZOS)
            im.save(dest_path, 'JPEG', quality=80)
        return True
    except Exception as e:
        logger.warning(f"⚠️  Could not make thumbnail from {os.path.basename(full_path)}: {e}")
        return False


def _build_scan_mosaic_section(working_dir, all_captures, request, timestamp,
                               match_index=None, probe_outcomes=None) -> str:
    """Build + upload the analysed-window mosaic and return its report HTML block.

    Renders EVERY frame the scan analysed (the copies in working_dir, via the
    shared scan_mosaic builder), uploads the paginated page images to R2, and
    returns the clickable section HTML. Empty string on no frames / any error —
    the mosaic is a debugging aid and must never break report generation.
    """
    try:
        if not all_captures or not working_dir or not os.path.isdir(working_dir):
            return ''
        from shared.src.lib.utils.scan_mosaic import build_mosaic_pages, render_mosaic_section, format_offset
        from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails

        # Border each tile: green 'match' for the matched frame, else (when we
        # know which frames the verifier ran on) blue 'probe' for a passing probe
        # and red 'fail' for a rejected one. _collapse_near_duplicates force-keeps
        # match/probe/fail tiles, so every probed frame is guaranteed to survive
        # into the mosaic — making the ~10s coarse-scan gaps visible.
        #
        # In addition, always force-keep three "anchor" frames that a reviewer
        # needs to judge the transition even when the scan's own probes don't
        # cover them: the frame right after the action (last button press), and
        # the frames immediately before/after the match. Without this, the
        # dedup collapse can hide exactly the frames a client needs to trust the
        # measurement (reported by a customer as confusing mosaic gaps).
        probe_outcomes = probe_outcomes or {}
        action_index = next(
            (i for i, cap in enumerate(all_captures) if cap['timestamp'] >= request.action_timestamp),
            (len(all_captures) - 1 if all_captures else None),
        )
        anchor_tags: Dict[int, List[str]] = {}
        if action_index is not None:
            anchor_tags.setdefault(action_index, []).append('ACTION')
        if match_index is not None:
            if match_index - 1 >= 0:
                anchor_tags.setdefault(match_index - 1, []).append('BEFORE MATCH')
            if match_index + 1 < len(all_captures):
                anchor_tags.setdefault(match_index + 1, []).append('AFTER MATCH')

        frames = []
        for idx, cap in enumerate(all_captures):
            local = os.path.join(working_dir, os.path.basename(cap['path']))
            name = os.path.basename(cap['path']).replace('capture_', '').replace('.jpg', '')
            offset = cap['timestamp'] - request.action_timestamp
            tag = '+'.join(anchor_tags.get(idx, [])) or None
            if match_index is not None and idx == match_index:
                border = 'match'
            elif idx in probe_outcomes:
                border = 'probe' if probe_outcomes[idx] else 'fail'
            elif idx in anchor_tags:
                border = 'anchor'
            else:
                border = None
            frames.append({
                'path': local,
                'label': name,
                'sublabel': format_offset(offset),
                'border': border,
                'tag': tag,
            })

        page_paths, stats = build_mosaic_pages(frames, working_dir, request.execution_result_id[:8])
        if not page_paths:
            return ''

        uploads = {f'scan_{i + 1}': p for i, p in enumerate(page_paths)}
        urls = upload_kpi_thumbnails(uploads, request.execution_result_id, timestamp) or {}
        page_urls = [urls[f'scan_{i + 1}'] for i in range(len(page_paths)) if f'scan_{i + 1}' in urls]
        return render_mosaic_section(page_urls, stats)
    except Exception as e:
        logger.warning(f"⚠️  Could not build scan mosaic section: {e}")
        return ''


def generate_kpi_success_report(
    request,  # KPIMeasurementRequest object
    match_result: Dict,
    kpi_ms: int,
    working_dir: str,
    extra_before_filename: Optional[str]
) -> Optional[str]:
    """
    Generate KPI success report HTML with thumbnail evidence and upload to R2.
    
    Args:
        request: KPIMeasurementRequest object with all execution context
        match_result: Dict with match details (timestamp, capture_path, etc.)
        kpi_ms: KPI duration in milliseconds
        working_dir: Working directory containing copied images
        extra_before_filename: Filename of frame before scan window (if any)
        
    Returns:
        R2 URL to uploaded report, or None if failed
    """
    try:
        from shared.src.lib.utils.storage_path_utils import get_thumbnail_path_from_capture
        from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails, upload_kpi_report
        from shared.src.lib.utils.kpi_report_template import create_kpi_report_template
        
        logger.info(f"📊 Generating KPI success report for {request.execution_result_id[:8]}")
        
        # Find thumbnails from working directory
        logger.info(f"🔍 Searching for thumbnails in working directory: {working_dir}")
        
        if not os.path.isdir(working_dir):
            logger.warning(f"⚠️  Working directory not found: {working_dir}")
            return None
        
        # Get match capture using index-based selection
        match_index = match_result.get('capture_index')
        all_captures = match_result.get('all_captures', [])
        
        if match_index is None or not all_captures:
            logger.error(f"❌ No capture_index or all_captures in match_result")
            return None
        
        # ─────────────────────────────────────────────────────────────────
        # Pick the FULL-resolution frame for each strip slot, then synthesise
        # its thumbnail on-the-fly from that exact frame (make_thumbnail_from_full).
        # We never look up the separately-numbered hot/thumbnails files — those
        # can point at a different moment after unequal dir cleanups, which is
        # what caused the "thumbnail ≠ click-to-view original" mismatch. The
        # strip thumbnail is now, by construction, the same frame as its full.
        # ─────────────────────────────────────────────────────────────────
        match_capture = all_captures[match_index]
        match_image = os.path.join(working_dir, os.path.basename(match_capture['path']))

        # Before-match = the frame immediately before the match (match_index - 1),
        # or the extra pre-window frame when the match is the first in window.
        before_index = match_index - 1
        if before_index >= 0:
            before_full = os.path.join(working_dir, os.path.basename(all_captures[before_index]['path']))
            before_time_ts = all_captures[before_index]['timestamp']
            logger.info(f"   • Before Match: index {before_index} (frame just before match)")
        elif extra_before_filename:
            before_full = os.path.join(working_dir, extra_before_filename)
            before_time_ts = os.path.getmtime(before_full) if os.path.exists(before_full) else match_capture['timestamp']
            logger.info(f"   • Before Match: {extra_before_filename} (extra pre-window frame)")
        else:
            before_full = match_image
            before_time_ts = match_capture['timestamp']
            logger.warning(f"⚠️  No frame before match — using match as before")

        # Before/after action come from the action screenshots (full-res paths).
        before_action_full = (request.before_action_screenshot_path
                              if request.before_action_screenshot_path
                              and os.path.exists(request.before_action_screenshot_path) else None)
        before_action_time_ts = os.path.getmtime(before_action_full) if before_action_full else None

        if request.action_screenshot_path and os.path.exists(request.action_screenshot_path):
            after_action_full = request.action_screenshot_path
            after_action_time_ts = os.path.getmtime(after_action_full)
        else:
            # Fallback: closest full capture to the action timestamp.
            after_action_full = None
            after_action_time_ts = None
            if all_captures:
                closest = min(all_captures, key=lambda c: abs(c['timestamp'] - request.action_timestamp))
                cand = os.path.join(working_dir, os.path.basename(closest['path']))
                if os.path.exists(cand):
                    after_action_full = cand
                    after_action_time_ts = closest['timestamp']
                    logger.info(f"   • After Action: closest capture to action ts (fallback)")

        # Appear-then-disappear: the disappear frame is the KPI endpoint (5th card).
        disappear_index = match_result.get('disappear_index')
        disappear_full = None
        disappear_time_ts = None
        if disappear_index is not None and 0 <= disappear_index < len(all_captures):
            disappear_full = os.path.join(working_dir, os.path.basename(all_captures[disappear_index]['path']))
            disappear_time_ts = all_captures[disappear_index]['timestamp']
            logger.info(f"   • Disappear: index {disappear_index}")

        # Synthesise each slot's thumbnail from its full frame.
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        thumbnails = {}
        logger.info(f"📦 Synthesising strip thumbnails from full frames:")

        slot_sources = [
            ('before_action', before_action_full),
            ('after_action', after_action_full),
            ('before_match', before_full),
            ('match', match_image),
            ('disappear', disappear_full),
        ]
        for slot, full_src in slot_sources:
            if full_src and os.path.exists(full_src):
                dest = os.path.join(working_dir, f'_strip_{slot}.jpg')
                if make_thumbnail_from_full(full_src, dest):
                    thumbnails[slot] = dest
                    logger.info(f"   ✓ {slot}: from {os.path.basename(full_src)}")
                else:
                    logger.warning(f"   ✗ {slot}: thumbnail synthesis failed")
            else:
                logger.warning(f"   ✗ {slot}: no source frame")

        # Match "click to view original" = the full-resolution match capture.
        if match_image and os.path.exists(match_image):
            thumbnails['match_original'] = match_image
        else:
            logger.warning(f"   ✗ match_original: NOT FOUND at {match_image}")

        # Upload what we have
        if thumbnails:
            thumb_urls = upload_kpi_thumbnails(thumbnails, request.execution_result_id, timestamp)
            if not thumb_urls:
                thumb_urls = {}
        else:
            logger.warning(f"⚠️  No thumbnails to upload")
            thumb_urls = {}
        
        # Placeholder for missing images
        placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='150'%3E%3Crect fill='%23ddd' width='200' height='150'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' fill='%23666'%3ENo Image%3C/text%3E%3C/svg%3E"
        thumb_urls.setdefault('before_action', placeholder)
        thumb_urls.setdefault('after_action', placeholder)
        thumb_urls.setdefault('before_match', placeholder)
        thumb_urls.setdefault('match', placeholder)
        thumb_urls.setdefault('match_original', placeholder)
        
        # Format timestamps for display
        before_action_time = datetime.fromtimestamp(before_action_time_ts).strftime('%H:%M:%S.%f')[:-3] if before_action_time_ts else 'N/A'
        after_action_time = datetime.fromtimestamp(after_action_time_ts).strftime('%H:%M:%S.%f')[:-3] if after_action_time_ts else 'N/A'
        before_time = datetime.fromtimestamp(before_time_ts).strftime('%H:%M:%S.%f')[:-3]
        match_time = datetime.fromtimestamp(match_result['timestamp']).strftime('%H:%M:%S.%f')[:-3]
        action_timestamp_full = datetime.fromtimestamp(request.action_timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        match_timestamp_full = datetime.fromtimestamp(match_result['timestamp']).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Calculate scan window
        scan_window = match_result['timestamp'] - request.action_timestamp
        
        # Verification section: one card slot per reference, with a frame
        # selector when the scan probed multiple frames (see
        # _build_verification_section). Overlay fallback is the match frame.
        logger.info(f"📸 Processing {len(request.verification_evidence_list or [])} verification evidence items")
        verification_cards_html, verification_count = _build_verification_section(
            request, request.verification_evidence_list or [], working_dir, timestamp,
            default_overlay_frame=match_image if (match_image and os.path.exists(match_image)) else None,
        )
        
        # Prepare action details for template
        action_command = request.action_details.get('command', 'N/A')
        action_type = request.action_details.get('action_type', 'N/A')
        action_params = json.dumps(request.action_details.get('params', {}))
        action_execution_time = request.action_details.get('execution_time_ms', 0)
        action_wait_time = request.action_details.get('wait_time_ms', 0)
        action_total_time = request.action_details.get('total_time_ms', 0)

        # The "After Action" thumbnail is captured AFTER the per-action wait_time
        # elapses (action_executor presses the key, waits, then screenshots), so
        # its timestamp is press + wait_time — NOT the instant of the press. Make
        # that explicit in the header so the before/after time gap reads as the
        # wait, not as device latency. KPI itself still anchors on the press.
        after_action_label = (
            f"After Action (+{action_wait_time}ms wait)" if action_wait_time else "After Action"
        )

        # Late-scan banner: surface queue backlog so report anomalies
        # (e.g. synthesised thumbnails, slightly stale KPI) trace cleanly
        # to a backlogged worker rather than a real device problem. Set
        # by kpi_executor when queue_wait > LATE_DEQUEUE_WARN_SECONDS.
        if getattr(request, 'late_scan', False):
            late_scan_banner = (
                '<div class="meta-line" style="margin-top:6px;padding:6px 10px;'
                'background:#fff4e5;border-left:4px solid #ed6c02;color:#663c00;">'
                '⏳ <strong>Late scan</strong>: this measurement was processed '
                'after a queue backlog. Thumbnails may have been synthesised '
                'from full captures; KPI value is still authoritative.</div>'
            )
        else:
            late_scan_banner = ''
        
        # Appear-then-disappear: build the optional 5th "Disappeared" strip card.
        # Empty string for all other KPI types (the grid auto-fits 4 vs 5 cards).
        if disappear_time_ts is not None:
            disappear_url = thumb_urls.get('disappear', placeholder)
            disappear_time = datetime.fromtimestamp(disappear_time_ts).strftime('%H:%M:%S.%f')[:-3]
            disappear_card = (
                '<div class="thumb-card">'
                '<h3>Disappeared</h3>'
                f'<img src="{disappear_url}" onclick="openModal(this.src)" alt="Disappeared">'
                f'<div class="timestamp">{disappear_time}</div>'
                '</div>'
            )
        else:
            disappear_card = ''

        # Full analysed-window mosaic (every scanned frame, deduped + paginated),
        # with the matched frame highlighted.
        scan_mosaic_section = _build_scan_mosaic_section(
            working_dir, all_captures, request, timestamp,
            match_index=match_result.get('capture_index'),
            probe_outcomes=match_result.get('probe_outcomes'))

        # Generate HTML
        pass_condition, kpi_source = _kpi_diag_strings(request)
        display_label_line = _kpi_display_label_line(request)
        html_template = create_kpi_report_template()
        html_content = html_template.format(
            kpi_ms=kpi_ms,
            display_label_line=display_label_line,
            pass_condition=pass_condition,
            kpi_source=kpi_source,
            device_name=f"{request.device_id}",
            navigation_path=request.userinterface_name,
            algorithm=match_result.get('algorithm', 'unknown'),
            captures_scanned=match_result.get('captures_scanned', 0),
            before_action_thumb=thumb_urls['before_action'],
            after_action_thumb=thumb_urls['after_action'],
            after_action_label=after_action_label,
            before_match_thumb=thumb_urls['before_match'],
            match_thumb=thumb_urls['match'],
            match_original=thumb_urls.get('match_original', thumb_urls['match']),
            before_action_time=before_action_time,
            after_action_time=after_action_time,
            before_time=before_time,
            match_time=match_time,
            execution_result_id=request.execution_result_id[:12],
            action_timestamp=action_timestamp_full,
            match_timestamp=match_timestamp_full,
            scan_window=f"{scan_window:.2f}",
            # Extended metadata
            host_name=request.host_name or 'N/A',
            device_model=request.device_model or 'N/A',
            tree_id=(request.tree_id[:8] if request.tree_id else 'N/A'),
            action_set_id=request.action_set_id or 'N/A',
            from_node_label=request.from_node_label or 'N/A',
            to_node_label=request.to_node_label or 'N/A',
            last_action=request.last_action or 'N/A',
            # Action details
            action_command=action_command,
            action_type=action_type,
            action_params=action_params,
            action_execution_time=action_execution_time,
            action_wait_time=action_wait_time,
            action_total_time=action_total_time,
            # Verification evidence
            verification_count=verification_count,
            verification_cards=verification_cards_html,
            late_scan_banner=late_scan_banner,
            disappear_card=disappear_card,
            scan_mosaic_section=scan_mosaic_section,
            measurement_log=_escape_measurement_log(getattr(request, 'measurement_log', '')),
        )
        
        # Upload HTML to R2
        upload_result = upload_kpi_report(html_content, request.execution_result_id, timestamp)
        
        if upload_result.get('success'):
            report_url = upload_result['report_url']
            logger.info(f"✅ KPI report generated: {report_url}")
            return report_url
        else:
            logger.error(f"❌ Failed to upload KPI report: {upload_result.get('error')}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error generating KPI success report: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_kpi_failure_report(
    request,  # KPIMeasurementRequest object
    match_result: Dict,
    working_dir: str
) -> Optional[str]:
    """
    Generate a KPI FAILURE report that mirrors the SUCCESS report and upload
    it to MinIO/R2.

    Same shape as ``generate_kpi_success_report`` so a failed measurement is
    debugged the same way a successful one is inspected:
      - a thumbnail strip (before/after action + sampled scanned frames),
        with each thumbnail uploaded to R2 (like success), and
      - verification cards built from the SAME ``verification_evidence_list``
        the success report uses (``create_verification_card``) — reference vs
        the failed source crop, with score/threshold — just rendered with
        ✗ NO MATCH badges.

    A local copy is also written to COLD storage for on-host debugging, but the
    returned value is the full MinIO/R2 URL — persisted to ``kpi_report_url``
    exactly like the success path.

    Args:
        request: KPIMeasurementRequest object with all execution context
        match_result: Dict with failure details (error, captures_scanned, etc.)
        working_dir: Working directory containing copied images (may not exist if early failure)

    Returns:
        Full MinIO/R2 URL to the uploaded report, or None if generation failed.
    """
    try:
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, get_capture_folder
        from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails, upload_kpi_report
        from shared.src.lib.utils.kpi_report_template import create_kpi_failure_report_template

        logger.info(f"📊 Generating KPI failure report for {request.execution_result_id[:8]}")
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        placeholder = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='150'%3E%3Crect fill='%23ddd' width='200' height='150'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' fill='%23666'%3ENo Image%3C/text%3E%3C/svg%3E"

        def _fmt_ts(ts):
            return datetime.fromtimestamp(ts).strftime('%H:%M:%S.%f')[:-3] if ts else 'N/A'

        # ── Action + scan timeline strip ──────────────────────────────────────
        # Before/After action give key-press context; then the FIRST / MIDDLE /
        # LAST frame of the actual scan window so the whole search is legible. The
        # old [::step][:3] sampling dropped the last frame — i.e. what the screen
        # looked like when the scan gave up, the single most useful frame. Each
        # card is badged with its elapsed time from the key press. Full-resolution
        # frames are uploaded and scaled in the strip via CSS; clicking opens the
        # same full-res URL in the modal (no separate thumbnail).
        action_ts = request.action_timestamp

        def _elapsed_str(ts):
            if not ts or not action_ts:
                return ''
            e = ts - action_ts
            return f"{'+' if e >= 0 else '−'}{abs(e):.1f}s"

        full_sources: Dict[str, str] = {}
        strip = []  # (slot_key, title, timestamp, is_scan) in display order

        ba = request.before_action_screenshot_path
        if ba and os.path.exists(ba):
            full_sources['before_action'] = ba
            strip.append(('before_action', 'Before Action', os.path.getmtime(ba), False))

        aa = request.action_screenshot_path
        if aa and os.path.exists(aa):
            full_sources['after_action'] = aa
            strip.append(('after_action', 'After Action', os.path.getmtime(aa), False))

        all_captures = match_result.get('all_captures', []) or []
        if all_captures:
            n = len(all_captures)
            # first / middle / last; dedup indices so tiny windows don't repeat.
            seen_idx = set()
            for key, title, idx in (
                ('scan_start', 'Scan start', 0),
                ('scan_middle', 'Scan middle', n // 2),
                ('scan_end', 'Scan end', n - 1),
            ):
                if idx in seen_idx:
                    continue
                seen_idx.add(idx)
                cap = all_captures[idx]
                full = os.path.join(working_dir, os.path.basename(cap['path']))
                if os.path.exists(full):
                    full_sources[key] = full
                    strip.append((key, title, cap['timestamp'], True))

        thumb_urls = upload_kpi_thumbnails(full_sources, request.execution_result_id, timestamp) if full_sources else {}
        if not thumb_urls:
            thumb_urls = {}

        thumbnail_cards = ""
        for key, title, ts, is_scan in strip:
            url = thumb_urls.get(key, placeholder)
            elapsed = _elapsed_str(ts)
            badge = f'<span class="{"elapsed" if is_scan else "action-badge"}">{elapsed}</span>' if elapsed else ''
            thumbnail_cards += (
                f'<div class="thumb-card{" scan" if is_scan else ""}">'
                f'<h3>{title} {badge}</h3>'
                f'<img src="{url}" onclick="openModal(this.src)" alt="{title}">'
                f'<div class="timestamp">{_fmt_ts(ts)}</div>'
                '</div>'
            )
        if not thumbnail_cards:
            thumbnail_cards = '<p style="color:#999">No frames available (early failure)</p>'

        # ── Verification cards: identical mechanism to the success report ──
        # One card slot per reference + frame selector when the scan probed
        # multiple frames (see _build_verification_section). Overlay fallback
        # is the frame where the scan gave up (the last capture) — the most
        # useful "what the screen looked like when we stopped looking" frame.
        evidence_list = request.verification_evidence_list or []
        full_frame_for_overlay = None
        if all_captures:
            cand = os.path.join(working_dir, os.path.basename(all_captures[-1]['path']))
            if os.path.exists(cand):
                full_frame_for_overlay = cand
        verification_cards_html, verification_count = _build_verification_section(
            request, evidence_list, working_dir, timestamp,
            default_overlay_frame=full_frame_for_overlay, placeholder=placeholder,
        )
        if not verification_cards_html:
            verification_cards_html = (
                '<p style="color:#999;margin-top:15px">No verification evidence captured '
                '(scan found no candidate frame to verify against).</p>'
            )

        # Late-scan banner (same wording as success).
        if getattr(request, 'late_scan', False):
            late_scan_banner = (
                '<div class="meta-line" style="margin-top:6px;padding:6px 10px;'
                'background:#fff4e5;border-left:4px solid #ed6c02;color:#fff;">'
                '⏳ <strong>Late scan</strong>: processed after a queue backlog — '
                'failure may be caused by stale hot-storage frames rather than a real '
                'device problem.</div>'
            )
        else:
            late_scan_banner = ''

        scan_window = 0.0
        scan_end_timestamp_full = 'N/A'
        if all_captures:
            scan_window = all_captures[-1]['timestamp'] - request.action_timestamp
            scan_end_timestamp_full = datetime.fromtimestamp(all_captures[-1]['timestamp']).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        action_timestamp_full = datetime.fromtimestamp(request.action_timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Note under the strip — explains the frames span the whole scan window.
        if all_captures:
            scan_rail_note = (
                f"Frames span the full {scan_window:.1f}s scan window (first · midpoint · "
                f"last). Click any frame to view full resolution."
            )
        else:
            scan_rail_note = ''

        # Link to the live verification's own failure report when one was
        # produced (only failed verifications generate one — see DEVICE_LOCK/
        # report flow). Gives the deep-dive evidence pack (per-frame wait
        # timeline, pixel-diff overlay) the KPI report intentionally summarises.
        verif_report_url = getattr(request, 'live_verification_report_url', None)
        if verif_report_url:
            verification_report_link = (
                f'<a class="verif-report-link" href="{verif_report_url}" '
                f'target="_blank" rel="noopener">🔍 Open verification failure report</a>'
            )
        else:
            verification_report_link = ''

        # Full analysed-window mosaic — the key debugging aid for failures: shows
        # every frame the scan looked at so you can see WHY nothing matched.
        scan_mosaic_section = _build_scan_mosaic_section(
            working_dir, all_captures, request, timestamp, match_index=None,
            probe_outcomes=match_result.get('probe_outcomes'))

        pass_condition, kpi_source = _kpi_diag_strings(request)
        html_content = create_kpi_failure_report_template().format(
            execution_result_id=request.execution_result_id,
            error=match_result.get('error', 'Unknown'),
            verification_report_link=verification_report_link,
            display_label_line=_kpi_display_label_line(request),
            pass_condition=pass_condition,
            kpi_source=kpi_source,
            from_node_label=request.from_node_label or 'N/A',
            to_node_label=request.to_node_label or 'N/A',
            last_action=request.last_action or 'N/A',
            host_name=request.host_name or 'N/A',
            device_name=f"{request.device_id}",
            device_model=request.device_model or 'N/A',
            navigation_path=request.userinterface_name,
            tree_id=(request.tree_id[:8] if request.tree_id else 'N/A'),
            action_set_id=request.action_set_id or 'N/A',
            algorithm=match_result.get('algorithm', 'unknown'),
            captures_scanned=match_result.get('captures_scanned', 0),
            late_scan_banner=late_scan_banner,
            thumbnail_cards=thumbnail_cards,
            scan_mosaic_section=scan_mosaic_section,
            scan_rail_note=scan_rail_note,
            verification_count=verification_count,
            verification_cards=verification_cards_html,
            scan_window=f"{scan_window:.2f}",
            action_timestamp=action_timestamp_full,
            scan_end_timestamp=scan_end_timestamp_full,
            measurement_log=_escape_measurement_log(getattr(request, 'measurement_log', '')),
        )

        # Local copy under reports/ for on-host debugging (best-effort).
        try:
            device_folder = get_capture_folder(request.capture_dir)
            cold_base = get_cold_storage_path(device_folder, 'reports')
            os.makedirs(cold_base, exist_ok=True)
            report_path = os.path.join(
                cold_base,
                f'kpi_failure_{request.execution_result_id[:8]}_{time.strftime("%Y%m%d_%H%M%S")}.html')
            with open(report_path, 'w') as f:
                f.write(html_content)
            logger.info(f"✅ Failure report (local copy): {report_path}")
        except Exception as e:
            logger.warning(f"⚠️  Could not write local failure report copy: {e}")

        # Upload to MinIO/R2 (same prefix as success) and return the full URL.
        upload_result = upload_kpi_report(html_content, request.execution_result_id, timestamp)
        if upload_result.get('success'):
            report_url = upload_result['report_url']
            logger.info(f"✅ Failure report uploaded: {report_url}")
            return report_url
        logger.error(f"❌ Failed to upload failure report: {upload_result.get('error')}")
        return None

    except Exception as e:
        logger.error(f"❌ Failed to generate failure report: {e}")
        import traceback
        traceback.print_exc()
        return None
