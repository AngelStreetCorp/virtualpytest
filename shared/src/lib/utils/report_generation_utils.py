"""
Report Generation Core

This module handles the main report generation logic and orchestration.
Contains the primary functions for generating validation reports and managing screenshots.
"""

import os
import json
from html import escape
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from .report_formatting import (
    create_compact_step_results_section,
    format_console_summary_for_html,
    get_thumbnail_screenshot_html,
    get_video_thumbnail_html,
    create_error_section,
    update_step_results_with_r2_urls,
    create_error_report
)
from .report_template_html import create_themed_html_template
from .script_identity_utils import normalize_script_ref, resolve_script_source_path
from .cloudflare_utils import _build_script_artifact_folder_name, get_cloudflare_utils
from .report_icons import icon
from .phase_timing import t0 as _phase_t0, log_phase as _log_phase
from ..i18n.report_i18n import (
    build_catalog, catalog_script_tag, clean_script_strings, load_script_strings, script_i18n_path, t, t_attr, tx, tx_lines,
    use_report_catalog,
)


def _build_report_link_row(label: str, url: str) -> str:
    """Build a compact one-line artifact link row for report summaries."""
    if not url:
        return ''

    safe_url = escape(url, quote=True)
    return (
        '<div style="margin-top: 6px; background-color: var(--background-secondary); '
        'border-radius: 4px; border-left: 3px solid var(--info-color); padding: 8px 10px;">'
        f'{escape(label)}: '
        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
        'style="color: var(--link-color); text-decoration: none; font-weight: bold;">'
        'Click here'
        '</a>'
        '</div>'
    )


def _read_code_version() -> str:
    """Read current code version from project-root VERSION.txt."""
    try:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(utils_dir, '..', '..', '..', '..'))
        version_path = os.path.join(project_root, 'VERSION.txt')
        if not os.path.exists(version_path):
            return ''
        with open(version_path, 'r', encoding='utf-8') as vf:
            return next((ln.strip() for ln in vf if ln.strip()), '')
    except Exception:
        return ''


