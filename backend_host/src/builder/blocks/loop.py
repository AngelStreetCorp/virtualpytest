"""
Loop Block

Execute a block or group of blocks multiple times.
"""

from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration"""
    return {
        'command': 'loop',
        'label': 'Loop',  # Short name for toolbox
        'description': 'Execute blocks multiple times',  # Longer description
        'params': {
            'start_block': create_param(
                ParamType.STRING,
                required=True,
                default='',
                description="Block ID where loop starts",
                placeholder="Enter start block ID"
            ),
            'end_block': create_param(
                ParamType.STRING,
                required=True,
                default='',
                description="Block ID where loop ends",
                placeholder="Enter end block ID"
            ),
            'iterations': create_param(
                ParamType.NUMBER,
                required=True,
                default=1,
                description="Number of iterations",
                placeholder="Enter number of iterations",
                min=1,
                max=10000
            ),
            'timeout': create_param(
                ParamType.NUMBER,
                required=False,
                default=300,
                description="Maximum time for entire loop (seconds)",
                placeholder="Enter timeout in seconds",
                min=1,
                max=3600
            ),
            'break_condition': create_param(
                ParamType.STRING,
                required=False,
                default='',
                description="Condition to break loop early (Python expression)",
                placeholder="Enter break condition (e.g., variable > 10)"
            ),
            'loop_variable': create_param(
                ParamType.STRING,
                required=False,
                default='i',
                description="Variable name for current iteration index",
                placeholder="Enter variable name (e.g., i)"
            )
        },
        'block_type': 'standard'
    }


@capture_logs
def execute(start_block: str = '', end_block: str = '', iterations: int = 1, 
            timeout: float = 300, break_condition: str = '', loop_variable: str = 'i',
            context=None, **kwargs) -> Dict[str, Any]:
    """
    Execute loop block - placeholder for now.
    
    Args:
        start_block: Block ID where loop execution starts
        end_block: Block ID where loop execution ends
        iterations: Number of times to loop
        timeout: Maximum time for entire loop (seconds)
        break_condition: Python expression to break loop early
        loop_variable: Variable name to store current iteration
        context: Execution context
        **kwargs: Additional parameters
        
    Returns:
        Dict with success status
    """
    print(f"[@block:loop] Loop placeholder - start={start_block}, end={end_block}, "
          f"iterations={iterations}, timeout={timeout}s, break_condition='{break_condition}'")
    
    try:
        # TODO: Implement loop logic with child blocks
        # - Find blocks between start_block and end_block
        # - Execute them N times
        # - Evaluate break_condition each iteration
        # - Respect timeout
        
        if context:
            context.variables = context.variables or {}
            context.variables['_loop_start'] = start_block
            context.variables['_loop_end'] = end_block
            context.variables['_loop_iterations'] = iterations
            context.variables['_loop_timeout'] = timeout
            context.variables['_loop_break_condition'] = break_condition
            context.variables[loop_variable] = 0  # Current iteration
        
        return {
            'result_success': 0,  # 0=success, 1=failure, -1=error
            'message': f'Loop block placeholder (start={start_block}, end={end_block}, iterations={iterations})'
        }
        
    except Exception as e:
        error_msg = f"Error in loop block: {str(e)}"
        print(f"[@block:loop] ERROR: {error_msg}")
        
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg
        }

