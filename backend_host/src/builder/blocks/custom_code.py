"""
Custom Code Block

Allows users to write and execute custom Python code directly in the UI.

Security: Runs in same process with access to context and device.
Use-case: Advanced users can write custom logic without creating new block files.
"""

from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration"""
    return {
        'command': 'custom_code',
        'label': 'Custom Code',  # Short name for toolbox
        'description': 'Execute custom Python code',  # Longer description
        'params': {
            'code': create_param(
                ParamType.STRING,
                required=True,
                default='# Write your Python code here\n# Available variables:\n#   - context: Execution context\n#   - device: Device instance\n#\n# Example:\n# device.remote_controller.press_key("HOME")\n# context.metadata["custom_value"] = "hello"\n',
                description="Python code to execute",
                placeholder="Enter Python code"
            )
        },
        'block_type': 'standard'
    }


@capture_logs
def execute(code: str = '', context=None, **kwargs) -> Dict[str, Any]:
    """
    Execute user-provided Python code.
    
    Available in code execution scope:
    - context: Execution context (variables, metadata, device)
    - device: Device instance (controllers, actions, etc.)
    
    Args:
        code: Python code to execute
        context: Execution context
        **kwargs: Additional parameters
        
    Returns:
        Dict with success status and any return value
    """
    print(f"[@block:custom_code] Executing custom Python code ({len(code)} chars)")
    
    if not code or not code.strip():
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': 'No code provided'
        }
    
    try:
        # Get device from context
        device = getattr(context, 'selected_device', None) if context else None
        
        # Prepare execution scope with context and device
        exec_globals = {
            'context': context,
            'device': device,
            '__builtins__': __builtins__,  # Keep Python built-ins available
        }
        
        # Execute the code
        exec(code, exec_globals)
        
        # Check if code set a return value
        return_value = exec_globals.get('result', None)
        
        # 🔍 DEBUG: Log context.metadata after code execution
        if context and hasattr(context, 'metadata'):
            print(f"[@block:custom_code] 🔍 context.metadata after execution:")
            print(f"  - type: {type(context.metadata)}")
            print(f"  - keys: {list(context.metadata.keys()) if isinstance(context.metadata, dict) else 'N/A'}")
            print(f"  - value: {context.metadata}")
        else:
            print(f"[@block:custom_code] ⚠️ context.metadata not available")
        
        print(f"[@block:custom_code] Execution completed")
        if return_value:
            print(f"[@block:custom_code] Return value: {return_value}")
        
        return {
            'result_success': 0,  # 0=success, 1=failure, -1=error
            'message': 'Custom code executed successfully',
            'result': return_value
        }
        
    except SyntaxError as e:
        error_msg = f"Syntax error in code: {str(e)}"
        print(f"[@block:custom_code] ERROR: {error_msg}")
        print(f"[@block:custom_code] Line {e.lineno}: {e.text}")
        
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg,
            'line': e.lineno,
            'details': str(e)
        }
        
    except Exception as e:
        error_msg = f"Error executing code: {str(e)}"
        print(f"[@block:custom_code] ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        
        return {
            'result_success': -1,  # 0=success, 1=failure, -1=error
            'message': error_msg,
            'details': traceback.format_exc()
        }