def _build_report_links_bar(links: list, meta_rows: list = ()) -> str:
    """Artifact links and run facts as one aligned list: icon | label | link (or value).

    `links` holds (icon_key, label, url); a row without a URL is dropped. `meta_rows` holds
    (icon_key, label, value_html) for facts such as the code version. Icons come from report_icons
    (one monochrome set), labels are plain translated text, all in the report's body font.
    """
    from .report_icons import icon
    rows = []
    for icon_key, label, url in links:
        if url:
            safe_url = escape(url, quote=True)
            rows.append(f'<span class="rl-icon">{icon(icon_key)}</span><span class="rl-label">{label}</span>'
                        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{t("link.click_here")}</a>')
    for icon_key, label, value_html in meta_rows:
        if value_html:
            rows.append(f'<span class="rl-icon">{icon(icon_key)}</span><span class="rl-label">{label}</span>'
                        f'<span class="rl-value">{value_html}</span>')
    if not rows:
        return ''
    return '<div class="report-links">' + ''.join(rows) + '</div>'


def _build_dom_captures_section(dom_captures: list) -> str:
    """Collapsible per-page DOM capture links: one compact row, expandable."""
    rows = []
    for idx, capture in enumerate(dom_captures or [], start=1):
        url = capture.get('url', '')
        if not url:
            continue
        label = f"{idx:02d} · {capture.get('name', 'page')}"
        title = (capture.get('title') or '').strip()
        if title:
            label += f" — {title}"
        rows.append(
            '<div style="padding: 1px 0;">'
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
            'style="color: var(--link-color); text-decoration: none;">'
            f'{escape(label)}</a></div>'
        )
    if not rows:
        return ''
    return (
        '<details style="margin-top: 4px; border-radius: 4px; '
        'background-color: var(--background-secondary); '
        'border-left: 3px solid var(--info-color);">'
        '<summary style="padding: 2px 10px; line-height: 1.3; cursor: pointer; font-weight: bold;">'
        + t('link.dom_captures', n=len(rows)) + '</summary>'
        '<div style="padding: 0 10px 6px 24px;">'
        + ''.join(rows)
        + '</div></details>'
    )


def _build_mosaic_section(mosaic_url: str, tiles: int = 0) -> str:
    """Collapsible "Test Mosaic" block: one step per tile, click for full size.

    Collapsed by default (user choice: the steps list stays the first thing on
    screen); the header click reveals it. The image is the compressed JPEG built
    by report_mosaic (~60 KB), lazy-loaded.
    """
    if not mosaic_url:
        return ''
    safe_url = escape(mosaic_url, quote=True)
    title = icon('mosaic', 18) + ' ' + ((t('mosaic.title_one') if tiles == 1 else t('mosaic.title_steps', tiles=tiles)) if tiles else t('mosaic.title'))
    return f"""
            <div class="section">
                <div class="section-header" onclick="toggleSection('mosaic-content')">
                    <h2>{title}</h2>
                    <button class="toggle-btn">▶</button>
                </div>
                <div id="mosaic-content" class="collapsible-content">
                    <img src="{safe_url}" alt="Step mosaic" loading="lazy"
                         onclick="openScreenshot('{safe_url}')"
                         style="display: block; max-width: 100%; height: auto; border-radius: 4px; cursor: zoom-in;
                                border: 1px solid var(--border-light); background: var(--bg-tertiary);">
                </div>
            </div>
    """


def _build_default_overview_section(
    execution_summary_html: str,
    logs_link_html: str,
    script_source_link_html: str,
    initial_screenshot_html: str,
    final_screenshot_html: str,
    test_video_html: str,
) -> str:
    """Build the standard script report overview section.

    Each state/video box only renders when it has content, so scripts run with
    capture_artifacts=False (no screenshots, no video - e.g. network/CLI
    diagnostics) don't leave behind empty "not available" boxes.
    """
    grid_items = []
    if initial_screenshot_html:
        grid_items.append(f"""
                <div class="state-video-grid-item">
                    <h3>{t("state.initial")}</h3>
                    <div class="screenshot-container">
                        {initial_screenshot_html}
                    </div>
                </div>""")
    if final_screenshot_html:
        grid_items.append(f"""
                <div class="state-video-grid-item">
                    <h3>{t("state.final")}</h3>
                    <div class="screenshot-container">
                        {final_screenshot_html}
                    </div>
                </div>""")
    if test_video_html:
        grid_items.append(f"""
                <div class="state-video-grid-item">
                    <h3>{t("state.video")}</h3>
                    <div class="test-video-content">
                        {test_video_html}
                    </div>
                </div>""")

    grid_section = ''
    if grid_items:
        grid_section = f"""
            <div class="state-video-grid-container">
                {''.join(grid_items)}
            </div>"""

    return f"""
            {grid_section}
            <div class="execution-summary-section">
                <h3>{t("section.execution_summary")}</h3>
                <div class="execution-summary-content">
                    {execution_summary_html}
                    {logs_link_html}
                    {script_source_link_html}
                </div>
            </div>
    """


def _build_report_catalog(report_data: Dict):
    """Language catalog for one report: platform strings + the script's `<script>.i18n.json`.

    report_data may carry `i18n_script_catalog` (a ready dict, tests/harnesses) or
    `script_i18n_path` (explicit file); otherwise the file is found through the script name.
    `script_i18n_inline` (the script's `main._i18n`) is merged over the file.
    """
    override = report_data.get('i18n_script_catalog')
    if isinstance(override, dict):
        return build_catalog(script_strings=override)
    identity = report_data.get('script_identity')
    script_ref = (identity.get('script_ref') if isinstance(identity, dict) else '') or report_data.get('script_name', '')
    strings = load_script_strings(report_data.get('script_i18n_path') or script_i18n_path(script_ref))
    # `main._i18n` in the script source (the only option for a virtual script) wins entry by entry.
    strings.update(clean_script_strings(report_data.get('script_i18n_inline')))
    return build_catalog(script_strings=strings)


def _inject_catalog(page: str) -> str:
    """Draw emoji as report icons, then embed the emoji-icon map and the used-keys catalog
    just before </body> (the page script redraws icons after a language switch)."""
    from .report_icons import emoji_icons_script_tag, iconify_html
    page = iconify_html(page)
    index = page.rfind('</body>')
    if index < 0:
        return page
    tags = emoji_icons_script_tag() + '\n' + catalog_script_tag()
    return page[:index] + tags + '\n' + page[index:]


def generate_validation_report(report_data: Dict) -> str:
    """
    Generate HTML validation report with embedded CSS and screenshots.

    The page is translatable (EN/FR/DE switcher): the catalog is active for the whole build and
    its used keys are embedded before </body>.

    Args:
        report_data: Dictionary containing all report information

    Returns:
        Complete HTML report as string
    """
    try:
        catalog = _build_report_catalog(report_data)
    except Exception as e:
        print(f"[@utils:report_utils:generate_validation_report] i18n catalog unavailable: {e}")
        catalog = None
    with use_report_catalog(catalog):
        return _inject_catalog(_generate_validation_report_html(report_data))


def _generate_validation_report_html(report_data: Dict) -> str:
    """Build the report HTML (runs inside the active language catalog)."""
    try:
        print(f"[@utils:report_utils:generate_validation_report] Generating report for {report_data.get('script_name')}")
        
        # Extract report data with safe defaults
        script_name = report_data.get('script_name', 'Unknown Script')
        # For AI testcases, prefer human-friendly title if provided
        # Expect optional fields: ai_testcase_name, ai_display_name
        ai_display_name = report_data.get('ai_testcase_name') or report_data.get('ai_display_name')
        if ai_display_name:
            script_name = f"AI : {ai_display_name}"
        device_info = report_data.get('device_info', {})
        host_info = report_data.get('host_info', {})
        execution_time = report_data.get('execution_time', 0)
        success = report_data.get('success', False)
        step_results = report_data.get('step_results', [])
        screenshots = report_data.get('screenshots', {})
        error_msg = report_data.get('error_msg', '')
        timestamp = report_data.get('timestamp', datetime.now().strftime('%Y%m%d%H%M%S'))
        start_time = report_data.get('start_time', timestamp)
        end_time = report_data.get('end_time', timestamp)
        
        # Calculate stats
        total_steps = len(step_results)
        passed_steps = sum(1 for step in step_results if step.get('success', False))
        failed_steps = total_steps - passed_steps
        
        # Generate HTML content
        html_template = create_themed_html_template()
        
        # Safely handle video URL - ensure it's either a valid URL or empty string
        test_video_url = report_data.get('test_video_url', '')
        if test_video_url is None:
            test_video_url = ''
        
        # Use detailed zap summary (stored separately to avoid overwrite by fullzap summary)
        zap_summary_section = ""
        zap_detailed_summary = report_data.get('zap_detailed_summary', '')
        if zap_detailed_summary:
            zap_summary_section = f"""
            <div class="section">
                <div class="section-header" onclick="toggleSection('zap-summary-content')">
                    <h2>{icon('zap', 18)} {t("zap.title")}</h2>
                    <button class="toggle-btn">▶</button>
                </div>
                <div id="zap-summary-content" class="collapsible-content">
                    <div class="execution-summary-section">
                        <h3>{t("zap.heading")}</h3>
                        <div class="execution-summary-content">
                            <pre style="white-space: pre-wrap; font-family: 'Courier New', monospace; margin: 0;">{tx_lines(zap_detailed_summary)}</pre>
                        </div>
                    </div>
                </div>
            </div>
            """

        # Edge Results section (validation): grouped Success/Failed/Skipped, with
        # at-a-glance count chips in the header. Same collapsible mechanism as the
        # zap section above. Counts derived from step_results so they match the
        # headline totals (skipped steps are recorded as success=False+skipped).
        edge_results_section = ""
        edge_results_summary = report_data.get('edge_results_summary', '')
        if edge_results_summary:
            ok_n = sum(1 for s in step_results if s.get('success'))
            skip_n = sum(1 for s in step_results if s.get('skipped'))
            fail_n = len(step_results) - ok_n - skip_n
            edge_results_section = f"""
            <div class="section">
                <div class="section-header" onclick="toggleSection('edge-results-content')">
                    <h2>{icon('edge', 18)} {t("edge.title", ok=ok_n, fail=fail_n, skip=skip_n)}</h2>
                    <button class="toggle-btn">▶</button>
                </div>
                <div id="edge-results-content" class="collapsible-content">
                    <div class="execution-summary-section">
                        <div class="execution-summary-content">
                            <pre style="white-space: pre-wrap; font-family: 'Courier New', monospace; margin: 0;">{tx_lines(edge_results_summary, escape_markup=True)}</pre>
                        </div>
                    </div>
                </div>
            </div>
            """

        # Generate combined links bar (compact stacked block)
        script_source_url = report_data.get('script_source_url', '')
        verification_review_url = report_data.get('verification_review_url', '')
        metadata_url = report_data.get('metadata_url', '')
        # Optional link to the latest standalone zap measurement report (set by zap scripts
        # into custom_data). _build_report_links_bar drops empty-URL entries, so this only
        # shows for zap runs that produced a report.
        zap_report_url = (report_data.get('custom_data') or {}).get('zap_report_url', '')
        subtitle_report_url = (report_data.get('custom_data') or {}).get('subtitle_report_url', '')  # subtitle_qa.py
        code_version = report_data.get('code_version') or _read_code_version()
        trigger = report_data.get('trigger') or {}
        trigger_html = ''
        if isinstance(trigger, dict) and trigger.get('type'):
            trigger_bits = [f"type <strong>{escape(str(trigger.get('type')))}</strong>"]
            if trigger.get('caller_user'):
                trigger_bits.append(f"user <strong>{escape(str(trigger.get('caller_user')))}</strong>")
            trigger_html = ' · '.join(trigger_bits)
        links_bar = _build_report_links_bar([
            ('logs', t('link.logs'), report_data.get('logs_url', '')),
            ('metadata', t('link.metadata'), metadata_url),
            ('review', t('link.verification_review'), verification_review_url),
            # Only present when a selector missed; _build_report_links_bar drops empty URLs.
            ('ui_dumps', t('link.ui_dumps'), report_data.get('ui_dumps_url', '')),
            ('code', t('link.code_source'), script_source_url),
            ('zap', t('link.zap_report'), zap_report_url),
            ('subtitle', t('link.subtitle_report'), subtitle_report_url),
            ('mosaic', t('link.mosaic'), report_data.get('mosaic_url', '')),
        ], meta_rows=[
            ('version', t('meta.code_version'), f'<code>{escape(code_version)}</code>' if code_version else ''),
            ('trigger', t('meta.trigger'), trigger_html),
        ])
        links_bar += _build_dom_captures_section(report_data.get('dom_captures'))

        initial_screenshot_html = get_thumbnail_screenshot_html(screenshots.get('initial'))
        final_screenshot_html = get_thumbnail_screenshot_html(screenshots.get('final'))
        test_video_html = get_video_thumbnail_html(test_video_url, 'Test Execution') if test_video_url else ''
        execution_summary_html = format_console_summary_for_html(report_data.get('execution_summary', ''))
        overview_section = _build_default_overview_section(
            execution_summary_html=execution_summary_html,
            logs_link_html=links_bar,
            script_source_link_html='',
            initial_screenshot_html=initial_screenshot_html,
            final_screenshot_html=final_screenshot_html,
            test_video_html=test_video_html,
        )

        # Build testcase builder link if testcase_id is available
        testcase_id = report_data.get('testcase_id')
        testcase_builder_link = report_data.get('testcase_builder_link', '')
        if not testcase_builder_link and testcase_id:
            testcase_builder_link = f' | <a href="/builder/test-builder?testcase_id={testcase_id}" style="color: #60a5fa; text-decoration: none;">{icon("open", 14)} {t("header.open_testcase_builder")}</a>'

        # Share button: opens the share dialog of the web app for this run (same origin as the
        # report; an outside viewer of a snapshot never gets it, the builder drops it).
        script_result_id = report_data.get('script_result_id')
        share_button = (
            f'<a class="header-icon-btn report-share-btn" href="/test-results/reports?share={script_result_id}" '
            f'target="_blank" rel="noopener" data-i18n-title="header.share_snapshot" '
            f'title="{t_attr("header.share_snapshot")}" aria-label="{t_attr("header.share_snapshot")}">{icon("share", 18)}</a>'
        ) if script_result_id else ''

        # Replace placeholders with actual content
        html_content = html_template.format(
            share_button=share_button,
            script_name=script_name,
            execution_date=format_execution_date(start_time),
            start_time=format_timestamp(start_time),
            end_time=format_timestamp(end_time),
            success_status=t('badge.pass') if success else t('badge.fail'),
            success_class="success" if success else "failure",
            execution_time=format_execution_time(execution_time),
            device_name=device_info.get('device_name', 'Unknown Device'),
            device_model=device_info.get('device_model', 'Unknown Model'),
            host_name=host_info.get('host_name', 'Unknown Host'),
            total_steps=total_steps,
            passed_steps=passed_steps,
            failed_steps=failed_steps,
            success_steps_text=t('summary.steps', n=passed_steps, total=total_steps),
            failure_steps_text=t('summary.steps', n=failed_steps, total=total_steps),
            step_results_html=create_compact_step_results_section(step_results, screenshots),
            error_section=create_error_section(tx(error_msg)) if error_msg else '',
            overview_section=overview_section,
            zap_summary_section=zap_summary_section,
            edge_results_section=edge_results_section,
            mosaic_section=_build_mosaic_section(report_data.get('mosaic_url', ''), report_data.get('mosaic_tiles', 0)),
            logs_link=links_bar,
            script_source_link='',
            steps_section_title=t('steps.title', passed=passed_steps, total=total_steps),
            testcase_builder_link=testcase_builder_link,
        )
        
        print(f"[@utils:report_utils:generate_validation_report] Report generated successfully")
        return html_content
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[@utils:report_utils:generate_validation_report] Error: {str(e)}")
        print(f"[@utils:report_utils:generate_validation_report] Full traceback: {error_details}")
        return create_error_report(f"Report generation failed: {str(e)}")


def generate_and_upload_script_report(
    script_name: str,
    device_info: Dict,
    host_info: Dict,
    execution_time: int,
    success: bool,
    step_results: List[Dict] = None,
    screenshot_paths: List[str] = None,
    screenshot_url_mapping: Dict[str, str] = None,  # NEW: Pre-built mapping from upload
    error_message: str = "",
    userinterface_name: str = "",
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    parameters: str = "",
    execution_summary: str = "",
    test_video_url: str = "",
    script_result_id: str = None,
    custom_data: Dict = None,
    zap_detailed_summary: str = "",
    edge_results_summary: str = "",
    script_identity: Dict[str, Any] = None,
    testcase_id: str = None,
    metadata_url: str = "",
    trigger: Dict[str, Any] = None,
    mosaic_local_path: str = "",
    mosaic_tile_count: int = 0,
    dom_captures: Optional[List[Dict[str, Any]]] = None,
    ui_dumps: Optional[Tuple[str, int]] = None,
    script_i18n: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, str]:
    """
    Generate HTML report and upload to R2 storage - extracted from validation.py

    script_i18n: the script's `main._i18n` translations (merged over its `<script>.i18n.json`).
    dom_captures / ui_dumps: this execution's DOM captures and (UI dump file, count) when the
    caller froze them earlier (a testcase report built in the background, after the next run
    reset the process-global sessions). None reads the sessions, as always.
    Can be used by any script execution (validation, simple scripts, etc.)
    
    Returns:
        Dict with 'report_url', 'report_path', and 'success' keys
    """
    try:
       
        from .cloudflare_utils import (
            upload_script_report,
            upload_validation_screenshots,
            upload_script_logs,
            upload_script_source_artifact,
            upload_test_video,
        )
        from datetime import datetime
        
        # Keep a human-readable execution timestamp for report display/time math.
        execution_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        # Use a high-precision upload timestamp for R2 paths to avoid collisions
        # when multiple runs of the same script/device model finish in the same second.
        upload_timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
       
        # Handle simple script execution (no step_results)
        # Don't include script output here - it's available via "Execution Logs" link
        if not step_results:
            step_results = [{
                'step_number': 1,
                'success': success,
                'screenshot_path': None,
                'message': f'Script execution: {script_name}',
                'execution_time_ms': execution_time,
                'start_time': 'N/A',
                'end_time': 'N/A',
                'from_node': 'Script Start',
                'to_node': 'Script End',
                'actions': [{
                    'command': f'python {script_name}',
                    'params': {'parameters': parameters} if parameters else {},
                    'label': f'Execute {script_name} script'
                }],
                'verifications': [],
                'verification_results': []
            }]
        
        # Calculate verification statistics
        total_verifications = sum(len(step.get('verification_results', [])) for step in step_results)
        passed_verifications = sum(
            sum(1 for v in step.get('verification_results', []) if v.get('success', False)) 
            for step in step_results
        )
        failed_verifications = total_verifications - passed_verifications
        
        # Upload screenshots FIRST to get R2 URLs (or use provided mapping)
        url_mapping = screenshot_url_mapping or {}  # Use provided mapping if available
        
        if not url_mapping and screenshot_paths:
            # No mapping provided - need to upload screenshots
            print(f"[@utils:report_utils:generate_and_upload_script_report] No mapping provided - uploading screenshots...")
            screenshot_result = upload_validation_screenshots(
                screenshot_paths=screenshot_paths,
                device_model=device_info.get('device_model', 'unknown'),
                script_name=script_name.replace('.py', ''),
                timestamp=upload_timestamp,
                script_result_id=script_result_id
            )
            
            if screenshot_result['success']:
                uploaded_screenshots = screenshot_result.get('uploaded_screenshots', [])
                
                for i, upload_info in enumerate(uploaded_screenshots):
                    try:
                        local_path = upload_info['local_path']
                        r2_url = upload_info['url']
                        url_mapping[local_path] = r2_url
                    except Exception as mapping_error:
                        print(f"[@utils:report_utils:generate_and_upload_script_report] ERROR: Failed to process mapping {i+1}: {mapping_error}")
                        print(f"[@utils:report_utils:generate_and_upload_script_report] ERROR: upload_info: {upload_info}")
                        import traceback
                        print(f"[@utils:report_utils:generate_and_upload_script_report] ERROR: Traceback: {traceback.format_exc()}")
                        # Continue with next mapping instead of crashing
                        continue
                        
            else:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Screenshot upload failed: {screenshot_result.get('error', 'Unknown error')}")
        elif url_mapping:
            print(f"[@utils:report_utils:generate_and_upload_script_report] Using provided mapping with {len(url_mapping)} local->R2 URL pairs") 
        # Update step_results to use R2 URLs instead of local paths
        updated_step_results = update_step_results_with_r2_urls(step_results, url_mapping)
        
        # Upload script logs to R2 if stdout is provided
        logs_url = ""
        logs_path = ""
        if stdout and stdout.strip():
            print(f"[@utils:report_utils:generate_and_upload_script_report] Uploading script logs...")
            _t = _phase_t0()
            logs_upload_result = upload_script_logs(
                log_content=stdout,
                device_model=device_info.get('device_model', 'unknown'),
                script_name=script_name.replace('.py', ''),
                timestamp=upload_timestamp,
                script_result_id=script_result_id
            )
            _log_phase('report.logs_upload', _t, f"bytes={len(stdout)}")
            
            if logs_upload_result['success']:
                logs_url = logs_upload_result['url']
                logs_path = logs_upload_result['path']
                print(f"[@utils:report_utils:generate_and_upload_script_report] Logs uploaded: {logs_url}")
            else:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Logs upload failed: {logs_upload_result.get('error', 'Unknown error')}")
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] No stdout provided, skipping log upload")

        artifact_folder_path = ''
        if logs_path:
            artifact_folder_path = os.path.dirname(logs_path)
        else:
            folder_name = _build_script_artifact_folder_name(
                script_name.replace('.py', ''),
                upload_timestamp,
                script_result_id,
            )
            artifact_folder_path = f"script-logs/{device_info.get('device_model', 'unknown')}/{folder_name}"

        # Upload per-page DOM captures (web scripts) alongside execution.txt.
        # Captures are pulled from the process-global dom_capture session, so no
        # script/executor plumbing is needed. Empty for non-web scripts.
        dom_capture_links = []
        try:
            if dom_captures is None:
                from .dom_capture import get_dom_captures
                dom_captures = get_dom_captures()
            dom_file_mappings = [
                {
                    'local_path': capture['path'],
                    'remote_path': f"{artifact_folder_path}/dom/{os.path.basename(capture['path'])}",
                    'content_type': 'text/plain; charset=utf-8',
                }
                for capture in dom_captures
                if os.path.exists(capture.get('path', ''))
            ]
            if dom_file_mappings:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Uploading {len(dom_file_mappings)} DOM capture(s)...")
                _t = _phase_t0()
                dom_upload_result = get_cloudflare_utils().upload_files(dom_file_mappings, for_report_assets=True)
                _log_phase('report.dom_captures_upload', _t, f"files={len(dom_file_mappings)}")
                dom_url_by_local = {f['local_path']: f['url'] for f in dom_upload_result.get('uploaded_files', [])}
                for capture in dom_captures:
                    dom_url = dom_url_by_local.get(capture.get('path', ''))
                    if dom_url:
                        dom_capture_links.append({
                            'name': capture.get('name', 'page'),
                            'title': capture.get('title', ''),
                            'url': dom_url,
                            'page_url': capture.get('url', ''),
                        })
        except Exception as dom_error:
            print(f"[@utils:report_utils:generate_and_upload_script_report] DOM capture upload skipped: {dom_error}")

        # Upload this execution's UI dump traces (device scripts) the same way: a selector
        # that missed is only diagnosable against the tree it actually searched, and that
        # belongs in the report rather than in execution.txt. Empty for scripts that never
        # missed a selector, and for web scripts.
        ui_dumps_url = ''
        try:
            if ui_dumps is None:
                from .ui_dump_capture import get_ui_dump_count, get_ui_dump_file
                ui_dumps_path = get_ui_dump_file()
                dump_count = get_ui_dump_count() if ui_dumps_path else 0
            else:
                ui_dumps_path, dump_count = ui_dumps
            if ui_dumps_path:
                print(f"[@utils:report_utils:generate_and_upload_script_report] "
                      f"Uploading {dump_count} UI dump trace(s)...")
                _t = _phase_t0()
                ui_dumps_result = get_cloudflare_utils().upload_files([{
                    'local_path': ui_dumps_path,
                    'remote_path': f"{artifact_folder_path}/ui_dumps.txt",
                    'content_type': 'text/plain; charset=utf-8',
                }], for_report_assets=True)
                _log_phase('report.ui_dumps_upload', _t)
                uploaded = ui_dumps_result.get('uploaded_files', [])
                ui_dumps_url = uploaded[0]['url'] if uploaded else ''
                try:
                    os.remove(ui_dumps_path)
                except OSError:
                    pass
        except Exception as ui_dump_error:
            print(f"[@utils:report_utils:generate_and_upload_script_report] UI dump upload skipped: {ui_dump_error}")

        script_source_url = ''
        script_source_path = ''
        script_source_ref = ''
        if isinstance(script_identity, dict):
            script_source_ref = script_identity.get('script_ref', '')
        if not script_source_ref:
            script_source_ref = normalize_script_ref(script_name)

        local_script_source_path = resolve_script_source_path(script_source_ref)
        if local_script_source_path:
            print(f"[@utils:report_utils:generate_and_upload_script_report] Uploading script source artifact...")
            _t = _phase_t0()
            source_upload_result = upload_script_source_artifact(
                local_source_path=local_script_source_path,
                device_model=device_info.get('device_model', 'unknown'),
                script_name=script_name.replace('.py', ''),
                timestamp=upload_timestamp,
                script_result_id=script_result_id,
                remote_path=f"{artifact_folder_path}/script_source.py",
            )
            _log_phase('report.script_source_upload', _t)
            if source_upload_result['success']:
                script_source_url = source_upload_result['url']
                script_source_path = source_upload_result['path']
                print(f"[@utils:report_utils:generate_and_upload_script_report] Script source uploaded: {script_source_url}")
            else:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Script source upload failed: {source_upload_result.get('error', 'Unknown error')}")
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] No local script source found for ref: {script_source_ref}")
        
        # Upload test video to R2 if test_video_url is provided and points to a local file
        uploaded_test_video_url = test_video_url
        if test_video_url and test_video_url.strip():
            # Check if it's a local file path that needs to be uploaded
            if os.path.exists(test_video_url) and test_video_url.endswith('.mp4'):
                print(f"[@utils:report_utils:generate_and_upload_script_report] Uploading test video: {test_video_url}")
                _t = _phase_t0()
                _video_bytes = os.path.getsize(test_video_url)
                video_upload_result = upload_test_video(
                    local_video_path=test_video_url,
                    device_model=device_info.get('device_model', 'unknown'),
                    script_name=script_name.replace('.py', ''),
                    timestamp=upload_timestamp,
                    script_result_id=script_result_id
                )
                _log_phase('report.video_upload', _t, f"bytes={_video_bytes}")
                
                if video_upload_result['success']:
                    uploaded_test_video_url = video_upload_result['video_url']
                    print(f"[@utils:report_utils:generate_and_upload_script_report] Test video uploaded: {uploaded_test_video_url}")
                else:
                    print(f"[@utils:report_utils:generate_and_upload_script_report] Test video upload failed: {video_upload_result.get('error', 'Unknown error')}")
                    # Keep original URL as fallback
            else:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Test video URL provided but not a local file, using as-is: {test_video_url}")
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] No test video provided")
        
        # Calculate proper start and end times based on actual script execution
        # execution_timestamp is when report is generated (end time)
        # start_time should be execution_timestamp - execution_time
        execution_time_seconds = execution_time / 1000.0  # Convert ms to seconds
        
        # Parse execution_timestamp to datetime object
        end_datetime = datetime.strptime(execution_timestamp, '%Y%m%d%H%M%S')
        
        # Calculate start time by subtracting execution duration
        from datetime import timedelta
        start_datetime = end_datetime - timedelta(seconds=execution_time_seconds)
        
        # Format back to timestamp strings
        calculated_start_time = start_datetime.strftime('%Y%m%d%H%M%S')
        calculated_end_time = execution_timestamp  # This is already the end time

        verification_review_url = ''
        verification_review_path = f"{artifact_folder_path}/verification_review.md"
        if verification_review_path:
            verification_review_url = get_cloudflare_utils().get_url_for_report_asset(verification_review_path)
        
        # Step mosaic: one compressed JPEG (one tile per step) next to report.html.
        #
        # BUG (found 2026-09-03 on a real vpt-pi1/stb3 run): by the time this
        # function runs, the executor has already uploaded step screenshots to
        # R2 and deleted the local "cold" copies (cloudflare_utils.upload_files
        # auto_delete_cold=True — see generate_report_for_context), so building
        # from `step_results` here almost always finds zero local files ("No
        # local step screenshots, skipping mosaic"). The executor now builds
        # the mosaic BEFORE that upload/delete and hands us the local JPEG via
        # `mosaic_local_path` (+ its tile count); we just upload it here,
        # mirroring how `test_video_url` is handled. Kept the from-scratch
        # build as a fallback for any other caller (e.g. a standalone script
        # calling this directly) that still has fresh local screenshots.
        mosaic_url = ''
        mosaic_r2_path = ''
        mosaic_tiles = mosaic_tile_count
        built_mosaic_path = mosaic_local_path if (mosaic_local_path and os.path.exists(mosaic_local_path)) else ''
        try:
            if not built_mosaic_path:
                import tempfile
                from .report_mosaic import build_step_mosaic
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as mosaic_tmp:
                    candidate_path = mosaic_tmp.name
                mosaic_info = build_step_mosaic(step_results, candidate_path)
                if mosaic_info:
                    built_mosaic_path = candidate_path
                    mosaic_tiles = mosaic_info['tiles']
                elif os.path.exists(candidate_path):
                    os.unlink(candidate_path)

            if built_mosaic_path:
                report_folder_name = _build_script_artifact_folder_name(
                    script_name.replace('.py', ''), upload_timestamp, script_result_id,
                )
                mosaic_r2_path = f"script-reports/{device_info.get('device_model', 'unknown')}/{report_folder_name}/mosaic.jpg"
                _t = _phase_t0()
                mosaic_upload = get_cloudflare_utils().upload_files(
                    [{'local_path': built_mosaic_path, 'remote_path': mosaic_r2_path, 'content_type': 'image/jpeg'}],
                    for_report_assets=True,
                )
                _log_phase('report.mosaic_upload', _t)
                if mosaic_upload.get('uploaded_files'):
                    mosaic_url = mosaic_upload['uploaded_files'][0]['url']
                    print(f"[@utils:report_utils:generate_and_upload_script_report] Mosaic uploaded ({mosaic_tiles} tiles): {mosaic_url}")
                else:
                    mosaic_r2_path = ''
                    print(f"[@utils:report_utils:generate_and_upload_script_report] Mosaic upload failed: {mosaic_upload.get('failed_uploads')}")
        except Exception as mosaic_error:
            print(f"[@utils:report_utils:generate_and_upload_script_report] Mosaic skipped: {mosaic_error}")
        finally:
            # Always a scratch file at this point (ours or the executor's) — safe to remove.
            if built_mosaic_path and os.path.exists(built_mosaic_path):
                os.unlink(built_mosaic_path)

        # Prepare report data (same structure as validation.py) - now with R2 URLs and correct timestamps
        report_data = {
            'script_name': script_name,
            'script_i18n_inline': script_i18n,
            'device_info': device_info,
            'host_info': host_info,
            'execution_time': execution_time,
            'success': success,
            'step_results': updated_step_results,  # Use updated step results with R2 URLs
            'screenshots': {
                'initial': url_mapping.get(screenshot_paths[0], screenshot_paths[0]) if screenshot_paths and len(screenshot_paths) > 0 else None,
                'steps': [url_mapping.get(path, path) for path in screenshot_paths[1:-1]] if screenshot_paths and len(screenshot_paths) > 2 else [],
                'final': url_mapping.get(screenshot_paths[-1], screenshot_paths[-1]) if screenshot_paths and len(screenshot_paths) > 1 else None
            },
            'error_msg': error_message,
            'timestamp': execution_timestamp,
            'start_time': calculated_start_time,  # Proper start time
            'end_time': calculated_end_time,      # Proper end time
            'userinterface_name': userinterface_name or f'script_{script_name}',
            'total_steps': len(updated_step_results),
            'passed_steps': sum(1 for step in updated_step_results if step.get('success', False)),
            'failed_steps': sum(1 for step in updated_step_results if not step.get('success', True)),
            'total_verifications': total_verifications,
            'passed_verifications': passed_verifications,
            'failed_verifications': failed_verifications,
            'execution_summary': execution_summary,
            'test_video_url': uploaded_test_video_url,
            'script_result_id': script_result_id,
            'custom_data': custom_data or {},  # Pass zap data from memory
            'zap_detailed_summary': zap_detailed_summary,
            'edge_results_summary': edge_results_summary,
            'logs_url': logs_url,  # Add logs URL for clickable link in report
            'script_identity': script_identity or {},
            'testcase_id': testcase_id,
            # Built by generate_validation_report from testcase_id (it needs the language catalog).
            'testcase_builder_link': '',
            'script_source_url': script_source_url,
            'verification_review_url': verification_review_url,
            'metadata_url': metadata_url,
            'code_version': _read_code_version(),
            'trigger': trigger or {},
            'dom_captures': dom_capture_links,
            'ui_dumps_url': ui_dumps_url,
            'mosaic_url': mosaic_url,
            'mosaic_tiles': mosaic_tiles,
        }
        
        _t = _phase_t0()
        html_content = generate_validation_report(report_data)
        _log_phase('report.html_build', _t, f"bytes={len(html_content or '')}")
        
        # Upload report to R2
        _t = _phase_t0()
        upload_result = upload_script_report(
            html_content=html_content,
            device_model=device_info.get('device_model', 'unknown'),
            script_name=script_name.replace('.py', ''),
            timestamp=upload_timestamp,
            script_result_id=script_result_id
        )
       
        _log_phase('report.html_upload', _t)
        if upload_result['success']:
            report_url = upload_result['report_url']
            report_path = upload_result['report_path']
            print(f"[@utils:report_utils:generate_and_upload_script_report] Report uploaded: {report_url}")
            return {
                'success': True,
                'report_url': report_url,
                'report_path': report_path,
                'logs_url': logs_url,
                'logs_path': logs_path,
                'script_source_url': script_source_url,
                'script_source_path': script_source_path,
                'verification_review_url': verification_review_url,
                'verification_review_path': verification_review_path,
                'mosaic_url': mosaic_url,
                'mosaic_path': mosaic_r2_path,
                'ui_dumps_url': ui_dumps_url,
            }
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] Upload failed: {upload_result.get('error', 'Unknown error')}")
            return {
                'success': False,
                'report_url': '',
                'report_path': '',
                'logs_url': '',
                'logs_path': '',
                'script_source_url': script_source_url,
                'script_source_path': script_source_path,
                'verification_review_url': verification_review_url,
                'verification_review_path': verification_review_path,
            }
        
    except Exception as e:
        print(f"[@utils:report_utils:generate_and_upload_script_report] Error: {str(e)}")
        return {
            'success': False,
            'report_url': '',
            'report_path': '',
            'logs_url': '',
            'logs_path': ''
        }


