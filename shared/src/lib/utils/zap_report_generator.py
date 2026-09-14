#!/usr/bin/env python3
"""
Zap Report Generator — single path for per-event zap measurement reports.

Both automatic zaps (capture_monitor → zapping_detector_utils) and scripted zaps
(zap_executor, which only reads last_zapping.json) funnel through
detect_and_record_zapping(). That is the ONE place this generator is called, so a
single report is produced+uploaded per zap event regardless of trigger, mirroring
the KPI report path (kpi_report_generator.generate_kpi_success_report →
execution_results.kpi_report_url). The returned URL is stored on
zap_results.report_url and surfaced in Grafana's "All Zapping Events" dashboard.
"""

import html
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _fmt_ms(value, suffix: str = 's') -> str:
    """Format a millisecond value as seconds with one decimal (e.g. 2890 → '2.9s')."""
    if value is None:
        return '—'
    try:
        return f"{float(value) / 1000.0:.1f}{suffix}"
    except (TypeError, ValueError):
        return '—'


def _esc(value) -> str:
    return html.escape(str(value)) if value not in (None, '') else '—'


# Same inline placeholder the KPI/verification reports use for a missing image.
_NO_IMAGE_PLACEHOLDER = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='150'"
    "%3E%3Crect fill='%23ddd' width='200' height='150'/%3E%3Ctext x='50%25' y='50%25' "
    "text-anchor='middle' fill='%23666'%3ENo Image%3C/text%3E%3C/svg%3E"
)


def _resolve_report_asset_url(ref: Optional[str]) -> Optional[str]:
    """Resolve an image reference to a URL that works in a standalone HTML report.

    Mirrors the KPI/verification path: a bare R2 object key is turned into an absolute,
    14-day report-asset URL via get_url_for_report_asset() (signed in private mode, public
    URL in public mode). Already-absolute URLs / data URIs are passed through unchanged.
    """
    if not ref:
        return None
    if isinstance(ref, str) and ref.startswith(('http://', 'https://', 'data:')):
        return ref
    try:
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        return get_cloudflare_utils().get_url_for_report_asset(ref)
    except Exception as e:
        logger.warning(f"Could not resolve report-asset URL for {ref}: {e}")
        return ref


def _image_cell(label: str, ref: Optional[str], frame: Optional[str]) -> str:
    caption = _esc(frame)
    url = _resolve_report_asset_url(ref) or _NO_IMAGE_PLACEHOLDER
    body = (
        f'<a href="{html.escape(url)}" target="_blank">'
        f'<img src="{html.escape(url)}" alt="{html.escape(label)}"></a>'
    )
    return (
        '<div class="frame">'
        f'<div class="frame-label">{html.escape(label)}</div>'
        f'{body}'
        f'<div class="frame-caption">{caption}</div>'
        '</div>'
    )


