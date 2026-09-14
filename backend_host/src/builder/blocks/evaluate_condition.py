"""
Evaluate Condition Block

Evaluate a condition and branch execution flow based on operand types and conditions.

Supports:
- int: >, <, >=, <=, =
- str: equal, contains, dont_contain
- list: equal, contain, dont_contain, index_of
- dict: equal, contain_key, contain_value, dont_contain_key, dont_contain_value, index_of_key

Returns:
- result_success: 0 (success), 1 (failure), -1 (error)
- error_msg: Error message if any
- result_output: The evaluation result (bool, int, or other)
"""

from typing import Dict, Any
from backend_host.src.builder.decorators import capture_logs
from shared.src.lib.schemas.param_types import create_param, ParamType
from backend_host.src.builder.blocks.evaluate_condition_handlers import (
    evaluate_int,
    evaluate_str,
    evaluate_list,
    evaluate_dict,
)
from backend_host.src.builder.blocks.evaluate_condition_handlers.operand_resolver import (
    resolve_operand,
    validate_operand_type,
)
from backend_host.src.builder.blocks.evaluate_condition_handlers import (
    int_evaluator,
    str_evaluator,
    list_evaluator,
    dict_evaluator,
)


# Map operand types to evaluators
EVALUATORS = {
    'int': evaluate_int,
    'str': evaluate_str,
    'list': evaluate_list,
    'dict': evaluate_dict,
}

# Map operand types to condition getters (for metadata)
CONDITION_GETTERS = {
    'int': int_evaluator.get_conditions,
    'str': str_evaluator.get_conditions,
    'list': list_evaluator.get_conditions,
    'dict': dict_evaluator.get_conditions,
}

# Build combined conditions for get_block_info
def _get_all_conditions():
    """Combine all conditions from all evaluators"""
    all_conditions = {}
    for operand_type, getter in CONDITION_GETTERS.items():
        all_conditions[operand_type] = getter()
    return all_conditions

OPERAND_CONDITIONS = _get_all_conditions()


def get_block_info() -> Dict[str, Any]:
    """Return block metadata for registration"""
    # Build choices for condition dropdown grouped by operand_type
    condition_choices = {}
    for operand_type, getter in CONDITION_GETTERS.items():
        conditions = getter()
        # Convert dict to list of choices
        condition_choices[operand_type] = [
            {'label': cond_data['label'], 'value': cond_data['value']}
            for cond_data in conditions.values()
        ]
    
    return {
        'command': 'evaluate_condition',
        'label': 'Evaluate Condition',
        'description': 'Evaluate condition with typed operands and dynamic conditions',
        'params': {
            'operand_type': create_param(
                ParamType.ENUM,
                required=True,
                default='int',
                choices=[
                    {'label': 'Integer', 'value': 'int'},
                    {'label': 'String', 'value': 'str'},
                    {'label': 'List', 'value': 'list'},
                    {'label': 'Dictionary', 'value': 'dict'}
                ],
                description="Type"
            ),
            'condition': create_param(
                ParamType.ENUM,
                required=True,
                default='equal',
                choices=condition_choices['int'],  # Default to int conditions
                description="Condition"
            ),
            'left_operand': create_param(
                ParamType.STRING,
                required=True,
                default='',
                description="Left operand",
                placeholder="Enter value or {variable_name}"
            ),
            'right_operand': create_param(
                ParamType.STRING,
                required=True,
                default='',
                description="Right operand",
                placeholder="Enter value or {variable_name}"
            )
        },
        'block_type': 'standard',
        'output_schema': {
            'result_success': 'int',  # 0=success, 1=failure, -1=error
            'error_msg': 'str',
            'result_output': 'any'  # bool, int, or other depending on condition
        }
    }


