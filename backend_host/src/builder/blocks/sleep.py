"""
Sleep Block

Wait for specified duration (simple delay).
"""

import time
from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration.

    The command stays 'sleep' (the registry/executor key), but it is presented
    as 'Wait' and its duration is in MILLISECONDS — consistent with the rest of
    the platform (timeouts etc. are all ms).
    """
    return {
        'command': 'sleep',
        'label': 'Wait',  # Short name for toolbox
        'description': 'Wait for a duration',  # Longer description
        'params': {
            'duration': create_param(
                ParamType.NUMBER,
                required=True,
                default=1000,
                description="Duration to wait (ms)",
                placeholder="Enter duration in milliseconds",
                min=0,
                max=600000  # 10 minutes
            )
        },
        'block_type': 'standard'
    }


@capture_logs
def execute(duration: float = 1000, context=None, **kwargs) -> Dict[str, Any]:
    """
    Execute the wait block - a simple delay.

    Args:
        duration: Time to wait in MILLISECONDS
        context: Execution context (unused)
        **kwargs: Additional parameters

    Returns:
        Dict with success status
    """
    print(f"[@block:sleep] Waiting for {duration}ms")

    try:
        time.sleep(max(0.0, float(duration) / 1000.0))

        print(f"[@block:sleep] Wait completed")

        return {
            'result_success': 0,  # 0=success, 1=failure, -1=error
            'message': f'Waited for {duration}ms'
        }

    except Exception as e:
        error_msg = f"Error during wait: {str(e)}"
        print(f"[@block:sleep] ERROR: {error_msg}")

        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg
        }

