"\"\"\"Reusable decorators for backend_host routes.\"\"\""

import functools
import traceback
from typing import Optional

from flask import jsonify


def route_exception_handler(error_prefix: Optional[str] = None):
    """
    Decorator that logs exceptions and returns a standardized 500 response.

    Args:
        error_prefix: optional format string that receives keyword `e` holding the exception message.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                route_id = f"{func.__module__}:{func.__name__}"
                print(f"[@route:{route_id}] Error: {exc}", flush=True)
                traceback.print_exc()
                message = error_prefix.format(e=str(exc)) if error_prefix else str(exc)
                return jsonify({'success': False, 'error': message}), 500

        return wrapper

    return decorator
