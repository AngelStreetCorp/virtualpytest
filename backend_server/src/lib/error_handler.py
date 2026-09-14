"""
Error Handler Utilities

Standardized error handling for routes.
"""

from flask import jsonify
import logging

logger = logging.getLogger(__name__)


def handle_error(exception: Exception, message: str = "An error occurred", status_code: int = 500):
    """
    Handle errors with standardized response format.
    
    Args:
        exception: The exception that occurred
        message: User-friendly error message
        status_code: HTTP status code to return
    
    Returns:
        Tuple of (response, status_code)
    """
    error_details = str(exception)
    logger.error(f"{message}: {error_details}")
    
    return jsonify({
        "error": message,
        "details": error_details
    }), status_code

