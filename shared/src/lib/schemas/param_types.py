"""
Parameter Type Definitions

Defines standard parameter types for verification blocks, actions, and builder blocks.
This provides a consistent schema for defining what parameters a block accepts.

Usage:
    from shared.src.lib.schemas.param_types import ParamType, create_param

    # Define a verification with typed params
    {
        "command": "waitForTextToAppear",
        "params": {
            "text": create_param(ParamType.STRING, required=True, default=""),
            "timeout": create_param(ParamType.NUMBER, required=False, default=0),
            "area": create_param(ParamType.AREA, required=False, default=None)
        }
    }
"""

from enum import Enum
from typing import Any, Dict, Optional, List, Union


class ParamType(str, Enum):
    """Standard parameter types for verification/action blocks."""
    
    # Basic types
    STRING = "string"           # Text input
    NUMBER = "number"           # Numeric input (int or float)
    BOOLEAN = "boolean"         # True/False checkbox
    
    # Complex types
    AREA = "area"               # Screen area: {x, y, width, height}
    ARRAY = "array"             # List of values
    OBJECT = "object"           # Nested object/dict
    
    # Special types
    REFERENCE = "reference"     # Reference to saved element/text
    COLOR = "color"             # Color picker
    FILE = "file"               # File path/upload
    ENUM = "enum"               # Dropdown with fixed choices


class OutputType(str, Enum):
    """Types of outputs a block can produce."""
    
    STRING = "string"           # Text output
    NUMBER = "number"           # Numeric output
    BOOLEAN = "boolean"         # True/False output
    OBJECT = "object"           # Complex object/dict output
    ARRAY = "array"             # List output


