"""
Report Step Formatting

Handles the formatting of individual step results for HTML reports.
"""

import os
import json
import html
from typing import Dict, List
from datetime import datetime
from .cloudflare_utils import convert_to_signed_url


def ensure_signed_url(url: str) -> str:
    """Ensure URL is signed if it's an R2 URL or path."""
    if not url:
        return url
    
    # Known R2 path prefixes that should be signed
    R2_PATH_PREFIXES = (
        'script-reports/',
        'navigation/',
        'reference-images/',
        'audio-analysis/',
        'kpi_measurement/',
        'heatmaps/',
        'restart-reports/',
        'script-logs/',
        'alerts/',
    )
    
    # Check for R2 URLs or known R2 paths
    if 'r2.dev' in url or 'r2.cloudflarestorage.com' in url or url.startswith(R2_PATH_PREFIXES):
        return convert_to_signed_url(url)
    return url


def format_timestamp_to_hhmmss_ms(timestamp_str: str) -> str:
    """Format timestamp string to readable format like 21H25m26s.

    Name is historical: milliseconds were dropped from the display on purpose
    (step timing doesn't need ms precision; zap_utils keeps its own ms variant).
    """
    if not timestamp_str:
        return 'N/A'

    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return f"{dt.strftime('%H')}H{dt.strftime('%M')}m{dt.strftime('%S')}s"
    except (ValueError, AttributeError):
        return 'N/A'


def extract_capture_filename_from_url(url_or_path: str) -> str:
    """Extract capture filename from URL or path, stripping signed URL parameters."""
    if not url_or_path:
        return 'unknown'
    
    try:
        # First strip query string parameters (signed URLs have ?X-Amz-... or similar)
        clean_path = url_or_path.split('?')[0]
        
        # Extract filename from URL or path
        filename = os.path.basename(clean_path)
        
        # Handle case where signing params got encoded differently (with underscores)
        # Split at common image extensions to get just the filename
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            if ext in filename.lower():
                # Find the extension and take everything up to it
                ext_idx = filename.lower().find(ext)
                filename = filename[:ext_idx]
                break
        
        return filename
    except:
        return 'unknown'


def format_capture_display_name(capture_filename: str) -> str:
    """Format capture filename consistently across all analysis types."""
    if not capture_filename:
        return 'unknown'
    
    try:
        import re
        # Look for timestamp patterns in filename
        timestamp_match = re.search(r'(\d{8}_\d{6})', capture_filename)  # YYYYMMDD_HHMMSS
        if timestamp_match:
            timestamp_str = timestamp_match.group(1)
            # Convert to readable format: YYYYMMDD_HHMMSS -> HH:MM:SS
            if len(timestamp_str) == 15:  # YYYYMMDD_HHMMSS
                time_part = timestamp_str[9:]  # Get HHMMSS
                formatted_time = f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
                return f"{capture_filename} - {formatted_time}"
        else:
            # Check for numeric capture ID patterns
            # Pattern 1: Pure numbers (like "10149")
            pure_numeric_match = re.search(r'^(\d{4,5})$', capture_filename)
            if pure_numeric_match:
                return f"#{capture_filename}"
            
            # Pattern 2: capture_NNNNN format (like "capture_10096")
            capture_numeric_match = re.search(r'^capture_(\d{4,5})$', capture_filename)
            if capture_numeric_match:
                capture_id = capture_numeric_match.group(1)
                return f"#{capture_id}"
            
            # If no pattern found, just use filename as-is
            return capture_filename
    except Exception:
        # Fallback to just filename if formatting fails
        return capture_filename


def format_screenshot_display_name(screenshot_url_or_path: str) -> str:
    """
    Single function to format screenshot display names consistently.
    Combines extract_capture_filename_from_url + format_capture_display_name.
    
    Args:
        screenshot_url_or_path: URL or path to screenshot
        
    Returns:
        Formatted display name (e.g., "#10149", "screenshot_20250911_213045_21_30_45")
    """
    if not screenshot_url_or_path:
        return 'unknown'
    
    # Extract filename and format in one step
    filename = extract_capture_filename_from_url(screenshot_url_or_path)
    formatted_name = format_capture_display_name(filename)
    
    # Import sanitization function
    from .report_formatting import sanitize_for_json
    return sanitize_for_json(formatted_name)


def create_compact_step_results_section(step_results: List[Dict], screenshots: Dict) -> str:
    """Create HTML for compact step-by-step results.

    Navigation SUB-step grouping: a navigation block (`step_category ==
    'testcase_block'`, message "Navigate to: X") is recorded by the executor
    AFTER its individual edge transitions (`step_category == 'navigation'`,
    "from → to"), because the hops are written DURING navigation and the block
    summary only once it returns. The flat list therefore reads "hop, hop, …,
    parent" with no visual nesting. We re-parent here: each navigation block
    becomes a collapsible PARENT shown FIRST, with its real hops nested and
    decimal-numbered (2.1, 2.2 …) beneath it. Same-node "already at destination"
    dummies are dropped so a no-op navigation renders flat (STEP N, no decimals).
    Every other authored step (action / verification / wait) stays a plain
    top-level row. Display numbers are sequential over top-level rows so the
    report reads STEP 1, STEP 2, STEP 3 regardless of how many hops each took.
    """
    if not step_results:
        return '<p>No steps executed</p>'

    # --- Grouping pass: (parent_step, [hop_steps]) tuples in display order. ---
    groups: List = []
    hop_buffer: List[Dict] = []
    for step in step_results:
        category = step.get('step_category')
        if category == 'navigation':
            hop_buffer.append(step)
            continue
        if category == 'testcase_block' and hop_buffer:
            # Real transitions only — same-node dummies represent "was already
            # there" and carry no useful per-hop detail.
            real_hops = [h for h in hop_buffer if h.get('from_node') != h.get('to_node')]
            groups.append((step, real_hops))
            hop_buffer = []
            continue
        # Any other row: flush orphan hops as standalone rows (defensive — a
        # navigation hop should always be followed by its block), then this row.
        for orphan in hop_buffer:
            groups.append((orphan, []))
        hop_buffer = []
        groups.append((step, []))
    for orphan in hop_buffer:  # trailing hops with no closing block
        groups.append((orphan, []))

    steps_html = ['<div class="step-list">']
    render_index = 0  # unique per RENDERED row → stable toggle / screenshot ids
    for display_number, (parent, children) in enumerate(groups, 1):
        children_html = ''
        if children:
            child_parts = []
            for child_i, child in enumerate(children, 1):
                child_parts.append(
                    format_single_step(
                        child, render_index, screenshots,
                        display_number=f"{display_number}.{child_i}",
                        nested=True,
                    )
                )
                render_index += 1
            children_html = (
                '<div class="step-substeps" style="margin-top: 8px;">' +
                ''.join(child_parts) +
                '</div>'
            )
        steps_html.append(
            format_single_step(
                parent, render_index, screenshots,
                display_number=str(display_number),
                nested_children_html=children_html,
                hop_count=len(children),
            )
        )
        render_index += 1

    steps_html.append('</div>')
    return ''.join(steps_html)


