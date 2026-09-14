"""Integer Evaluator - Compare two integers"""


def evaluate(left: int, right: int, condition: str) -> bool:
    """
    Evaluate integer condition.
    
    Args:
        left: Left integer operand
        right: Right integer operand
        condition: Condition type (greater_than, less_than, etc.)
        
    Returns:
        Boolean result of comparison
        
    Raises:
        ValueError: If condition is unknown
    """
    if condition == 'greater_than':
        return left > right
    elif condition == 'less_than':
        return left < right
    elif condition == 'greater_equal':
        return left >= right
    elif condition == 'less_equal':
        return left <= right
    elif condition == 'equal':
        return left == right
    else:
        raise ValueError(f"Unknown int condition: {condition}")


def get_conditions():
    """Return available conditions for int type"""
    return {
        'greater_than': {'label': 'Greater than (>)', 'value': 'greater_than', 'output_type': 'bool'},
        'less_than': {'label': 'Less than (<)', 'value': 'less_than', 'output_type': 'bool'},
        'greater_equal': {'label': 'Greater or equal (>=)', 'value': 'greater_equal', 'output_type': 'bool'},
        'less_equal': {'label': 'Less or equal (<=)', 'value': 'less_equal', 'output_type': 'bool'},
        'equal': {'label': 'Equal (=)', 'value': 'equal', 'output_type': 'bool'}
    }



