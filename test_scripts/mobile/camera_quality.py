#!/usr/bin/env python3
"""
Camera Capture and Quality Analysis Script for VirtualPyTest

This script captures an image using the device camera, pulls it from the device,
and analyzes its quality using comprehensive metrics.

Usage:
    python test_scripts/mobile/camera_quality.py [--output <output_path>]

Examples:
    python test_scripts/mobile/camera_quality.py                           # Capture and analyze with default settings
    python test_scripts/mobile/camera_quality.py --output /tmp/camera_test.jpg
    python test_scripts/mobile/camera_quality.py --device device1
"""

import sys
import os
import time
import tempfile
from pathlib import Path

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.utils.image_utils import compute_composite_note
from shared.src.lib.utils.report_step_formatter import format_single_step
from shared.src.lib.utils.ai_utils import call_vision_ai
from datetime import datetime


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format"""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def _get_quality_label(score: float) -> tuple:
    """Get quality label and emoji for a score (0-10)"""
    if score >= 8:
        return "EXCELLENT", "🟢"
    elif score >= 6:
        return "GOOD", "🟡"
    elif score >= 4:
        return "FAIR", "🟠"
    else:
        return "POOR", "🔴"


def _calculate_megapixels(resolution: str) -> str:
    """Calculate megapixels from resolution string"""
    try:
        parts = resolution.lower().replace('×', 'x').split('x')
        if len(parts) == 2:
            mp = (int(parts[0].strip()) * int(parts[1].strip())) / 1_000_000
            return f"{mp:.1f} MP"
    except:
        pass
    return ""


def capture_camera_report(context, output_path: str) -> str:
    """Capture camera analysis report - Simple, clean format"""
    lines = []
    
    lines.append("📸 CAMERA QUALITY REPORT")
    lines.append("═" * 40)
    
    if hasattr(context, 'quality_note') and context.quality_note is not None:
        quality_note = context.quality_note
        notes = context.quality_details.get('notes', {}) if hasattr(context, 'quality_details') else {}
        
        # Overall verdict
        if quality_note >= 9:
            verdict, verdict_emoji = "EXCELLENT", "🏆"
        elif quality_note >= 7:
            verdict, verdict_emoji = "GOOD", "✅"
        elif quality_note >= 5:
            verdict, verdict_emoji = "ACCEPTABLE", "⚠️"
        elif quality_note >= 3:
            verdict, verdict_emoji = "POOR", "❌"
        else:
            verdict, verdict_emoji = "UNUSABLE", "🚫"
        
        lines.append("")
        lines.append(f"🎯 OVERALL: {quality_note:.1f}/10 - {verdict} {verdict_emoji}")
        
        # Breakdown - simple table
        lines.append("")
        lines.append("📊 BREAKDOWN:")

        brisque_note = notes.get('brisque_note', 0)
        sharpness_note = notes.get('sharpness_note', 0)
        noise_note = notes.get('noise_note', 0)
        contrast_note = notes.get('contrast_note', 0)

        brisque_label, brisque_emoji = _get_quality_label(brisque_note)
        sharpness_label, sharpness_emoji = _get_quality_label(sharpness_note)
        noise_label, noise_emoji = _get_quality_label(noise_note)
        contrast_label, contrast_emoji = _get_quality_label(contrast_note)

        lines.append(f"   BRISQUE:        {brisque_note:.1f}/10  {brisque_emoji} {brisque_label}")
        lines.append(f"   Sharpness:      {sharpness_note:.1f}/10  {sharpness_emoji} {sharpness_label}")
        lines.append(f"   Noise:          {noise_note:.1f}/10  {noise_emoji} {noise_label}")
        lines.append(f"   Contrast:       {contrast_note:.1f}/10  {contrast_emoji} {contrast_label}")

        lines.append("")
        lines.append("   Score  50% BRISQUE + 30% Sharpness + 10% Noise + 10% Contrast")
        
        # Issues (only if any metric is poor)
        issues = []
        if sharpness_note < 4:
            issues.append("Sharpness is low - image may be blurry")
        if brisque_note < 4:
            issues.append("Image quality is low - visible artifacts")
        if noise_note < 4:
            issues.append("High noise level - image appears grainy")
        if contrast_note < 4:
            issues.append("Low contrast - image appears flat")
        
        if issues:
            lines.append("")
            lines.append("⚠️ ISSUES:")
            for issue in issues:
                lines.append(f"   • {issue}")

        # AI Analysis section
        if hasattr(context, 'ai_analysis') and context.ai_analysis.get('success'):
            ai_data = context.ai_analysis
            lines.append("")
            lines.append("🤖 AI ANALYSIS:")

            # Description
            description = ai_data.get('description', 'No description available')
            lines.append(f"   📝 Description: {description}")

            # AI Quality Assessment
            ai_quality = ai_data.get('ai_quality_assessment', 'UNKNOWN')
            ai_score = ai_data.get('ai_quality_score', 0.0)
            lines.append(f"   ⭐ AI Quality: {ai_quality} ({ai_score:.1f}/10)")

            # Quality explanation
            if ai_data.get('quality_explanation'):
                lines.append(f"   💡 Assessment: {ai_data['quality_explanation']}")

            # Coherence check
            coherence = ai_data.get('coherence_check', {})
            coherent = coherence.get('coherent', False)
            coherence_icon = "✅" if coherent else "⚠️"
            lines.append(f"   🔍 Coherence: {coherence_icon} {'COHERENT' if coherent else 'INCOHERENT'}")

            if coherence.get('significant_discrepancy'):
                lines.append("   ⚠️  SIGNIFICANT DISCREPANCY DETECTED")
                lines.append(f"   📊 {coherence.get('discrepancy_details', '')}")
            else:
                lines.append(f"   📊 {coherence.get('explanation', '')}")

        elif hasattr(context, 'ai_analysis') and not context.ai_analysis.get('success'):
            # AI analysis failed
            error_msg = context.ai_analysis.get('error', 'AI analysis failed')
            lines.append("")
            lines.append("🤖 AI ANALYSIS:")
            lines.append(f"   ❌ Failed: {error_msg}")

        # Image info - single line
        if hasattr(context, 'quality_details') and context.quality_details:
            image_info = context.quality_details.get('image_info', {})
            resolution = image_info.get('resolution', 'Unknown')
            file_size = _format_file_size(getattr(context, 'image_size', 0))
            megapixels = _calculate_megapixels(resolution)
            
            lines.append("")
            mp_str = f" ({megapixels})" if megapixels else ""
            lines.append(f"📐 IMAGE: {resolution}{mp_str} | {file_size}")
    
    else:
        lines.append("")
        lines.append("🔴 CAPTURE FAILED")
        if hasattr(context, 'capture_error'):
            lines.append(f"   Error: {context.capture_error}")
    
    # Footer
    execution_time = context.get_execution_time_ms() if hasattr(context, 'get_execution_time_ms') else 0
    lines.append("")
    lines.append(f"⏱️ {execution_time/1000:.1f}s")
    
    return "\n".join(lines)


def create_camera_step_result(context, output_path: str, success: bool):
    """Create a step result for camera capture and analysis using existing format"""

    # Create actions for the step
    actions = [{
        'command': 'capture_camera_image',
        'params': {'output_path': output_path, 'wait_time': 3000}
    }]

    if success and hasattr(context, 'quality_note'):
        actions.append({
            'command': 'analyze_image_quality',
            'params': {'image_path': output_path}
        })

    # Create verifications
    verifications = [{
        'command': 'verify_camera_capture',
        'type': 'camera_capture'
    }]

    if hasattr(context, 'quality_note') and context.quality_note is not None:
        verifications.append({
            'command': 'verify_image_quality',
            'type': 'image_quality',
            'params': {'min_quality': 5.0}
        })

    # Create action results
    action_results = []
    if success:
        action_results.append({
            'action_category': 'main',
            'success': True,
            'message': f"Camera image captured successfully to {output_path}"
        })

        if hasattr(context, 'quality_note') and context.quality_note is not None:
            quality_note = context.quality_note
            quality_passed = quality_note >= 5.0
            action_results.append({
                'action_category': 'main',
                'success': quality_passed,
                'message': f"Image quality analysis: {quality_note}/10 ({'PASS' if quality_passed else 'FAIL'})"
            })

    # Create verification results
    verification_results = [{
        'success': success,
        'verification_type': 'camera_capture',
        'message': 'Camera capture verification'
    }]

    if hasattr(context, 'quality_note') and context.quality_note is not None:
        quality_note = context.quality_note
        quality_passed = quality_note >= 5.0
        verification_results.append({
            'success': quality_passed,
            'verification_type': 'image_quality',
            'message': f'Image quality check: {quality_note}/10',
            'details': {
                'quality_score': quality_note,
                'assessment': 'EXCELLENT' if quality_note >= 9 else 'GOOD' if quality_note >= 7 else 'FAIR' if quality_note >= 5 else 'POOR'
            }
        })

    # Create the step result
    step_result = {
        'step_number': 1,
        'success': success,
        'message': f"Camera Capture & Quality Analysis - {'SUCCESS' if success else 'FAILED'}",
        'actions': actions,
        'action_results': action_results,
        'verifications': verifications,
        'verification_results': verification_results,
        'execution_time_ms': context.get_execution_time_ms(),
        'start_time': datetime.now().isoformat(),
        'end_time': datetime.now().isoformat(),
        # Add screenshot paths for report display (will be uploaded to R2)
        'screenshot_path': output_path if success else None,
        'step_end_screenshot_path': output_path if success else None,
        'screenshots': [output_path] if success else []
    }

    # Add error if failed
    if not success and hasattr(context, 'error_message'):
        step_result['error'] = context.error_message

    # Add quality analysis details
    if hasattr(context, 'quality_details') and context.quality_details and hasattr(context, 'quality_note') and context.quality_note is not None:
        details = context.quality_details
        analysis_html = "<div><strong>🎯 Image Quality Analysis:</strong></div>"

        quality_note = details.get('quality_note', 0)
        analysis_html += f"<div>⭐ Overall Quality: {quality_note}/10</div>"

        # Quality interpretation
        if quality_note >= 9:
            quality_desc = "EXCELLENT (Professional grade)"
        elif quality_note >= 7:
            quality_desc = "GOOD (Clear and usable)"
        elif quality_note >= 5:
            quality_desc = "FAIR (Acceptable for basic use)"
        elif quality_note >= 3:
            quality_desc = "POOR (Significant issues)"
        else:
            quality_desc = "VERY POOR (Unusable)"

        analysis_html += f"<div>📋 Assessment: {quality_desc}</div>"

        # Technical details
        image_info = details.get('image_info', {})
        analysis_html += "<div><strong>📐 Image Properties:</strong></div>"
        analysis_html += f"<div>📏 Resolution: {image_info.get('resolution', 'Unknown')}</div>"
        analysis_html += f"<div>🎨 Channels: {image_info.get('channels', 'Unknown')}</div>"

        analysis_html += "<div><strong>🔍 Technical Metrics:</strong></div>"
        analysis_html += "<div><em>(with quality ranges: EXCELLENT | GOOD | FAIR | POOR)</em></div>"

        # BRISQUE Score
        brisque_score = details.get('brisque_score', 'N/A')
        if brisque_score != 'N/A':
            if brisque_score < 30:
                brisque_quality = "EXCELLENT"
            elif brisque_score < 60:
                brisque_quality = "GOOD"
            elif brisque_score < 80:
                brisque_quality = "FAIR"
            else:
                brisque_quality = "POOR"
            analysis_html += f"<div>• BRISQUE Score: {brisque_score:.2f} <strong>({brisque_quality})</strong> - lower = better</div>"
            analysis_html += "<div>&nbsp;&nbsp;└─ 0-30: Excellent | 30-60: Good | 60-80: Fair | 80+: Poor</div>"
        else:
            analysis_html += f"<div>• BRISQUE Score: {brisque_score} - lower = better</div>"

        # Sharpness (with multi-metric breakdown)
        sharpness = details.get('sharpness', 'N/A')
        sharpness_details = details.get('sharpness_details', {})
        
        if sharpness != 'N/A':
            if sharpness > 1000:
                sharpness_quality = "EXCELLENT"
            elif sharpness > 500:
                sharpness_quality = "GOOD"
            elif sharpness > 200:
                sharpness_quality = "FAIR"
            else:
                sharpness_quality = "POOR"
            analysis_html += f"<div>• Sharpness (Laplacian): {sharpness:.2f} <strong>({sharpness_quality})</strong></div>"
            
            # Show individual sharpness metrics if available
            if sharpness_details:
                analysis_html += "<div>&nbsp;&nbsp;<strong>Multi-metric Analysis:</strong></div>"
                analysis_html += f"<div>&nbsp;&nbsp;├─ Laplacian: {sharpness_details.get('laplacian_note', 'N/A')}/10 (edge variance)</div>"
                analysis_html += f"<div>&nbsp;&nbsp;├─ Tenengrad: {sharpness_details.get('tenengrad_note', 'N/A')}/10 (gradient strength)</div>"
                analysis_html += f"<div>&nbsp;&nbsp;├─ FFT: {sharpness_details.get('fft_note', 'N/A')}/10 (high-frequency content)</div>"
                analysis_html += f"<div>&nbsp;&nbsp;└─ Edge Density: {sharpness_details.get('edge_note', 'N/A')}/10 (perceptual)</div>"
                combined = sharpness_details.get('combined_note', 'N/A')
                analysis_html += f"<div>&nbsp;&nbsp;<strong>Combined Score: {combined}/10</strong> (weighted average)</div>"
        else:
            analysis_html += f"<div>• Sharpness: {sharpness}</div>"

        # Noise Level
        noise_level = details.get('noise_level', 'N/A')
        if noise_level != 'N/A':
            if noise_level < 0.5:
                noise_quality = "EXCELLENT"
            elif noise_level < 2.0:
                noise_quality = "GOOD"
            elif noise_level < 5.0:
                noise_quality = "FAIR"
            else:
                noise_quality = "POOR"
            analysis_html += f"<div>• Noise Level: {noise_level:.2f} <strong>({noise_quality})</strong> - lower = less noise</div>"
            analysis_html += "<div>&nbsp;&nbsp;└─ <0.5: Excellent | 0.5-2.0: Good | 2.0-5.0: Fair | >5.0: Poor</div>"
        else:
            analysis_html += f"<div>• Noise Level: {noise_level} - lower = less noise</div>"

        # Contrast
        contrast = details.get('contrast', 'N/A')
        if contrast != 'N/A':
            if contrast > 60:
                contrast_quality = "EXCELLENT"
            elif contrast > 40:
                contrast_quality = "GOOD"
            elif contrast > 25:
                contrast_quality = "FAIR"
            else:
                contrast_quality = "POOR"
            analysis_html += f"<div>• Contrast: {contrast:.2f} <strong>({contrast_quality})</strong> - higher = better contrast</div>"
            analysis_html += "<div>&nbsp;&nbsp;└─ >60: Excellent | 40-60: Good | 25-40: Fair | <25: Poor</div>"
        else:
            analysis_html += f"<div>• Contrast: {contrast} - higher = better contrast</div>"

        # Component scores
        notes = details.get('notes', {})
        analysis_html += "<div><strong>📊 Component Scores (0-10 scale):</strong></div>"
        analysis_html += "<div><em>(weighted contribution to overall quality)</em></div>"

        brisque_note = notes.get('brisque_note', 'N/A')
        sharpness_note = notes.get('sharpness_note', 'N/A')
        noise_note = notes.get('noise_note', 'N/A')
        contrast_note = notes.get('contrast_note', 'N/A')

        analysis_html += f"<div>• BRISQUE Quality: {brisque_note}/10 (50% weight) - image naturalness & artifacts</div>"
        analysis_html += f"<div>• Sharpness: {sharpness_note}/10 (30% weight) - edge clarity & focus</div>"
        analysis_html += f"<div>• Noise: {noise_note}/10 (10% weight) - signal-to-noise ratio</div>"
        analysis_html += f"<div>• Contrast: {contrast_note}/10 (10% weight) - tonal range & detail</div>"

        # Overall calculation
        analysis_html += "<div><strong>🧮 Quality Calculation:</strong></div>"
        analysis_html += f"<div>Overall = (0.5 × {brisque_note}) + (0.3 × {sharpness_note}) + (0.1 × {noise_note}) + (0.1 × {contrast_note}) = {quality_note}/10</div>"

        # Add AI Analysis section to HTML report
        if hasattr(context, 'ai_analysis') and context.ai_analysis.get('success'):
            ai_data = context.ai_analysis
            analysis_html += "<div><strong>🤖 AI Analysis:</strong></div>"

            # AI Description
            description = ai_data.get('description', 'No description available')
            analysis_html += f"<div>📝 <strong>Description:</strong> {description}</div>"

            # AI Quality Assessment
            ai_quality = ai_data.get('ai_quality_assessment', 'UNKNOWN')
            ai_score = ai_data.get('ai_quality_score', 0.0)
            analysis_html += f"<div>⭐ <strong>AI Quality:</strong> {ai_quality} ({ai_score:.1f}/10)</div>"

            # Quality explanation
            if ai_data.get('quality_explanation'):
                analysis_html += f"<div>💡 <strong>Assessment:</strong> {ai_data['quality_explanation']}</div>"

            # Coherence check
            coherence = ai_data.get('coherence_check', {})
            coherent = coherence.get('coherent', False)
            coherence_icon = "✅" if coherent else "⚠️"
            coherence_status = "COHERENT" if coherent else "INCOHERENT"
            analysis_html += f"<div>🔍 <strong>Coherence Check:</strong> {coherence_icon} {coherence_status}</div>"

            # Coherence details
            if coherence.get('significant_discrepancy'):
                analysis_html += "<div>⚠️ <strong>SIGNIFICANT DISCREPANCY DETECTED</strong></div>"
                analysis_html += f"<div>📊 {coherence.get('discrepancy_details', '')}</div>"
            else:
                analysis_html += f"<div>📊 {coherence.get('explanation', '')}</div>"

        elif hasattr(context, 'ai_analysis') and not context.ai_analysis.get('success'):
            # AI analysis failed
            error_msg = context.ai_analysis.get('error', 'AI analysis failed')
            analysis_html += "<div><strong>🤖 AI Analysis:</strong></div>"
            analysis_html += f"<div>❌ <strong>Failed:</strong> {error_msg}</div>"

        step_result['analysis_html'] = analysis_html

    return step_result


def analyze_image_with_ai(image_path: str, technical_quality: float, technical_details: dict) -> dict:
    """
    Analyze image using AI to provide description, quality assessment, and coherence check.

    Args:
        image_path: Path to the captured image
        technical_quality: Overall quality score from technical analysis (0-10)
        technical_details: Dictionary with technical analysis results

    Returns:
        Dictionary with AI analysis results:
        {
            'success': bool,
            'description': str,
            'ai_quality_assessment': str ('EXCELLENT'|'GOOD'|'FAIR'|'POOR'),
            'ai_quality_score': float (0-10),
            'coherence_check': {
                'coherent': bool,
                'explanation': str,
                'discrepancy_details': str
            },
            'error': str (if any)
        }
    """
    try:
        print("🤖 [camera_quality] Starting AI image analysis...")

        # Create comprehensive prompt for AI analysis
        prompt = f"""Analyze this camera-captured image and provide a comprehensive assessment. You have technical quality metrics for reference:

TECHNICAL METRICS (for coherence check):
- Overall Quality Score: {technical_quality}/10
- BRISQUE Score: {technical_details.get('brisque_score', 'N/A')} (lower = better, <30=excellent, 30-60=good, 60-80=fair, 80+=poor)
- Sharpness Score: {technical_details.get('sharpness', 'N/A')} (higher = sharper)
- Noise Level: {technical_details.get('noise_level', 'N/A')} (lower = less noise)
- Contrast Score: {technical_details.get('contrast', 'N/A')} (higher = better contrast)

Please respond with JSON in this exact format:
{{
  "image_description": "A short, concise description of what you see in this image (10-20 words)",
  "quality_assessment": "EXCELLENT|GOOD|FAIR|POOR",
  "quality_score": 8.5,
  "quality_explanation": "Brief explanation of your quality assessment (why excellent/good/fair/poor)",
  "coherence_analysis": {{
    "coherent_with_technical": true/false,
    "coherence_explanation": "Does your visual assessment align with the technical metrics? Explain any discrepancies."
  }}
}}

IMPORTANT GUIDELINES:
- Quality assessment should be based on visual clarity, sharpness, color accuracy, and overall usability
- EXCELLENT: Professional quality, crystal clear, no visible issues
- GOOD: Clear and usable for most purposes
- FAIR: Acceptable but has noticeable issues
- POOR: Significant problems that affect usability

