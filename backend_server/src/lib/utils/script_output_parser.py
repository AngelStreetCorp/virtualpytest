"""
Script Output Parser Utilities for Server Side

This module provides utilities for parsing script output and extracting URLs.
The server doesn't generate reports but needs to parse host-generated output.
"""

import re
from typing import Dict, Optional


def extract_report_url_from_output(output_line: str) -> Optional[str]:
    """
    Extract report URL from script output line.
    
    Args:
        output_line: Single line of script output
        
    Returns:
        Report URL if found, None otherwise
    """
    marker = '[@cloudflare_utils:upload_script_report] INFO: Uploaded script report:'
    if marker not in output_line:
        return None
    # The uploader already emits the configured public URL or private storage path.
    # Preserve it verbatim, including signed URL query parameters.
    return output_line.split(marker, 1)[1].strip() or None



def extract_logs_url_from_output(output_line: str) -> Optional[str]:
    """
    Extract logs URL from script output line.
    
    Args:
        output_line: Single line of script output
        
    Returns:
        Logs URL if found, None otherwise
    """
    if '[@utils:report_utils:generate_and_upload_script_report] Logs uploaded:' in output_line:
        try:
            return output_line.split('Logs uploaded: ')[1].strip()
        except Exception:
            return None
    return None


def extract_script_success_from_output(output: str) -> Optional[bool]:
    """
    Extract SCRIPT_SUCCESS marker from complete script output.
    
    Args:
        output: Complete script output
        
    Returns:
        True/False if SCRIPT_SUCCESS found, None if not found
    """
    if output and 'SCRIPT_SUCCESS:' in output:
        success_match = re.search(r'SCRIPT_SUCCESS:(true|false)', output)
        if success_match:
            return success_match.group(1) == 'true'
    return None


def parse_script_execution_output(output: str) -> Dict[str, Optional[str]]:
    """
    Parse complete script output and extract all relevant information.
    
    Args:
        output: Complete script output
        
    Returns:
        Dict with report_url, logs_url, and script_success
    """
    result = {
        'report_url': None,
        'logs_url': None,
        'script_success': None
    }
    
    if not output:
        return result
    
    # Parse line by line for URLs
    for line in output.split('\n'):
        if not result['report_url']:
            result['report_url'] = extract_report_url_from_output(line)
        
        if not result['logs_url']:
            result['logs_url'] = extract_logs_url_from_output(line)
    
    # Extract script success from complete output
    result['script_success'] = extract_script_success_from_output(output)
    
    return result
