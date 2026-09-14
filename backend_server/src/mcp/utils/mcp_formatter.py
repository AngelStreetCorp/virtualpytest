"""
MCP Response Formatter

Converts backend API responses to MCP protocol format.
Handles success/error responses, categorizes errors, and formats content.
"""

import json
import re
from typing import Dict, Any, List
from enum import Enum


class ErrorCategory(Enum):
    """Error categories for better error handling"""
    VALIDATION = "validation_error"
    TIMEOUT = "timeout_error"
    NETWORK = "network_error"
    BACKEND = "backend_error"
    NOT_FOUND = "not_found_error"
    UNAUTHORIZED = "unauthorized_error"
    UNKNOWN = "unknown_error"


class MCPFormatter:
    """Utility for formatting responses in MCP protocol format"""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean text by removing/replacing problematic Unicode characters
        
        Removes:
        - Emoji modifiers (U+FE0F)
        - Box drawing characters (U+2500-U+257F)
        - Arrows and special symbols that appear as escape sequences
        
        Args:
            text: Raw text with Unicode characters
            
        Returns:
            Cleaned text with problematic characters removed
        """
        if not isinstance(text, str):
            return text
        
        # Remove emoji variation selectors (U+FE0F)
        text = text.replace('\uFE0F', '')
        
        # Replace box drawing characters with simple equivalents
        text = re.sub(r'[\u2500-\u257F]', '-', text)  # Box drawing → '-'
        
        # Replace arrows with simple text equivalents
        text = text.replace('\u2192', '->')  # → 
        text = text.replace('\u2190', '<-')  # ←
        text = text.replace('\u2191', '^')   # ↑
        text = text.replace('\u2193', 'v')   # ↓
        
        # Remove other common emoji/special characters used in logs
        text = text.replace('\u25B6', '>')   # ▶ (play button)
        text = text.replace('\u2705', '[OK]')  # ✅
        text = text.replace('\u274C', '[FAIL]')  # ❌
        text = text.replace('\u26A0', '[WARN]')  # ⚠
        text = text.replace('\u23F1', '[TIME]')  # ⏱
        text = text.replace('\u1F4F8', '[PHOTO]')  # 📸
        
        return text
    
    @staticmethod
    def format_success(data: Any) -> Dict[str, Any]:
        """
        Format successful response in MCP format
        
        Args:
            data: Response data (dict, string, or other)
            
        Returns:
            MCP-formatted success response with content array and isError: False
        """
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            # Remove 'success' flag if present
            clean_data = {k: v for k, v in data.items() if k != 'success'}
            text = json.dumps(clean_data, indent=2)
        else:
            text = str(data)
        
        # Clean Unicode special characters
        text = MCPFormatter.clean_text(text)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": text
                }
            ],
            "isError": False
        }
    
    @staticmethod
    def format_image_response(image_data: str, mime_type: str = "image/png") -> Dict[str, Any]:
        """
        Format image response in MCP format for AI vision analysis
        
        Args:
            image_data: Base64-encoded image data
            mime_type: MIME type of the image (default: image/png)
            
        Returns:
            MCP-formatted response with image content for AI vision models
        """
        return {
            "content": [
                {
                    "type": "image",
                    "data": image_data,
                    "mimeType": mime_type
                }
            ],
            "isError": False
        }
    
    @staticmethod
    def format_error(error_msg: str, category: ErrorCategory = ErrorCategory.UNKNOWN) -> Dict[str, Any]:
        """
        Format error response in MCP format
        
        Args:
            error_msg: Error message
            category: Error category for better error handling
            
        Returns:
            MCP-formatted error response with content array and isError: True
        """
        # Clean Unicode special characters from error message
        error_msg = MCPFormatter.clean_text(error_msg)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error [{category.value}]: {error_msg}"
                }
            ],
            "isError": True,
            "errorCategory": category.value
        }
    
    @staticmethod
    def format_api_response(api_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert backend API response to MCP format
        
        Automatically categorizes errors based on response fields.
        
        Args:
            api_response: Raw API response from backend
            
        Returns:
            MCP-formatted response
        """
        success = api_response.get('success', False)
        
        if success:
            return MCPFormatter.format_success(api_response)
        else:
            # Categorize error
            error_msg = api_response.get('error', 'Operation failed')
            
            # Determine error category from response
            if api_response.get('timeout'):
                category = ErrorCategory.TIMEOUT
            elif api_response.get('network_error'):
                category = ErrorCategory.NETWORK
            elif api_response.get('status_code') == 404:
                category = ErrorCategory.NOT_FOUND
            elif api_response.get('status_code') in [401, 403]:
                category = ErrorCategory.UNAUTHORIZED
            elif api_response.get('status_code'):
                category = ErrorCategory.BACKEND
            else:
                category = ErrorCategory.UNKNOWN
            
            return MCPFormatter.format_error(error_msg, category)
    
    @staticmethod
    def format_validation_error(field: str, message: str) -> Dict[str, Any]:
        """
        Format validation error for invalid inputs
        
        Args:
            field: Field that failed validation
            message: Validation error message
            
        Returns:
            MCP-formatted validation error
        """
        error_msg = f"Validation failed for '{field}': {message}"
        return MCPFormatter.format_error(error_msg, ErrorCategory.VALIDATION)