def format_single_step(
    step: Dict,
    step_index: int,
    screenshots: Dict,
    display_number=None,
    nested: bool = False,
    nested_children_html: str = '',
    hop_count: int = 0,
) -> str:
    """Format a single step for display.

    display_number: overrides the shown number (e.g. "2" for a top-level step,
        "2.1" for a nested navigation hop). Falls back to the raw step_number.
    nested: render as an indented navigation SUB-step (lighter accent, left
        margin).
    nested_children_html: pre-rendered hop rows appended inside this step's
        collapsible body (used by a navigation PARENT).
    hop_count: when > 0, show a "· N hops" badge on the parent message.
    """
    step_number = display_number if display_number is not None else step.get('step_number', step_index + 1)
    success = step.get('success', False)
    skipped = step.get('skipped', False)
    is_recovery = step.get('step_category') == 'recovery'
    # A 'testcase_block' step is an ENCAPSULATING step (one QuickTest / TestCase
    # block — e.g. "Navigate to: home"). Its navigation SUB-steps are nested
    # beneath it (see create_compact_step_results_section), so the parent gets a
    # stronger left accent and the children render indented/plain.
    is_block = step.get('step_category') == 'testcase_block'
    message = step.get('message', 'No message')
    execution_time = step.get('execution_time_ms', 0)
    start_time = step.get('start_time', 'N/A')
    end_time = step.get('end_time', 'N/A')

    # Status class + badge text. Order matters: skipped wins over success/failure
    # because a skipped step has success=False but isn't a real failure;
    # recovery wins over plain success/failure for its own visual lane (blue).
    if skipped:
        status_class = 'skipped'
        badge_text = 'SKIP'
    elif is_recovery:
        status_class = 'recovery'
        badge_text = 'PASS' if success else 'FAIL'
    else:
        status_class = 'success' if success else 'failure'
        badge_text = 'PASS' if success else 'FAIL'

    # Format execution time. A genuine 0 (e.g. an "already at destination" step
    # that runs no actions) is a real duration, not missing data — show "0s",
    # never "N/A". execution_time_ms defaults to 0 when absent, so it is never None.
    exec_time_str = format_execution_time(execution_time) if execution_time else "0s"
    timing_header = f"Start: {start_time} End: {end_time} Duration: {exec_time_str}"

    # Format step content
    actions_html = format_step_actions(step)
    verifications_html = format_step_verifications(step)

    # Add verification details (OCR extracted text, match scores) from testcase blocks
    extracted_text = step.get('extracted_text')
    matching_result = step.get('matching_result')
    if extracted_text or matching_result is not None:
        detail_parts = []
        if extracted_text:
            truncated = str(extracted_text)[:300]
            detail_parts.append(f'<div style="margin: 4px 0;"><strong>OCR Extracted Text:</strong> <code style="background: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 3px;">{truncated}</code></div>')
        if matching_result is not None:
            score = float(matching_result)
            color = '#22c55e' if score >= 0.8 else '#f59e0b' if score >= 0.5 else '#ef4444'
            detail_parts.append(f'<div style="margin: 4px 0;"><strong>Match Score:</strong> <span style="color: {color}; font-weight: bold;">{score:.2f}</span></div>')
        verifications_html += '<div style="background: rgba(0,0,0,0.03); border-left: 3px solid #3b82f6; padding: 8px 12px; margin: 8px 0; border-radius: 4px;">' + ''.join(detail_parts) + '</div>'

    # For zap steps the failure reason is shown inside Analysis Results → Zap Detection
    # (with the frames). Don't also float a generic "Error Details" block above it.
    if step.get('step_category') == 'zap_action':
        error_html = ""
    else:
        error_html = format_step_error(step)  # Error shown AFTER verifications
    script_output_html = format_script_output(step)
    analysis_html = format_analysis_results(step)
    screenshot_html = format_step_screenshots(step, step_index)

    # Row styling: encapsulating block (strong indigo accent) vs
    # nested navigation hop (indented, lighter accent).
    item_styles = []
    if is_block and not nested:
        item_styles.extend(['border-left-width: 5px', 'border-left-color: #6366f1'])
    if nested:
        item_styles.extend([
            'margin-left: 28px',
            'border-left-width: 3px',
            'border-left-color: #c7d2fe',
        ])
    item_style_attr = f' style="{"; ".join(item_styles)};"' if item_styles else ''

    # "· N hops" badge on a navigation parent — signals the row expands into
    # nested sub-steps without having to open it first.
    hop_badge = (
        '<span style="display:inline-block;margin-left:8px;padding:1px 6px;'
        'border-radius:3px;background:#eef2ff;color:#6366f1;font-size:11px;'
        f'font-weight:600;vertical-align:middle;">{hop_count} '
        f'{"hop" if hop_count == 1 else "hops"}</span>'
        if hop_count else ''
    )

    # A failed navigation PARENT opens by default so the failing hop isn't hidden
    # inside a collapsed row. `.step-details.expanded` is statically styled
    # (max-height:none) so no JS is needed to start expanded.
    details_class = 'step-details'
    if nested_children_html and not success:
        details_class += ' expanded'

    return f"""
    <div class="step-item {status_class}"{item_style_attr} onclick="toggleStep('step-details-{step_index}')">
        <div class="step-number">{step_number}</div>
        <div class="step-status">
            <span class="step-status-badge {status_class}">
                {badge_text}
            </span>
        </div>
        <div class="step-message">
            {message}{hop_badge}
            <div class="step-timing-inline">{timing_header}</div>
        </div>
    </div>
    <div id="step-details-{step_index}" class="{details_class}">
         <div class="step-details-content">
             <div class="step-info">
                 {actions_html}
                 {verifications_html}
                 {error_html}
                 {script_output_html}
                 {analysis_html}
             </div>
             {screenshot_html}
         </div>
         {nested_children_html}
    </div>
    """


def format_step_error(step: Dict) -> str:
    """Format error details section for a step."""
    error = step.get('error')
    success = step.get('success', False)
    skipped = step.get('skipped', False)

    # Only show error section for failed steps with error details
    if success or not error:
        return ""

    # Skipped steps carry a "Skip Reason" string in `error`, not a failure.
    # Render it with the orange/skipped palette and a neutral header so the
    # report doesn't shout red at non-failures.
    if skipped:
        reason_text = str(error)
        if reason_text.lower().startswith('skipped:'):
            reason_text = reason_text.split(':', 1)[1].strip()
        return (
            '<div><strong>⏭️ Skip Reason:</strong></div>'
            '<div class="skip-reason-container" '
            'style="background-color: var(--skipped-bg); '
            'border-left: 4px solid var(--skipped-color); '
            'padding: 12px; margin: 8px 0; border-radius: 4px; '
            f'color: var(--skipped-text); font-size: 14px;">{reason_text}</div>'
        )

    # Clean and format the error message
    error_html = "<div><strong>❌ Error Details:</strong></div>"
    error_html += '<div class="error-details-container" style="background-color: #fff5f5; border-left: 4px solid #e53e3e; padding: 12px; margin: 8px 0; border-radius: 4px;">'

    # When the failure is one or more verification legs, render a numbered list
    # (numbered to match the Verifications section above) with each leg's message
    # and an inline comparison-report link, instead of the single aggregate
    # error + boxed link below. Falls through to the generic formatting for
    # non-verification failures (action/setup/timeout errors).
    verification_failures_html = _format_verification_failures(step)
    if verification_failures_html:
        error_html += verification_failures_html
        error_html += '</div>'
        return error_html

    # Split error message by common delimiters to make it more readable
    error_text = str(error)

    # Handle specific error patterns for better formatting
    if "Actions failed:" in error_text:
        # Parse action failure details
        parts = error_text.split("Actions failed:")
        if len(parts) > 1:
            main_error = parts[0].strip()
            failed_actions = parts[1].strip()
            
            if main_error:
                error_html += f'<div class="error-summary" style="font-weight: bold; color: #e53e3e; margin-bottom: 8px;">{main_error}</div>'
            
            error_html += f'<div class="failed-actions" style="color: #a0a0a0; font-size: 14px;">Failed Actions: <span style="color: #e53e3e; font-weight: bold;">{failed_actions}</span></div>'
    
    elif "Detailed selector attempts:" in error_text:
        # Handle Playwright detailed selector failures
        parts = error_text.split("Detailed selector attempts:")
        if len(parts) > 1:
            main_error = parts[0].strip()
            selector_details = parts[1].strip()
            
            error_html += f'<div class="error-summary" style="font-weight: bold; color: #e53e3e; margin-bottom: 8px;">🔍 {main_error}</div>'
            
            # Format selector attempts in a collapsible section
            error_html += '<div class="selector-attempts" style="margin-top: 12px;">'
            error_html += '<div style="font-weight: bold; color: #666; margin-bottom: 6px; cursor: pointer;" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === \'none\' ? \'block\' : \'none\'">📋 View All Selector Attempts ▼</div>'
            error_html += '<div style="display: none; background-color: #f8f8f8; padding: 8px; border-radius: 4px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto;">'
            
            # Format each selector attempt
            attempt_lines = selector_details.split('\n')
            for line in attempt_lines:
                if line.strip():
                    # Color-code the attempts
                    if "failed" in line.lower():
                        error_html += f'<div style="color: #e53e3e; margin: 2px 0;">{line.strip()}</div>'
                    else:
                        error_html += f'<div style="color: #666; margin: 2px 0;">{line.strip()}</div>'
            
            error_html += '</div></div>'
        else:
            # Fallback if parsing fails
            error_html += f'<div style="color: #e53e3e; font-size: 14px;">{error_text}</div>'
    
    elif "Timeout" in error_text or "timeout" in error_text:
        # Format timeout errors with better structure
        error_html += f'<div class="timeout-error" style="color: #e53e3e;">'
        error_html += f'<div style="font-weight: bold;">⏱️ Timeout Error</div>'
        error_html += f'<div style="margin-top: 4px; font-size: 14px;">{error_text}</div>'
        error_html += f'</div>'
        
    elif "element not found" in error_text.lower():
        # Format element not found errors
        error_html += f'<div class="element-error" style="color: #e53e3e;">'
        error_html += f'<div style="font-weight: bold;">🔍 Element Not Found</div>'
        error_html += f'<div style="margin-top: 4px; font-size: 14px;">{error_text}</div>'
        error_html += f'</div>'
        
    else:
        # Generic error formatting with better line break handling
        error_html += f'<div class="generic-error" style="color: #e53e3e; font-size: 14px; line-height: 1.4;">'
        
        # Handle multiline errors better
        if '\n' in error_text:
            lines = error_text.split('\n')
            for line in lines:
                if line.strip():
                    # Preserve indentation for structured error messages
                    formatted_line = line.replace('  ', '&nbsp;&nbsp;').replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
                    error_html += f'<div style="margin: 2px 0;">{formatted_line}</div>'
        else:
            # Single line error
            error_html += error_text
        
        error_html += f'</div>'
    
    # Single debug report link for non-verification failures (verification
    # failures are rendered with inline per-leg links above and return early).
    # Check both direct step field and error_details (different code paths may use either).
    debug_report_url = step.get('debug_report_url') or step.get('error_details', {}).get('debug_report_url')
    if debug_report_url:
        error_html += '<div class="debug-report-link" style="margin-top: 12px; padding: 8px; background-color: #e8f4fd; border-left: 4px solid #3182ce; border-radius: 4px;">'
        error_html += f'<a href="{debug_report_url}" target="_blank" style="color: #3182ce; text-decoration: none; font-size: 14px; display: inline-flex; align-items: center; gap: 4px;">'
        error_html += '📊 View Detailed Comparison Report'
        error_html += '<span style="font-size: 12px;">↗</span>'
        error_html += '</a>'
        error_html += '</div>'

    error_html += '</div>'
    return error_html


