"""List Evaluator - Compare lists or check membership"""

from typing import Any, Union, List


def evaluate(left: List, right: Any, condition: str) -> Union[bool, int]:
    """
    Evaluate list condition.
    
    Args:
        left: Left list operand
        right: Right operand (can be any type for membership checks)
        condition: Condition type (equal, contain, etc.)
        
    Returns:
        Boolean result or integer index
        
    Raises:
        ValueError: If condition is unknown
    """
    if condition == 'equal':
        return left == right
    elif condition == 'contain':
        return right in left
    elif condition == 'dont_contain':
        return right not in left
    elif condition == 'index_of':
        try:
            return left.index(right)
        except ValueError:
            return -1  # Not found
    else:
        raise ValueError(f"Unknown list condition: {condition}")


def get_conditions():
    """Return available conditions for list type"""
    return {
        'equal': {'label': 'Equal', 'value': 'equal', 'output_type': 'bool'},
        'contain': {'label': 'Contains', 'value': 'contain', 'output_type': 'bool'},
        'dont_contain': {'label': 'Does not contain', 'value': 'dont_contain', 'output_type': 'bool'},
        'index_of': {'label': 'Index of', 'value': 'index_of', 'output_type': 'int'}
    }



