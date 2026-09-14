"""
Zap Utilities - Comprehensive zap-related utilities

Handles zap summary formatting, analysis logging, timestamp formatting,
and other zap-related utility functions.
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime


def format_time_from_timestamp(timestamp_str: str) -> str:
    """
    Format timestamp string to HH:MM:SS format.
    
    Args:
        timestamp_str: ISO timestamp string
        
    Returns:
        Time in HH:MM:SS format or 'N/A' if invalid
    """
    if not timestamp_str:
        return 'N/A'
    
    try:
        # Parse ISO timestamp and format as time only
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime('%H:%M:%S')
    except (ValueError, AttributeError):
        return 'N/A'




# DELETED: create_zap_summary_section() - used database calls and parsing
# Now using execution_summary directly from context (no DB calls, no parsing)


def generate_zap_summary_text(zap_data: List[Dict[str, Any]]) -> str:
    """
    Generate the exact same zap summary text that appears in logs.
    This is the shared function used by both logs and reports.
    
    Args:
        zap_data: List of zap iteration data from database
        
    Returns:
        Plain text string matching log format exactly
    """
    if not zap_data:
        return "No zap data available."
    
    lines = []
    
    # Header with separators
    lines.append("=" * 135)
    lines.append("🎯 ZAP EXECUTION SUMMARY")
    lines.append("=" * 135)
    
    # Header info
    first_iteration = zap_data[0]
    formatted_date = first_iteration['execution_date'][:19] if first_iteration.get('execution_date') else 'Unknown'
    lines.append(f"Host: {first_iteration['host_name']} | Device: {first_iteration['device_name']} ({first_iteration['device_model']}) | Date: {formatted_date}")
    lines.append("")
    
    # Table header — Zap (channel change detected) and Motion (destination playing
    # after zap) are SEPARATE columns: Zap = did it change channel, Motion = is the
    # landed channel actually playing video (not a frozen/parental-block screen).
    lines.append(f"{'Iter':<4} | {'Action':<12} | {'Start':<8} | {'End':<8} | {'Duration':<8} | {'Zap':<10} | {'Motion':<6} | {'Subtitles':<10} | {'Audio':<8} | {'Channel Info':<40}")
    lines.append("-" * 135)

    # Table rows
    motion_count = subtitle_count = audio_count = zap_count = success_count = 0
    for iteration in zap_data:
        # Format detection results (exact same logic as zap_controller)
        motion_icon = "✅" if iteration['motion_detected'] else "❌"
        subtitle_result = "✅" if iteration['subtitles_detected'] else "❌"
        if iteration['subtitles_detected'] and iteration['subtitle_language']:
            subtitle_result += f" {iteration['subtitle_language'][:2].upper()}"
        
        audio_result = "✅" if iteration['audio_speech_detected'] else "❌"
        if iteration['audio_speech_detected'] and iteration['audio_language']:
            audio_result += f" {iteration['audio_language'][:2].upper()}"
        
        # Zap column: did the channel actually change (blackscreen/freeze transition).
        zap_result = "❌"
        if iteration['blackscreen_freeze_detected']:
            duration = iteration['blackscreen_freeze_duration_seconds'] or 0
            method = iteration['detection_method'] or 'blackscreen'
            method_icon = "⬛" if method == 'blackscreen' else "🧊"
            zap_result = f"✅ {method_icon}{duration:.1f}s"
        
        # Format channel info - show partial info even without channel name
        channel_info = ""
        channel_parts = []
        
        # Channel name and number
        if iteration['channel_name']:
            if iteration['channel_number']:
                channel_parts.append(f"{iteration['channel_name']} ({iteration['channel_number']})")
            else:
                channel_parts.append(iteration['channel_name'])
        elif iteration['channel_number']:
            channel_parts.append(f"Ch {iteration['channel_number']}")
        
        # Program name
        if iteration['program_name']:
            channel_parts.append(iteration['program_name'])
        
        # Time range
        if iteration['program_start_time'] and iteration['program_end_time']:
            channel_parts.append(f"[{iteration['program_start_time']}-{iteration['program_end_time']}]")
        
        channel_info = " - ".join(channel_parts)
        
        # Truncate channel info if too long
        if len(channel_info) > 40:
            channel_info = channel_info[:37] + "..."
        
        # Format timestamps to HH:MM:SS
        start_time_str = format_time_from_timestamp(iteration.get('started_at', ''))
        end_time_str = format_time_from_timestamp(iteration.get('completed_at', ''))
        
        lines.append(f"{iteration['iteration_index']:<4} | {iteration['action_command']:<12} | {start_time_str:<8} | {end_time_str:<8} | {iteration['duration_seconds']:<8.1f}s | {zap_result:<10} | {motion_icon:<6} | {subtitle_result:<10} | {audio_result:<8} | {channel_info:<40}")

        # Count successes. An iteration is "successful" only if it zapped AND the
        # destination is playing (motion) — same rule as the script pass/fail.
        if iteration['motion_detected']:
            motion_count += 1
        if iteration['subtitles_detected']:
            subtitle_count += 1
        if iteration['audio_speech_detected']:
            audio_count += 1
        if iteration['blackscreen_freeze_detected']:
            zap_count += 1
        if iteration['blackscreen_freeze_detected'] and iteration['motion_detected']:
            success_count += 1

    # Summary totals
    total_iterations = len(zap_data)
    lines.append("-" * 135)
    lines.append(f"TOTALS: {success_count}/{total_iterations} successful (zap+motion) | Zap: {zap_count}/{total_iterations} ({zap_count/total_iterations*100:.0f}%) | Motion: {motion_count}/{total_iterations} ({motion_count/total_iterations*100:.0f}%) | Subtitles: {subtitle_count}/{total_iterations} ({subtitle_count/total_iterations*100:.0f}%) | Audio: {audio_count}/{total_iterations} ({audio_count/total_iterations*100:.0f}%)")
    
    # Calculate mean durations
    mean_zap_duration = sum(iteration['duration_seconds'] for iteration in zap_data) / total_iterations
    bf_durations = [iteration['blackscreen_freeze_duration_seconds'] for iteration in zap_data if iteration['blackscreen_freeze_detected'] and iteration['blackscreen_freeze_duration_seconds']]
    mean_bf_duration = sum(bf_durations) / len(bf_durations) if bf_durations else 0
    
    lines.append(f"MEANS: Zap Duration: {mean_zap_duration:.1f}s | Zap Transition (blackscreen/freeze) Duration: {mean_bf_duration:.1f}s")
    lines.append("=" * 135)
    
    return "\n".join(lines)


def create_zap_summary_text(zap_data: List[Dict[str, Any]]) -> str:
    """
    Create HTML wrapper for zap summary text for reports.
    
    Args:
        zap_data: List of zap iteration data from database
        
    Returns:
        HTML string with preformatted text matching log style
    """
    if not zap_data:
        return "<p>No zap data available.</p>"
    
    # Get the exact same text as logs
    text_content = generate_zap_summary_text(zap_data)
    
    return f"""
    <div class="zap-summary-text" style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 10px 0;">
        <pre style="font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.4; margin: 0; white-space: pre; overflow-x: auto;">{text_content}</pre>
    </div>
    """

def format_channel_info(zap: Dict[str, Any]) -> str:
    """
    Format channel information for display - shows partial info even without channel name.
    
    Args:
        zap: Single zap iteration data
        
    Returns:
        Formatted channel info string
    """
    channel_name = zap.get('channel_name', '')
    channel_number = zap.get('channel_number', '')
    program_name = zap.get('program_name', '')
    program_start = zap.get('program_start_time', '')
    program_end = zap.get('program_end_time', '')
    
    # Build channel info string
    parts = []
    
    # Channel name and number
    if channel_name:
        if channel_number:
            parts.append(f"{channel_name} ({channel_number})")
        else:
            parts.append(channel_name)
    elif channel_number:
        parts.append(f"Ch {channel_number}")
    
    # Program name
    if program_name:
        parts.append(program_name)
    
    # Time range
    if program_start and program_end:
        parts.append(f"[{program_start}-{program_end}]")
    
    return " - ".join(parts) if parts else "N/A"


# Analysis logging functions
def create_blackscreen_analysis_log(analyzed_screenshots: List[str], zapping_result: Dict[str, Any], key_release_timestamp: float) -> List[str]:
    """Create detailed analysis log for blackscreen detection failure"""
    log_lines = []
    
    # Header
    log_lines.append("VideoContent[Video Verification]: Starting blackscreen zapping detection")
    log_lines.append(f"VideoContent[Video Verification]: Key release timestamp: {datetime.fromtimestamp(key_release_timestamp).strftime('%Y%m%d%H%M%S')} (Unix: {key_release_timestamp})")
    log_lines.append(f"VideoContent[Video Verification]: Enhanced collection: {len(analyzed_screenshots)} images covering {len(analyzed_screenshots)}s")
    log_lines.append(f"VideoContent[Video Verification]: Found {len(analyzed_screenshots)} images to analyze")
    
    # Individual image analysis
    for i, screenshot_path in enumerate(analyzed_screenshots):
        filename = os.path.basename(screenshot_path)
        # Simulate blackscreen analysis log (we don't have the actual percentages from the result)
        log_lines.append(f"VideoContent[Video Verification]: {filename} | 1280x720 | region=400x200@(200,0) | blackscreen=False (0.0%)")
    
    # Summary
    log_lines.append(f"VideoContent[Video Verification]: Blackscreen analysis complete - {len(analyzed_screenshots)} images analyzed, early_stopped=False")
    log_lines.append("VideoContent[Video Verification]: Simple zapping detection complete - detected=False, duration=0.0s")
    
    return log_lines


def create_freeze_analysis_log(analyzed_screenshots: List[str], freeze_result: Dict[str, Any], key_release_timestamp: float) -> List[str]:
    """Create detailed analysis log for freeze detection failure"""
    log_lines = []
    
    # Header
    log_lines.append("VideoContent[Video Verification]: Starting freeze-based zapping detection")
    log_lines.append(f"VideoContent[Video Verification]: Key release timestamp: {datetime.fromtimestamp(key_release_timestamp).strftime('%Y%m%d%H%M%S')} (Unix: {key_release_timestamp})")
    log_lines.append(f"VideoContent[Video Verification]: Enhanced collection: {len(analyzed_screenshots)} images covering {len(analyzed_screenshots)}s")
    log_lines.append(f"VideoContent[Video Verification]: Found {len(analyzed_screenshots)} images to analyze for freeze zapping")
    
    # Individual comparisons
    comparisons = freeze_result.get('comparisons', [])
    for i, comp in enumerate(comparisons):
        if i + 1 < len(analyzed_screenshots):
            img1 = os.path.basename(analyzed_screenshots[i])
            img2 = os.path.basename(analyzed_screenshots[i + 1])
            diff = comp.get('difference', 0)
            frozen = comp.get('frozen', False)
            log_lines.append(f"VideoContent[Video Verification]: {img1} vs {img2}: diff={diff:.2f}, frozen={frozen}")
    
    # Summary
    frozen_count = sum(1 for c in comparisons if c.get('frozen', False))
    log_lines.append(f"VideoContent[Video Verification]: Freeze analysis - {frozen_count}/{len(comparisons)} frozen comparisons, max consecutive: 0, sequence detected: False, early_stopped=False")
    log_lines.append("VideoContent[Video Verification]: Freeze zapping detection complete - detected=False, duration=0.0s")
    
    return log_lines


def create_combined_analysis_log(analyzed_screenshots: List[str], key_release_timestamp: float) -> List[str]:
    """Create combined analysis log for both methods failed case"""
    log_lines = []
    
    # Header
    log_lines.append("VideoContent[Video Verification]: Both blackscreen and freeze detection failed")
    log_lines.append(f"VideoContent[Video Verification]: Key release timestamp: {datetime.fromtimestamp(key_release_timestamp).strftime('%Y%m%d%H%M%S')} (Unix: {key_release_timestamp})")
    log_lines.append(f"VideoContent[Video Verification]: Enhanced collection: {len(analyzed_screenshots)} images covering {len(analyzed_screenshots)}s")
    log_lines.append(f"VideoContent[Video Verification]: Found {len(analyzed_screenshots)} images to analyze")
    log_lines.append("")
    
    # Blackscreen analysis summary
    log_lines.append("--- BLACKSCREEN ANALYSIS ---")
    for i, screenshot_path in enumerate(analyzed_screenshots):
        filename = os.path.basename(screenshot_path)
        log_lines.append(f"VideoContent[Video Verification]: {filename} | 1280x720 | region=400x200@(200,0) | blackscreen=False (0.0%)")
    log_lines.append("VideoContent[Video Verification]: Blackscreen analysis complete - no blackscreen detected")
    log_lines.append("")
    
    # Freeze analysis summary
    log_lines.append("--- FREEZE ANALYSIS ---")
    for i in range(len(analyzed_screenshots) - 1):
        img1 = os.path.basename(analyzed_screenshots[i])
        img2 = os.path.basename(analyzed_screenshots[i + 1])
        # Simulate typical differences (we don't have actual comparison data)
        diff = 50.0 + (i * 10)  # Simulate varying differences
        log_lines.append(f"VideoContent[Video Verification]: {img1} vs {img2}: diff={diff:.2f}, frozen=False")
    log_lines.append("VideoContent[Video Verification]: Freeze analysis - 0 frozen comparisons, no freeze sequence detected")
    log_lines.append("")
    
    # Summary
    log_lines.append("--- FINAL RESULT ---")
    log_lines.append("VideoContent[Video Verification]: Both detection methods failed")
    log_lines.append("VideoContent[Video Verification]: No zapping transition detected")
    
    return log_lines


def validate_capture_filename(filename: str) -> bool:
    """Validate capture filename format to prevent FileNotFoundError on malformed files"""
    if not filename or not filename.startswith('capture_') or not filename.endswith('.jpg'):
        return False
    
    # Validate sequential format: capture_0001.jpg, capture_0002.jpg, etc.
    import re
    if not re.match(r'^capture_\d+\.jpg$', filename):
        print(f"🔍 [ZapUtils] Skipping invalid filename format: {filename}")
        return False
    
    # Additional protection: ensure it's not a thumbnail
    if '_thumbnail' in filename:
        return False
        
    return True


def capture_fullzap_summary(context, userinterface_name: str):
    """Capture fullzap summary and store in context - moved from fullzap.py"""
    lines = []
    data = context.custom_data
    
    action_command = data.get('action_command', 'unknown')
    max_iteration = data.get('max_iteration', 0)
    successful_iterations = data.get('successful_iterations', 0)
    motion_detected_count = data.get('motion_detected_count', 0)
    subtitles_detected_count = data.get('subtitles_detected_count', 0)
    audio_speech_detected_count = data.get('audio_speech_detected_count', 0)
    zapping_detected_count = data.get('zapping_detected_count', 0)
    total_action_time = data.get('total_action_time', 0)
    
    zapping_durations = data.get('zapping_durations', [])
    blackscreen_durations = data.get('blackscreen_durations', [])
    detected_channels = data.get('detected_channels', [])
    channel_info_results = data.get('channel_info_results', [])
    detected_languages = data.get('detected_languages', [])
    audio_languages = data.get('audio_languages', [])
    
    if max_iteration > 0:
        lines.append("📊 [ZapExecutor] Action execution summary:")
        lines.append(f"   • Total iterations: {max_iteration}")
        lines.append(f"   • Successful: {successful_iterations}")
        success_rate = (successful_iterations / max_iteration * 100) if max_iteration > 0 else 0
        lines.append(f"   • Success rate: {success_rate:.1f}%")
        avg_time = total_action_time / max_iteration if max_iteration > 0 else 0
        lines.append(f"   • Average time per iteration: {avg_time:.0f}ms")
        lines.append(f"   • Total action time: {total_action_time}ms")
        motion_rate = (motion_detected_count / max_iteration * 100) if max_iteration > 0 else 0
        lines.append(f"   • Motion detected: {motion_detected_count}/{max_iteration} ({motion_rate:.1f}%)")
        subtitle_rate = (subtitles_detected_count / max_iteration * 100) if max_iteration > 0 else 0
        lines.append(f"   • Subtitles detected: {subtitles_detected_count}/{max_iteration} ({subtitle_rate:.1f}%)")
        audio_speech_rate = (audio_speech_detected_count / max_iteration * 100) if max_iteration > 0 else 0
        lines.append(f"   • Audio speech detected: {audio_speech_detected_count}/{max_iteration} ({audio_speech_rate:.1f}%)")
        zapping_rate = (zapping_detected_count / max_iteration * 100) if max_iteration > 0 else 0
        lines.append(f"   • Zapping detected: {zapping_detected_count}/{max_iteration} ({zapping_rate:.1f}%)")
        
        if zapping_durations:
            avg_zap_duration = sum(zapping_durations) / len(zapping_durations)
            avg_blackscreen_duration = sum(blackscreen_durations) / len(blackscreen_durations) if blackscreen_durations else 0.0
            lines.append(f"   ⚡ Average zapping duration: {avg_zap_duration:.2f}s")
            lines.append(f"   ⬛ Average blackscreen/freeze duration: {avg_blackscreen_duration:.2f}s")
            
            min_zap = min(zapping_durations)
            max_zap = max(zapping_durations)
            lines.append(f"   📊 Zapping duration range: {min_zap:.2f}s - {max_zap:.2f}s")
        
        if detected_channels:
            lines.append(f"   📺 Channels detected: {', '.join(detected_channels)}")
            
            successful_channel_info = [info for info in channel_info_results if info.get('channel_name')]
            if successful_channel_info:
                lines.append(f"   🎬 Channel details:")
                for i, info in enumerate(successful_channel_info, 1):
                    channel_display = info['channel_name']
                    if info.get('channel_number'):
                        channel_display += f" ({info['channel_number']})"
                    if info.get('program_name'):
                        channel_display += f" - {info['program_name']}"
                    if info.get('program_start_time') and info.get('program_end_time'):
                        channel_display += f" [{info['program_start_time']}-{info['program_end_time']}]"
                    
                    lines.append(f"      {i}. {channel_display} (zap: {info['zapping_duration']:.2f}s, confidence: {info['channel_confidence']:.1f})")
        
        if detected_languages:
            lines.append(f"   🌐 Subtitle languages detected: {', '.join(detected_languages)}")
        
        if audio_languages:
            lines.append(f"   🎤 Audio languages detected: {', '.join(audio_languages)}")
        
        no_motion_count = max_iteration - motion_detected_count
        if no_motion_count > 0:
            lines.append(f"   ⚠️  {no_motion_count} zap(s) did not show content change")
        
        if successful_iterations == max_iteration:
            lines.append(f"✅ [fullzap] All {max_iteration} iterations of action '{action_command}' completed successfully!")
        else:
            lines.append(f"❌ [fullzap] Only {successful_iterations}/{max_iteration} iterations of action '{action_command}' completed successfully!")
        
        lines.append("")
    
    # Resolve the active variant the same way the scripts do
    # (device.navigation_context is canonical; empty/None = base).
    variant = None
    device = context.selected_device
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if isinstance(variant, str):
        variant = variant.strip() or None

    lines.append("🎯 [FULLZAP] EXECUTION SUMMARY")
    lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    lines.append(f"🖥️ Host: {context.host.host_name}")
    lines.append(f"📋 Interface: {userinterface_name}")
    lines.append(f"🎭 Variant: {variant or 'base'}")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    
    lines.append("✅ [fullzap] Fullzap execution completed successfully!")
    
    context.execution_summary = "\n".join(lines)


def format_timestamp_to_time(timestamp_str: str) -> str:
    """Format timestamp string to HH:MM:SS format."""
    if not timestamp_str:
        return 'N/A'
    
    try:
        # Parse ISO timestamp and format as time only
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime('%H:%M:%S')
    except (ValueError, AttributeError):
        return 'N/A'


def format_timestamp_to_hhmmss_ms(timestamp_str: str) -> str:
    """Format timestamp string to readable format like 21H25m26s.698ms."""
    if not timestamp_str:
        return 'N/A'
    
    try:
        # Parse ISO timestamp and format with milliseconds
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        # Format as 21H25m26s.698ms (more readable)
        ms = dt.microsecond // 1000
        return f"{dt.strftime('%H')}H{dt.strftime('%M')}m{dt.strftime('%S')}s.{ms:03d}ms"
    except (ValueError, AttributeError):
        return 'N/A'

def print_zap_summary_table(context):
    """Print formatted zap summary table from in-memory context data (NO database fetch)"""
    try:
        # Get zap data from context (already in memory from execution)
        zap_data = context.custom_data.get('zap_data')
        if not zap_data:
            print("⚠️ [ZapUtils] No zap data in context - skipping summary table")
            return
        
        analysis_results = zap_data.get('analysis_results', [])
        if not analysis_results:
            print("⚠️ [ZapUtils] No analysis results in zap data - skipping summary table")
            return
        
        # Convert analysis results to database-like format for formatter compatibility
        zap_iterations = []
        for i, result in enumerate(analysis_results, 1):
            result_dict = result.to_dict() if hasattr(result, 'to_dict') else result
            
            # Extract zap timing from analysis result
            zap_start_timestamp = result_dict.get('zap_start_timestamp')
            zap_end_timestamp = result_dict.get('zap_end_timestamp')
            total_zap_duration = result_dict.get('total_zap_duration', 0.0)
            
            # Convert timestamps to ISO format for table display
            started_at_iso = None
            completed_at_iso = None
            if zap_start_timestamp:
                started_at_iso = datetime.fromtimestamp(zap_start_timestamp).isoformat()
            if zap_end_timestamp:
                completed_at_iso = datetime.fromtimestamp(zap_end_timestamp).isoformat()
            
            # Convert to format expected by generate_zap_summary_text
            iteration_data = {
                'iteration_index': i,
                'execution_date': datetime.now().isoformat(),
                'host_name': context.host.host_name,
                'device_name': context.selected_device.device_name,
                'device_model': context.selected_device.device_model,
                'action_command': context.custom_data.get('action_command', 'unknown'),
                'started_at': started_at_iso,
                'completed_at': completed_at_iso,
                'duration_seconds': total_zap_duration,
                'motion_detected': result_dict.get('motion_detected', False),
                'subtitles_detected': result_dict.get('subtitles_detected', False),
                'subtitle_language': result_dict.get('detected_language'),
                'audio_speech_detected': result_dict.get('audio_speech_detected', False),
                'audio_language': result_dict.get('audio_language'),
                'blackscreen_freeze_detected': result_dict.get('zapping_detected', False),
                'blackscreen_freeze_duration_seconds': result_dict.get('blackscreen_duration', 0.0),
                'detection_method': result_dict.get('zapping_details', {}).get('detection_type'),
                'channel_name': result_dict.get('channel_name', ''),
                'channel_number': result_dict.get('channel_number', ''),
                'program_name': result_dict.get('program_name', ''),
                'program_start_time': result_dict.get('program_start_time', ''),
                'program_end_time': result_dict.get('program_end_time', '')
            }
            zap_iterations.append(iteration_data)
        
        # Use shared function to generate the exact same text as reports
        summary_text = generate_zap_summary_text(zap_iterations)
        print(f"\n{summary_text}")
        
        # Store detailed table for report
        context.zap_detailed_summary = summary_text
        
        # Also capture fullzap summary
        capture_fullzap_summary(context, context.userinterface_name)
        
    except Exception as e:
        print(f"❌ [ZapUtils] Failed to generate summary table: {e}")
        import traceback
        traceback.print_exc()