def _format_verification_failures(step: Dict) -> str:
    """Numbered list of failed verification legs for the Error Details box.

    Each line is `N. <message> - View comparison report`, where N is the leg's
    1-based position in verification_results (so it matches the numbering in the
    Verifications section above) and the report link sits inline on the same
    line. Returns '' when no verification leg failed, so the caller falls back to
    the generic error formatting for action/setup/timeout failures.
    """
    results = step.get('verification_results', [])
    failures = [
        (idx, r) for idx, r in enumerate(results, 1)
        if not r.get('success', False) and not r.get('skipped')
    ]
    if not failures:
        return ''

    items_html = ''
    for idx, r in failures:
        msg = r.get('message') or r.get('error') or 'Verification failed'
        url = r.get('debug_report_url')
        link_html = ''
        if url:
            link_html = (
                f' &nbsp;-&nbsp; <a href="{url}" target="_blank" '
                'style="color:#3182ce;text-decoration:none;white-space:nowrap;">'
                '📊 View comparison report <span style="font-size:12px;">↗</span></a>'
            )
        items_html += (
            '<div class="verification-error-item" '
            'style="color:#e53e3e;font-size:14px;line-height:1.6;margin:3px 0;">'
            f'<span style="font-weight:bold;">{idx}.</span> {msg}{link_html}</div>'
        )
    return items_html


def _action_result_detail(result: Dict, command: str) -> str:
    """The part of an action's result message that adds something to `command(params)`.

    action_executor builds `message` as the command name plus, after " - ", whatever the
    controller reported about what it did. Only that tail is new information; the rest (the
    command itself, an iteration count) is already on the line, so nothing else is shown.
    """
    message = (result.get('message') or '').strip()
    separator = f'{command} - '
    return message[len(separator):].strip() if message.startswith(separator) else ''


def format_step_actions(step: Dict) -> str:
    """Format actions section for a step with execution status."""
    # Check if this is an "already at destination" step
    if step.get('already_at_destination'):
        return '''<div class="already-at-destination" style="background-color: #f0f9ff; border-left: 4px solid #3b82f6; padding: 12px; margin: 8px 0; border-radius: 4px;">
            <div style="font-weight: bold; color: #1e40af; margin-bottom: 4px;">✓ Already at Destination</div>
            <div style="color: #64748b; font-size: 14px;">No navigation needed - device was already verified at the target node.</div>
        </div>'''
    
    actions = step.get('actions', [])
    retry_actions = step.get('retry_actions', [])
    failure_actions = step.get('failure_actions', [])
    action_results = step.get('action_results', [])
    
    actions_html = ""
    
    # Determine which actions were executed based on action_results
    executed_categories = set()
    if action_results:
        for result in action_results:
            executed_categories.add(result.get('action_category', 'main'))
    
    # Regular actions
    if actions:
        actions_html = "<div><strong>Actions:</strong></div>"
        for action_index, action in enumerate(actions, 1):
            command = action.get('command', 'unknown')
            params = action.get('params', {})
            
            # Format params as key=value pairs
            params_str = ", ".join([f"{k}='{v}'" for k, v in params.items()]) if params else ""
            
            action_line = f"{action_index}. {command}({params_str})" if params_str else f"{action_index}. {command}"
            
            # Show result if available
            if action_results and action_index <= len([r for r in action_results if r.get('action_category') == 'main']):
                main_results = [r for r in action_results if r.get('action_category') == 'main']
                if action_index - 1 < len(main_results):
                    result = main_results[action_index - 1]
                    success = result.get('success', False)
                    status_badge = f'<span class="action-result-badge {"success" if success else "failure"}">{"✓" if success else "✗"}</span>'
                    action_line += f" {status_badge}"
                    # A controller that reported what it actually did says so here. It matters
                    # for selector-based actions: click_element(element_id=' seconds') is a
                    # search term, not an id, and only the detail tells you which node it hit.
                    detail = _action_result_detail(result, command)
                    if detail:
                        action_line += (
                            f' <span class="action-result-detail" '
                            f'style="color:#a0a0a0;">{html.escape(detail)}</span>'
                        )
            
            actions_html += f'<div class="action-item">{action_line}</div>'
    
    # Retry actions
    if retry_actions:
        was_executed = 'retry' in executed_categories
        status_label = 'EXECUTED' if was_executed else 'AVAILABLE'
        status_class = 'executed' if was_executed else 'available'
        
        actions_html += f"<div><strong>Retry Actions:</strong> <span class='retry-status {status_class}'>{status_label}</span></div>"
        for retry_index, retry_action in enumerate(retry_actions, 1):
            command = retry_action.get('command', 'unknown')
            params = retry_action.get('params', {})
            
            # Format params as key=value pairs
            params_str = ", ".join([f"{k}='{v}'" for k, v in params.items()]) if params else ""
            
            retry_line = f"{retry_index}. {command}({params_str})" if params_str else f"{retry_index}. {command}"
            
            # Show result if retry was executed
            if was_executed and action_results:
                retry_results = [r for r in action_results if r.get('action_category') == 'retry']
                if retry_index - 1 < len(retry_results):
                    result = retry_results[retry_index - 1]
                    success = result.get('success', False)
                    status_badge = f'<span class="action-result-badge {"success" if success else "failure"}">{"✓" if success else "✗"}</span>'
                    retry_line += f" {status_badge}"
            
            actions_html += f'<div class="retry-action-item {status_class}">{retry_line}</div>'
    
    # Failure actions
    if failure_actions:
        was_executed = 'failure' in executed_categories
        status_label = 'EXECUTED' if was_executed else 'AVAILABLE'
        status_class = 'executed' if was_executed else 'available'
        
        actions_html += f"<div><strong>Failure Actions:</strong> <span class='failure-status {status_class}'>{status_label}</span></div>"
        for failure_index, failure_action in enumerate(failure_actions, 1):
            command = failure_action.get('command', 'unknown')
            params = failure_action.get('params', {})
            
            # Format params as key=value pairs
            params_str = ", ".join([f"{k}='{v}'" for k, v in params.items()]) if params else ""
            
            failure_line = f"{failure_index}. {command}({params_str})" if params_str else f"{failure_index}. {command}"
            
            # Show result if failure action was executed
            if was_executed and action_results:
                failure_results = [r for r in action_results if r.get('action_category') == 'failure']
                if failure_index - 1 < len(failure_results):
                    result = failure_results[failure_index - 1]
                    success = result.get('success', False)
                    status_badge = f'<span class="action-result-badge {"success" if success else "failure"}">{"✓" if success else "✗"}</span>'
                    failure_line += f" {status_badge}"
            
            actions_html += f'<div class="failure-action-item {status_class}">{failure_line}</div>'
    
    return actions_html


