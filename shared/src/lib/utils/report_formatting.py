"""
Report Formatting Utilities

This module handles HTML formatting, thumbnails, and utility functions for reports.
Contains functions for creating HTML sections, formatting data, and handling images.
"""

import json
import re
from typing import Dict, List, Optional, Any
from .report_step_formatter import create_compact_step_results_section
from .cloudflare_utils import convert_to_signed_url


def ensure_signed_url(url: str) -> str:
    """Ensure URL is signed if it's an R2 URL. Used when embedding in HTML reports."""
    if not url:
        return url
    # Only sign R2 URLs (public or endpoint URLs)
    if 'r2.dev' in url or 'r2.cloudflarestorage.com' in url or url.startswith('script-reports/') or url.startswith('navigation/'):
        return convert_to_signed_url(url)
    return url


def sanitize_for_json(text: str) -> str:
    """
    Sanitize text to be JSON-safe by removing control characters.
    
    Args:
        text: Input text that may contain control characters
        
    Returns:
        Sanitized text safe for JSON serialization
    """
    if not text:
        return text
    
    # Remove control characters (newlines, tabs, etc.) and replace with underscores
    # Keep alphanumeric, spaces, hyphens, underscores, and basic punctuation
    sanitized = re.sub(r'[\n\r\t\f\v]', '_', text)  # Replace control chars with underscore
    sanitized = re.sub(r'[^\w\s\-_.,()#]', '_', sanitized)  # Replace other special chars
    sanitized = re.sub(r'_+', '_', sanitized)  # Collapse multiple underscores
    sanitized = sanitized.strip('_')  # Remove leading/trailing underscores
    
    return sanitized


def get_video_thumbnail_html(video_url: str, label: str = "Video") -> str:
    """Generate HTML for video thumbnail that opens video URL in modal (supports MP4 and HLS)"""
    if not video_url or video_url is None:
        return '<div class="video-placeholder" style="text-align: center; color: #888; font-style: italic; padding: 20px;">No video available</div>'
    
    # Escape quotes in the URL and label for JavaScript
    escaped_url = video_url.replace("'", "\\'").replace('"', '\\"')
    escaped_label = label.replace("'", "\\'").replace('"', '\\"')
    
    # Determine video type for appropriate source tag
    video_type = "video/mp4" if video_url.endswith('.mp4') else "application/x-mpegURL"
    video_format = "MP4" if video_url.endswith('.mp4') else "HLS"
    
    return f"""
    <div class="video-thumbnail" onclick="console.log('Video thumbnail clicked: {video_format}'); openVideoModal('{escaped_url}', '{escaped_label}')" style="cursor: pointer; position: relative; width: 100%; max-width: 200px; margin: 0 auto; display: block;" title="Click to play {video_format} video">
        <video muted preload="metadata" style="width: 100%; height: auto; object-fit: contain; max-height: 150px;">
            <source src="{video_url}" type="{video_type}">
        </video>
        <div class="play-overlay" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 24px;">▶</div>
    </div>
    """


