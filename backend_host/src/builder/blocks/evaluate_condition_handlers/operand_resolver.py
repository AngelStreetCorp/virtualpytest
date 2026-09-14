"""Operand Resolver - Resolve variables or parse literal values"""

import re
from typing import Any


def resolve_operand(operand_str: str, context, operand_type: str) -> Any:
    """
    Resolve operand from string - either variable reference or literal value.
    
    Variable reference format: {variable_name}
    Literal values: parsed based on operand_type
    
    Args:
        operand_str: The operand string
        context: Execution context with variables
        operand_type: Expected type (int, str, list, dict)
        
    Returns:
        Resolved value with correct type
        
    Raises:
        ValueError: If operand cannot be resolved or converted
    """
    operand_str = operand_str.strip()
    
    # Check for variable reference: {variable_name}
    var_match = re.match(r'^\{(.+?)\}$', operand_str)
    if var_match:
        var_name = var_match.group(1).strip()
        if not context or not hasattr(context, 'variables') or not context.variables:
            raise ValueError(f"Variable '{var_name}' not found in context")
        
        if var_name not in context.variables:
            raise ValueError(f"Variable '{var_name}' not found in context")
        
        value = context.variables[var_name]
        print(f"[@evaluate_condition] Resolved variable '{var_name}' = {value} (type: {type(value).__name__})")
        return value
    
    # Parse literal value based on operand_type
    try:
        if operand_type == 'int':
            return int(operand_str)
        elif operand_type == 'str':
            # Remove surrounding quotes if present
            if (operand_str.startswith('"') and operand_str.endswith('"')) or \
               (operand_str.startswith("'") and operand_str.endswith("'")):
                return operand_str[1:-1]
            return operand_str
        elif operand_type == 'list':
            import ast
            return ast.literal_eval(operand_str)
        elif operand_type == 'dict':
            import ast
            return ast.literal_eval(operand_str)
    except Exception as e:
        raise ValueError(f"Failed to parse operand '{operand_str}' as {operand_type}: {str(e)}")
    
    return operand_str


def validate_operand_type(value: Any, expected_type: str) -> bool:
    """Validate that value matches expected type"""
    type_map = {
        'int': int,
        'str': str,
        'list': list,
        'dict': dict
    }
    expected_python_type = type_map.get(expected_type)
    return isinstance(value, expected_python_type)



