"""
Authentication Utilities

Provides API key authentication for backend_host routes.
"""

import os
from flask import request, jsonify

def validate_api_key() -> tuple[bool, dict]:
    """
    Validate API key from request headers.
    
    Returns:
        Tuple of (is_valid, error_response)
        - If valid: (True, None)
        - If invalid: (False, error_dict)
    """
    # Get API key from header
    provided_key = request.headers.get('X-API-Key')
    expected_key = os.getenv('API_KEY')
    
    # Check if API_KEY is configured
    if not expected_key:
        print("[@auth_utils] WARNING: API_KEY not configured in environment")
        return False, {
            'error': 'Server configuration error',
            'message': 'API authentication not configured'
        }
    
    # Check if API key was provided
    if not provided_key:
        return False, {
            'error': 'Authentication required',
            'message': 'X-API-Key header is required'
        }
    
    # Validate API key
    if provided_key != expected_key:
        return False, {
            'error': 'Invalid API key',
            'message': 'Authentication failed'
        }
    
    # Valid API key
    return True, None


def generate_api_key() -> str:
    """
    Generate a secure random API key.
    
    Returns:
        Random API key string (URL-safe)
    """
    import secrets
    return secrets.token_urlsafe(32)


if __name__ == '__main__':
    # Generate a new API key for configuration
    print("Generated API Key:")
    print(generate_api_key())
    print("\nAdd this to your .env file:")
    print(f"API_KEY={generate_api_key()}")