def format_step_verifications(step: Dict) -> str:
    """Format verifications section for a step."""
    verifications = step.get('verifications', [])
    verification_results = step.get('verification_results', [])
    
    if not verifications and not verification_results:
        return ""
    
    verifications_html = ""
    
    if verifications:
        verifications_html = "<div><strong>Verifications:</strong></div>"
        for verification_index, verification in enumerate(verifications, 1):
            # Script verifications include 'success' inline (combined definition + result)
            if isinstance(verification, dict) and 'success' in verification:
                v_label = verification.get('label', verification.get('command', f'Verification {verification_index}'))
                v_details = verification.get('details', '')
                v_success = verification.get('success', False)
                badge_text = "PASS" if v_success else "FAIL"
                badge_class = "success" if v_success else "failure"
                verification_line = f'{verification_index}. {v_label}: {v_details}'
                verification_result_html = f' <span class="verification-result-badge {badge_class}">{badge_text}</span>'
                verifications_html += f'<div class="verification-item">{verification_line}{verification_result_html}</div>'
            else:
                verification_line = format_verification_item(verification, verification_index)

                # Add verification result if available
                verification_result_html = ""
                if verification_index <= len(verification_results):
                    result = verification_results[verification_index-1]
                    verification_result_html = format_verification_result(result, step)

                verifications_html += f'<div class="verification-item">{verification_line}{verification_result_html}</div>'
    
    elif verification_results:
        # Show verification results even if verification definitions are missing
        verifications_html = "<div><strong>Verification Results:</strong></div>"
        for verification_index, result in enumerate(verification_results, 1):
            result_success = result.get('success', False)
            result_message = result.get('message', 'Verification completed')
            verification_type = result.get('verification_type', 'unknown')
            result_badge = f'<span class="verification-result-badge {"success" if result_success else "failure"}">{"PASS" if result_success else "FAIL"}</span>'
            
            verification_line = f"{verification_index}. {verification_type}: {result_message}"
            verification_result_html = f" {result_badge}"
            
            if not result_success and result.get('error'):
                verification_result_html += f" <span class='verification-error'>({result['error']})</span>"
            
            verification_result_html += format_image_verification_extras(result, step)
            
            verifications_html += f'<div class="verification-item">{verification_line}{verification_result_html}</div>'
    
    return verifications_html


def format_verification_item(verification: Dict, verification_index: int) -> str:
    """Format a single verification item."""
    if isinstance(verification, dict):
        command = verification.get('command', verification.get('type', verification.get('verification_type', 'unknown')))
        params = verification.get('params', verification.get('parameters', {}))
        label = verification.get('label', '')

        # Format params. `wait_time` is the action settle delay (lives on
        # actions, not verifications, but historically leaks here) and stays
        # hidden. `timeout` is the waitFor* polling budget — for image/text
        # waitFor* verifications this is the single most important number
        # when a failure is a "fired too early" timing issue, so we surface
        # it inline beside the score badge instead of stripping it.
        filtered_params = {k: v for k, v in params.items() if k != 'wait_time'}
        params_str = ", ".join([f"{k}='{v}'" for k, v in filtered_params.items()]) if filtered_params else ""
        
        # Create verification line with label if available
        if label:
            verification_line = f"{verification_index}. {label}: {command}({params_str})" if params_str else f"{verification_index}. {label}: {command}"
        else:
            verification_line = f"{verification_index}. {command}({params_str})" if params_str else f"{verification_index}. {command}"
    else:
        verification_line = f"{verification_index}. {str(verification)}"
    
    return verification_line


def format_verification_result(result: Dict, step: Dict) -> str:
    """Format verification result with badges and extras."""
    result_success = result.get('success', False)
    verification_type = result.get('verification_type')

    # Use tick marks like actions (✓/✗) with percentage for both image AND text
    # verifications. Text now uses the same 0.0-1.0 matching_result scale
    # (1.0 = exact substring after normalization, partial = difflib score), so
    # "✓ 100%" / "✗ 87%" reads identically in both types.
    badge_text = "✓" if result_success else "✗"
    if verification_type in ('image', 'text'):
        details = result.get('details', {})
        match_score = (
            details.get('match_score')
            or details.get('matching_result')
            # Fallback to top-level if executor flattened it (image route + text
            # route both expose matchingResult at the top of their responses).
            or result.get('matching_result')
            or result.get('matchingResult')
        )
        if match_score is not None:
            badge_text += f" <strong>{match_score*100:.0f}%</strong>"

    result_badge = f'<span class="verification-result-badge {"success" if result_success else "failure"}">{badge_text}</span>'
    verification_result_html = f" {result_badge}"

    if not result_success and result.get('error'):
        verification_result_html += f" <span class='verification-error'>({result['error']})</span>"

    # Text extras: render threshold + extracted snippet inline next to the
    # badge so the OCR outcome (what Tesseract actually read, against what
    # threshold) is visible at a glance without opening the failure report.
    if verification_type == 'text':
        verification_result_html += format_text_verification_extras(result)

    # Add image verification extras (thumbnails only now)
    verification_result_html += format_image_verification_extras(result, step)

    return verification_result_html


def format_text_verification_extras(result: Dict) -> str:
    """Inline OCR context for text verifications: required threshold + extracted snippet.

    Renders as a small dim parenthetical next to the score badge. Truncates
    extracted text to keep the report line scannable; the full text is still
    in the failure-report HTML for failed verifications.
    """
    if result.get('verification_type') != 'text':
        return ""

    details = result.get('details', {}) or {}

    # Threshold — try nested details first, then top-level. The executor flattens
    # the controller's user_threshold to the top-level key `threshold`
    # (verification_executor.py builds flattened_result with 'threshold': user_threshold),
    # so that key MUST be in the chain — otherwise "required X%" silently drops
    # whenever the nested details dict isn't carried (the score badge + extracted
    # text already survive via their correctly-named top-level fallbacks).
    threshold = (
        details.get('user_threshold')
        or details.get('threshold')
        or result.get('threshold')
        or result.get('user_threshold')
        or result.get('userThreshold')
    )

    # Extracted text — what OCR actually read (camelCase from the controller).
    extracted = (
        details.get('extractedText')
        or details.get('extracted_text')
        or result.get('extractedText')
    )

    parts = []
    if threshold is not None:
        try:
            parts.append(f"required {float(threshold)*100:.0f}%")
        except (TypeError, ValueError):
            pass
    if extracted:
        # OCR can return arbitrary chars (incl. HTML-special) and very long
        # text — escape + truncate so the report row stays one line.
        import html
        snippet = extracted if len(extracted) <= 60 else extracted[:57] + '...'
        parts.append(f'read &ldquo;{html.escape(snippet)}&rdquo;')

    if not parts:
        return ""
    return f' <span class="verification-meta">({" · ".join(parts)})</span>'


