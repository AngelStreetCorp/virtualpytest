"""Dict Evaluator - Compare dicts or check keys/values"""

from typing import Any, Union, Dict


def evaluate(left: Dict, right: Any, condition: str) -> Union[bool, int]:
    """
    Evaluate dict condition.
    
    Args:
        left: Left dict operand
        right: Right operand (can be any type for key/value checks)
        condition: Condition type (equal, contain_key, etc.)
        
    Returns:
        Boolean result or integer index
        
    Raises:
        ValueError: If condition is unknown
    """
    if condition == 'equal':
        return left == right
    elif condition == 'contain_key':
        return right in left
    elif condition == 'contain_value':
        return right in left.values()
    elif condition == 'dont_contain_key':
        return right not in left
    elif condition == 'dont_contain_value':
        return right not in left.values()
    elif condition == 'index_of_key':
        # Get index position of key in dict (insertion order in Python 3.7+)
        keys_list = list(left.keys())
        try:
            return keys_list.index(right)
        except ValueError:
            return -1  # Not found
    else:
        raise ValueError(f"Unknown dict condition: {condition}")


def get_conditions():
    """Return available conditions for dict type"""
    return {
        'equal': {'label': 'Equal', 'value': 'equal', 'output_type': 'bool'},
        'contain_key': {'label': 'Contains key', 'value': 'contain_key', 'output_type': 'bool'},
        'contain_value': {'label': 'Contains value', 'value': 'contain_value', 'output_type': 'bool'},
        'dont_contain_key': {'label': 'Does not contain key', 'value': 'dont_contain_key', 'output_type': 'bool'},
        'dont_contain_value': {'label': 'Does not contain value', 'value': 'dont_contain_value', 'output_type': 'bool'},
        'index_of_key': {'label': 'Index of key', 'value': 'index_of_key', 'output_type': 'int'}
    }