def generate_campaign_orchestrator_report(report_data: Dict[str, Any]) -> str:
    """Generate campaign orchestrator HTML using the shared themed report template.

    Platform words are translatable (EN/FR/DE switcher); campaigns have no per-script file.
    """
    with use_report_catalog(build_catalog(script_strings={})):
        return _inject_catalog(_generate_campaign_orchestrator_report_html(report_data))


def _generate_campaign_orchestrator_report_html(report_data: Dict[str, Any]) -> str:
    campaign_name = report_data.get('campaign_name', 'Campaign')
    campaign_id = report_data.get('campaign_id', '')
    execution_id = report_data.get('campaign_execution_id', '')
    started_at = report_data.get('started_at', datetime.now().strftime('%Y%m%d%H%M%S'))
    ended_at = report_data.get('ended_at', started_at)
    execution_time = int(report_data.get('execution_time', 0) or 0)
    device_name = report_data.get('device_name', 'Unknown Device')
    device_model = report_data.get('device_model', 'Unknown Model')
    host_name = report_data.get('host_name', 'Unknown Host')
    script_executions = report_data.get('script_executions', []) or []
    logs_url = report_data.get('logs_url', '') or ''
    overall_success = bool(report_data.get('success', False))
    error_msg = report_data.get('error_msg', '') or ''

    total_scripts = int(report_data.get('total_scripts', len(script_executions)) or 0)
    completed_scripts = int(report_data.get('completed_scripts', len(script_executions)) or 0)
    successful_scripts = int(report_data.get('successful_scripts', sum(1 for item in script_executions if item.get('success'))) or 0)
    failed_scripts = int(report_data.get('failed_scripts', sum(1 for item in script_executions if not item.get('success') and not item.get('skipped', False))) or 0)
    skipped_scripts = int(report_data.get('skipped_scripts', sum(1 for item in script_executions if item.get('skipped', False))) or 0)

    logs_link_html = ''
    if logs_url:
        safe_logs_url = escape(logs_url, quote=True)
        logs_link_html = f"""
            <div style="margin-top: 8px; background-color: var(--background-secondary); border-radius: 4px; border-left: 3px solid var(--info-color); padding: 8px 10px;">
                <div style="font-weight: 600; margin-bottom: 2px;">{t("campaign.logs")}</div>
                <a href="{safe_logs_url}" target="_blank" style="color: var(--link-color); text-decoration: none; font-weight: bold;">{t("campaign.open_logs")}</a>
            </div>
        """

    summary_text = "\n".join([
        f"Campaign: {campaign_name}",
        f"Campaign ID: {campaign_id or 'n/a'}",
        f"Execution ID: {execution_id or 'n/a'}",
        f"Scripts: total={total_scripts}, completed={completed_scripts}, success={successful_scripts}, failed={failed_scripts}, skipped={skipped_scripts}",
    ])
    overview_section = f"""
            <div class="execution-summary-section">
                <h3>{t("campaign.overview")}</h3>
                <div class="execution-summary-content">
                    {format_console_summary_for_html(summary_text)}
                    {logs_link_html}
                </div>
            </div>
    """

    items_html: List[str] = ['<div class="step-list">']
    for idx, script in enumerate(script_executions):
        script_name = str(script.get('script_name', '') or f'script_{idx + 1}')
        script_type = str(script.get('script_type') or 'script')
        success = bool(script.get('success', False))
        skipped = bool(script.get('skipped', False))
        execution_time_ms = int(script.get('execution_time_ms') or 0)
        report_url = str(script.get('report_url') or '')
        per_script_logs_url = str(script.get('logs_url') or '')
        script_result_id = str(script.get('script_result_id') or '')
        script_outputs = script.get('script_outputs') or {}
        script_inputs = script.get('script_inputs') or {}
        script_error = str(script.get('error') or '')

        source_url = str(script.get('script_source_url') or '')

        status_label = t('badge.skip') if skipped else (t('badge.pass') if success else t('badge.fail'))
        status_class = 'skipped' if skipped else ('success' if success else 'failure')

        # Everything scalar lives on the row itself (two lines, links on the
        # right) so a campaign reads top-to-bottom without expanding anything.
        # The details panel only exists for payloads that can't fit a line:
        # inputs / outputs JSON and the error text.
        link_style = 'color: var(--link-color); text-decoration: none; font-size: 0.85em;'
        row_links: List[str] = []
        for label, url in ((t('campaign.report'), report_url), (t('campaign.logs_short'), per_script_logs_url), (t('campaign.source'), source_url)):
            if url:
                row_links.append(
                    f'<a href="{escape(url, quote=True)}" target="_blank" style="{link_style}" '
                    f'onclick="event.stopPropagation()">{label}</a>'
                )
        links_html = (
            '<span style="display: flex; gap: 14px; white-space: nowrap; margin-left: auto; padding-left: 16px;">'
            + ''.join(row_links) + '</span>'
        ) if row_links else ''

        meta_parts = [escape(script_type), escape(format_execution_time(execution_time_ms))]
        if script_result_id:
            meta_parts.append(t('campaign.result', id=script_result_id))
        if script_error:
            meta_parts.append(
                f'<span style="color: var(--failure-text);">{escape(script_error[:120])}'
                f'{"…" if len(script_error) > 120 else ""}</span>'
            )
        meta_html = ' | '.join(meta_parts)

        detail_blocks: List[str] = []
        if script_inputs:
            detail_blocks.append(
                f'<div class="action-item"><strong>{t("campaign.input")}</strong><pre style="white-space: pre-wrap; margin-top: 6px;">{escape(json.dumps(script_inputs, indent=2, sort_keys=True, default=str))}</pre></div>'
            )
        if script_outputs:
            detail_blocks.append(
                f'<div class="action-item"><strong>{t("campaign.outputs")}</strong><pre style="white-space: pre-wrap; margin-top: 6px;">{escape(json.dumps(script_outputs, indent=2, sort_keys=True, default=str))}</pre></div>'
            )
        if script_error:
            detail_blocks.append(f'<div class="failure-action-item executed"><strong>{t("campaign.error")}</strong> {tx(script_error, escape_markup=True)}</div>')

        if detail_blocks:
            item_attrs = f' onclick="toggleStep(\'campaign-script-{idx}\')"'
            details_html = f"""
            <div id="campaign-script-{idx}" class="step-details">
                <div class="step-details-content" style="grid-template-columns: 1fr;">
                    <div class="step-info">
                        {''.join(detail_blocks)}
                    </div>
                </div>
            </div>"""
            expand_hint = '<span style="font-size: 0.8em; color: var(--text-secondary); white-space: nowrap; padding-left: 16px;">' + t('campaign.details') + '</span>'
        else:
            item_attrs = ' style="cursor: default;"'
            details_html = ''
            expand_hint = ''

        items_html.append(
            f"""
            <div class="step-item {status_class}"{item_attrs}>
                <div class="step-number">{idx + 1}</div>
                <div class="step-status">
                    <span class="step-status-badge {status_class}">{status_label}</span>
                </div>
                <div class="step-message" style="display: flex; align-items: center; flex-wrap: wrap;">
                    <span style="flex: 1; min-width: 260px;">
                        {escape(script_name)}
                        <div class="step-timing-inline" style="margin-left: 0;">{meta_html}</div>
                    </span>
                    {expand_hint}{links_html}
                </div>
            </div>{details_html}
            """
        )
    items_html.append('</div>')

    html_template = create_themed_html_template()
    return html_template.format(
        share_button='',
        script_name=escape(campaign_name),
        execution_date=format_execution_date(started_at),
        start_time=format_timestamp(started_at),
        end_time=format_timestamp(ended_at),
        success_status=t('badge.pass') if overall_success else t('badge.fail'),
        success_class="success" if overall_success else "failure",
        execution_time=format_execution_time(execution_time),
        device_name=escape(device_name),
        device_model=escape(device_model),
        host_name=escape(host_name),
        total_steps=total_scripts,
        passed_steps=successful_scripts,
        failed_steps=failed_scripts,
        success_steps_text=t('summary.steps', n=successful_scripts, total=total_scripts),
        failure_steps_text=t('summary.steps', n=failed_scripts, total=total_scripts),
        step_results_html=''.join(items_html),
        error_section=create_error_section(tx(error_msg, escape_markup=True)) if error_msg else '',
        overview_section=overview_section,
        zap_summary_section='',
        edge_results_section='',
        mosaic_section='',
        logs_link=logs_link_html,
        script_source_link='',
        # Required by the shared themed template's {testcase_builder_link}
        # placeholder. Campaign orchestrator reports cover multiple scripts
        # and never have a single testcase id, so always pass empty.
        testcase_builder_link='',
        steps_section_title=t('campaign.title', ok=successful_scripts, total=total_scripts, skipped=skipped_scripts)
    )