def format_image_verification_extras(result: Dict, step: Dict) -> str:
    """Format thumbnails for image verifications."""
    if result.get('verification_type') != 'image':
        return ""
    
    extras_html = ""
    details = result.get('details', {})
    
    # Add small thumbnails
    source_image = None
    reference_image = None
    overlay_image = None
    
    # Find source and overlay images from verification_images
    # First try to get from individual verification result, then fall back to step level
    verification_images = result.get('verification_images', []) or step.get('verification_images', [])
    for img_path in verification_images:
        if img_path:
            filename = os.path.basename(img_path).lower()
            if 'source' in filename:
                source_image = img_path
            elif 'overlay' in filename or 'result_overlay' in filename:
                overlay_image = img_path
    
    # Get reference image from details
    reference_image = details.get('reference_image_url')
    
    # Debug logging to help diagnose missing images
    print(f"[@report_step_formatter:format_image_verification_extras] Debug verification images:")
    print(f"  verification_images array: {verification_images}")
    print(f"  source_image found: {source_image}")
    print(f"  overlay_image found: {overlay_image}")
    print(f"  reference_image from details: {reference_image}")
    
    # Create small thumbnails if we have images
    if source_image or reference_image or overlay_image:
        from .report_formatting import create_verification_image_modal_data
        modal_data = create_verification_image_modal_data(source_image, reference_image, overlay_image)
        
        thumbnails_html = "<div class='verification-thumbnails' style='margin-top: 4px; display: flex; gap: 10px;'>"
        
        # Order: Source → Reference → Overlay (logical flow)
        if source_image:
            signed_source = ensure_signed_url(source_image)
            thumbnails_html += f"""
            <div style='text-align: center;'>
                <div style='font-size: 11px; color: #666; margin-bottom: 2px;'>Source</div>
                <img src='{signed_source}' style='width: 60px; height: 40px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                     onclick='openVerificationImageModal({modal_data})' title='Click to compare all images'>
            </div>
            """
        
        if reference_image:
            signed_reference = ensure_signed_url(reference_image)
            thumbnails_html += f"""
            <div style='text-align: center;'>
                <div style='font-size: 11px; color: #666; margin-bottom: 2px;'>Reference</div>
                <img src='{signed_reference}' style='width: 60px; height: 40px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                     onclick='openVerificationImageModal({modal_data})' title='Click to compare all images'>
            </div>
            """
        
        if overlay_image:
            signed_overlay = ensure_signed_url(overlay_image)
            thumbnails_html += f"""
            <div style='text-align: center;'>
                <div style='font-size: 11px; color: #666; margin-bottom: 2px;'>Overlay</div>
                <img src='{signed_overlay}' style='width: 60px; height: 40px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                     onclick='openVerificationImageModal({modal_data})' title='Click to compare all images'>
            </div>
            """
        
        thumbnails_html += "</div>"
        extras_html += thumbnails_html
    
    return extras_html


def format_script_output(step: Dict) -> str:
    """Format script output section for a step."""
    script_output = step.get('script_output', {})
    if not script_output or not (script_output.get('stdout') or script_output.get('stderr')):
        return ""
    
    script_output_html = "<div><strong>Script Output:</strong></div>"
    
    if script_output.get('stdout'):
        script_output_html += f'<div class="script-output stdout"><strong>Output:</strong><pre>{script_output["stdout"]}</pre></div>'
    
    if script_output.get('stderr'):
        script_output_html += f'<div class="script-output stderr"><strong>Error:</strong><pre>{script_output["stderr"]}</pre></div>'
    
    exit_code = script_output.get('exit_code', 0)
    script_output_html += f'<div class="script-output exit-code"><strong>Exit Code:</strong> {exit_code}</div>'
    
    return script_output_html


