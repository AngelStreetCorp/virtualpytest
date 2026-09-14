"""
Auto-generate tool definitions from implementation code.

Best Practice: Single source of truth - function signatures generate schemas.
No manual maintenance required.
"""

import inspect
from typing import Dict, Any, List, get_type_hints, get_origin, get_args
import re


def parse_docstring(docstring: str) -> Dict[str, Any]:
    """
    Parse docstring to extract description and parameter docs.
    Handles MCP pattern: params: {'key': type (REQUIRED/OPTIONAL - desc)}
    
    Returns:
        {
            'description': 'Main description',
            'example': 'Example usage line',
            'params': {
                'param_name': {
                    'description': 'param description',
                    'type': 'string',
                    'required': True/False
                }
            }
        }
    """
    if not docstring:
        return {'description': '', 'params': {}, 'example': ''}
    
    lines = docstring.strip().split('\n')
    description_lines = []
    params = {}
    example = ''
    
    in_args_section = False
    in_params_dict = False
    
    for line in lines:
        stripped = line.strip()
        
        # Extract example from description
        if 'Example:' in stripped:
            example_match = re.search(r'Example:\s*(.+)', stripped)
            if example_match:
                example = example_match.group(1).strip()
                continue
        
        # Check for Args:/params: section
        if stripped.lower() in ['args:', 'arguments:', 'parameters:', 'params:']:
            in_args_section = True
            continue
        
        # Check if we're in params dict definition
        if in_args_section and 'params:' in stripped and '{' in stripped:
            in_params_dict = True
            continue
        
        # End of params dict
        if in_params_dict and '}' in stripped:
            in_params_dict = False
            in_args_section = False
            continue
        
        # Check for Returns: or other sections
        if stripped.lower().startswith(('returns:', 'return:', 'raises:', 'notes:', 'note:')):
            in_args_section = False
            in_params_dict = False
            continue
        
        # Parse params dict entries: 'key_name': type (REQUIRED/OPTIONAL - description) or (REQUIRED) - description
        if in_params_dict:
            # Try pattern 1: 'param': type (REQUIRED - description)
            param_match = re.match(r"[\'\"](\w+)[\'\"]:\s*([^\s]+)\s*\((REQUIRED|OPTIONAL)\s*-\s*(.+)\)", stripped)
            if not param_match:
                # Try pattern 2: 'param': type (REQUIRED) - description
                param_match = re.match(r"[\'\"](\w+)[\'\"]:\s*([^\s]+)\s*\((REQUIRED|OPTIONAL)\)\s*-\s*(.+)", stripped)
            
            if param_match:
                param_name = param_match.group(1)
                param_type = param_match.group(2).lower()
                is_required = param_match.group(3) == 'REQUIRED'
                param_desc = param_match.group(4).strip(' ,)')
                
                # Map Python types to JSON schema types
                type_map = {
                    'str': 'string',
                    'int': 'integer',
                    'bool': 'boolean',
                    'dict': 'object',
                    'list': 'array'
                }

                # Handle complex types like List[Dict]
                if '[' in param_type and ']' in param_type:
                    if param_type.startswith('List[') or param_type.startswith('list['):
                        json_type = 'array'
                    elif param_type.startswith('Dict[') or param_type.startswith('dict['):
                        json_type = 'object'
                    else:
                        json_type = 'string'  # fallback for unknown complex types
                else:
                    json_type = type_map.get(param_type, 'string')
                
                params[param_name] = {
                    'description': param_desc,
                    'type': json_type,
                    'required': is_required
                }
        elif not in_args_section:
            # Main description (before Args:)
            if stripped and not stripped.startswith(('Args:', 'Returns:', 'Example:')):
                description_lines.append(stripped)
    
    # Build description
    description = ' '.join(description_lines)
    
    # Add example to description if found
    if example:
        description = f"{description}\n\nExample: {example}"
    
    return {'description': description, 'params': params, 'example': example}


def python_type_to_json_schema(py_type) -> Dict[str, Any]:
    """Convert Python type hint to JSON schema type."""
    
    # Handle None/Optional
    origin = get_origin(py_type)
    if origin is type(None):
        return {"type": "null"}
    
    # Handle Optional[X] (Union[X, None])
    if origin is type(None) or (hasattr(py_type, '__origin__') and py_type.__origin__ is type(None)):
        return {"type": "null"}
    
    # Handle basic types
    type_mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }
    
    # Direct type mapping
    if py_type in type_mapping:
        return {"type": type_mapping[py_type]}
    
    # Handle Dict[str, Any] etc
    if origin in (dict, Dict):
        return {"type": "object"}
    
    # Handle List[X] etc
    if origin in (list, List):
        return {"type": "array"}
    
    # Default to string for unknown types
    return {"type": "string"}


def generate_tool_definition(func, tool_name: str = None, description_override: str = None) -> Dict[str, Any]:
    """
    Auto-generate Anthropic tool definition from function docstring.
    Supports MCP pattern: def tool(params: Dict[str, Any])
    
    Args:
        func: The tool function to generate definition for
        tool_name: Override tool name (default: function name)
        description_override: Override description (default: from docstring)
    
    Returns:
        Anthropic tool definition dict
    """
    
    # Parse docstring (contains params dict definition)
    doc_info = parse_docstring(func.__doc__)
    
    # Build tool definition
    tool_def = {
        "name": tool_name or func.__name__,
        "description": description_override or doc_info['description'] or f"Execute {func.__name__}",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
    
    # Process parameters from docstring
    for param_name, param_info in doc_info['params'].items():
        # Add to properties
        tool_def["inputSchema"]["properties"][param_name] = {
            "type": param_info['type'],
            "description": param_info['description']
        }
        
        # Add to required if marked as REQUIRED
        if param_info['required']:
            tool_def["inputSchema"]["required"].append(param_name)
    
    return tool_def


def generate_from_class(tool_class, method_names: List[str] = None) -> List[Dict[str, Any]]:
    """
    Generate tool definitions from a class with tool methods.
    Works without instantiating the class - just reads method docstrings.
    
    Args:
        tool_class: Class containing tool methods
        method_names: List of method names to generate (default: all public methods)
    
    Returns:
        List of tool definitions
    """
    tools = []
    
    # Get all methods if not specified
    if method_names is None:
        method_names = [name for name in dir(tool_class) 
                       if not name.startswith('_') 
                       and callable(getattr(tool_class, name))
                       and name not in ('format_api_response',)]
    
    # Get methods from class (no instantiation needed - just read docstrings)
    for method_name in method_names:
        if hasattr(tool_class, method_name):
            method = getattr(tool_class, method_name)
            tool_def = generate_tool_definition(method, tool_name=method_name)
            tools.append(tool_def)
    
    return tools


# Example usage for your tools:
"""
from backend_server.src.mcp.tools.control_tools import ControlTools
from backend_server.src.mcp.tool_definitions.auto_generator import generate_from_class

# Auto-generate control tool definitions
control_definitions = generate_from_class(ControlTools, ['take_control', 'release_control'])
"""

