"""
Report Generation Utilities for Restart Videos

This module provides functions to generate and upload restart video reports.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from .restart_video_template import create_restart_video_template
    from shared.src.lib.utils.cloudflare_utils import upload_restart_report, upload_restart_video
except ImportError as e:
    print(f"Warning: Import error in report_generation.py: {e}")
    # Define fallback functions for testing
    def create_restart_video_template():
        return "<!DOCTYPE html><html><head><title>Restart Video Report - {device_name}</title></head><body><h1>Report for {host_name} - {device_name}</h1><p>Video: {video_url}</p><p>Summary: {video_summary}</p><p>Transcript: {audio_transcript}</p><script>window.ANALYSIS_DATA = {analysis_data_json};</script></body></html>"
    
    def upload_restart_report(html_content, host_name, device_id, timestamp):
        return {'success': False, 'error': 'Upload functions not available in test environment'}
    
    def upload_restart_video(local_video_path, timestamp):
        return {'success': False, 'error': 'Upload functions not available in test environment'}


def generate_and_upload_restart_report(
    host_info: Dict[str, Any],
    device_info: Dict[str, Any], 
    video_url: str,
    analysis_data: Dict[str, Any],
    processing_time: float = 0.0,
    local_video_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate HTML report for restart video analysis and upload to R2 storage.
    
    Args:
        host_info: Dictionary containing host information (host_name)
        device_info: Dictionary containing device information (device_name, device_model, device_id)
        video_url: URL to the restart video
        analysis_data: Dictionary containing AI analysis results
        processing_time: Time taken for processing in seconds
        local_video_path: Optional local path to video file for upload
        
    Returns:
        Dictionary with 'success', 'report_url', 'report_path', and optional 'error' keys
    """
    try:
        print(f"[report_generation] Generating restart video report...")
        
        # Generate timestamp for report
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Extract information from parameters
        host_name = host_info.get('host_name', 'unknown')
        device_name = device_info.get('device_name', 'unknown')
        device_model = device_info.get('device_model', 'unknown')
        device_id = device_info.get('device_id', 'device1')
        
        # Upload video file if local path provided
        video_upload_url = video_url
        if local_video_path and os.path.exists(local_video_path):
            print(f"[report_generation] Uploading video file: {local_video_path}")
            video_upload_result = upload_restart_video(local_video_path, timestamp)
            if video_upload_result.get('success'):
                video_upload_url = video_upload_result['video_url']
                print(f"[report_generation] Video uploaded successfully: {video_upload_url}")
            else:
                print(f"[report_generation] Video upload failed: {video_upload_result.get('error', 'Unknown error')}")
                # Continue with original URL if upload fails
        
        # Extract analysis results
        audio_analysis = analysis_data.get('audio_analysis', {})
        subtitle_analysis = analysis_data.get('subtitle_analysis', {})
        video_analysis = analysis_data.get('video_analysis', {})
        
        # Get audio transcript
        audio_transcript = audio_analysis.get('combined_transcript', 'No audio transcript available')
        if not audio_transcript or audio_transcript.strip() == '':
            audio_transcript = 'No audio transcript available'
        
        # Get video summary
        video_summary = video_analysis.get('video_summary', 'No video summary available')
        if not video_summary or video_summary.strip() == '':
            video_summary = 'No video summary available'
        
        # Prepare analysis data for JavaScript
        analysis_data_json = json.dumps({
            'audio_analysis': audio_analysis,
            'subtitle_analysis': subtitle_analysis,
            'video_analysis': video_analysis,
            'processing_time': processing_time
        }, indent=2)
        
        # Generate HTML content using template
        template = create_restart_video_template()
        
        # Replace template variables
        html_content = template.format(
            device_name=device_name,
            host_name=host_name,
            timestamp=timestamp,
            video_url=video_upload_url,
            video_summary=video_summary,
            audio_transcript=audio_transcript,
            analysis_data_json=analysis_data_json
        )
        
        print(f"[report_generation] HTML report generated ({len(html_content)} characters)")
        
        # Upload report to R2
        upload_result = upload_restart_report(
            html_content=html_content,
            host_name=host_name,
            device_id=device_id,
            timestamp=timestamp
        )
        
        if upload_result.get('success'):
            report_url = upload_result['report_url']
            report_path = upload_result['report_path']
            print(f"[report_generation] Report uploaded successfully: {report_url}")
            
            return {
                'success': True,
                'report_url': report_url,
                'report_path': report_path,
                'video_url': video_upload_url,
                'timestamp': timestamp
            }
        else:
            error_msg = upload_result.get('error', 'Unknown upload error')
            print(f"[report_generation] Report upload failed: {error_msg}")
            return {
                'success': False,
                'error': f'Report upload failed: {error_msg}'
            }
            
    except Exception as e:
        error_msg = f"Report generation failed: {str(e)}"
        print(f"[report_generation] {error_msg}")
        import traceback
        print(f"[report_generation] Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': error_msg
        }