@capture_logs
def execute(
    operand_type: str = 'int',
    condition: str = 'equal',
    left_operand: str = '',
    right_operand: str = '',
    context=None,
    **kwargs
) -> Dict[str, Any]:
    """
    Execute condition evaluation by routing to appropriate evaluator.
    
    Args:
        operand_type: Type of operands (int, str, list, dict)
        condition: Condition to evaluate (depends on operand_type)
        left_operand: Left operand (variable reference or literal)
        right_operand: Right operand (variable reference or literal)
        context: Execution context with variables
        **kwargs: Additional parameters
        
    Returns:
        Dict with:
        - result_success: 0 (success), 1 (failure), -1 (error)
        - error_msg: Error message if error occurred
        - result_output: The evaluation result (bool or int)
    """
    print(f"[@block:evaluate_condition] Evaluating: type={operand_type}, condition={condition}, "
          f"left={left_operand}, right={right_operand}")
    
    try:
        # Validate inputs
        if not left_operand or not right_operand:
            return {
                'result_success': -1,
                'error_msg': 'Both left_operand and right_operand are required',
                'result_output': None
            }
        
        if operand_type not in EVALUATORS:
            return {
                'result_success': -1,
                'error_msg': f"Invalid operand_type: {operand_type}",
                'result_output': None
            }
        
        if condition not in OPERAND_CONDITIONS[operand_type]:
            return {
                'result_success': -1,
                'error_msg': f"Invalid condition '{condition}' for type '{operand_type}'",
                'result_output': None
            }
        
        # Resolve operands
        try:
            left_value = resolve_operand(left_operand, context, operand_type)
            
            # Right operand resolution depends on condition
            # For membership/search operations, right can be any type (try as-is first)
            flexible_conditions = [
                'contain', 'dont_contain', 'index_of',
                'contain_key', 'contain_value', 'dont_contain_key', 'dont_contain_value', 'index_of_key'
            ]
            
            if condition in flexible_conditions:
                # Try to resolve as variable first, then as string literal
                try:
                    right_value = resolve_operand(right_operand, context, 'str')
                except ValueError:
                    # If fails, try as the declared operand type
                    right_value = resolve_operand(right_operand, context, operand_type)
            else:
                # For comparison operations, must match declared type
                right_value = resolve_operand(right_operand, context, operand_type)
                
        except ValueError as e:
            return {
                'result_success': -1,
                'error_msg': f"Operand resolution error: {str(e)}",
                'result_output': None
            }
        
        # Validate left operand type
        if not validate_operand_type(left_value, operand_type):
            return {
                'result_success': -1,
                'error_msg': f"Left operand type mismatch: expected {operand_type}, got {type(left_value).__name__}",
                'result_output': None
            }
        
        # Right operand type validation depends on condition
        # For membership/search operations, right can be any type
        flexible_conditions = [
            'contain', 'dont_contain', 'index_of',
            'contain_key', 'contain_value', 'dont_contain_key', 'dont_contain_value', 'index_of_key'
        ]
        
        if condition not in flexible_conditions:
            if not validate_operand_type(right_value, operand_type):
                return {
                    'result_success': -1,
                    'error_msg': f"Right operand type mismatch: expected {operand_type}, got {type(right_value).__name__}",
                    'result_output': None
                }
        
        # Route to appropriate evaluator
        evaluator = EVALUATORS[operand_type]
        result_output = evaluator(left_value, right_value, condition)
        
        # Store result in context
        if context:
            context.variables = context.variables or {}
            context.variables['result_output'] = result_output
            context.variables['result_success'] = 0
            context.variables['error_msg'] = ''
        
        # Determine success code based on result
        # For boolean results: True = success (0), False = failure (1)
        # For integer results (index): >= 0 = success (0), -1 = failure (1)
        result_success = 0
        if isinstance(result_output, bool):
            result_success = 0 if result_output else 1
        elif isinstance(result_output, int):
            result_success = 0 if result_output >= 0 else 1
        
        print(f"[@block:evaluate_condition] Result: {result_output} (success_code={result_success})")
        
        return {
            'result_success': result_success,
            'error_msg': '',
            'result_output': result_output
        }
        
    except Exception as e:
        error_msg = f"Unexpected error evaluating condition: {str(e)}"
        print(f"[@block:evaluate_condition] ERROR: {error_msg}")
        
        if context:
            context.variables = context.variables or {}
            context.variables['result_success'] = -1
            context.variables['error_msg'] = error_msg
            context.variables['result_output'] = None
        
        return {
            'result_success': -1,
            'error_msg': error_msg,
            'result_output': None
        }
