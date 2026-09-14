"""String Evaluator - Compare two strings"""


def evaluate(left: str, right: str, condition: str) -> bool:
    """
    Evaluate string condition.
    
    Args:
        left: Left string operand
        right: Right string operand
        condition: Condition type (equal, contains, etc.)
        
    Returns:
        Boolean result of comparison
        
    Raises:
        ValueError: If condition is unknown
    """
    if condition == 'equal':
        return left == right
    elif condition == 'contains':
        return right in left
    elif condition == 'dont_contain':
        return right not in left
    else:
        raise ValueError(f"Unknown str condition: {condition}")


def get_conditions():
    """Return available conditions for str type"""
    return {
        'equal': {'label': 'Equal', 'value': 'equal', 'output_type': 'bool'},
        'contains': {'label': 'Contains', 'value': 'contains', 'output_type': 'bool'},
        'dont_contain': {'label': 'Does not contain', 'value': 'dont_contain', 'output_type': 'bool'}
    }