def build_zap_report_html(zap_event: Dict) -> str:
    """Build a self-contained HTML zap report (inline CSS, links the 4 R2 frames)."""
    transition_type = zap_event.get('transition_type') or 'blackscreen'
    transition_label = 'Freeze' if transition_type == 'freeze' else 'Blackscreen'

    images = zap_event.get('images') or {}
    frames = zap_event.get('frames') or {}

    channel = _esc(zap_event.get('channel_name'))
    channel_number = zap_event.get('channel_number')
    if channel_number:
        channel = f"{channel} ({_esc(channel_number)})"

    program = _esc(zap_event.get('program_name'))
    program_window = ''
    if zap_event.get('program_start_time') or zap_event.get('program_end_time'):
        program_window = f"{_esc(zap_event.get('program_start_time'))} – {_esc(zap_event.get('program_end_time'))}"

    action = zap_event.get('action_command') or ''
    action_params = zap_event.get('action_params') or {}
    if isinstance(action_params, dict) and action_params.get('key'):
        action = f"{action} ({action_params['key']})"

    # Optional run-level display name a script stamped into the action params
    # (e.g. zap_digit's free-text run name). Surfaced as a prominent first row +
    # title prefix when present; absent for ordinary/auto zaps.
    display_name = ''
    channel_input = ''
    if isinstance(action_params, dict):
        display_name = (action_params.get('display_name') or '').strip()
        # The full channel the operator typed (zap_digit stamps it). Only the LAST
        # digit survives in `key` — the channel commits on it, so that is the
        # key-press the monitor anchors the zap to — which makes a multi-digit
        # entry like "10" read as a bare "KEY_0". Shown alongside so the entry is
        # recoverable. Absent for CHANNEL_UP/DOWN zaps, where the row is omitted.
        channel_input = str(action_params.get('channel') or '').strip()

    silence = zap_event.get('audio_silence_duration')
    silence_str = f"{float(silence):.2f}s" if silence not in (None, '') else '—'

    # Absolute key-press time — the anchor the at-press frame and Total zap time
    # are measured from. Showing it (plus the resolved at-press frame) makes a
    # stale/early action timestamp obvious instead of hidden behind a duration.
    action_pressed_at = zap_event.get('action_pressed_at')
    try:
        action_pressed_str = (
            datetime.fromtimestamp(float(action_pressed_at)).strftime('%H:%M:%S.%f')[:-3]
            if action_pressed_at else '—'
        )
    except (TypeError, ValueError, OSError):
        action_pressed_str = '—'
    at_press_frame = frames.get('at_press_frame')

    rows = [
        *( [('Display name', f"<strong>{_esc(display_name)}</strong>")] if display_name else [] ),
        ('Channel', channel),
        ('Program', f"{program}{f' · {program_window}' if program_window else ''}"),
        ('Total zap time', f"<strong>{_fmt_ms(zap_event.get('total_zap_duration_ms'))}</strong> "
                           f"<span class='hint'>(key press → new content)</span>"),
        (f'{transition_label} duration', f"{_fmt_ms(zap_event.get('blackscreen_duration_ms'))} "
                                         f"<span class='hint'>(on-screen disruption)</span>"),
        ('Action pressed', f"{action_pressed_str} "
                           f"<span class='hint'>(key-press anchor → at-press frame {_esc(at_press_frame)})</span>"),
        ('Audio silence', silence_str),
        ('Transition type', _esc(transition_type)),
        ('Last Action', _esc(action)),
        *( [('Channel input', f"<strong>{_esc(channel_input)}</strong> "
                              f"<span class='hint'>(digits entered; the anchor key above is the last one)</span>")]
           if channel_input else [] ),
        ('Detection', _esc(zap_event.get('detection_method'))),
        ('Device', f"{_esc(zap_event.get('device_name'))} · {_esc(zap_event.get('device_model'))}"),
        ('Host', _esc(zap_event.get('host_name'))),
        ('User interface', _esc(zap_event.get('userinterface_name'))),
        ('Detected at', _esc(zap_event.get('detected_at'))),
    ]
    rows_html = ''.join(
        f'<tr><th>{html.escape(label)}</th><td>{value}</td></tr>' for label, value in rows
    )

    # When the transition is a single frame (freeze/blackscreen start == end), the
    # detector only uploads one image for it — the "end" frame is never uploaded
    # separately. Reuse the start image URL so the end cell shows that same frame
    # instead of a blank "No Image" placeholder.
    first_blackscreen_url = images.get('first_blackscreen_url')
    last_blackscreen_url = images.get('last_blackscreen_url')
    if not last_blackscreen_url and frames.get('last_blackscreen_frame') == frames.get('first_blackscreen_frame'):
        last_blackscreen_url = first_blackscreen_url

    images_html = ''.join([
        _image_cell('At key press', images.get('at_press_url'), frames.get('at_press_frame')),
        _image_cell('Before transition', images.get('before_url'), frames.get('before_frame')),
        _image_cell(f'{transition_label} start', first_blackscreen_url,
                    frames.get('first_blackscreen_frame')),
        _image_cell(f'{transition_label} end', last_blackscreen_url,
                    frames.get('last_blackscreen_frame')),
        _image_cell('After (new content)', images.get('after_url'), frames.get('after_frame')),
    ])

    # Collapsible per-event worker log (thread-local capture) — the audio
    # check, action re-anchoring, banner detection and frame selection that
    # explain the timings, without trawling journalctl on the host.
    measurement_log = zap_event.get('measurement_log') or ''
    if measurement_log:
        log_section_html = (
            '<details class="log"><summary>Measurement Log</summary>'
            f'<pre class="log-pre">{html.escape(measurement_log)}</pre></details>'
        )
    else:
        log_section_html = ''

    title = f"{display_name}: Zap → {channel}" if display_name else f"Zap → {channel}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; background: #0f1117; color: #e6e6e6; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: #8b93a7; font-size: 13px; margin-bottom: 20px; }}
  .frames {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .frame {{ background: #1a1d28; border: 1px solid #2a2e3c; border-radius: 8px; padding: 8px; }}
  .frame-label {{ font-size: 12px; font-weight: 600; color: #a9b1c6; margin-bottom: 6px; }}
  .frame img {{ width: 100%; border-radius: 4px; display: block; }}
  .frame-caption {{ font-size: 10px; color: #6b7280; margin-top: 6px; word-break: break-all; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 720px; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #232735; font-size: 14px; }}
  th {{ color: #8b93a7; font-weight: 500; width: 200px; }}
  .hint {{ color: #6b7280; font-size: 12px; }}
  details.log {{ margin-top: 24px; }}
  details.log summary {{ cursor: pointer; font-weight: 600; color: #a9b1c6; padding: 6px 0; }}
  .log-pre {{ margin-top: 12px; background: #11141c; color: #c8ccd6; padding: 14px;
             border-radius: 6px; font-family: ui-monospace, Menlo, Consolas, monospace;
             font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
             max-height: 420px; overflow: auto; }}
  @media (max-width: 720px) {{ .frames {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
  <h1>📺 {html.escape(title)}</h1>
  <div class="sub">Zap measurement report</div>
  <div class="frames">{images_html}</div>
  <table>{rows_html}</table>
  {log_section_html}
</body>
</html>"""


def generate_and_upload_zap_report(zap_event: Dict) -> Optional[str]:
    """
    Generate a per-event zap HTML report and upload it to R2. Single path for both
    automatic and scripted zaps. Best-effort: never raises — returns the report URL,
    or None if generation/upload failed (a missing report must not break zap recording).

    Args:
        zap_event: Normalized zap data — see build_zap_report_html for consumed keys,
            plus 'capture_folder' / 'device_name' used only to namespace the R2 path.
    """
    try:
        from shared.src.lib.utils.cloudflare_utils import upload_zap_report

        html_content = build_zap_report_html(zap_event)

        report_id = (
            zap_event.get('capture_folder')
            or zap_event.get('device_name')
            or 'zap'
        )
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')

        result = upload_zap_report(html_content, report_id=str(report_id), timestamp=timestamp)
        if result.get('success'):
            logger.info(f"📊 Uploaded zap report: {result.get('report_path')}")
            return result.get('report_url')

        logger.warning(f"⚠️  Zap report upload failed: {result.get('error', 'unknown error')}")
        return None
    except Exception as e:
        logger.error(f"❌ Error generating zap report: {e}")
        import traceback
        traceback.print_exc()
        return None
