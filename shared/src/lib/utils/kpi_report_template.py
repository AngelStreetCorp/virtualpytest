"""
KPI Report Template

Minimal HTML template for KPI measurement reports with thumbnail evidence.
"""

def _full_capture_panel(full_url: str) -> str:
    """Left panel — the full frame with the red (and yellow, when fuzzy) search
    rectangle drawn on it. Returns '' when no overlay exists (e.g. early failure
    with no frame to draw on), so the card falls back to the crops-only layout.
    Coordinates/focus are surfaced as values on the right panel instead."""
    if not full_url:
        return ''
    return (
        '<div class="full-capture-panel">'
        f'<img src="{full_url}" onclick="openModal(this.src)" alt="Full capture">'
        '</div>'
    )


def _area_details(area: dict, focus_score=None, focus_threshold=None) -> str:
    """Right-panel block: the exact search area (red rectangle), the fuzzy area
    (yellow rectangle — only when fx/fy/fwidth/fheight are defined), and the
    focus score/threshold (only when present). Colored dots map each row to the
    rectangle drawn on the full capture."""
    if not isinstance(area, dict):
        area = {}
    rows = []
    if all(area.get(k) is not None for k in ('x', 'y', 'width', 'height')):
        rows.append(
            '<div class="area-row"><span class="swatch swatch-red"></span>'
            '<span class="area-key">Area</span>'
            f'<span class="area-val">x:{int(area["x"])} y:{int(area["y"])} '
            f'w:{int(area["width"])} h:{int(area["height"])}</span></div>'
        )
    if all(area.get(k) is not None for k in ('fx', 'fy', 'fwidth', 'fheight')):
        rows.append(
            '<div class="area-row"><span class="swatch swatch-yellow"></span>'
            '<span class="area-key">Fuzzy</span>'
            f'<span class="area-val">x:{int(area["fx"])} y:{int(area["fy"])} '
            f'w:{int(area["fwidth"])} h:{int(area["fheight"])}</span></div>'
        )
    if focus_score is not None or focus_threshold is not None:
        fs = f'{focus_score:.3f}' if isinstance(focus_score, (int, float)) else 'n/a'
        ft = f'{focus_threshold:.2f}' if isinstance(focus_threshold, (int, float)) else 'n/a'
        rows.append(
            '<div class="area-row"><span class="area-key">Focus</span>'
            f'<span class="area-val">{fs} / required {ft}</span></div>'
        )
    if not rows:
        return ''
    return '<div class="area-details">' + ''.join(rows) + '</div>'


def create_verification_card(index: int, verification: dict) -> str:
    """Create HTML for a single verification evidence card.

    Layout mirrors the Verification Failure view: the full capture with the
    search-area rectangle is the primary panel on the left, with the cropped
    source/reference (image) or OCR details (text) and the score on the right.
    Falls back to a crops-only layout when no full-capture overlay is available.
    """
    v_type = verification.get('type', 'image')
    command = verification.get('command', 'N/A')
    success = verification.get('success', False)
    # When the KPI scan probes multiple frames, each card is tagged with its
    # frame (name · offset) so it lines up with the mosaic's bordered tile.
    frame_label = verification.get('frame_label', '')
    frame_suffix = f' · {frame_label}' if frame_label else ''
    full_url = verification.get('full_url', '')
    area = verification.get('search_area') or verification.get('area') or {}
    focus_score = verification.get('focus_score')
    focus_threshold = verification.get('focus_threshold')
    full_panel = _full_capture_panel(full_url)
    area_details = _area_details(area, focus_score, focus_threshold)
    layout_class = 'evidence-layout' if full_panel else 'evidence-layout no-full'

    if v_type == 'image':
        ref_url = verification.get('reference_url', '')
        src_url = verification.get('source_url', '')
        score = verification.get('matching_score', 0.0)
        threshold = verification.get('threshold', 0.8)

        return f"""
        <div class="verification-card {'success' if success else ''}">
            <div class="verification-header">
                <span>#{index}: {command}{frame_suffix}</span>
                <span class="verification-status">{'✓ MATCH' if success else '✗ NO MATCH'}</span>
            </div>
            <div class="{layout_class}">
                {full_panel}
                <div class="side-panel">
                    <div class="cmp-pair">
                        <div class="comparison-image">
                            <img src="{src_url}" onclick="openModal(this.src)" alt="Source">
                            <div class="comparison-label">Source (cropped)</div>
                        </div>
                        <div class="comparison-vs">VS</div>
                        <div class="comparison-image">
                            <img src="{ref_url}" onclick="openModal(this.src)" alt="Reference">
                            <div class="comparison-label">Reference (cropped)</div>
                        </div>
                    </div>
                    <div class="comparison-result">
                        <div class="score">{score:.3f}</div>
                        <div class="threshold">threshold: {threshold}</div>
                    </div>
                    {area_details}
                </div>
            </div>
        </div>
        """

    elif v_type == 'text':
        src_url = verification.get('source_url', '')
        searched_text = verification.get('searched_text', '')
        extracted_text = verification.get('extracted_text', '')
        confidence_raw = verification.get('confidence', 0) or 0
        # confidence comes in on a 0..1 scale from langdetect; display as percent
        confidence_pct = f"{confidence_raw * 100:.1f}"
        language = verification.get('language') or 'unknown'
        # OCR match score + threshold mirror the image card (executor evidence
        # uses matching_score/threshold keys for both types).
        score = verification.get('matching_score', 0.0) or 0.0
        threshold = verification.get('threshold', 0.8)
        threshold_str = f"{threshold:.3f}" if isinstance(threshold, (int, float)) else 'n/a'

        return f"""
        <div class="verification-card {'success' if success else ''}">
            <div class="verification-header">
                <span>#{index}: {command}{frame_suffix}</span>
                <span class="verification-status">{'✓ MATCH' if success else '✗ NO MATCH'}</span>
            </div>
            <div class="{layout_class}">
                {full_panel}
                <div class="side-panel">
                    <div class="comparison-image">
                        <img src="{src_url}" onclick="openModal(this.src)" alt="Source OCR">
                        <div class="comparison-label">Source (OCR)</div>
                    </div>
                    <div class="text-fields">
                        <div class="param-row">
                            <span class="param-key">Searched Text:</span>
                            <span class="param-value">"{searched_text}"</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Extracted Text:</span>
                            <span class="param-value">"{extracted_text[:100]}"</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Language:</span>
                            <span class="param-value">{language} ({confidence_pct}% confidence)</span>
                        </div>
                    </div>
                    <div class="comparison-result">
                        <div class="score">{score:.3f}</div>
                        <div class="threshold">threshold: {threshold_str}</div>
                    </div>
                    {area_details}
                </div>
            </div>
        </div>
        """

    return ""