def create_output(
    name: str,
    output_type: OutputType,
    description: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Create an output definition.
    
    Args:
        name: Output variable name (e.g., 'parsed_data', 'ocr_text')
        output_type: Type of output
        description: Human-readable description
        **kwargs: Additional options
    
    Returns:
        Dict representation of output definition
    
    Example:
        create_output('parsed_data', OutputType.OBJECT, description="Parsed key-value pairs")
    """
    return {
        "name": name,
        "type": output_type.value,
        "description": description,
        **kwargs
    }


class ParamDefinition:
    """
    Definition of a single parameter.
    
    Attributes:
        type: Parameter type (ParamType enum)
        required: Whether parameter is required
        default: Default value if not provided
        description: Human-readable description
        choices: List of valid choices (for ENUM type)
        min: Minimum value (for NUMBER type)
        max: Maximum value (for NUMBER type)
        placeholder: Placeholder text for input fields
        nested_schema: Schema for nested OBJECT or ARRAY types
    """
    
    def __init__(
        self,
        type: ParamType,
        required: bool = False,
        default: Any = None,
        description: str = "",
        choices: Optional[List[Any]] = None,
        min: Optional[Union[int, float]] = None,
        max: Optional[Union[int, float]] = None,
        placeholder: str = "",
        nested_schema: Optional[Dict] = None
    ):
        self.type = type
        self.required = required
        self.default = default
        self.description = description
        self.choices = choices
        self.min = min
        self.max = max
        self.placeholder = placeholder
        self.nested_schema = nested_schema
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization."""
        result = {
            "type": self.type.value,
            "required": self.required,
            "default": self.default,
        }
        
        if self.description:
            result["description"] = self.description
        
        if self.choices is not None:
            result["choices"] = self.choices
        
        if self.min is not None:
            result["min"] = self.min
        
        if self.max is not None:
            result["max"] = self.max
        
        if self.placeholder:
            result["placeholder"] = self.placeholder
        
        if self.nested_schema:
            result["nested_schema"] = self.nested_schema
        
        return result


def create_param(
    type: ParamType,
    required: bool = False,
    default: Any = None,
    description: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Create a parameter definition (convenience function).
    
    Args:
        type: Parameter type
        required: Whether parameter is required
        default: Default value
        description: Human-readable description
        **kwargs: Additional options (choices, min, max, etc.)
    
    Returns:
        Dict representation of parameter definition
    
    Example:
        create_param(ParamType.STRING, required=True, default="", placeholder="Enter text")
    """
    param = ParamDefinition(
        type=type,
        required=required,
        default=default,
        description=description,
        **kwargs
    )
    return param.to_dict()


# Common parameter definitions (reusable)
COMMON_PARAMS = {
    "text": create_param(
        ParamType.STRING,
        required=True,
        default="",
        description="Text to search for",
        placeholder="Enter text to detect"
    ),
    
    "timeout": create_param(
        ParamType.NUMBER,
        required=False,
        default=0,
        description="Maximum time to wait (seconds)"
    ),
    
    "area": create_param(
        ParamType.AREA,
        required=False,
        default=None,
        description="Screen area to search in",
        nested_schema={
            "x": {"type": "number", "min": 0},
            "y": {"type": "number", "min": 0},
            "width": {"type": "number", "min": 1},
            "height": {"type": "number", "min": 1}
        }
    ),
    
    "threshold": create_param(
        ParamType.NUMBER,
        required=False,
        default=0.8,
        description="Match threshold (0.0 to 1.0)",
        min=0.0,
        max=1.0
    ),
    
    "confidence": create_param(
        ParamType.NUMBER,
        required=False,
        default=0.8,
        description="Confidence level (0.0 to 1.0)",
        min=0.0,
        max=1.0
    ),
    
    "reference_name": create_param(
        ParamType.REFERENCE,
        required=False,
        default=None,
        description="Reference to saved element"
    ),
}


def extract_param_value(param_def: Dict[str, Any], provided_value: Any = None) -> Any:
    """
    Extract actual value from parameter definition.
    
    If provided_value is given, use it. Otherwise use default from param_def.
    
    Args:
        param_def: Parameter definition dict
        provided_value: Value provided by user (None if not provided)
    
    Returns:
        Actual value to use
    
    Example:
        param_def = create_param(ParamType.STRING, default="hello")
        extract_param_value(param_def, "world")  # Returns "world"
        extract_param_value(param_def, None)     # Returns "hello"
    """
    if provided_value is not None:
        return provided_value
    
    return param_def.get("default")


def validate_param_value(param_def: Dict[str, Any], value: Any) -> tuple[bool, str]:
    """
    Validate a parameter value against its definition.
    
    Args:
        param_def: Parameter definition dict
        value: Value to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Example:
        param_def = create_param(ParamType.NUMBER, min=0, max=10)
        validate_param_value(param_def, 5)   # Returns (True, "")
        validate_param_value(param_def, 15)  # Returns (False, "Value exceeds maximum")
    """
    param_type = param_def.get("type")
    required = param_def.get("required", False)
    
    # Check required
    if required and value is None:
        return False, "Parameter is required"
    
    # If not required and None, it's valid
    if not required and value is None:
        return True, ""
    
    # Type-specific validation
    if param_type == ParamType.NUMBER.value:
        if not isinstance(value, (int, float)):
            return False, "Value must be a number"
        
        min_val = param_def.get("min")
        max_val = param_def.get("max")
        
        if min_val is not None and value < min_val:
            return False, f"Value must be at least {min_val}"
        
        if max_val is not None and value > max_val:
            return False, f"Value must be at most {max_val}"
    
    elif param_type == ParamType.STRING.value:
        if not isinstance(value, str):
            return False, "Value must be a string"
    
    elif param_type == ParamType.BOOLEAN.value:
        if not isinstance(value, bool):
            return False, "Value must be a boolean"
    
    elif param_type == ParamType.ENUM.value:
        choices = param_def.get("choices", [])
        if value not in choices:
            return False, f"Value must be one of: {', '.join(map(str, choices))}"
    
    elif param_type == ParamType.AREA.value:
        if not isinstance(value, dict):
            return False, "Area must be an object"
        
        required_keys = ["x", "y", "width", "height"]
        for key in required_keys:
            if key not in value:
                return False, f"Area missing required key: {key}"
    
    return True, ""