def generate_and_upload_restart_report(
    host_info: Dict,
    device_info: Dict,
    video_url: str,
    analysis_data: Dict,
    processing_time: float,
    timestamp: str = None,
    local_video_path: str = None
) -> Dict[str, str]:
    """
    Generate HTML report for restart video using dedicated restart video template.
    Creates a clean video player interface with AI analysis results.
    
    Args:
        host_info: Dict with host_name
        device_info: Dict with device_name, device_model, device_id
        video_url: URL to the generated restart video (local host URL)
        analysis_data: Dict containing audio, subtitle, and video analysis results
        processing_time: Processing time in seconds
        timestamp: Optional timestamp, will generate if not provided
        local_video_path: Optional local path to video file for R2 upload
        
    Returns:
        Dict with 'report_url', 'report_path', and 'success' keys
    """
    try:
        print(f"[@utils:report_utils:generate_and_upload_restart_report] Starting restart report generation...")
        
        from .cloudflare_utils import upload_restart_report, upload_restart_video
        from .restart_video_template import create_restart_video_template
        from datetime import datetime
        import json
        
        if not timestamp:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Upload video to R2 if local path provided
        r2_video_url = video_url  # Default to original URL
        if local_video_path:
            print(f"[@utils:report_utils:generate_and_upload_restart_report] Uploading video to R2...")
            video_upload_result = upload_restart_video(local_video_path, timestamp)
            if video_upload_result.get('success'):
                r2_video_url = video_upload_result['video_url']
                print(f"[@utils:report_utils:generate_and_upload_restart_report] Video uploaded to R2: {r2_video_url}")
            else:
                print(f"[@utils:report_utils:generate_and_upload_restart_report] Video upload failed: {video_upload_result.get('error')}")
                # Continue with original URL as fallback
        
        # Extract analysis results for template
        audio_analysis = analysis_data.get('audio_analysis', {})
        subtitle_analysis = analysis_data.get('subtitle_analysis', {})
        video_analysis = analysis_data.get('video_analysis', {})
        
        # Prepare template data with R2 video URL
        template_data = {
            'host_name': host_info.get('host_name', 'Unknown Host'),
            'device_name': device_info.get('device_name', 'Unknown Device'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'video_url': r2_video_url,  # Use R2 URL instead of local host URL
            'audio_transcript': audio_analysis.get('combined_transcript', 'No audio transcript available'),
            'subtitle_text': subtitle_analysis.get('extracted_text', 'No subtitles detected'),
            'video_summary': video_analysis.get('video_summary', 'Video analysis pending'),
            'analysis_data_json': json.dumps(analysis_data)  # Remove indent to make it compact for JavaScript
        }
        
        # Generate HTML using dedicated restart video template
        html_template = create_restart_video_template()
        html_content = html_template.format(**template_data)
        
        # Upload report to R2 using timestamp-based structure
        upload_result = upload_restart_report(
            html_content=html_content,
            host_name=host_info.get('host_name', 'unknown'),
            device_id=device_info.get('device_id', 'unknown'),
            timestamp=timestamp
        )
        
        if upload_result['success']:
            report_url = upload_result['report_url']
            report_path = upload_result['report_path']
            print(f"[@cloudflare_utils:upload_restart_report] INFO: Uploaded restart report: {report_path}")
            print(f"[@utils:report_utils:generate_and_upload_restart_report] Report uploaded: {report_url}")
            return {
                'success': True,
                'report_url': report_url,
                'report_path': report_path
            }
        else:
            print(f"[@utils:report_utils:generate_and_upload_restart_report] Upload failed: {upload_result.get('error', 'Unknown error')}")
            return {
                'success': False,
                'report_url': '',
                'report_path': ''
            }
        
    except Exception as e:
        print(f"[@utils:report_utils:generate_and_upload_restart_report] Error: {str(e)}")
        return {
            'success': False,
            'report_url': '',
            'report_path': ''
        }


def format_timestamp(timestamp: str) -> str:
    """Format timestamp for display."""
    try:
        # Convert YYYYMMDDHHMMSS to readable format
        dt = datetime.strptime(timestamp, '%Y%m%d%H%M%S')
        return dt.strftime('%H:%M:%S')
    except:
        return timestamp


def format_execution_date(timestamp: str) -> str:
    """Format execution date for display in DD/MM/YYYY format."""
    try:
        # Convert YYYYMMDDHHMMSS to readable date format
        dt = datetime.strptime(timestamp, '%Y%m%d%H%M%S')
        return dt.strftime('%d/%m/%Y')
    except:
        # Fallback to current date if timestamp parsing fails
        return datetime.now().strftime('%d/%m/%Y')


def format_execution_time(execution_time_ms: int) -> str:
    """Format execution time for display as HH:MM:SS."""
    total_seconds = int(execution_time_ms // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