def format_analysis_results(step: Dict) -> str:
    """Format analysis results section for a step."""
    motion_analysis = step.get('motion_analysis', {})
    subtitle_analysis = step.get('subtitle_analysis', {})
    audio_analysis = step.get('audio_analysis', {})
    audio_menu_analysis = step.get('audio_menu_analysis', {})
    zapping_analysis = step.get('zapping_analysis', {})
    
    if not (motion_analysis or subtitle_analysis or audio_analysis or audio_menu_analysis or zapping_analysis):
        return ""

    import json
    sep = '<div style="margin: 8px 0; border-top: 1px solid #555; opacity: 0.6;"></div>'

    # =====================================================================
    # ZAP DETECTION — shown FIRST (it's the primary signal). If the zap
    # wasn't detected, the failure reason is shown HERE (inside Analysis
    # Results), not as a floating "Error Details" block above. Motion is
    # only computed/shown when the zap was detected (see ZapExecutor), so a
    # "Zap NOT DETECTED" step won't contradict itself with a Motion line.
    # =====================================================================
    zapping_html = ""
    if zapping_analysis and zapping_analysis.get('success') is not None:
        zapping_detected = zapping_analysis.get('zapping_detected', False)
        zapping_status = "✅ DETECTED" if zapping_detected else "❌ NOT DETECTED"
        zapping_html += f'<div class="analysis-item zapping"><strong>Zap Detection:</strong> {zapping_status}</div>'

        # Link to the standalone per-event zap measurement report (R2/MinIO HTML) when the
        # script attached its URL. Gives the step the same "open the full report" affordance
        # as the KPI Measurement link.
        _zap_report_url = zapping_analysis.get('report_url')
        if _zap_report_url:
            zapping_html += (
                '<div class="analysis-detail" style="margin: 2px 0 6px;">'
                f'<a href="{_zap_report_url}" target="_blank" rel="noopener" '
                'style="color:#3182ce;text-decoration:none;font-weight:600;">📺 View Zap Report ↗</a></div>'
            )

        if zapping_detected:
            blackscreen_duration = zapping_analysis.get('blackscreen_duration', 0)
            blackscreen_duration_ms = zapping_analysis.get('blackscreen_duration_ms', 0)
            total_zap_duration_ms = zapping_analysis.get('total_zap_duration_ms', 0)
            audio_silence_duration = zapping_analysis.get('audio_silence_duration', 0)
            zapping_duration = zapping_analysis.get('zapping_duration', 0)  # Legacy field
            channel_info = zapping_analysis.get('channel_info', {})
            analyzed_images = zapping_analysis.get('analyzed_images', 0)

            # Label the transition by its real type (freeze vs blackscreen). Many STBs zap via a
            # frozen frame, never a black frame, so "Blackscreen" would be wrong.
            transition_type = zapping_analysis.get('transition_type', 'blackscreen')
            t_label = 'Freeze' if transition_type == 'freeze' else 'Blackscreen'

            zap_details = []
            if total_zap_duration_ms > 0:
                zap_details.append(f"Total Zap Duration: {total_zap_duration_ms/1000:.2f}s")
            elif zapping_duration > 0:
                zap_details.append(f"Total Zap Duration: {zapping_duration:.1f}s")
            if blackscreen_duration_ms > 0:
                zap_details.append(f"{t_label} Duration: {blackscreen_duration_ms/1000:.2f}s")
            elif blackscreen_duration > 0:
                zap_details.append(f"{t_label} Duration: {blackscreen_duration:.1f}s")
            if audio_silence_duration > 0:
                zap_details.append(f"Audio Silence: {audio_silence_duration:.2f}s")
            if analyzed_images > 0:
                zap_details.append(f"Images Analyzed: {analyzed_images}")
            if zap_details:
                zapping_html += f'<div class="analysis-detail" style="margin-bottom: 6px;">{" | ".join(zap_details)}</div>'

            if channel_info.get('channel_name'):
                channel_display = channel_info['channel_name']
                if channel_info.get('channel_number'):
                    channel_display += f" ({channel_info['channel_number']})"
                if channel_info.get('program_name'):
                    channel_display += f" - {channel_info['program_name']}"
                channel_info_line = f"Channel info: {channel_display}"
                if channel_info.get('start_time') and channel_info.get('end_time'):
                    channel_info_line += f" Program Time - {channel_info['start_time']}-{channel_info['end_time']}"
                zapping_html += f'<div class="analysis-detail" style="word-wrap: break-word; max-width: none; margin-bottom: 8px;">{channel_info_line}</div>'

            # Transition images used for the zap decision (before / blackscreen / after)
            before_blackscreen = ensure_signed_url(zapping_analysis.get('first_image'))
            blackscreen_start = ensure_signed_url(zapping_analysis.get('blackscreen_start_image'))
            blackscreen_end = ensure_signed_url(zapping_analysis.get('blackscreen_end_image'))
            first_content = ensure_signed_url(zapping_analysis.get('first_content_after_blackscreen'))

            if before_blackscreen or blackscreen_start or blackscreen_end or first_content:
                images = []
                if before_blackscreen:
                    images.append({'url': before_blackscreen, 'label': 'Before Transition'})
                if blackscreen_start:
                    images.append({'url': blackscreen_start, 'label': 'First Transition'})
                if blackscreen_end:
                    images.append({'url': blackscreen_end, 'label': 'Last Transition'})
                if first_content:
                    images.append({'url': first_content, 'label': 'First Content After'})
                if images:
                    modal_data = {'title': 'Complete Zapping Sequence Analysis', 'images': images}
                    modal_data_json = json.dumps(modal_data, ensure_ascii=True).replace('"', '&quot;').replace("'", "&#x27;")
                    zapping_html += "<div class='zapping-sequence-thumbnails' style='margin-top: 4px; display: flex; gap: 8px;'>"
                    for image in images:
                        zapping_html += f"""
                        <div style='text-align: center;'>
                            <img src='{image['url']}' style='width: 120px; height: 80px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;'
                                 onclick='openVerificationImageModal({modal_data_json})' title='Click to view complete zapping sequence'>
                        </div>
                        """
                    zapping_html += "</div>"
        else:
            # NOT DETECTED — show the reason here (red), and any analyzed images / mosaic.
            reason = zapping_analysis.get('error') or zapping_analysis.get('message') or 'No channel change detected'
            zapping_html += f'<div class="analysis-detail" style="color: #f87171;">Reason: {reason}</div>'
            analyzed_images = zapping_analysis.get('analyzed_images', 0)
            if analyzed_images > 0:
                zapping_html += f'<div class="analysis-detail">Images Analyzed: {analyzed_images}</div>'
            failure_mosaic_path = ensure_signed_url(zapping_analysis.get('failure_mosaic_path'))
            analysis_log = zapping_analysis.get('analysis_log', [])
            if failure_mosaic_path:
                modal_data = {
                    'title': f'Zapping Detection Failure Analysis - {zapping_analysis.get("detection_method", "Unknown").title()} Method',
                    'images': [{'url': failure_mosaic_path, 'label': f'Analysis Mosaic ({zapping_analysis.get("mosaic_images_count", 0)} images)'}],
                    'analysis_log': analysis_log
                }
                modal_data_json = json.dumps(modal_data, ensure_ascii=True).replace('"', '&quot;').replace("'", "&#x27;")
                zapping_html += "<div class='zapping-failure-mosaic' style='margin-top: 4px;'>"
                zapping_html += f"""
                <div style='text-align: center;'>
                    <div style='font-size: 11px; color: #666; margin-bottom: 2px;'>Failure Analysis Mosaic</div>
                    <img src='{failure_mosaic_path}' style='width: 120px; height: 80px; object-fit: contain; border: 2px solid #e53e3e; border-radius: 4px; cursor: pointer;'
                         onclick='openZappingAnalysisModal({modal_data_json})' title='Click to view detailed failure analysis'>
                </div>
                """
                zapping_html += "</div>"

    # Assemble Analysis Results — Zap Detection first.
    analysis_html = "<div><strong>Analysis Results:</strong></div>"
    if zapping_html:
        analysis_html += zapping_html

    # =====================================================================
    # MOTION DETECTION — destination playing after zap (with the frames used).
    # Only present when the zap was detected (ZapExecutor skips motion otherwise),
    # so a "Zap NOT DETECTED" step won't show a contradictory motion line.
    # =====================================================================
    if motion_analysis and motion_analysis.get('success') is not None:
        if zapping_html:
            analysis_html += sep
        motion_success = motion_analysis.get('success', False)
        motion_status = "✅ DETECTED" if motion_success else "❌ NOT DETECTED"
        # When the real (2-frame) detector ran, show the measured change AS A COMPARISON
        # against the threshold it was tested on, plus the region used. The explicit
        # "1.9% < 5% threshold" makes a NOT DETECTED verdict self-explanatory (two
        # close-but-different frames just below the bar), and "15.3% ≥ 5%" the converse.
        real_change = motion_analysis.get('real_motion_change')
        real_threshold = motion_analysis.get('real_motion_threshold')
        real_area = motion_analysis.get('real_motion_area')
        meta = ""
        if real_change is not None:
            region_txt = "custom region" if real_area else "centre region"
            if real_threshold is not None:
                # Operator from the numbers themselves so the text is always internally
                # consistent (never "1.9% ≥ 5%"), independent of which flag set the badge.
                try:
                    op = "≥" if float(real_change) >= float(real_threshold) else "<"
                except (TypeError, ValueError):
                    op = "vs"
                change_txt = f"{real_change}% {op} {real_threshold}% threshold"
            else:
                change_txt = f"{real_change}% change"
            meta = f' <span style="color:#888; font-size: 12px;">({change_txt} · {region_txt})</span>'
        analysis_html += f'<div class="analysis-item motion"><strong>Motion Detection:</strong> {motion_status}{meta}</div>'

        # Motion analysis thumbnails — the exact frames compared (or recent JSON captures)
        motion_images = motion_analysis.get('motion_analysis_images', [])
        if motion_images:
            import json
            
            # Convert motion images to modal format
            images = []
            for motion_img in motion_images:
                image_url = ensure_signed_url(motion_img.get('path', ''))  # Sign R2 URLs

                # Real-motion crops carry a 'caption' (the frames actually compared); use it
                # directly instead of the freeze/blackscreen JSON-flag label.
                if motion_img.get('caption'):
                    images.append({'url': image_url, 'label': motion_img['caption']})
                    continue

                # Extract analysis info for label with improved formatting
                analysis_data = motion_img.get('analysis_data', {})

                # Format capture name and timestamp
                filename = motion_img.get('filename', 'unknown')
                timestamp_str = motion_img.get('timestamp', '')

                # Extract readable timestamp
                formatted_time = format_timestamp_to_hhmmss_ms(timestamp_str)

                # First line: capture name - time
                first_line = f"{filename} - {formatted_time}"

                # Second line: status indicators with proper Yes/No format and color coding
                freeze_val = analysis_data.get('freeze', False)
                blackscreen_val = analysis_data.get('blackscreen', False)
                audio_val = analysis_data.get('audio', True)
                
                freeze_status = "Yes" if freeze_val else "No"
                blackscreen_status = "Yes" if blackscreen_val else "No"
                audio_status = "Yes" if audio_val else "No"

                # Individual color logic for each status
                # Freeze/Blackscreen: "No" is good (green), "Yes" is bad (red)
                # Audio: "Yes" is good (green, audio present), "No" is bad (red, no audio)
                freeze_color = "#44ff44" if not freeze_val else "#ff4444"  # Green for no freeze, red for freeze
                blackscreen_color = "#44ff44" if not blackscreen_val else "#ff4444"  # Green for no blackscreen, red for blackscreen
                audio_color = "#44ff44" if audio_val else "#ff4444"  # Green for audio present, red for no audio

                # Create HTML-formatted second line with individual colors
                second_line_html = f'<span style="color: {freeze_color};">Freeze:{freeze_status}</span>, <span style="color: {blackscreen_color};">Blackscreen:{blackscreen_status}</span>, <span style="color: {audio_color};">Audio:{audio_status}</span>'
                
                # Use actual newline character and HTML formatting
                label = f"{first_line}<br>{second_line_html}"
                images.append({'url': image_url, 'label': label})
            
            modal_data = {
                'title': 'Motion Analysis - frames compared',
                'images': images
            }
            # Encode modal data as JSON for JavaScript with proper escaping
            json_str = json.dumps(modal_data, ensure_ascii=True)
            modal_data_json = json_str.replace('"', '&quot;').replace("'", "&#x27;")
            
            thumbnails_html = "<div class='motion-analysis-thumbnails' style='margin-top: 4px; display: flex; gap: 8px;'>"
            
            for i, image in enumerate(images):
                # Show first 3 images as thumbnails
                if i < 3:
                    # Extract capture name and time from label (first line before <br> or newline)
                    label_first_line = image['label'].split('<br>')[0] if '<br>' in image['label'] else image['label'].split('\n')[0] if '\n' in image['label'] else image['label']
                    thumbnails_html += f"""
                    <div style='text-align: center;'>
                        <img src='{image['url']}' style='width: 120px; height: 80px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                             onclick='openVerificationImageModal({modal_data_json})' title='Click to view motion analysis images'>
                    </div>
                    """
            
            thumbnails_html += "</div>"
            analysis_html += thumbnails_html
    
    # Subtitle Analysis Results
    if subtitle_analysis and subtitle_analysis.get('success') is not None:
        analysis_html += '<div style="margin: 8px 0; border-top: 1px solid #555; opacity: 0.6;"></div>'
        

        subtitle_detected = subtitle_analysis.get('subtitles_detected', False)
        subtitle_status = "✅ DETECTED" if subtitle_detected else "❌ NOT DETECTED"
        analysis_html += f'<div class="analysis-item subtitle"><strong>Subtitle Detection:</strong> {subtitle_status}</div>'
        
        if subtitle_detected:
            if subtitle_analysis.get('detected_language'):
                analysis_html += f'<div class="analysis-detail">Language: {subtitle_analysis.get("detected_language")}</div>'
            if subtitle_analysis.get('extracted_text'):
                text_preview = subtitle_analysis.get('extracted_text')[:100] + ('...' if len(subtitle_analysis.get('extracted_text', '')) > 100 else '')
                analysis_html += f'<div class="analysis-detail">Text: {text_preview}</div>'
        elif subtitle_analysis.get('message'):
            analysis_html += f'<div class="analysis-detail">Details: {subtitle_analysis.get("message")}</div>'
            
        # Show analyzed screenshot thumbnail for debugging (with modal like zapping images)
        analyzed_screenshot = ensure_signed_url(subtitle_analysis.get('analyzed_screenshot'))
        if analyzed_screenshot:
            import json
            # Create single image modal data
            modal_data = {
                'title': 'Subtitle Analysis Screenshot',
                'images': [{'url': analyzed_screenshot, 'label': 'Analyzed for Subtitles'}]
            }
            # Encode modal data as JSON for JavaScript with proper escaping
            json_str = json.dumps(modal_data, ensure_ascii=True)
            modal_data_json = json_str.replace('"', '&quot;').replace("'", "&#x27;")
            
            # Use single function to format screenshot display name
            formatted_display = format_screenshot_display_name(analyzed_screenshot)
            
            analysis_html += f"""
            <div class='subtitle-screenshot' style='margin-top: 4px;'>
                <div>
                    <img src='{analyzed_screenshot}' style='width: 120px; height: 80px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                         onclick='openVerificationImageModal({modal_data_json})' title='Click to view subtitle analysis screenshot'>
                </div>
            </div>
            """
    
    # Audio Speech Analysis Results
    if audio_analysis and audio_analysis.get('success') is not None:
        analysis_html += '<div style="margin: 8px 0; border-top: 1px solid #555; opacity: 0.6;"></div>'
        
        speech_detected = audio_analysis.get('speech_detected', False)
        was_skipped = audio_analysis.get('skipped', False)
        
        if was_skipped:
            speech_status = "⏭️ SKIPPED"
        else:
            speech_status = "✅ DETECTED" if speech_detected else "❌ NOT DETECTED"
        
        analysis_html += f'<div class="analysis-item audio"><strong>Audio Speech Detection:</strong> {speech_status}</div>'
        
        if was_skipped:
            # Show skip reason for skipped analysis
            if audio_analysis.get('details'):
                analysis_html += f'<div class="analysis-detail">Details: {audio_analysis.get("details")}</div>'
        elif speech_detected:
            # Add details on separate lines for better readability
            if audio_analysis.get('detected_language'):
                analysis_html += f'<div class="analysis-detail">Language: {audio_analysis.get("detected_language")}</div>'
            if audio_analysis.get('combined_transcript'):
                transcript_preview = audio_analysis.get('combined_transcript')[:100] + ('...' if len(audio_analysis.get('combined_transcript', '')) > 100 else '')
                analysis_html += f'<div class="analysis-detail">Transcript: {transcript_preview}</div>'
            if audio_analysis.get('confidence'):
                analysis_html += f'<div class="analysis-detail">Confidence: {audio_analysis.get("confidence"):.2f}</div>'
        else:
            # Show failure details for failed (not skipped) analysis
            if audio_analysis.get('message'):
                analysis_html += f'<div class="analysis-detail">Details: {audio_analysis.get("message")}</div>'

        # Show R2 audio URLs if available for traceability (for both detected and not detected speech)
        audio_urls = audio_analysis.get('audio_urls', [])
        if audio_urls:
            analysis_html += '<div class="analysis-detail">Audio files:'
            for i, url in enumerate(audio_urls, 1):
                if url:
                    signed_url = ensure_signed_url(url)
                    analysis_html += f' <a href="{signed_url}" target="_blank" style="font-size: 10px; margin-left: 4px;">Segment {i}</a>'
            analysis_html += '</div>'
    
    # Audio Menu Analysis Results
    if audio_menu_analysis and audio_menu_analysis.get('success') is not None:
        analysis_html += '<div style="margin: 8px 0; border-top: 1px solid #555; opacity: 0.6;"></div>'
        
        menu_detected = audio_menu_analysis.get('menu_detected', False)
        menu_status = "✅ DETECTED" if menu_detected else "❌ NOT DETECTED"
        analysis_html += f'<div class="analysis-item audio-menu"><strong>Audio Menu Detection:</strong> {menu_status}</div>'
        
        if menu_detected:
            audio_languages = audio_menu_analysis.get('audio_languages', [])
            subtitle_languages = audio_menu_analysis.get('subtitle_languages', [])
            selected_audio = audio_menu_analysis.get('selected_audio', -1)
            selected_subtitle = audio_menu_analysis.get('selected_subtitle', -1)
            
            if audio_languages:
                # Show available audio languages with selected indicator
                audio_display = []
                for i, lang in enumerate(audio_languages):
                    if i == selected_audio:
                        audio_display.append(f"<strong>{lang}</strong> (selected)")
                    else:
                        audio_display.append(lang)
                analysis_html += f'<div class="analysis-detail">Audio Languages: {", ".join(audio_display)}</div>'
            
            if subtitle_languages:
                # Show available subtitle languages with selected indicator
                subtitle_display = []
                for i, lang in enumerate(subtitle_languages):
                    if i == selected_subtitle:
                        subtitle_display.append(f"<strong>{lang}</strong> (selected)")
                    else:
                        subtitle_display.append(lang)
                analysis_html += f'<div class="analysis-detail">Subtitle Languages: {", ".join(subtitle_display)}</div>'
        elif audio_menu_analysis.get('message'):
            analysis_html += f'<div class="analysis-detail">Details: {audio_menu_analysis.get("message")}</div>'

        # Add screenshot display for audio menu analysis (similar to subtitle analysis)
        analyzed_screenshot = ensure_signed_url(audio_menu_analysis.get('analyzed_screenshot'))
        if analyzed_screenshot:
            import json
            # Create single image modal data
            modal_data = {
                'title': 'Audio Menu Analysis Screenshot',
                'images': [{'url': analyzed_screenshot, 'label': 'Analyzed for Audio Menu'}]
            }
            # Encode modal data as JSON for JavaScript with proper escaping
            json_str = json.dumps(modal_data, ensure_ascii=True)
            modal_data_json = json_str.replace('"', '&quot;').replace("'", "&#x27;")
            
            # Use single function to format screenshot display name
            formatted_display = format_screenshot_display_name(analyzed_screenshot)
            
            analysis_html += f"""
            <div class='audio-menu-screenshot' style='margin-top: 4px;'>
                <div style='text-align: center;'>
                    <img src='{analyzed_screenshot}' style='width: 120px; height: 80px; object-fit: contain; border: 1px solid #ddd; border-radius: 3px; cursor: pointer;' 
                         onclick='openVerificationImageModal({modal_data_json})' title='Click to view audio menu analysis screenshot'>
                </div>
            </div>
            """
    
    
    return analysis_html