_BANNER_LINE_RE = re.compile(r'^=+$', re.MULTILINE)
# Matches both absolute (`https://…`) and root-relative (`/host/…`) link
# targets. Root-relative is needed for host-served reports like the
# verification failure report (`/host/<host>/stream/.../*.html`): the script
# report HTML is served from the same proxy origin as the host, so a relative
# href resolves there exactly like the step report's "View Detailed Comparison
# Report" anchor (report_step_formatter emits that href raw). Without the `/`
# alternative a relative `[kpi_report](/host/…)` stayed as literal text.
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\(((?:https?://|/)[^\s)]+)\)')
# Negative lookbehind skips URLs that are already the href value of an <a>
# tag — markdown links are transformed first and we don't want to re-wrap
# their URLs into nested anchors (which breaks the rendered HTML).
_URL_RE = re.compile(r'(?<!href=")(https?://[^\s<>"\']+)')


def format_console_summary_for_html(console_text: str) -> str:
    """Convert console summary text to HTML format."""
    if not console_text:
        return """<div class="summary-stats">
    <pre style="white-space: pre-wrap; font-family: 'Courier New', monospace; margin: 0;">📊 Execution summary not available<br>ℹ️  This may be from an older script run<br>🔄 Run the script again to see detailed summary</pre>
</div>"""

    # Strip banner-style separator lines (whole line of '=' chars only) — the
    # earlier blanket .replace('=', '') destroyed inline '=' chars in signed
    # URLs and any `key=value` content. Line-anchored regex preserves them.
    cleaned = _BANNER_LINE_RE.sub('', console_text)
    # Markdown-style links `[text](url)` → `<a href="url">text</a>` so summaries
    # can emit labeled links (e.g. `[kpi_report](https://...)`) without
    # surfacing the full URL in the rendered report.
    cleaned = _MD_LINK_RE.sub(
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        cleaned,
    )
    # Auto-link any remaining bare http(s) URLs. URLs already inside an
    # href="..." attribute aren't re-matched because the regex excludes `"`.
    linked = _URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener">\1</a>', cleaned)
    html_text = linked.replace('\n', '<br>')

    return f"""<div class="summary-stats">
    <pre style="white-space: pre-wrap; font-family: 'Courier New', monospace; margin: 0;">{html_text}</pre>
</div>"""


def create_error_section(error_msg: str) -> str:
    """Create HTML for error section."""
    return f"""<div class="section">
    <div class="error-section">
        <h3>Error Details</h3>
        <div class="error-message">{error_msg}</div>
    </div>
</div>"""


def get_thumbnail_screenshot_html(screenshot_path: Optional[str], label: str = None, step_title: str = None, all_screenshots: list = None, current_index: int = 0) -> str:
    """Get HTML for displaying a thumbnail screenshot that opens modal with navigation."""
    if not screenshot_path:
        return ''
    
    # Sign the main screenshot URL
    signed_screenshot_path = ensure_signed_url(screenshot_path)
    
    # Prepare screenshots for modal with signed URLs
    modal_screenshots = []
    if all_screenshots:
        for screenshot_data in all_screenshots:
            screenshot_label = screenshot_data[0]
            screenshot_working_path = ensure_signed_url(screenshot_data[1])  # Sign each URL
            action_cmd = screenshot_data[2] if len(screenshot_data) > 2 else None
            action_params = screenshot_data[3] if len(screenshot_data) > 3 else None
            
            modal_screenshots.append({
                'label': screenshot_label,
                'url': screenshot_working_path,
                'command': action_cmd,
                'params': action_params or {}
            })
    else:
        modal_screenshots.append({
            'label': label or 'Screenshot',
            'url': signed_screenshot_path,
            'command': None,
            'params': {}
        })
    
    # Create modal data for navigation
    modal_data = {
        'step_title': step_title or 'Screenshot',
        'screenshots': modal_screenshots,
        'current_index': current_index
    }
    
    # Encode modal data as JSON for JavaScript with proper escaping
    # First ensure JSON is valid by handling control characters
    json_str = json.dumps(modal_data, ensure_ascii=True)
    # Then escape for HTML embedding
    modal_data_json = json_str.replace('"', '&quot;').replace("'", "&#x27;")
    
    display_url = signed_screenshot_path
    
    return f"""
    <div class="screenshot-container">
        <span class="screenshot-label">{label or 'Screenshot'}</span>
        <img src="{display_url}" alt="Screenshot" class="screenshot-thumbnail" 
             style="width: 100%; height: auto; object-fit: contain; max-height: 150px;" 
             onclick="openScreenshotModal('{modal_data_json}')">
    </div>
    """


def update_step_results_with_r2_urls(step_results: List[Dict], url_mapping: Dict[str, str]) -> List[Dict]:
    """Update step results to replace local screenshot paths with R2 URLs."""
    if not url_mapping:
        return step_results
    
    updated_results = []
    for step in step_results:
        updated_step = step.copy()
        
        # Update various screenshot fields (step-level screenshot arrays)
        for field in ['action_screenshots', 'verification_screenshots']:
            if field in updated_step and updated_step[field]:
                updated_list = []
                for path in updated_step[field]:
                    if path and path.startswith('http'):
                        updated_list.append(path)
                    else:
                        r2_url = url_mapping.get(path, path)
                        updated_list.append(r2_url)
                updated_step[field] = updated_list
        
        # Update single path fields
        for field in ['screenshot_path', 'screenshot_url', 'step_start_screenshot_path', 'step_end_screenshot_path']:
            if field in updated_step and updated_step[field]:
                original_path = updated_step[field]
                if not original_path.startswith('http'):
                    r2_url = url_mapping.get(original_path, original_path)
                    updated_step[field] = r2_url
        
        # Update verification results with R2 URLs (for individual verification images)
        if 'verification_results' in updated_step and updated_step['verification_results']:
            updated_verification_results = []
            for verification_result in updated_step['verification_results']:
                updated_verification = verification_result.copy()
                
                # Update verification_images field if it exists
                if 'verification_images' in updated_verification and updated_verification['verification_images']:
                    updated_verification_images = []
                    for img_path in updated_verification['verification_images']:
                        if img_path and img_path.startswith('http'):
                            updated_verification_images.append(img_path)
                        else:
                            r2_url = url_mapping.get(img_path, img_path)
                            updated_verification_images.append(r2_url)
                    updated_verification['verification_images'] = updated_verification_images
                
                updated_verification_results.append(updated_verification)
            updated_step['verification_results'] = updated_verification_results
        
        # Update analysis results with R2 URLs (for zap controller analysis)
        for analysis_field in ['subtitle_analysis', 'audio_analysis', 'audio_menu_analysis', 'motion_analysis', 'zapping_analysis']:
            if analysis_field in updated_step and updated_step[analysis_field]:
                analysis = updated_step[analysis_field]
                # Update analyzed_screenshot field if it exists
                if 'analyzed_screenshot' in analysis and analysis['analyzed_screenshot']:
                    original_path = analysis['analyzed_screenshot']
                    if not original_path.startswith('http'):
                        r2_url = url_mapping.get(original_path, original_path)
                        analysis['analyzed_screenshot'] = r2_url
                
                # Update other potential image fields in analysis results
                for img_field in ['screenshot_path', 'image_path', 'first_image', 'blackscreen_start_image', 
                                  'blackscreen_end_image', 'first_content_after_blackscreen', 'failure_mosaic_path']:
                    if img_field in analysis and analysis[img_field]:
                        original_path = analysis[img_field]
                        if not original_path.startswith('http'):
                            r2_url = url_mapping.get(original_path, original_path)
                            analysis[img_field] = r2_url
                
                # Update motion analysis images array (for motion detection thumbnails)
                if 'motion_analysis_images' in analysis and analysis['motion_analysis_images']:
                    updated_motion_images = []
                    for motion_img in analysis['motion_analysis_images']:
                        updated_img = motion_img.copy()
                        if 'path' in updated_img and updated_img['path']:
                            original_path = updated_img['path']
                            if not original_path.startswith('http'):
                                r2_url = url_mapping.get(original_path, original_path)
                                updated_img['path'] = r2_url
                        updated_motion_images.append(updated_img)
                    analysis['motion_analysis_images'] = updated_motion_images
        
        updated_results.append(updated_step)
    
    return updated_results


def create_verification_image_modal_data(source_image: str, reference_image: str, overlay_image: str) -> str:
    """Create JSON data for verification image comparison modal."""
    modal_data = {
        'title': 'Image Verification Comparison',
        'images': []
    }
    
    # Add all available images with signed URLs
    if source_image:
        modal_data['images'].append({
            'url': ensure_signed_url(source_image),
            'label': 'Source Image (Current)'
        })
    
    if reference_image:
        modal_data['images'].append({
            'url': ensure_signed_url(reference_image),
            'label': 'Reference Image (Expected)'
        })
    
    if overlay_image:
        modal_data['images'].append({
            'url': ensure_signed_url(overlay_image),
            'label': 'Overlay (Differences)'
        })
    
    # Convert to JSON and escape for embedding in HTML
    # First ensure JSON is valid by handling control characters
    json_str = json.dumps(modal_data, ensure_ascii=True)
    # Then escape for HTML embedding
    return json_str.replace('"', '&quot;').replace("'", "&#x27;")


def create_error_report(error_message: str) -> str:
    """Create a minimal error report when report generation fails."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Report Generation Error</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .error {{ color: red; background: #ffe6e6; padding: 20px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1>Report Generation Error</h1>
    <div class="error">
        <h3>Error occurred while generating the report:</h3>
        <p>{error_message}</p>
    </div>
</body>
</html>"""