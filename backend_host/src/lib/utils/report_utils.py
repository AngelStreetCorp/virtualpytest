"""
Report Generation Utilities for Host Side

This module provides report generation functionality for the host side.
Moved from backend_server since host executes scripts and generates reports.

NOTE: For screenshot capture in scripts, use capture_screenshot_for_script() 
from shared.src.lib.utils.device_utils instead!
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.cloudflare_utils import upload_script_report, upload_validation_screenshots, upload_script_logs


def generate_and_upload_script_report(
    script_name: str,
    device_info: Dict,
    host_info: Dict,
    execution_time: int,
    success: bool,
    step_results: List[Dict] = None,
    screenshot_paths: List[str] = None,
    error_message: str = "",
    userinterface_name: str = "",
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    parameters: str = "",
    execution_summary: str = "",
    test_video_url: str = "",
    script_result_id: str = None,
    custom_data: Dict = None
) -> Dict[str, str]:
    """
    Generate HTML report and upload to R2 storage - host-side version.
    Can be used by any script execution (validation, simple scripts, etc.)
    
    Returns:
        Dict with 'report_url', 'report_path', 'logs_url', 'logs_path', and 'success' keys
    """
    try:
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Starting report generation...")
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Parameters - script_name: {script_name}")
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Parameters - device_info: {device_info}")
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Parameters - screenshot_paths length: {len(screenshot_paths) if screenshot_paths else 0}")
        
        # Keep execution timestamp for report display/time math.
        execution_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        # Use high-precision timestamp for upload paths to avoid cross-run collisions.
        upload_timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Timestamp generated: {execution_timestamp}")
        
        # Handle simple script execution (no step_results)
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
                'verification_results': [],
                'script_output': {
                    'stdout': stdout[:2000] if stdout else '',
                    'stderr': stderr[:2000] if stderr else '',
                    'exit_code': exit_code
                }
            }]
        
        # Calculate verification statistics
        total_verifications = sum(len(step.get('verification_results', [])) for step in step_results)
        passed_verifications = sum(
            sum(1 for v in step.get('verification_results', []) if v.get('success', False)) 
            for step in step_results
        )
        failed_verifications = total_verifications - passed_verifications
        
        # Upload screenshots FIRST to get R2 URLs
        url_mapping = {}  # Map local paths to R2 URLs
        if screenshot_paths:
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
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: No screenshots to upload")
        
        # Update step_results to use R2 URLs instead of local paths
        updated_step_results = update_step_results_with_r2_urls(step_results, url_mapping)
        
        # Upload script logs to R2 if stdout is provided
        logs_url = ""
        logs_path = ""
        if stdout and stdout.strip():
            print(f"[@utils:report_utils:generate_and_upload_script_report] Uploading script logs...")
            logs_upload_result = upload_script_logs(
                log_content=stdout,
                device_model=device_info.get('device_model', 'unknown'),
                script_name=script_name.replace('.py', ''),
                timestamp=upload_timestamp,
                script_result_id=script_result_id
            )
            
            if logs_upload_result['success']:
                logs_url = logs_upload_result['url']
                logs_path = logs_upload_result['path']
                print(f"[@utils:report_utils:generate_and_upload_script_report] Logs uploaded: {logs_url}")
            else:
                print(f"[@utils:report_utils:generate_and_upload_script_report] Logs upload failed: {logs_upload_result.get('error', 'Unknown error')}")
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] No stdout provided, skipping log upload")
        
        # Calculate proper start and end times based on actual script execution
        execution_time_seconds = execution_time / 1000.0  # Convert ms to seconds
        
        # Parse execution_timestamp to datetime object
        end_datetime = datetime.strptime(execution_timestamp, '%Y%m%d%H%M%S')
        
        # Calculate start time by subtracting execution duration
        from datetime import timedelta
        start_datetime = end_datetime - timedelta(seconds=execution_time_seconds)
        
        # Format back to timestamp strings
        calculated_start_time = start_datetime.strftime('%Y%m%d%H%M%S')
        calculated_end_time = execution_timestamp  # This is already the end time
        
        print(f"[@utils:report_utils:generate_and_upload_script_report] DEBUG: Calculated timing:")
        print(f"  - Execution duration: {execution_time_seconds:.1f}s ({execution_time}ms)")
        print(f"  - Start time: {calculated_start_time} ({start_datetime.strftime('%H:%M:%S')})")
        print(f"  - End time: {calculated_end_time} ({end_datetime.strftime('%H:%M:%S')})")

        # Prepare report data (same structure as validation.py) - now with R2 URLs and correct timestamps
        report_data = {
            'script_name': script_name,
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
            'test_video_url': test_video_url,
            'script_result_id': script_result_id,
            'custom_data': custom_data or {}  # Pass zap data from memory
        }
        
        html_content = generate_validation_report(report_data)
        
        # Upload report to R2
        upload_result = upload_script_report(
            html_content=html_content,
            device_model=device_info.get('device_model', 'unknown'),
            script_name=script_name.replace('.py', ''),
            timestamp=upload_timestamp,
            script_result_id=script_result_id
        )
       
        if upload_result['success']:
            report_url = upload_result['report_url']
            report_path = upload_result['report_path']
            print(f"[@utils:report_utils:generate_and_upload_script_report] Report uploaded: {report_url}")
            return {
                'success': True,
                'report_url': report_url,
                'report_path': report_path,
                'logs_url': logs_url,
                'logs_path': logs_path
            }
        else:
            print(f"[@utils:report_utils:generate_and_upload_script_report] Upload failed: {upload_result.get('error', 'Unknown error')}")
            return {
                'success': False,
                'report_url': '',
                'report_path': '',
                'logs_url': '',
                'logs_path': ''
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


def format_execution_time(execution_time_ms: int) -> str:
    """Format execution time for display."""
    if execution_time_ms < 1000:
        return f"{execution_time_ms}ms"
    elif execution_time_ms < 60000:
        return f"{execution_time_ms / 1000:.1f}s"
    else:
        minutes = execution_time_ms // 60000
        seconds = (execution_time_ms % 60000) / 1000
        return f"{minutes}m {seconds:.1f}s"


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


# Import helper functions from shared utilities
def update_step_results_with_r2_urls(step_results: List[Dict], url_mapping: Dict[str, str]) -> List[Dict]:
    """Update step results to use R2 URLs instead of local paths"""
    try:
        # Import from shared utilities since this is a formatting function
        from shared.src.lib.utils.report_formatting_utils import update_step_results_with_r2_urls as shared_update
        return shared_update(step_results, url_mapping)
    except ImportError:
        # Fallback implementation if shared utility doesn't exist
        updated_results = []
        for step in step_results:
            updated_step = step.copy()
            
            # Update screenshot paths to R2 URLs
            if step.get('step_start_screenshot_path') and step['step_start_screenshot_path'] in url_mapping:
                updated_step['step_start_screenshot_path'] = url_mapping[step['step_start_screenshot_path']]
            
            if step.get('step_end_screenshot_path') and step['step_end_screenshot_path'] in url_mapping:
                updated_step['step_end_screenshot_path'] = url_mapping[step['step_end_screenshot_path']]
            
            if step.get('screenshot_path') and step['screenshot_path'] in url_mapping:
                updated_step['screenshot_path'] = url_mapping[step['screenshot_path']]
            
            # Update action screenshots
            if step.get('action_screenshots'):
                updated_action_screenshots = []
                for screenshot_path in step['action_screenshots']:
                    if screenshot_path in url_mapping:
                        updated_action_screenshots.append(url_mapping[screenshot_path])
                    else:
                        updated_action_screenshots.append(screenshot_path)
                updated_step['action_screenshots'] = updated_action_screenshots
            
            # Update verification images
            if step.get('verification_images'):
                updated_verification_images = []
                for image_path in step['verification_images']:
                    if image_path in url_mapping:
                        updated_verification_images.append(url_mapping[image_path])
                    else:
                        updated_verification_images.append(image_path)
                updated_step['verification_images'] = updated_verification_images
            
            updated_results.append(updated_step)
        
        return updated_results


def generate_validation_report(report_data: Dict) -> str:
    """
    Generate HTML validation report with embedded CSS and screenshots.
    Host-side version that uses shared report generation utilities.
    
    Args:
        report_data: Dictionary containing all report information
        
    Returns:
        Complete HTML report as string
    """
    try:
        # Import from shared utilities for report generation
        from shared.src.lib.utils.report_generation_utils import generate_validation_report as shared_generate
        return shared_generate(report_data)
    except ImportError:
        # Fallback to basic HTML if shared utility doesn't exist
        script_name = report_data.get('script_name', 'Unknown Script')
        success = report_data.get('success', False)
        execution_time = report_data.get('execution_time', 0)
        device_info = report_data.get('device_info', {})
        host_info = report_data.get('host_info', {})
        error_msg = report_data.get('error_msg', '')
        
        status = "PASS" if success else "FAIL"
        status_class = "success" if success else "failure"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Script Report: {script_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f5f5f5; padding: 20px; border-radius: 5px; }}
                .{status_class} {{ color: {'green' if success else 'red'}; }}
                .error {{ background: #ffe6e6; padding: 10px; border-radius: 5px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Script Report: {script_name}</h1>
                <p><strong>Status:</strong> <span class="{status_class}">{status}</span></p>
                <p><strong>Execution Time:</strong> {format_execution_time(execution_time)}</p>
                <p><strong>Device:</strong> {device_info.get('device_name', 'Unknown')} ({device_info.get('device_model', 'Unknown')})</p>
                <p><strong>Host:</strong> {host_info.get('host_name', 'Unknown')}</p>
            </div>
            {f'<div class="error"><strong>Error:</strong> {error_msg}</div>' if error_msg else ''}
        </body>
        </html>
        """
        return html_content
