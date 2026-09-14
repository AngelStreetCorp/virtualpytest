"""
Common Operation Block

Execute common operations like string manipulation, math, etc.
"""

from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration"""
    return {
        'command': 'common_operation',
        'label': 'Common Operation',  # Short name for toolbox
        'description': 'Perform common operations',  # Longer description
        'params': {
            'operation': create_param(
                ParamType.ENUM,
                required=True,
                default='add',
                choices=[
                    {'label': 'Add numbers', 'value': 'add'},
                    {'label': 'Subtract numbers', 'value': 'subtract'},
                    {'label': 'Multiply numbers', 'value': 'multiply'},
                    {'label': 'Divide numbers', 'value': 'divide'},
                    {'label': 'Concatenate strings', 'value': 'concat'},
                    {'label': 'Split string', 'value': 'split'},
                    {'label': 'Replace text', 'value': 'replace'},
                    {'label': 'Convert to uppercase', 'value': 'upper'},
                    {'label': 'Convert to lowercase', 'value': 'lower'}
                ],
                description="Operation to perform"
            ),
            'input_a': create_param(
                ParamType.STRING,
                required=True,
                default='',
                description="First input value",
                placeholder="Enter first value"
            ),
            'input_b': create_param(
                ParamType.STRING,
                required=False,
                default='',
                description="Second input value (if needed)",
                placeholder="Enter second value"
            ),
            'output_variable': create_param(
                ParamType.STRING,
                required=False,
                default='result',
                description="Variable name to store result",
                placeholder="Enter variable name"
            )
        },
        'block_type': 'standard'
    }


@capture_logs
def execute(operation: str = 'add', input_a: str = '', input_b: str = '', 
            output_variable: str = 'result', context=None, **kwargs) -> Dict[str, Any]:
    """
    Execute common operation - placeholder for now.
    
    Args:
        operation: Operation type
        input_a: First input
        input_b: Second input
        output_variable: Variable to store result
        context: Execution context
        **kwargs: Additional parameters
        
    Returns:
        Dict with success status and result
    """
    print(f"[@block:common_operation] Operation placeholder - op={operation}, a={input_a}, b={input_b}")
    
    try:
        # TODO: Implement operation logic
        # For now, just return placeholder result
        result = f"{input_a} {operation} {input_b}"
        
        if context:
            context.variables = context.variables or {}
            context.variables[output_variable] = result
        
        return {
            'result_success': 0,  # 0=success, 1=failure, -1=error
            'result': result,
            'message': f'Common operation placeholder (result={result})'
        }
        
    except Exception as e:
        error_msg = f"Error in common operation: {str(e)}"
        print(f"[@block:common_operation] ERROR: {error_msg}")
        
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg
        }