def create_frame_selector_section(frames_meta: list, frame_cards: list) -> str:
    """Verification section with a frame-selector chip strip.

    ``frames_meta``: one dict per analyzed frame, ordered MOST RECENT FIRST
    (leftmost chip, pre-selected): {'label': '+1.2s', 'ok': bool}.
    ``frame_cards``: parallel list — for each frame, the list of pre-rendered
    verification-card HTML strings (one per reference, same order every frame).

    Every frame's cards are embedded in a JSON blob; clicking a chip swaps the
    card slots' innerHTML client-side, so the reader can inspect what each
    analyzed frame looked like against each reference. The whole block is
    self-contained (inline style + script) so both the success and failure
    page templates receive it through their existing {verification_cards}
    placeholder without template changes.
    """
    import json

    chips = ''.join(
        '<button type="button" class="frame-chip '
        + ('pass' if m.get('ok') else 'fail')
        + (' selected' if i == 0 else '')
        + f'" data-f="{i}" onclick="kpiSelectFrame({i})">'
        + f'{m.get("label", "?")} {"✓" if m.get("ok") else "✗"}</button>'
        for i, m in enumerate(frames_meta)
    )
    slots = ''.join(
        f'<div class="vslot" data-slot="{j}">{html}</div>'
        for j, html in enumerate(frame_cards[0])
    )
    # '</' would close the inline <script> early; '<\/' is the JSON-legal escape.
    payload = json.dumps(frame_cards).replace('</', '<\\/')

    style = (
        '<style>'
        '.frame-chips { margin: 12px 0 4px; }'
        '.chips-label { display: block; font-size: 12px; color: #666; margin-bottom: 6px; }'
        '.chips-row { display: flex; flex-wrap: wrap; gap: 6px; }'
        '.frame-chip { font-family: "Courier New", monospace; font-size: 12px;'
        ' padding: 4px 10px; border-radius: 14px; border: 2px solid transparent;'
        ' cursor: pointer; background: #fdecea; color: #c62828; }'
        '.frame-chip.pass { background: #e8f5e9; color: #2e7d32; }'
        '.frame-chip.selected { border-color: #333; font-weight: 700; }'
        '</style>'
    )
    script = (
        '<script>'
        'var KPI_VERIF_FRAMES = ' + payload + ';'
        'function kpiSelectFrame(i) {'
        '  var cards = KPI_VERIF_FRAMES[i] || [];'
        '  document.querySelectorAll("#verifSlots .vslot").forEach(function(s, j) {'
        '    if (cards[j] !== undefined) s.innerHTML = cards[j];'
        '  });'
        '  document.querySelectorAll(".frame-chip").forEach(function(c) {'
        '    c.classList.toggle("selected", c.dataset.f === String(i));'
        '  });'
        '}'
        '</script>'
    )
    return (
        style
        + '<div class="frame-chips">'
        + f'<span class="chips-label">Analyzed frames ({len(frames_meta)}) — most recent first</span>'
        + f'<div class="chips-row">{chips}</div>'
        + '</div>'
        + f'<div id="verifSlots">{slots}</div>'
        + script
    )