def format_step_screenshots(step: Dict, step_index: int) -> str:
    """Format screenshots section for a step."""
    screenshots_for_step = []
    
    # Debug logging to see what screenshot fields are available
    step_num = step.get('step_number', step_index + 1)
    print(f"[@report_step_formatter:format_step_screenshots] Step {step_num} screenshot fields:")
    print(f"  success: {step.get('success')}")
    error_msg = step.get('error', 'No error')
    error_preview = error_msg[:100] + "..." if error_msg and len(str(error_msg)) > 100 else (error_msg or 'No error')
    print(f"  error: {error_preview}")
    print(f"  step_start_screenshot_path: {step.get('step_start_screenshot_path')}")
    print(f"  step_end_screenshot_path: {step.get('step_end_screenshot_path')}")
    print(f"  screenshot_url: {step.get('screenshot_url')}")
    print(f"  screenshot_path: {step.get('screenshot_path')}")
    print(f"  action_screenshots: {step.get('action_screenshots', [])}")
    print(f"  verification_screenshots: {step.get('verification_screenshots', [])}")
    
    # Collect all screenshots in chronological order
    if step.get('step_start_screenshot_path'):
        # Use enhanced formatting for navigation step screenshots
        start_screenshot_path = step.get('step_start_screenshot_path')
        start_formatted_display = format_screenshot_display_name(start_screenshot_path)
        screenshots_for_step.append((f'{start_formatted_display}_step_start', start_screenshot_path, None, None))
    
    # Action screenshots - use action_results to get correct command and category
    # Actions provide their own screenshots, no need for separate "main action screenshot"
    action_screenshots = step.get('action_screenshots', [])
    action_results = step.get('action_results', [])
    
    # If we have action_results (new format with categories), use them
    if action_results:
        # action_results don't carry params, so recover the command+params from the
        # action definitions (step['actions'] / retry_actions / failure_actions). The
        # results appear in order within each category, so walk a per-category cursor
        # to map each screenshot back to its definition. Without this the screenshot
        # modal title shows e.g. "press_key()" with no key/wait_time, even though the
        # inline Actions section (which reads the definitions) shows them in full.
        defs_by_category = {
            'main': step.get('actions', []),
            'retry': step.get('retry_actions', []),
            'failure': step.get('failure_actions', []),
        }
        category_cursor = {}
        for i, screenshot_path in enumerate(action_screenshots):
            if i < len(action_results):
                result = action_results[i]
                action_category = result.get('action_category', 'main')  # main, retry, or failure

                # Pull the matching definition (params + command) by category position
                cursor = category_cursor.get(action_category, 0)
                category_cursor[action_category] = cursor + 1
                defs = defs_by_category.get(action_category, [])
                action_def = defs[cursor] if cursor < len(defs) else None

                # Prefer the definition's command; fall back to parsing the result message
                action_cmd = (action_def.get('command') if action_def else None) \
                    or result.get('message', 'unknown').split('(')[0].strip()
                action_params = action_def.get('params', {}) if action_def else {}

                # Create label with category indicator
                category_label = {
                    'main': '',
                    'retry': 'retry_',
                    'failure': 'failure_'
                }.get(action_category, '')
                
                # Use enhanced formatting for action screenshots
                # Don't include action_cmd in label - JavaScript will add it with ": cmd"
                action_formatted_display = format_screenshot_display_name(screenshot_path)
                label_suffix = f'{category_label}action' if category_label else ''
                screenshots_for_step.append((f'{action_formatted_display}_{label_suffix}' if label_suffix else action_formatted_display, screenshot_path, action_cmd, action_params))
            else:
                # Fallback if screenshot has no matching result
                action_formatted_display = format_screenshot_display_name(screenshot_path)
                screenshots_for_step.append((f'{action_formatted_display}_action_{i+1}', screenshot_path, 'unknown', {}))
    else:
        # Fallback to old method: combine all actions (main + retry + failure)
        all_actions = []
        all_actions.extend(step.get('actions', []))
        all_actions.extend(step.get('retry_actions', []))
        all_actions.extend(step.get('failure_actions', []))
        
        for i, screenshot_path in enumerate(action_screenshots):
            action_cmd = all_actions[i].get('command', 'unknown') if i < len(all_actions) else 'unknown'
            action_params = all_actions[i].get('params', {}) if i < len(all_actions) else {}
            # Use enhanced formatting for action screenshots
            action_formatted_display = format_screenshot_display_name(screenshot_path)
            screenshots_for_step.append((f'{action_formatted_display}_action_{i+1}', screenshot_path, action_cmd, action_params))
    
    # Verification screenshots - use verification_results to get correct command and type
    verification_screenshots = step.get('verification_screenshots', [])
    verification_results = step.get('verification_results', [])
    verifications = step.get('verifications', [])
    
    if verification_screenshots:
        # verification_screenshots is 1:1 with verification_results (the executor
        # emits one entry per leg, in order — '' for skipped any-pass legs that
        # captured no frame). Keep `i` as the true position so the command/params
        # lookup against verification_results[i]/verifications[i] stays correct;
        # just skip the empty placeholders so they don't render blank thumbnails.
        for i, screenshot_path in enumerate(verification_screenshots):
            if not screenshot_path:
                continue
            if i < len(verification_results):
                result = verification_results[i]
                # Prefer the leg's command (image/text/adb…); fall back to its
                # type, then the result's own command, before giving up.
                verification_cmd = result.get('verification_type') or result.get('command') or 'unknown'
                verification_params = result.get('params', {})

                if i < len(verifications):
                    verification = verifications[i]
                    verification_cmd = verification.get('command', verification_cmd)
                    # Extract verification parameters
                    verification_params = verification.get('params', verification_params)

                # Use enhanced formatting for verification screenshots
                verification_formatted_display = format_screenshot_display_name(screenshot_path)
                screenshots_for_step.append((f'{verification_formatted_display}_verification_{i+1}', screenshot_path, verification_cmd, verification_params))
            else:
                # Fallback if screenshot has no matching result
                verification_formatted_display = format_screenshot_display_name(screenshot_path)
                screenshots_for_step.append((f'{verification_formatted_display}_verification_{i+1}', screenshot_path, 'unknown', {}))
    
    # Check if this is a dummy "Script Start → Script End" step (no actual navigation)
    is_dummy_step = (step.get('from_node') == 'Script Start' and step.get('to_node') == 'Script End')
    
    # Step end screenshot
    if step.get('step_end_screenshot_path'):
        # Use enhanced formatting for navigation step screenshots
        end_screenshot_path = step.get('step_end_screenshot_path')
        end_formatted_display = format_screenshot_display_name(end_screenshot_path)
        screenshots_for_step.append((f'{end_formatted_display}_step_end', end_screenshot_path, None, None))
        print(f"[@report_step_formatter:format_step_screenshots] ✅ Step {step_num} end screenshot included")
    elif not is_dummy_step:
        # Only warn about missing screenshots for real navigation steps
        expected_filename = f"step_{step_num}_{step.get('from_node', 'unknown')}_{step.get('to_node', 'unknown')}_end"
        print(f"[@report_step_formatter:format_step_screenshots] ⚠️ Step {step_num} end screenshot NOT found - expected: {expected_filename}")
    
    print(f"[@report_step_formatter:format_step_screenshots] Step {step_num} total screenshots for modal: {len(screenshots_for_step)}")
    for i, (label, path, cmd, params) in enumerate(screenshots_for_step):
        print(f"  [{i+1}] {label}: {path}")
    
    if not screenshots_for_step:
        if not is_dummy_step:
            # Only warn for real steps - dummy steps are expected to have no screenshots
            print(f"[@report_step_formatter:format_step_screenshots] ⚠️ Step {step_num} has no screenshots - this may be a failed action")
        return ""
    
    step_id = step.get('step_number', step_index+1)
    from_node = step.get('from_node', 'Unknown')
    to_node = step.get('to_node', 'Unknown')
    step_title = f"Step {step_id}: {from_node} → {to_node}"
    
    # Show the step_end screenshot as thumbnail when available, otherwise fall back to the last captured screenshot
    thumbnail_index = next(
        (i for i, (label, _, _, _) in enumerate(screenshots_for_step) if label.endswith('_step_end')),
        len(screenshots_for_step) - 1
    )
    first_screenshot = screenshots_for_step[thumbnail_index]
    first_screenshot_path = first_screenshot[1]
    screenshot_count = len(screenshots_for_step)
    
    # For failed steps, emphasize that screenshots are available for debugging
    step_success = step.get('success', False)
    if not step_success and screenshot_count > 0:
        print(f"[@report_step_formatter:format_step_screenshots] 🔍 Failed step {step_num} has {screenshot_count} screenshot(s) for debugging")
    
    from .report_formatting import get_thumbnail_screenshot_html
    thumbnail_html = get_thumbnail_screenshot_html(
        first_screenshot_path,
        f"{screenshot_count} screenshot{'s' if screenshot_count > 1 else ''}",
        step_title,
        screenshots_for_step,
        0
    )
    
    return f"""
    <div class="step-screenshot-container">
        <div class="screenshot-row">
            {thumbnail_html}
        </div>
    </div>
    """


def format_execution_time(execution_time_ms: int) -> str:
    """Format execution time for display (seconds/minutes; never ms)."""
    if execution_time_ms < 1000:
        return f"{execution_time_ms / 1000:.1f}s"
    elif execution_time_ms < 60000:
        return f"{execution_time_ms / 1000:.1f}s"
    else:
        minutes = execution_time_ms // 60000
        seconds = (execution_time_ms % 60000) / 1000
        return f"{minutes}m {seconds:.1f}s"