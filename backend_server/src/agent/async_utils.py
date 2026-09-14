"""
Async Utilities for Flask Integration

Provides helpers to run async code in synchronous Flask route handlers.
"""

import asyncio
import threading
from typing import Any, Coroutine
from functools import wraps

# Global event loop for async operations
_loop = None
_loop_thread = None
_loop_lock = threading.Lock()


def get_or_create_event_loop():
    """Get or create a background event loop for async operations"""
    global _loop, _loop_thread
    
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            
            def run_loop():
                asyncio.set_event_loop(_loop)
                _loop.run_forever()
            
            _loop_thread = threading.Thread(target=run_loop, daemon=True)
            _loop_thread.start()
    
    return _loop


def run_async(coro: Coroutine) -> Any:
    """
    Run async coroutine in Flask route handler
    
    Args:
        coro: Async coroutine to execute
        
    Returns:
        Result of the coroutine
    """
    loop = get_or_create_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)  # 30 second timeout