Be honest about any discrepancies between technical metrics and visual quality."""

        # Call AI vision analysis
        result = call_vision_ai(prompt, image_path, max_tokens=400, temperature=0.0)

        if not result['success']:
            return {
                'success': False,
                'error': f'AI analysis failed: {result.get("error", "Unknown error")}',
                'description': '',
                'ai_quality_assessment': 'UNKNOWN',
                'ai_quality_score': 0.0,
                'coherence_check': {
                    'coherent': False,
                    'explanation': 'AI analysis failed',
                    'discrepancy_details': 'Unable to perform coherence check due to AI failure'
                }
            }

        # Parse AI response
        content = result['content'].strip()

        # Clean up markdown formatting if present
        if content.startswith('```json'):
            content = content.replace('```json', '').replace('```', '').strip()

        try:
            import json
            ai_response = json.loads(content)

            # Extract and validate fields
            description = ai_response.get('image_description', 'No description available')
            ai_quality_assessment = ai_response.get('quality_assessment', 'UNKNOWN')
            ai_quality_score = float(ai_response.get('quality_score', 0.0))
            quality_explanation = ai_response.get('quality_explanation', '')

            # Coherence analysis
            coherence_data = ai_response.get('coherence_analysis', {})
            coherent = coherence_data.get('coherent_with_technical', True)
            coherence_explanation = coherence_data.get('coherence_explanation', 'No coherence analysis provided')

            # Determine if there's a significant discrepancy
            technical_to_ai_mapping = {
                'EXCELLENT': 9.0,
                'GOOD': 7.0,
                'FAIR': 5.0,
                'POOR': 3.0
            }

            expected_ai_score = technical_to_ai_mapping.get(ai_quality_assessment, 5.0)
            score_difference = abs(ai_quality_score - technical_quality)
            significant_discrepancy = score_difference > 2.0  # More than 2 points difference

            if significant_discrepancy:
                discrepancy_details = f"Significant discrepancy: AI score ({ai_quality_score:.1f}) vs Technical ({technical_quality:.1f}). {coherence_explanation}"
            else:
                discrepancy_details = f"Minor/normal variation: AI score ({ai_quality_score:.1f}) vs Technical ({technical_quality:.1f}). {coherence_explanation}"

            print(f"🤖 [camera_quality] AI analysis complete:")
            print(f"   📝 Description: {description}")
            print(f"   ⭐ Quality: {ai_quality_assessment} ({ai_quality_score:.1f}/10)")
            print(f"   🔍 Coherent: {coherent} - {coherence_explanation}")

            return {
                'success': True,
                'description': description,
                'ai_quality_assessment': ai_quality_assessment,
                'ai_quality_score': ai_quality_score,
                'quality_explanation': quality_explanation,
                'coherence_check': {
                    'coherent': coherent,
                    'explanation': coherence_explanation,
                    'discrepancy_details': discrepancy_details,
                    'score_difference': score_difference,
                    'significant_discrepancy': significant_discrepancy
                }
            }

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"🤖 [camera_quality] Failed to parse AI response: {e}")
            print(f"🤖 [camera_quality] Raw AI content: {content}")

            # Fallback: extract what we can from the raw text
            return {
                'success': False,
                'error': f'Failed to parse AI response: {e}',
                'description': content[:100] + '...' if len(content) > 100 else content,
                'ai_quality_assessment': 'UNKNOWN',
                'ai_quality_score': 0.0,
                'coherence_check': {
                    'coherent': False,
                    'explanation': 'Unable to parse AI response for coherence check',
                    'discrepancy_details': 'AI response parsing failed'
                }
            }

    except Exception as e:
        print(f"🤖 [camera_quality] AI analysis error: {e}")
        return {
            'success': False,
            'error': str(e),
            'description': '',
            'ai_quality_assessment': 'UNKNOWN',
            'ai_quality_score': 0.0,
            'coherence_check': {
                'coherent': False,
                'explanation': 'AI analysis failed due to error',
                'discrepancy_details': f'Exception: {str(e)}'
            }
        }


@script("camera_quality", "Capture camera image and analyze quality", default_device="device1")
def main():
    """Main camera capture and analysis function"""
    args = get_args()
    context = get_context()
    device = get_device()
    output_path = args.output or tempfile.mktemp(suffix='.jpg', prefix='camera_capture_')

    print("📸 [camera_quality] Starting camera capture and analysis")
    print(f"📁 [camera_quality] Output path: {output_path}")
    print(f"📱 [camera_quality] Device: {device.device_name} ({device.device_model})")

    try:
        # Step 1: Capture camera image using ExecutionOrchestrator
        print("📷 [camera_quality] Capturing camera image...")
        start_time = time.time()

        # Build camera capture action (same format as device actions)
        camera_action = {
            'command': 'capture_camera_image',
            'name': 'Capture Camera Image',
            'params': {
                'output_path': output_path,
                'wait_time': 3000
            },
            'action_type': 'remote'
        }

        print("📷 [camera_quality] Executing camera capture action via ExecutionOrchestrator...")

        # Execute through ExecutionOrchestrator (same as device_get_info.py)
        from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator
        import asyncio

        capture_result = asyncio.run(ExecutionOrchestrator.execute_actions(
            device=device,
            actions=[camera_action],
            team_id=context.team_id,
            context=context
        ))

        capture_time = time.time() - start_time
        print(".1f")

        if not capture_result.get('success'):
            context.capture_success = False
            context.capture_error = capture_result.get('error', 'Unknown capture error')
            context.error_message = f"Camera capture failed: {context.capture_error}"
            context.overall_success = False

            # Create step-based report and execution summary even for failures
            step_result = create_camera_step_result(context, output_path, False)
            context.step_results = [step_result]
            summary_text = capture_camera_report(context, output_path)
            context.execution_summary = summary_text

            return False

        context.capture_success = True

        # Step 2: Verify image exists and get basic info
        if os.path.exists(output_path):
            context.image_path = output_path
            context.image_size = os.path.getsize(output_path)
            print(f"🖼️  [camera_quality] Image captured: {context.image_size} bytes")
            
            # Add to context screenshots for R2 upload and report display
            context.add_screenshot(output_path)
            print(f"📤 [camera_quality] Image added to context for R2 upload")
        else:
            context.capture_success = False
            context.capture_error = "Image file not found after capture"
            context.error_message = "Image file not found after capture"
            context.overall_success = False

            # Create step-based report and execution summary for this failure case
            step_result = create_camera_step_result(context, output_path, False)
            context.step_results = [step_result]
            summary_text = capture_camera_report(context, output_path)
            context.execution_summary = summary_text

            return False

        # Step 3: Analyze image quality
        print("🎯 [camera_quality] Analyzing image quality...")
        analysis_start = time.time()

        quality_result = compute_composite_note(output_path)
        analysis_time = time.time() - analysis_start

        print(".1f")

        if quality_result:
            quality_note = quality_result['quality_note']
            print(f"⭐ [camera_quality] Quality Note: {quality_note}/10")

            context.quality_note = quality_note
            context.quality_details = quality_result
            context.image_info = quality_result.get('image_info', {})

            # Step 3.5: AI Analysis for description, quality assessment, and coherence check
            print("🤖 [camera_quality] Analyzing image with AI...")
            ai_analysis = analyze_image_with_ai(output_path, quality_note, quality_result)

            if ai_analysis['success']:
                context.ai_analysis = ai_analysis
                print(f"🤖 [camera_quality] AI analysis successful")
            else:
                print(f"🤖 [camera_quality] AI analysis failed: {ai_analysis.get('error', 'Unknown error')}")
                context.ai_analysis = ai_analysis

        else:
            print("❌ [camera_quality] Quality analysis failed")
            context.quality_note = None
            context.quality_details = {}
            context.image_info = {}

        context.overall_success = True

        # Create step-based report using existing infrastructure
        step_result = create_camera_step_result(context, output_path, True)
        context.step_results = [step_result]

        # Create execution summary
        summary_text = capture_camera_report(context, output_path)
        context.execution_summary = summary_text

        return True

    except Exception as e:
        # Catch any unexpected errors and ensure execution summary is set
        context.capture_success = False
        context.capture_error = str(e)
        context.error_message = f"Camera capture/analysis error: {str(e)}"
        context.overall_success = False
        print(f"❌ [camera_quality] Unexpected error: {str(e)}")

        # Create step-based report and execution summary even for unexpected errors
        step_result = create_camera_step_result(context, output_path, False)
        context.step_results = [step_result]
        summary_text = capture_camera_report(context, output_path)
        context.execution_summary = summary_text

        return False


# Script arguments
main._script_args = [
    '--output:str:'  # Script-specific param (empty = temp file)
]
main._script_description = "Capture photo and analyze camera image quality."
main._arg_descriptions = {
    'output': 'Output path for captured image',
}

main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "android_mobile",
}

if __name__ == "__main__":
    main()
