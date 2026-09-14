"""
Get Current Time Block

Returns the current timestamp in 2 formats: formatted string or unix timestamp.
"""

import time
from datetime import datetime
from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration"""
    return {
        'command': 'get_current_time',
        'label': 'Get Current Time',  # Short name for toolbox
        'description': 'Get current timestamp',  # Longer description
        'params': {
            'format': create_param(
                ParamType.ENUM,
                required=False,
                default='formatted',
                choices=[
                    {'label': 'Formatted (YYMMDD-HH:MM:SS.ms)', 'value': 'formatted'},
                    {'label': 'Unix timestamp', 'value': 'unix'}
                ],
                description="Time format to return"
            )
        },
        'block_type': 'standard'
    }


@capture_logs
def execute(format: str = 'formatted', context=None, **kwargs) -> Dict[str, Any]:
    """
    Get current time in specified format.
    
    Args:
        format: Time format ('formatted' or 'unix')
        context: Execution context
        **kwargs: Additional parameters
        
    Returns:
        Dict with success status and current_time in output_data
    """
    print(f"[@block:get_current_time] Getting current time in format: {format}")
    
    try:
        now = datetime.now()
        
        # Format based on user selection
        if format == 'unix':
            current_time = int(time.time())
        else:  # formatted (default)
            # YYMMDD-HH:MM:SS.ms format
            ms = int(now.microsecond / 1000)
            current_time = now.strftime(f'%y%m%d-%H:%M:%S.{ms:03d}')
        
        print(f"[@block:get_current_time] Current time: {current_time}")
        
        return {
            'result_success': 0,  # 0=success, 1=failure, -1=error
            'message': f'Current time: {current_time}',
            'output_data': {
                'current_time': current_time
            }
        }
        
    except Exception as e:
        error_msg = f"Error getting current time: {str(e)}"
        print(f"[@block:get_current_time] ERROR: {error_msg}")
        
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg
        }

