"""
Input Validator for MCP Tools

Validates tool arguments against JSON Schema before execution.
Prevents invalid inputs from reaching backend APIs.
"""

from typing import Dict, Any, Tuple, Optional
from jsonschema import validate, ValidationError, SchemaError
import logging


class InputValidator:
    """Validates tool inputs against JSON Schema"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate tool arguments against JSON Schema
        
        Args:
            tool_name: Name of the tool being called
            arguments: Arguments provided by user
            schema: JSON Schema to validate against (inputSchema from tool definition)
            
        Returns:
            Tuple of (is_valid, error_message)
            - (True, None) if valid
            - (False, error_message) if invalid
        """
        try:
            # Validate arguments against schema
            validate(instance=arguments, schema=schema)
            self.logger.debug(f"Validation passed for tool: {tool_name}")
            return True, None
            
        except ValidationError as e:
            # Validation failed - construct user-friendly error message
            error_path = " -> ".join(str(p) for p in e.path) if e.path else "root"
            error_msg = f"Invalid input for '{error_path}': {e.message}"
            
            self.logger.warning(f"Validation failed for {tool_name}: {error_msg}")
            return False, error_msg
            
        except SchemaError as e:
            # Schema itself is invalid (shouldn't happen in production)
            error_msg = f"Invalid schema for tool {tool_name}: {e.message}"
            self.logger.error(error_msg)
            return False, error_msg
            
        except Exception as e:
            # Unexpected error during validation
            error_msg = f"Validation error: {str(e)}"
            self.logger.error(f"Unexpected validation error for {tool_name}: {e}", exc_info=True)
            return False, error_msg
    
    def validate_required_fields(
        self,
        arguments: Dict[str, Any],
        required_fields: list
    ) -> Tuple[bool, Optional[str]]:
        """
        Quick validation of required fields (faster than full schema validation)
        
        Args:
            arguments: Arguments provided
            required_fields: List of required field names
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        missing_fields = [field for field in required_fields if field not in arguments]
        
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            return False, error_msg
        
        return True, None
    
    def sanitize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize arguments by removing None values and empty strings
        
        Args:
            arguments: Raw arguments
            
        Returns:
            Sanitized arguments dict
        """
        return {
            k: v for k, v in arguments.items()
            if v is not None and v != ''
        }