def create_kpi_report_template() -> str:
    """Create the KPI success report: two rows of three frames (action trio,
    match trio), the scan mosaic, and modal zoom."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KPI Report - {execution_result_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
            color: #333;
        }}
        
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
            color: white;
            padding: 15px 25px;
            position: relative;
        }}

        .download-btn {{
            position: absolute;
            top: 15px;
            right: 20px;
            background: rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background 0.2s;
            padding: 0;
        }}

        .download-btn:hover {{
            background: rgba(255,255,255,0.3);
        }}

        .download-btn svg {{
            width: 20px;
            height: 20px;
            fill: white;
        }}
        
        .header h1 {{
            font-size: 28px;
            margin: 0 0 8px 0;
            font-weight: 600;
        }}

        /* The +/- next to the headline number: the KPI can only be as precise as the
           gap between the two frames around the transition, so the number is never
           shown on its own any more. */
        .header h1 .precision {{
            font-size: 16px;
            font-weight: 400;
            opacity: 0.85;
            margin-left: 8px;
        }}
        
        .header .meta {{
            font-size: 13px;
            opacity: 0.95;
            line-height: 1.6;
            margin: 5px 0 0 0;
        }}
        
        .header .meta-line {{
            margin: 2px 0;
            font-size: 12px;
        }}
        
        .header .meta-inline {{
            display: inline-block;
            margin-right: 20px;
        }}
        
        .content {{
            padding: 30px;
        }}
        
        .section {{
            margin-bottom: 30px;
        }}
        
        .section h2 {{
            font-size: 18px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        /* Two rows of three, fixed: the action trio (before / at the press /
           after the wait) on top, the match trio (before / match / after)
           underneath. auto-fit used to reflow them into one row of four, which
           read as a single sequence and hid that these are two separate moments. */
        .thumbnails {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }}

        @media (max-width: 720px) {{
            .thumbnails {{
                grid-template-columns: 1fr;
            }}
        }}
        
        .thumb-card {{
            background: #fafafa;
            border-radius: 8px;
            padding: 15px;
            border: 2px solid #e0e0e0;
            transition: all 0.2s;
        }}
        
        .thumb-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        .thumb-card h3 {{
            font-size: 13px;
            color: #666;
            margin-bottom: 10px;
            text-transform: uppercase;
            font-weight: 600;
        }}
        
        .thumb-card.match {{
            border-color: #4CAF50;
            background: #f1f8f4;
        }}
        
        .thumb-card.match h3 {{
            color: #4CAF50;
        }}
        
        .thumb-card img {{
            width: 100%;
            border-radius: 4px;
            cursor: pointer;
            display: block;
            border: 1px solid #ddd;
        }}
        
        .thumb-card img:hover {{
            opacity: 0.9;
        }}
        
        .thumb-card .timestamp {{
            font-size: 12px;
            color: #999;
            margin-top: 8px;
            font-family: 'Courier New', monospace;
        }}
        
        .details {{
            background: #fafafa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
        }}
        
        .details h2 {{
            color: #333;
            font-size: 16px;
            margin-bottom: 15px;
        }}
        
        .details-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }}
        
        .detail-item {{
            display: flex;
            flex-direction: column;
        }}
        
        .detail-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-bottom: 4px;
            font-weight: 600;
        }}
        
        .detail-value {{
            font-size: 14px;
            color: #333;
            font-family: 'Courier New', monospace;
        }}
        
        /* Modal styles */
        .modal {{
            display: none;
            position: fixed;
            z-index: 9999;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            cursor: pointer;
        }}
        
        .modal.active {{
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .modal img {{
            max-width: 95%;
            max-height: 95%;
            box-shadow: 0 4px 24px rgba(0,0,0,0.5);
            cursor: default;
        }}
        
        .close {{
            position: absolute;
            top: 20px;
            right: 40px;
            color: white;
            font-size: 40px;
            font-weight: bold;
            cursor: pointer;
            z-index: 10000;
        }}
        
        .close:hover {{
            color: #ccc;
        }}
        
        .hint {{
            text-align: center;
            color: #999;
            font-size: 13px;
            margin-top: 10px;
        }}
        
        /* Collapsible sections */
        details {{
            background: #fafafa;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }}
        
        details[open] {{
            padding-bottom: 20px;
        }}
        
        details.action-details {{
            border-left: 4px solid #2196F3;
        }}
        
        details.verification-evidence {{
            border-left: 4px solid #FF9800;
        }}

        details.measurement-log {{
            border-left: 4px solid #9E9E9E;
        }}

        .log-pre {{
            margin-top: 12px;
            padding: 14px;
            background: #1e1e1e;
            color: #d4d4d4;
            border-radius: 6px;
            font-family: 'SF Mono', Menlo, Consolas, monospace;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 420px;
            overflow: auto;
        }}

        summary {{
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            padding: 5px 0;
            user-select: none;
            list-style: none;
        }}
        
        summary::-webkit-details-marker {{
            display: none;
        }}
        
        summary::before {{
            content: '▶ ';
            display: inline-block;
            transition: transform 0.2s;
        }}
        
        details[open] summary::before {{
            transform: rotate(90deg);
        }}
        
        .action-params {{
            margin-top: 15px;
            padding: 15px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e0e0e0;
        }}
        
        .param-row {{
            display: flex;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }}
        
        .param-row:last-child {{
            border-bottom: none;
        }}
        
        .param-key {{
            font-weight: 600;
            color: #666;
            min-width: 120px;
            font-size: 13px;
        }}
        
        .param-value {{
            color: #333;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }}
        
        .verification-card {{
            background: white;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px;
            margin-top: 15px;
        }}
        
        .verification-card.success {{
            border-color: #4CAF50;
            background: #f1f8f4;
        }}
        
        .verification-header {{
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .verification-status {{
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 4px;
            background: #4CAF50;
            color: white;
        }}
        
        .comparison-grid {{
            display: grid;
            grid-template-columns: 1fr auto 1fr auto;
            gap: 15px;
            align-items: center;
            margin: 15px 0;
        }}
        
        .comparison-image {{
            text-align: center;
        }}
        
        .comparison-image img {{
            max-width: 180px;
            border: 2px solid #ddd;
            border-radius: 6px;
            cursor: zoom-in;
        }}
        
        .comparison-image img:hover {{
            border-color: #2196F3;
        }}
        
        .comparison-label {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
            font-weight: 600;
        }}
        
        .comparison-vs {{
            font-size: 18px;
            color: #999;
            font-weight: bold;
        }}
        
        .comparison-result {{
            text-align: center;
            font-size: 14px;
        }}
        
        .score {{
            font-size: 24px;
            font-weight: bold;
            color: #4CAF50;
        }}
        
        .threshold {{
            font-size: 12px;
            color: #666;
        }}

        /* Failure-view evidence layout: full capture (with search rectangle) on
           the left, crops/OCR + score on the right. Collapses to one column when
           no full-capture overlay is available. */
        .evidence-layout {{
            display: grid;
            grid-template-columns: minmax(280px, 1.5fr) minmax(220px, 1fr);
            gap: 20px;
            align-items: start;
            margin: 15px 0;
        }}
        .evidence-layout.no-full {{ grid-template-columns: 1fr; }}
        .full-capture-panel {{ text-align: center; }}
        .full-capture-panel img {{
            width: 100%;
            max-width: 520px;
            border: 2px solid #ddd;
            border-radius: 6px;
            cursor: zoom-in;
            display: block;
        }}
        .full-capture-panel img:hover {{ border-color: #2196F3; }}
        .side-panel {{ display: flex; flex-direction: column; gap: 14px; }}
        /* Source/Reference crops vary wildly in shape (wide banners like 300x12,
           but also narrow vertical strips like 40x123). Stack them vertically so
           each gets the full side-panel width. Display each at its NATIVE pixel
           size, only scaling DOWN to fit (max-width:100% + max-height), never up
           — mirrors the verification failure view (native, crisp). The old
           width:100% upscaled a 40px-wide crop ~8.5x into a giant blurry strip. */
        .cmp-pair {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .cmp-pair .comparison-image img {{
            width: auto; height: auto;
            max-width: 100%; max-height: 360px;
        }}
        .cmp-pair .comparison-vs {{ text-align: center; }}
        .text-fields {{ padding: 4px 0; }}
        .area-details {{
            margin-top: 4px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #444;
        }}
        .area-row {{ display: flex; align-items: center; gap: 8px; }}
        .area-key {{ min-width: 48px; font-weight: 600; color: #666; }}
        .area-val {{ color: #333; }}
        .swatch {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px; flex: 0 0 auto; }}
        .swatch-red {{ background: #ff3b30; }}
        .swatch-yellow {{ background: #ffd60a; }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
                border-radius: 0;
                max-width: 100%;
            }}
            .header {{
                /* keep colors when printing */
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .download-btn,
            .modal {{
                display: none !important;
            }}
            .thumb-card,
            .verification-card,
            .details,
            details {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}
            details {{
                /* expand collapsibles in the printed output */
            }}
            details:not([open]) > *:not(summary) {{
                display: block;
            }}
            img {{
                max-width: 100% !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <button class="download-btn" onclick="window.print()" title="Save as PDF (browser print dialog)" aria-label="Download as PDF">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 3v10.59l3.3-3.3 1.4 1.42L12 17.41l-4.7-4.7 1.4-1.42 3.3 3.3V3h2zM5 19h14v2H5v-2z"/>
                </svg>
            </button>
            <h1>✓ KPI: <span id="kpiDisplay" data-ms="{kpi_ms}">{kpi_ms}ms</span><span class="precision">{kpi_precision}</span></h1>
            <div class="meta">
                {display_label_line}
                <div class="meta-line">
                    <strong>Measurement Start:</strong> {action_timestamp} &nbsp;|&nbsp; <strong>Measurement End:</strong> {match_timestamp}
                </div>
                <div class="meta-line">
                    <strong>Navigation:</strong> {from_node_label} → {to_node_label} &nbsp;|&nbsp; <strong>Last Action:</strong> {last_action}
                </div>
                <div class="meta-line">
                    <strong>Host:</strong> {host_name} &nbsp;|&nbsp; <strong>Device:</strong> {device_name} ({device_model}) &nbsp;|&nbsp; <strong>UI:</strong> {navigation_path}
                </div>
                <div class="meta-line">
                    <strong>Tree:</strong> {tree_id} &nbsp;|&nbsp; <strong>Action Set:</strong> {action_set_id} &nbsp;|&nbsp; <strong>Algorithm:</strong> {algorithm} &nbsp;|&nbsp; <strong>Scanned:</strong> {captures_scanned} frames
                </div>
                <div class="meta-line">
                    <strong>Pass condition:</strong> {pass_condition} &nbsp;|&nbsp; <strong>KPI source:</strong> {kpi_source}
                </div>
                {confidence_line}
                {late_scan_banner}
                {confidence_warnings}
            </div>
        </div>
        
        <div class="content">
            <div class="section">
                <div class="thumbnails">
                    <!-- Row 1 — the action: the screenshot taken just before the
                         press, the captured frame at the press itself, and the
                         screenshot taken once the action's wait has elapsed. -->
                    <div class="thumb-card">
                        <h3>Before Action</h3>
                        <img src="{before_action_thumb}" onclick="openModal(this.src)" alt="Before action pressed">
                        <div class="timestamp">{before_action_time}</div>
                    </div>
                    <div class="thumb-card">
                        <h3>Action</h3>
                        <img src="{action_thumb}" onclick="openModal(this.src)" alt="Frame at the action">
                        <div class="timestamp">{action_time}</div>
                    </div>
                    <div class="thumb-card">
                        <h3>{after_action_label}</h3>
                        <img src="{after_action_thumb}" onclick="openModal(this.src)" alt="After action pressed">
                        <div class="timestamp">{after_action_time}</div>
                    </div>
                    <!-- Row 2 — the match: the frame before it, the match, and the
                         frame after it, so the transition the KPI is measured on is
                         visible without opening the mosaic. -->
                    <div class="thumb-card">
                        <h3>Before Match</h3>
                        <img src="{before_match_thumb}" onclick="openModal(this.src)" alt="Before match">
                        <div class="timestamp">{before_time}</div>
                    </div>
                    <div class="thumb-card match">
                        <h3>✓ Match Found</h3>
                        <img src="{match_thumb}" onclick="openModal('{match_original}')" alt="Match found" style="cursor: zoom-in;">
                        <div class="timestamp">{match_time}</div>
                        <div class="hint" style="font-size: 11px; margin-top: 4px; color: #4CAF50;">Click to view original</div>
                    </div>
                    <div class="thumb-card">
                        <h3>After Match</h3>
                        <img src="{after_match_thumb}" onclick="openModal(this.src)" alt="After match">
                        <div class="timestamp">{after_match_time}</div>
                    </div>
                    {disappear_card}
                </div>
                {scan_mosaic_section}
            </div>

            <!-- Action Details Section (Collapsible) -->
            <div class="section">
                <details class="action-details" open>
                    <summary>Last Action Executed</summary>
                    <div class="action-params">
                        <div class="param-row">
                            <span class="param-key">Executed At:</span>
                            <span class="param-value">{action_timestamp}</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Command:</span>
                            <span class="param-value">{action_command}</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Action Type:</span>
                            <span class="param-value">{action_type}</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Parameters:</span>
                            <span class="param-value">{action_params}</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Execution Time:</span>
                            <span class="param-value">{action_execution_time}ms</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Wait Time:</span>
                            <span class="param-value">{action_wait_time}ms</span>
                        </div>
                        <div class="param-row">
                            <span class="param-key">Total Time:</span>
                            <span class="param-value">{action_total_time}ms</span>
                        </div>
                    </div>
                </details>
            </div>
            
            <!-- Verification Evidence Section (Collapsible) -->
            <div class="section">
                <details class="verification-evidence" open>
                    <summary>Verification ({verification_count})</summary>
                    {verification_cards}
                </details>
            </div>
            
            <div class="section">
                <div class="details">
                    <h2>📊 Measurement Details</h2>
                    <div class="details-grid">
                        <div class="detail-item">
                            <span class="detail-label">Execution Result ID</span>
                            <span class="detail-value">{execution_result_id}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">KPI Duration</span>
                            <span class="detail-value">{kpi_ms}ms</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Action Timestamp</span>
                            <span class="detail-value">{action_timestamp}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Match Timestamp</span>
                            <span class="detail-value">{match_timestamp}</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Scan Window</span>
                            <span class="detail-value">{scan_window}s</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Captures Scanned</span>
                            <span class="detail-value">{captures_scanned} frames</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="section">
                <details class="measurement-log">
                    <summary>Measurement Log</summary>
                    <pre class="log-pre">{measurement_log}</pre>
                </details>
            </div>
        </div>
    </div>
    
    <div id="modal" class="modal" onclick="closeModal()">
        <span class="close" onclick="closeModal()">&times;</span>
        <img id="modalImg" src="" alt="Full size">
    </div>
    
    <script>
        // Format milliseconds to smart format (only show non-zero units)
        function formatKPI() {{
            const kpiEl = document.getElementById('kpiDisplay');
            const ms = parseInt(kpiEl.dataset.ms);
            
            const minutes = Math.floor(ms / 60000);
            const seconds = Math.floor((ms % 60000) / 1000);
            const milliseconds = ms % 1000;
            
            let parts = [];
            if (minutes > 0) parts.push(minutes + 'm');
            if (seconds > 0) parts.push(seconds + 's');
            if (milliseconds > 0 || parts.length === 0) parts.push(milliseconds + 'ms');
            
            kpiEl.textContent = parts.join(' ');
        }}
        
        // Format on page load
        formatKPI();
        
        function openModal(src) {{
            event.stopPropagation();
            document.getElementById('modal').classList.add('active');
            document.getElementById('modalImg').src = src;
        }}
        
        function closeModal() {{
            document.getElementById('modal').classList.remove('active');
        }}
        
        // Close modal on ESC key
        document.addEventListener('keydown', function(event) {{
            if (event.key === 'Escape') {{
                closeModal();
            }}
        }});
    </script>
</body>
</html>"""


def create_kpi_failure_report_template() -> str:
    """KPI FAILURE report — mirrors the success template (same CSS, modal,
    thumbnail strip and verification cards) but with a red header and
    failure-oriented fields.

    Used for a *real* KPI measurement failure (the scan ran but found no
    frame where the destination rendered). The verification cards are built
    from the SAME verification_evidence_list the success report uses, so a
    failed measurement shows the reference vs the failed source crop with
    score/threshold — exactly like success, just with ✗ NO MATCH badges.

    Placeholders: execution_result_id, error, from_node_label, to_node_label,
    last_action, host_name, device_name, device_model, navigation_path,
    tree_id, action_set_id, algorithm, captures_scanned, late_scan_banner,
    thumbnail_cards, verification_count, verification_cards, scan_window,
    action_timestamp, scan_end_timestamp, measurement_log.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KPI Failure - {execution_result_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; color: #333; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%); color: white; padding: 15px 25px; position: relative; }}
        .download-btn {{ position: absolute; top: 15px; right: 20px; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: white; width: 40px; height: 40px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; padding: 0; }}
        .download-btn:hover {{ background: rgba(255,255,255,0.3); }}
        .download-btn svg {{ width: 20px; height: 20px; fill: white; }}
        .header h1 {{ font-size: 26px; margin: 0 0 8px 0; font-weight: 600; }}
        .header .err {{ font-size: 14px; opacity: 0.97; margin: 4px 0 8px 0; font-family: 'Courier New', monospace; }}
        .header .meta {{ font-size: 13px; opacity: 0.95; line-height: 1.6; margin: 5px 0 0 0; }}
        .header .meta-line {{ margin: 2px 0; font-size: 12px; }}
        .content {{ padding: 30px; }}
        .section {{ margin-bottom: 30px; }}
        .thumbnails {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .thumb-card {{ background: #fafafa; border-radius: 8px; padding: 15px; border: 2px solid #e0e0e0; transition: all 0.2s; }}
        .thumb-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        .thumb-card h3 {{ font-size: 13px; color: #666; margin-bottom: 10px; text-transform: uppercase; font-weight: 600; }}
        .thumb-card img {{ width: 100%; border-radius: 4px; cursor: zoom-in; display: block; border: 1px solid #ddd; }}
        .thumb-card img:hover {{ opacity: 0.9; }}
        .thumb-card .timestamp {{ font-size: 12px; color: #999; margin-top: 8px; font-family: 'Courier New', monospace; }}
        /* Scan-window cards (first/middle/last) get a red accent + elapsed badge to
           distinguish them from the blue-badged before/after action context cards. */
        .scan-rail {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: .5px; margin: 0 0 10px; font-weight: 600; }}
        .thumb-card.scan {{ border-color: #ef9a9a; background: #fff6f6; }}
        .thumb-card.scan h3 {{ color: #c62828; }}
        .elapsed {{ display: inline-block; font-size: 11px; font-weight: 700; color: #c62828; background: #ffe3e3; border-radius: 10px; padding: 1px 8px; margin-left: 6px; }}
        .action-badge {{ display: inline-block; font-size: 11px; font-weight: 700; color: #1565c0; background: #e3f0ff; border-radius: 10px; padding: 1px 8px; margin-left: 6px; }}
        .rail-note {{ font-size: 11px; color: #999; margin: 6px 0 0; }}
        .details {{ background: #fafafa; padding: 20px; border-radius: 8px; border-left: 4px solid #d32f2f; }}
        .details h2 {{ color: #333; font-size: 16px; margin-bottom: 15px; }}
        .details-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }}
        .detail-item {{ display: flex; flex-direction: column; }}
        .detail-label {{ font-size: 12px; color: #666; text-transform: uppercase; margin-bottom: 4px; font-weight: 600; }}
        .detail-value {{ font-size: 14px; color: #333; font-family: 'Courier New', monospace; word-break: break-word; }}
        .modal {{ display: none; position: fixed; z-index: 9999; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); cursor: pointer; }}
        .modal.active {{ display: flex; align-items: center; justify-content: center; }}
        .modal img {{ max-width: 95%; max-height: 95%; box-shadow: 0 4px 24px rgba(0,0,0,0.5); cursor: default; }}
        .close {{ position: absolute; top: 20px; right: 40px; color: white; font-size: 40px; font-weight: bold; cursor: pointer; z-index: 10000; }}
        .close:hover {{ color: #ccc; }}
        details {{ background: #fafafa; border-radius: 8px; padding: 15px; margin-bottom: 20px; }}
        details.verification-evidence {{ border-left: 4px solid #FF9800; }}
        details.measurement-log {{ border-left: 4px solid #9E9E9E; }}
        .log-pre {{ margin-top: 12px; padding: 14px; background: #1e1e1e; color: #d4d4d4; border-radius: 6px; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow: auto; }}
        summary {{ font-size: 16px; font-weight: 600; cursor: pointer; padding: 5px 0; user-select: none; list-style: none; }}
        summary::-webkit-details-marker {{ display: none; }}
        summary::before {{ content: '▶ '; display: inline-block; transition: transform 0.2s; }}
        details[open] summary::before {{ transform: rotate(90deg); }}
        .verification-card {{ background: white; border: 2px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-top: 15px; }}
        .verification-card.success {{ border-color: #4CAF50; background: #f1f8f4; }}
        .verification-header {{ font-size: 14px; font-weight: 600; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }}
        .verification-status {{ font-size: 12px; padding: 4px 10px; border-radius: 4px; background: #4CAF50; color: white; }}
        .verification-card:not(.success) .verification-status {{ background: #f44336; }}
        .comparison-grid {{ display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 15px; align-items: center; margin: 15px 0; }}
        .comparison-image {{ text-align: center; }}
        .comparison-image img {{ max-width: 180px; border: 2px solid #ddd; border-radius: 6px; cursor: zoom-in; }}
        .comparison-image img:hover {{ border-color: #2196F3; }}
        .comparison-label {{ font-size: 12px; color: #666; margin-top: 5px; font-weight: 600; }}
        .comparison-vs {{ font-size: 18px; color: #999; font-weight: bold; }}
        .comparison-result {{ text-align: center; font-size: 14px; }}
        .score {{ font-size: 24px; font-weight: bold; color: #d32f2f; }}
        .threshold {{ font-size: 12px; color: #666; }}
        .evidence-layout {{ display: grid; grid-template-columns: minmax(280px, 1.5fr) minmax(220px, 1fr); gap: 20px; align-items: start; margin: 15px 0; }}
        .evidence-layout.no-full {{ grid-template-columns: 1fr; }}
        .full-capture-panel {{ text-align: center; }}
        .full-capture-panel img {{ width: 100%; max-width: 520px; border: 2px solid #ddd; border-radius: 6px; cursor: zoom-in; display: block; }}
        .full-capture-panel img:hover {{ border-color: #2196F3; }}
        .side-panel {{ display: flex; flex-direction: column; gap: 14px; }}
        /* Crops vary in shape (wide banners and narrow vertical strips). Stack
           vertically; show each at native size, scaling DOWN only (never up) so a
           40px-wide crop isn't blown up to fill the panel (see success CSS). */
        .cmp-pair {{ display: flex; flex-direction: column; gap: 8px; }}
        .cmp-pair .comparison-image img {{ width: auto; height: auto; max-width: 100%; max-height: 360px; }}
        .cmp-pair .comparison-vs {{ text-align: center; }}
        .text-fields {{ padding: 4px 0; }}
        .area-details {{ margin-top: 4px; display: flex; flex-direction: column; gap: 6px; font-family: 'Courier New', monospace; font-size: 12px; color: #444; }}
        .area-row {{ display: flex; align-items: center; gap: 8px; }}
        .area-key {{ min-width: 48px; font-weight: 600; color: #666; }}
        .area-val {{ color: #333; }}
        .swatch {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px; flex: 0 0 auto; }}
        .swatch-red {{ background: #ff3b30; }}
        .swatch-yellow {{ background: #ffd60a; }}
        .verif-report-link {{ display: inline-flex; align-items: center; gap: 6px; margin-top: 6px; padding: 8px 14px; background: rgba(255,255,255,0.18); border: 1px solid rgba(255,255,255,0.45); border-radius: 6px; color: #fff; text-decoration: none; font-size: 13px; font-weight: 600; }}
        .verif-report-link:hover {{ background: rgba(255,255,255,0.32); }}
        .param-row {{ display: flex; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }}
        .param-key {{ font-weight: 600; color: #666; min-width: 120px; font-size: 13px; }}
        .param-value {{ color: #333; font-family: 'Courier New', monospace; font-size: 13px; }}
        @media print {{ body {{ background: white; padding: 0; }} .container {{ box-shadow: none; border-radius: 0; max-width: 100%; }} .header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .download-btn, .modal {{ display: none !important; }} .thumb-card, .verification-card, .details, details {{ break-inside: avoid; page-break-inside: avoid; }} img {{ max-width: 100% !important; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <button class="download-btn" onclick="window.print()" title="Save as PDF (browser print dialog)" aria-label="Download as PDF">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 3v10.59l3.3-3.3 1.4 1.42L12 17.41l-4.7-4.7 1.4-1.42 3.3 3.3V3h2zM5 19h14v2H5v-2z"/></svg>
            </button>
            <h1>✗ KPI Measurement Failed</h1>
            <div class="err">{error}</div>
            <div class="meta">
                {display_label_line}
                <div class="meta-line"><strong>Measurement Start:</strong> {action_timestamp} &nbsp;|&nbsp; <strong>Scan End:</strong> {scan_end_timestamp}</div>
                <div class="meta-line"><strong>Navigation:</strong> {from_node_label} → {to_node_label} &nbsp;|&nbsp; <strong>Last Action:</strong> {last_action}</div>
                <div class="meta-line"><strong>Host:</strong> {host_name} &nbsp;|&nbsp; <strong>Device:</strong> {device_name} ({device_model}) &nbsp;|&nbsp; <strong>UI:</strong> {navigation_path}</div>
                <div class="meta-line"><strong>Tree:</strong> {tree_id} &nbsp;|&nbsp; <strong>Action Set:</strong> {action_set_id} &nbsp;|&nbsp; <strong>Algorithm:</strong> {algorithm} &nbsp;|&nbsp; <strong>Scanned:</strong> {captures_scanned} frames</div>
                <div class="meta-line"><strong>Pass condition:</strong> {pass_condition} &nbsp;|&nbsp; <strong>KPI source:</strong> {kpi_source}</div>
                {late_scan_banner}
                {verification_report_link}
            </div>
        </div>
        <div class="content">
            <div class="section">
                <div class="scan-rail">Action &amp; scan timeline</div>
                <div class="thumbnails">
                    {thumbnail_cards}
                </div>
                <div class="rail-note">{scan_rail_note}</div>
                {scan_mosaic_section}
            </div>
            <div class="section">
                <details class="verification-evidence" open>
                    <summary>Verification ({verification_count})</summary>
                    {verification_cards}
                </details>
            </div>
            <div class="section">
                <div class="details">
                    <h2>📊 Failure Details</h2>
                    <div class="details-grid">
                        <div class="detail-item"><span class="detail-label">Execution Result ID</span><span class="detail-value">{execution_result_id}</span></div>
                        <div class="detail-item"><span class="detail-label">Error</span><span class="detail-value">{error}</span></div>
                        <div class="detail-item"><span class="detail-label">Action Timestamp</span><span class="detail-value">{action_timestamp}</span></div>
                        <div class="detail-item"><span class="detail-label">Scan Window</span><span class="detail-value">{scan_window}s</span></div>
                        <div class="detail-item"><span class="detail-label">Captures Scanned</span><span class="detail-value">{captures_scanned} frames</span></div>
                        <div class="detail-item"><span class="detail-label">Algorithm</span><span class="detail-value">{algorithm}</span></div>
                    </div>
                </div>
            </div>
            <div class="section">
                <details class="measurement-log">
                    <summary>Measurement Log</summary>
                    <pre class="log-pre">{measurement_log}</pre>
                </details>
            </div>
        </div>
    </div>
    <div id="modal" class="modal" onclick="closeModal()">
        <span class="close" onclick="closeModal()">&times;</span>
        <img id="modalImg" src="" alt="Full size">
    </div>
    <script>
        function openModal(src) {{ event.stopPropagation(); document.getElementById('modal').classList.add('active'); document.getElementById('modalImg').src = src; }}
        function closeModal() {{ document.getElementById('modal').classList.remove('active'); }}
        document.addEventListener('keydown', function(event) {{ if (event.key === 'Escape') {{ closeModal(); }} }});
    </script>
</body>
</html>"""

